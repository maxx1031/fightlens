// FightLens arcade HUD driven by a live session (test page).
// Joins the session as an extra viewer (own LiveKit identity), shows the worker's
// YOLO video track, and computes engagement HUD values and contact candidates from
// the per-frame "fightlens.pose" packets. Nothing here writes to the session.
const $ = (id) => document.getElementById(id);
const LK = window.LivekitClient;
const pct = (x) => Math.round(x * 100);

// ---- session id -------------------------------------------------------------
function sessionFrom(text) {
  const m = String(text || "").match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  return m ? m[0] : null;
}
const sessionId = sessionFrom(new URLSearchParams(location.search).get("session"));

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify({ requestId: crypto.randomUUID(), ...body }) : undefined,
    cache: "no-store",
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error?.message || `Request failed (${response.status})`);
  return result;
}

// ---- strikes from raw keypoints (live port of yolo_branch/hits.py) ----------------
// Punches are detected per arm from raw (unsmoothed) keypoints, using the puncher's own
// torso length as scale, so a punch counts even if the other fighter is briefly lost.
const PUNCH_EXT_ON = 0.8, PUNCH_EXT_RESET = 0.65, PUNCH_SPEED = 2.0, PUNCH_SPEED_WINDOW_S = 0.3;
const W_KICK = 7.0, STRIKE_WINDOW_S = 0.2, KICK_DEDUP_S = 0.5, CONTACT = 0.6, KPT_CONF = 0.3;
const HEAD = [0, 1, 2, 3, 4], SH = [5, 6], HIP = [11, 12], KNEE = [13, 14], AN = [15, 16];
const ARMS = [[5, 7, 9], [6, 8, 10]];

const ok = (p) => p && p[2] >= KPT_CONF;
function mean(k, idx) {
  const pts = idx.map((i) => k[i]).filter(ok);
  if (!pts.length) return null;
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
}
const mid = (a, b) => (a && b ? [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] : null);
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const near = (p, target, scale) => (ok(p) && target ? dist(p, target) / scale : Infinity);
function median(xs) { const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; }

