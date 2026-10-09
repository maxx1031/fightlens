import { NextRequest } from "next/server";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { diagnosticSchema, poseSchema } from "@/lib/live/types";
import {
  active,
  findSession,
  initialize,
  issueToken,
  LiveError,
  registry,
  snapshot,
} from "@/lib/server/live-registry";
import { body, failure, internalAuth, response } from "@/lib/server/live-http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ path?: string[] }> };
export async function GET(request: NextRequest, context: Context) {
  try {
    internalAuth(request);
    await initialize();
    const path = (await context.params).path || [];
    if (path.length) throw new LiveError("not_found", "Unknown endpoint.", 404);
    const instance = z
      .string()
      .uuid()
      .parse(request.headers.get("x-worker-instance"));
    // Single diagnostic daemon. Reject another live daemon rather than racing receivers.
    if (
      registry.workerInstance !== instance &&
      Date.now() - registry.workerSeen < 5000
    )
      throw new LiveError(
        "worker_conflict",
        "Another receiver daemon is active.",
        409,
      );
    registry.workerInstance = instance;
    registry.workerSeen = Date.now();
    const sessions = [];
    for (const session of registry.sessions.values()) {
      if (session.state !== "active") continue;
      if (
        session.workerInstance !== instance ||
        Date.now() - session.workerSeen >= 5000
      ) {
        session.workerInstance = instance;
        session.workerGeneration += 1;
        session.workerIdentity = `worker-${session.workerGeneration}-${randomUUID()}`;
        session.segmentId = randomUUID();
        session.latest = null;
        session.updatedAt = null;
        session.outputTrackId = null;
        session.pose = null;
        session.history = [];
        session.revision += 1;
      }
      session.workerSeen = Date.now();
      sessions.push({
        room: session.room,
        url: process.env.LIVEKIT_URL,
        token: await issueToken(session, "worker"),
        id: session.id,
        state: session.state,
        sourceGeneration: session.sourceGeneration,
        segmentId: session.segmentId,
        publisherIdentity: session.publisherIdentity,
        workerIdentity: session.workerIdentity,
        workerGeneration: session.workerGeneration,
        paused: session.paused,
        analysisRevision: session.analysisRevision,
      });
    }
    return response({ sessions, leaseMs: 5000 });
  } catch (error) {
    return failure(error);
  }
}
export async function POST(request: NextRequest, context: Context) {
  try {
    internalAuth(request);
    const path = (await context.params).path || [];
    if (
      path.length !== 2 ||
      !["updates", "segment", "pose", "output"].includes(path[1])
    )
      throw new LiveError("not_found", "Unknown endpoint.", 404);
    const session = findSession(path[0]);
    active(session);
    if (
      request.headers.get("x-worker-instance") !== session.workerInstance ||
      Date.now() - session.workerSeen >= 5000
    )
      throw new LiveError("lease_expired", "Receiver lease expired.", 409);
    if (path[1] === "segment") {
      const data = z
        .object({
          workerGeneration: z.number().int(),
          trackId: z.string().min(1).max(200),
        })
        .parse(await body(request));
      if (data.workerGeneration !== session.workerGeneration)
        throw new LiveError(
          "stale_generation",
          "Receiver generation changed.",
          409,
        );
      session.segmentId = randomUUID();
      session.latest = null;
      session.updatedAt = null;
      session.pose = null;
      session.history = [];
      session.revision += 1;
      return response(snapshot(session));
    }
    if (path[1] === "output") {
      const data = z
        .object({
          workerGeneration: z.number().int(),
          segmentId: z.string().uuid(),
          trackId: z.string().min(1).max(200),
        })
        .parse(await body(request));
      if (
        data.workerGeneration !== session.workerGeneration ||
        data.segmentId !== session.segmentId
      )
        throw new LiveError(
          "stale_generation",
          "Receiver generation changed.",
          409,
        );
      session.outputTrackId = data.trackId;
      session.revision += 1;
      return response({ accepted: true });
    }
    if (path[1] === "pose") {
      const pose = poseSchema.parse(await body(request));
      if (
        pose.session_id !== session.id ||
        pose.source_generation !== session.sourceGeneration ||
        pose.worker_generation !== session.workerGeneration ||
        pose.segment_id !== session.segmentId ||
        pose.analysis_revision !== session.analysisRevision ||
        session.paused ||
        pose.output_track_id !== session.outputTrackId
      )
        throw new LiveError(
          "stale_generation",
          "Analysis generation changed.",
          409,
        );
      if (session.pose && pose.seq <= session.pose.seq)
        return response({ accepted: false });
      session.pose = pose;
      session.history.push({
        frame_id: pose.output_frame_id,
        t_ms: pose.received_position_ms,
        engaged: pose.signals.engaged,
        distance: pose.signals.distance,
      });
      session.history = session.history
        .filter((point) => point.t_ms >= pose.received_position_ms - 60_000)
        .slice(-600);
      session.revision += 1;
      return response({ accepted: true });
    }
    const update = diagnosticSchema.parse(await body(request));
    if (
      update.session_id !== session.id ||
      update.source_generation !== session.sourceGeneration ||
      update.worker_generation !== session.workerGeneration ||
      update.analysis_revision !== session.analysisRevision ||
      update.segment_id !== session.segmentId
    )
      throw new LiveError(
        "stale_generation",
        "Source or receiver generation has changed.",
        409,
      );
    if (session.latest && update.seq <= session.latest.seq)
      return response({ accepted: false });
    if (update.analysis.mode === "failed" && session.pose) {
      const last = session.history.at(-1);
      session.history.push({
        frame_id: update.frame_ref.output_frame_id || last?.frame_id || 0,
        t_ms:
          Math.max(last?.t_ms || 0, update.timing.received_position_ms) + 0.001,
        engaged: null,
        distance: null,
      });
      session.history = session.history.slice(-600);
      session.pose = null;
    }
    session.latest = update;
    session.updatedAt = Date.now();
    session.revision += 1;
    return response({ accepted: true });
  } catch (error) {
    return failure(error);
  }
}
