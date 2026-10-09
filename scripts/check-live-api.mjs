import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

// Against the running local stack. Never print tokens, cookies, or invitations.
const base = new URL(process.env.FIGHTLENS_TEST_URL || "http://127.0.0.1:4173")
  .origin;
function device() {
  const cookies = new Map();
  return async (path, payload, origin = base) => {
    const response = await fetch(`${base}${path}`, {
      headers: {
        Cookie: [...cookies]
          .map(([key, value]) => `${key}=${value}`)
          .join("; "),
        ...(payload
          ? { Origin: origin, "Content-Type": "application/json" }
          : {}),
      },
      method: payload ? "POST" : "GET",
      body: payload
        ? JSON.stringify({ requestId: randomUUID(), ...payload })
        : undefined,
    });
    for (const cookie of response.headers.getSetCookie()) {
      const [key, value] = cookie.split(";")[0].split("=");
      cookies.set(key, value);
    }
    return {
      status: response.status,
      data: await response.json(),
      headers: response.headers,
    };
  };
}
const owner = device(),
  phoneA = device(),
  phoneB = device(),
  stranger = device();
await owner("/api/sessions");
const requestId = randomUUID();
const created = await owner("/api/sessions", { requestId });
assert.equal(created.status, 201);
const id = created.data.id;
const path = `/api/sessions/${id}`;
try {
  assert.equal((await owner("/api/sessions", { requestId })).data.id, id);
  assert.equal((await stranger(path)).status, 403);
  assert.equal((await owner(path)).headers.get("cache-control"), "no-store");
  assert.equal(
    (await owner(`${path}/pairing`, {}, "https://unrelated.example")).status,
    403,
  );
  assert.equal((await stranger("/api/internal/sessions")).status, 403);
  assert.equal(
    (await owner(`${path}/analysis`, { padding: "x".repeat(9000) })).status,
    413,
  );
  assert.equal(
    (await owner(`${path}/analysis`, { paused: "yes" })).status,
    400,
  );
  const pairRequestId = randomUUID();
  const pairing = await owner(`${path}/pairing`, { requestId: pairRequestId });
  assert.equal(pairing.status, 200);
  assert.equal(
    (await owner(`${path}/pairing`, { requestId: pairRequestId })).data.url,
    pairing.data.url,
  );
  const link = new URL(pairing.data.url);
  assert.equal(link.origin, base);
  assert.equal(link.search, "");
  const invitation = new URLSearchParams(link.hash.slice(1)).get("invite");
  assert.ok(invitation);
  const claims = await Promise.all([
    phoneA(`${path}/redeem`, { invitation }),
    phoneB(`${path}/redeem`, { invitation }),
  ]);
  assert.deepEqual(claims.map((r) => r.status).sort(), [200, 409]);
  const publisher = claims[0].status === 200 ? phoneA : phoneB;
  assert.equal((await publisher(`${path}/redeem`, { invitation })).status, 200);
  assert.equal(
    (await owner(`${path}/join`, { mode: "publisher" })).status,
    409,
  );
  assert.equal(
    (await publisher(`${path}/analysis`, { paused: true })).status,
    403,
  );
  assert.equal((await publisher(`${path}/pairing`, {})).status, 403);
  const viewer = await owner(`${path}/join`, { mode: "viewer" });
  assert.equal(viewer.status, 200);
  const decode = (token) =>
    JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString());
  const viewerGrant = decode(viewer.data.token).video;
  assert.equal(viewerGrant.canPublish, false);
  assert.equal(viewerGrant.canPublishData, false);
  assert.equal(viewerGrant.canSubscribe, true);
  assert.ok(!viewerGrant.roomAdmin && !viewerGrant.roomRecord);
  const publisherJoin = await publisher(`${path}/join`, { mode: "publisher" });
  assert.equal(publisherJoin.status, 200);
  const publisherGrant = decode(publisherJoin.data.token).video;
  assert.equal(publisherGrant.canPublish, true);
  assert.equal(publisherGrant.canSubscribe, false);
  assert.equal(publisherGrant.canPublishData, false);
  assert.deepEqual(publisherGrant.canPublishSources, ["camera"]);
  assert.ok(!publisherGrant.roomAdmin && !publisherGrant.roomRecord);
  assert.equal(
    (await owner(`${path}/analysis`, { paused: true })).data.paused,
    true,
  );
  const ended = await publisher(`${path}/stop`, {});
  assert.equal(ended.data.state, "ended");
  assert.equal(
    (await owner(`${path}/stop`, {})).data.endedAt,
    ended.data.endedAt,
  );
  assert.equal(
    (await publisher(`${path}/join`, { mode: "publisher" })).status,
    410,
  );
  assert.equal((await owner(`${path}/join`, { mode: "viewer" })).status, 410);
  assert.equal((await stranger(`${path}/stop`, {})).status, 403);
  console.log(
    "Live API checks passed: credentials, single-use pairing race, role grants, origin/body validation, idempotency, terminal stop.",
  );
} finally {
  await owner(`${path}/stop`, {});
}
