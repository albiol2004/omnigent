# Builder brief — slice image-attachment

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent`. Mailbox `loop-stability/`. Iteration 1.

Do NOT commit. Do NOT edit web/ except if a tiny test needs it
(prefer server tests). No live browser required if headers are
asserted.

PATH: `PATH=/home/alex/omnigent/.venv/bin:$PATH`

Scout: upload stores MIME; download ignores it.

## Writes (only)

- `omnigent/server/routes/sessions/routes_resources.py`
- `omnigent/server/routes/_sessions/helpers.py` (only if needed
  for the content-disposition helper ~626-645)
- `tests/server/routes/test_session_resources.py`

Line ranges: `routes_resources.py` 1213-1305 (upload),
1341-1400 (content: line 1382 `guess_type`, 1388-1396 force
`attachment` + nosniff).

## Required behavior (test-first)

1. Content route uses stored/canonical `content_type`, not only
   filename guess. Extensionless PNG must be `image/png`.
2. Vetted raster types (`image/png`, `image/jpeg`, `image/gif`,
   `image/webp`) served **inline**.
3. HTML, SVG, text, unknown stay `Content-Disposition: attachment`.
4. Keep XSS hardening (`nosniff`); do not inline HTML/SVG.

Add tests next to existing PNG upload tests
(`test_session_resources.py` ~1800-2055).

```
cd /home/alex/omnigent && uv run pytest -q \
  tests/server/routes/test_session_resources.py -k 'image or upload or content'
```

Capture `loop-stability/evidence/iter1/image-attachment/pytest.txt`
and NOTES.md. Lines < 88 chars.
