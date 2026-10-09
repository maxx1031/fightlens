# fusion

Merges candidates and verdicts into one deduplicated event ledger.

- **Input:** `outputs/<clip_id>/candidates.jsonl`, `outputs/<clip_id>/verdicts.jsonl`
- **Output:** `outputs/<clip_id>/events.json`
- **Format:** see [Event JSON contract](../README.md#event-json-contract), section 4.

## Rules

- Candidate without verdict → `status: pending`.
- Verdict `not_strike` → `status: withdrawn`.
- Any field change → `revision += 1`; never emit two events with the same `event_id`.
- Verdicts that arrive after a newer revision must not overwrite it.
- If the video model is unavailable, keep events `pending` rather than inventing outcomes.
