import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

// Use a dedicated local test control service with no receiver daemon running.
// Never print service credentials or cookies.
const base = new URL(process.env.FIGHTLENS_TEST_URL || "http://127.0.0.1:4273")
  .origin;
const key = process.env.FIGHTLENS_WORKER_SECRET;
assert.ok(key, "Load the dedicated local test environment first.");
const instance = randomUUID();
const cookies = new Map();
async function owner(path, payload) {
  const response = await fetch(`${base}${path}`, {
    method: payload ? "POST" : "GET",
    headers: {
      Cookie: [...cookies].map(([k, v]) => `${k}=${v}`).join("; "),
      ...(payload ? { Origin: base, "Content-Type": "application/json" } : {}),
    },
    body: payload
      ? JSON.stringify({ requestId: randomUUID(), ...payload })
      : undefined,
  });
  for (const cookie of response.headers.getSetCookie()) {
    const [name, value] = cookie.split(";")[0].split("=");
    cookies.set(name, value);
  }
  return { status: response.status, data: await response.json() };
}
async function worker(path = "", packet) {
  const response = await fetch(`${base}/api/internal/sessions${path}`, {
    method: packet ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${key}`,
      "X-Worker-Instance": instance,
      "Content-Type": "application/json",
    },
    body: packet ? JSON.stringify(packet) : undefined,
  });
  return { status: response.status, data: await response.json() };
}
await owner("/api/sessions");
const created = await owner("/api/sessions", {});
assert.equal(created.status, 201);
const id = created.data.id,
  path = `/api/sessions/${id}`;
try {
  assert.equal((await worker()).status, 200);
  assert.equal(
    (await owner(`${path}/join`, { mode: "publisher" })).status,
    200,
  );
  let state = (await worker()).data.sessions.find((s) => s.id === id);
  const packet = () => ({
    schema_version: "fightlens.caption.v1",
    session_id: id,
    source_generation: state.sourceGeneration,
    worker_generation: state.workerGeneration,
    segment_id: state.segmentId,
    analysis_revision: state.analysisRevision,
    seq: 1,
    status: "ready",
    skipped_windows: 0,
    error_code: null,
    caption: {
      id: `${state.segmentId}:fixture`,
      t0_s: 0,
      t1_s: 2.75,
      text: "(fake) API fixture; no footage was reviewed.",
      model: "fake/cosmos3-reason",
      latency_ms: 100,
      ready_at: new Date().toISOString(),
      frames: 12,
    },
  });
  assert.equal((await worker(`/${id}/captions`, packet())).status, 409);
  assert.equal(
    (await owner(`${path}/caption-settings`, { A: "same", B: "same" })).status,
    400,
  );
  assert.equal(
    (
      await owner(`${path}/caption-settings`, {
        A: "red trunks",
        B: "blue trunks",
      })
    ).status,
    200,
  );
  state = (await worker()).data.sessions.find((s) => s.id === id);
  const first = packet();
  const unauthorized = await fetch(
    `${base}/api/internal/sessions/${id}/captions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(first),
    },
  );
  assert.equal(unauthorized.status, 403);
  assert.equal((await worker(`/${id}/captions`, first)).data.accepted, true);
  assert.equal(
    (await owner(path)).data.caption.caption.text,
    first.caption.text,
  );
  assert.equal((await worker(`/${id}/captions`, first)).data.accepted, false);
  assert.equal(
    (
      await worker(`/${id}/captions`, {
        ...first,
        seq: 2,
        caption: { ...first.caption, t1_s: 1.5 },
      })
    ).data.accepted,
    false,
  );
  assert.equal(
    (
      await worker(`/${id}/captions`, {
        ...first,
        seq: 2,
        caption: { ...first.caption, t0_s: 4, t1_s: 3 },
      })
    ).status,
    400,
  );
  assert.equal(
    (
      await worker(`/${id}/captions`, {
        ...first,
        segment_id: randomUUID(),
        seq: 2,
      })
    ).status,
    409,
  );
  await owner(`${path}/analysis`, { paused: true });
  assert.equal((await owner(path)).data.caption, null);
  assert.equal(
    (await worker(`/${id}/captions`, { ...first, seq: 2 })).status,
    409,
  );
  state = (await worker()).data.sessions.find((s) => s.id === id);
  assert.equal((await worker(`/${id}/captions`, packet())).status, 409);
  assert.equal(
    (
      await worker(`/${id}/captions`, {
        ...packet(),
        status: "paused",
        caption: null,
      })
    ).data.accepted,
    true,
  );
  await owner(`${path}/analysis`, { paused: false });
  state = (await worker()).data.sessions.find((s) => s.id === id);
  assert.equal((await worker(`/${id}/captions`, packet())).data.accepted, true);
  await owner(`${path}/segment`, {});
  assert.equal((await owner(path)).data.caption, null);
  assert.equal((await worker(`/${id}/captions`, packet())).status, 409);
  await owner(`${path}/stop`, {});
  assert.equal((await worker(`/${id}/captions`, packet())).status, 410);
  console.log(
    "Caption API checks passed: authentication, identities, ordering, schema validation, pause/resume, source changes, terminal stop.",
  );
} finally {
  await owner(`${path}/stop`, {});
}
