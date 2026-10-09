import type { AcceptedJudgment, JudgmentUpdate } from "@/lib/live/judgments";
import "server-only";
import { randomUUID, randomBytes, timingSafeEqual } from "node:crypto";
import {
  AccessToken,
  RoomServiceClient,
  TrackSource,
} from "livekit-server-sdk";
import type {
  CaptionFighters,
  CaptionUpdate,
  Diagnostic,
  LiveSnapshot,
  Pose,
  EngagementPoint,
} from "@/lib/live/types";

export class LiveError extends Error {
  constructor(
    public code: string,
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}
export const secret = () => randomBytes(32).toString("hex");
export const equal = (a: string | undefined, b: string | undefined) => {
  if (!a || !b) return false;
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
};
export interface Session {
  id: string;
  revision: number;
  room: string;
  owner: string;
  publisher: string | null;
  publisherIdentity: string | null;
  state: "created" | "active" | "ended";
  sourceGeneration: number;
  segmentId: string | null;
  workerGeneration: number;
  workerIdentity: string | null;
  workerInstance: string | null;
  workerSeen: number;
  paused: boolean;
  analysisRevision: number;
  captionRevision: number;
  captionFighters: CaptionFighters | null;
  caption: CaptionUpdate | null;
  judgment: JudgmentUpdate | null;
  judgmentHistory: AcceptedJudgment[];
  outputTrackId: string | null;
  pose: Pose | null;
  history: EngagementPoint[];
  cleanupPending: boolean;
  latest: Diagnostic | null;
  updatedAt: number | null;
  createdAt: number;
  endedAt: number | null;
  invitation: { secret: string; expires: number; used: boolean } | null;
  commands: Map<string, unknown>;
}
interface Registry {
  sessions: Map<string, Session>;
  creations: Map<string, string>;
  initialized: Promise<void> | null;
  workerSeen: number;
  workerInstance: string | null;
}
const globalRegistry = globalThis as typeof globalThis & {
  fightlensRegistry?: Registry;
};
export const registry: Registry = (globalRegistry.fightlensRegistry ??= {
  sessions: new Map(),
  creations: new Map(),
  initialized: null,
  workerSeen: 0,
  workerInstance: null,
});
export function config() {
  const key = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const url = process.env.LIVEKIT_URL;
  const workerSecret = process.env.FIGHTLENS_WORKER_SECRET;
  const prefix = process.env.FIGHTLENS_ROOM_PREFIX;
  if (
    !key ||
    !apiSecret ||
    !url ||
    !workerSecret ||
    !prefix ||
    !/^[a-z0-9-]{8,80}$/.test(prefix)
  ) {
    throw new LiveError(
      "not_configured",
      "Live services are not configured. Run pnpm live:setup and pnpm live:dev.",
      503,
    );
  }
  return {
    key,
    apiSecret,
    url,
    workerSecret,
    prefix,
    browserUrl: process.env.LIVEKIT_PUBLIC_URL || url,
  };
}
export function mediaClient() {
  const c = config();
  return new RoomServiceClient(
    c.url.replace(/^ws/, "http"),
    c.key,
    c.apiSecret,
  );
}
export async function initialize() {
  if (!registry.initialized)
    registry.initialized = (async () => {
      const c = config();
      const client = mediaClient();
      const rooms = await client.listRooms();
      // This prefix is generated for this checkout, never a shared global prefix.
      for (const room of rooms.filter((room) => room.name.startsWith(c.prefix)))
        await client.deleteRoom(room.name);
    })().catch(() => {
      registry.initialized = null;
      throw new LiveError(
        "media_unavailable",
        "Cannot reach the media service. Start the local live stack or check LiveKit configuration.",
        503,
      );
    });
  await registry.initialized;
  for (const [id, session] of registry.sessions) {
    if (session.endedAt && Date.now() - session.endedAt > 30 * 60_000)
      registry.sessions.delete(id);
  }
  for (const [key, id] of registry.creations)
    if (!registry.sessions.has(id)) registry.creations.delete(key);
}
export function findSession(id: string) {
  const session = registry.sessions.get(id);
  if (!session)
    throw new LiveError(
      "session_missing",
      "Session not found or expired. Create a new session.",
      404,
    );
  return session;
}
export function authorize(session: Session, credential: string | undefined) {
  if (equal(credential, session.owner)) return "owner" as const;
  if (equal(credential, session.publisher || undefined))
    return "publisher" as const;
  throw new LiveError(
    "forbidden",
    "This device does not have access to this session.",
    403,
  );
}
export function active(session: Session) {
  if (session.state === "ended")
    throw new LiveError(
      "session_ended",
      "This session has ended. Create a new session to broadcast again.",
      410,
    );
}
export function snapshot(
  session: Session,
  role: "owner" | "publisher" = "owner",
): LiveSnapshot {
  return {
    id: session.id,
    revision: session.revision,
    state: session.state,
    role,
    sourceGeneration: session.sourceGeneration,
    segmentId: session.segmentId,
    publisherIdentity: session.publisherIdentity,
    workerIdentity: session.workerIdentity,
    workerGeneration: session.workerGeneration,
    workerAvailable: Date.now() - registry.workerSeen < 5000,
    paused: session.paused,
    analysisRevision: session.analysisRevision,
    captionRevision: session.captionRevision,
    captionFighters: session.captionFighters,
    caption: session.caption,
    judgment: session.judgment ?? null,
    judgmentHistory: session.judgmentHistory ?? [],
    outputTrackId: session.outputTrackId,
    pose: session.pose,
    history: session.history,
    cleanupPending: session.cleanupPending,
    latest: session.latest,
    updatedAt: session.updatedAt,
    createdAt: session.createdAt,
    endedAt: session.endedAt,
  };
}
export function createSession(device: string, requestId: string) {
  const commandKey = `${device}:${requestId}`;
  const existing = registry.creations.get(commandKey);
  if (existing) return findSession(existing);
  if (registry.sessions.size >= 100)
    throw new LiveError(
      "capacity",
      "The demo has reached its session limit.",
      429,
    );
  const id = randomUUID();
  const session: Session = {
    id,
    revision: 1,
    room: `${config().prefix}${id}`,
    owner: secret(),
    publisher: null,
    publisherIdentity: null,
    state: "created",
    sourceGeneration: 0,
    segmentId: null,
    workerGeneration: 0,
    workerIdentity: null,
    workerInstance: null,
    workerSeen: 0,
    paused: false,
    analysisRevision: 0,
    captionRevision: 0,
    captionFighters: null,
    caption: null,
    judgment: null,
    judgmentHistory: [],
    outputTrackId: null,
    pose: null,
    history: [],
    cleanupPending: false,
    latest: null,
    updatedAt: null,
    createdAt: Date.now(),
    endedAt: null,
    invitation: null,
    commands: new Map(),
  };
  registry.sessions.set(id, session);
  registry.creations.set(commandKey, id);
  return session;
}
export function remember<T>(
  session: Session,
  role: string,
  action: string,
  requestId: string,
  operation: () => T,
): T {
  const key = `${role}:${action}:${requestId}`;
  if (session.commands.has(key)) return session.commands.get(key) as T;
  if (session.commands.size >= 500)
    throw new LiveError(
      "capacity",
      "This session reached its command limit. Start a new session.",
      429,
    );
  const value = operation();
  session.commands.set(key, value);
  return value;
}
export async function issueToken(
  session: Session,
  role: "publisher" | "viewer" | "worker",
) {
  const c = config();
  const identity =
    role === "publisher"
      ? session.publisherIdentity!
      : role === "worker"
        ? session.workerIdentity!
        : `viewer-${randomUUID()}`;
  const token = new AccessToken(c.key, c.apiSecret, { identity, ttl: 120 });
  token.addGrant({
    roomJoin: true,
    room: session.room,
    canPublish: role === "publisher" || role === "worker",
    canSubscribe: role !== "publisher",
    canPublishData: role === "worker",
    canUpdateOwnMetadata: false,
    ...(role === "publisher" || role === "worker"
      ? { canPublishSources: [TrackSource.CAMERA] }
      : {}),
  });
  return token.toJwt();
}
export async function cleanup(session: Session) {
  const wasPending = session.cleanupPending;
  try {
    await mediaClient().deleteRoom(session.room);
    session.cleanupPending = false;
  } catch (error) {
    if ((error as { code?: string }).code === "not_found")
      session.cleanupPending = false;
    else session.cleanupPending = true;
  }
  if (wasPending !== session.cleanupPending) session.revision += 1;
}
