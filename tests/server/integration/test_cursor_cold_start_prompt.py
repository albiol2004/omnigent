"""First-prompt delivery into a cold cursor TUI (live canary finding F1).

Real: ``CursorNativeExecutor`` and the bridge driving a real tmux pane, and
receipt admission (``record_injection``) on an opted-in bridge dir. Substituted:
the cursor-agent TUI (``cursor_fake_tui.py`` with its ``cold_start_s`` knob,
which paints the placeholder before its key handler is wired, as observed live:
a Backspace burst landed as 200 literal DELs ahead of an intact prompt).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from omnigent.harnesses.cursor_native import bridge as cbridge
from omnigent.harnesses.cursor_native import status
from omnigent.inner import cursor_native_executor
from omnigent.inner.cursor_native_executor import CursorNativeExecutor
from omnigent.inner.executor import ExecutorError, TurnComplete

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux"),
]

_FAKE_TUI = Path(__file__).with_name("cursor_fake_tui.py")


class _ColdPane:
    """A freshly launched fake cursor TUI in a real tmux server on a private socket."""

    def __init__(self, tmp_path: Path, cfg: dict[str, Any]) -> None:
        self.bridge_dir = tmp_path / "bridge"
        self.bridge_dir.mkdir()
        # Opted in, so every admitted injection is logged like a live launch.
        status.write_receipt_epoch(self.bridge_dir, int(time.time() * 1000))
        ws = tmp_path / "ws"
        ws.mkdir()
        chats = tmp_path / "chats"
        chat_id = "chat-" + uuid.uuid4().hex[:12]
        self.store = chats / hashlib.md5(str(ws).encode()).hexdigest() / chat_id / "store.db"
        self.log = tmp_path / "tui.jsonl"
        cfg_path = tmp_path / "tui.json"
        cfg_path.write_text(json.dumps({"turn_s": 0.5, "bracketed_paste": True, **cfg}))
        self._sock_dir = Path(tempfile.mkdtemp(prefix="omg-tmux-"))
        self.sock = self._sock_dir / "s.sock"
        cmd = " ".join(
            [
                sys.executable,
                str(_FAKE_TUI),
                "--bridge-dir",
                str(self.bridge_dir),
                "--workspace",
                str(ws),
                "--chats",
                str(chats),
                "--chat-id",
                chat_id,
                "--cfg",
                str(cfg_path),
                "--log",
                str(self.log),
            ]
        )
        subprocess.run(
            [
                *("tmux", "-S", str(self.sock), "-f", "/dev/null", "new-session", "-d"),
                *("-s", "cur", "-x", "200", "-y", "50", cmd),
            ],
            check=True,
            env={**os.environ},
        )
        cbridge.write_tmux_target(self.bridge_dir, socket_path=self.sock, tmux_target="cur")

    def events(self, ev: str | None = None) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]
        return [e for e in rows if ev is None or e["ev"] == ev]

    def user_rows(self) -> list[str]:
        """``<user_query>`` bodies committed to the cursor-shaped store, in order."""
        if not self.store.exists():
            return []
        con = sqlite3.connect(f"file:{self.store}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT data FROM blobs ORDER BY rowid").fetchall()
        except sqlite3.OperationalError:
            return []  # store file created, table not yet
        finally:
            con.close()
        out = []
        for blob in (json.loads(d) for (d,) in rows):
            if blob.get("role") == "user":
                text = blob["content"][0]["text"]
                out.append(text.removeprefix("<user_query>\n").removesuffix("\n</user_query>"))
        return out

    def injects(self) -> list[dict[str, Any]]:
        path = self.bridge_dir / status.INJECT_FILE
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def type_draft(self, text: str) -> None:
        """A local user leaves an unsent draft in the composer."""
        subprocess.run(
            ["tmux", "-S", str(self.sock), "send-keys", "-t", "cur", "-l", text], check=True
        )

    def close(self) -> None:
        subprocess.run(["tmux", "-S", str(self.sock), "kill-server"], check=False)
        shutil.rmtree(self._sock_dir, ignore_errors=True)


@pytest.fixture
def pane_factory(tmp_path: Path) -> Any:
    panes: list[_ColdPane] = []

    def _make(cfg: dict[str, Any]) -> _ColdPane:
        pane = _ColdPane(tmp_path, cfg)
        panes.append(pane)
        return pane

    yield _make
    for pane in panes:
        pane.close()


async def _wait_for(cond: Callable[[], Any], timeout: float, what: str) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = cond()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


async def _run_turn(executor: CursorNativeExecutor, prompt: str) -> list[Any]:
    return [ev async for ev in executor.run_turn([{"role": "user", "content": prompt}], [], "")]


def _prompt() -> str:
    return f"CANARY LEAD nonce={uuid.uuid4().hex}: implement slice S and run the tests"


def _assert_delivered_intact(pane: _ColdPane, prompts: list[str]) -> None:
    rows = pane.user_rows()
    assert rows == prompts, rows
    assert not any("\x7f" in row for row in rows)
    injects = [i for i in pane.injects() if i["kind"] == "message"]
    assert [i["norm_sha256"] for i in injects] == [status.prompt_binding_sha(p) for p in prompts]
    assert [status.prompt_binding_sha(r) for r in rows] == [i["norm_sha256"] for i in injects]
    assert len(pane.events("submit")) == len(prompts)


@pytest.mark.parametrize("cold_paste", ["keep", "drop"])
async def test_cold_start_first_prompt_waits_for_ready_and_lands_once(
    pane_factory: Any, cold_paste: str
) -> None:
    """Dispatch right at launch: nothing is typed while the TUI boots; one intact submit.

    ``keep`` is the live2 shape (DEL burst kept as text, paste intact: the stored
    row was 200 DELs + prompt); ``drop`` is the lost-paste shape (live1).
    """
    pane = pane_factory({"cold_start_s": 2.0, "cold_start_paste": cold_paste})
    prompt = _prompt()

    events = await _run_turn(CursorNativeExecutor(pane.bridge_dir), prompt)

    assert [type(e) for e in events] == [TurnComplete]
    await _wait_for(lambda: pane.user_rows(), 10, "user row")
    assert pane.events("input"), "the paste reached the pane"
    assert not [e for e in pane.events("input") if e["cold"]], "keys sent to a booting TUI"
    assert sum(e["dels"] for e in pane.events("input")) == 0, "Backspace sent to empty composer"
    _assert_delivered_intact(pane, [prompt])


async def test_warm_steering_stays_fast_while_the_pane_keeps_changing(
    pane_factory: Any,
) -> None:
    """After the first readiness, a mid-turn message does not wait for a settled pane."""
    pane = pane_factory({"cold_start_s": 1.0, "busy_ticker": True, "turn_s": 20.0})
    executor = CursorNativeExecutor(pane.bridge_dir)
    first, second = _prompt(), _prompt()
    await _run_turn(executor, first)
    await _wait_for(lambda: pane.events("turn_start"), 10, "turn 1 start")

    started = time.monotonic()
    assert await executor.enqueue_session_message("k", second)
    elapsed = time.monotonic() - started

    # A stability gate here would never pass (the footer ticks) and would time out.
    assert elapsed < 3.0, elapsed
    await _wait_for(lambda: len(pane.events("submit")) == 2, 5, "queued submit")
    assert [e["text"] for e in pane.events("submit")] == [first, second]
    assert sum(e["dels"] for e in pane.events("input")) == 0


async def test_nonempty_composer_is_still_cleared(
    pane_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leftover draft hides the placeholder, so the Backspace clear still runs."""
    # A draft hides the placeholder, so the (unchanged) warm settle waits out its
    # timeout before falling through; shorten it to keep the test quick.
    monkeypatch.setattr(
        cursor_native_executor,
        "inject_user_message",
        functools.partial(cbridge.inject_user_message, timeout_s=3.0),
    )
    pane = pane_factory({"cold_start_s": 1.0})
    executor = CursorNativeExecutor(pane.bridge_dir)
    first, second = _prompt(), _prompt()
    await _run_turn(executor, first)
    await _wait_for(lambda: pane.events("stop_hook"), 10, "turn 1 end")
    pane.type_draft("half-typed local draft")
    await _wait_for(
        lambda: "half-typed" in (cbridge.capture_cursor_pane(pane.bridge_dir) or ""),
        5,
        "draft rendered",
    )

    await _run_turn(executor, second)

    await _wait_for(lambda: len(pane.user_rows()) == 2, 10, "second user row")
    assert sum(e["dels"] for e in pane.events("input") if not e["cold"]) > 0
    _assert_delivered_intact(pane, [first, second])


