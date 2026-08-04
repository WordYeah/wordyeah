# WordYeah media PoC API

The first PoC deliberately uses a private standard-library HTTP server so it
can be tested without adding a web framework or an upload URL fetcher.

## `GET /health`

Returns service liveness and states that model calls are local-only.

## `POST /v1/moderate/image`

- Bind: `127.0.0.1:18765` by default (`WORDYEAH_BIND`/`WORDYEAH_PORT`)
- Body: raw image bytes (`Content-Length` required)
- Maximum body: 10 MiB by default (`WORDYEAH_MAX_BODY_BYTES`)
- No URL input; the service does not fetch remote content.
- Model loading uses `local_files_only=True`.
- If `WORDYEAH_API_KEY` is set, requests require `Authorization: Bearer ...`.

Example response shape:

```json
{
  "request_id": "...",
  "content_sha256": "...",
  "media_type": "image",
  "decision": "allow|block|review|error",
  "reasons": [],
  "findings": [],
  "top_score": 0.002,
  "model_versions": {"media.nsfw": "Falconsai/nsfw_image_detection"},
  "elapsed_ms": 12.3,
  "error": null
}
```

`error` is fail-closed at the API boundary. The Cravatar adapter is not part
of this PoC and no production decision is changed.

## Text baseline

The `wy-word` module currently exposes a deterministic rule service for tests
and local integration. It intentionally has no built-in sensitive-word list;
callers must provide configured `TextRule` values. OCR and semantic models are
separate future adapters and are not implied by a rule match.
