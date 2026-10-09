"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  CircleHelp,
  Crosshair,
  Expand,
  Flag,
  Layers,
  Moon,
  Pause,
  Play,
  RotateCcw,
  Shield,
  Sun,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import dynamic from "next/dynamic";
import "./viewer.css";
import type { Feedback } from "@/components/ImpactAvatar";
const ImpactAvatar = dynamic(
  () => import("@/components/ImpactAvatar").then((module) => module.ImpactAvatar),
  {
    ssr: false,
    loading: () => (
      <div className="avatar-stage" aria-label="Loading impact mirror" />
    ),
  },
);
import {
  DURATION,
  EVENTS,
  FIGHTERS,
  QUOTES,
  VIDEO_OFFSET,
  formatTime,
  quoteAt,
  receivedCounts,
  visibleEvents,
  type Fighter,
  type FightEvent,
  type Zone,
} from "@/lib/replay";

const ZONES: Zone[] = ["head", "body", "leg"];
const zoneName = { head: "Head", body: "Body", leg: "Legs" };
const outcomeName = {
  landed: "Landed",
  blocked: "Blocked",
  missed: "Missed",
  unknown: "Unclear",
};
function OutcomeIcon({
  outcome,
  className,
}: {
  outcome: FightEvent["outcome"];
  className?: string;
}) {
  const Icon =
    outcome === "landed"
      ? Crosshair
      : outcome === "blocked"
        ? Shield
        : outcome === "missed"
          ? X
          : CircleHelp;
  return <Icon size={13} className={className} />;
}

function MarketChart({
  time,
  onSeek,
  windowSize,
}: {
  time: number;
  onSeek: (time: number) => void;
  windowSize: number;
}) {
  const chart = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(680);
  useEffect(() => {
    const host = chart.current;
    if (!host) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(180, entry.contentRect.width)),
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  const height = 158,
    pad = { left: 34, right: 14, top: 14, bottom: 25 };
  const start = windowSize === 5 ? Math.max(0, time - 5) : 0,
    end = windowSize === 5 ? Math.max(5, time) : DURATION;
  const x = (t: number) =>
    pad.left + ((t - start) / (end - start)) * (width - pad.left - pad.right);
  const y = (value: number) =>
    pad.top + ((75 - value) / 50) * (height - pad.top - pad.bottom);
  const quotes = QUOTES.filter((q) => q.t_s <= time && q.t_s >= start);
  const prior = quoteAt(start);
  const data = [
    { ...prior, t_s: start },
    ...quotes.filter((q) => q.t_s > start),
  ];
  const path = (fighter: Fighter) => {
    let d = `M${x(start)},${y(prior[fighter])}`;
    for (const q of data.slice(1)) d += `H${x(q.t_s)}V${y(q[fighter])}`;
    return d + `H${x(Math.min(time, end))}`;
  };
  const quote = quoteAt(time);
  return (
    <div
      ref={chart}
      className="market-chart"
      role="slider"
      tabIndex={0}
      aria-label="Market timeline. Arrow keys move replay by one second."
      aria-valuemin={0}
      aria-valuemax={DURATION}
      aria-valuenow={Math.round(time)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          onSeek(time + (e.key === "ArrowRight" ? 1 : -1));
        }
      }}
      onPointerDown={(e) => {
        const box = e.currentTarget.getBoundingClientRect();
        onSeek(
          start +
            Math.max(
              0,
              Math.min(
                1,
                (e.clientX - box.left - (box.width * pad.left) / width) /
                  ((box.width * (width - pad.left - pad.right)) / width),
              ),
            ) *
              (end - start),
        );
      }}
    >
      <svg viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        {[25, 50, 75].map((value) => (
          <g key={value}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(value)}
              y2={y(value)}
              className="chart-grid"
              strokeDasharray={value === 50 ? "3 4" : undefined}
            />
            <text
              x={pad.left - 9}
              y={y(value) + 4}
              textAnchor="end"
              className="chart-label"
            >
              {value}%
            </text>
          </g>
        ))}
        {[
          start,
          start + (end - start) / 3,
          start + (2 * (end - start)) / 3,
          end,
        ].map((t) => (
          <text
            key={t}
            x={x(t)}
            y={height - 4}
            textAnchor="middle"
            className="chart-label"
          >
            {formatTime(t)}
          </text>
        ))}
        <path
          d={path("A")}
          stroke={FIGHTERS.A.color}
          strokeWidth="2.2"
          fill="none"
        />
        <path
          d={path("B")}
          stroke={FIGHTERS.B.color}
          strokeWidth="2.2"
          fill="none"
        />
        <line
          x1={x(time)}
          x2={x(time)}
          y1={pad.top}
          y2={height - pad.bottom}
          className="chart-cursor"
          strokeDasharray="3 4"
        />
        {(["A", "B"] as Fighter[]).map((f) => (
          <circle
            key={f}
            cx={x(time)}
            cy={y(quote[f])}
            r="4"
            fill={FIGHTERS[f].color}
            className="chart-point"
          />
        ))}
      </svg>
    </div>
  );
}

