# Setup

## Requirements

- Python 3.11 or newer
- `ffmpeg` on the PATH (faster-whisper shells out to it for decoding)
- ~500 MB of disk for the model cache, plus room for your uploads

## Local, in two minutes

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-20-sada.git
cd day-20-sada

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))" >> .env

python -m app.seed                 # creates the demo account
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000> and click **use the demo account**.

The first transcription downloads the Whisper model (~75 MB for `tiny`). That
happens once, on the first upload, not at startup.

## Docker

```bash
cp .env.example .env
# put a real JWT_SECRET in .env first
docker compose up --build
```

That brings up the app on port 8000 and Postgres 16 alongside it. The app
waits for the database to be healthy before starting.

To use a different model without rebuilding:

```bash
WHISPER_MODEL=base docker compose up
```

## Choosing a model

| Model | Size | Speed on CPU | Quality |
|---|---|---|---|
| `tiny` | 75 MB | ~1× realtime | Fine for clear English |
| `base` | 145 MB | ~0.6× realtime | Noticeably better on names |
| `small` | 480 MB | ~0.3× realtime | The practical default |
| `medium` | 1.5 GB | ~0.15× realtime | Good, slow on CPU |
| `large-v3` | 3 GB | needs a GPU | Best |

Set `WHISPER_MODEL` in `.env`. On a GPU, also set
`WHISPER_DEVICE=cuda` and `WHISPER_COMPUTE_TYPE=float16`.

## Environment variables

Every one is documented in `.env.example`. The only one you must set for a
real deployment is `JWT_SECRET` — the app refuses to start in production
without it rather than falling back to something insecure.

## Running the tests

```bash
pytest
```

81 tests, all offline. No model is downloaded, no network is touched, and the
whole suite finishes in under a second.

## Linting

```bash
ruff check .
ruff format --check .
```

## Troubleshooting

**`ffmpeg not found`** — install it: `apt install ffmpeg` / `brew install ffmpeg`.

**First upload hangs for a minute** — that is the model downloading. Watch the
log; it prints `loading whisper model=...` when it starts.

**`unable to open database file`** — the `data/` directory does not exist yet.
`mkdir -p data` or just run `python -m app.seed`, which creates it.

**Everything is 429** — you hit the rate limit. `RATE_LIMIT_ENABLED=false` in
`.env` for local development.