class ContactDetector {
  constructor(onStrike, onPunch) { this.onStrike = onStrike; this.onPunch = onPunch; this.reset(); }
  reset() { this.f = { A: this.fresh(), B: this.fresh() }; }
  fresh() {
    return { torso: [], arms: [0, 1].map(() => ({ armed: true, hist: [], dists: [], pending: null })),
             prev: null, speeds: [], kick: null, lastKick: -Infinity };
  }
  push(t, fighters) {
    for (const [me, opp] of [["A", "B"], ["B", "A"]]) {
      const mine = fighters[me]?.kpts, o = fighters[opp]?.kpts, st = this.f[me];
      if (!mine) continue;
      const sh = mean(mine, SH), hp = mean(mine, HIP);
      if (sh && hp && dist(sh, hp) > 1) st.torso.push([t, dist(sh, hp)]);
      while (st.torso.length && st.torso[0][0] < t - 1) st.torso.shift();
      if (!st.torso.length) continue;
      const scale = median(st.torso.map((x) => x[1]));
      const zones = o ? { head: mean(o, HEAD), body: mid(mean(o, SH), mean(o, HIP)), leg: mid(mean(o, HIP), mean(o, KNEE)) } : null;
      ARMS.forEach(([s, e, w], j) => {
        const arm = st.arms[j], k = mine;
        if (zones) {  // wrist-to-opponent distances, kept briefly for judging a punch
          arm.dists.push([t, near(k[w], zones.head, scale), near(k[w], zones.body, scale)]);
          while (arm.dists.length && arm.dists[0][0] < t - 2 * STRIKE_WINDOW_S) arm.dists.shift();
        }
        if (ok(k[s]) && ok(k[e]) && ok(k[w])) {
          const len = dist(k[s], k[e]) + dist(k[e], k[w]);
          const ext = len > 1 ? dist(k[s], k[w]) / len : null;
          const rel = [k[w][0] - k[s][0], k[w][1] - k[s][1]];
          const last = arm.hist.at(-1);
          const speed = last && t - last.t > 0 && t - last.t <= 0.5 ? dist(rel, last.rel) / (t - last.t) / scale : 0;
          arm.hist.push({ t, ext, rel, speed });
          while (arm.hist.length && arm.hist[0].t < t - PUNCH_SPEED_WINDOW_S) arm.hist.shift();
          if (ext !== null && ext < PUNCH_EXT_RESET) arm.armed = true;
          const fast = arm.hist.some((h) => h.speed >= PUNCH_SPEED);
          if (arm.armed && ext !== null && ext >= PUNCH_EXT_ON && fast) {
            arm.armed = false;
            this.onPunch?.({ t, who: me, arm: j ? "right" : "left" });
            if (zones) arm.pending = { t };
          }
        }
        if (arm.pending && t - arm.pending.t >= STRIKE_WINDOW_S) {  // judge at the closest approach
          const win = arm.dists.filter((d) => Math.abs(d[0] - arm.pending.t) <= STRIKE_WINDOW_S);
          let best = null;
          for (const [dt, dh, db] of win) for (const [zone, d] of [["head", dh], ["body", db]])
            if (isFinite(d) && (!best || d < best.d)) best = { t: dt, zone, d };
          if (best) this.emit(me, opp, "punch", best);
          arm.pending = null;
        }
      });
      if (!zones) { st.prev = null; continue; }
      // kick: peak of ankle speed relative to own hips, judged within +-STRIKE_WINDOW_S
      const rel = AN.map((i) => (ok(mine[i]) && hp ? [mine[i][0] - hp[0], mine[i][1] - hp[1]] : null));
      let speed = null;
      if (st.prev && t - st.prev.t > 0 && t - st.prev.t <= 0.5)
        for (let j = 0; j < 2; j++) if (rel[j] && st.prev.rel[j]) speed = Math.max(speed ?? 0, dist(rel[j], st.prev.rel[j]) / (t - st.prev.t) / scale);
      st.prev = { t, rel };
      const ankle = { leg: Math.min(...AN.map((i) => near(mine[i], zones.leg, scale))),
                      body: Math.min(...AN.map((i) => near(mine[i], zones.body, scale))),
                      head: Math.min(...AN.map((i) => near(mine[i], zones.head, scale))) };
      const za = Object.keys(ankle).reduce((a, b) => (ankle[a] <= ankle[b] ? a : b));
      st.speeds.push(speed); if (st.speeds.length > 3) st.speeds.shift();
      const [s0, s1, s2] = st.speeds;
      if (!st.kick && s1 != null && s1 >= W_KICK && s1 >= (s0 ?? 0) && s1 >= (s2 ?? 0)) st.kick = { peak: t, t, zone: za, d: ankle[za] };
      if (st.kick) {
        if (ankle[za] < st.kick.d) Object.assign(st.kick, { t, zone: za, d: ankle[za] });
        if (t - st.kick.peak >= STRIKE_WINDOW_S) {
          if (isFinite(st.kick.d) && st.kick.t - st.lastKick >= KICK_DEDUP_S) { this.emit(me, opp, "kick", st.kick); st.lastKick = st.kick.t; }
          st.kick = null;
        }
      }
    }
  }
  emit(attacker, defender, limb, s) {
    this.onStrike({ t: s.t, attacker, defender, limb, zone: s.zone, dist: s.d, contact: s.d < CONTACT });
  }
}

// ---- HUD state ---------------------------------------------------------------
const ZONES = [["head", "HEAD"], ["body", "BODY"], ["leg", "LEGS"]];
const BODY = '<svg viewBox="0 0 120 240" aria-hidden="true"><circle class="z" data-z="head" cx="60" cy="24" r="17"/><path class="z" data-z="body" d="M34 48h52l16 6 8 66-12 4-8-50v50H38V74l-8 50-12-4 8-66z"/><path class="z" data-z="leg" d="M38 126h44l-4 108H63l-3-78-3 78H42z"/></svg>';
for (const who of ["A", "B"])
  $("heat" + who).outerHTML = '<div class="hcard ' + who.toLowerCase() + '" id="heat' + who + '"><div class="who"><b>FIGHTER ' + who + '</b><span id="heatName' + who + '"></span></div>' + BODY +
    "<ul>" + ZONES.map(([z, l]) => "<li>" + l + '<b id="n' + who + z + '">0</b></li>').join("") + '</ul><div class="last" id="heatLast' + who + '">No contact candidates yet</div></div>';
