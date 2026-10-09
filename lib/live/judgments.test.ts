import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import {
  judgmentSchema,
  judgmentUpdateSchema,
  mergeJudgment,
  presentJudgments,
  directionValue,
  advantageCurve,
  type Judgment,
} from "./judgments";

const entry = (changes: Partial<Judgment> = {}): Judgment => ({
  id: randomUUID(),
  episode_id: randomUUID(),
  revision: 0,
  kind: "direction",
  t0_s: 10,
  t1_s: 12,
  available_position_ms: 14000,
  ready_at: "2026-10-09T20:00:00.000Z",
  model: "fake/clef",
  prompt_version: "exchange-direction.v1",
  frames: 8,
  latency_ms: 2000,
  direction: "favors_A",
  evidence: "contact_only",
  gap_reason: null,
  confidence: { direction: 0.8, evidence: 0.8 },
  probabilities: {
    direction: {
      favors_A: 1,
      favors_B: 0,
      no_clear_advantage: 0,
      insufficient_evidence: 0,
    },
    evidence: {
      contact_only: 1,
      observable_reaction: 0,
      sustained_change: 0,
      no_confirmed_effect: 0,
      insufficient_evidence: 0,
    },
  },
  ...changes,
});

test("schema rejects invalid distributions and impossible timing", () => {
  assert.ok(judgmentSchema.safeParse(entry()).success);
  assert.ok(
    !judgmentSchema.safeParse(entry({ available_position_ms: 11000 })).success,
  );
  const bad = entry();
  bad.probabilities!.direction.favors_B = 0.5;
  assert.ok(!judgmentSchema.safeParse(bad).success);
  assert.ok(
    !judgmentSchema.safeParse(entry({ direction: "favors_B" })).success,
  );
});

test("transport repeats and stale revisions don't double count; new revision replaces result", () => {
  const first = entry(),
    at = first.ready_at;
  const history = mergeJudgment([], first, at);
  assert.equal(mergeJudgment(history, first, at), history);
  const revised = entry({
    ...first,
    revision: 1,
    direction: "favors_B",
    available_position_ms: 17000,
    probabilities: {
      ...first.probabilities!,
      direction: {
        favors_A: 0,
        favors_B: 1,
        no_clear_advantage: 0,
        insufficient_evidence: 0,
      },
    },
  });
  const next = mergeJudgment(history, revised, at);
  assert.equal(next.length, 1);
  assert.equal(next[0].direction, "favors_B");
  assert.equal(mergeJudgment(next, first, at), next);
});

test("late judgment cannot backfill or use unrendered evidence; revisions preserve what was previously displayed", () => {
  const first = entry(),
    history = mergeJudgment([], first, first.ready_at);
  assert.deepEqual(presentJudgments([], history, 11000, first.ready_at), []);
  assert.deepEqual(presentJudgments([], history, 13000, first.ready_at), []);
  const shown = presentJudgments([], history, 16000, first.ready_at);
  assert.equal(shown[0].display_position_ms, 16000);
  assert.equal(presentJudgments(shown, history, 17000, first.ready_at), shown);
  const revised = entry({
    ...first,
    revision: 1,
    available_position_ms: 20000,
  });
  const next = presentJudgments(
    shown,
    mergeJudgment(history, revised, first.ready_at),
    22000,
    first.ready_at,
  );
  assert.equal(next[0].revision, 0);
  assert.equal(next[1].revision, 1);
  assert.equal(next[1].display_position_ms, 22000);
});

test("missing evidence produces a gap even when the selected direction favors A; balanced is distinct", () => {
  assert.equal(
    directionValue(entry({ evidence: "insufficient_evidence" })),
    null,
  );
  assert.equal(
    directionValue(entry({ direction: "insufficient_evidence" })),
    null,
  );
  assert.equal(directionValue(entry({ direction: "no_clear_advantage" })), 0);
});

test("status validation prohibits inactive results and unclassified errors", () => {
  const packet = {
    schema_version: "fightlens.judgment.v1",
    session_id: randomUUID(),
    source_generation: 1,
    worker_generation: 1,
    segment_id: randomUUID(),
    analysis_revision: 0,
    identity_revision: 0,
    seq: 1,
    status: "paused",
    skipped_windows: 0,
    error_code: null,
    judgment: entry(),
  };
  assert.ok(!judgmentUpdateSchema.safeParse(packet).success);
  assert.ok(
    judgmentUpdateSchema.safeParse({ ...packet, judgment: null }).success,
  );
  assert.ok(
    !judgmentUpdateSchema.safeParse({
      ...packet,
      status: "error",
      judgment: null,
    }).success,
  );
});

test("categorical level is held until a gap or expiry, and never connected across missing evidence", () => {
  const first = entry(),
    history = mergeJudgment([], first, first.ready_at);
  const presented = presentJudgments([], history, 16000, first.ready_at);
  const rows = advantageCurve(presented, 26000, false);
  assert.equal(rows[0].time, 16);
  assert.equal(rows[1].time, 24);
  assert.equal(rows[1].value, 1);
  assert.equal(rows[2].value, null);
  assert.equal(advantageCurve(presented, 18000, true).at(-1)?.value, null);
});
