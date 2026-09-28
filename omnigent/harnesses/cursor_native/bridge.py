"""Filesystem bridge + tmux injection for the cursor-native terminal harness.

The runner launches the ``cursor-agent`` TUI in a private tmux pane and records
that pane's socket + target here via :func:`write_tmux_target`. The harness
executor then delivers Omnigent web-UI messages into the *same* pane via
:func:`inject_user_message` (tmux bracketed paste + Enter) — the cursor analog
of claude-native's tmux send-keys bridge. This is what wires the web-UI chat box
to the running Cursor TUI (and, since the web UI embeds that pane, the message
shows in both surfaces).

Known limitation — one hooks/MCP slot per workspace: the usage ``stop`` hook
(``.cursor/hooks.json``) and the Omnigent MCP server (``.cursor/mcp.json``) are
project-scoped files, and each bakes ONE session's bridge dir. Two cursor-native
sessions launched in the same workspace therefore share one slot, and the last
launch wins: both TUIs' stop hooks (usage, turn-end idle, completion receipts)
and MCP tools route to the last launcher's bridge dir. cursor-agent reads these
only from the project/user/team/enterprise locations and from ``--plugin-dir``
plugins. The runner does not refuse such launches (non-isolated Trio runs rely
on them); it logs a warning naming both sessions when a launch overwrites a slot
still bound to a LIVE sibling (:func:`live_foreign_config_bridges`). Give
concurrent sessions distinct worktrees to avoid it.

Opt-in per-launch config (``OMNIGENT_CURSOR_PLUGIN_DIR=1``, see
:func:`plugin_dir_mode_enabled`): the launch instead writes a private Cursor
plugin under its own bridge dir (:func:`write_cursor_plugin` — ``mcp.json`` with
the bridge server, ``hooks/hooks.json`` with the usage stop hook) and passes it
as ``--plugin-dir``, so each session has its own hooks and MCP server and the
project ``mcp.json`` is not written. One constant, session-agnostic entry
remains in the project ``hooks.json`` (:func:`write_plugin_stop_armer`):
cursor-agent (2026.09.23 / 2026.09.26 bundles) only dispatches the ``stop``
event when the user or project hooks file declares a ``stop`` hook, although it
then runs plugin stop hooks too. The entry is a no-op and identical for every
session, so concurrent launches no longer overwrite each other.

Chat-transcript binding is NOT affected by either route: each session is pinned
to its own chat (see :mod:`omnigent.harnesses.cursor_native.forwarder`).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import click

from omnigent import native_tmux_kill
from omnigent._platform import stable_user_id
from omnigent.harnesses.cursor_native import status as cursor_native_status
from omnigent.util.json_types import JsonObject as _JsonObject

if TYPE_CHECKING:
    from omnigent.harnesses.cursor_native.main import CursorModelOption
    from omnigent.inner.terminal import TerminalInstance


#: Env var carrying the bridge dir into the harness executor process.
BRIDGE_DIR_ENV_VAR = "HARNESS_CURSOR_NATIVE_BRIDGE_DIR"

_BRIDGE_ROOT = Path(tempfile.gettempdir()) / f"omnigent-{stable_user_id()}" / "cursor-native"
_TMUX_FILE = "tmux.json"
_BRIDGE_CONFIG_FILE = "bridge.json"
_MCP_CONFIG_FILE = "mcp.json"
_HOOKS_CONFIG_FILE = "hooks.json"
#: Module invoked by Omnigent's usage ``stop`` hook; marks entries we own.
_USAGE_HOOK_MODULE = "omnigent.harnesses.cursor_native.usage"
_MCP_SERVER_NAME = "omnigent"
#: Env flag enabling the per-launch ``--plugin-dir`` config route (default off).
PLUGIN_DIR_ENV_VAR = "OMNIGENT_CURSOR_PLUGIN_DIR"
#: Config-file switch for the same route: ``cursor_native: {plugin_dir: true}``.
PLUGIN_DIR_CONFIG_SECTION = "cursor_native"
PLUGIN_DIR_CONFIG_KEY = "plugin_dir"
_TRUTHY_FLAG_VALUES = frozenset({"1", "true", "yes", "on"})
#: Plugin directory name. cursor-agent names a ``--plugin-dir`` plugin's MCP
#: servers ``plugin-<directory basename>-<server>`` (not the manifest ``name``),
#: so a constant basename keeps the server id -- and the ``Mcp(<id>:<tool>)``
#: permission entries -- the same for every session.
_PLUGIN_DIR_NAME = "omnigent"
#: Used instead when the user's own launch args already pass a ``--plugin-dir``
#: named ``omnigent``: two plugin dirs with one basename get one id and
#: cursor-agent silently keeps only the LAST (the user's), dropping ours.
_PLUGIN_DIR_FALLBACK_NAME = "omnigent-session"
_PLUGIN_PARENT_DIR = "cursor-plugin"
#: MCP server id cursor-agent gives the plugin's ``omnigent`` server.
PLUGIN_MCP_SERVER_ID = f"plugin-{_PLUGIN_DIR_NAME}-{_MCP_SERVER_NAME}"
#: The project ``stop`` entry that makes cursor-agent dispatch ``stop`` to
#: plugin hooks. A shell no-op; the comment marks it as Omnigent's.
PLUGIN_STOP_ARMER_COMMAND = "true # omnigent-plugin-stop-armer"
_CURSOR_AUTO_APPROVE_TOOLS = [
    "list_comments",
    "sys_add_policy",
    "sys_agent_download",
    "sys_agent_get",
    "sys_agent_list",
    "sys_call_async",
    "sys_cancel_async",
    "sys_cancel_task",
    "sys_list_models",
    "sys_os_edit",
    "sys_os_read",
    "sys_os_shell",
    "sys_os_write",
    "sys_policy_registry",
    "sys_session_close",
    "sys_session_create",
    "sys_session_get_history",
    "sys_session_get_info",
    "sys_session_list",
    "sys_session_send",
    "sys_terminal_close",
    "sys_terminal_launch",
    "sys_terminal_list",
    "sys_terminal_read",
    "sys_terminal_send",
    "update_comment",
]
_TMUX_READY_TIMEOUT_S = 30.0
_TMUX_SEND_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.2
_PASTE_SETTLE_S = 0.3
_PASTE_BUFFER = "omnigent-cursor-paste"
# How long to wait for the pasted text to become visible in the pane before
# sending Enter — submitting before the TUI commits the paste folds the Enter
# into the paste as a newline and the message sits unsent.
_PASTE_COMMIT_TIMEOUT_S = 5.0
# Pause between the ``/model`` filter landing and Enter. cursor-agent's
# composer debounces input (~1.5s); an Enter fired too soon selects a stale
# picker highlight. See the cursor-native e2e_ui TUI-driving notes.
_MODEL_PICKER_SETTLE_S = 1.5
# ``/model`` picker filter-result markers. cursor prints ``Models matching
# "<query>"`` above the matched rows, or ``No matches`` when the id resolves to
# nothing. These distinguish a landed filter from the echoed ``/model <id>``
# composer text (which always contains the id), so the readiness gate verifies
# the picker actually matched rather than passing instantly off the echo.
_PICKER_MATCH_MARKER = "Models matching"
_PICKER_NO_MATCH_MARKER = "No matches"
# cursor-agent TUI markers (Phase 0): idle input placeholder / running footer /
# first-run trust modal.
_IDLE_MARKERS = ("Plan, search, build", "Add a follow-up")
_TRUST_MARKER = "Trust this workspace"
# Composer-clear (see _clear_composer): cursor-agent's input widget ignores the
# readline Home/kill-line keys, so we delete with a Backspace flood instead.
# Backspaces per round (one ``send-keys -N`` call) and a round cap; the loop
# stops early once the pane stops changing (the draft is gone). The cap bounds a
# pathological never-settles pane; ``_COMPOSER_CLEAR_CHUNK * _COMPOSER_CLEAR_MAX_ROUNDS``
# deletions comfortably exceed any real draft.
_COMPOSER_CLEAR_CHUNK = 200
_COMPOSER_CLEAR_MAX_ROUNDS = 50
# Cold-start readiness (see _settle_pane): cursor-agent paints the input
# placeholder before its key handler is wired, so keys sent then are taken as
# literal text (a Backspace burst landed as 200 DELs ahead of a first prompt) or
# dropped. The first injection into a freshly launched TUI therefore also needs
# the pane unchanged across this many consecutive captures (~1s at
# _POLL_INTERVAL_S) once a placeholder is up. Later injections skip it: a running
# turn's pane never stops changing, and mid-turn steering must stay fast.
_COMPOSER_READY_STABLE_CAPTURES = 6
# Per-bridge stamp: the tmux.json instance (see _tmux_instance_key) whose
# composer has been seen stably ready. A relaunch rewrites tmux.json, so the
# next injection is cold again.
_COMPOSER_READY_FILE = "composer_ready.json"
# After a cancel, cursor-agent restores the interrupted prompt into the composer
# slightly after the turn stops. Wait for the pane to stop changing (generation
# ended and the draft settled) before clearing it, bounded by this timeout.
_INTERRUPT_SETTLE_TIMEOUT_S = 2.0


def bridge_dir_for_session_id(session_id: str) -> Path:
    """Return the per-session bridge dir, e.g. ``/tmp/omnigent-<uid>/cursor-native/<hash>``."""
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return _BRIDGE_ROOT / digest


def bridge_root() -> Path:
    """Return the configured Cursor-native bridge root."""
    return _BRIDGE_ROOT


def _ensure_dir(path: Path) -> None:
    """Create *path* (and parents) with owner-only permissions."""
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)


def _ensure_secure_bridge_dir(bridge_dir: Path) -> None:
    """Create/validate *bridge_dir* as an owner-only chain before writing secrets.

    ``_ensure_dir`` only ``mkdir(parents=True, exist_ok=True)`` + a suppressed
    ``chmod`` on the leaf: it trusts pre-existing ancestors, so on a shared host
    an attacker could pre-create ``$TMPDIR/omnigent-<uid>`` (or a deeper ancestor)
    as a symlink / world-writable dir and redirect the bridge tree. That tree now
    holds ``bridge.json`` — a bearer token for the relay's localhost control
    endpoint — so its directory must be hardened. Delegate to the same
    ``_ensure_secure_dir`` the shared relay (``start_tool_relay``) already applies
    to token-bearing trees; it rejects symlinked / non-owned / group-or-other
    accessible ancestors (the cursor-native root is in its allowlist). Lazy import
    avoids a cycle (``claude_native_bridge`` resolves cursor's ``bridge_root``
    lazily in turn).

    :raises RuntimeError: If any ancestor fails owner-only validation.
    """
    from omnigent.harnesses.claude_native.bridge import _ensure_secure_dir

    _ensure_secure_dir(bridge_dir)


#: File the runner drops into a fork's bridge dir holding the prior-conversation
#: text preamble, consumed once by the executor on the first injected message.
#: cursor's conversation is server-backed (a synthesized local store.db is NOT
#: loaded by ``cursor-agent --resume``), so a fork carries history by replaying
#: the prior turns as a text prefix on the first message (text-prefix replay).
_FORK_PREAMBLE_FILE = "fork_preamble.txt"
#: Sentinel framing the replayed history inside the first injected message. The
#: cursor agent reads the wrapped context, but the forwarder strips this block
#: when mirroring the user turn back to Omnigent so the copied history isn't
#: duplicated in the timeline (see cursor_native_forwarder._unwrap_user_query).
FORK_HISTORY_OPEN_TAG = "<omnigent_fork_history>"
FORK_HISTORY_CLOSE_TAG = "</omnigent_fork_history>"


def write_fork_preamble(bridge_dir: Path, preamble: str) -> None:
    """Persist a fork's prior-conversation preamble for the executor to consume.

    :param bridge_dir: The session's cursor-native bridge dir.
    :param preamble: Rendered prior-conversation text (``""`` is not written).
    """
    if not preamble:
        return
    _ensure_dir(bridge_dir)
    (bridge_dir / _FORK_PREAMBLE_FILE).write_text(preamble, encoding="utf-8")


def read_fork_preamble(bridge_dir: Path) -> str | None:
    """Read the fork preamble WITHOUT consuming it (else ``None``).

    Read and clear are deliberately split: the executor reads the preamble,
    injects it, and only calls :func:`clear_fork_preamble` on a SUCCESSFUL
    injection. Consuming on read would lose the forked history permanently if
    the first injection fails (e.g. the TUI exited) and the turn is retried.

    :param bridge_dir: The session's cursor-native bridge dir.
    :returns: The preamble text, or ``None`` when absent/empty.
    """
    try:
        text = (bridge_dir / _FORK_PREAMBLE_FILE).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    return text or None


def clear_fork_preamble(bridge_dir: Path) -> None:
    """Remove the fork preamble so it rides only the FIRST injected message.

    Called by the executor only after a turn's injection succeeds; subsequent
    turns then inject the plain user text. A no-op when the file is absent.

    :param bridge_dir: The session's cursor-native bridge dir.
    """
    with contextlib.suppress(OSError):
        (bridge_dir / _FORK_PREAMBLE_FILE).unlink()


#: Human-readable lead-in / sign-off framing the replayed transcript inside the
#: sentinel, so the block reads as a contained "here's the prior conversation"
#: note rather than a raw dump. The cursor agent sees this context; the forwarder
#: strips the whole sentinel block from the mirrored web bubble.
_FORK_HISTORY_HEADER = "This session was forked. Here is the conversation so far:"
_FORK_HISTORY_FOOTER = "(End of prior conversation. Please continue from here.)"


def _neutralize_fork_sentinels(text: str) -> str:
    """Defang any literal fork sentinel tags inside replayed transcript text.

    The preamble is rendered from prior user/assistant turns verbatim, so a turn
    could literally contain ``<omnigent_fork_history>`` /
    ``</omnigent_fork_history>`` (a user typed it, pasted logs, etc.). If left
    intact, an embedded close tag would let the forwarder's strip stop early and
    leak the rest of the transcript into the mirrored web bubble. Replacing the
    angle brackets guarantees the framed block contains exactly ONE real
    open/close pair, so the (non-greedy) strip is unambiguous. The bracketed form
    stays readable for the cursor agent.

    :param text: Rendered transcript text.
    :returns: The text with any literal sentinel tags defanged.
    """
    return text.replace(FORK_HISTORY_OPEN_TAG, "[omnigent_fork_history]").replace(
        FORK_HISTORY_CLOSE_TAG, "[/omnigent_fork_history]"
    )


def wrap_fork_preamble(preamble: str, user_text: str) -> str:
    """Combine a fork preamble with the latest user text for one injection.

    The transcript is framed by a human lead-in / sign-off and fenced in
    :data:`FORK_HISTORY_OPEN_TAG` / :data:`FORK_HISTORY_CLOSE_TAG`. cursor can't
    reconstruct native chat bubbles from a fork (its conversation is
    server-backed), so this is the closest single-message analog: the agent
    reads the framed transcript as context, and the forwarder strips the whole
    sentinel block from the mirrored user turn so the copied history isn't
    duplicated in the Omnigent timeline.

    Any literal sentinel tags inside *preamble* are defanged
    (:func:`_neutralize_fork_sentinels`) so the framed block holds exactly one
    real open/close pair — this keeps the forwarder's non-greedy strip
    unambiguous and prevents embedded tags from leaking history. *user_text* is
    left untouched (it sits after the close tag; the non-greedy strip stops at
    the real close, so a tag in the user's own message is preserved).

    :param preamble: Rendered prior-conversation transcript.
    :param user_text: The user's first message in the fork.
    :returns: The framed, fenced transcript followed by the user text.
    """
    return (
        f"{FORK_HISTORY_OPEN_TAG}\n"
        f"{_FORK_HISTORY_HEADER}\n\n"
        f"{_neutralize_fork_sentinels(preamble)}\n\n"
        f"{_FORK_HISTORY_FOOTER}\n"
        f"{FORK_HISTORY_CLOSE_TAG}\n\n"
        f"{user_text}"
    )


def build_cursor_native_spawn_env(session_id: str) -> dict[str, str]:
    """Build the ``HARNESS_CURSOR_NATIVE_*`` env the harness executor reads."""
    bridge_dir = bridge_dir_for_session_id(session_id)
    _ensure_dir(bridge_dir)
    return {
        BRIDGE_DIR_ENV_VAR: str(bridge_dir),
    }


def build_mcp_config(
    bridge_dir: Path,
    *,
    python_executable: str | None = None,
) -> _JsonObject:
    """Build Cursor's ``.cursor/mcp.json`` for the Omnigent relay server.

    Cursor prompts for MCP tool approval before it sends ``tools/call`` to the
    server. Omnigent tools already route through the Omnigent ``/mcp`` proxy,
    where TOOL_CALL policies publish ``response.elicitation_request`` events
    that the web UI can render. Auto-approving the Cursor-side MCP gate avoids a
    hidden in-terminal approval prompt blocking the call before Omnigent ever
    sees it, while preserving Omnigent's own policy/elicitation gate.
    """
    python = python_executable or sys.executable
    return {
        "mcpServers": {
            _MCP_SERVER_NAME: {
                "command": python,
                "args": [
                    "-I",
                    "-m",
                    "omnigent.harnesses.claude_native.bridge",
                    "serve-mcp",
                    "--bridge-dir",
                    str(bridge_dir),
                ],
                "autoApprove": list(_CURSOR_AUTO_APPROVE_TOOLS),
                "env": {
                    "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                },
            }
        }
    }


def write_mcp_bridge_config(bridge_dir: Path) -> None:
    """Write the token config required by the shared Omnigent MCP bridge.

    :raises RuntimeError: If the bridge dir fails owner-only validation
        (:func:`_ensure_secure_bridge_dir`) — the token is not written.
    """
    _ensure_secure_bridge_dir(bridge_dir)
    config_path = bridge_dir / _BRIDGE_CONFIG_FILE
    if config_path.exists():
        return
    payload = {"token": secrets.token_urlsafe(32)}
    tmp = bridge_dir / (_BRIDGE_CONFIG_FILE + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, config_path)


def write_mcp_config(
    workspace: Path,
    bridge_dir: Path,
    *,
    python_executable: str | None = None,
    home: Path | None = None,
) -> Path | None:
    """Write the workspace-scoped Cursor MCP config for Omnigent tools.

    Merges the Omnigent bridge server into an existing ``mcp.json`` so that
    user-configured MCP servers are preserved. Returns the written path.

    Returns ``None`` and leaves Cursor's config alone when the project file is
    the user file (see :func:`shared_mcp_scope_reason`): a server bound to this
    session's bridge there is loaded by every Cursor session on the machine.
    Such a launch has no Omnigent MCP tools.
    """
    write_mcp_bridge_config(bridge_dir)
    if shared_mcp_scope_reason(workspace, home=home) is not None:
        return None
    cursor_dir = workspace / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    path = cursor_dir / _MCP_CONFIG_FILE

    # A hand-edited mcp.json can hold any JSON shape; discard non-dicts so a
    # malformed file can't crash the session launch.
    loaded = _load_json_config(path)
    existing: _JsonObject = loaded if isinstance(loaded, dict) else {}
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        existing["mcpServers"] = servers

    omnigent_entry = build_mcp_config(bridge_dir, python_executable=python_executable)
    omnigent_servers = omnigent_entry["mcpServers"]
    if not isinstance(omnigent_servers, dict):  # pragma: no cover - build_mcp_config invariant
        raise ValueError("Omnigent MCP config is missing mcpServers")
    servers[_MCP_SERVER_NAME] = omnigent_servers[_MCP_SERVER_NAME]

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    enable_mcp_for_workspace(workspace)
    allow_mcp_tools_in_cli_config()
    return path


_BRIDGE_OWNER_FILE = "owner.json"
#: Mirrors the forwarder's ``_STATE_FILE`` / ``_CLAIM_FRESH_MS`` (not imported:
#: the forwarder imports this module). A bridge whose forwarder persisted within
#: this window is a live session.
_FORWARDER_STATE_FILE = "cursor_forwarder.json"
_FORWARDER_FRESH_MS = 30_000


def write_bridge_owner(bridge_dir: Path, session_id: str) -> None:
    """Record which session owns *bridge_dir* (its name is a one-way hash).

    Lets a later same-workspace launch name the session whose hooks/MCP slot it
    is about to overwrite. Best-effort.
    """
    with contextlib.suppress(OSError):
        _ensure_dir(bridge_dir)
        tmp = bridge_dir / (_BRIDGE_OWNER_FILE + ".tmp")
        tmp.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
        os.replace(tmp, bridge_dir / _BRIDGE_OWNER_FILE)


def read_bridge_owner(bridge_dir: Path) -> str | None:
    """Return the session id recorded by :func:`write_bridge_owner`, if any."""
    loaded = _load_json_config(bridge_dir / _BRIDGE_OWNER_FILE)
    sid = loaded.get("session_id") if isinstance(loaded, dict) else None
    return sid if isinstance(sid, str) and sid else None


def _bridge_session_live(bridge_dir: Path) -> bool:
    """Whether the session behind *bridge_dir* still runs (fresh forwarder or live pane)."""
    state = _load_json_config(bridge_dir / _FORWARDER_STATE_FILE)
    heartbeat = state.get("heartbeat_ms") if isinstance(state, dict) else None
    if isinstance(heartbeat, int) and time.time() * 1000 - heartbeat <= _FORWARDER_FRESH_MS:
        return True
    info = read_tmux_info(bridge_dir)
    return info is not None and _session_alive(info["socket_path"], info["tmux_target"])


def _arg_after(argv: object, flag: str) -> str | None:
    """Return the argv element following *flag*, or ``None``."""
    if not isinstance(argv, list):
        return None
    for i, arg in enumerate(argv[:-1]):
        if arg == flag and isinstance(argv[i + 1], str):
            return argv[i + 1]
    return None


def _config_bridge_dirs(workspace: Path) -> dict[str, set[str]]:
    """Bridge dirs baked into *workspace*'s ``.cursor/hooks.json`` / ``mcp.json``."""
    import shlex

    found: dict[str, set[str]] = {_HOOKS_CONFIG_FILE: set(), _MCP_CONFIG_FILE: set()}
    hooks_cfg = _load_json_config(workspace / ".cursor" / _HOOKS_CONFIG_FILE)
    hooks = hooks_cfg.get("hooks") if isinstance(hooks_cfg, dict) else None
    if isinstance(hooks, dict):
        for entries in hooks.values():
            for entry in entries if isinstance(entries, list) else ():
                if not _is_omnigent_usage_hook(entry):
                    continue
                try:
                    bridge = _arg_after(shlex.split(str(entry.get("command"))), "--bridge-dir")
                except ValueError:
                    bridge = None
                if bridge:
                    found[_HOOKS_CONFIG_FILE].add(bridge)
    mcp_cfg = _load_json_config(workspace / ".cursor" / _MCP_CONFIG_FILE)
    servers = mcp_cfg.get("mcpServers") if isinstance(mcp_cfg, dict) else None
    server = servers.get(_MCP_SERVER_NAME) if isinstance(servers, dict) else None
    bridge = _arg_after(server.get("args"), "--bridge-dir") if isinstance(server, dict) else None
    if bridge:
        found[_MCP_CONFIG_FILE].add(bridge)
    return found


def live_foreign_config_bridges(
    workspace: Path,
    bridge_dir: Path,
    *,
    is_live: Callable[[Path], bool] | None = None,
    launch_grace: bool = False,
) -> dict[str, list[Path]]:
    """Find LIVE sibling sessions whose hooks/MCP slot this launch would overwrite.

    ``.cursor/hooks.json`` and ``.cursor/mcp.json`` hold one bridge dir each per
    workspace (see the module docstring), so a same-workspace launch re-points
    them at itself and silently detaches the sibling's stop hook and MCP tools.
    Call before :func:`write_hooks_config` / :func:`write_mcp_config`.

    :param workspace: The launch workspace.
    :param bridge_dir: This launch's bridge dir (never reported).
    :param is_live: Liveness probe for a bridge dir (tests); defaults to a fresh
        forwarder heartbeat or a live tmux pane.
    :param launch_grace: Also count a sibling launched within
        :data:`_LAUNCH_GRACE_S` (the plugin route keeps those entries).
    :returns: ``{config file name: [live foreign bridge dirs]}``, only non-empty
        entries.
    """
    probe = is_live or (_bridge_live_or_launching if launch_grace else _bridge_session_live)
    result: dict[str, list[Path]] = {}
    for name, bridges in _config_bridge_dirs(workspace).items():
        live = [
            Path(b)
            for b in sorted(bridges)
            if not _same_path(b, bridge_dir) and Path(b).is_dir() and probe(Path(b))
        ]
        if live:
            result[name] = live
    return result


def build_hooks_config(bridge_dir: Path, *, python_executable: str | None = None) -> _JsonObject:
    """Build Cursor's ``.cursor/hooks.json`` registering the usage ``stop`` hook.

    cursor-agent fires the ``stop`` hook once per completed turn with a JSON
    payload (on stdin) carrying that turn's token usage — the only surface where
    the interactive TUI exposes usage. The hook command runs
    ``omnigent.harnesses.cursor_native.usage record-usage``, which appends the usage to
    ``<bridge_dir>/cursor_usage.jsonl`` for the runner's usage forwarder to tail
    and post as ``external_session_usage`` (lighting up the web Session-cost
    badge). Bakes the absolute ``--bridge-dir`` so the recorder writes where the
    forwarder reads, regardless of the hook's working directory.
    """
    import shlex

    python = python_executable or sys.executable
    command = " ".join(
        shlex.quote(part)
        for part in (
            python,
            "-I",
            "-m",
            _USAGE_HOOK_MODULE,
            "record-usage",
            "--bridge-dir",
            str(bridge_dir),
        )
    )
    return {"version": 1, "hooks": {"stop": [{"command": command}]}}


def _load_json_config(path: Path) -> object:
    """Best-effort load of an existing workspace JSON config.

    Shared decode policy for the ``.cursor`` config writers: a missing,
    unreadable, non-UTF-8, or non-JSON file yields ``None`` — a malformed
    file must never crash the session launch. ``ValueError`` covers both
    ``json.JSONDecodeError`` and ``UnicodeDecodeError``.
    """
    if not path.exists():
        return None
    with contextlib.suppress(ValueError, OSError):
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _is_omnigent_usage_hook(entry: object) -> bool:
    """Whether a hooks.json entry is Omnigent's own usage-recorder hook.

    The recorder command bakes a session-specific bridge dir, so entries from
    earlier sessions are stale and must be replaced rather than accumulated.
    """
    if not isinstance(entry, dict):
        return False
    return _USAGE_HOOK_MODULE in str(entry.get("command", ""))


def write_hooks_config(
    workspace: Path,
    bridge_dir: Path,
    *,
    python_executable: str | None = None,
    home: Path | None = None,
) -> Path | None:
    """Merge Omnigent's usage ``stop`` hook into the workspace's ``hooks.json``.

    Sibling of :func:`write_mcp_config`: project-scoped Cursor config the TUI
    loads on launch in a trusted workspace. Preserves the workspace's existing
    hooks (e.g. a project ``preToolUse`` policy hook) and replaces only stale
    Omnigent usage hooks from earlier sessions. Returns the written path.

    Returns ``None`` and writes nothing when the project file is the user file
    (see :func:`shared_hooks_scope_reason`): a session-specific stop hook there
    fires for every Cursor session on the machine. Such a launch reports no
    token usage and no turn-end idle.
    """
    if shared_hooks_scope_reason(workspace, home=home) is not None:
        return None
    cursor_dir = workspace / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    path = cursor_dir / _HOOKS_CONFIG_FILE

    # A hand-edited hooks.json can hold any JSON shape; discard non-dicts so a
    # malformed file can't crash the session launch.
    loaded = _load_json_config(path)
    existing: _JsonObject = loaded if isinstance(loaded, dict) else {}
    hooks = existing.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    existing["hooks"] = hooks
    existing.setdefault("version", 1)

    payload = build_hooks_config(bridge_dir, python_executable=python_executable)
    omnigent_hooks = payload["hooks"]
    if not isinstance(omnigent_hooks, dict):  # pragma: no cover - build_hooks_config invariant
        raise ValueError("Omnigent hooks config is missing its hooks mapping")
    for event, entries in omnigent_hooks.items():
        current = hooks.get(event)
        if not isinstance(current, list):
            current = []
        kept = [entry for entry in current if not _is_omnigent_usage_hook(entry)]
        hooks[event] = kept + list(entries)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def plugin_dir_mode_enabled(
    env: Mapping[str, str] | None = None,
    config: Mapping[str, object] | None = None,
) -> bool:
    """Whether launches use the per-launch ``--plugin-dir`` config route.

    Off by default, which keeps the project ``.cursor/{hooks,mcp}.json`` route.
    Read in the runner at every cursor launch. A non-empty
    ``OMNIGENT_CURSOR_PLUGIN_DIR`` decides (``1``/``true``/``yes``/``on`` enable,
    anything else, e.g. ``0``, disables); unset or empty falls back to the user
    config (``~/.omnigent/config.yaml``, or ``$OMNIGENT_CONFIG_HOME``)::

        cursor_native:
          plugin_dir: true

    The config switch needs no host restart; the env var must be set on the
    host service (the runner env is allowlisted from it).

    :param env: Environment to read (default ``os.environ``).
    :param config: User config mapping (default: loaded from disk; a missing
        or unreadable file counts as unset).
    """
    value = (os.environ if env is None else env).get(PLUGIN_DIR_ENV_VAR, "").strip()
    if value:
        return value.casefold() in _TRUTHY_FLAG_VALUES
    if config is None:
        try:
            from omnigent.config import load_global_config

            config = load_global_config()
        except Exception:  # noqa: BLE001 — a bad config must not break the launch
            return False
    section = config.get(PLUGIN_DIR_CONFIG_SECTION) if isinstance(config, Mapping) else None
    setting = section.get(PLUGIN_DIR_CONFIG_KEY) if isinstance(section, Mapping) else None
    if isinstance(setting, str):
        return setting.strip().casefold() in _TRUTHY_FLAG_VALUES
    return setting is True


def plugin_dir_for_bridge(bridge_dir: Path, name: str = _PLUGIN_DIR_NAME) -> Path:
    """This session's private Cursor plugin dir, inside its bridge dir."""
    return bridge_dir / _PLUGIN_PARENT_DIR / name


def plugin_mcp_server_id(name: str = _PLUGIN_DIR_NAME) -> str:
    """The MCP server id cursor-agent gives the plugin named *name*."""
    return f"plugin-{name}-{_MCP_SERVER_NAME}"


class CursorPluginRouteError(RuntimeError):
    """A plugin-route (``--plugin-dir``) launch that cannot work as configured.

    Raised before the terminal starts so the session fails loudly instead of
    running with no Omnigent tools and completion receipts waiting forever.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"cursor-native plugin-route launch refused: {message}")

    def user_message(self) -> str:
        """Actionable text for the failed-launch status."""
        return self.message


def _passthrough_plugin_dirs(args: Sequence[str]) -> list[str]:
    """The ``--plugin-dir`` values in cursor-agent launch args (both spellings)."""
    found: list[str] = []
    for i, arg in enumerate(args):
        if arg == "--plugin-dir" and i + 1 < len(args):
            found.append(args[i + 1])
        elif arg.startswith("--plugin-dir="):
            found.append(arg.split("=", 1)[1])
    return found


def plugin_dir_name_for_launch(args: Sequence[str]) -> str:
    """Pick this launch's plugin dir basename given the user's launch args.

    cursor-agent ids a ``--plugin-dir`` plugin by its directory basename and,
    for two dirs with the same basename, silently keeps only the last one. When
    the user's args already pass a plugin dir named ``omnigent``, ours is named
    :data:`_PLUGIN_DIR_FALLBACK_NAME` instead, so both load; its MCP server id
    is then ``plugin-omnigent-session-omnigent`` (tools are allow-listed under
    that id).

    :raises CursorPluginRouteError: When both names are taken.
    """
    taken = {os.path.basename(os.path.normpath(path)) for path in _passthrough_plugin_dirs(args)}
    for name in (_PLUGIN_DIR_NAME, _PLUGIN_DIR_FALLBACK_NAME):
        if name not in taken:
            return name
    raise CursorPluginRouteError(
        "the Cursor launch args already pass --plugin-dir directories named "
        f"{_PLUGIN_DIR_NAME!r} and {_PLUGIN_DIR_FALLBACK_NAME!r}; cursor-agent keeps only "
        "one plugin per directory name, so Omnigent's own plugin would be dropped. "
        "Rename one of them, or unset OMNIGENT_CURSOR_PLUGIN_DIR / cursor_native.plugin_dir."
    )


#: cursor-agent launch flags / env that select the local-agent authless or
#: Bedrock profile, whose ``enableUserLocalPlugins`` capability is false.
_PLUGINS_OFF_FLAGS = ("--authless", "--enable-bedrock", "--enable-local-bedrock")
_PLUGINS_OFF_ENV = (
    "CURSOR_ENABLE_AUTHLESS",
    "CURSOR_ENABLE_BEDROCK",
    "CURSOR_ENABLE_LOCAL_BEDROCK",
)
_LOCAL_AGENT_BUILD = "cursor-agent-local"


def user_local_plugins_disabled_reason(
    cursor_command: str,
    args: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Why cursor-agent would ignore ``--plugin-dir`` for this launch, if it would.

    cursor-agent loads ``--plugin-dir`` plugins only when its local-agent
    profile has ``enableUserLocalPlugins`` (2026.09.26 bundle,
    ``src/local-agent-profile.ts``). That is not a config-file setting: the
    standard ``cursor-agent`` build always runs the remote profile, where it is
    true. Only the ``cursor-agent-local`` build in authless or Bedrock mode
    (``--authless``, ``--enable-bedrock``, ``--enable-local-bedrock``, or
    ``CURSOR_ENABLE_AUTHLESS`` / ``CURSOR_ENABLE_BEDROCK`` /
    ``CURSOR_ENABLE_LOCAL_BEDROCK`` = ``1``) uses the ``local-authless``
    profile, where it is false. The flags count for any build (the standard
    build rejects them anyway); the env vars only for the local build.

    :returns: ``None`` when plugins load, else ``enableUserLocalPlugins_off:<marker>``.
    """
    env = os.environ if env is None else env
    for arg in args:
        if arg.split("=", 1)[0] in _PLUGINS_OFF_FLAGS:
            return f"enableUserLocalPlugins_off:{arg}"
    resolved = Path(os.path.realpath(cursor_command))
    if any(part.startswith(_LOCAL_AGENT_BUILD) for part in (*resolved.parts, cursor_command)):
        for name in _PLUGINS_OFF_ENV:
            if env.get(name) == "1":
                return f"enableUserLocalPlugins_off:{name}=1"
    return None


def check_plugin_route_launch(
    cursor_command: str,
    args: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> str:
    """Refuse a plugin-route launch cursor-agent would run without the plugin.

    Run before any launch write. With ``enableUserLocalPlugins`` off the
    session would have no Omnigent tools, no usage/idle stop hook, and
    completion receipts armed on a hook that never fires.

    :returns: The plugin dir basename to use (:func:`plugin_dir_name_for_launch`).
    :raises CursorPluginRouteError: When the plugin would not load.
    """
    reason = user_local_plugins_disabled_reason(cursor_command, args, env)
    if reason is not None:
        marker = reason.split(":", 1)[1]
        raise CursorPluginRouteError(
            f"cursor-agent runs in its authless/Bedrock local-agent profile ({marker}), "
            "where enableUserLocalPlugins is off, so it ignores --plugin-dir and this "
            "session would get no Omnigent tools, no usage or turn-end hook, and "
            "completion receipts that never arrive. Remove that setting, or turn the "
            "plugin route off (unset OMNIGENT_CURSOR_PLUGIN_DIR on the host service, or "
            "cursor_native.plugin_dir in config.yaml)."
        )
    return plugin_dir_name_for_launch(args)


def _write_json_atomic(path: Path, payload: _JsonObject) -> None:
    # A per-writer tmp name: concurrent first launches in one workspace must not
    # rename each other's half-written file.
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_cursor_plugin(
    bridge_dir: Path,
    *,
    workspace: Path | None = None,
    python_executable: str | None = None,
    name: str = _PLUGIN_DIR_NAME,
) -> Path:
    """Write this session's Cursor plugin (MCP server + usage stop hook).

    The plugin is loaded with ``cursor-agent --plugin-dir <returned path>`` and
    carries the same MCP server (:func:`build_mcp_config`) and ``stop`` hook
    (:func:`build_hooks_config`) the project files carry on the default route,
    bound to this session's bridge dir only. Layout (read in the 2026.09.26
    bundle): ``.cursor-plugin/plugin.json`` (manifest), ``mcp.json`` and
    ``hooks/hooks.json``. cursor-agent names the server
    :data:`PLUGIN_MCP_SERVER_ID` and needs no server approval for it; tool calls
    still pass its permission config, so the tools are allow-listed under that
    id. Rewritten on every launch.

    :param workspace: When given, re-enable the plugin server if Cursor has it
        in the workspace's disabled list.
    :param name: Plugin dir basename (:func:`plugin_dir_name_for_launch`); it
        sets the server id (:func:`plugin_mcp_server_id`).
    :returns: The plugin dir.
    """
    write_mcp_bridge_config(bridge_dir)
    plugin_dir = plugin_dir_for_bridge(bridge_dir, name)
    server_id = plugin_mcp_server_id(name)
    _ensure_dir(plugin_dir / ".cursor-plugin")
    _ensure_dir(plugin_dir / "hooks")
    _write_json_atomic(
        plugin_dir / ".cursor-plugin" / "plugin.json",
        {
            "name": name,
            "description": "Omnigent session bridge (MCP tools and usage hook).",
        },
    )
    _write_json_atomic(
        plugin_dir / _MCP_CONFIG_FILE,
        build_mcp_config(bridge_dir, python_executable=python_executable),
    )
    _write_json_atomic(
        plugin_dir / "hooks" / _HOOKS_CONFIG_FILE,
        build_hooks_config(bridge_dir, python_executable=python_executable),
    )
    if workspace is not None:
        enable_mcp_for_workspace(workspace, server_id)
    allow_mcp_tools_in_cli_config(server_id)
    return plugin_dir


def is_plugin_stop_armer(entry: object) -> bool:
    """Whether a hooks.json entry is the no-op plugin stop armer."""
    return (
        isinstance(entry, dict)
        and entry.get("command") == PLUGIN_STOP_ARMER_COMMAND
        and entry.get("type", "command") == "command"
    )


#: A bridge whose owner file (written first by every launch, before any
#: ``.cursor`` config) is this recent counts as live: its session may be
#: mid-launch, with hooks written but no forwarder heartbeat or tmux target yet.
_LAUNCH_GRACE_S = 120.0


def _bridge_live_or_launching(bridge_dir: Path) -> bool:
    """:func:`_bridge_session_live`, or launched within :data:`_LAUNCH_GRACE_S`."""
    if _bridge_session_live(bridge_dir):
        return True
    try:
        written = (bridge_dir / _BRIDGE_OWNER_FILE).stat().st_mtime
    except OSError:
        return False
    return time.time() - written <= _LAUNCH_GRACE_S


def _owned_bridge_is_live(
    bridge: str, is_live: Callable[[Path], bool] | None, own_bridge: Path | None = None
) -> bool:
    """Whether an Omnigent entry bound to *bridge* must be kept for a sibling.

    Entries bound to *own_bridge* (this launch's earlier project-route config)
    are never kept: this launch replaces them with its plugin.
    """
    if own_bridge is not None and _same_path(bridge, own_bridge):
        return False
    path = Path(bridge)
    return path.is_dir() and (is_live or _bridge_live_or_launching)(path)


def write_plugin_stop_armer(
    workspace: Path,
    *,
    home: Path | None = None,
    is_live: Callable[[Path], bool] | None = None,
    own_bridge: Path | None = None,
) -> Path | None:
    """Make cursor-agent dispatch ``stop`` to plugin hooks in *workspace*.

    cursor-agent fires the ``stop`` event only when the user or project hooks
    file declares a ``stop`` hook; it then runs plugin stop hooks as well. This
    merges one constant no-op entry (:data:`PLUGIN_STOP_ARMER_COMMAND`) into the
    project ``hooks.json``; it is identical for every session, so concurrent
    launches write the same bytes. Omnigent usage hooks left by earlier
    project-route launches are dropped unless their session is still live or
    launched within :data:`_LAUNCH_GRACE_S` (a live one keeps working and is
    reported by :func:`live_foreign_config_bridges`); one bound to *own_bridge*
    is always dropped. Other hooks are preserved.

    :returns: The written path, or ``None`` (nothing written) when the project
        file is the user file (:func:`shared_hooks_scope_reason`).
    """
    import shlex

    if shared_hooks_scope_reason(workspace, home=home) is not None:
        return None
    cursor_dir = workspace / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    path = cursor_dir / _HOOKS_CONFIG_FILE
    loaded = _load_json_config(path)
    existing: _JsonObject = loaded if isinstance(loaded, dict) else {}
    hooks = existing.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    existing["hooks"] = hooks
    existing.setdefault("version", 1)
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if _is_omnigent_usage_hook(entry):
                try:
                    bridge = _arg_after(shlex.split(str(entry.get("command"))), "--bridge-dir")
                except ValueError:
                    bridge = None
                if bridge is None or not _owned_bridge_is_live(bridge, is_live, own_bridge):
                    continue
            kept.append(entry)
        hooks[event] = kept
    stop = hooks.get("stop")
    if not isinstance(stop, list):
        stop = []
    stop = [entry for entry in stop if not is_plugin_stop_armer(entry)]
    hooks["stop"] = [*stop, {"command": PLUGIN_STOP_ARMER_COMMAND}]
    if _load_json_config(path) != existing:
        _write_json_atomic(path, existing)
    return path


def remove_stale_workspace_mcp_server(
    workspace: Path,
    *,
    home: Path | None = None,
    is_live: Callable[[Path], bool] | None = None,
    own_bridge: Path | None = None,
) -> bool:
    """Drop a dead session's ``omnigent`` server from the project ``mcp.json``.

    On the plugin route the project file is not written, but a server an
    earlier project-route launch left there would still load next to this
    session's plugin server and route to that old bridge. Removes the entry
    only when it has Omnigent's shape (``serve-mcp --bridge-dir``) and its
    session is neither live nor launching (see :func:`write_plugin_stop_armer`;
    *own_bridge* always counts as stale). The file is rewritten, never deleted (it may be
    tracked): with no other server left it holds ``{"mcpServers": {}}``.
    Never touches the user file (:func:`shared_mcp_scope_reason`).

    :returns: Whether an entry was removed.
    """
    if shared_mcp_scope_reason(workspace, home=home) is not None:
        return False
    path = workspace / ".cursor" / _MCP_CONFIG_FILE
    loaded = _load_json_config(path)
    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    entry = servers.get(_MCP_SERVER_NAME) if isinstance(servers, dict) else None
    if (
        not isinstance(loaded, dict)
        or not isinstance(servers, dict)
        or not isinstance(entry, dict)
    ):
        return False
    args = entry.get("args")
    if not isinstance(args, list) or "serve-mcp" not in args:
        return False
    bridge = _arg_after(args, "--bridge-dir")
    if bridge is not None and _owned_bridge_is_live(bridge, is_live, own_bridge):
        return False
    del servers[_MCP_SERVER_NAME]
    # Never unlink: the file may be tracked (a deletion is a foreign ``D`` change
    # to git/Trio). With nothing else left it becomes ``{"mcpServers": {}}``.
    _write_json_atomic(path, loaded)
    return True


#: System-wide ``hooks.json`` locations from Cursor's hooks documentation
#: (Linux, macOS). Checked when present; not verified against a live install.
_SYSTEM_HOOKS_PATHS = (
    Path("/etc/cursor/hooks.json"),
    Path("/Library/Application Support/Cursor/hooks.json"),
)


#: The fixed argv between the interpreter and the bridge dir in an owned hook.
_OWNED_HOOK_ARGS = ("-I", "-m", _USAGE_HOOK_MODULE, "record-usage", "--bridge-dir")


def is_owned_usage_hook_command(command: object) -> bool:
    """Whether *command* is exactly a command :func:`build_hooks_config` generates.

    Stricter than :func:`_is_omnigent_usage_hook`: the command must be the
    canonical quoted argv ``<abs python> -I -m <usage module> record-usage
    --bridge-dir <abs dir>`` and nothing else, so a foreign hook that merely
    mentions the module (``sh -c '…usage record-usage…; echo …'``) is not owned.
    """
    import shlex

    if not isinstance(command, str):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if len(argv) != 7 or tuple(argv[1:6]) != _OWNED_HOOK_ARGS:
        return False
    python, bridge = argv[0], argv[6]
    if not (os.path.isabs(python) and os.path.basename(python).startswith("python")):
        return False
    if not os.path.isabs(bridge):
        return False
    return " ".join(shlex.quote(part) for part in argv) == command


def _owned_hook_bridge(command: object) -> str | None:
    """The ``--bridge-dir`` of an owned usage hook command, else ``None``."""
    import shlex

    if not is_owned_usage_hook_command(command):
        return None
    return shlex.split(str(command))[6]


def _same_path(a: str | Path, b: str | Path) -> bool:
    """Whether *a* and *b* name one location (symlinks, ``..``, bind mounts)."""
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _stop_hooks_hold_reason(
    path: Path, *, owned_bridge: Path | None = None, stale_ok: bool = False
) -> str | None:
    """Why *path* rules out completion receipts, or ``None`` if it does not.

    A missing file is fine, and so is the no-op plugin stop armer
    (:func:`is_plugin_stop_armer`). An unreadable or malformed one fails closed, as does
    any entry under a stop-type event (``stop``, ``subagentStop``, matched
    case-insensitively) that is not an owned Omnigent usage hook for this
    launch: its ``--bridge-dir`` must be *owned_bridge*, or, with *stale_ok*,
    any bridge (a project entry the launch is about to replace). With neither,
    as for the user and system files, every stop entry holds: those files are
    shared by every Cursor session on the machine.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return f"hooks_config_unreadable:{path}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return f"hooks_config_malformed:{path}"
    if not isinstance(data, dict):
        return f"hooks_config_malformed:{path}"
    hooks = data.get("hooks")
    if hooks is None:
        return None
    if not isinstance(hooks, dict):
        return f"hooks_config_malformed:{path}"
    for event, entries in hooks.items():
        if not str(event).casefold().endswith("stop"):
            continue
        if not isinstance(entries, list):
            return f"hooks_config_malformed:{path}"
        for entry in entries:
            if not isinstance(entry, dict):
                return f"hooks_config_malformed:{path}"
            if is_plugin_stop_armer(entry):
                continue
            bridge = _owned_hook_bridge(entry.get("command"))
            if bridge is None:
                return f"foreign_stop_hook:{path}"
            if not stale_ok and (owned_bridge is None or not _same_path(bridge, owned_bridge)):
                return f"foreign_stop_hook:{path}"
    return None


def _home_candidates(home: Path | None) -> list[Path]:
    """``$HOME`` (what Cursor reads user hooks from) and the account's home dir."""
    candidates = [home if home is not None else Path.home()]
    with contextlib.suppress(KeyError, ImportError):
        import pwd

        candidates.append(Path(pwd.getpwuid(os.getuid()).pw_dir))
    return candidates


def _shared_config_scope_reason(
    workspace: Path, file_name: str, reason: str, *, home: Path | None
) -> str | None:
    """Why *workspace*'s project ``.cursor/<file_name>`` is the user one, else ``None``.

    True when the workspace is ``$HOME`` or the account home (directly or via an
    alias), when its ``.cursor`` directory is the home one, or when the project
    file resolves to the home one. Cursor then loads one file as both project
    and user scope, so it is shared by every session on the machine.
    """
    for candidate in _home_candidates(home):
        if _same_path(workspace, candidate) or _same_path(
            workspace / ".cursor", candidate / ".cursor"
        ):
            return f"workspace_is_home:{workspace}"
        project_file = workspace / ".cursor" / file_name
        if _same_path(project_file, candidate / ".cursor" / file_name):
            return f"{reason}:{project_file}"
    return None


def shared_hooks_scope_reason(workspace: Path, *, home: Path | None = None) -> str | None:
    """Why *workspace*'s project ``hooks.json`` is the user hooks file, else ``None``."""
    return _shared_config_scope_reason(
        workspace, _HOOKS_CONFIG_FILE, "shared_hooks_config", home=home
    )


def shared_mcp_scope_reason(workspace: Path, *, home: Path | None = None) -> str | None:
    """Why *workspace*'s project ``mcp.json`` is the user MCP file, else ``None``."""
    return _shared_config_scope_reason(workspace, _MCP_CONFIG_FILE, "shared_mcp_config", home=home)


def user_mcp_has_omnigent_server(*, home: Path | None = None) -> bool:
    """Whether the user ``~/.cursor/mcp.json`` declares an ``omnigent`` server.

    Every Cursor session loads that entry, so a shared-scope launch that writes
    none of its own still connects to whatever bridge it names.
    """
    return _user_mcp_omnigent_entry(home) is not None


def _user_mcp_omnigent_entry(home: Path | None) -> object | None:
    path = (home if home is not None else Path.home()) / ".cursor" / _MCP_CONFIG_FILE
    loaded = _load_json_config(path)
    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    if not isinstance(servers, dict) or _MCP_SERVER_NAME not in servers:
        return None
    return servers[_MCP_SERVER_NAME]


def user_mcp_has_session_bound_omnigent_server(*, home: Path | None = None) -> bool:
    """Whether the user ``mcp.json`` holds an ``omnigent`` entry an Omnigent launch wrote.

    Matches the shape :func:`build_mcp_config` writes (``serve-mcp`` bound to
    one session's ``--bridge-dir``), so only an entry Omnigent itself left
    behind counts. Only the bool leaves this function, never the entry.
    """
    entry = _user_mcp_omnigent_entry(home)
    args = entry.get("args") if isinstance(entry, dict) else None
    return isinstance(args, list) and "serve-mcp" in args and "--bridge-dir" in args


def cursor_project_root(workspace: Path) -> Path:
    """The project root cursor-agent uses for a TUI started in *workspace*.

    Mirrors cursor-agent's ``src/utils/git.ts`` lookup (read in the installed
    2026.09.23 bundle), which picks the directory its project ``.cursor/mcp.json``
    and ``.cursor/hooks.json`` come from: the nearest of *workspace* and its
    ancestors holding a ``.git`` entry (a directory, a worktree file, or a link
    that resolves), never the filesystem root itself; otherwise *workspace*.
    """
    current = str(workspace)
    anchor = Path(current).anchor
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return Path(current)
        parent = os.path.dirname(current)
        if parent in (current, anchor):
            return workspace
        current = parent


class CursorSharedWorkspaceError(RuntimeError):
    """A Cursor launch whose project config is not the workspace's own.

    Cursor loads its project ``mcp.json`` / ``hooks.json`` from the workspace's
    git root. When that root is the home folder (or links to its ``.cursor``
    files), the project config is the user config shared by every Cursor
    session on the machine. When it is another folder above the workspace, the
    session's own config is never read. Either way the session gets no Omnigent
    tools of its own and would load whatever another session left there.
    """

    def __init__(
        self,
        *,
        workspace: Path,
        project_root: Path,
        shared_scope: Path,
        reason: str,
        stale_omnigent_server: bool,
    ) -> None:
        self.workspace = workspace
        self.project_root = project_root
        self.shared_scope = shared_scope
        self.reason = reason
        self.stale_omnigent_server = stale_omnigent_server
        super().__init__(
            f"cursor-native launch refused: workspace={workspace} "
            f"project_root={project_root} reason={reason} "
            f"stale_omnigent_server={stale_omnigent_server}"
        )

    def user_message(self) -> str:
        """Actionable, non-secret text for the failed-launch status (paths only)."""
        if self.reason.startswith(_NOT_PROJECT_ROOT_REASON):
            subfolder = os.path.relpath(os.path.realpath(self.workspace), self.project_root)
            message = (
                "Cursor can't start here. Cursor reads its project tools and hooks "
                f"from the git repository {self.project_root}, not from the workspace "
                f"{self.workspace}, so this session would get no Omnigent tools of its "
                "own and could load another session's. Start a new session with "
                f"{self.project_root} as the workspace, and name the subfolder "
                f"{subfolder} in your task."
            )
        else:
            if self.shared_scope == self.workspace:
                where = f"The workspace {self.workspace} is"
            else:
                where = (
                    f"The workspace {self.workspace} is inside the git repository "
                    f"{self.project_root}, which Cursor uses as its project folder. "
                    "That folder is"
                )
            message = (
                f"Cursor can't start here. {where} your home folder or shares its "
                "~/.cursor config, so Cursor would share its tool and hook config "
                "with every other Cursor session on this machine. Start a new session "
                "whose workspace is the root folder of a git repository other than "
                "your home folder, or a folder that is not inside any git repository, "
                "and name any subfolder you want to work in in your task."
            )
        if self.stale_omnigent_server:
            message += (
                " Your ~/.cursor/mcp.json also has an 'omnigent' server left by an "
                "earlier session; remove that entry."
            )
        return message


_NOT_PROJECT_ROOT_REASON = "workspace_not_project_root:"


def check_cursor_launch_admission(workspace: Path, *, home: Path | None = None) -> None:
    """Refuse a Cursor launch that would not load the workspace's own project config.

    Cursor resolves its project root (:func:`cursor_project_root`) from its
    physical cwd. The launch is refused when the workspace or that root shares
    the user MCP or hooks config, or when the root is a folder above the
    workspace (aliases of the workspace itself are fine): Cursor would then read
    that folder's ``.cursor`` config, not the one this launch writes. Reads
    only; run it before any launch write.

    :raises CursorSharedWorkspaceError: When the launch is refused.
    """
    project_root = cursor_project_root(Path(os.path.realpath(workspace)))
    is_root = _same_path(project_root, workspace)
    candidates = [workspace] if is_root else [workspace, project_root]
    for candidate in candidates:
        reason = shared_mcp_scope_reason(candidate, home=home) or shared_hooks_scope_reason(
            candidate, home=home
        )
        if reason is not None:
            break
    else:
        candidate = project_root
        reason = None if is_root else f"{_NOT_PROJECT_ROOT_REASON}{project_root}"
    if reason is not None:
        raise CursorSharedWorkspaceError(
            workspace=workspace,
            project_root=project_root,
            shared_scope=candidate,
            reason=reason,
            stale_omnigent_server=user_mcp_has_session_bound_omnigent_server(home=home),
        )


def completion_receipt_project_precheck(
    workspace: Path, *, home: Path | None = None
) -> str | None:
    """Pre-write gate: run before :func:`write_hooks_config` rewrites the project file.

    That rewrite drops a malformed file and replaces stale Omnigent hooks, so
    this is the only point where a malformed or foreign project file is seen.
    Stale owned hooks for other bridges pass here; they are replaced by the
    rewrite and :func:`completion_receipt_hook_hold_reason` re-checks the result.
    """
    reason = shared_hooks_scope_reason(workspace, home=home)
    if reason is not None:
        return reason
    return _stop_hooks_hold_reason(workspace / ".cursor" / _HOOKS_CONFIG_FILE, stale_ok=True)


def completion_receipt_hook_hold_reason(
    workspace: Path,
    bridge_dir: Path,
    *,
    home: Path | None = None,
    system_paths: tuple[Path, ...] | None = None,
    plugin_dir: Path | None = None,
) -> str | None:
    """Check the hooks.json files Cursor loads for this launch before receipts arm.

    A non-Omnigent ``stop`` hook can answer ``followup_message`` and start a turn
    that no receipt binds correctly, and an Omnigent hook in a shared file
    records other sessions' stops, so only this launch's own hook in the
    project file (``<workspace>/.cursor/hooks.json``) is allowed; any stop hook
    in the user (``~/.cursor/hooks.json``) or system file holds. Hooks outside
    the project file are never edited to gain the capability. Run after
    :func:`write_hooks_config`, on the files the TUI will load.

    With *plugin_dir* (the per-launch plugin route), this launch's hook lives in
    the plugin's ``hooks/hooks.json`` instead: that file must exist and hold
    only this launch's hook, and the project file may hold only the no-op
    armer (any Omnigent hook there belongs to another session).

    :returns: ``None`` when no such hook exists, else the first hold reason.
    """
    reason = shared_hooks_scope_reason(workspace, home=home)
    if reason is not None:
        return reason
    reason = _stop_hooks_hold_reason(
        workspace / ".cursor" / _HOOKS_CONFIG_FILE,
        owned_bridge=None if plugin_dir is not None else bridge_dir,
    )
    if reason is not None:
        return reason
    if plugin_dir is not None:
        plugin_hooks = plugin_dir / "hooks" / _HOOKS_CONFIG_FILE
        if not plugin_hooks.is_file():
            return f"plugin_hooks_missing:{plugin_hooks}"
        reason = _stop_hooks_hold_reason(plugin_hooks, owned_bridge=bridge_dir)
        if reason is not None:
            return reason
    for path in (
        (home if home is not None else Path.home()) / ".cursor" / _HOOKS_CONFIG_FILE,
        *(_SYSTEM_HOOKS_PATHS if system_paths is None else system_paths),
    ):
        reason = _stop_hooks_hold_reason(path)
        if reason is not None:
            return reason
    return None


def prepare_completion_receipts(
    bridge_dir: Path, workspace: Path, *, opted_in: bool, home: Path | None = None
) -> str | None:
    """First launch step: drop the prior epoch and run the pre-write project gate.

    :returns: ``"not_opted_in"``, a pre-write hold reason, or ``None``; pass it
        to :func:`arm_completion_receipts` as *precheck*.
    :raises ReceiptEpochClearError: the prior epoch could not be removed, opted
        in or not; the launch must abort before the terminal starts.
    """
    cursor_native_status.clear_receipt_epoch(bridge_dir)
    if not opted_in:
        return "not_opted_in"
    return completion_receipt_project_precheck(workspace, home=home)


def arm_completion_receipts(
    bridge_dir: Path,
    workspace: Path,
    launch_epoch_ms: int,
    *,
    opted_in: bool,
    precheck: str | None = None,
    home: Path | None = None,
    system_paths: tuple[Path, ...] | None = None,
    plugin_dir: Path | None = None,
) -> str | None:
    """Set this launch's completion-receipt capability from the opt-in and hooks.

    Called after :func:`write_hooks_config`. Always drops the prior launch's
    epoch first, so neither a refused launch nor one that fails midway keeps a
    stale capability. Writes a fresh epoch only when opted in, *precheck* (from
    :func:`prepare_completion_receipts`) is ``None`` and
    :func:`completion_receipt_hook_hold_reason` finds nothing; without an epoch
    the fence answers ``capability_unsupported`` and Trio holds.

    :returns: ``None`` when armed, ``"not_opted_in"``, or the hold reason.
    :raises ReceiptEpochClearError: the prior epoch could not be removed.
    """
    cursor_native_status.clear_receipt_epoch(bridge_dir)
    if not opted_in:
        return "not_opted_in"
    reason = precheck or completion_receipt_hook_hold_reason(
        workspace, bridge_dir, home=home, system_paths=system_paths, plugin_dir=plugin_dir
    )
    if reason is None:
        cursor_native_status.write_receipt_epoch(bridge_dir, launch_epoch_ms)
    return reason


def approve_mcp_server_for_workspace(workspace: Path) -> None:
    """Approve the workspace-scoped Omnigent MCP server in Cursor's state.

    Cursor stores per-workspace MCP approvals using a private hash of the
    concrete server config. Rather than duplicate that implementation here,
    ask ``cursor-agent mcp enable omnigent`` to write the exact approval entry
    for this workspace. This is best-effort: the TUI still launches if the
    installed Cursor CLI cannot run the management subcommand, but when it can,
    the hidden server-approval gate is cleared before startup.
    """
    try:
        from omnigent.harnesses.cursor_native.main import resolve_cursor_executable

        cursor = resolve_cursor_executable()
        subprocess.run(
            [cursor, "mcp", "enable", _MCP_SERVER_NAME],
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return


def cursor_project_key(workspace: Path) -> str:
    """Return Cursor's project-state directory key for *workspace*."""
    return str(workspace).strip("/").replace("/", "-") or "root"


def enable_mcp_for_workspace(workspace: Path, server_name: str = _MCP_SERVER_NAME) -> None:
    """Ensure Cursor does not keep the Omnigent MCP disabled for this workspace."""
    disabled_path = (
        Path.home() / ".cursor" / "projects" / cursor_project_key(workspace) / "mcp-disabled.json"
    )
    try:
        raw = json.loads(disabled_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, list) or server_name not in raw:
        return
    updated = [item for item in raw if item != server_name]
    tmp = disabled_path.with_suffix(disabled_path.suffix + ".tmp")
    tmp.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, disabled_path)


def allow_mcp_tools_in_cli_config(server_name: str = _MCP_SERVER_NAME) -> None:
    """Allow Omnigent MCP tool calls in Cursor's CLI permission config.

    *server_name* is the id cursor-agent gives the server: ``omnigent`` for the
    project ``mcp.json``, :data:`PLUGIN_MCP_SERVER_ID` for the plugin route.
    """
    path = Path.home() / ".cursor" / "cli-config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(config, dict):
        return
    permissions = config.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        return
    allow = permissions.setdefault("allow", [])
    if not isinstance(allow, list):
        return
    existing = {item for item in allow if isinstance(item, str)}
    for tool_name in _CURSOR_AUTO_APPROVE_TOOLS:
        entry = f"Mcp({server_name}:{tool_name})"
        if entry not in existing:
            allow.append(entry)
            existing.add(entry)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_tmux_target(
    bridge_dir: Path,
    *,
    socket_path: Path,
    tmux_target: str,
    pid: int | None = None,
) -> None:
    """Advertise the tmux socket + target for the running Cursor terminal."""
    _ensure_dir(bridge_dir)
    payload: _JsonObject = {
        "socket_path": str(socket_path),
        "tmux_target": tmux_target,
        "updated_at": time.time(),
    }
    if pid is not None:
        payload["pid"] = pid
    tmp = bridge_dir / (_TMUX_FILE + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, bridge_dir / _TMUX_FILE)


def read_tmux_info(bridge_dir: Path) -> dict[str, str] | None:
    """Return ``{socket_path, tmux_target}`` from ``tmux.json``, or ``None``."""
    try:
        raw = (bridge_dir / _TMUX_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    socket_path = data.get("socket_path")
    tmux_target = data.get("tmux_target")
    if (
        isinstance(socket_path, str)
        and socket_path
        and isinstance(tmux_target, str)
        and tmux_target
    ):
        return {"socket_path": socket_path, "tmux_target": tmux_target}
    return None


def _wait_for_tmux_info(bridge_dir: Path, *, timeout_s: float) -> dict[str, str]:
    """Block until ``tmux.json`` is advertised, or raise on timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        info = read_tmux_info(bridge_dir)
        if info is not None:
            return info
        time.sleep(_POLL_INTERVAL_S)
    raise RuntimeError(f"cursor-native tmux target was not advertised within {timeout_s:.0f}s")


def _run_tmux(socket_path: str, *args: str) -> None:
    """Invoke ``tmux -S <socket> <args...>`` and raise on failure."""
    try:
        proc = subprocess.run(
            ["tmux", "-S", socket_path, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_TMUX_SEND_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"tmux command timed out after {_TMUX_SEND_TIMEOUT_S}s") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "<no output>"
        raise RuntimeError(f"tmux command failed (rc={proc.returncode}): {detail}")


def _capture_pane(socket_path: str, tmux_target: str) -> str:
    """Capture the visible pane contents; ``""`` on any failure (treat as not-ready)."""
    try:
        proc = subprocess.run(
            ["tmux", "-S", socket_path, "capture-pane", "-p", "-t", tmux_target],
            check=False,
            capture_output=True,
            text=True,
            timeout=_TMUX_SEND_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _paste_payload_bytes(text: str) -> bytes:
    r"""Encode text for ``tmux load-buffer``: line breaks → CR, tabs kept, other
    control bytes dropped (a stray ESC would close the bracketed-paste early)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    body = bytearray()
    for ch in normalized:
        if ch == "\n":
            body.append(0x0D)
            continue
        if ch == "\t":
            body.append(0x09)
            continue
        if ord(ch) < 0x20:
            continue
        body.extend(ch.encode("utf-8"))
    return bytes(body)


def _session_alive(socket_path: str, tmux_target: str) -> bool:
    """Return whether the tmux session/pane still exists (the TUI is running)."""
    try:
        proc = subprocess.run(
            ["tmux", "-S", socket_path, "has-session", "-t", tmux_target],
            check=False,
            capture_output=True,
            text=True,
            timeout=_TMUX_SEND_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def capture_cursor_pane(bridge_dir: Path) -> str | None:
    """
    Return the visible Cursor pane text, or ``None`` if the TUI is not running.

    Reused by the runner-side approval mirror
    (:mod:`omnigent.harnesses.cursor_native.permissions`) to detect cursor-agent's native
    tool-approval prompts. ``None`` (no advertised tmux target, or a dead pane)
    is distinct from ``""`` (a live but empty capture) so the caller can skip
    polling a TUI that has not started yet or has exited.

    :param bridge_dir: The cursor-native bridge dir holding ``tmux.json``.
    :returns: The captured pane text, or ``None`` when no live pane exists.
    """
    info = read_tmux_info(bridge_dir)
    if info is None:
        return None
    socket_path, tmux_target = info["socket_path"], info["tmux_target"]
    if not _session_alive(socket_path, tmux_target):
        return None
    return _capture_pane(socket_path, tmux_target)


def send_cursor_pane_keys(bridge_dir: Path, *keys: str) -> None:
    """
    Send one or more keys to the Cursor pane (tmux ``send-keys``).

    Used by the approval mirror to answer cursor-agent's native prompt from a
    web verdict, e.g. ``"y"`` to approve or ``"Escape"`` to reject. Each key is
    a tmux key name/argument (not bracketed-paste data), so multi-byte keys like
    ``"Escape"`` are interpreted, not typed literally.

    :param bridge_dir: The cursor-native bridge dir holding ``tmux.json``.
    :param keys: tmux key arguments, e.g. ``"y"`` or ``"Escape"``.
    :raises RuntimeError: If the tmux target is not advertised or the
        ``send-keys`` invocation fails.
    """
    info = read_tmux_info(bridge_dir)
    if info is None:
        raise RuntimeError("cursor-native tmux target not advertised")
    _run_tmux(info["socket_path"], "send-keys", "-t", info["tmux_target"], *keys)


def _submit_needle(content: str) -> str:
    """A stable single-line substring used to confirm the paste rendered in the pane."""
    for line in content.splitlines():
        stripped = line.strip()
        if len(stripped) >= 4:
            return stripped[:24]
    stripped = content.strip()
    return stripped[:24] if len(stripped) >= 4 else ""


def _settle_pane(
    socket_path: str,
    tmux_target: str,
    *,
    timeout_s: float,
    require_stable: bool = False,
) -> bool:
    """Wait until the Cursor input box is ready to receive a paste.

    Accepts the first-run "Trust this workspace" modal (sends ``a`` at most once)
    so the input box can mount, then waits for an idle/running input marker. With
    *require_stable* (a cold TUI) the pane must also stay byte-identical, marker
    visible, for :data:`_COMPOSER_READY_STABLE_CAPTURES` consecutive captures.

    :returns: Whether readiness was seen before *timeout_s*. Warm callers ignore
        a ``False`` and fall through (mid-turn steering may show no placeholder).
    """
    deadline = time.monotonic() + timeout_s
    trust_accepted = False
    stable_pane: str | None = None
    stable_count = 0
    while time.monotonic() < deadline:
        pane = _capture_pane(socket_path, tmux_target)
        if any(marker in pane for marker in _IDLE_MARKERS):
            if not require_stable:
                return True
            if pane == stable_pane:
                stable_count += 1
            else:
                stable_pane, stable_count = pane, 1
            if stable_count >= _COMPOSER_READY_STABLE_CAPTURES:
                return True
        else:
            stable_pane, stable_count = None, 0
            # One-shot, only when no input marker is up (so a later transcript that
            # merely echoes the phrase can't spray repeated keystrokes into the TUI).
            if not trust_accepted and _TRUST_MARKER in pane:
                trust_accepted = True
                with contextlib.suppress(RuntimeError):
                    _run_tmux(socket_path, "send-keys", "-t", tmux_target, "a")
        time.sleep(_POLL_INTERVAL_S)
    return False


def _tmux_instance_key(bridge_dir: Path) -> str | None:
    """Identify the advertised TUI instance: a hash of ``tmux.json`` (rewritten per launch)."""
    try:
        raw = (bridge_dir / _TMUX_FILE).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(raw).hexdigest()


def _composer_ready_seen(bridge_dir: Path) -> bool:
    """Whether this TUI instance's composer was already seen stably ready."""
    key = _tmux_instance_key(bridge_dir)
    if key is None:
        return False
    try:
        data = json.loads((bridge_dir / _COMPOSER_READY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("tmux") == key


def _mark_composer_ready(bridge_dir: Path) -> None:
    """Stamp this TUI instance as warm (best effort: a lost stamp only re-waits)."""
    key = _tmux_instance_key(bridge_dir)
    if key is None:
        return
    tmp = bridge_dir / (_COMPOSER_READY_FILE + ".tmp")
    with contextlib.suppress(OSError):
        tmp.write_text(json.dumps({"tmux": key}), encoding="utf-8")
        os.replace(tmp, bridge_dir / _COMPOSER_READY_FILE)


def _clear_composer(socket_path: str, tmux_target: str) -> None:
    """Empty the cursor-agent composer of any leftover draft before a paste.

    cursor-agent restores the interrupted prompt back into the composer when a
    turn is cancelled (Stop button -> :func:`inject_interrupt`), and its input
    widget ignores the readline ``C-a``/``C-k``/``C-u`` keys we'd otherwise use
    to clear a line — only ``Backspace`` deletes. So jump to the end (``End``)
    and flood ``Backspace`` in ``send-keys -N`` bursts until the pane stops
    changing (the draft is gone) or a generous round cap is hit.

    A visible input placeholder means the composer is already empty, so no key
    is sent at all: on a TUI that is still booting the burst is taken as literal
    ``\x7f`` text ahead of the next paste, which the unchanged pane cannot reveal.
    """
    pane = _capture_pane(socket_path, tmux_target)
    if any(marker in pane for marker in _IDLE_MARKERS):
        return
    _run_tmux(socket_path, "send-keys", "-t", tmux_target, "End")
    previous = _capture_pane(socket_path, tmux_target)
    for _ in range(_COMPOSER_CLEAR_MAX_ROUNDS):
        _run_tmux(
            socket_path,
            "send-keys",
            "-t",
            tmux_target,
            "-N",
            str(_COMPOSER_CLEAR_CHUNK),
            "BSpace",
        )
        current = _capture_pane(socket_path, tmux_target)
        # Once a burst no longer changes the pane, the composer is empty —
        # further Backspaces are no-ops, so stop.
        if current == previous:
            return
        previous = current


def inject_user_message(
    bridge_dir: Path,
    *,
    content: str,
    timeout_s: float = _TMUX_READY_TIMEOUT_S,
) -> None:
    """Deliver a web-UI user message into the Cursor TUI via a tmux bracketed paste.

    Clears any leftover draft, pastes *content* (multi-line safe via
    ``load-buffer``/``paste-buffer -p`` so interior newlines stay data, not
    submits), settles, then submits with Enter.

    :param bridge_dir: The cursor-native bridge dir holding ``tmux.json``.
    :param content: User text (non-empty).
    :param timeout_s: Per-readiness-gate timeout.
    :raises RuntimeError: If the tmux target is never advertised, a tmux
        command fails, or a freshly launched TUI's input box is not stably ready
        within *timeout_s* (nothing is typed in that case).
    """
    if not content:
        raise RuntimeError("cursor-native injection requires non-empty content")
    info = _wait_for_tmux_info(bridge_dir, timeout_s=timeout_s)
    socket_path = info["socket_path"]
    tmux_target = info["tmux_target"]
    # Fast-fail if the TUI already exited: otherwise _settle_pane polls a dead
    # pane for the full timeout and the web message is silently lost. A clear
    # error lets run_turn surface ExecutorError so the UI can say "restart".
    if not _session_alive(socket_path, tmux_target):
        raise RuntimeError(
            "cursor terminal is no longer running (the TUI exited); restart the session"
        )
    # Admission point for completion receipts: refuses when the input fence is
    # closed and logs the prompt for opted-in sessions (no-op otherwise).
    cursor_native_status.record_injection(bridge_dir, content, kind="message")
    # A freshly launched TUI must be stably ready before any key reaches it; if
    # it never is, fail before typing anything (the logged injection then holds
    # as undelivered — never retried here).
    cold = not _composer_ready_seen(bridge_dir)
    ready = _settle_pane(socket_path, tmux_target, timeout_s=timeout_s, require_stable=cold)
    if cold:
        if not ready:
            raise RuntimeError(
                f"cursor input box was not stably ready within {timeout_s:.0f}s after launch; "
                "the message was not sent"
            )
        _mark_composer_ready(bridge_dir)
    # Clear any leftover draft (e.g. the prompt cursor-agent restores into the
    # composer after a cancelled turn) so it can't prepend the new message.
    _clear_composer(socket_path, tmux_target)
    with tempfile.NamedTemporaryFile(
        dir=bridge_dir, prefix="paste_", suffix=".bin", delete=False
    ) as paste_file:
        # Trailing newline absorbs any trailing backslash so it can't escape Enter.
        paste_file.write(_paste_payload_bytes(content + "\n"))
        paste_path = paste_file.name
    try:
        _run_tmux(socket_path, "load-buffer", "-b", _PASTE_BUFFER, paste_path)
        _run_tmux(
            socket_path,
            "paste-buffer",
            "-p",  # bracketed-paste markers — the TUI keeps newlines as data
            "-d",  # drop the buffer after pasting
            "-b",
            _PASTE_BUFFER,
            "-t",
            tmux_target,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(paste_path)
    # Wait until the paste is visibly committed to the input box before Enter.
    # Submitting mid-paste folds the Enter in as a newline (the cursor TUI
    # coalesces rapid stdin bursts), leaving the message unsent. Poll for the
    # text, then submit; fall through to a blind submit if no needle is usable.
    needle = _submit_needle(content)
    if needle:
        deadline = time.monotonic() + _PASTE_COMMIT_TIMEOUT_S
        while time.monotonic() < deadline:
            if needle in _capture_pane(socket_path, tmux_target):
                break
            time.sleep(_POLL_INTERVAL_S)
    time.sleep(_PASTE_SETTLE_S)
    _run_tmux(socket_path, "send-keys", "-t", tmux_target, "Enter")


def inject_model_command(
    bridge_dir: Path,
    *,
    model: str,
    expected_display_name: str | None = None,
    timeout_s: float = _TMUX_READY_TIMEOUT_S,
) -> None:
    """Switch the live Cursor model by driving the TUI ``/model`` picker.

    cursor-agent's ``--model`` flag is baked in at spawn, so a web-UI / REPL
    model switch on a *running* pane can't be applied by re-reading the
    persisted ``model_override`` — it has to be typed into the TUI. Typing
    ``/model <id>`` opens cursor-agent's model picker filtered to *model* and
    Enter selects the (now top) match; verified live that an exact model id
    selects exactly that model (e.g. ``gpt-5.2`` → "GPT-5.2 Medium"). This is
    the cursor analog of claude-native's ``inject_slash_command('/model …')``.

    :param bridge_dir: The cursor-native bridge dir holding ``tmux.json``.
    :param model: cursor-agent base model id, e.g. ``"gpt-5.2"`` (derived from
        ``cursor-agent models`` by stripping effort variants).
    :param expected_display_name: Display name from the already-fetched live
        picker catalog. ``None`` refreshes the catalog before switching.
    :param timeout_s: Per-readiness-gate timeout.
    :raises RuntimeError: If the tmux target is never advertised, the TUI has
        exited, a tmux command fails, or the picker reports no match for *model*
        (an unavailable/typo'd id) — in which case the picker is dismissed and
        the model is left unchanged rather than mis-selected.
    """
    model = model.strip()
    if not model:
        raise RuntimeError("cursor-native model switch requires a non-empty model id")
    if expected_display_name is None:
        try:
            expected_display_name = next(
                option["displayName"]
                for option in _live_cursor_model_options()
                if option.get("id") == model
            )
        except (click.ClickException, OSError, subprocess.SubprocessError, ValueError) as exc:
            raise RuntimeError("cursor-native could not verify the live model catalog") from exc
        except StopIteration as exc:
            raise RuntimeError(
                f"cursor model {model!r} is not available in the live catalog"
            ) from exc
    info = _wait_for_tmux_info(bridge_dir, timeout_s=timeout_s)
    socket_path = info["socket_path"]
    tmux_target = info["tmux_target"]
    if not _session_alive(socket_path, tmux_target):
        raise RuntimeError(
            "cursor terminal is no longer running (the TUI exited); restart the session"
        )
    cursor_native_status.record_injection(bridge_dir, f"/model {model}", kind="model_command")
    _settle_pane(socket_path, tmux_target, timeout_s=timeout_s)
    # Clear any leftover draft so the slash command isn't appended to it.
    # cursor-agent's composer ignores the readline C-a/C-k keys, so this floods
    # Backspace (see _clear_composer); a bare "/model <id>" is what opens the
    # picker, whereas "<draft>/model <id>" would not.
    _clear_composer(socket_path, tmux_target)
    # ``-l`` sends the command as literal characters so ``/`` opens the slash
    # menu and the id filters the picker rather than being parsed as key names.
    _run_tmux(socket_path, "send-keys", "-t", tmux_target, "-l", f"/model {model}")
    # Gate on the picker's *filter result*, not the echoed command: the composer
    # line itself contains ``model``, so a naive ``model in pane`` check passes
    # instantly off the echo and never confirms a match landed. Poll for cursor's
    # "Models matching" header (≥1 match) or "No matches", then settle so the
    # highlight stabilizes before Enter. The composer debounces input (~1.5s), so
    # both the filter and the highlight need time to resolve.
    deadline = time.monotonic() + _PASTE_COMMIT_TIMEOUT_S
    while time.monotonic() < deadline:
        pane = _capture_pane(socket_path, tmux_target)
        if _PICKER_NO_MATCH_MARKER in pane or _PICKER_MATCH_MARKER in pane:
            break
        time.sleep(_POLL_INTERVAL_S)
    time.sleep(_MODEL_PICKER_SETTLE_S)
    # Re-read after the settle: a transient "No matches" can flash mid-filter,
    # and a real match may only resolve once the debounce fires.
    settled_pane = _capture_pane(socket_path, tmux_target)
    if _PICKER_NO_MATCH_MARKER in settled_pane:
        # Dismiss the picker and clear the composer so the literal "/model <id>"
        # can't be submitted as a chat message, then fail loudly so the web
        # surfaces an honest error instead of silently selecting nothing.
        _run_tmux(socket_path, "send-keys", "-t", tmux_target, "Escape")
        _clear_composer(socket_path, tmux_target)
        raise RuntimeError(
            f"cursor model {model!r} is not available in the picker (no match); "
            "the model was not switched"
        )
    highlighted_row = _picker_highlighted_row(settled_pane)
    if (
        _PICKER_MATCH_MARKER not in settled_pane
        or highlighted_row is None
        or not _picker_row_matches_display(highlighted_row, expected_display_name)
    ):
        _run_tmux(socket_path, "send-keys", "-t", tmux_target, "Escape")
        _clear_composer(socket_path, tmux_target)
        raise RuntimeError(
            f"cursor model {model!r} did not resolve to its exact picker row; "
            "the model was not switched"
        )
    _run_tmux(socket_path, "send-keys", "-t", tmux_target, "Enter")


def _live_cursor_model_options() -> list[CursorModelOption]:
    """Read the same live catalog that supplies Cursor's Web picker."""
    from omnigent.harnesses.cursor_native.main import list_cursor_cli_model_options

    return list_cursor_cli_model_options()


def _picker_highlighted_row(pane: str) -> str | None:
    """Return the text of Cursor's currently highlighted picker row."""
    for line in pane.splitlines():
        stripped = line.strip()
        if stripped.startswith("→"):
            return stripped.removeprefix("→").strip()
    return None


def _picker_row_matches_display(row: str, display_name: str) -> bool:
    """Match a base display name without accepting a longer-name prefix."""
    normalized_row = " ".join(row.casefold().split())
    normalized_display = " ".join(display_name.casefold().split())
    return normalized_row == normalized_display or normalized_row.startswith(
        f"{normalized_display} "
    )


def _wait_for_pane_settle(socket_path: str, tmux_target: str, *, timeout_s: float) -> None:
    """Best-effort wait until the pane stops changing across two captures.

    Used after a cancel so the restored draft (and any final generation output)
    has landed before we clear the composer. Falls through after *timeout_s*
    rather than raising — the clear that follows is a no-op on an empty composer.
    """
    deadline = time.monotonic() + timeout_s
    previous = _capture_pane(socket_path, tmux_target)
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        current = _capture_pane(socket_path, tmux_target)
        if current and current == previous:
            return
        previous = current


def inject_interrupt(bridge_dir: Path, *, timeout_s: float = _TMUX_READY_TIMEOUT_S) -> None:
    """Cancel the in-flight Cursor turn and clear the composer.

    Sends ``Escape`` to stop the running turn, then clears the input box:
    cursor-agent restores the interrupted prompt into the composer on cancel, so
    without this the leftover prompt sits in the box and prepends the next
    message (the web UI's Stop button would otherwise leave a half-sent draft).
    The harness ``run_turn`` returns right after the paste, so the runner's
    in-process cancel floor can't reach the turn — this is the analog of
    :func:`inject_user_message` for the web UI's Stop button.

    :raises RuntimeError: If the tmux target is not advertised or send-keys fails.
    """
    info = _wait_for_tmux_info(bridge_dir, timeout_s=timeout_s)
    socket_path = info["socket_path"]
    tmux_target = info["tmux_target"]
    # No ``-l``: tmux must interpret ``Escape`` as a key name.
    _run_tmux(socket_path, "send-keys", "-t", tmux_target, "Escape")
    # Let the cancel land and the restored draft settle, then clear it. The
    # next injection also clears (defense in depth), but clearing here means the
    # composer is empty the moment the user looks at the TUI after pressing Stop.
    _wait_for_pane_settle(socket_path, tmux_target, timeout_s=_INTERRUPT_SETTLE_TIMEOUT_S)
    _clear_composer(socket_path, tmux_target)


def kill_session(bridge_dir: Path, *, timeout_s: float = _TMUX_READY_TIMEOUT_S) -> None:
    """Hard-stop the Cursor session by killing its tmux session.

    Terminates ``cursor-agent`` and the pane outright — the analog of the
    user manually exiting the attached TUI, for the web UI's "Stop session"
    affordance. Mirrors :func:`omnigent.harnesses.claude_native.bridge.kill_session`.

    :raises RuntimeError: If the tmux target is not advertised or kill-session fails.
    """
    info = _wait_for_tmux_info(bridge_dir, timeout_s=timeout_s)
    # Delegate pid-resolution + kill-session + leftover SIGKILL escalation to
    # the shared native-tmux-kill helper (mirrors claude-native). The bridge's
    # own _run_tmux stays authoritative for the kill-session call and errors.
    native_tmux_kill.kill_session_with_escalation(
        bridge_dir,
        socket_path=info["socket_path"],
        tmux_target=info["tmux_target"],
        kill_session_fn=lambda socket, target: _run_tmux(socket, "kill-session", "-t", target),
    )


def native_input_ready(session_id: str, instance: TerminalInstance) -> bool:
    """Provider ``input_ready_probe``: Cursor's composer placeholder is on screen.

    :param session_id: Omnigent conversation id (unused; the pane is enough).
    :param instance: The live terminal; the watcher already captured its pane.
    """
    del session_id
    pane = instance.last_pane_text() or ""
    return any(marker in pane for marker in _IDLE_MARKERS)
