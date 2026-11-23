"""Two-tier agent cache — disk + in-memory — backed by ArtifactStore."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
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


class AgentCache:
    """
    Two-tier cache for loaded agents.

    Tier 1 (in-memory): parsed specs keyed by agent and bundle location.
    Tier 2 (disk): immutable version directories under cache_dir/<agent_id>/.
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
    ) -> None:
        self._artifact_store = artifact_store
        self._cache_dir = cache_dir
        self._clock = clock
        self._grace_age = grace_age
        self._retained_versions = retained_versions
        self._specs: dict[tuple[str, str], AgentSpec] = {}

    def _cache_path(self, agent_id: str) -> Path:
        """Return a direct child of the cache root for an agent id."""
        component = os.path.basename(agent_id)
        if (
            not component
            or component in {".", ".."}
            or component.casefold() == ".staging"
            or component != agent_id
            or "\\" in component
            or "\x00" in component
        ):
            raise ValueError(f"unsafe agent id for cache path: {agent_id!r}")
        cache_root = self._cache_dir.resolve(strict=False)
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

    def _lock(self, agent_id: str) -> FileLock:
        self._cache_path(agent_id)
        path = self._staging_root() / (hashlib.sha256(agent_id.encode()).hexdigest() + ".lock")
        if path.resolve(strict=False) != path:
            raise ValueError(f"unsafe cache lock: {path}")
        return FileLock(path)

    def _quarantine(self, path: Path) -> None:
        with self._staging_dir() as staging, contextlib.suppress(FileNotFoundError):
            path.rename(staging / "discarded")

    def _prepare_parent(self, agent_id: str) -> None:
        parent = self._cache_path(agent_id)
        if (parent / "config.yaml").exists() or (parent / _LOCATION_MARKER).exists():
            self._quarantine(parent)
        parent.mkdir(parents=True, exist_ok=True)

    def _touch_and_collect(self, agent_id: str, workdir: Path) -> None:
        now = self._clock()
        os.utime(workdir, (now, now))
        entries = []
        for entry in self._cache_path(agent_id).iterdir():
            try:
                if not entry.is_symlink() and entry.is_dir():
                    entries.append((entry.stat().st_mtime, entry))
            except FileNotFoundError:
                continue
        entries.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        for modified, entry in entries[self._retained_versions :]:
            if entry == workdir or now - modified <= self._grace_age:
                continue
            # A workdir held longer than the grace age can still be reclaimed.
            self._quarantine(entry)
            for key in list(self._specs):
                if key[0] == agent_id and self._version_path(*key) == entry:
                    self._specs.pop(key, None)

    def load(
        self, agent_id: str, bundle_location: str, *, expand_env: bool = False
    ) -> LoadedAgent:
        """Load the requested version, keeping its spec and workdir together."""
        workdir = self._version_path(agent_id, bundle_location)
        key = (agent_id, bundle_location)
        cached = self._specs.get(key)
        if cached is not None:
            with self._lock(agent_id):
                if workdir.is_dir() and _published_location(workdir) == bundle_location:
                    self._touch_and_collect(agent_id, workdir)
                    return LoadedAgent(spec=cached, workdir=workdir)
            self._specs.pop(key, None)
        if workdir.is_dir():
            try:
                with self._lock(agent_id):
                    if workdir.is_dir():
                        os.utime(workdir, (self._clock(), self._clock()))
                if _published_location(workdir) != bundle_location:
                    raise ValueError("bundle location marker mismatch")
                inode = workdir.stat().st_ino
                spec = load_spec(workdir, expand_env=expand_env, prune_invalid_sub_agents=True)
                with self._lock(agent_id):
                    if (
                        workdir.is_dir()
                        and workdir.stat().st_ino == inode
                        and _published_location(workdir) == bundle_location
                    ):
                        self._touch_and_collect(agent_id, workdir)
                        self._specs[key] = spec
                        return LoadedAgent(spec=spec, workdir=workdir)
            except Exception:
                return self._recover_disk_entry(agent_id, bundle_location, expand_env=expand_env)
        bundle = self._artifact_store.get(bundle_location)
        return self._extract_and_cache(agent_id, bundle_location, bundle, expand_env=expand_env)

    def _recover_disk_entry(
        self, agent_id: str, bundle_location: str, *, expand_env: bool
    ) -> LoadedAgent:
        workdir = self._version_path(agent_id, bundle_location)
        with self._lock(agent_id):
            try:
                if _published_location(workdir) != bundle_location:
                    raise ValueError("bundle location marker mismatch")
                spec = load_spec(workdir, expand_env=expand_env, prune_invalid_sub_agents=True)
            except Exception as exc:
                _logger.warning(
                    "Rebuilding unreadable agent cache entry",
                    extra=debug_event(
                        "agent_cache_rebuild_started",
                        agent_id=agent_id,
                        exception_type=type(exc).__name__,
                    ),
                )
                try:
                    bundle = self._artifact_store.get(bundle_location)
                    if workdir.exists():
                        self._quarantine(workdir)
                    loaded = self._publish(
                        agent_id, bundle_location, bundle, expand_env=expand_env
                    )
                except Exception as failure:
                    _logger.warning(
                        "Agent cache rebuild failed",
                        extra=debug_event(
                            "agent_cache_rebuild_failed",
                            agent_id=agent_id,
                            exception_type=type(failure).__name__,
                        ),
                    )
                    raise
                _logger.info(
                    "Rebuilt agent cache entry",
                    extra=debug_event("agent_cache_rebuild_completed", agent_id=agent_id),
                )
                return loaded
            self._touch_and_collect(agent_id, workdir)
            self._specs[(agent_id, bundle_location)] = spec
            return LoadedAgent(spec=spec, workdir=workdir)

    def replace(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes, *, expand_env: bool = False
    ) -> LoadedAgent:
        """Publish a version while leaving older workdirs available to readers."""
        return self._extract_and_cache(
            agent_id, bundle_location, bundle_bytes, expand_env=expand_env
        )

    def evict(self, agent_id: str) -> None:
        """Forget memory entries while leaving disk versions for active readers."""
        self._cache_path(agent_id)
        for key in list(self._specs):
            if key[0] == agent_id:
                self._specs.pop(key, None)

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

    def _publish(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes, *, expand_env: bool
    ) -> LoadedAgent:
        with self._staging_dir() as staging:
            load_spec(
                bundle_bytes, dest=staging, expand_env=expand_env, prune_invalid_sub_agents=True
            )
            (staging / _LOCATION_MARKER).write_text(bundle_location, encoding="utf-8")
            self._prepare_parent(agent_id)
            workdir = self._version_path(agent_id, bundle_location)
            staging.rename(workdir)
            spec = load_spec(workdir, expand_env=expand_env, prune_invalid_sub_agents=True)
            self._touch_and_collect(agent_id, workdir)
            self._specs[(agent_id, bundle_location)] = spec
            return LoadedAgent(spec=spec, workdir=workdir)

    def _extract_and_cache(
        self, agent_id: str, bundle_location: str, bundle_bytes: bytes, *, expand_env: bool = False
    ) -> LoadedAgent:
        self._version_path(agent_id, bundle_location)
        with self._staging_dir() as staging:
            load_spec(
                bundle_bytes, dest=staging, expand_env=expand_env, prune_invalid_sub_agents=True
            )
            (staging / _LOCATION_MARKER).write_text(bundle_location, encoding="utf-8")
            with self._lock(agent_id):
                self._prepare_parent(agent_id)
                workdir = self._version_path(agent_id, bundle_location)
                if workdir.exists():
                    try:
                        if _published_location(workdir) != bundle_location:
                            raise ValueError("bundle location marker mismatch")
                        spec = load_spec(
                            workdir, expand_env=expand_env, prune_invalid_sub_agents=True
                        )
                    except Exception:
                        self._quarantine(workdir)
                    else:
                        self._touch_and_collect(agent_id, workdir)
                        self._specs[(agent_id, bundle_location)] = spec
                        return LoadedAgent(spec=spec, workdir=workdir)
                staging.rename(workdir)
                spec = load_spec(workdir, expand_env=expand_env, prune_invalid_sub_agents=True)
                self._touch_and_collect(agent_id, workdir)
                self._specs[(agent_id, bundle_location)] = spec
                return LoadedAgent(spec=spec, workdir=workdir)
