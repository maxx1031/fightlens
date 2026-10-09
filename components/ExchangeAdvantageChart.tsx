"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  advantageCurve,
  presentJudgments,
  type AcceptedJudgment,
  type JudgmentUpdate,
  type PresentedJudgment,
} from "@/lib/live/judgments";
import { formatTime } from "@/lib/types";

const directionLabels = {
  favors_A: "A advantage",
  favors_B: "B advantage",
  no_clear_advantage: "Balanced",
  insufficient_evidence: "Insufficient evidence",
};
const evidenceLabels = {
  contact_only: "Contact only",
  observable_reaction: "Observable reaction",
  sustained_change: "Sustained visible change",
  no_confirmed_effect: "No confirmed effect",
  insufficient_evidence: "Insufficient evidence",
};
const gapLabels = {
  reviewing: "Exchange being assessed",
  identity_uncertain: "Identity uncertain",
  coverage_gap: "Missing evidence",
  too_long: "Exchange exceeded the evidence limit",
  skipped: "Window skipped under load",
  model_error: "Model result unavailable",
  paused: "Analysis paused",
};
const statusLabels = {
  not_configured: "Exchange judgments are not configured.",
  awaiting_identity:
    "Confirm fighter appearances below the video to start judgments.",
  buffering: "Waiting for a complete exchange.",
  reviewing: "Assessing the latest exchange…",
  ready: "Exchange assessment received",
  error: "Assessment unavailable. The next exchange can recover.",
  paused: "Analysis paused",
};
const describe = (entry: AcceptedJudgment) =>
  entry.kind === "gap"
    ? gapLabels[entry.gap_reason!]
    : directionLabels[entry.direction!];

