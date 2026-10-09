import type { AnalysisSnapshot, ExchangeEvent } from "./types"

export const DEMO_DURATION = 60
export const DEMO_EVENTS: ExchangeEvent[] = [
  {
    id: "demo-1",
    time: 5,
    fighter: "B",
    title: "B finds the body",
    detail: "Illustrative body contact in an opening exchange.",
    outcome: "landed",
    direction: -26
  },
  {
    id: "demo-2",
    time: 12,
    fighter: "A",
    title: "A answers with a counter",
    detail: "Illustrative right-hand contact after B's entry.",
    outcome: "landed",
    direction: 33
  },
  {
    id: "demo-3",
    time: 18,
    fighter: "A",
    title: "A keeps the pressure",
    detail: "Illustrative follow-up contact during the exchange.",
    outcome: "landed",
    direction: 24
  },
  {
    id: "demo-4",
    time: 24,
    fighter: "B",
    title: "B's return is blocked",
    detail: "A blocked attack is separate from a landed strike.",
    outcome: "blocked",
    direction: 0
  },
  {
    id: "demo-5",
    time: 31,
    fighter: null,
    title: "Contact is obscured",
    detail: "An illustrative visibility gap. No direction is assigned.",
    outcome: "unknown",
    direction: 0
  },
  {
    id: "demo-6",
    time: 36,
    fighter: "B",
    title: "B turns the exchange",
    detail: "Illustrative counter contact shifts the demo signal.",
    outcome: "landed",
    direction: -48
  },
  {
    id: "demo-7",
    time: 43,
    fighter: "B",
    title: "A steps back off balance",
    detail: "Illustrative reaction; this demo does not establish causation.",
    outcome: "reaction",
    direction: -24
  },
  {
    id: "demo-8",
    time: 51,
    fighter: "A",
    title: "A regains initiative",
    detail: "Illustrative clean counter in the closing exchange.",
    outcome: "landed",
    direction: 44
  }
]

function valueAt(time: number): number | null {
  if (time >= 31 && time < 34) return null
  const value = DEMO_EVENTS.filter((event) => event.time <= time).reduce(
    (sum, event) => sum + event.direction * Math.exp(-(time - event.time) / 15),
    0
  )
  return Math.max(-80, Math.min(80, value))
}

export function getDemoSnapshot(time: number): AnalysisSnapshot {
  const cutoff = Math.max(0, time)
  // Long videos repeat the named demo sequence; this is never video analysis.
  const remainder = cutoff % DEMO_DURATION
  const localTime = cutoff > 0 && remainder === 0 ? DEMO_DURATION : remainder
  const cycleStart = cutoff - localTime
  const points = Array.from(
    { length: Math.floor(localTime) + 1 },
    (_, index) => ({
      time: cycleStart + index,
      value: valueAt(index)
    })
  )
  if (!Number.isInteger(localTime))
    points.push({ time: cutoff, value: valueAt(localTime) })
  return {
    source: "demo",
    evidenceCutoff: cutoff,
    momentum: valueAt(localTime),
    points,
    events: DEMO_EVENTS.filter((event) => event.time <= localTime).map(
      (event) => ({
        ...event,
        id: `${Math.floor(cycleStart / DEMO_DURATION)}-${event.id}`,
        time: cycleStart + event.time
      })
    )
  }
}
