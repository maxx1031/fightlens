import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import {
  LiveError,
  authorize,
  config,
  equal,
  type Session,
} from "./live-registry";

export function appOrigin(request: NextRequest) {
  // Next may normalize nextUrl to the server bind address (0.0.0.0).
  // Use the actual request Host locally and an explicit public origin behind a proxy.
  return new URL(
    process.env.FIGHTLENS_PUBLIC_URL ||
      `${request.nextUrl.protocol}//${request.headers.get("host") || request.nextUrl.host}`,
  ).origin;
}
export function origin(request: NextRequest) {
  if (request.headers.get("origin") !== appOrigin(request))
    throw new LiveError(
      "origin_rejected",
      "Request origin is not allowed.",
      403,
    );
}
export const commandSchema = z.object({ requestId: z.string().uuid() });
export async function body(request: NextRequest) {
  if (Number(request.headers.get("content-length") || 0) > 8192)
    throw new LiveError("too_large", "Request is too large.", 413);
  const raw = await request.text();
  if (Buffer.byteLength(raw) > 8192)
    throw new LiveError("too_large", "Request is too large.", 413);
  try {
    return JSON.parse(raw);
  } catch {
    throw new LiveError("invalid_request", "Expected a JSON request.");
  }
}
export const cookieName = (id: string) => `fl_${id}`;
export const auth = (request: NextRequest, session: Session) =>
  authorize(session, request.cookies.get(cookieName(session.id))?.value);
export function setCredential(
  response: NextResponse,
  request: NextRequest,
  name: string,
  value: string,
) {
  response.cookies.set(name, value, {
    httpOnly: true,
    secure: appOrigin(request).startsWith("https:"),
    sameSite: "strict",
    path: "/",
    maxAge: 6 * 3600,
  });
}
export function response(value: unknown, status = 200) {
  return NextResponse.json(value, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}
export function failure(error: unknown) {
  if (error instanceof LiveError)
    return response(
      { error: { code: error.code, message: error.message } },
      error.status,
    );
  if (error instanceof z.ZodError)
    return response(
      {
        error: { code: "invalid_request", message: "Invalid request fields." },
      },
      400,
    );
  // Never log body/token/SDK errors that can contain credentials.
  return response(
    {
      error: {
        code: "service_unavailable",
        message:
          "The live service is unavailable. Check the local stack and retry.",
      },
    },
    503,
  );
}
export function internalAuth(request: NextRequest) {
  const credential = request.headers
    .get("authorization")
    ?.replace(/^Bearer /, "");
  if (!equal(credential, config().workerSecret))
    throw new LiveError("forbidden", "Service authentication required.", 403);
}
