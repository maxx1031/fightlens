import { NextRequest } from "next/server";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import {
  active,
  cleanup,
  config,
  createSession,
  equal,
  findSession,
  initialize,
  issueToken,
  LiveError,
  registry,
  remember,
  secret,
  snapshot,
} from "@/lib/server/live-registry";
import {
  appOrigin,
  auth,
  body,
  commandSchema,
  cookieName,
  failure,
  origin,
  response,
  setCredential,
} from "@/lib/server/live-http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ path?: string[] }> };
export async function GET(request: NextRequest, context: Context) {
  try {
    const path = (await context.params).path || [];
    if (!path.length) {
      let configured = true;
      try {
        config();
      } catch {
        configured = false;
      }
      const result = response({
        configured,
        workerAvailable: Date.now() - registry.workerSeen < 5000,
      });
      if (!request.cookies.get("fl_device"))
        setCredential(result, request, "fl_device", secret());
      return result;
    }
    if (path.length !== 1)
      throw new LiveError("not_found", "Unknown endpoint.", 404);
    const session = findSession(path[0]);
    const role = auth(request, session);
    if (session.endedAt && Date.now() - session.endedAt > 30 * 60_000)
      throw new LiveError("session_missing", "Session expired.", 404);
    if (session.cleanupPending) await cleanup(session);
    return response(snapshot(session, role));
  } catch (error) {
    return failure(error);
  }
}
export async function POST(request: NextRequest, context: Context) {
  try {
    origin(request);
    const data = await body(request);
    const { requestId } = commandSchema.parse(data);
    const path = (await context.params).path || [];
    if (!path.length) {
      await initialize();
      const device = request.cookies.get("fl_device")?.value || secret();
      const session = createSession(device, requestId);
      const result = response(
        {
          id: session.id,
          viewUrl: `/sessions/${session.id}`,
          publishUrl: `/sessions/${session.id}/publish`,
        },
        201,
      );
      setCredential(result, request, "fl_device", device);
      setCredential(result, request, cookieName(session.id), session.owner);
      return result;
    }
    if (path.length !== 2)
      throw new LiveError("not_found", "Unknown endpoint.", 404);
    const session = findSession(path[0]);
    const action = path[1];
    if (action === "redeem") {
      active(session);
      const { invitation } = z
        .object({ invitation: z.string().length(64) })
        .parse(data);
      const existingRole = (() => {
        try {
          return auth(request, session);
        } catch {
          return null;
        }
      })();
      if (
        existingRole === "publisher" &&
        session.invitation?.used &&
        equal(invitation, session.invitation.secret)
      )
        return response(snapshot(session, "publisher"));
      if (!session.invitation || !equal(invitation, session.invitation.secret))
        throw new LiveError("invitation_invalid", "Invalid pairing link.", 403);
      if (session.invitation.expires < Date.now())
        throw new LiveError(
          "invitation_expired",
          "Pairing link expired. Ask the owner for a new link.",
          410,
        );
      if (session.invitation.used || session.publisherIdentity)
        throw new LiveError(
          "publisher_conflict",
          "A publisher is already paired with this session.",
          409,
        );
      session.invitation.used = true;
      session.publisher = secret();
      session.publisherIdentity = `publisher-${randomUUID()}`;
      session.revision += 1;
      const result = response(snapshot(session, "publisher"));
      setCredential(result, request, cookieName(session.id), session.publisher);
      return result;
    }
    const role = auth(request, session);
    if (action === "stop") {
      if (session.state !== "ended") session.revision += 1;
      session.state = "ended";
      session.endedAt ??= Date.now();
      session.cleanupPending = true;
      await cleanup(session);
      return response(snapshot(session, role));
    }
    active(session);
    if (action === "pairing") {
      if (role !== "owner")
        throw new LiveError(
          "forbidden",
          "Only the owner can pair a publisher.",
          403,
        );
      if (session.publisherIdentity)
        throw new LiveError(
          "publisher_conflict",
          "A publisher is already paired. End this session before replacing it.",
          409,
        );
      const invitation = remember(session, role, action, requestId, () => {
        session.invitation = {
          secret: secret(),
          expires: Date.now() + 5 * 60_000,
          used: false,
        };
        session.revision += 1;
        return session.invitation;
      });
      const base = appOrigin(request);
      return response({
        url: `${base}/sessions/${session.id}/publish#invite=${invitation.secret}`,
        expiresAt: invitation.expires,
      });
    }
    if (action === "join") {
      const { mode } = z
        .object({ mode: z.enum(["publisher", "viewer"]) })
        .parse(data);
      if (mode === "publisher") {
        if (
          [...registry.sessions.values()].some(
            (other) => other.id !== session.id && other.state === "active",
          )
        )
          throw new LiveError(
            "analysis_capacity",
            "The local YOLO demo supports one live session. End the current session first.",
            409,
          );
        if (Date.now() - registry.workerSeen >= 5000)
          throw new LiveError(
            "worker_unavailable",
            "The Python receiver is offline. Start pnpm live:dev, then retry.",
            503,
          );
        if (role === "owner" && session.publisher)
          throw new LiveError(
            "publisher_conflict",
            "This session is paired with another publishing device.",
            409,
          );
        remember(session, role, action, requestId, () => {
          session.publisherIdentity ??= `publisher-${randomUUID()}`;
          if (session.state !== "active") {
            session.state = "active";
            session.sourceGeneration = 1;
            session.segmentId = randomUUID();
            session.revision += 1;
          }
          return true;
        });
      }
      return response({
        url: config().browserUrl,
        token: await issueToken(session, mode),
        publisherIdentity: session.publisherIdentity,
        snapshot: snapshot(session, role),
      });
    }
    if (action === "analysis") {
      if (role !== "owner")
        throw new LiveError(
          "forbidden",
          "Only the owner can pause analysis.",
          403,
        );
      const { paused } = z.object({ paused: z.boolean() }).parse(data);
      remember(session, role, action, requestId, () => {
        if (session.paused !== paused) {
          const last = session.history.at(-1);
          session.analysisRevision += 1;
          session.pose = null;
          session.history.push({
            frame_id: Math.max(
              last?.frame_id || 0,
              session.latest?.frame_ref.output_frame_id || 0,
            ),
            t_ms:
              Math.max(
                last?.t_ms || 0,
                session.latest?.timing.received_position_ms || 0,
              ) + 0.001,
            engaged: null,
            distance: null,
          });
          session.history = session.history.slice(-600);
        }
        session.paused = paused;
        session.revision += 1;
        return true;
      });
      return response(snapshot(session, role));
    }
    if (action === "segment") {
      remember(session, role, action, requestId, () => {
        session.segmentId = randomUUID();
        session.latest = null;
        session.updatedAt = null;
        session.pose = null;
        session.history = [];
        session.revision += 1;
        return true;
      });
      return response(snapshot(session, role));
    }
    throw new LiveError("not_found", "Unknown endpoint.", 404);
  } catch (error) {
    return failure(error);
  }
}
