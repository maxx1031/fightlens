"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  captionSettingsSchema,
  type CaptionFighters,
  type LiveSnapshot,
} from "@/lib/live/types";

const messages = {
  not_configured: "Captions will start when Cosmos is connected.",
  awaiting_identity: "Confirm how to identify A and B to start configured analysis.",
  buffering: "Collecting the next short video window…",
  reviewing: "Cosmos is reviewing a recent exchange…",
  ready: "Recent exchange reviewed",
  error: "Caption unavailable for the latest window. Trying the next window.",
  paused: "Caption analysis paused",
};
const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;

export function CosmosCaption({
  snapshot,
  fresh,
  onConfirm,
}: {
  snapshot: LiveSnapshot;
  fresh: boolean;
  onConfirm: (fighters: CaptionFighters) => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const update = snapshot.caption;
  const ended = snapshot.state === "ended";
  const result = !ended && !snapshot.paused ? update?.caption : null;
  const fake = result?.model.startsWith("fake/");
  const status = ended
    ? "Session ended"
    : snapshot.paused
      ? messages.paused
      : !snapshot.workerAvailable
        ? "Waiting for the analysis service"
        : snapshot.state !== "active"
          ? "Start live to receive captions."
          : !fresh
            ? "Waiting for fresh video. Earlier captions describe earlier footage."
            : update
              ? messages[update.status]
              : "Waiting for caption status…";

  async function confirm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    const parsed = captionSettingsSchema.safeParse({
      A: form.get("A"),
      B: form.get("B"),
    });
    if (!parsed.success) {
      setError(
        "Use distinct appearance descriptions for A and B (2–160 characters each).",
      );
      return;
    }
    setSaving(true);
    try {
      await onConfirm(parsed.data);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="space-y-3 rounded-md border p-3"
      aria-label="Cosmos captions"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Cosmos commentary</span>
        {result && (
          <span>
            {fake ? "Fake endpoint · demo" : "Video review"} ·{" "}
            {clock(result.t0_s)}–{clock(result.t1_s)} · receiver time
          </span>
        )}
      </div>
      <div aria-live="polite" aria-atomic="true">
        {result && (
          <p className="break-words text-sm" data-testid="cosmos-caption-text">
            {result.text}
          </p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">{status}</p>
      </div>
      {result && (
        <p className="text-xs text-muted-foreground">
          This describes an earlier video window, rather than the current frame.
          Review took {(result.latency_ms / 1000).toFixed(1)}s.
        </p>
      )}
      {!!update?.skipped_windows && (
        <p className="text-xs text-muted-foreground">
          {update.skipped_windows} video{" "}
          {update.skipped_windows === 1 ? "window was" : "windows were"} not
          reviewed.
        </p>
      )}
      {snapshot.role === "owner" && !ended && (
        <details open={!snapshot.captionFighters}>
          <summary className="cursor-pointer text-xs underline">
            {snapshot.captionFighters
              ? "Edit fighter descriptions"
              : "Identify the fighters"}
          </summary>
          <form
            className="mt-3 space-y-3"
            onSubmit={confirm}
            key={JSON.stringify(snapshot.captionFighters)}
          >
            <p className="text-xs text-muted-foreground">
              These descriptions are shared by Cosmos and exchange judgments. Match the A/B labels in the received video using visible appearance,
              such as trunks or gloves. Reconfirm if camera changes swap the labels.
            </p>
            {(["A", "B"] as const).map((fighter) => (
              <label className="block space-y-1 text-xs" key={fighter}>
                <span>Fighter {fighter} appearance</span>
                <input
                  name={fighter}
                  defaultValue={snapshot.captionFighters?.[fighter] || ""}
                  required
                  minLength={2}
                  maxLength={160}
                  placeholder={
                    fighter === "A"
                      ? "Red trunks, black gloves"
                      : "Blue trunks, white gloves"
                  }
                  className="h-11 w-full rounded-md border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  disabled={saving}
                />
              </label>
            ))}
            <Button className="h-11" size="sm" disabled={saving}>
              {saving ? "Saving…" : "Confirm A/B"}
            </Button>
            {error && (
              <p role="alert" className="text-xs text-destructive">
                {error}
              </p>
            )}
          </form>
        </details>
      )}
    </section>
  );
}
