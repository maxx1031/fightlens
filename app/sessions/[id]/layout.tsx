import type { ReactNode } from "react";
import { LiveSession } from "@/components/LiveSession";

// Keep capture mounted while navigating between setup and the live viewer.
export default async function SessionLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <LiveSession id={id} />
      {children}
    </>
  );
}
