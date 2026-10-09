import { LiveSession } from "@/components/LiveSession";

export default async function SessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <LiveSession id={id} />;
}
