# Architecture

## The problem

Every transcription tool gives you text and no signal about which parts of it
are trustworthy. Whisper is very good, but it is not perfect, and it fails in
predictable ways: proper nouns, accented speech, technical vocabulary, and —
most dangerously — silence, which it will happily turn into plausible
sentences.

The information needed to flag those failures already exists. Whisper emits a
probability for every token it produces. Almost every wrapper throws it away.

Sada keeps it.

## System diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (vanilla JS, no build step)                             │
│                                                                  │
│  index.html ── styles.css ── app.js                              │
│      │                                                           │
│      ├─ XHR upload with progress ─────────────┐                  │
│      └─ poll GET /api/jobs/{id} every 1.2s ───┼──┐               │
└───────────────────────────────────────────────┼──┼───────────────┘
                                                │  │
┌───────────────────────────────────────────────▼──▼───────────────┐
│  FastAPI                                                         │
│                                                                  │
│  SlowAPI middleware ── security headers ── CORS                  │
│                                                                  │
│  /api/auth/*        register · login · me                        │
│  /api/jobs          POST upload · GET list · GET detail          │
│                     GET export · DELETE                          │
│  /api/health                                                     │
│                                                                  │
│  deps.current_user ── JWT decode ── User lookup                   │
└───────────────┬──────────────────────────────┬───────────────────┘
                │                              │
                │ SQLAlchemy 2.0               │ BackgroundTasks
                ▼                              ▼
      ┌──────────────────┐          ┌──────────────────────────┐
      │  SQLite / Postgres│          │  TranscriptionEngine     │
      │                  │          │  (lazy, thread-safe)     │
      │  users           │          │                          │
      │  jobs            │          │  faster-whisper          │
      │  segments        │          │  word_timestamps=True    │
      └──────────────────┘          └────────────┬─────────────┘
                                                 │
                                                 ▼
                                    ┌────────────────────────┐
                                    │  transcript.py         │
                                    │  pure functions:       │
                                    │  · segment_confidence  │
                                    │  · low_confidence_words│
                                    │  · segment_needs_review│
                                    │  · to_srt/vtt/txt/md   │
                                    └────────────────────────┘
```

## Data flow

1. **Upload.** `POST /api/jobs` streams the file to disk in 1 MB chunks,
   aborting the moment the size cap is crossed rather than after writing the
   whole thing. Extension and MIME are both validated — either alone is
   trivially spoofed. A `Job` row is created with `status=queued` and the
   response returns `202` immediately.

2. **Transcribe.** A `BackgroundTask` opens its own database session (the
   request's is already closed) and calls the engine. The engine loads the
   Whisper model on first use and caches it — loading takes seconds and must
   not happen per request, nor at import time.

3. **Score.** For each segment, word probabilities are collected. The segment
   confidence is `0.7 × mean + 0.3 × worst`, so one badly-wrong word pulls the
   line down without destroying it. A segment is flagged if its confidence is
   below the threshold, if its worst word is below `0.35`, or if the model
   suspected there was no speech at all.

4. **Persist.** Segments are written with their confidence, the raw
   `avg_logprob`, `no_speech_prob`, and the list of doubted words.

5. **Poll.** The browser polls `GET /api/jobs/{id}` until `status` is `done`
   or `failed`, then renders. Polling rather than WebSockets because the job
   is short-lived and a socket would be more moving parts than the problem
   deserves.

6. **Export.** `GET /api/jobs/{id}/export?fmt=srt|vtt|txt|md` renders from the
   stored segments through pure functions in `transcript.py`.

## Why word probabilities, not segment log-probability

This is the single most important design decision, and it was made after
measuring rather than assuming.

faster-whisper reports `avg_logprob` per segment, but it is averaged over the
whole 30-second decode window. Consecutive segments inside one window come
back with **identical** values to many decimal places:

```
 0.00- 5.36 lp=-0.157482
 5.36-10.96 lp=-0.157482
10.96-15.52 lp=-0.157482
15.52-20.56 lp=-0.157482
```

A per-line confidence built on that would be a lie — every line in a window
would show the same number. Word probabilities are per-token and genuinely
differ, and they catch real errors:

```
11.08 avg=0.887 min=0.233 low=[' t', ' stalls']   ← "tea stalls" misheard
 5.46 avg=0.933 min=0.446 low=[' harbor']
```

That is the difference between a feature and a decoration.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI 0.115 | Async uploads, Pydantic validation, OpenAPI for free |
| ORM | SQLAlchemy 2.0 | Typed `Mapped[]` models, works on SQLite and Postgres unchanged |
| DB | SQLite → Postgres | Zero-setup clone; `DATABASE_URL` switches it |
| ASR | faster-whisper | CTranslate2 backend, ~4× faster than openai-whisper on CPU |
| Auth | JWT (HS256) + bcrypt | Stateless, no session store to run |
| Rate limit | SlowAPI | Per-route limits, in-memory by default |
| Frontend | Vanilla JS | No build step, no framework, no dependency tree to audit |
| Tests | pytest | 81 tests, all offline, whole suite under a second |

## Scaling notes

**Where this breaks first:** the background task runs in the web process. A
long file blocks a worker, and a restart loses in-flight jobs. The fix is a
real queue — Celery or RQ with Redis — and the `_run_transcription` function
is already shaped to be lifted into a worker unchanged.

**Model loading.** One model instance per process, guarded by a lock. With
multiple workers each loads its own copy; `tiny` is ~75 MB so that is fine,
but `large-v3` at ~3 GB per worker is not. At that point the model belongs
behind its own service.

**Rate limiting.** SlowAPI's `memory://` storage is per-process, so limits
multiply by worker count. Set `RATELIMIT_STORAGE_URI=redis://...` before
running more than one worker.

**Storage.** Uploads go to local disk. On any multi-instance deployment that
must be object storage (S3/R2), and the `stored_path` column becomes a key
rather than a path.

**Database.** `create_all()` is fine for one deploy. Once there is data worth
keeping, add Alembic — the models are already clean enough to autogenerate
from.

**Cost of transcription.** CPU `tiny` runs roughly real-time on a modern core.
`base` is ~2× slower and noticeably more accurate; `small` is the practical
sweet spot for production quality on CPU. GPU with `compute_type=float16` is
an order of magnitude faster again.
