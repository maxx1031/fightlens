export type Fighter = "A" | "B"

export interface ExchangeEvent {
  id: string
  time: number
  fighter: Fighter | null
  title: string
  detail: string
  outcome: "landed" | "blocked" | "unknown" | "reaction"
  direction: number
}

// A future analysis adapter can produce this same shape. Demo values are
// illustrative indices; they are not calibrated probabilities or damage scores.
export interface AnalysisSnapshot {
  source: "demo" | "analysis"
  evidenceCutoff: number
  momentum: number | null
  points: { time: number; value: number | null }[]
  events: ExchangeEvent[]
}

export const formatTime = (seconds: number) => {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)
    .toString()
    .padStart(2, "0")}:${(whole % 60).toString().padStart(2, "0")}`
}
