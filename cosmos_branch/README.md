# cosmos_branch

Cosmos watches the stretches of the bout that the YOLO branch points at. What it says is the memory of the
bout: the strikes, who is pressing, running notes, and the caption that goes with the win probability.

- **Input:** the YOLO branch's folder for one video, `yolo_branch/outputs/<clip>/`
  (`summary.json`, `keypoints.jsonl`, `windows.jsonl` or `exchange.jsonl`), and the video itself.
- **Output**, into the same folder: `memory.jsonl`, `memory.json`, `cosmos/` (the clips Cosmos watched),
  `narration.jsonl`.

## Who contributes what

| Who | Contributes | Never contributes |
|---|---|---|
| YOLO branch | when to look (`windows.jsonl`), and who is called A and B (the tags on the clips) | what happened |
| Cosmos | what happened in each clip: strikes, outcome, who is pressing | any number that is shown |
| `memory.py` | every count (hits taken, strikes thrown), from Cosmos's answers | |
| Whoever predicts | the win probability | |
| Text model (the Cosmos endpoint, without a video) | the words: running notes, captions | numbers |

The YOLO branch writes nothing into the memory. The only trace it leaves there is the field `source`
("yolo:ENGAGE"): why Cosmos looked at that stretch.

## Run it

```bash
pip install -r cosmos_branch/requirements.txt        # numpy, opencv-python, requests; ffmpeg on the PATH
export COSMOS3_REASON_URL=http://host:port           # already set on the organisers' VM

CLIP=yolo_branch/outputs/0_realhuman                 # after track.py and engage.py have run on the video

python cosmos_branch/review.py $CLIP --window 3.0 5.5     # FIRST: one stretch by hand. Prints question, raw reply, reading
python cosmos_branch/review.py $CLIP --a "red trunks" --b "black trunks"      # every window -> memory
python cosmos_branch/narrate.py $CLIP --p-a 0.63 --t 31    # the caption for "A 63%" at 0:31
python cosmos_branch/narrate.py $CLIP --notes              # what the memory holds
```

Without the endpoint (the whole path, made-up answers):

```bash
python cosmos_branch/fake_cosmos.py --delay 2 --think &
COSMOS3_REASON_URL=http://127.0.0.1:9001 python cosmos_branch/review.py $CLIP
```

Other ways to run `review.py`:

| Flag | What it does |
|---|---|
| `--follow` | keeps reading `windows.jsonl` while the YOLO branch appends to it; ends on a row `{"end": true, "t": <seconds>}` or Ctrl-C |
| `--grid 2.5 --video bout.mp4 --a ... --b ...` | no YOLO at all: the whole video in 2.5 s pieces, each reviewed like an exchange |
| `--glance T0 T1` | like `--window`, with the question for the time between exchanges |
| `--no-context` / `--no-notes` | exchanges only / no running notes |
| `--no-tags` | ignore `keypoints.jsonl` (no crop, no A / B tags); then `--a` and `--b` are required |
| `--video`, `--out`, `--windows`, `--workers`, `--fresh`, `--url`, `--model` | see `--help` |

A run can be repeated: windows that have an answer are skipped, failed ones are asked again.

Tests: `python -m pytest cosmos_branch`

## What triggers what

| Trigger | Comes from | What happens |
|---|---|---|
| An ENGAGE window | YOLO branch: `(t0, t1)` and nothing more | the stretch is cut into a slow-motion clip (pieces of at most 3 s) and Cosmos lists every strike in it -> an `exchange` entry |
| A RANGE window, or time no row covers, of 2 s or more | YOLO branch / the gaps | a glance at 2 frames a second: who is pressing, anything notable -> a `context` entry |
| FAR | YOLO branch | nothing |
| 6 new entries | the memory itself | the notes so far and the new entries are rewritten into new notes -> a `summary` entry |
| A new probability | whoever predicts | `narrate.caption()`: notes + recent entries + exact counts + the number -> two sentences and the entries they rest on |

## What is written

`memory.jsonl`: one line per answer, appended as it arrives, never edited.

```json
{"id": "x12.25", "kind": "exchange", "t0": 12.25, "t1": 14.6, "source": "yolo:ENGAGE",
 "strikes": [{"t": 12.9, "attacker": "A", "limb": "hand", "move": "jab", "target": "head", "outcome": "landed"}],
 "advantage": "A", "note": "A lands a jab as B steps in.", "dropped": 0,
 "clip": "cosmos/x12.25.mp4", "sheet": "cosmos/x12.25.jpg", "frames": 28, "model": "...", "latency_s": 3.1}
{"id": "c14.60", "kind": "context", "t0": 14.6, "t1": 24.6, "source": "yolo:RANGE",
 "pressure": "A", "notable": "", "note": "A walks B towards the fence."}
{"id": "s2", "kind": "summary", "t": 31.2, "covers": ["x24.60", "c27.00"], "text": "..."}
{"id": "x30.00", "kind": "failed", "t0": 30.0, "t1": 32.0, "asked": "exchange", "error": "..."}
```

- `limb`: hand, foot, elbow, knee. `target`: head, torso, legs. `outcome`: landed, blocked, missed, unclear.
  Any of the first two can be null when the reply did not say; `t` is null when the time it gave is not in the window.
- The latest line for an id is the one that counts; a failure never displaces an answer.
- `latency_s` is how long the answer took. For a replay that is honest about being live, show an entry
  once playback has reached `t1 + latency_s`.

