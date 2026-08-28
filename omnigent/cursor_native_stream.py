"""Pure helpers for streaming assistant text from a Cursor TUI pane."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ANSI_RE = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\)|"
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))"
)
_WORKING_LINE_RE = re.compile(r"^[^A-Za-z]*(?:Working|Generating)(?:\s|$)")
_ASSISTANT_MARKER_RE = re.compile(r"(?m)^[ \t]*(?P<marker>🤖)")


def strip_ansi(text: str) -> str:
    """Remove terminal escape sequences while retaining pane text."""
    return _ANSI_RE.sub("", text)


def pane_is_working(viewport: str) -> bool:
    """Return whether a pane snapshot contains a generation indicator."""
    return any(_WORKING_LINE_RE.match(line.strip()) for line in strip_ansi(viewport).splitlines())


def _is_chrome_line(line: str) -> bool:
    """Return whether a line belongs to Cursor's non-assistant chrome."""
    stripped = line.strip()
    return (
        bool(_WORKING_LINE_RE.match(stripped))
        or stripped.startswith("→")
        or "Run Everything" in stripped
    )


def _last_assistant_marker(viewport: str) -> int:
    """Return the newest line-start marker, ignoring quoted prompt emoji."""
    matches = _ASSISTANT_MARKER_RE.finditer(viewport)
    return max((match.start("marker") for match in matches), default=-1)


def _normalize_region(lines: list[str]) -> str:
    """Remove the pane's common left margin without changing paragraphs."""
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""

    first = lines[0].strip()
    rest = lines[1:]
    indents = [len(line) - len(line.lstrip()) for line in rest if line.strip()]
    margin = min(indents, default=0)
    normalized = [first]
    for line in rest:
        normalized.append(line[margin:].rstrip() if line.strip() else "")
    return "\n".join(normalized)


def extract_assistant_region(viewport: str, *, has_emitted: bool = False) -> str:
    """Extract visible assistant text, excluding Cursor's surrounding chrome."""
    clean = strip_ansi(viewport)
    marker = _last_assistant_marker(clean)
    if marker >= 0:
        body = clean[marker:]
    elif has_emitted:
        # Once the response scrolls, its marker can leave the viewport.
        body = clean
    else:
        return ""

    lines = body.splitlines()
    prose_lines: list[str] = []
    for line in lines:
        if not _is_chrome_line(line):
            prose_lines.append(line)
        elif line.strip().startswith("→"):
            # Tool output can be interleaved with prose. It is chrome, but not
            # a boundary: later assistant text remains part of this region.
            continue
        else:
            break
    return _unwrap_wrapped_lines(_normalize_region(prose_lines))


def _unwrap_wrapped_lines(text: str) -> str:
    """Turn terminal wrap breaks into spaces; keep paragraph blanks."""
    return re.sub(r"(?<!\n)\n(?!\n)", " ", text).strip()


def suffix_after(emitted: str, viewport: str) -> str:
    """Return text visible after the already emitted assistant text."""
    if not viewport or not emitted:
        return viewport
    if viewport.startswith(emitted):
        return viewport[len(emitted) :]
    if emitted.startswith(viewport) or viewport in emitted:
        return ""

    max_overlap = min(len(emitted), len(viewport))
    for size in range(max_overlap, 0, -1):
        if emitted[-size:] == viewport[:size]:
            return viewport[size:]

    # A large scroll jump may have no overlapping characters. Treat its
    # viewport as new text; redraws that repeat old text were handled above.
    return viewport


@dataclass(frozen=True)
class CursorTextDelta:
    """One transient assistant-text delta destined for the Sessions API."""

    message_id: str
    index: int
    final: bool
    delta: str


@dataclass
class CursorNativeStream:
    """Track one in-flight Cursor assistant response in memory."""

    session_id: str
    emitted: str = ""
    message_id: str | None = None
    next_index: int = 0
    turn_epoch: int = 0
    _awaiting_new_turn: bool = field(default=False, init=False, repr=False)
    _completed_region: str = field(default="", init=False, repr=False)
    _last_working: bool = field(default=False, init=False, repr=False)
    _force_new_turn: bool = field(default=False, init=False, repr=False)

    def observe(self, viewport: str) -> CursorTextDelta | None:
        """Convert a pane snapshot into one new transient delta, if any."""
        working = pane_is_working(viewport)
        if self._awaiting_new_turn:
            # Do not use the completed response as a new baseline until Cursor
            # has started another generation. A user item can force this path
            # immediately, while the pane path waits for a working edge.
            region = extract_assistant_region(viewport)
            if not working:
                self._last_working = False
            region_is_new = bool(region) and (
                not self._completed_region or region not in self._completed_region
            )
            generation_started = self._force_new_turn or (
                working and (not self._last_working or region_is_new)
            )
            if not generation_started:
                return None
            self._start_new_epoch(region)

        region = extract_assistant_region(
            viewport,
            has_emitted=bool(self.emitted),
        )
        delta = suffix_after(self.emitted, region)
        if not delta:
            self._last_working = working
            return None
        if self.message_id is None:
            epoch = f"-{self.turn_epoch}" if self.turn_epoch else ""
            self.message_id = f"cursor-live-{self.session_id}{epoch}"
        result = CursorTextDelta(
            message_id=self.message_id,
            index=self.next_index,
            final=False,
            delta=delta,
        )
        self.emitted += delta
        self.next_index += 1
        self._last_working = working
        return result

    def rewind(self, delta: CursorTextDelta) -> None:
        """Undo an observe that failed to POST so the suffix is retried."""
        if self.emitted.endswith(delta.delta) and self.next_index > 0:
            self.emitted = self.emitted[: -len(delta.delta)]
            self.next_index -= 1

    def start_new_turn(self) -> None:
        """Allow the next pane frame to start a new user-injected turn."""
        if not self._awaiting_new_turn:
            return
        self._force_new_turn = True

    def _start_new_epoch(self, region: str) -> None:
        """Advance the live message epoch and ignore one stale pane redraw."""
        stale = bool(self._completed_region) and region in self._completed_region
        self.turn_epoch += 1
        self._awaiting_new_turn = False
        self._force_new_turn = False
        self._completed_region = ""
        self.emitted = region if stale else ""
        self.message_id = None
        self.next_index = 0

    def reset(self) -> None:
        """Arm the stream for a new turn without replaying the completed one."""
        self._completed_region = self.emitted
        self._awaiting_new_turn = True
        self._force_new_turn = False
        self.emitted = ""
        self.message_id = None
        self.next_index = 0
