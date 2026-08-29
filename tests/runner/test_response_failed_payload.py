"""Incomplete ``response.failed`` payloads must not 500 the SSE stream."""

from __future__ import annotations

import json

from omnigent.runner.app import _response_failed_dict, _response_failed_event
from omnigent.server.schemas import FailedEvent


def test_response_failed_dict_validates_as_failed_event() -> None:
    """ReadError-shaped runner errors must include ResponseObject ids."""
    payload = _response_failed_dict({"message": "dropped", "type": "ReadError"})
    event = FailedEvent.model_validate(payload)
    assert event.type == "response.failed"
    assert event.response.id == "resp_failed"
    assert event.response.model == "unknown"
    assert event.response.created_at > 0
    assert event.response.error is not None
    assert event.response.error.code == "ReadError"


def test_response_failed_sse_frame_parses() -> None:
    """The SSE encoder carries the same complete response object."""
    raw = _response_failed_event({"status": 502}).decode()
    assert raw.startswith("event: response.failed\n")
    data_line = next(line for line in raw.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    FailedEvent.model_validate(payload)
