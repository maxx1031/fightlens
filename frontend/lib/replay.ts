export type Fighter = "A" | "B";
export type Zone = "head" | "body" | "leg";
export type Outcome = "landed" | "blocked" | "missed" | "unknown";
export interface FightEvent {
  event_id: string;
  t_s: number;
  attacker: Fighter;
  defender: Fighter;
  contact_zone: Zone;
  outcome: Outcome;
  status: "accepted" | "pending" | "withdrawn";
  revision: number;
  title: string;
  observation: string;
  source: "scripted";
}
export interface MarketQuote {
  t_s: number;
  A: number;
  B: number;
}
export const DURATION = 15;
export const VIDEO_OFFSET = 10;
export const FIGHTERS = {
  A: { name: "Black kit", short: "Black kit", color: "#e89574" },
  B: { name: "White kit", short: "White kit", color: "#769fdd" },
};
// Review fixtures only. These events do not describe observed contact in the footage.
export const EVENTS: FightEvent[] = [
  {
    event_id: "demo-01",
    t_s: 1.1,
    attacker: "A",
    defender: "B",
    contact_zone: "head",
    outcome: "landed",
    status: "accepted",
    revision: 1,
    title: "Right cross",
    observation:
      "A simulated right-hand strike to B’s head. Inspect the linked replay to review the interaction.",
    source: "scripted",
  },
  {
    event_id: "demo-02",
    t_s: 2.8,
    attacker: "B",
    defender: "A",
    contact_zone: "body",
    outcome: "landed",
    status: "accepted",
    revision: 1,
    title: "Body hook",
    observation:
      "A simulated body strike received by A. This adds one body contact to A’s mirror.",
    source: "scripted",
  },
  {
    event_id: "demo-03",
    t_s: 4.3,
    attacker: "A",
    defender: "B",
    contact_zone: "head",
    outcome: "blocked",
    status: "accepted",
    revision: 1,
    title: "Guard catches the jab",
    observation:
      "A simulated blocked head strike. The shield animates; received-strike heat stays unchanged.",
    source: "scripted",
  },
  {
    event_id: "demo-04",
    t_s: 6.0,
    attacker: "A",
    defender: "B",
    contact_zone: "leg",
    outcome: "landed",
    status: "accepted",
    revision: 1,
    title: "Low kick",
    observation:
      "A simulated leg contact received by B. The leg zone flashes and its received count increases.",
    source: "scripted",
  },
  {
    event_id: "demo-05",
    t_s: 7.4,
    attacker: "B",
    defender: "A",
    contact_zone: "head",
    outcome: "landed",
    status: "accepted",
    revision: 1,
    title: "Counter cross",
    observation:
      "A simulated counter to A’s head. Both mirrors use the same contact-count color scale.",
    source: "scripted",
  },
  {
    event_id: "demo-06",
    t_s: 8.7,
    attacker: "A",
    defender: "B",
    contact_zone: "head",
    outcome: "unknown",
    status: "accepted",
    revision: 1,
    title: "Contact unclear",
    observation:
      "An ambiguous demo exchange. Unknown outcomes do not trigger a hit flash or add heat.",
    source: "scripted",
  },
  {
    event_id: "demo-07",
    t_s: 10.2,
    attacker: "A",
    defender: "B",
    contact_zone: "body",
    outcome: "landed",
    status: "accepted",
    revision: 1,
    title: "Body cross",
    observation:
      "A simulated body contact received by B. Select the body zone to filter its evidence.",
    source: "scripted",
  },
  {
    event_id: "demo-08",
    t_s: 11.5,
    attacker: "B",
    defender: "A",
    contact_zone: "leg",
    outcome: "missed",
    status: "accepted",
    revision: 1,
    title: "Kick falls short",
    observation:
      "A simulated missed kick. No body zone flashes and no received contact is counted.",
    source: "scripted",
  },
  {
    event_id: "demo-09",
    t_s: 12.6,
    attacker: "B",
    defender: "A",
    contact_zone: "leg",
    outcome: "landed",
    status: "accepted",
    revision: 1,
    title: "Outside low kick",
    observation:
      "A simulated leg strike received by A. Counts are reconstructed from the selected replay time.",
    source: "scripted",
  },
  {
    event_id: "demo-10",
    t_s: 14.0,
    attacker: "B",
    defender: "A",
    contact_zone: "head",
    outcome: "blocked",
    status: "accepted",
    revision: 1,
    title: "High guard",
    observation:
      "A simulated head strike stopped by A’s guard. Blocks are counted separately from landed contact.",
    source: "scripted",
  },
];
// Sample binary-market snapshots, independent of the event fixtures; no market API is connected.
export const QUOTES: MarketQuote[] = [
  { t_s: 0, A: 52, B: 48 },
  { t_s: 1.8, A: 54, B: 46 },
  { t_s: 3.5, A: 51, B: 49 },
  { t_s: 5, A: 55, B: 45 },
  { t_s: 6.5, A: 59, B: 41 },
  { t_s: 8, A: 56, B: 44 },
  { t_s: 9.5, A: 58, B: 42 },
  { t_s: 11, A: 62, B: 38 },
  { t_s: 13, A: 60, B: 40 },
  { t_s: 14.8, A: 61, B: 39 },
];
export function visibleEvents(
  records: FightEvent[],
  time: number,
): FightEvent[] {
  const latest = new Map<string, FightEvent>();
  for (const record of records) {
    const prior = latest.get(record.event_id);
    if (!prior || record.revision > prior.revision)
      latest.set(record.event_id, record);
  }
  return [...latest.values()]
    .filter((e) => e.t_s <= time)
    .sort((a, b) => a.t_s - b.t_s);
}
export function receivedCounts(
  events: FightEvent[],
  fighter: Fighter,
): Record<Zone, number> {
  const counts = { head: 0, body: 0, leg: 0 };
  for (const event of events)
    if (
      event.defender === fighter &&
      event.status === "accepted" &&
      event.outcome === "landed"
    )
      counts[event.contact_zone]++;
  return counts;
}
export function quoteAt(time: number): MarketQuote {
  return QUOTES.filter((q) => q.t_s <= time).at(-1) ?? QUOTES[0];
}
export function formatTime(time: number): string {
  return `00:${Math.floor(Math.max(0, time)).toString().padStart(2, "0")}`;
}
