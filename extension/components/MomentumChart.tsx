import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts"
import type { AnalysisSnapshot } from "../lib/types"
import { formatTime } from "../lib/types"

export function MomentumChart({ snapshot }: { snapshot: AnalysisSnapshot }) {
  const start = snapshot.points[0]?.time || 0
  return (
    <div
      className="fl-chart"
      role="img"
      aria-label="Demo momentum curve. Above zero favors A; below zero favors B. Gaps mean unable to assess."
    >
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <LineChart
          data={snapshot.points}
          margin={{ top: 10, right: 10, bottom: 0, left: 0 }}
        >
          <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
          <XAxis
            type="number"
            dataKey="time"
            domain={[start, start + 60]}
            ticks={[start, start + 15, start + 30, start + 45, start + 60]}
            tickFormatter={formatTime}
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            minTickGap={0}
            tickMargin={10}
          />
          <YAxis
            domain={[-100, 100]}
            ticks={[-80, 0, 80]}
            tickFormatter={(value: number) =>
              value > 0 ? "A" : value < 0 ? "B" : "0"
            }
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
            width={22}
            axisLine={false}
            tickLine={false}
          />
          <ReferenceLine
            y={0}
            stroke="hsl(var(--muted-foreground))"
            strokeDasharray="3 4"
          />
          {snapshot.evidenceCutoff >= start + 31 && (
            <ReferenceArea
              x1={start + 31}
              x2={Math.min(start + 34, snapshot.evidenceCutoff)}
              fill="hsl(var(--muted))"
              fillOpacity={1}
            />
          )}
          <Tooltip
            cursor={{ stroke: "hsl(var(--border))" }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
                  <p className="font-medium">{formatTime(Number(label))}</p>
                  <p className="text-muted-foreground">
                    Demo index: {Math.round(Number(payload[0].value))}
                  </p>
                </div>
              ) : null
            }
          />
          <Line
            type="linear"
            dataKey="value"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            connectNulls={false}
            isAnimationActive={false}
            dot={false}
            activeDot={{ r: 3, fill: "hsl(var(--primary))", strokeWidth: 0 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
