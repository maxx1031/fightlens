import { z } from "zod";

export const directions = [
  "favors_A",
  "favors_B",
  "no_clear_advantage",
  "insufficient_evidence",
] as const;
export const evidenceTypes = [
  "contact_only",
  "observable_reaction",
  "sustained_change",
  "no_confirmed_effect",
  "insufficient_evidence",
] as const;
export const gapReasons = [
  "reviewing",
  "identity_uncertain",
  "coverage_gap",
  "too_long",
  "skipped",
  "model_error",
  "paused",
] as const;
const probability = z.number().finite().min(0).max(1);
const directionDistribution = z.object({
  favors_A: probability,
  favors_B: probability,
  no_clear_advantage: probability,
  insufficient_evidence: probability,
});
const evidenceDistribution = z.object({
  contact_only: probability,
  observable_reaction: probability,
  sustained_change: probability,
  no_confirmed_effect: probability,
  insufficient_evidence: probability,
});

export const judgmentSchema = z
  .object({
    id: z.string().min(1).max(200),
    episode_id: z.string().uuid(),
    revision: z.number().int().nonnegative(),
    kind: z.enum(["direction", "gap"]),
    t0_s: z.number().finite().nonnegative(),
    t1_s: z.number().finite().nonnegative(),
    available_position_ms: z.number().finite().nonnegative(),
    ready_at: z.string().datetime(),
    model: z.string().min(1).max(200),
    prompt_version: z.literal("exchange-direction.v1"),
    frames: z.number().int().min(0).max(40),
    latency_ms: z.number().finite().nonnegative(),
    direction: z.enum(directions).nullable(),
    evidence: z.enum(evidenceTypes).nullable(),
    probabilities: z
      .object({
        direction: directionDistribution,
        evidence: evidenceDistribution,
      })
      .nullable(),
    confidence: z
      .object({ direction: probability, evidence: probability })
      .nullable(),
    gap_reason: z.enum(gapReasons).nullable(),
  })
  .superRefine((entry, ctx) => {
    const invalid = () =>
      ctx.addIssue({ code: "custom", message: "Invalid exchange judgment." });
    if (
      entry.t1_s < entry.t0_s ||
      entry.available_position_ms + 1 < entry.t1_s * 1000
    )
      invalid();
    if (entry.kind === "gap") {
      if (
        !entry.gap_reason ||
        entry.direction ||
        entry.evidence ||
        entry.probabilities ||
        entry.confidence
      )
        invalid();
    } else {
      if (
        entry.gap_reason ||
        !entry.direction ||
        !entry.evidence ||
        !entry.probabilities ||
        !entry.confidence ||
        entry.frames < 2 ||
        entry.t1_s <= entry.t0_s
      )
        invalid();
      if (entry.probabilities) {
        for (const distribution of Object.values(entry.probabilities)) {
          if (
            Math.abs(
              Object.values(distribution).reduce((sum, p) => sum + p, 0) - 1,
            ) > 0.02
          )
            invalid();
        }
        if (
          entry.direction &&
          entry.probabilities.direction[entry.direction] <
            Math.max(...Object.values(entry.probabilities.direction))
        )
          invalid();
        if (
          entry.evidence &&
          entry.probabilities.evidence[entry.evidence] <
            Math.max(...Object.values(entry.probabilities.evidence))
        )
          invalid();
      }
    }
  });
export type Judgment = z.infer<typeof judgmentSchema>;
export type AcceptedJudgment = Judgment & { accepted_at: string };
export const judgmentUpdateSchema = z
  .object({
    schema_version: z.literal("fightlens.judgment.v1"),
    session_id: z.string().uuid(),
    source_generation: z.number().int().positive(),
    worker_generation: z.number().int().positive(),
    segment_id: z.string().uuid(),
    analysis_revision: z.number().int().nonnegative(),
    identity_revision: z.number().int().nonnegative(),
    seq: z.number().int().positive(),
    status: z.enum([
      "not_configured",
      "awaiting_identity",
      "buffering",
      "reviewing",
      "ready",
      "error",
      "paused",
    ]),
    skipped_windows: z.number().int().nonnegative(),
    error_code: z
      .enum(["endpoint_unavailable", "invalid_response", "frame_unavailable"])
      .nullable(),
    judgment: judgmentSchema.nullable(),
  })
  .superRefine((update, ctx) => {
    if (
      (update.status === "error") !== (update.error_code !== null) ||
      (["not_configured", "awaiting_identity", "paused"].includes(
        update.status,
      ) &&
        update.judgment)
    )
      ctx.addIssue({ code: "custom", message: "Invalid judgment status." });
  });
