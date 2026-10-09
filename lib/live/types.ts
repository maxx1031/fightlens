import { z } from "zod";

export const diagnosticSchema = z.object({
  schema_version: z.literal("fightlens.live.v1"),
  session_id: z.string().uuid(),
  source_generation: z.number().int().positive(),
  segment_id: z.string().uuid(),
  track_id: z.string().min(1).max(200),
  worker_generation: z.number().int().positive(),
  seq: z.number().int().positive(),
  kind: z.literal("receiver_status"),
  provenance: z.literal("live_camera"),
  timing: z.object({
    basis: z.literal("receiver_monotonic"),
    received_position_ms: z.number().finite().nonnegative(),
    processed_position_ms: z.number().finite().nonnegative(),
    capture_wall_time_us: z.null(),
    clock_mapping_id: z.null(),
  }),
  frame_ref: z.object({
    publisher_frame_id: z.null(),
    receiver_frame_seq: z.number().int().nonnegative(),
  }),
  analysis: z.object({
    mode: z.enum(["diagnostic_only", "paused"]),
    momentum: z.null(),
    model_version: z.null(),
  }),
  metrics: z.object({
    received_fps: z.number().finite().nonnegative(),
    width: z.number().int().nonnegative(),
    height: z.number().int().nonnegative(),
    queue_depth: z.number().int().min(0).max(2),
    dropped_frames: z.number().int().nonnegative(),
    frame_count: z.number().int().nonnegative(),
    processing_ms: z.number().finite().nonnegative(),
    last_frame_age_ms: z.number().finite().nonnegative(),
    memory_mb: z.number().finite().nonnegative(),
    codec: z.string().nullable(),
  }),
});
export type Diagnostic = z.infer<typeof diagnosticSchema>;
export interface LiveSnapshot {
  id: string;
  revision: number;
  state: "created" | "active" | "ended";
  role: "owner" | "publisher";
  sourceGeneration: number;
  segmentId: string | null;
  publisherIdentity: string | null;
  workerIdentity: string | null;
  workerGeneration: number;
  workerAvailable: boolean;
  paused: boolean;
  cleanupPending: boolean;
  latest: Diagnostic | null;
  updatedAt: number | null;
  createdAt: number;
  endedAt: number | null;
}
export interface JoinInfo {
  url: string;
  token: string;
  publisherIdentity: string;
  snapshot: LiveSnapshot;
}
