// Data console: pipeline summary (cheap sentinel -> expensive referee -> decision layer)
// and analysis charts drawn in step with the replay video. Uses DATA (data.js) and the
// page's <video id="video">; clicking a chart seeks the video.
(() => {
  const video = document.getElementById("video");
  const t = DATA.t, n = t.length, fps = DATA.fps, duration = t[n - 1] + 1 / fps;
  const winPts = DATA.win_points || [], rounds = DATA.segments || [], refs = DATA.referee || [];
  const C = { a: "#ffb91b", b: "#36b5ff", cog: "#50e050", hit: "#ff5145", cut: "#7a3cff", grid: "#262b33", muted: "#8d939f", model: "#c38bff" };

  // ---- pipeline numbers ---------------------------------------------------------
  const engagedFrames = DATA.engaged.filter((e) => e === 1).length;
  const windows = [];  // engaged runs = clips a video model would review
  for (let i = 0, s = null; i <= n; i++) {
    const on = i < n && DATA.engaged[i] === 1;
    if (on && s === null) s = t[i];
    if (!on && s !== null) { windows.push([s, t[i - 1] + 1 / fps]); s = null; }
  }
  const seconds = Math.round(duration);
  const sent = winPts.length;
  const pct = (x) => Math.round(x * 100);
  const strikes = refs.flatMap((r) => (r.cosmos && r.cosmos.strikes) || []);
  const landedCount = strikes.filter((x) => x.outcome === "landed").length, blockedCount = strikes.filter((x) => x.outcome === "blocked").length;
  const avgLatency = (k) => { const xs = refs.map((r) => r[k] && r[k].latency_s).filter((x) => x != null); return xs.length ? (xs.reduce((a, b) => a + b) / xs.length).toFixed(1) : "—"; };
  const cosmosModel = ((refs.find((r) => r.cosmos && r.cosmos.model) || {}).cosmos || {}).model || "Cosmos";
  const jevModel = ((refs.find((r) => r.jev && r.jev.model) || {}).jev || {}).model || "Jev";
  const stage = (cls, k, title, big, unit, lines) =>
    `<div class="stage ${cls}"><small>${k}</small><h3>${title}</h3><strong>${big}<em>${unit}</em></strong>${lines.map((l) => `<p>${l}</p>`).join("")}</div>`;
  document.getElementById("stages").innerHTML =
    stage("yolo", "01 · ALWAYS ON", "YOLO sentinel", n, "frames",
      ["Pose + tracking on <b>every</b> frame (100%)", "Cheap: distance, reach, arm extension, limb speed",
       `Flags engagement on <b>${pct(engagedFrames / n)}%</b> of frames`]) +
    `<div class="arrow">→</div>` +
    stage("cosmos", "02 · ONLY WHEN FLAGGED", "Cosmos referee", refs.length, "clips",
      [`Reviewed <b>${refs.reduce((s, r) => s + r.t1 - r.t0, 0).toFixed(1)} s</b> of ${duration.toFixed(0)} s: engaged stretches + context, ≤ 3 s clips`,
       `Prompt = task + YOLO output (signals, strike candidates) · <b>${refs.reduce((s, r) => s + (r.frames || 0), 0)}</b> frames at 4 fps`,
       `Verdicts: <b>${landedCount}</b> landed · <b>${blockedCount}</b> blocked · avg <b>${avgLatency("cosmos")} s</b> per clip (${cosmosModel})`]) +
    `<div class="arrow">→</div>` +
    stage("decision", "03 · ON NEW EVIDENCE", "Jev · decision layer", refs.filter((r) => r.jev && r.jev.direction).length, "judgments",
      [`Per exchange: direction + evidence type (${jevModel}, avg <b>${avgLatency("jev")} s</b>)`,
       `Win probability: <b>${sent}</b> of ${seconds} s updated, <b>${sent * 2}</b> Luna Decisions calls; <b>${seconds - sent}</b> s held`,
       "Uncalibrated model estimates"]);

  // ---- charts ---------------------------------------------------------------------
  const specs = [
    { id: "win", title: "Win probability · A", note: "dots = decision-layer updates · flat = held between exchanges · dashed = 50%",
      series: [{ key: "win_A", color: C.a }], range: [0, 1], lines: [0.5], dots: true, h: 150 },
    { id: "pipe", title: "Sentinel → referee → decision", note: "YOLO = engaged · Cosmos = clip reviewed (red landed, blue blocked, grey no clean hit), shown when its verdict returns · Jev = direction · Luna = win-probability update",
      strip: true, h: 118 },
    { id: "com", title: "Center distance", note: "between shoulder/hip centers · torso lengths", series: [{ key: "com_dist", color: C.cog }], h: 120 },
    { id: "reach", title: "Wrist to opponent", note: "lower = closer", series: [{ key: "reach_A", color: C.a }, { key: "reach_B", color: C.b }], h: 120 },
    { id: "ext", title: "Arm extension", note: "1 = straight · dashed 0.9 = punch candidate", series: [{ key: "ext_A", color: C.a }, { key: "ext_B", color: C.b }], range: [0, 1.05], lines: [0.9], h: 120 },
  ];
  const host = document.getElementById("charts");
  host.innerHTML = specs.map((s) => `<div class="tchart"><div class="thead"><b>${s.title}</b><span>${s.note}</span></div><canvas id="tc-${s.id}" style="height:${s.h}px"></canvas></div>`).join("");
  for (const s of specs) {
    s.canvas = document.getElementById("tc-" + s.id);
    s.ctx = s.canvas.getContext("2d");
    if (!s.range && s.series) {
      let lo = Infinity, hi = -Infinity;
      for (const se of s.series) for (const v of DATA[se.key]) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      const pad = (hi - lo) * 0.1 || 0.1;
      s.range = [Math.max(0, lo - pad), hi + pad];
    }
    let dragging = false;
    const seek = (e) => {
      const r = s.canvas.getBoundingClientRect();
      video.currentTime = Math.max(0, Math.min(duration - 0.01, ((e.clientX - r.left - P.l) / (r.width - P.l - P.r)) * duration));
    };
    s.canvas.addEventListener("pointerdown", (e) => { dragging = true; s.canvas.setPointerCapture(e.pointerId); seek(e); });
    s.canvas.addEventListener("pointermove", (e) => dragging && seek(e));
    s.canvas.addEventListener("pointerup", () => (dragging = false));
  }

  const P = { l: 50, r: 10, t: 8, b: 18 };
  function size() {
    const dpr = window.devicePixelRatio || 1;
    for (const s of specs) {
      const r = s.canvas.getBoundingClientRect();
      s.w = r.width; s.h2 = r.height;
      s.canvas.width = Math.round(r.width * dpr); s.canvas.height = Math.round(r.height * dpr);
      s.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  }

  function draw(cur) {
    for (const s of specs) {
      const { ctx, w } = s, h = s.h2;
      if (!w) continue;
      const X = (time) => P.l + (time / duration) * (w - P.l - P.r);
      ctx.clearRect(0, 0, w, h);
      ctx.font = "10px ui-monospace, monospace"; ctx.fillStyle = C.muted; ctx.textBaseline = "top"; ctx.textAlign = "center";
      for (let x = 0; x <= duration; x += 5) ctx.fillText(x + "s", X(x), h - P.b + 4);
      for (const r of rounds.slice(1)) { ctx.strokeStyle = "#555"; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(X(r.start), P.t); ctx.lineTo(X(r.start), h - P.b); ctx.stroke(); ctx.setLineDash([]); }
      if (s.strip) {
        const rows = [["YOLO", P.t + 4, 20], ["Cosmos", P.t + 30, 18], ["Jev", P.t + 54, 16], ["Luna", P.t + 76, 12]];
        ctx.textAlign = "right"; ctx.textBaseline = "middle";
        for (const [label, y, hh] of rows) { ctx.fillStyle = "#1c2028"; ctx.fillRect(P.l, y, w - P.l - P.r, hh); ctx.fillStyle = C.muted; ctx.fillText(label, P.l - 6, y + hh / 2); }
        for (const [a, b] of windows) {
          if (a > t[cur]) continue;
          ctx.fillStyle = C.hit; ctx.fillRect(X(a), rows[0][1], X(Math.min(b, t[cur])) - X(a), rows[0][2]);
        }
        const now = t[cur], atEnd = cur >= n - 1;
        for (const r of refs) {
          if (r.available > now + 1e-6 && !atEnd) continue;  // appears when its verdict would have returned
          const st = (r.cosmos && r.cosmos.strikes) || [];
          ctx.fillStyle = st.some((x) => x.outcome === "landed") ? C.hit : st.some((x) => x.outcome === "blocked") ? C.b : "#6b7280";
          ctx.fillRect(X(r.t0) + 1, rows[1][1], X(r.t1) - X(r.t0) - 2, rows[1][2]);
          const d = r.jev && r.jev.direction && r.jev.direction.choice;
          ctx.fillStyle = d === "favors_A" ? C.a : d === "favors_B" ? C.b : "#6b7280";
          ctx.fillRect(X(r.t0) + 1, rows[2][1], X(r.t1) - X(r.t0) - 2, rows[2][2]);
          ctx.fillStyle = "#0b0d11"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = "bold 10px ui-monospace, monospace";
          if (X(r.t1) - X(r.t0) > 14) ctx.fillText(d === "favors_A" ? "A" : d === "favors_B" ? "B" : "=", (X(r.t0) + X(r.t1)) / 2, rows[2][1] + rows[2][2] / 2);
          ctx.font = "10px ui-monospace, monospace";
        }
        for (const p of winPts) {
          if (p.t > t[cur] + 1e-6) continue;
          ctx.fillStyle = C.model; ctx.fillRect(X(p.t - 1) + 1, rows[3][1], X(p.t) - X(p.t - 1) - 2, rows[3][2]);
        }
      } else {
        const [lo, hi] = s.range, Y = (v) => P.t + (1 - (v - lo) / (hi - lo)) * (h - P.t - P.b);
        ctx.strokeStyle = C.grid; ctx.lineWidth = 1; ctx.textAlign = "right"; ctx.textBaseline = "middle";
        for (let k = 0; k <= 2; k++) {
          const v = lo + ((hi - lo) * k) / 2;
          ctx.beginPath(); ctx.moveTo(P.l, Y(v)); ctx.lineTo(w - P.r, Y(v)); ctx.stroke();
          ctx.fillStyle = C.muted; ctx.fillText(s.id === "win" ? pct(v) + "%" : v.toFixed(1), P.l - 6, Y(v));
        }
        for (const v of s.lines || []) { ctx.strokeStyle = "#666"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(P.l, Y(v)); ctx.lineTo(w - P.r, Y(v)); ctx.stroke(); ctx.setLineDash([]); }
        for (const c of DATA.cuts || []) { ctx.strokeStyle = C.cut; ctx.globalAlpha = 0.5; ctx.beginPath(); ctx.moveTo(X(c), P.t); ctx.lineTo(X(c), h - P.b); ctx.stroke(); ctx.globalAlpha = 1; }
        for (const se of s.series) {
          const ys = DATA[se.key];
          for (const [alpha, upto] of [[0.18, n - 1], [1, cur]]) {
            ctx.globalAlpha = alpha; ctx.strokeStyle = se.color; ctx.lineWidth = alpha < 1 ? 1 : 1.8; ctx.beginPath();
            let open = false;
            for (let i = 0; i <= upto; i++) {
              if (ys[i] == null) { open = false; continue; }
              open ? ctx.lineTo(X(t[i]), Y(ys[i])) : ctx.moveTo(X(t[i]), Y(ys[i])); open = true;
            }
            ctx.stroke();
          }
          ctx.globalAlpha = 1;
        }
        if (s.dots) for (const p of winPts) {
          if (p.t > t[cur] + 1e-6) continue;
          ctx.fillStyle = C.a; ctx.strokeStyle = "#000"; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.arc(X(p.t), Y(p.A), 3.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        }
      }
      ctx.strokeStyle = "rgba(255,255,255,.75)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(X(t[cur]), P.t); ctx.lineTo(X(t[cur]), h - P.b); ctx.stroke();
    }
  }

  let last = -1;
  function loop() {
    if (!document.getElementById("console").hidden) {
      const cur = Math.max(0, Math.min(n - 1, Math.round(video.currentTime * fps)));
      if (cur !== last) { last = cur; draw(cur); }
    }
    requestAnimationFrame(loop);
  }
  const redraw = () => { size(); last = -1; };
  window.addEventListener("resize", redraw);
  document.getElementById("database").addEventListener("click", () => requestAnimationFrame(redraw));
  requestAnimationFrame(() => { redraw(); loop(); });
})();
