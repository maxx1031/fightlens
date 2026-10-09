import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

// Dedicated Next.js service, with a unique LiveKit room prefix and no competing receiver.
const base = new URL(process.env.FIGHTLENS_TEST_URL || "http://127.0.0.1:4393")
  .origin;
const key = process.env.FIGHTLENS_WORKER_SECRET;
assert.ok(key, "Load the dedicated local test environment first.");
const instance = randomUUID(),
  cookies = new Map();
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
  await worker();
  assert.equal(
    (await owner(`${path}/join`, { mode: "publisher" })).status,
    200,
  );
  let state = (await worker()).data.sessions.find((s) => s.id === id);
  const packet = () => ({
    schema_version: "fightlens.judgment.v1",
    session_id: id,
    source_generation: state.sourceGeneration,
    worker_generation: state.workerGeneration,
    segment_id: state.segmentId,
    analysis_revision: state.analysisRevision,
    identity_revision: state.captionRevision,
    seq: 1,
    status: "ready",
    skipped_windows: 0,
    error_code: null,
    judgment: {
      id: randomUUID(),
      episode_id: randomUUID(),
      revision: 0,
      kind: "direction",
      t0_s: 10,
      t1_s: 12,
      available_position_ms: 14000,
      ready_at: new Date().toISOString(),
      model: "fake/clef",
      prompt_version: "exchange-direction.v1",
      frames: 8,
      latency_ms: 2000,
      direction: "favors_A",
      evidence: "contact_only",
      gap_reason: null,
      confidence: { direction: 0.8, evidence: 0.8 },
      probabilities: {
        direction: {
          favors_A: 1,
          favors_B: 0,
          no_clear_advantage: 0,
          insufficient_evidence: 0,
        },
        evidence: {
          contact_only: 1,
          observable_reaction: 0,
          sustained_change: 0,
          no_confirmed_effect: 0,
          insufficient_evidence: 0,
        },
      },
    },
  });
  assert.equal((await worker(`/${id}/judgments`, packet())).status, 409);
  await owner(`${path}/caption-settings`, {
    A: "red trunks",
    B: "blue trunks",
  });
  state = (await worker()).data.sessions.find((s) => s.id === id);
  const first = packet();
  assert.equal(
    (
      await fetch(`${base}/api/internal/sessions/${id}/judgments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(first),
      })
    ).status,
    403,
  );
  assert.equal((await worker(`/${id}/judgments`, first)).data.accepted, true);
  assert.equal((await owner(path)).data.judgmentHistory.length, 1);
  assert.equal((await worker(`/${id}/judgments`, first)).data.accepted, false);
  // A transport repeat with a fresh sequence still doesn't duplicate the exchange.
  assert.equal(
    (await worker(`/${id}/judgments`, { ...first, seq: 2 })).data.accepted,
    true,
  );
  assert.equal((await owner(path)).data.judgmentHistory.length, 1);
  const revision = {
    ...first,
    seq: 3,
    judgment: {
      ...first.judgment,
      revision: 1,
      available_position_ms: 17000,
      direction: "favors_B",
      probabilities: {
        ...first.judgment.probabilities,
        direction: {
          favors_A: 0,
          favors_B: 1,
          no_clear_advantage: 0,
          insufficient_evidence: 0,
        },
      },
    },
  };
  assert.equal(
    (await worker(`/${id}/judgments`, revision)).data.accepted,
    true,
  );
  assert.equal((await owner(path)).data.judgmentHistory.length, 1);
  assert.equal(
    (await owner(path)).data.judgmentHistory[0].direction,
    "favors_B",
  );
  await worker(`/${id}/judgments`, { ...first, seq: 4 });
  assert.equal(
    (await owner(path)).data.judgmentHistory[0].direction,
    "favors_B",
  );
  assert.equal(
    (
      await worker(`/${id}/judgments`, {
        ...revision,
        seq: 5,
        judgment: { ...revision.judgment, available_position_ms: 1000 },
      })
    ).status,
    400,
  );
  assert.equal(
    (
      await worker(`/${id}/judgments`, {
        ...revision,
        seq: 5,
        segment_id: randomUUID(),
      })
    ).status,
    409,
  );
  await owner(`${path}/analysis`, { paused: true });
  const paused = (await owner(path)).data;
  assert.equal(paused.judgment, null);
  assert.equal(paused.judgmentHistory.at(-1).kind, "gap");
  assert.equal(
    (await worker(`/${id}/judgments`, { ...revision, seq: 5 })).status,
    409,
  );
  state = (await worker()).data.sessions.find((s) => s.id === id);
  assert.equal((await worker(`/${id}/judgments`, packet())).status, 409);
  assert.equal(
    (
      await worker(`/${id}/judgments`, {
        ...packet(),
        status: "paused",
        judgment: null,
      })
    ).status,
    200,
  );
  await owner(`${path}/analysis`, { paused: false });
  state = (await worker()).data.sessions.find((s) => s.id === id);
  assert.equal((await worker(`/${id}/judgments`, packet())).status, 200);
  const previousIdentity = packet();
  await owner(`${path}/caption-settings`, {
    A: "black trunks",
    B: "white trunks",
  });
  assert.deepEqual((await owner(path)).data.judgmentHistory, []);
  assert.equal(
    (await worker(`/${id}/judgments`, previousIdentity)).status,
    409,
  );
  state = (await worker()).data.sessions.find((s) => s.id === id);
  const beforeSegment = packet();
  await worker(`/${id}/judgments`, beforeSegment);
  await owner(`${path}/segment`, {});
  assert.deepEqual((await owner(path)).data.judgmentHistory, []);
  assert.equal((await worker(`/${id}/judgments`, beforeSegment)).status, 409);
  await owner(`${path}/stop`, {});
  assert.equal((await worker(`/${id}/judgments`, beforeSegment)).status, 410);
  console.log(
    "Judgment API checks passed: authentication, identity, ordering, revisions, schema, pause/resume, segment reset, terminal stop.",
  );
} finally {
  await owner(`${path}/stop`, {});
}
