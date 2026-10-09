"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { liveRequest } from "@/lib/live/api";

export function LiveHome() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create(phone: boolean) {
    setBusy(true);
    setError("");
    try {
      await liveRequest("/api/sessions"); // Establish device identity for command retries.
      const session = await liveRequest<{ id: string }>("/api/sessions", {});
      router.push(`/sessions/${session.id}${phone ? "?phone=1" : "/publish"}`);
    } catch (error) {
      setError((error as Error).message);
      setBusy(false);
    }
  }
  return (
    <Card aria-label="Start camera session">
      <CardHeader className="p-4">
        <CardTitle className="text-base">Live camera</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 p-4 pt-0">
        <p className="text-sm text-muted-foreground">
          Stream your camera for live YOLO pose analysis. Video reaches the
          media and analysis services; no recording is saved.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            className="h-11"
            disabled={busy}
            onClick={() => void create(false)}
          >
            {busy ? "Creating session…" : "Use this camera"}
          </Button>
          <Button
            className="h-11"
            variant="outline"
            disabled={busy}
            onClick={() => void create(true)}
          >
            Connect phone
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