const heatColor = (n) => (n <= 0 ? "#2b2f38" : ["#6e2a25", "#a3332b", "#d63b30", "#ff4a3d"][Math.min(n, 4) - 1]);

let snap = null, segmentKey = null, t0 = null, lastPoseAt = 0;
const strikes = [], punches = { A: 0, B: 0 }, poseTimes = [];
let lastMove = null;
const detector = new ContactDetector((s) => {
  strikes.push(s);
  if (s.contact) { renderHeat(); flash(s.defender, s.zone); }
}, (p) => {
  if (lastMove && lastMove.who === p.who && p.t - lastMove.t < 0.15) return;  // both arms at once = one punch
  punches[p.who] += 1; lastMove = p;
});

// ---- win probability (Luna Decisions via the local winprob_server.py) ------------
// Engaged seconds only: up to WP_FRAMES frames of the YOLO video are sent once the second ends.
const WP_URL = "http://127.0.0.1:8787/winprob", WP_FRAMES = 6, WP_MIN_ENGAGED = 0.5, WP_WIDTH = 480;
const wp = { win: null, frames: [], engaged: 0, total: 0, lastShot: -1, busy: false, points: [], error: null };
const shot = document.createElement("canvas");
function capture() {
  const v = $("video");
  if (!v.videoWidth) return null;
  shot.width = WP_WIDTH; shot.height = Math.round(v.videoHeight * WP_WIDTH / v.videoWidth);
  shot.getContext("2d").drawImage(v, 0, 0, shot.width, shot.height);
  return shot.toDataURL("image/jpeg", 0.6);
}
function wpReset() { Object.assign(wp, { win: null, frames: [], engaged: 0, total: 0, lastShot: -1, points: [], error: null }); renderWin(null); }
function wpFrame(t, engaged) {
  const k = Math.floor(t);
  if (wp.win !== null && k !== wp.win) wpSend(wp.win);
  if (k !== wp.win) Object.assign(wp, { win: k, frames: [], engaged: 0, total: 0, lastShot: -1 });
  wp.total += 1;
  if (engaged) wp.engaged += 1;
  if (engaged && wp.frames.length < WP_FRAMES && t - wp.lastShot >= 1 / WP_FRAMES - 0.01) {
    const f = capture();
    if (f) { wp.frames.push(f); wp.lastShot = t; }
  }
}
async function wpSend(k) {
  if (wp.busy || wp.frames.length < 2 || wp.engaged / Math.max(1, wp.total) < WP_MIN_ENGAGED) return;
  wp.busy = true;
  const key = segmentKey;
  try {
    const r = await fetch(WP_URL, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: sessionId, segment: key, t0: k, t1: k + 1, fighters: snap?.captionFighters ?? {}, frames: wp.frames }) });
    const out = await r.json();
    if (!r.ok) throw new Error(out.error || "request failed");
    if (key === segmentKey) { wp.points.push({ t: out.end_s, A: out.probabilities.A, latency: out.latency_s }); wp.error = null; }
  } catch (e) {
    wp.error = e instanceof TypeError ? "Win-probability server offline (run yolo_branch/winprob_server.py)" : e.message;
  } finally { wp.busy = false; }
}
function renderWin(t) {
  const last = wp.points.at(-1), prev = wp.points.at(-2), a = last ? last.A : null;
  $("wpA").textContent = a == null ? "—" : pct(a) + "%";
  $("wpB").textContent = a == null ? "—" : 100 - pct(a) + "%";
  $("wpFill").style.width = (a == null ? 50 : a * 100) + "%";
  $("wpInA").textContent = a == null ? "" : "A " + pct(a) + "%";
  $("wpInB").textContent = a == null ? "" : 100 - pct(a) + "% B";
  $("wpInA").style.visibility = a != null && a >= 0.12 ? "visible" : "hidden";  // too narrow to label
  $("wpInB").style.visibility = a != null && a <= 0.88 ? "visible" : "hidden";
  document.querySelector(".wp-bar").classList.toggle("empty", a == null);
  $("wpStatus").textContent = wp.error ? wp.error
    : !last ? (wp.busy ? "Asking Luna about the last engaged second…" : "No estimate yet · waiting for an engaged second")
    : t !== null && t - last.t < 1.5 ? "Updated at " + clock(last.t) + " · engaged second · " + last.latency + "s"
    : "Held since " + clock(last.t) + " · no engagement, not sampled";
  $("wpTrend").textContent = last && prev ? "A " + (pct(last.A) - pct(prev.A) >= 0 ? "+" : "") + (pct(last.A) - pct(prev.A)) + " pts" : "";
}

