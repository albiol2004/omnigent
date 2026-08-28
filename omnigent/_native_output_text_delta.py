"""Shared Sessions API POST for native assistant text deltas."""

from __future__ import annotations

import httpx


async def post_external_output_text_delta(
    client: httpx.AsyncClient,
    *,
    session_id: str,
    delta: str,
    message_id: str,
    index: int,
    final: bool,
) -> None:
    """Post one transient ``external_output_text_delta`` event."""
    response = await client.post(
        f"/v1/sessions/{session_id}/events",
        json={
            "type": "external_output_text_delta",
            "data": {
                "delta": delta,
                "message_id": message_id,
                "index": index,
                "final": final,
            },
        },
    )
    response.raise_for_status()
