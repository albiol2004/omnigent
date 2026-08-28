"""Tests for transient assistant text extracted from the Cursor pane."""

from __future__ import annotations

from omnigent.cursor_native_stream import (
    CursorNativeStream,
    extract_assistant_region,
    strip_ansi,
)


def test_first_viewport_emits_the_first_assistant_delta() -> None:
    stream = CursorNativeStream("session-1")

    delta = stream.observe("  🤖 A mechanical clock is\n\n ⠼ Working 1 token")

    assert delta is not None
    assert delta.delta == "🤖 A mechanical clock is"
    assert delta.message_id == "cursor-live-session-1"
    assert delta.index == 0
    assert delta.final is False


def test_growing_viewport_emits_only_the_new_suffix() -> None:
    stream = CursorNativeStream("session-2")
    stream.observe("  🤖 Hello")

    delta = stream.observe("  🤖 Hello world\n\n ⠼ Working 2 tokens")

    assert delta is not None
    assert delta.delta == " world"
    assert delta.index == 1


def test_scrolled_viewport_emits_new_text_without_duplicate_prefix() -> None:
    stream = CursorNativeStream("session-3")
    stream.observe("  🤖 A mechanical clock is a machine\n\n ⠼ Working")

    delta = stream.observe("  a machine that measures time\n\n ⠼ Working")

    assert delta is not None
    assert delta.delta == " that measures time"


def test_redraw_with_the_same_text_is_empty() -> None:
    stream = CursorNativeStream("session-4")
    viewport = "  🤖 Stable text\n\n ⠼ Working"

    assert stream.observe(viewport) is not None
    assert stream.observe(viewport) is None


def test_ansi_is_removed_before_extracting_assistant_text() -> None:
    pane = "\x1b[32m  🤖 Hello\x1b[0m\n\x1b[2m ⠼ Working\x1b[0m"

    assert strip_ansi(pane) == "  🤖 Hello\n ⠼ Working"
    delta = CursorNativeStream("session-5").observe(pane)

    assert delta is not None
    assert delta.delta == "🤖 Hello"


def test_wrapped_viewport_lines_become_spaces() -> None:
    stream = CursorNativeStream("session-wrap")
    pane = "  🤖 Hello\n  world\n\n ⠼ Working"
    delta = stream.observe(pane)
    assert delta is not None
    assert delta.delta == "🤖 Hello world"


def test_rewind_allows_the_same_suffix_to_be_retried() -> None:
    stream = CursorNativeStream("session-6")
    first = stream.observe("  🤖 Hello\n\n ⠼ Working")
    assert first is not None
    stream.rewind(first)
    again = stream.observe("  🤖 Hello\n\n ⠼ Working")
    assert again is not None
    assert again.delta == "🤖 Hello"
    assert again.index == 0


def test_reset_does_not_replay_the_completed_pane_region() -> None:
    stream = CursorNativeStream("session-replay")
    first = stream.observe("  🤖 Old answer\n\n ⠼ Working")
    assert first is not None

    stream.reset()

    assert stream.observe("  🤖 Old answer\n\n") is None


def test_new_turn_uses_a_fresh_message_id_after_reset() -> None:
    stream = CursorNativeStream("session-epochs")
    first = stream.observe("  🤖 First answer\n\n ⠼ Working")
    assert first is not None
    stream.reset()

    assert stream.observe("  🤖 First answer\n\n") is None
    second = stream.observe("  🤖 Second answer\n\n ⠼ Working")

    assert second is not None
    assert second.delta == "🤖 Second answer"
    assert second.message_id != first.message_id
    assert second.index == 0


def test_last_assistant_marker_ignores_prompt_emoji() -> None:
    pane = "  Ask about 🤖 in this prompt\n  🤖 Assistant answer\n\n ⠼ Working"

    assert extract_assistant_region(pane) == "🤖 Assistant answer"


def test_tool_chrome_is_skipped_without_truncating_later_prose() -> None:
    pane = "  🤖 First paragraph\n\n  → Run a tool\n  second paragraph\n\n ⠼ Working"

    assert extract_assistant_region(pane) == "🤖 First paragraph\n\nsecond paragraph"