function renderHeat() {
  for (const who of ["A", "B"]) {
    const got = strikes.filter((h) => h.contact && h.defender === who);
    for (const [z] of ZONES) {
      const n = got.filter((h) => h.zone === z).length;
      $("n" + who + z).textContent = n;
      $("n" + who + z).classList.toggle("hot", n > 0);
      document.querySelector("#heat" + who + ' [data-z="' + z + '"]').style.fill = heatColor(n);
    }
    const last = got.at(-1);
    $("heatLast" + who).textContent = last ? "Last: " + last.zone + " · " + last.limb + " by " + last.attacker + " · " + clock(last.t) : "No contact candidates yet";
  }
}
function flash(who, zone) {
  const el = document.querySelector("#heat" + who + ' [data-z="' + zone + '"]');
  el.classList.remove("flash"); void el.getBoundingClientRect(); el.classList.add("flash");
}
const clock = (t) => { const s = Math.max(0, Math.floor(t - (t0 ?? t))); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };

function resetSegment() {
  detector.reset(); strikes.length = 0; punches.A = punches.B = 0; t0 = null; lastMove = null;
  wpReset(); renderHeat(); $("countA").textContent = $("countB").textContent = "00"; $("move").textContent = "Waiting for an action";
}

function onPose(pose) {
  if (!snap || pose.session_id !== sessionId) return;
  const key = pose.segment_id + ":" + pose.analysis_revision + ":" + pose.worker_generation;
  if (key !== segmentKey) { segmentKey = key; resetSegment(); }
  const t = pose.received_position_ms / 1000;
  if (t0 === null) t0 = t;
  lastPoseAt = performance.now();
  poseTimes.push(lastPoseAt); while (poseTimes.length && poseTimes[0] < lastPoseAt - 2000) poseTimes.shift();
  const sig = pose.signals, ext = { A: sig.extension_a, B: sig.extension_b }, reach = { A: sig.reach_a, B: sig.reach_b };
  if (pose.identity_status !== "lost") detector.push(t, pose.fighters);
  wpFrame(t, pose.signals.engaged === 1);
  renderWin(t);
  for (const who of ["A", "B"]) {
    const p = reach[who] == null || ext[who] == null ? null : Math.round(Math.min(1, Math.max(0, 1 - reach[who] / 1.5)) * ext[who] * 100);
    $("bar" + who).style.width = (p ?? 0) + "%";
    $("pressure" + who).textContent = p ?? "—";
    $("count" + who).textContent = String(punches[who]).padStart(2, "0");
  }
  $("move").textContent = lastMove ? lastMove.who + " · " + lastMove.arm + " punch / " + clock(lastMove.t) : "Waiting for an action";
  const known = sig.engaged !== null, engaged = sig.engaged === 1;
  $("state").textContent = !known ? "UNKNOWN" : engaged ? "ENGAGE!" : "CLEAR";
  $("stateText").textContent = !known ? "Tracking uncertain · identity " + pose.identity_status : engaged ? "Exchange active · Stay alert" : "Current rule: no engagement";
  $("callout").classList.toggle("hot", engaged);
  $("risk").textContent = !known ? "Tracking uncertain" : engaged ? "Engagement alert" : "Alert cleared";
  $("light").style.color = !known ? "#888" : engaged ? "#ff6552" : "#89e39e";
  $("clock").textContent = clock(t);
  $("liveStatus").textContent = "YOLO " + (poseTimes.length / 2).toFixed(0) + " fps · worker " + Math.round(pose.worker_latency_ms) + " ms · " + sig.state + " · identity " + pose.identity_status;
  $("time").textContent = clock(t);
}

