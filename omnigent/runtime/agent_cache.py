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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock, Timeout

try:
    import fcntl
except ImportError:  # Windows falls back to age and retention limits.
    fcntl = None

from omnigent.debug_logging import debug_event
from omnigent.entities import LoadedAgent
from omnigent.spec import AgentSpec
from omnigent.spec import load as load_spec
from omnigent.stores.artifact_store import ArtifactStore

_logger = logging.getLogger(__name__)

# Written into each published directory: the bundle location it was extracted from.
_LOCATION_MARKER = ".omnigent-bundle-location"
_MAX_MEMORY_VERSIONS = 128
_MAX_LEASED_ENTRIES = 32
_lease_support_lock = threading.RLock()
_lease_support_failed = False


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


class _Lease:
    def __init__(self, fd: int) -> None:
        self.fd = fd

    def __del__(self) -> None:
        os.close(self.fd)

    def __deepcopy__(self, memo: dict[int, object]) -> _Lease:
        return self

    def __reduce__(self):
        return (type(None), ())


@dataclass(frozen=True)
class _Entry:
    spec: AgentSpec
    workdir: Path
    lease: _Lease | None
    last_hit: float = 0

    def loaded(self) -> LoadedAgent:
        return LoadedAgent(spec=self.spec, workdir=self.workdir, _lease=self.lease)


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
        grace_age: float = 3600,
        retained_versions: int = 3,
        sweep_ttl: float = 86400,
    ) -> None:
        self._artifact_store = artifact_store
        self._cache_dir = cache_dir
        self._clock = clock
        self._grace_age = grace_age
        self._retained_versions = retained_versions
        self._specs: dict[tuple[str, str], _Entry] = {}
        self._memory_lock = threading.Lock()
        self._sweep_ttl = sweep_ttl
        self._last_sweep = float("-inf")
        self._schedule_clock = time.monotonic if clock is time.time else clock
        self._sweep_thread: threading.Thread | None = None
        self._pending_evictions: set[str] = set()

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

    def _lease_path(self, workdir: Path) -> Path:
        return workdir.with_name(workdir.name + ".lease")

    def _acquire_lease(self, workdir: Path, *, exclusive: bool = False) -> int | None:
        with _lease_support_lock:
            if fcntl is None:
                self._warn_unavailable_lease()
                return None
            try:
                fd = os.open(self._lease_path(workdir), os.O_CREAT | os.O_RDWR, 0o600)
            except OSError as exc:
                if exc.errno in (errno.EMFILE, errno.ENFILE):
                    return None
                raise
            try:
                mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(fd)
                if exc.errno in (errno.EOPNOTSUPP, errno.ENOLCK, errno.EINVAL):
                    self._warn_unavailable_lease()
                    return None
                if exc.errno in (errno.EMFILE, errno.ENFILE):
                    return None
                raise
            except BaseException:
                os.close(fd)
                raise
            return fd

    def _warn_unavailable_lease(self) -> None:
        global _lease_support_failed
        with _lease_support_lock:
            if not _lease_support_failed:
                _logger.warning("Agent cache leases unavailable; version deletion disabled")
                _lease_support_failed = True

    def _remember(self, key: tuple[str, str], entry: _Entry) -> None:
        with self._memory_lock:
            self._specs.pop(key, None)
            self._specs[key] = entry
            leased = [key for key, value in self._specs.items() if value.lease is not None]
            for old_key in leased[:-_MAX_LEASED_ENTRIES]:
                old = self._specs[old_key]
                self._specs[old_key] = _Entry(old.spec, old.workdir, None, old.last_hit)
            while len(self._specs) > _MAX_MEMORY_VERSIONS:
                self._specs.pop(next(iter(self._specs)), None)

    def _quarantine(self, path: Path) -> None:
        with self._staging_dir() as staging, contextlib.suppress(FileNotFoundError):
            path.rename(staging / "discarded")

    def _prepare_parent(self, agent_id: str) -> None:
        # Legacy directories belong to older revisions and are never touched here.
        self._cache_path(agent_id).mkdir(parents=True, exist_ok=True)

    def _collect(self, agent_id: str, *, ttl: float, retain: int) -> None:
        if _lease_support_failed:
            return
        try:
            with self._lock(agent_id).acquire(timeout=0):
                parent = self._cache_path(agent_id)
                if not parent.is_dir():
                    return
                entries = []
                for entry in parent.iterdir():
                    try:
                        if not entry.is_symlink() and entry.is_dir():
                            marker = entry / _LOCATION_MARKER
                            published = (
                                marker.stat().st_mtime
                                if marker.exists()
                                else entry.stat().st_mtime
                            )
                            entries.append((published, entry))
                    except FileNotFoundError:
                        continue
                entries.sort(key=lambda item: (item[0], item[1].name), reverse=True)
                for published, entry in entries[retain:]:
                    if self._clock() - published <= ttl:
                        continue
                    try:
                        fd = self._acquire_lease(entry, exclusive=True)
                        try:
                            with _lease_support_lock:
                                if fd is not None and not _lease_support_failed:
                                    self._quarantine(entry)
                                    self._lease_path(entry).unlink(missing_ok=True)
                        finally:
                            if fd is not None:
                                os.close(fd)
                    except (BlockingIOError, Timeout, FileNotFoundError):
                        continue
                for lease in parent.glob("*.lease"):
                    workdir = lease.with_name(lease.name[:-6])
                    if workdir.exists():
                        continue
                    try:
                        fd = self._acquire_lease(workdir, exclusive=True)
                        try:
                            with _lease_support_lock:
                                if (
                                    fd is not None
                                    and not _lease_support_failed
                                    and not workdir.exists()
                                ):
                                    lease.unlink(missing_ok=True)
                        finally:
                            if fd is not None:
                                os.close(fd)
                    except (BlockingIOError, Timeout, FileNotFoundError):
                        continue
                with contextlib.suppress(OSError):
                    parent.rmdir()
        except Timeout:
            pass

    def _after_publish(self, agent_id: str) -> None:
        self._collect(agent_id, ttl=self._grace_age, retain=self._retained_versions)
        self._schedule_sweep()

    def _schedule_sweep(self) -> None:
        now = self._schedule_clock()
        with self._memory_lock:
            if now - self._last_sweep < self._grace_age / 4:
                return
            if self._sweep_thread is not None and self._sweep_thread.is_alive():
                return
            self._last_sweep = now
            self._sweep_thread = threading.Thread(target=self._run_sweep, daemon=True)
            self._sweep_thread.start()

    def _run_sweep(self) -> None:
        try:
            self._sweep()
        except Exception:
            _logger.exception("Agent cache sweep failed")

    def _sweep(self) -> None:
        now = self._schedule_clock()
        with self._memory_lock:
            for key, entry in list(self._specs.items()):
                if entry.lease is not None and now - entry.last_hit >= self._grace_age:
                    self._specs[key] = _Entry(entry.spec, entry.workdir, None, entry.last_hit)
            evictions = self._pending_evictions.copy()
            self._pending_evictions.clear()
        for agent_id in evictions:
            self._collect(agent_id, ttl=self._grace_age, retain=0)
        root = self._cache_dir / ".versions"
        if root.is_dir():
            for parent in root.iterdir():
                if parent.is_dir() and not parent.is_symlink() and not parent.name.startswith("."):
                    self._collect(parent.name, ttl=self._sweep_ttl, retain=0)

    def load(
        self, agent_id: str, bundle_location: str, *, expand_env: bool = False
    ) -> LoadedAgent:
        self._version_path(agent_id, bundle_location)
        self._schedule_sweep()
        key = (agent_id, bundle_location)
        with self._memory_lock:
            cached = self._specs.get(key)
        if cached is not None:
            if cached.lease is None:
                try:
                    fd = self._acquire_lease(cached.workdir)
                except (BlockingIOError, FileNotFoundError):
                    fd = None
                if fd is not None:
                    candidate = _Entry(
                        cached.spec, cached.workdir, _Lease(fd), self._schedule_clock()
                    )
                    if (
                        candidate.workdir.is_dir()
                        and _published_location(candidate.workdir) == bundle_location
                    ):
                        with self._memory_lock:
                            if self._specs.get(key) is cached:
                                self._specs[key] = candidate
                        return candidate.loaded()
            elif cached.workdir.is_dir():
                with self._memory_lock:
                    if self._specs.get(key) is cached:
                        self._specs[key] = _Entry(
                            cached.spec, cached.workdir, cached.lease, self._schedule_clock()
                        )
                return cached.loaded()
        return self._load_or_publish(agent_id, bundle_location, None, expand_env=expand_env)

    def replace(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes, *, expand_env: bool = False
    ) -> LoadedAgent:
        return self._extract_and_cache(
            agent_id, bundle_location, bundle_bytes, expand_env=expand_env
        )

    def evict(self, agent_id: str) -> None:
        self._cache_path(agent_id)
        with self._memory_lock:
            for key in list(self._specs):
                if key[0] == agent_id:
                    self._specs.pop(key, None)
            self._pending_evictions.add(agent_id)
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
        published = False
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
            with self._lock(agent_id):
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
                fd = None
                for candidate in candidates:
                    candidate_fd = self._acquire_lease(candidate)
                    try:
                        if _published_location(candidate) != bundle_location:
                            raise ValueError("bundle location marker mismatch")
                        spec = load_spec(
                            candidate, expand_env=expand_env, prune_invalid_sub_agents=True
                        )
                    except Exception as exc:
                        if candidate_fd is not None:
                            os.close(candidate_fd)
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
                    workdir, fd = candidate, candidate_fd
                    break
                if spec is None:
                    if workdir.exists():
                        with self._memory_lock:
                            self._specs.pop(key, None)
                        try:
                            exclusive = self._acquire_lease(workdir, exclusive=True)
                        except BlockingIOError:
                            exclusive = None
                        removed = False
                        if exclusive is not None:
                            try:
                                with _lease_support_lock:
                                    if not _lease_support_failed:
                                        self._quarantine(workdir)
                                        self._lease_path(workdir).unlink(missing_ok=True)
                                        removed = True
                            finally:
                                os.close(exclusive)
                        if not removed:
                            workdir = workdir.with_name(workdir.name + "." + uuid.uuid4().hex)
                    fd = self._acquire_lease(workdir)
            try:
                if spec is None:
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
                        staging.rename(workdir)
                        spec = load_spec(
                            workdir, expand_env=expand_env, prune_invalid_sub_agents=True
                        )
                        published = True
                        if rebuilding:
                            _logger.info(
                                "Rebuilt agent cache entry",
                                extra=debug_event(
                                    "agent_cache_rebuild_completed", agent_id=agent_id
                                ),
                            )
                lease = _Lease(fd) if fd is not None else None
                fd = None
                entry = _Entry(spec, workdir, lease, self._schedule_clock())
                self._remember(key, entry)
            finally:
                if fd is not None:
                    os.close(fd)
                    with self._lock(agent_id):
                        if not workdir.exists():
                            try:
                                exclusive = self._acquire_lease(workdir, exclusive=True)
                            except BlockingIOError:
                                exclusive = None
                            if exclusive is not None:
                                try:
                                    self._lease_path(workdir).unlink(missing_ok=True)
                                finally:
                                    os.close(exclusive)
        if published:
            self._after_publish(agent_id)
        return entry.loaded()

    def _extract_and_cache(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes, *, expand_env: bool = False
    ) -> LoadedAgent:
        return self._load_or_publish(
            agent_id, bundle_location, bundle_bytes, expand_env=expand_env
        )
