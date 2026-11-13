# API reference

Base URL: `http://127.0.0.1:8000`. Interactive docs at `/api/docs`.

All authenticated endpoints take `Authorization: Bearer <token>`. The browser
UI also accepts an `access_token` cookie.

## Errors

Every error is `{"detail": "..."}`. Validation errors (422) return FastAPI's
standard array form.

| Code | When |
|---|---|
| 400 | Malformed request |
| 401 | Missing, invalid or expired token |
| 404 | Not found, **or not yours** |
| 409 | Conflict (duplicate email, job not finished) |
| 413 | Upload over the size cap |
| 415 | Unsupported file type |
| 422 | Validation failure |
| 429 | Rate limited |

---

## `GET /api/health`

No auth. Returns service status.

```json
{"status": "ok", "version": "1.0.0", "model": "tiny", "engine_ready": false}
```

`engine_ready` is `false` until the first transcription loads the model.

---

## `POST /api/auth/register`

Rate limit: 5/minute.

```json
{"email": "you@example.com", "password": "at-least-8-chars", "display_name": "Abrar"}
```

`201` →

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {"id": "a1b2...", "email": "you@example.com", "display_name": "Abrar", "created_at": "..."}
}
```

`409` if the email is taken. `422` if the password is under 8 characters or
over 72 bytes (bcrypt's limit — rejected rather than silently truncated).

---

## `POST /api/auth/login`

Rate limit: 10/minute.

```json
{"email": "you@example.com", "password": "..."}
```

`200` with the same shape as register. `401` with
`"Incorrect email or password."` for both a wrong password and an unknown
address — the response must not reveal which.

---

## `GET /api/auth/me`

`200` → the user object. `401` without a valid token.

---

## `POST /api/jobs`

Rate limit: 10/minute. `multipart/form-data`.

| Field | Type | Notes |
|---|---|---|
| `file` | file | Required. Max 100 MB (`MAX_UPLOAD_MB`). |
| `language` | query | Optional ISO code, e.g. `ur`. Omit to auto-detect. |

Accepted extensions: `.mp3 .wav .m4a .flac .ogg .opus .webm .aac .mp4 .mpeg .mpga`

`202` →

```json
{
  "id": "b689f9d9...",
  "original_filename": "talk.mp3",
  "status": "queued",
  "language": "",
  "language_probability": 0.0,
  "duration_seconds": 0.0,
  "size_bytes": 69888,
  "confidence": 0.0,
  "uncertain_count": 0,
  "model_name": "",
  "created_at": "2026-11-13T19:08:33",
  "completed_at": null
}
```

Transcription runs in the background. Poll the detail endpoint.

`413` if over the cap, `415` if the type is wrong.

---

## `GET /api/jobs`

Query: `limit` (1–100, default 20), `offset` (default 0).

```json
{"items": [ ...JobSummary... ], "total": 3}
```

Newest first, scoped to the caller.

---

## `GET /api/jobs/{id}`

`200` → the job with its segments.

```json
{
  "id": "b689f9d9...",
  "status": "done",
  "language": "en",
  "language_probability": 0.999,
  "duration_seconds": 46.1,
  "confidence": 0.8663,
  "uncertain_count": 1,
  "full_text": "Karachi is a city that never really sleeps. ...",
  "segments": [
    {
      "index": 2,
      "start": 11.08,
      "end": 15.66,
      "text": "you will find bookshops opening at eight and t- stalls ...",
      "confidence": 0.691,
      "avg_logprob": -0.157482,
      "no_speech_prob": 0.0029,
      "uncertain": true,
      "low_words": "t, stalls"
    }
  ]
}
```

`status` is one of `queued`, `running`, `done`, `failed`. On `failed`, `error`
holds a message.

`404` if the job does not exist **or belongs to someone else**.

### Segment fields

| Field | Meaning |
|---|---|
| `confidence` | 0–1, from word probabilities: `0.7 × mean + 0.3 × worst` |
| `avg_logprob` | Raw Whisper value. Averaged over the 30s decode window, so it repeats across segments — kept for debugging, not for display. |
| `no_speech_prob` | Model's suspicion that there was no speech here |
| `uncertain` | True if confidence is low, the worst word is under 0.35, or `no_speech_prob > 0.6` |
| `low_words` | Comma-separated words below 0.5 probability |

---

## `GET /api/jobs/{id}/export`

| Query | Values | Default |
|---|---|---|
| `fmt` | `srt`, `vtt`, `txt`, `md` | `txt` |
| `timestamps` | `true`/`false` (txt only) | `false` |

Returns the file with `Content-Disposition: attachment`. Content types:
`application/x-subrip`, `text/vtt`, `text/plain`, `text/markdown`.

`409` if the job is not `done` yet. `422` for an unknown format.

---

## `DELETE /api/jobs/{id}`

`204` on success. Removes the row, its segments, and the audio file from disk.
`404` if not yours.

---

## Rate limits

| Endpoint | Limit |
|---|---|
| `POST /api/auth/register` | 5/minute |
| `POST /api/auth/login` | 10/minute |
| `POST /api/jobs` | 10/minute |
| everything else | 120/minute |

`429` responses carry `Retry-After: 60`. Limits are per-process with the
default in-memory store — set `RATELIMIT_STORAGE_URI=redis://...` before
running multiple workers.
