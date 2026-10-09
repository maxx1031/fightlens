"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { LiveHome } from "@/components/LiveHome";
import { Button } from "@/components/ui/button";
const Demo = dynamic(() =>
  import("@/components/FightLensApp").then((module) => module.FightLensApp),
);

export function FightLensHome() {
  const [demo, setDemo] = useState(false);
  if (demo)
    return (
      <>
        <div className="border-b p-3">
          <Button variant="ghost" onClick={() => setDemo(false)}>
            Back to live camera
          </Button>
        </div>
        <Demo />
      </>
    );
  return (
    <div className="min-h-svh">
      <header className="border-b">
        <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6">
          <h1 className="text-sm font-semibold">FightLens</h1>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-5 px-4 py-8 sm:px-6">
        <p className="text-sm text-muted-foreground">
          Stream a camera from this device, or pair a phone with your desktop.
        </p>
        <LiveHome />
        <Button variant="ghost" className="h-11" onClick={() => setDemo(true)}>
          Explore Demo curve / local video
        </Button>
      </main>
    </div>
  );
}
