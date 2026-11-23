"""Two-tier agent cache — disk + in-memory — backed by ArtifactStore."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock

from omnigent.debug_logging import debug_event
from omnigent.entities import LoadedAgent
from omnigent.spec import AgentSpec
from omnigent.spec import load as load_spec
from omnigent.stores.artifact_store import ArtifactStore

_logger = logging.getLogger(__name__)

# Written into each published directory: the bundle location it was extracted from.
_LOCATION_MARKER = ".omnigent-bundle-location"
_MAX_MEMORY_VERSIONS = 128
_holds: weakref.WeakSet[_Hold] = weakref.WeakSet()
_holds_lock = threading.Lock()
_TOUCH_INTERVAL = 3600


def _cleanup_staging_dir(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass  # Successful publication moved this staging directory into the cache.
    except OSError as exc:
        _logger.warning("Could not clean agent cache staging directory %s: %s", path, exc)


def _published_location(workdir: Path) -> str | None:
    """Return the bundle location a cache directory holds, or ``None`` if unknown."""
    try:
        return (workdir / _LOCATION_MARKER).read_text(encoding="utf-8")
    except OSError:
        return None


class _Hold:
    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        with _holds_lock:
            _holds.add(self)

    def __deepcopy__(self, memo: dict[int, object]) -> _Hold:
        return self

    def __reduce__(self):
        return (type(None), ())


@dataclass(frozen=True)
class _Entry:
    spec: AgentSpec
    workdir: Path
    hold: _Hold

    def loaded(self) -> LoadedAgent:
        return LoadedAgent(spec=self.spec, workdir=self.workdir, _hold=self.hold)


class AgentCache:
    """
    Two-tier cache for loaded agents.

    Tier 1 (in-memory): parsed specs keyed by agent and bundle location.
    Tier 2 (disk): immutable version directories under cache_dir/.versions/<agent_id>/.
    Source of truth: ArtifactStore (tarball bytes).

    Bundle locations identify separate entries in both tiers.

    On cache miss the bundle is downloaded from the ArtifactStore,
    extracted to disk, parsed, validated, and stored in both tiers.

    This is an **execution** load path, so it loads with
    ``prune_invalid_sub_agents=True``: a sub-agent that fails
    validation here means this server is older than whatever produced
    the bundle and can't run that sub-agent (version skew), so it is
    dropped (with a WARNING) and the parent agent still dispatches.
    Authoring/upload validation stays strict elsewhere
    (:func:`omnigent.server.bundles.validate_agent_bundle`). See
    :func:`omnigent.spec.load`.
    """

    def __init__(
        self,
        artifact_store: ArtifactStore,
        cache_dir: Path,
        *,
        clock: Callable[[], float] = time.time,
        grace_age: float = 7 * 86400,
        retained_versions: int = 3,
        sweep_ttl: float = 7 * 86400,
        trash_grace: float = 3600,
        current_location: Callable[[str], set[str]] | None = None,
    ) -> None:
        self._artifact_store = artifact_store
        self._cache_dir = cache_dir
        self._clock = clock
        self._grace_age = grace_age
        self._retained_versions = retained_versions
        self._specs: dict[tuple[str, str], _Entry] = {}
        self._memory_lock = threading.Lock()
        self._sweep_ttl = sweep_ttl
        self._trash_grace = trash_grace
        self._last_sweep = float("-inf")
        self._schedule_clock = time.monotonic if clock is time.time else clock
        self._sweep_thread: threading.Thread | None = None
        self._current_location = current_location
        self._last_touches: dict[Path, float] = {}
        self._touch_warned = False
        self._heartbeat_started = False

    def _cache_path(self, agent_id: str) -> Path:
        """Return a direct child of the cache root for an agent id."""
        component = os.path.basename(agent_id)
        if (
            not component
            or component in {".", ".."}
            or component.startswith(".")
            or component != agent_id
            or "\\" in component
            or "\x00" in component
        ):
            raise ValueError(f"unsafe agent id for cache path: {agent_id!r}")
        cache_root = self._cache_dir.resolve(strict=False) / ".versions"
        if cache_root.resolve(strict=False) != cache_root:
            raise ValueError("unsafe agent id: redirected versions root")
        normalized_path = os.path.normpath(cache_root / component)
        if not normalized_path.startswith(os.path.join(cache_root, "")):
            raise ValueError(f"unsafe agent id for cache path: {agent_id!r}")
        path = Path(normalized_path)
        if path.parent != cache_root or path.resolve(strict=False) != path:
            raise ValueError(f"unsafe agent id for cache path: {agent_id!r}")
        return path

    def _version_path(self, agent_id: str, location: str) -> Path:
        parent = self._cache_path(agent_id)
        path = parent / hashlib.sha256(location.encode("utf-8")).hexdigest()
        if path.resolve(strict=False) != path:
            raise ValueError(f"unsafe cache version path: {path}")
        return path

    def _lock(self, agent_id: str, version: str = "gc") -> FileLock:
        self._cache_path(agent_id)
        name = hashlib.sha256(f"{agent_id}/{version}".encode()).hexdigest()
        return FileLock(self._staging_root() / (name + ".lock"), timeout=30)

    def _remember(self, key: tuple[str, str], entry: _Entry) -> None:
        with self._memory_lock:
            self._specs.pop(key, None)
            self._specs[key] = entry
            while len(self._specs) > _MAX_MEMORY_VERSIONS:
                self._specs.pop(next(iter(self._specs)), None)

    @staticmethod
    def _marker(workdir: Path) -> Path:
        return workdir.with_name(workdir.name + ".last_used")

    def _touch(self, workdir: Path, *, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._last_touches.get(workdir, float("-inf")) < _TOUCH_INTERVAL:
            return
        self._last_touches[workdir] = now
        try:
            marker = self._marker(workdir)
            marker.touch(exist_ok=True)
            os.utime(marker, (now, now))
        except OSError as exc:
            if not self._touch_warned:
                self._touch_warned = True
                _logger.warning("Could not touch agent cache marker: %s", exc)

    def _prepare_parent(self, agent_id: str) -> None:
        self._cache_path(agent_id).mkdir(parents=True, exist_ok=True)

    def _collect(self, agent_id: str) -> None:
        parent = self._cache_path(agent_id)

        def protected_paths() -> set[Path]:
            entries = []
            try:
                for path in parent.iterdir():
                    try:
                        if not path.is_symlink() and path.is_dir():
                            marker = path / _LOCATION_MARKER
                            published = (
                                marker.stat().st_mtime if marker.exists() else path.stat().st_mtime
                            )
                            entries.append((published, path))
                    except FileNotFoundError:
                        continue
            except FileNotFoundError:
                return set()
            entries.sort(key=lambda item: (item[0], item[1].name), reverse=True)
            current = None
            if self._current_location is not None:
                try:
                    current = self._current_location(agent_id)
                except Exception:
                    _logger.exception("Could not resolve current agent cache location")
            protected = (
                {path for _, path in entries[: self._retained_versions]}
                if current != set()
                else set()
            )
            if current is not None:
                protected.update(
                    path for _, path in entries if _published_location(path) in current
                )
            elif entries:
                protected.add(entries[0][1])
            return protected

        def eligible(entry: Path, trashed: Path | None = None) -> bool:
            with _holds_lock:
                if any(hold.workdir == entry for hold in _holds):
                    return False
            try:
                marker = self._marker(entry)
                last_used = (
                    marker.stat().st_mtime
                    if marker.exists()
                    else (trashed or entry).stat().st_mtime
                )
                return self._clock() - last_used > self._sweep_ttl
            except FileNotFoundError:
                return False

        protected = protected_paths()
        try:
            candidates = list(parent.iterdir())
        except FileNotFoundError:
            return
        for entry in candidates:
            if (
                entry in protected
                or entry.is_symlink()
                or not entry.is_dir()
                or not eligible(entry)
            ):
                continue
            try:
                trash = self._cache_dir / ".versions" / ".trash"
                trash.mkdir(parents=True, exist_ok=True)
                destination = trash / f"{int(self._clock() * 1_000_000_000)}-{uuid.uuid4().hex}"
                entry.rename(destination)
                # A touch before this check is visible; a later loader sees the
                # missing directory and republishes before returning it.
                # A collector stalled beyond trash grace may lose the restore; a
                # loader seeing the missing directory republishes the version.
                # Rank the trashed candidate without exposing it to loaders.
                if self._candidate_protected(agent_id, entry, destination) or not eligible(
                    entry, destination
                ):
                    try:
                        self._prepare_parent(agent_id)
                        destination.rename(entry)
                    except OSError as exc:
                        if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                            raise
                        shutil.rmtree(destination)
                    continue
                self._marker(entry).unlink(missing_ok=True)
                shutil.rmtree(destination)
            except FileNotFoundError:
                continue
            except OSError:
                _logger.exception("Could not collect agent cache version %s", entry)
        with contextlib.suppress(OSError):
            parent.rmdir()

    def _candidate_protected(self, agent_id: str, entry: Path, destination: Path) -> bool:
        try:
            current = self._current_location(agent_id) if self._current_location else None
        except Exception:
            _logger.exception("Could not resolve current agent cache location")
            current = None
        if current is not None and _published_location(destination) in current:
            return True
        if current == set():
            return False
        try:

            def published(path: Path) -> float:
                marker = path / _LOCATION_MARKER
                return marker.stat().st_mtime if marker.exists() else path.stat().st_mtime

            candidate_time = published(destination)
            siblings = [
                path for path in entry.parent.iterdir() if path.is_dir() and not path.is_symlink()
            ]
            newer = sum(
                (published(path), path.name) > (candidate_time, entry.name) for path in siblings
            )
            return newer < max(self._retained_versions, 1 if current is None else 0)
        except FileNotFoundError:
            return True

    def _schedule_sweep(self) -> None:
        now = self._schedule_clock()
        with self._memory_lock:
            if now - self._last_sweep < min(_TOUCH_INTERVAL, self._grace_age / 4):
                return
            if self._sweep_thread is not None and self._sweep_thread.is_alive():
                return
            thread = threading.Thread(target=self._run_sweep, daemon=True)
            try:
                thread.start()
            except Exception:
                _logger.exception("Could not start agent cache sweep")
                return
            self._sweep_thread = thread
            self._last_sweep = now
            if not self._heartbeat_started:
                try:
                    self._start_heartbeat(weakref.ref(self))
                    self._heartbeat_started = True
                except Exception:
                    _logger.exception("Could not start agent cache heartbeat")

    @staticmethod
    def _start_heartbeat(cache_ref: weakref.ReferenceType[AgentCache]) -> None:
        cache = cache_ref()
        if cache is None:
            return
        root = cache._cache_dir.resolve(strict=False) / ".versions"
        clock = cache._clock

        def schedule() -> None:
            timer = threading.Timer(_TOUCH_INTERVAL, heartbeat)
            timer.daemon = True
            timer.start()

        def heartbeat() -> None:
            with _holds_lock:
                held = [hold.workdir for hold in _holds if hold.workdir.parent.parent == root]
            if not held and cache_ref() is None:
                return
            schedule()
            for workdir in held:
                try:
                    marker = AgentCache._marker(workdir)
                    marker.touch(exist_ok=True)
                    now = clock()
                    os.utime(marker, (now, now))
                except OSError:
                    _logger.warning("Could not touch agent cache marker", exc_info=True)

        schedule()

    def _run_sweep(self) -> None:
        try:
            self._sweep()
        except Exception:
            _logger.exception("Agent cache sweep failed")

    def _sweep(self) -> None:
        root = self._cache_dir / ".versions"
        if not root.is_dir():
            return
        trash = root / ".trash"
        if trash.is_dir():
            for entry in trash.iterdir():
                try:
                    timestamp, separator, suffix = entry.name.partition("-")
                    if separator and suffix and timestamp.isascii() and timestamp.isdigit():
                        renamed_at = int(timestamp) / 1_000_000_000
                    else:
                        renamed_at = entry.lstat().st_mtime
                    if self._clock() - renamed_at <= self._trash_grace:
                        continue
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
        for parent in root.iterdir():
            if parent.is_dir() and not parent.is_symlink() and not parent.name.startswith("."):
                for marker in parent.glob("*.last_used"):
                    try:
                        version = marker.with_name(marker.name.removesuffix(".last_used"))
                        if (
                            not version.exists()
                            and self._clock() - marker.stat().st_mtime > self._sweep_ttl
                        ):
                            marker.unlink(missing_ok=True)
                    except FileNotFoundError:
                        pass
                self._collect(parent.name)

    def load(
        self, agent_id: str, bundle_location: str, *, expand_env: bool = False
    ) -> LoadedAgent:
        self._version_path(agent_id, bundle_location)
        self._schedule_sweep()
        key = (agent_id, bundle_location)
        with self._memory_lock:
            cached = self._specs.get(key)
        if cached is not None:
            self._touch(cached.workdir, force=True)
            if cached.workdir.is_dir() and _published_location(cached.workdir) == bundle_location:
                return cached.loaded()
        return self._load_or_publish(agent_id, bundle_location, None, expand_env=expand_env)

    def replace(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes, *, expand_env: bool = False
    ) -> LoadedAgent:
        self._schedule_sweep()
        return self._extract_and_cache(
            agent_id, bundle_location, bundle_bytes, expand_env=expand_env
        )

    def evict(self, agent_id: str) -> None:
        self._cache_path(agent_id)
        with self._memory_lock:
            for key in list(self._specs):
                if key[0] == agent_id:
                    self._specs.pop(key, None)
        self._schedule_sweep()

    def _staging_root(self) -> Path:
        """Return the reserved staging namespace on the cache filesystem."""
        cache_root = self._cache_dir.resolve(strict=False)
        cache_root.mkdir(parents=True, exist_ok=True)
        staging_root = cache_root / ".staging"
        if staging_root.resolve(strict=False) != staging_root:
            raise ValueError(f"unsafe staging root: {staging_root}")
        staging_root.mkdir(mode=0o700, exist_ok=True)
        return staging_root

    @contextlib.contextmanager
    def _staging_dir(self) -> Iterator[Path]:
        """Stage on the cache filesystem in a reserved, symlink-checked namespace."""
        staging_dir = Path(tempfile.mkdtemp(prefix="bundle-", dir=self._staging_root()))
        try:
            yield staging_dir
        finally:
            _cleanup_staging_dir(staging_dir)

    def _load_or_publish(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes | None, *, expand_env: bool
    ) -> LoadedAgent:
        workdir = self._version_path(agent_id, bundle_location)
        key = (agent_id, bundle_location)
        rebuilding = False
        if bundle_bytes is not None:
            with self._staging_dir() as staging:
                load_spec(
                    bundle_bytes,
                    dest=staging,
                    expand_env=expand_env,
                    prune_invalid_sub_agents=True,
                )
        with self._lock(agent_id, workdir.name):
            self._prepare_parent(agent_id)
            candidates = [
                path
                for path in workdir.parent.glob(workdir.name + "*")
                if not path.is_symlink()
                and path.is_dir()
                and (path.name == workdir.name or path.name.startswith(workdir.name + "."))
            ]

            def publish_time(path: Path) -> float:
                try:
                    return (path / _LOCATION_MARKER).stat().st_mtime
                except OSError:
                    return float("-inf")

            candidates.sort(key=lambda path: (publish_time(path), path.name), reverse=True)
            spec = None
            hold = None
            for candidate in candidates:
                candidate_hold = _Hold(candidate)
                self._touch(candidate, force=True)
                try:
                    if _published_location(candidate) != bundle_location:
                        raise ValueError("bundle location marker mismatch")
                    spec = load_spec(
                        candidate, expand_env=expand_env, prune_invalid_sub_agents=True
                    )
                except Exception as exc:
                    rebuilding = True
                    _logger.warning(
                        "Rebuilding unreadable agent cache entry",
                        extra=debug_event(
                            "agent_cache_rebuild_started",
                            agent_id=agent_id,
                            exception_type=type(exc).__name__,
                        ),
                    )
                    continue
                workdir, hold = candidate, candidate_hold
                break
            if spec is None:
                if workdir.exists():
                    workdir = workdir.with_name(workdir.name + "." + uuid.uuid4().hex)
                if bundle_bytes is None:
                    try:
                        bundle_bytes = self._artifact_store.get(bundle_location)
                    except Exception as failure:
                        if rebuilding:
                            _logger.warning(
                                "Agent cache rebuild failed",
                                extra=debug_event(
                                    "agent_cache_rebuild_failed",
                                    agent_id=agent_id,
                                    exception_type=type(failure).__name__,
                                ),
                            )
                        raise
                with self._staging_dir() as staging:
                    load_spec(
                        bundle_bytes,
                        dest=staging,
                        expand_env=expand_env,
                        prune_invalid_sub_agents=True,
                    )
                    marker = staging / _LOCATION_MARKER
                    marker.write_text(bundle_location, encoding="utf-8")
                    now = self._clock()
                    os.utime(marker, (now, now))
                    self._prepare_parent(agent_id)
                    hold = _Hold(workdir)
                    for attempt in range(3):
                        try:
                            self._prepare_parent(agent_id)
                            staging.rename(workdir)
                            break
                        except FileNotFoundError:
                            if attempt == 2:
                                raise
                        except OSError as exc:
                            if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY) or attempt == 2:
                                raise
                            workdir = workdir.with_name(workdir.name + "." + uuid.uuid4().hex)
                            hold = _Hold(workdir)
                    spec = load_spec(workdir, expand_env=expand_env, prune_invalid_sub_agents=True)
                    if rebuilding:
                        _logger.info(
                            "Rebuilt agent cache entry",
                            extra=debug_event("agent_cache_rebuild_completed", agent_id=agent_id),
                        )
            assert hold is not None
            entry = _Entry(spec, workdir, hold)
            self._remember(key, entry)
            self._touch(workdir, force=True)
        return entry.loaded()

    def _extract_and_cache(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes, *, expand_env: bool = False
    ) -> LoadedAgent:
        return self._load_or_publish(
            agent_id, bundle_location, bundle_bytes, expand_env=expand_env
        )