export function FightViewer() {
  const video = useRef<HTMLVideoElement>(null),
    lastTime = useRef(6.2),
    nonce = useRef(0);
  const [time, setTime] = useState(6.2),
    [playing, setPlaying] = useState(false),
    [dark, setDark] = useState(true),
    [rate, setRate] = useState("1");
  const [selectedId, setSelectedId] = useState<string | null>(null),
    [filter, setFilter] = useState<{ fighter: Fighter; zone: Zone } | null>(
      null,
    ),
    [feedback, setFeedback] = useState<Feedback | null>(null),
    [windowSize, setWindowSize] = useState(15),
    [videoError, setVideoError] = useState(false);
  const [mediaMessage, setMediaMessage] = useState<string | null>(null);

  const events = visibleEvents(EVENTS, time),
    quote = quoteAt(time);
  const latest = events.at(-1),
    selected = events.find((e) => e.event_id === selectedId) ?? latest;
  const filtered = events
    .filter(
      (e) =>
        !filter ||
        (e.defender === filter.fighter && e.contact_zone === filter.zone),
    )
    .slice()
    .reverse();
  const counts = {
    A: receivedCounts(events, "A"),
    B: receivedCounts(events, "B"),
  };
  const landed = events.filter(
      (e) => e.status === "accepted" && e.outcome === "landed",
    ).length,
    blocked = events.filter(
      (e) => e.status === "accepted" && e.outcome === "blocked",
    ).length;
  function flash(event: FightEvent) {
    if (
      event.status === "accepted" &&
      (event.outcome === "landed" || event.outcome === "blocked")
    )
      setFeedback({
        defender: event.defender,
        zone: event.contact_zone,
        outcome: event.outcome,
        nonce: ++nonce.current,
      });
    else setFeedback(null);
  }
  function seek(target: number, event?: FightEvent) {
    const next = Math.max(0, Math.min(DURATION, target));
    lastTime.current = next;
    setTime(next);
    if (video.current) video.current.currentTime = VIDEO_OFFSET + next;
    setSelectedId(event?.event_id ?? null);
    setMediaMessage(null);
    if (event) flash(event);
    else setFeedback(null);
  }
  function selectEvent(event: FightEvent) {
    video.current?.pause();
    seek(event.t_s, event);
  }
  function tick() {
    if (!video.current) return;
    const next = Math.max(
      0,
      Math.min(DURATION, video.current.currentTime - VIDEO_OFFSET),
    );
    if (next >= DURATION - 0.025) {
      video.current.pause();
      setTime(DURATION);
      lastTime.current = DURATION;
      return;
    }
    if (next > lastTime.current && next - lastTime.current < 0.8) {
      const crossed = EVENTS.filter(
        (e) => e.t_s > lastTime.current && e.t_s <= next,
      );
      if (crossed.length) flash(crossed.at(-1)!);
    }
    lastTime.current = next;
    setTime(next);
  }
  async function togglePlay() {
    if (!video.current) return;
    if (playing) {
      video.current.pause();
      return;
    }
    if (time >= DURATION - 0.1) seek(0);
    setSelectedId(null);
    setFilter(null);
    try {
      await video.current.play();
      setMediaMessage(null);
    } catch {
      setMediaMessage("Playback could not start. Press play to retry.");
    }
  }
  async function replayExchange() {
    if (!selected) return;
    seek(Math.max(0, selected.t_s - 0.7));
    setFilter(null);
    try {
      await video.current?.play();
    } catch {
      setMediaMessage("Playback could not start. Press play to retry.");
    }
  }
  async function fullscreen() {
    try {
      await video.current?.requestFullscreen();
    } catch {
      setMediaMessage("Fullscreen is unavailable in this preview.");
    }
  }
  function filterZone(fighter: Fighter, zone: Zone) {
    setFilter((previous) =>
      previous?.fighter === fighter && previous.zone === zone
        ? null
        : { fighter, zone },
    );
  }

  return (
    <div className={dark ? "fight-replay" : "fight-replay light"}>
    <div className="viewer-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="FightLens home">
          <span className="brand-icon">
            <Crosshair size={21} />
          </span>
          <span>
            FightLens
            <span className="brand-divider" />
            <span className="brand-description">The fight, made visible.</span>
          </span>
        </a>
        <div className="header-actions">
          <Badge variant="outline" className="review-badge">
            <span className="status-dot" />
            Review prototype
          </Badge>
          <details className="help-menu">
            <summary aria-label="About this prototype">
              <CircleHelp size={17} />
            </summary>
            <div className="help-popover">
              <strong>One timeline. Every perspective.</strong>
              <p>
                Play the footage or select an exchange to see the receiving body
                region react. Select a body region to filter events.
              </p>
              <p>
                Footage is recorded. Contact events and market quotes are
                scripted review fixtures and are not observations or live
                prices. Pose overlays are baked into this sample video.
              </p>
            </div>
          </details>
          <Button
            variant="ghost"
            size="icon"
            aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
            onClick={() => setDark(!dark)}
          >
            {dark ? <Sun size={17} /> : <Moon size={17} />}
          </Button>
        </div>
      </header>
      <main className="viewer-main">
        <div className="page-heading">
          <div>
            <div className="eyebrow">
              <span className="status-dot" />
              RECORDED SESSION <span className="eyebrow-separator">/</span> CLIP
              01
            </div>
            <h1>Every exchange tells a story.</h1>
            <p>Follow the action. See the contact. Revisit the evidence.</p>
          </div>
          <div className="session-meta">
            <span>
              <Flag size={13} /> Standing exchange
            </span>
            <span className="tabular-nums">15-second replay</span>
          </div>
        </div>
        <div className="fight-strip">
          <div className="fighter-summary">
            <span className="fighter-token fighter-a">A</span>
            <div>
              <strong>Black kit</strong>
              <span>Fighter A</span>
            </div>
          </div>
          <div className="round-summary">
            <span>SPARRING SESSION</span>
            <strong>
              {formatTime(time)}
              <span> / {formatTime(DURATION)}</span>
            </strong>
          </div>
          <div className="fighter-summary right">
            <div>
              <strong>White kit</strong>
              <span>Fighter B</span>
            </div>
            <span className="fighter-token fighter-b">B</span>
          </div>
        </div>
        <div className="main-grid">
          <div className="video-column">
            <Card className="video-card">
              <div className="card-topline">
                <span>
                  <span className="status-dot" />
                  Fight replay
                </span>
                <Badge variant="secondary">Recorded footage</Badge>
              </div>
              <div className="video-surface">
                <video
                  ref={video}
                  src="/demo/footage.mp4"
                  muted
                  playsInline
                  preload="auto"
                  onLoadedMetadata={() => {
                    if (video.current) {
                      video.current.currentTime = VIDEO_OFFSET + 6.2;
                      video.current.playbackRate = Number(rate);
                    }
                  }}
                  onTimeUpdate={tick}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onEnded={() => {
                    setPlaying(false);
                    setTime(DURATION);
                  }}
                  onError={() => setVideoError(true)}
                  aria-label="Recorded sparring footage. Pose overlays are part of the source video."
                />
                <span className="video-top-badge">
                  <Layers size={12} /> Pose replay
                </span>
                <span className="video-bottom-caption">
                  <span className="record-dot" /> LOCAL ARENA
                  <span>BLACK KIT × WHITE KIT</span>
                </span>
                {videoError && (
                  <div className="media-error">
                    <CircleHelp size={24} />
                    <strong>Video unavailable</strong>
                    <span>
                      Run npm run dev from frontend to prepare the bundled
                      sample.
                    </span>
                  </div>
                )}
              </div>
              <div className="transport">
                <div className="seek-wrap">
                  <input
                    aria-label="Replay position"
                    type="range"
                    min="0"
                    max={DURATION}
                    step=".01"
                    value={time}
                    onChange={(e) => seek(Number(e.target.value))}
                    style={
                      {
                        "--progress": `${(time / DURATION) * 100}%`,
                      } as React.CSSProperties
                    }
                  />
                  <div className="event-markers">
                    {EVENTS.map((event) => (
                      <button
                        key={event.event_id}
                        style={{ left: `${(event.t_s / DURATION) * 100}%` }}
                        className={`event-marker ${event.t_s <= time ? "past" : ""} ${event.outcome === "blocked" ? "block-marker" : ""}`}
                        aria-label={`Seek to ${event.title} at ${event.t_s.toFixed(1)} seconds`}
                        title={`${event.title} · ${event.t_s.toFixed(1)}s · scripted`}
                        onClick={() => selectEvent(event)}
                      />
                    ))}
                  </div>
                </div>
                <div className="transport-buttons">
                  <div>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={playing ? "Pause replay" : "Play replay"}
                      onClick={togglePlay}
                    >
                      {playing ? <Pause size={17} /> : <Play size={17} />}
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label="Restart replay"
                      onClick={() => {
                        video.current?.pause();
                        seek(0);
                        setFilter(null);
                      }}
                    >
                      <RotateCcw size={15} />
                    </Button>
                    <span className="timecode">
                      {formatTime(time)} <span>/ {formatTime(DURATION)}</span>
                    </span>
                  </div>
                  <div>
                    <select
                      aria-label="Playback speed"
                      className="speed-select"
                      value={rate}
                      onChange={(e) => {
                        setRate(e.target.value);
                        if (video.current)
                          video.current.playbackRate = Number(e.target.value);
                      }}
                    >
                      <option value=".25">0.25×</option>
                      <option value=".5">0.5×</option>
                      <option value="1">1×</option>
                      <option value="2">2×</option>
                    </select>
                    <span
                      className="silent-footage"
                      title="The bundled sample has no audio"
                    >
                      No audio
                    </span>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label="Open video fullscreen"
                      onClick={fullscreen}
                    >
                      <Expand size={16} />
                    </Button>
                  </div>
                </div>
                {mediaMessage && (
                  <p className="media-message" role="status">
                    {mediaMessage}
                  </p>
                )}
              </div>
            </Card>
            <Card className="market-card">
              <div className="card-heading">
                <div>
                  <span className="section-icon">
                    <Activity size={16} />
                  </span>
                  <h2>Prediction market</h2>
                </div>
                <Badge variant="outline">Sample quotes</Badge>
              </div>
              <div className="market-question">
                Who wins this matchup?<span>Binary market · simulated</span>
              </div>
              <div className="quote-grid">
                {(["A", "B"] as Fighter[]).map((f) => {
                  const change = quote[f] - QUOTES[0][f],
                    Up = change >= 0 ? ArrowUpRight : ArrowDownRight;
                  return (
                    <div
                      key={f}
                      className={`quote-item quote-${f.toLowerCase()}`}
                    >
                      <div className="quote-name">
                        <span
                          className={`tiny-fighter fighter-${f.toLowerCase()}`}
                        >
                          {f}
                        </span>
                        {FIGHTERS[f].short}
                      </div>
                      <div className="quote-value">
                        {quote[f]}
                        <span>%</span>
                        <span
                          className={`quote-change ${change >= 0 ? "positive" : "negative"}`}
                        >
                          <Up size={12} />
                          {change > 0 ? "+" : ""}
                          {change} pp
                        </span>
                      </div>
                      <span className="quote-price">
                        {quote[f]}¢ per YES share
                      </span>
                    </div>
                  );
                })}
              </div>
              <MarketChart time={time} onSeek={seek} windowSize={windowSize} />
              <div className="market-footer">
                <span>Market-implied probability · demo data</span>
                <div
                  className="chart-range"
                  role="group"
                  aria-label="Market chart range"
                >
                  <button
                    aria-pressed={windowSize === 5}
                    className={windowSize === 5 ? "active" : ""}
                    onClick={() => setWindowSize(5)}
                  >
                    5s
                  </button>
                  <button
                    aria-pressed={windowSize === 15}
                    className={windowSize === 15 ? "active" : ""}
                    onClick={() => setWindowSize(15)}
                  >
                    Full clip
                  </button>
                </div>
              </div>
            </Card>
          </div>
          <div className="analysis-column">
            <Card className="impact-card">
              <div className="card-heading">
                <div>
                  <span className="section-icon">
                    <Crosshair size={16} />
                  </span>
                  <h2>Impact mirror</h2>
                </div>
                <Badge variant="outline">Scripted events</Badge>
              </div>
              <p className="card-description">
                Received contacts, made visible.
              </p>
              <div className="mirrors">
                {(["A", "B"] as Fighter[]).map((f) => {
                  const total = ZONES.reduce((sum, z) => sum + counts[f][z], 0),
                    blocks = events.filter(
                      (e) =>
                        e.defender === f &&
                        e.status === "accepted" &&
                        e.outcome === "blocked",
                    ).length;
                  return (
                    <div className="mirror" key={f}>
                      <div className="mirror-identity">
                        <span
                          className={`tiny-fighter fighter-${f.toLowerCase()}`}
                        >
                          {f}
                        </span>
                        <strong>{FIGHTERS[f].name}</strong>
                      </div>
                      <div className="received-label">
                        Received from {f === "A" ? "B" : "A"}
                      </div>
                      <ImpactAvatar
                        fighter={f}
                        counts={counts[f]}
                        feedback={feedback}
                        onZone={(zone) => filterZone(f, zone)}
                      />
                      <div className="body-zone-list">
                        {ZONES.map((zone) => (
                          <button
                            key={zone}
                            className={`body-zone ${filter?.fighter === f && filter.zone === zone ? "selected" : ""}`}
                            aria-label={`Inspect ${FIGHTERS[f].name} ${zoneName[zone].toLowerCase()} contacts`}
                            aria-pressed={
                              filter?.fighter === f && filter.zone === zone
                            }
                            onClick={() => filterZone(f, zone)}
                          >
                            <span>{zoneName[zone]}</span>
                            <span className="heat-track">
                              <i
                                style={{
                                  width: `${Math.min(counts[f][zone] / 4, 1) * 100}%`,
                                }}
                              />
                            </span>
                            <strong>{counts[f][zone]}</strong>
                          </button>
                        ))}
                      </div>
                      <div className="mirror-total">
                        <span>{total} landed</span>
                        <span>
                          <Shield size={11} />
                          {blocks} blocked
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="impact-legend">
                <span>
                  <i className="contact-swatch" />
                  Confirmed contact
                </span>
                <span>
                  <Shield size={12} />
                  Blocked
                </span>
                <span className="heat-scale">
                  0 <i /> 4+
                </span>
              </div>
              <p className="impact-note">
                Heat shows contact counts, not damage. Select a region to
                inspect its events.
              </p>
            </Card>
            <Card className="exchange-card">
              <div className="card-heading">
                <div>
                  <span className="section-icon">
                    <Layers size={16} />
                  </span>
                  <h2>
                    {selectedId ? "Selected exchange" : "Latest exchange"}
                  </h2>
                </div>
                <span className="small-label">
                  {selected ? `${selected.t_s.toFixed(1)}s` : "—"}
                </span>
              </div>
              <div aria-live="polite" aria-atomic="true">
                {selected ? (
                  <>
                    <div className="exchange-title">
                      <h3>{selected.title}</h3>
                      <Badge
                        variant="secondary"
                        className={`outcome-badge ${selected.outcome}`}
                      >
                        <OutcomeIcon outcome={selected.outcome} />
                        {outcomeName[selected.outcome]}
                      </Badge>
                    </div>
                    <div className="exchange-direction">
                      <span
                        className={`tiny-fighter fighter-${selected.attacker.toLowerCase()}`}
                      >
                        {selected.attacker}
                      </span>
                      <ArrowRight size={12} />
                      <span
                        className={`tiny-fighter fighter-${selected.defender.toLowerCase()}`}
                      >
                        {selected.defender}
                      </span>
                      <span className="detail-divider" />
                      {zoneName[selected.contact_zone]}
                    </div>
                    <p className="exchange-observation">
                      {selected.observation}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      className="replay-button"
                      onClick={replayExchange}
                    >
                      <Play size={13} />
                      Replay exchange
                      <ChevronRight size={13} />
                    </Button>
                  </>
                ) : (
                  <div className="empty-exchange">
                    <Crosshair size={23} />
                    <p>Waiting for the first exchange</p>
                    <span>
                      Play the clip to follow the scripted event sequence.
                    </span>
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
        <Card className="events-card">
          <div className="events-heading">
            <div>
              <h2>Exchange timeline</h2>
              <span>
                {landed} landed<span className="text-separator">·</span>
                {blocked} blocked<span className="text-separator">·</span>Up to{" "}
                {formatTime(time)}
              </span>
            </div>
            {filter ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFilter(null)}
              >
                Fighter {filter.fighter} · {zoneName[filter.zone]}
                <X size={13} />
              </Button>
            ) : (
              <Badge variant="secondary">Click an event to revisit</Badge>
            )}
          </div>
          <div className="event-table-header">
            <span>TIME</span>
            <span>EXCHANGE</span>
            <span className="event-direction-column">DIRECTION</span>
            <span>RESULT</span>
            <span />
          </div>
          <div className="event-list">
            {filtered.length ? (
              filtered.map((event) => (
                <button
                  className={`event-row ${selectedId === event.event_id ? "selected" : ""}`}
                  key={event.event_id}
                  onClick={() => selectEvent(event)}
                  aria-label={`Review ${event.title}, ${event.outcome}, ${event.t_s.toFixed(1)} seconds`}
                >
                  <span className="event-time">
                    {event.t_s.toFixed(1)}
                    <small>s</small>
                  </span>
                  <span className="event-name">
                    <strong>{event.title}</strong>
                    <small>{zoneName[event.contact_zone]} · scripted</small>
                  </span>
                  <span className="event-direction-column event-direction">
                    <span
                      className={`tiny-fighter fighter-${event.attacker.toLowerCase()}`}
                    >
                      {event.attacker}
                    </span>
                    <ArrowRight size={12} />
                    <span
                      className={`tiny-fighter fighter-${event.defender.toLowerCase()}`}
                    >
                      {event.defender}
                    </span>
                  </span>
                  <span className={`event-result ${event.outcome}`}>
                    <OutcomeIcon outcome={event.outcome} />
                    {outcomeName[event.outcome]}
                  </span>
                  <ChevronRight size={14} className="event-chevron" />
                </button>
              ))
            ) : (
              <div className="event-empty">
                {filter
                  ? "No events in this region at the selected time."
                  : "No exchanges yet. Start the replay to see events."}
              </div>
            )}
          </div>
        </Card>
        <footer className="site-footer">
          <span>
            <Crosshair size={13} />
            FightLens<span className="footer-separator">/</span>Review prototype
          </span>
          <span>
            Recorded video · scripted contact events · simulated market prices
          </span>
        </footer>
      </main>
    </div>
    </div>
  );
}