`memory.json`: what follows from the log, rewritten after every line. This is the file for the page.

```json
{"until": 31.2,
 "received": {"A": {"head": 1, "torso": 0, "legs": 2, "other": 0, "total": 3}, "B": {"...": 0}},
 "thrown":   {"A": {"landed": 4, "blocked": 2, "missed": 1, "unclear": 0, "total": 7}, "B": {"...": 0}},
 "summary": {"t": 24.6, "text": "..."},
 "entries": {"exchange": 9, "context": 4, "failed": 0}}
```

Hits taken are counted from the landed strikes every time and never stored. A blow reported by two
neighbouring clips (same attacker, same target, within 0.25 s) is counted once.

`narration.jsonl`: one line per caption.

```json
{"t": 31.0, "p_A": 0.63, "prev": {"t": 20.0, "p_A": 0.55}, "text": "...", "evidence": ["x24.60"],
 "agrees": "yes", "record": "A", "number": "A", "consistent": true, "by": "nvidia/cosmos3-reason"}
```

- `record`: who landed more over the span the caption is about (counted here). `number`: which way the
  probability moved. `consistent` is false when they point at different fighters: show that on the page.
- `by` is "counts" when the model could not be used; the text is then a plain sentence built from the counts.
- From Python: `narrate.caption(Memory(clip_dir), p_a=0.63, t=31.0, prev=(20.0, 0.55), cosmos=Cosmos())`.
- A file of numbers: `narrate.py $CLIP --predictions predictions.jsonl`, rows like `{"t": 31, "p_A": 0.63}`.

`cosmos/<id>.mp4 .jpg .txt`: the clip Cosmos watched, a contact sheet of its frames, its raw reply.
The contact sheet is the quickest way to compare what it was shown with what it said.

## Before the first real run

Nothing here has seen fight footage or the real endpoint. Find these out first, in this order:

1. **Does the call work at all?** `review.py $CLIP --window T0 T1`. An HTTP error prints the endpoint's own message.
2. **Can Cosmos list the strikes of an exchange?** Pick five stretches where you can see the answer yourself
   and compare (the contact sheet is in `cosmos/by_hand/`). If it cannot tell landed from blocked, show
   `note` and `advantage` on the page and treat the counts as a suggestion.
3. **Does it read the A / B tags?** Check that `attacker` matches the tags on the sheet. If not, give `--a` and `--b`.
4. **Does the endpoint answer without a video?** `narrate.py $CLIP --p-a 0.6`. If `by` comes back as "counts",
   look at the error it prints, or point the words at another OpenAI-compatible endpoint with
   `NARRATOR_URL` / `NARRATOR_MODEL` / `NARRATOR_API_KEY`.

## Settings

| Where | Name | Default | Meaning |
|---|---|---|---|
| `windows.py` | `EXCHANGE_MAX_S` / `EXCHANGE_MIN_S` | 3.0 / 1.0 | longest and shortest stretch in one exchange clip |
| | `EXCHANGE_FPS` / `CONTEXT_FPS` | 12 / 2 | frames sampled per second of bout time |
| | `CONTEXT_MAX_S` / `CONTEXT_MIN_S` | 10 / 2 | longest glance / shortest gap that gets one |
| `clips.py` | `CLIP_FPS` | 4 | the rate clips are encoded at (what the Cosmos Reason model cards recommend), so an exchange plays 3x slower |
| | `MAX_FRAMES`, `CLIP_HEIGHT` | 36, 480 | lower these if the endpoint refuses a clip as too large |
| `cosmos.py` | `MAX_TOKENS`, `TIMEOUT_S`, `RETRIES` | 4096, 120, 2 | |
| `narrate.py` | `SUMMARY_EVERY`, `RECENT_S` | 6, 20 | entries per rewrite of the notes; seconds a caption always sees in full |
| `review.py` | `WORKERS` | 2 | clips under review at once |

## Assumed, and known gaps

- **`windows.jsonl` field names are a guess** (`engage.py` was not at hand). Rows are read as
  `{t0, t1, state}` under several spellings (`windows.py`, `_T0` / `_T1` / `_STATE`), also as frame numbers.
  A row that fits none stops the run and prints its keys. An `fps` in a row is used as the sampling rate.
- `candidates.jsonl` and `tracks.jsonl` are not read. Cosmos is not told what the pose tracker suspects.
- Who is A comes from `track.py`. If the tracker swaps the two fighters, the tags swap, and the memory with
  them. Giving `--a` / `--b` as well lets Cosmos go by the description where the two disagree.
- `keypoints.jsonl` covers what `track.py` covered (10 s by default). A window without tracking is refused
  unless `--a` / `--b` are given.
- Clips are cut from the video file. With a camera feed, record it to a file first.
- A stretch longer than 3 s is watched in pieces; a strike that lands exactly on a cut can be reported by
  neither piece.
- Camera cuts and replays are not handled.

## The code

| File | Job |
|---|---|
| `windows.py` | when to look: the YOLO branch's files (or a grid) -> windows |
| `clips.py` | what Cosmos is shown: slow motion, cropped, tagged, bout time under every frame |
| `cosmos.py` | how Cosmos is reached; the JSON in a reply |
| `asks.py` | the two questions about a clip, and how the answers are read |
| `memory.py` | the log and what is counted from it |
| `review.py` | the trigger: a window in, a memory entry out |
| `narrate.py` | the running notes and the caption |
| `fake_cosmos.py` | a stand-in endpoint |
