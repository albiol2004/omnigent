"""Pure helpers for streaming assistant text from a Cursor TUI pane."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ANSI_RE = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\)|"
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))"
)
_WORKING_LINE_RE = re.compile(r"^[^A-Za-z]*Working(?:\s|$)")


def strip_ansi(text: str) -> str:
    """Remove terminal escape sequences while retaining pane text."""
    return _ANSI_RE.sub("", text)


def pane_is_working(viewport: str) -> bool:
    """Return whether a pane snapshot contains Cursor's working indicator."""
    return any(_WORKING_LINE_RE.match(line.strip()) for line in strip_ansi(viewport).splitlines())


def _is_chrome_line(line: str) -> bool:
    """Return whether a line belongs to Cursor's non-assistant chrome."""
    stripped = line.strip()
    return (
        bool(_WORKING_LINE_RE.match(stripped))
        or stripped.startswith("→ ")
        or "Run Everything" in stripped
    )


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
    marker = clean.find("🤖")
    if marker >= 0:
        body = clean[marker + len("🤖") :]
    elif has_emitted:
        # Once the response scrolls, its marker can leave the viewport.
        body = clean
    else:
        return ""

    lines = body.splitlines()
    for index, line in enumerate(lines):
        if _is_chrome_line(line):
            lines = lines[:index]
            break
    return _normalize_region(lines)


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

    def observe(self, viewport: str) -> CursorTextDelta | None:
        """Convert a pane snapshot into one new transient delta, if any."""
        region = extract_assistant_region(
            viewport,
            has_emitted=bool(self.emitted),
        )
        delta = suffix_after(self.emitted, region)
        if not delta:
            return None
        if self.message_id is None:
            self.message_id = f"cursor-live-{self.session_id}"
        result = CursorTextDelta(
            message_id=self.message_id,
            index=self.next_index,
            final=False,
            delta=delta,
        )
        self.emitted += delta
        self.next_index += 1
        return result

    def rewind(self, delta: CursorTextDelta) -> None:
        """Undo an observe that failed to POST so the suffix is retried."""
        if self.emitted.endswith(delta.delta) and self.next_index > 0:
            self.emitted = self.emitted[: -len(delta.delta)]
            self.next_index -= 1

    def reset(self) -> None:
        """Forget the completed response before the next assistant turn."""
        self.emitted = ""
        self.message_id = None
        self.next_index = 0
