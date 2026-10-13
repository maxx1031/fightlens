// Win probability, same frames, two models: frames only vs frames + Cosmos verdicts,
// in step with the fight video. Data: compare_data.js (yolo_branch/compare.py);
// captions and chapters: compare_captions.js (optional; ?nocaps hides the captions).
// window.cmpSeek(t) renders the page at clip time t (used to record it frame by frame).
(() => {
  const video = document.getElementById("video");
  const D = CMP, dur = D.duration, N = D.names;
  const C = { a: "#f2b53b", b: "#5bb8ff", acc: "#9be22d", card: "#11151b", grid: "#1e242c", dim: "#6b7480", muted: "#8a94a3" };
  const $ = (id) => document.getElementById(id);
  const fmt = (s) => `0:${String(Math.floor(s)).padStart(2, "0")}`;
  const cap1 = (s) => s[0] + s.slice(1).toLowerCase();
  video.src = D.video;
  $("title").textContent = "FIGHTLENS" + (D.title ? " · " + D.title : ` · ${N.A} vs ${N.B}`);
  $("histTitle").textContent = `WIN PROBABILITY · ${N.A}`;
  video.addEventListener("loadedmetadata", () => {
    document.documentElement.style.setProperty("--aspect", video.videoWidth / video.videoHeight);
    window.dispatchEvent(new Event("resize"));
  });

  // ?nocaps records the page without burned-in captions (to caption it in an editor instead).
  const caps = typeof CAPTIONS === "undefined" || new URLSearchParams(location.search).has("nocaps") ? [] : CAPTIONS;
  const chapters = typeof CHAPTERS === "undefined" ? [] : CHAPTERS;
  $("beats").innerHTML = chapters.map(([a, b, tag]) => `<div class="beat"><span>${fmt(a)}–${fmt(b)}</span><b>${tag}</b></div>`).join("");
  if (!chapters.length) $("beats").remove();

  const EASE = 0.45;  // seconds a new estimate takes to slide in
  function valueAt(steps, t) {
    let i = -1;
    while (i + 1 < steps.length && steps[i + 1].t <= t) i++;
    if (i < 0) return null;
    const prev = i > 0 ? steps[i - 1].A : 0.5, u = Math.min(1, (t - steps[i].t) / EASE);
    return prev + (steps[i].A - prev) * (1 - (1 - u) * (1 - u));
  }
  const pct = (v) => Math.round(v * 100);

  function chart(t) {
    const canvas = $("chart"), dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const P = { l: 44, r: 92, t: 14, b: 24 }, X = (s) => P.l + (s / dur) * (w - P.l - P.r), Y = (v) => P.t + (1 - v) * (h - P.t - P.b);
    ctx.font = "11px 'JetBrains Mono', monospace"; ctx.textAlign = "right"; ctx.textBaseline = "middle"; ctx.fillStyle = C.dim;
    for (const v of [0, 0.5, 1]) {
      ctx.strokeStyle = C.grid; ctx.lineWidth = 1; ctx.setLineDash(v === 0.5 ? [3, 5] : []);
      ctx.beginPath(); ctx.moveTo(P.l, Y(v)); ctx.lineTo(w - P.r, Y(v)); ctx.stroke();
      ctx.fillText(pct(v) + "%", P.l - 8, Y(v));
    }
    ctx.setLineDash([]); ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (let s = 0; s <= dur + 1e-6; s += 5) ctx.fillText(fmt(s), X(s), h - P.b + 8);

    const series = (steps) => { const pts = []; for (let s = 0; s <= t + 1e-6; s += 1 / 30) { const v = valueAt(steps, s); if (v != null) pts.push([s, v]); } return pts; };
    const f = series(D.frames_only), c = series(D.with_cosmos);
    if (f.length && c.length) {  // the gap Cosmos opens, shaded
      ctx.fillStyle = C.acc + "1a"; ctx.beginPath();
      f.forEach(([s, v], i) => (i ? ctx.lineTo(X(s), Y(v)) : ctx.moveTo(X(s), Y(v))));
      for (let i = c.length - 1; i >= 0; i--) ctx.lineTo(X(c[i][0]), Y(c[i][1]));
      ctx.closePath(); ctx.fill();
    }
    const line = (pts, color, width, dash) => {
      if (!pts.length) return;
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineJoin = ctx.lineCap = "round"; ctx.setLineDash(dash);
      ctx.beginPath(); pts.forEach(([s, v], i) => (i ? ctx.lineTo(X(s), Y(v)) : ctx.moveTo(X(s), Y(v)))); ctx.stroke(); ctx.setLineDash([]);
    };
    line(f, C.dim, 2, [6, 5]);
    line(c, C.acc, 4, []);
    for (const r of D.verdicts) if (r.available <= t) {  // a diamond where each verdict arrived
      const x = X(r.available), y = Y(valueAt(D.with_cosmos, r.available) ?? 0.5);
      ctx.save(); ctx.translate(x, y); ctx.rotate(Math.PI / 4);
      ctx.fillStyle = C.acc; ctx.strokeStyle = C.card; ctx.lineWidth = 2; ctx.fillRect(-5, -5, 10, 10); ctx.strokeRect(-5, -5, 10, 10); ctx.restore();
    }
    if (!f.length || !c.length) return;
    const [sf, vf] = f[f.length - 1], [sc, vc] = c[c.length - 1];
    ctx.fillStyle = C.dim; ctx.beginPath(); ctx.arc(X(sf), Y(vf), 4, 0, 7); ctx.fill();
    ctx.fillStyle = C.acc; ctx.beginPath(); ctx.arc(X(sc), Y(vc), 6, 0, 7); ctx.fill();
    // Right margin: both current values, and the gap between them.
    const bx = w - P.r + 16, d = pct(vc) - pct(vf);
    ctx.textAlign = "left"; ctx.textBaseline = "middle";
    if (Math.abs(d) >= 3) {
      ctx.strokeStyle = C.acc; ctx.lineWidth = 1.5; ctx.beginPath();
      ctx.moveTo(bx - 5, Y(vf)); ctx.lineTo(bx + 5, Y(vf)); ctx.moveTo(bx, Y(vf)); ctx.lineTo(bx, Y(vc)); ctx.moveTo(bx - 5, Y(vc)); ctx.lineTo(bx + 5, Y(vc)); ctx.stroke();
      ctx.font = "600 12px 'JetBrains Mono', monospace"; ctx.fillStyle = C.acc;
      ctx.fillText((d > 0 ? "+" : "−") + Math.abs(d), bx + 12, (Y(vf) + Y(vc)) / 2);
    }
    ctx.font = "12px 'JetBrains Mono', monospace"; ctx.fillStyle = C.muted; ctx.fillText(pct(vf) + "%", bx + 12, Y(vf) + (Math.abs(d) < 3 ? -9 : 0));
    ctx.font = "600 13px 'JetBrains Mono', monospace"; ctx.fillStyle = C.acc; ctx.fillText(pct(vc) + "%", bx + 12, Y(vc) + (Math.abs(d) < 3 ? 9 : 0));
  }

  function captions(t) {  // t may run past the clip end: captions over the frozen last frame
    const c = caps.find(([a, b]) => a <= t && t < b), box = $("cap");
    if (c !== captions.last) { $("capTxt").innerHTML = c ? c[2] : ""; $("capEv").innerHTML = c && c[3] ? c[3] : ""; captions.last = c; }
    const u = c ? Math.max(0, Math.min(1, (t - c[0]) / 0.35, (c[1] - t) / 0.2)) : 0;
    box.style.opacity = u;
    box.style.transform = `translateX(-50%) translateY(${(1 - u) * 6}px)`;
  }

  function cards(t) {
    const g = valueAt(D.frames_only, t), c = valueAt(D.with_cosmos, t), done = D.verdicts.filter((r) => r.available <= t);
    // Hero: frames + Cosmos.
    $("vchip").textContent = done.length ? `◆ ${done.length} COSMOS VERDICT${done.length > 1 ? "S" : ""}` : "◆ COSMOS · WAITING";
    if (c == null) {
      $("winName").textContent = "—"; $("winPct").textContent = "—"; $("winName").style.color = $("winPct").style.color = C.muted;
      $("cA").style.width = $("cB").style.width = "0"; $("cA").textContent = $("cB").textContent = "";
    } else {
      const ca = pct(c), favB = ca < 50, color = favB ? C.b : C.a;
      $("winName").textContent = favB ? N.B : N.A; $("winPct").textContent = (favB ? 100 - ca : ca) + "%";
      $("winName").style.color = $("winPct").style.color = color;
      $("cA").style.width = c * 100 + "%"; $("cB").style.width = (1 - c) * 100 + "%";
      $("cA").textContent = `${N.A} ${ca}`; $("cB").textContent = `${N.B} ${100 - ca}`;
    }
    $("hcap").textContent = c == null ? "Waiting for the first exchange" : done.length ? `Pictures + ${done.length} Cosmos verdict${done.length > 1 ? "s" : ""}` : "Pictures only, so far";
    // Baseline: frames only.
    $("gA").textContent = `${N.A} ${g == null ? "—" : pct(g) + "%"}`; $("gB").textContent = `${N.B} ${g == null ? "—" : 100 - pct(g) + "%"}`;
    $("sA").style.width = g == null ? "0" : g * 100 + "%"; $("sB").style.width = g == null ? "0" : (1 - g) * 100 + "%";
    // Between them: what Cosmos changed.
    const delta = $("delta");
    if (g == null || c == null) delta.innerHTML = `<span class="eq">·</span><span>Waiting for the first exchange</span>`;
    else if (pct(g) === pct(c)) delta.innerHTML = `<span class="eq">=</span><span>Same input so far, so the same call</span>`;
    else delta.innerHTML = `<span class="up">▲</span><span>${(g >= 0.5) !== (c >= 0.5) ? "Cosmos flipped the favorite:" : "Cosmos moved the call:"}</span><span class="v">${cap1(N.A)} ${pct(g)}% → ${pct(c)}%</span>`;
    $("dot").style.opacity = 0.62 + 0.38 * Math.cos((2 * Math.PI * t) / 1.2);
  }

  const label = (f) => `<span class="${f}">${N[f]}</span>`;
  // Cosmos writes "Fighter A" / "A's head"; show the names instead.
  const named = (note) => note.replace(/\b(?:[Ff]ighter )?([AB])\b/g, (_, f) => N[f]);
  let lastCosmos = "";
  function cosmos(t) {
    const done = D.verdicts.filter((r) => r.available <= t), last = done[done.length - 1];
    const reviewing = D.verdicts.find((r) => r.t1 <= t && t < r.available);
    const key = (reviewing ? "r" + reviewing.t0 : "") + (last ? "v" + last.t0 : "w");
    if (key === lastCosmos) return;
    lastCosmos = key;
    const what = (r) => `${r.kind === "kick" ? "Kick clip" : "Exchange"} ${fmt(r.t0)}–${fmt(r.t1)}`;
    $("feed").textContent = reviewing ? `Reviewing ${what(reviewing).toLowerCase()}…`
      : last ? `${what(last)} reviewed` : "Watching · no exchange sent yet";
    $("strikes").innerHTML = last ? (last.strikes.length ? last.strikes : [null]).map((s) => s
      ? `<li>${label(s.attacker)} ${s.move} → ${s.target} · <span class="${s.outcome}">${s.outcome.toUpperCase()}</span></li>`
      : `<li class="missed">no strikes thrown</li>`).join("") : "";
    $("note").hidden = !last;
    $("note").textContent = last ? named(last.note) : "";
  }

  function render(t) {
    captions(t);
    t = Math.max(0, Math.min(dur, t));
    $("clock").textContent = fmt(t);
    document.querySelectorAll(".beat").forEach((e, i) => e.classList.toggle("on", chapters[i][0] <= t && t < chapters[i][1] + (i === chapters.length - 1 ? 1 : 0)));
    cards(t);
    cosmos(t);
    chart(t);
  }

  // Live playback: loop the clip's stretch of the video.
  video.addEventListener("loadedmetadata", () => { video.currentTime = D.offset; if (!window.cmpRecording) video.play().catch(() => {}); });
  (function tick() {
    if (!window.cmpRecording) {
      const t = video.currentTime - D.offset;
      if (t >= dur || t < -0.5) video.currentTime = D.offset;
      render(t);
    }
    requestAnimationFrame(tick);
  })();
  window.cmpSeek = (t) => new Promise((resolve) => {
    window.cmpRecording = true;
    video.pause();
    const done = () => { render(t); requestAnimationFrame(() => requestAnimationFrame(resolve)); };
    const at = D.offset + Math.min(t, dur - 0.02);
    if (Math.abs(video.currentTime - at) < 1e-3) return done();
    video.addEventListener("seeked", done, { once: true });
    video.currentTime = at;
  });
  window.addEventListener("resize", () => { lastCosmos = ""; render(video.currentTime - D.offset); });
})();
