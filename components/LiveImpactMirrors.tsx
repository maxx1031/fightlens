"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Pose, EngagementPoint } from "@/lib/live/types";

const ImpactAvatar = dynamic(
  () => import("./ImpactAvatar").then((module) => module.ImpactAvatar),
  { ssr: false, loading: () => <div className="h-60" aria-label="Loading mirror" /> },
);
const emptyCounts = { head: 0, body: 0, leg: 0 };

export function LiveImpactMirrors({ pose, history, renderedFrame, available, aligned }: {
  pose: Pose | null;
  history: EngagementPoint[];
  renderedFrame: number | null;
  available: boolean;
  aligned: boolean;
}) {
  const point = aligned && renderedFrame !== null
    ? history.findLast((entry) => entry.frame_id <= renderedFrame)
    : history.at(-1);
  const reliable = available && point !== undefined && point.engaged !== null;
  const engaged = reliable && point.engaged === 1;
  return (
    <Card className="min-w-0" aria-label="Live fighter mirrors">
      <CardHeader className="p-4">
        <CardTitle className="text-base">Fighter mirrors</CardTitle>
        <p className="text-xs text-muted-foreground">
          {reliable ? (engaged ? "Engagement detected" : "No engagement detected") : "Waiting for reliable live analysis"}
          {aligned ? " · Video aligned" : " · Latest received result"}
        </p>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4">
        <div className="grid grid-cols-2 gap-3">
          {(["A", "B"] as const).map((fighter) => (
            <div key={fighter} className="min-w-0 rounded-md border bg-muted/20">
              <p className="px-3 pt-3 text-sm font-medium">
                Fighter {fighter}
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  {available && pose?.fighters[fighter] ? "Tracked" : "Unavailable"}
                </span>
              </p>
              <ImpactAvatar fighter={fighter} counts={emptyCounts} feedback={null}
                engagement={engaged}
                label={`Fighter ${fighter} live mirror. ${engaged ? "Engagement detected." : "No engagement highlight."} Contact events are unavailable.`} />
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Blue glow shows the YOLO engagement rule. The bodies are neutral mirrors, not reconstructed poses. Contact detection is not connected.
          {" "}<Link href="/replay" className="underline underline-offset-4">Review hit and block effects with scripted replay</Link>.
        </p>
      </CardContent>
    </Card>
  );
}
