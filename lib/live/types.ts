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
export const captionSettingsSchema = z
  .object({
    A: z.string().trim().min(2).max(160),
    B: z.string().trim().min(2).max(160),
  })
  .refine((value) => value.A.toLowerCase() !== value.B.toLowerCase(), {
    message: "Fighters need distinct appearance descriptions.",
  });
export type CaptionFighters = z.infer<typeof captionSettingsSchema>;

export const captionUpdateSchema = z
  .object({
    schema_version: z.literal("fightlens.caption.v1"),
    session_id: z.string().uuid(),
    source_generation: z.number().int().positive(),
    worker_generation: z.number().int().positive(),
    segment_id: z.string().uuid(),
    analysis_revision: z.number().int().nonnegative(),
    seq: z.number().int().positive(),
    status: z.enum([
      "not_configured",
      "awaiting_identity",
      "buffering",
      "reviewing",
      "ready",
      "error",
      "paused",
    ]),
    skipped_windows: z.number().int().nonnegative(),
    error_code: z
      .enum(["endpoint_unavailable", "invalid_response", "frame_unavailable"])
      .nullable(),
    caption: z
      .object({
        id: z.string().min(1).max(200),
        t0_s: z.number().finite().nonnegative(),
        t1_s: z.number().finite().positive(),
        text: z.string().trim().min(1).max(800),
        model: z.string().min(1).max(200),
        latency_ms: z.number().finite().nonnegative(),
        ready_at: z.string().datetime(),
        frames: z.number().int().min(2).max(36),
      })
      .refine((caption) => caption.t1_s > caption.t0_s)
      .nullable(),
  })
  .superRefine((update, ctx) => {
    if (update.status === "ready" && !update.caption)
      ctx.addIssue({
        code: "custom",
        message: "Ready captions require a result.",
      });
    if ((update.status === "error") !== (update.error_code !== null))
      ctx.addIssue({
        code: "custom",
        message: "Error state requires an error code.",
      });
    if (
      ["paused", "not_configured", "awaiting_identity"].includes(
        update.status,
      ) &&
      update.caption
    )
      ctx.addIssue({
        code: "custom",
        message: "Inactive captions must be cleared.",
      });
  });
export type CaptionUpdate = z.infer<typeof captionUpdateSchema>;
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
  analysisRevision: number;
  captionFighters: CaptionFighters | null;
  caption: CaptionUpdate | null;
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
