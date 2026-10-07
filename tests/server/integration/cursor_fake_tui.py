"""Scripted stand-in for the cursor-agent TUI, run inside a real tmux pane.

Harness for ``test_cursor_receipt_binding_e2e`` (not product code). It models
only the externally visible behaviour the receipt/fence design depends on:

* bracketed paste + Enter submits a prompt; a prompt submitted while a turn is
  running is QUEUED and runs after the current turn (cursor's queued follow-ups);
* each turn appends a ``<user_query>`` user blob and an assistant blob to a
  cursor-shaped ``blobs`` SQLite store under ``<chats>/md5(ws)/<chat>/store.db``;
* at turn end it runs the REAL Omnigent stop hook CLI
  (``omnigent.harnesses.cursor_native.usage record-usage``) with a stop payload;
* optionally a second (project) stop hook answers ``followup_message`` after a
  chosen turn, which makes the agent run one more turn with that text — the
  documented cursor ``stop``-hook follow-up loop — firing ``stop`` again.

Config JSON (``--cfg``): ``{"turn_s": float, "turn_s_by_prefix": {prefix: s},
"followup_after_turns": [int], "followup_text": str}``. Optional knobs:

* ``"followup_front": false`` queues the follow-up BEHIND already-queued prompts
  (default in front); which order real cursor uses is unverified;
* ``"user_row_delay_by_origin": {origin: s}`` commits that origin's user row
  ``s`` seconds into its turn (still before its ``stop``, so B1 holds);
* ``"hooks_from_config": true`` replaces the scripted hooks above: at each turn
  end the TUI reads the ``stop`` entries of ``<workspace>/.cursor/hooks.json``
  then ``$HOME/.cursor/hooks.json``, runs each through ``/bin/sh -c`` with the
  payload on stdin, and queues any ``followup_message`` one answers. Real
  cursor's load/merge/reload rules are not modelled beyond that;
* ``"cold_start_s": s`` models the live cold-start race: for ``s`` seconds after
  launch the placeholder is already painted but the key handler is not wired, so
  Backspace/DEL bytes are kept as literal (invisible) composer text, and with
  ``"cold_start_paste": "drop"`` pasted text is lost (default ``"keep"``). While
  cold, a boot line ticks every 0.1s unless ``"cold_start_ticker": false`` (a
  static pane that no pane check can tell from ready);
* ``"bracketed_paste": true`` enables bracketed-paste mode like cursor does, so
  a paste stays in the composer until Enter (without it tmux pastes raw text
  and the payload's trailing CR submits it);
* ``"busy_ticker": true`` re-renders a ticking footer while a turn runs, so the
  pane never settles mid-turn (as while cursor streams output).
Every stdin read is logged as ``{"ev": "input", "n", "dels", "cold"}``.
Events are appended to ``--log`` as JSONL for assertions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import sqlite3
import subprocess
import sys
import termios
import threading
import time
import tty
import uuid
from collections import deque
from pathlib import Path

PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"


class Tui:
    def __init__(self, args: argparse.Namespace) -> None:
        self.bridge_dir = args.bridge_dir
        self.workspace = args.workspace
        self.cfg = json.loads(Path(args.cfg).read_text())
        self.log_path = Path(args.log)
        self.chat_dir = (
            Path(args.chats) / hashlib.md5(args.workspace.encode()).hexdigest() / (args.chat_id)
        )
        self.composer = ""
        self.queue: deque[tuple[str, str]] = deque()
        self.busy = False
        self.turns = 0
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.lines: list[str] = []
        self.store: sqlite3.Connection | None = None
        self.t0 = time.monotonic()
        self.cold_until = self.t0 + float(self.cfg.get("cold_start_s", 0.0))

    def cold(self) -> bool:
        return time.monotonic() < self.cold_until

    # ---------------------------------------------------------------- output
    def log(self, **event: object) -> None:
        event["t"] = time.time()
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def render(self) -> None:
        with self.lock:
            out = ["\x1b[2J\x1b[H"]
            out += [line[:150] + "\r\n" for line in self.lines[-20:]]
            tick = int((time.monotonic() - self.t0) * 10)
            if self.cold() and self.cfg.get("cold_start_ticker", True):
                out.append(f"starting {tick}\r\n")
            state = "Generating..." if self.busy else "idle"
            if self.busy and self.cfg.get("busy_ticker"):
                state += f" {tick}"
            out.append(f"[{state}] queued={len(self.queue)}\r\n")
            # Like cursor: control bytes (incl. a literal DEL) are not rendered.
            shown = "".join(
                " " if ch in "\r\n" else ch for ch in self.composer if ch >= " " and ch != "\x7f"
            )
            out.append("> " + (shown if shown else "Add a follow-up") + "\r\n")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    # ----------------------------------------------------------------- store
    def _store(self) -> sqlite3.Connection:
        if self.store is None:
            self.chat_dir.mkdir(parents=True, exist_ok=True)
            (self.chat_dir / "meta.json").write_text(
                json.dumps({"createdAtMs": int(time.time() * 1000)})
            )
            con = sqlite3.connect(str(self.chat_dir / "store.db"), check_same_thread=False)
            con.execute("CREATE TABLE IF NOT EXISTS blobs(id TEXT PRIMARY KEY, data BLOB)")
            con.commit()
            self.store = con
        return self.store

    def blob(self, obj: dict) -> None:
        con = self._store()
        con.execute(
            "INSERT INTO blobs(id, data) VALUES(?, ?)",
            (uuid.uuid4().hex, json.dumps(obj).encode()),
        )
        con.commit()

    # ------------------------------------------------------------------ turns
    def submit(self, text: str, origin: str, front: bool = False) -> None:
        with self.lock:
            (self.queue.appendleft if front else self.queue.append)((text, origin))
            queued_behind_busy = self.busy
        self.log(ev="submit", text=text, origin=origin, queued=queued_behind_busy)
        self.wake.set()

    def _turn_seconds(self, text: str) -> float:
        for prefix, secs in (self.cfg.get("turn_s_by_prefix") or {}).items():
            if text.startswith(prefix):
                return float(secs)
        return float(self.cfg.get("turn_s", 1.0))

    def _run_hook(self, cmd: list[str], payload: dict) -> str:
        proc = subprocess.run(
            cmd, input=json.dumps(payload), capture_output=True, text=True, timeout=60
        )
        return proc.stdout

    def _configured_stop_hooks(self, payload: dict) -> list[str]:
        """Run the configured ``stop`` hooks; return the follow-ups they ask for."""
        followups: list[str] = []
        for path in (
            Path(self.workspace) / ".cursor" / "hooks.json",
            Path(os.environ["HOME"]) / ".cursor" / "hooks.json",
        ):
            try:
                entries = json.loads(path.read_text())["hooks"]["stop"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            for entry in entries:
                out = self._run_hook(["/bin/sh", "-c", entry["command"]], payload)
                self.log(ev="config_stop_hook", path=str(path), command=entry["command"])
                try:
                    answer = json.loads(out) if out.strip() else {}
                except ValueError:
                    answer = {}
                if isinstance(answer, dict) and answer.get("followup_message"):
                    followups.append(str(answer["followup_message"]))
        return followups

    def worker(self) -> None:
        while True:
            self.wake.wait(0.1)
            with self.lock:
                if not self.queue:
                    self.wake.clear()
                    continue
                text, origin = self.queue.popleft()
                self.busy = True
            self.turns += 1
            turn_no = self.turns
            self.log(ev="turn_start", turn=turn_no, text=text, origin=origin)
            self.lines.append(f"USER({origin}): {text}")
            self.render()
            row_delay = float((self.cfg.get("user_row_delay_by_origin") or {}).get(origin, 0.0))
            time.sleep(row_delay)
            self.blob(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": f"<user_query>\n{text}\n</user_query>"}],
                }
            )
            self.log(ev="user_row", turn=turn_no, origin=origin)
            time.sleep(max(0.0, self._turn_seconds(text) - row_delay))
            answer = f"done: {text[:60]}"
            self.blob({"role": "assistant", "content": [{"type": "text", "text": answer}]})
            self.lines.append(f"AGENT: {answer}")
            payload = {
                "status": "completed",
                "conversation_id": self.chat_dir.name,
                "generation_id": uuid.uuid4().hex,
                "loop_count": 0,
            }
            if self.cfg.get("hooks_from_config"):
                followups = self._configured_stop_hooks(payload)
                self.log(ev="stop_hook", turn=turn_no, text=text)
                with self.lock:
                    self.busy = False
                for followup in followups:
                    self.submit(
                        followup,
                        "stop_hook_followup",
                        front=bool(self.cfg.get("followup_front", True)),
                    )
                self.render()
                continue
            # 1) Omnigent's own stop hook (the REAL module/CLI under test).
            self._run_hook(
                [
                    sys.executable,
                    "-m",
                    "omnigent.harnesses.cursor_native.usage",
                    "record-usage",
                    "--bridge-dir",
                    self.bridge_dir,
                ],
                payload,
            )
            self.log(ev="stop_hook", turn=turn_no, text=text)
            if turn_no in (self.cfg.get("double_stop_turns") or []):
                # Hypothetical: a second stop firing for the same turn (no new user row).
                self._run_hook(
                    [
                        sys.executable,
                        "-m",
                        "omnigent.harnesses.cursor_native.usage",
                        "record-usage",
                        "--bridge-dir",
                        self.bridge_dir,
                    ],
                    {**payload, "generation_id": uuid.uuid4().hex},
                )
                self.log(ev="stop_hook_dup", turn=turn_no, text=text)
            # 2) An optional workspace/project stop hook that asks for a follow-up.
            with self.lock:
                self.busy = False
            if turn_no in (self.cfg.get("followup_after_turns") or []):
                self.submit(
                    self.cfg.get("followup_text", "Continue and verify."),
                    "stop_hook_followup",
                    front=bool(self.cfg.get("followup_front", True)),
                )
            self.render()

    def ticker(self) -> None:
        was_cold = self.cold()
        while True:
            time.sleep(0.1)
            cold = self.cold()
            ticking = (cold and self.cfg.get("cold_start_ticker", True)) or (
                self.busy and self.cfg.get("busy_ticker")
            )
            if ticking or (was_cold and not cold):
                self.render()
            was_cold = cold

    # ------------------------------------------------------------------ input
    def input_loop(self) -> None:
        fd = sys.stdin.fileno()
        buf = b""
        in_paste = False
        while True:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                chunk = os.read(fd, 65536)
                if not chunk:
                    return
                buf += chunk
                self.log(ev="input", n=len(chunk), dels=chunk.count(b"\x7f"), cold=self.cold())
            while buf:
                if in_paste:
                    keep = not (self.cold() and self.cfg.get("cold_start_paste") == "drop")
                    end = buf.find(PASTE_END)
                    if end < 0:
                        if keep:
                            self.composer += buf.decode("utf-8", "replace")
                        buf = b""
                        break
                    if keep:
                        self.composer += buf[:end].decode("utf-8", "replace")
                    buf = buf[end + len(PASTE_END) :]
                    in_paste = False
                    continue
                if buf.startswith(PASTE_START):
                    in_paste = True
                    buf = buf[len(PASTE_START) :]
                    continue
                if buf.startswith(b"\x1b"):
                    # Drop a CSI/SS3 sequence (End etc.) or a lone Escape.
                    if len(buf) >= 3 and buf[1:2] in (b"[", b"O"):
                        i = 2
                        while i < len(buf) and not (0x40 <= buf[i] <= 0x7E):
                            i += 1
                        buf = buf[i + 1 :]
                    else:
                        buf = buf[1:]
                    continue
                ch, buf = buf[:1], buf[1:]
                if ch in (b"\r", b"\n"):
                    text = self.composer.strip("\n").strip()
                    self.composer = ""
                    if text:
                        self.submit(text, "pane")
                elif ch in (b"\x7f", b"\x08") and self.cold():
                    self.composer += "\x7f"  # not wired yet: taken as text
                elif ch in (b"\x7f", b"\x08"):
                    self.composer = self.composer[:-1]
                elif ch >= b" ":
                    self.composer += ch.decode("utf-8", "replace")
            self.render()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bridge-dir", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--chats", required=True)
    p.add_argument("--chat-id", required=True)
    p.add_argument("--cfg", required=True)
    p.add_argument("--log", required=True)
    args = p.parse_args()
    tui = Tui(args)
    old = termios.tcgetattr(sys.stdin.fileno())
    tty.setraw(sys.stdin.fileno())
    if tui.cfg.get("bracketed_paste"):
        sys.stdout.write("\x1b[?2004h")
    try:
        threading.Thread(target=tui.worker, daemon=True).start()
        threading.Thread(target=tui.ticker, daemon=True).start()
        tui.render()
        tui.input_loop()
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
