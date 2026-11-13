# Usage

## The short version

1. Open the app and sign in (or click **use the demo account**).
2. Drop an audio file on the upload box.
3. Wait. A 45-second clip takes about 10 seconds on CPU with `tiny`.
4. Read the transcript. Lines are coloured by how sure the model was.
5. Export as TXT, SRT, VTT or Markdown.

## Reading the colours

| Colour | Meaning | What to do |
|---|---|---|
| Green (no badge) | Confidence ≥ 80% | Trust it |
| Amber `UNSURE` | 50–80% | Skim it |
| Red `CHECK` | Below 50%, or one word below 35% | Read it carefully |

Under any flagged line you will see `doubted: <words>` — the specific tokens
the model was least sure about. That is the whole point of the tool: it tells
you where to look instead of making you re-read everything.

A real example from the demo file:

```
00:11  you will find bookshops opening at eight and t- stalls that have been
       in the same family for three generations.
       [CHECK] 69%   doubted: t, stalls
```

The audio said "tea stalls". Whisper heard "t- stalls" and was not confident
about it. The tool flagged exactly that line and named the two tokens. Every
other line in the file was clean.

## The confidence bar

The bar at the top of the transcript is the overall score, weighted by segment
duration — a two-second mumble does not drag down a five-minute clear
recording. Next to it is the count of flagged lines.

## Exporting

| Format | Use it for |
|---|---|
| **TXT** | Reading, pasting into a doc. Reflowed into paragraphs, not one line per segment. |
| **SRT** | Subtitles for any video editor, YouTube, Premiere, DaVinci. |
| **VTT** | Web `<track>` elements, HTML5 video. |
| **MD** | Review workflows — flagged lines are marked with ⚠ so a reviewer can work down the list. |

TXT also accepts `?timestamps=true` if you want the times inline.

## Your files

Everything you upload is listed at the bottom of the page with its status and
confidence. Click one to reopen it. Delete removes both the row and the audio
file from disk.

Files are private to your account. Requesting someone else's job returns 404,
not 403 — a 403 would confirm the id exists.

## API, briefly

```bash
# register
curl -X POST localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"at-least-8-chars"}'

# upload
curl -X POST localhost:8000/api/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@talk.mp3"

# poll
curl localhost:8000/api/jobs/$JOB_ID -H "Authorization: Bearer $TOKEN"

# export
curl "localhost:8000/api/jobs/$JOB_ID/export?fmt=srt" \
  -H "Authorization: Bearer $TOKEN" -o talk.srt
```

Full reference: [`docs/api.md`](api.md), or the live OpenAPI docs at
`/api/docs`.

## Tips that actually help

**Use a better model for names.** `tiny` mangles proper nouns. `base` or
`small` fixes most of it, and the confidence score will tell you when it
hasn't.

**Don't fight the flags.** If a line is flagged, listen to that timestamp
rather than guessing from context. The model is usually right about being
unsure.

**Long files are fine but slow.** A one-hour recording on CPU with `tiny` is
roughly an hour of processing. Use a GPU, or a smaller model, or split it.

**Silence gets flagged.** If you see a flagged line that reads like plausible
speech but you remember silence there, trust the flag — that is Whisper
inventing text, and it is the most dangerous failure mode this tool exists to
catch.