async def test_readiness_timeout_fails_before_typing_and_does_not_retry(
    pane_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A TUI that never settles gets no keystrokes: a clean, logged, unsent failure."""
    pane = pane_factory({"cold_start_s": 60.0})
    monkeypatch.setattr(
        cursor_native_executor,
        "inject_user_message",
        functools.partial(cbridge.inject_user_message, timeout_s=2.0),
    )

    events = await _run_turn(CursorNativeExecutor(pane.bridge_dir), _prompt())

    assert len(events) == 1 and isinstance(events[0], ExecutorError), events
    assert "not stably ready" in events[0].message
    await asyncio.sleep(0.5)
    assert pane.events("input") == [], "nothing may be typed into a booting TUI"
    assert pane.events("submit") == [] and pane.user_rows() == []
    # Admitted once (so a receipt consumer holds on it) and never re-sent.
    assert len(pane.injects()) == 1
    assert not (pane.bridge_dir / cbridge._COMPOSER_READY_FILE).exists()


async def test_static_cold_window_cannot_corrupt_the_prompt(pane_factory: Any) -> None:
    """Limit of the readiness gate: a boot screen that looks settled is not detectable.

    The paste may then be lost, but no Backspace is ever sent to the empty
    composer, so no DEL-prefixed copy can be stored and bind or execute.
    """
    pane = pane_factory(
        {"cold_start_s": 4.0, "cold_start_ticker": False, "cold_start_paste": "drop"}
    )
    prompt = _prompt()

    await _run_turn(CursorNativeExecutor(pane.bridge_dir), prompt)
    await asyncio.sleep(5.0)

    assert sum(e["dels"] for e in pane.events("input")) == 0
    assert not any("\x7f" in row for row in pane.user_rows())
    assert pane.user_rows() in ([], [prompt])
    assert len(pane.injects()) == 1