export function ExchangeAdvantageChart({
  history,
  update,
  positionMs,
  paused,
  fresh,
  ended,
  aligned,
}: {
  history: AcceptedJudgment[];
  update: JudgmentUpdate | null;
  positionMs: number;
  paused: boolean;
  fresh: boolean;
  ended: boolean;
  aligned: boolean;
}) {
  const [presented, setPresented] = useState<PresentedJudgment[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (!fresh || paused || ended) return;
    setPresented((previous) =>
      presentJudgments(previous, history, positionMs, new Date().toISOString()),
    );
  }, [history, positionMs, fresh, paused, ended]);
  const latest = presented.at(-1);
  const selectedEntry =
    presented.findLast(
      (entry) => `${entry.id}:${entry.revision}` === selected,
    ) ?? latest;
  const data = advantageCurve(presented, positionMs, paused || !fresh || ended);
  const message = ended
    ? "Session ended"
    : paused
      ? statusLabels.paused
      : !fresh
        ? "Waiting for fresh video · current direction unavailable"
        : update
          ? statusLabels[update.status]
          : "Waiting for the judgment service";
  return (
    <section className="space-y-3" aria-label="Exchange advantage">
      <p role="status" className="text-sm" data-testid="exchange-direction">
        {latest &&
        fresh &&
        !paused &&
        !ended &&
        positionMs - latest.available_position_ms <= 10_000
          ? describe(latest)
          : "Current direction unavailable"}
      </p>
      <div
        className="h-48 min-w-0"
        role="img"
        aria-label="Exchange direction over time. Upper level favors A, middle is balanced, lower favors B. Gaps mean unavailable evidence."
      >
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{ top: 12, right: 12, left: 0, bottom: 0 }}
            >
              <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
              <XAxis
                type="number"
                dataKey="time"
                domain={[
                  Math.max(0, positionMs / 1000 - 60),
                  Math.max(1, positionMs / 1000),
                ]}
                tickFormatter={formatTime}
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              />
              <YAxis
                domain={[-1, 1]}
                ticks={[-1, 0, 1]}
                tickFormatter={(v) => (v === 1 ? "A" : v === -1 ? "B" : "Even")}
                width={38}
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              />
              <ReferenceLine
                y={0}
                stroke="hsl(var(--muted-foreground))"
                strokeDasharray="3 4"
              />
              <Tooltip
                content={({ active, payload }) => {
                  const entry = payload?.[0]?.payload?.entry as
                    | PresentedJudgment
                    | undefined;
                  return active && entry ? (
                    <div className="max-w-64 rounded-md border bg-popover p-3 text-xs text-popover-foreground shadow-md">
                      <p>{describe(entry)}</p>
                      <p>
                        Evidence {entry.t0_s.toFixed(1)}–{entry.t1_s.toFixed(1)}
                        s
                      </p>
                      <p>
                        First shown at{" "}
                        {(entry.display_position_ms / 1000).toFixed(1)}s
                      </p>
                      {entry.evidence && (
                        <p>{evidenceLabels[entry.evidence]}</p>
                      )}
                    </div>
                  ) : null;
                }}
              />
              <Line
                type="stepAfter"
                dataKey="value"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
            Waiting for assessed exchanges
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{message}</p>
      {latest?.model.startsWith("fake/") && (
        <p className="text-xs text-muted-foreground">
          Fixture · no footage assessment
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Direction of the latest assessed exchange. Levels express A / balanced /
        B, without a numeric strength measure. Steps start when first shown;
        evidence times are separate. Receiver-relative timing. Results older
        than 10s become unavailable.
      </p>
      <p className="text-xs text-muted-foreground">
        {aligned
          ? "Results wait for their receiver position in the rendered YOLO video."
          : "Receiver-relative results · rendered-frame alignment unavailable."}
      </p>
      {!!update?.skipped_windows && (
        <p className="text-xs text-muted-foreground">
          {update.skipped_windows} exchange windows skipped.
        </p>
      )}
      {presented.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs underline">
            Exchange evidence and uncertainty
          </summary>
          <div className="mt-2 flex flex-wrap gap-2">
            {presented.slice(-6).map((entry) => (
              <button
                key={`${entry.id}:${entry.revision}`}
                type="button"
                className="min-h-11 rounded-md border px-2 text-xs focus-visible:outline focus-visible:outline-2"
                aria-pressed={selectedEntry === entry}
                onClick={() => setSelected(`${entry.id}:${entry.revision}`)}
              >
                {entry.t1_s.toFixed(1)}s · {describe(entry)}
              </button>
            ))}
          </div>
          {selectedEntry && (
            <div className="mt-3 space-y-1 break-words text-xs">
              <p>
                Evidence: {selectedEntry.t0_s.toFixed(1)}–
                {selectedEntry.t1_s.toFixed(1)}s · {selectedEntry.frames} frames
              </p>
              <p>
                First displayed: {selectedEntry.first_displayed_at} · ready:{" "}
                {selectedEntry.ready_at}
              </p>
              <p>
                {selectedEntry.model.startsWith("fake/")
                  ? "Fixture · no footage assessment"
                  : selectedEntry.model}{" "}
                · revision {selectedEntry.revision}
              </p>
              {selectedEntry.evidence && (
                <p>{evidenceLabels[selectedEntry.evidence]}</p>
              )}
              {selectedEntry.probabilities && (
                <ul className="space-y-1">
                  {Object.entries(selectedEntry.probabilities.direction).map(
                    ([option, probability]) => (
                      <li key={option}>
                        {
                          directionLabels[
                            option as keyof typeof directionLabels
                          ]
                        }
                        : {(probability * 100).toFixed(1)}%
                      </li>
                    ),
                  )}
                </ul>
              )}
              {selectedEntry.probabilities && (
                <ul className="space-y-1">
                  {Object.entries(selectedEntry.probabilities.evidence).map(
                    ([option, probability]) => (
                      <li key={option}>
                        {evidenceLabels[option as keyof typeof evidenceLabels]}:{" "}
                        {(probability * 100).toFixed(1)}%
                      </li>
                    ),
                  )}
                </ul>
              )}
              {selectedEntry.confidence && (
                <p>
                  Reported confidence:{" "}
                  {selectedEntry.confidence.direction.toFixed(2)}. It does not
                  measure advantage strength or validated accuracy.
                </p>
              )}
              <p>Evidence replay is unavailable in this live view.</p>
            </div>
          )}
        </details>
      )}
    </section>
  );
}
