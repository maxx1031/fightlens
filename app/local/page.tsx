import Link from "next/link";
import { FightLensApp } from "@/components/FightLensApp";
import { Button } from "@/components/ui/button";

export default function LocalVideoPage() {
  return (
    <>
      <div className="border-b p-3">
        <Button asChild variant="ghost">
          <Link href="/">Back to source selection</Link>
        </Button>
      </div>
      <FightLensApp />
    </>
  );
}
