# Image attachment evidence

Implemented the server-side image content response behavior.

- Upload metadata remains the canonical MIME source.
- PNG, JPEG, GIF, and WebP responses use `Content-Disposition: inline`.
- HTML, SVG, text, and unknown types remain attachments.
- Every content response keeps `X-Content-Type-Options: nosniff`.
- No helper change was needed because inline responses omit filenames.

Verification:

- Focused command: 12 passed, 138 deselected.
- Full `test_session_resources.py`: 150 passed in 33.37s.
- HTML attachment regression: 1 passed, 149 deselected.
- Ruff lint passed with the baseline `I001` rule ignored.
- Ruff formatting passed for both changed source files.
- New and changed lines stay below 88 characters.

Concerns:

- A broad Ruff check still reports the pre-existing import-order violation
  `I001` in `routes_resources.py`; it was not changed in this slice.
- No live browser run was needed; response headers are asserted directly.
