"use client";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EngagementPoint } from "@/lib/live/types";

export function EngagementChart({
  history,
  renderedFrame,
  paused,
  aligned,
}: {
  history: EngagementPoint[];
  renderedFrame: number | null;
  paused: boolean;
  aligned: boolean;
}) {
  const visible =
    aligned && renderedFrame !== null
      ? history.filter((p) => p.frame_id <= renderedFrame)
      : history;
  const data = visible.map((p) => ({ t: p.t_ms / 1000, engaged: p.engaged }));
  return (
    <div aria-label="Live engagement curve" className="space-y-2">
      <div
        className="h-40 min-w-0"
        role="img"
        aria-label="Rule engagement: zero or one; missing or paused intervals are gaps"
      >
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{ top: 12, right: 8, left: -24, bottom: 0 }}
            >
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis
                type="number"
                dataKey="t"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(v) => `${Math.floor(v)}s`}
                tick={{ fontSize: 11 }}
              />
              <YAxis domain={[0, 1]} ticks={[0, 1]} tick={{ fontSize: 11 }} />
              <Tooltip
                labelFormatter={(v) => `${Number(v).toFixed(2)}s`}
                formatter={(v) => [v, "Rule engagement"]}
              />
              <Line
                type="stepAfter"
                dataKey="engaged"
                stroke="hsl(var(--foreground))"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
            Waiting for real pose results
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {paused
          ? "Analysis paused · video continues · curve has a gap."
          : "Rule-based engagement 0/1. Confirmed strikes and numeric momentum are unavailable."}
      </p>
      <p className="text-xs text-muted-foreground">
        {aligned
          ? "Curve follows rendered YOLO frame IDs."
          : "Receiver-relative results · rendered-frame alignment unavailable."}
      </p>
    </div>
  );
}