export type JudgmentUpdate = z.infer<typeof judgmentUpdateSchema>;

// Revisions replace one exchange result. Transport repeats never add another point.
export function mergeJudgment(
  history: AcceptedJudgment[],
  entry: Judgment,
  acceptedAt: string,
): AcceptedJudgment[] {
  const prior = history.find((item) => item.id === entry.id);
  if (prior && prior.revision >= entry.revision) return history;
  if (
    prior &&
    (prior.episode_id !== entry.episode_id ||
      entry.available_position_ms < prior.available_position_ms)
  )
    return history;
  const cutoff =
    Math.max(
      entry.available_position_ms,
      ...history.map((p) => p.available_position_ms),
    ) - 60_000;
  return [
    ...history.filter((item) => item.id !== entry.id),
    { ...entry, accepted_at: acceptedAt },
  ]
    .filter((item) => item.available_position_ms >= cutoff)
    .sort((a, b) => a.available_position_ms - b.available_position_ms)
    .slice(-120);
}

export function directionValue(entry: Judgment): -1 | 0 | 1 | null {
  if (entry.kind === "gap" || entry.evidence === "insufficient_evidence")
    return null;
  return entry.direction === "favors_A"
    ? 1
    : entry.direction === "favors_B"
      ? -1
      : entry.direction === "no_clear_advantage"
        ? 0
        : null;
}
export interface PresentedJudgment extends AcceptedJudgment {
  display_position_ms: number;
  first_displayed_at: string;
}
// A late/revised answer starts at its first visible position, never backfills a past step.
export function presentJudgments(
  previous: PresentedJudgment[],
  history: AcceptedJudgment[],
  positionMs: number,
  now: string,
): PresentedJudgment[] {
  const visible = history.filter(
    (entry) =>
      entry.available_position_ms <= positionMs &&
      entry.available_position_ms >= positionMs - 60_000 &&
      entry.t1_s * 1000 <= positionMs,
  );
  const existing = new Set(
    previous.map((entry) => `${entry.id}:${entry.revision}`),
  );
  const additions = visible
    .filter((entry) => !existing.has(`${entry.id}:${entry.revision}`))
    .map((entry) => ({
      ...entry,
      display_position_ms: positionMs,
      first_displayed_at: now,
    }));
  const retained = previous.filter(
    (entry) => entry.display_position_ms >= positionMs - 60_000,
  );
  if (!additions.length && retained.length === previous.length) return previous;
  return [...retained, ...additions].slice(-120);
}

// Preserve the last categorical level up to a gap/expiry, without bridging either.
export function advantageCurve(
  presented: PresentedJudgment[],
  positionMs: number,
  unavailable: boolean,
) {
  const rows: {
    time: number;
    value: -1 | 0 | 1 | null;
    entry: PresentedJudgment;
  }[] = [];
  for (let index = 0; index < presented.length; index++) {
    const entry = presented[index],
      value = directionValue(entry);
    rows.push({ time: entry.display_position_ms / 1000, value, entry });
    if (value === null) continue;
    const next = presented[index + 1];
    const end = Math.min(
      next?.display_position_ms ?? positionMs,
      entry.available_position_ms + 10_000,
    );
    if (end > entry.display_position_ms)
      rows.push({ time: end / 1000, value, entry });
    if (
      end < (next?.display_position_ms ?? positionMs) ||
      (!next && unavailable)
    )
      rows.push({ time: (end + 0.001) / 1000, value: null, entry });
  }
  return rows;
}
