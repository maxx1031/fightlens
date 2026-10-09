export class LiveRequestError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "LiveRequestError";
  }
}

export async function liveRequest<T>(
  path: string,
  body?: Record<string, unknown>,
): Promise<T> {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body
      ? JSON.stringify({ requestId: crypto.randomUUID(), ...body })
      : undefined,
    cache: "no-store",
  });
  const result = await response.json();
  if (!response.ok)
    throw new LiveRequestError(
      response.status,
      result.error?.code || "request_failed",
      result.error?.message || "Request failed. Please retry.",
    );
  return result as T;
}
