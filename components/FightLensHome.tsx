"use client";

import Link from "next/link";
import { LiveHome } from "@/components/LiveHome";
import { Button } from "@/components/ui/button";

export function FightLensHome() {
  return (
    <div className="arcade-app min-h-svh">
      <header className="arcade-header border-b">
        <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6">
          <h1 className="arcade-brand">FightLens</h1>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-5 px-4 py-8 sm:px-6">
        <h2 className="text-xl font-semibold">
          Use live camera or local video
        </h2>
        <p className="text-sm text-muted-foreground">
          Stream a camera from this device, or pair a phone with your desktop.
        </p>
        <LiveHome />
        <Button asChild variant="outline" className="h-11">
          <Link href="/replay">Review 3D impact mirrors</Link>
        </Button>
        <Button asChild variant="outline" className="h-11">
          <Link href="/local">Use local video / demo</Link>
        </Button>
      </main>
    </div>
  );
}