function onSnapshot(s) {
  snap = s;
  const names = s.captionFighters;
  $("kitA").textContent = "PLAYER 01 / " + (names?.A ? names.A.toUpperCase() : "FIGHTER A");
  $("kitB").textContent = (names?.B ? names.B.toUpperCase() : "FIGHTER B") + " / PLAYER 02";
  $("heatNameA").textContent = names?.A ?? ""; $("heatNameB").textContent = names?.B ?? "";
  const cap = s.caption?.caption, capStatus = s.caption?.status;
  $("caption").textContent = cap?.text
    ? cap.text + "  (" + cap.t0_s.toFixed(1) + "–" + cap.t1_s.toFixed(1) + "s)"
    : !s.captionFighters ? "Cosmos commentary appears here once A/B are confirmed on the session page."
    : capStatus === "not_configured" ? "Cosmos is not configured for this worker."
    : capStatus === "error" ? "Cosmos review failed (" + (s.caption.error_code || "error") + ")."
    : "Waiting for the next Cosmos review…";
  const ended = s.state === "ended";
  $("liveTag").textContent = ended ? "● SESSION ENDED" : s.paused ? "● ANALYSIS PAUSED" : "● LIVE";
  $("liveDot").style.color = ended ? "#888" : s.paused ? "#ffb91b" : "#ff5145";
  if (ended) $("liveStatus").textContent = "Session ended";
}

// ---- connection ----------------------------------------------------------------
async function connect() {
  const join = await api("/api/sessions/" + sessionId + "/join", { mode: "viewer" });
  onSnapshot(join.snapshot);
  const room = new LK.Room({ adaptiveStream: false, dynacast: false });
  // Subscribe only to the worker's annotated output track, like the session page does.
  const selected = (participant, publication) =>
    !!snap && participant.identity === snap.workerIdentity && publication.trackSid === snap.outputTrackId;
  const sync = () => {
    for (const p of room.remoteParticipants.values())
      for (const pub of p.trackPublications.values()) {
        const want = selected(p, pub);
        if (pub.isSubscribed !== want) pub.setSubscribed(want);
        if (want && pub.track) attach(pub.track, pub, p);
      }
  };
  const attach = (track, publication, participant) => {
    if (track.kind !== "video" || !selected(participant, publication)) return;
    if ($("video").srcObject && track.attachedElements.includes($("video"))) return;
    track.attach($("video"));
    $("video").play().catch(() => ($("stateText").textContent = "Click the video to play"));
  };
  room.on(LK.RoomEvent.TrackSubscribed, attach);
  room.on(LK.RoomEvent.TrackPublished, sync);
  room.on(LK.RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
    if (topic !== "fightlens.pose" || participant?.identity !== snap?.workerIdentity || payload.length > 8192) return;
    try { onPose(JSON.parse(new TextDecoder().decode(payload))); } catch { /* ignore malformed packets */ }
  });
  room.on(LK.RoomEvent.Disconnected, () => { $("liveTag").textContent = "● DISCONNECTED"; $("liveStatus").textContent = "Disconnected · reload to rejoin"; });
  await room.connect(join.url, join.token, { autoSubscribe: false });
  sync();
  $("video").onclick = () => $("video").play();
  setInterval(async () => {
    try {
      const s = await api("/api/sessions/" + sessionId);
      onSnapshot(s);
      sync();
    } catch (e) { $("liveStatus").textContent = e.message; }
    if (performance.now() - lastPoseAt > 2500 && snap?.state === "active" && !snap.paused) $("stateText").textContent = "Waiting for live pose data…";
  }, 1000);
}

renderHeat();
if (!sessionId) {
  $("pick").hidden = false;
  $("stateText").textContent = "Paste the live session link below";
  $("pick").onsubmit = (e) => {
    e.preventDefault();
    const id = sessionFrom($("sessionInput").value);
    if (id) location.search = "?session=" + id;
  };
} else {
  connect().catch((e) => {
    $("liveTag").textContent = "● NOT CONNECTED";
    $("liveStatus").textContent = e.message;
    $("stateText").textContent = e.message;
  });
}
