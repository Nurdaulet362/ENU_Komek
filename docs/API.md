# ENU Көмек API v0.1

Base URL: `http://127.0.0.1:8777`. Local development only; no CORS access.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status, document/chunk count, model name |
| GET | `/api/documents` | Metadata for actually present files |
| GET | `/api/documents/{id}/file` | Original file, allowlisted SHA-based ID |
| GET | `/api/documents/{id}/preview/{page}` | PNG of a PDF page, Poppler required |
| GET | `/api/export` | Download metadata JSON |
| POST | `/api/ask` | Retrieve source excerpts |
| POST | `/api/upload` | Add local PDF/DOCX, at most 20 MB |
| POST | `/api/reindex` | Re-read local sources and retrain the search index |

`POST /api/ask`, Content-Type `application/json`:
```json
{"question":"Какие документы нужны для возвращения с академической мобильности?","language":"ru","role":"student"}
```
`question`: 3–1500 characters. `language`: `kk` or `ru`. `role`: `student` or `all`.
Optional `document_ids`: list of IDs limiting the search corpus; empty list means no sources.
Optional `topic`: stem-based title filter, default `all`.

Response fields: `status` (`found` / `not_found`), `message`, `sources`, `mode`, `elapsed_ms`, `notice`.
Each source includes `document_id`, `title`, `role`, `page`, `location`, `text`, `score`.
`location=section` denotes a DOCX extraction section, not a printed page.
`score` is an uncalibrated ranking score, NOT probability or answer confidence.

Upload: binary request body; `X-Filename` contains URL-encoded filename. PDF/DOCX signatures
and filename boundaries are checked. Existing filenames are not overwritten. The index is rebuilt.
Reindex: JSON body `{}`.

Errors: 400 malformed input, 403 invalid Host/Origin, 404 unknown ID/path, 409 duplicate filename,
413 oversized input, 415 wrong request format, 503 preview unavailable.

SMART.ENU integration is a future adapter. No real integration, SSO, student records access,
application submission or institutional endorsement is claimed. A deployed multi-user version needs
proper authentication, authorization, rate limiting, audit policy and restricted admin upload endpoints.

## Local conversation extension

`POST /api/ask` additionally accepts `conversation_mode: "documents" | "general"` (default: documents) and `history: string[]` (at most six previous questions, each at most 1000 characters). Existing requests remain compatible.

Responses include `steps`, `resolved_question` for retrieval, and one of these modes: `local-rag` (Qwen + retrieved evidence), `local-extractive` (fallback), `conversation` (greeting/help/model unavailable), `general-chat` (unverified general conversation). Status can additionally be `greeting`, `help`, `thanks`, `chat`, or `model_unavailable`. The UI translates template statuses at render time. `model_error: true` indicates generation fallback.

`GET /api/health` adds `chat_model` and `chat_available` (installed model detected, not an inference-quality guarantee). Generation uses local Ollama, with a 90-second timeout and no cloud requests. Source content and prior questions are untrusted input. Structural citation checking rejects missing/out-of-range references; it cannot prove the model's factual accuracy.

`local-extractive-summary` returns a short exact transcript requirement quote for matching document questions. This bypasses generation and is explicitly distinct from `local-rag`.

## Gemini settings

`GET /api/settings` returns `{provider, model, key_saved, allow_documents}`. `POST /api/settings` saves provider (`local` or `gemini`), model id, optional `api_key`, optional boolean `allow_documents`, or `clear_key: true`. Empty key preserves an existing key. Secrets are never returned. `POST /api/models` loads Google's generateContent model list (id/name/chat_supported); non-text specialized variants are marked not supported by this text UI. These endpoints inherit loopback Host, Origin, JSON and body-size checks.

Gemini calls use the native REST generateContent API. `cloud_documents_blocked` means retrieval succeeded but document-to-cloud permission is off. `provider_error` contains a stable sanitized error code. No automatic switch from a failed cloud model to another provider is performed.

## Multiple cloud providers

Provider IDs: `local`, `gemini`, `openai`, `anthropic`. `GET /api/settings` additionally returns `providers`, a map of provider IDs to `{key_saved, model, allow_documents}` with no secrets. `POST /api/settings` accepts `key_provider` to save/clear credentials and document permission for one provider without activating it; `provider` and `model` select the active provider/model. `POST /api/models` accepts `{provider}` to retrieve that provider's model list without changing the active conversation. Gemini's legacy settings are preserved. Permissions do not carry over to OpenAI or Anthropic.

Official API contracts: [OpenAI Responses](https://developers.openai.com/api/docs/guides/text), [OpenAI models](https://developers.openai.com/api/reference/resources/models/methods/list), [Claude Messages](https://platform.claude.com/docs/en/api/messages/create), [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
