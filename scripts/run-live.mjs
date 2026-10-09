import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
process.chdir(resolve(dirname(fileURLToPath(import.meta.url)), ".."));
if (!existsSync(".env.local") || !existsSync("output/livekit/livekit-server"))
  throw new Error("Run pnpm live:setup first.");
await import("./prepare-replay.mjs");
process.loadEnvFile(".env.local");
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  children.forEach((child) => child.kill("SIGTERM"));
  const timer = setTimeout(() => {
    children.forEach((child) => child.kill("SIGKILL"));
    process.exit(code);
  }, 5000);
  timer.unref();
}
function start(command, args, label) {
  const child = spawn(command, args, { stdio: "inherit", env: process.env });
  children.push(child);
  child.on("error", () => {
    console.error(`${label} could not start.`);
    stop(1);
  });
  child.on("exit", (code) => {
    if (!stopping) {
      console.error(`${label} exited (${code}).`);
      stop(code || 1);
    }
  });
}
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
start(
  "output/livekit/livekit-server",
  ["--config", "output/livekit/local.yaml"],
  "LiveKit",
);
start(
  process.execPath,
  [
    "node_modules/next/dist/bin/next",
    process.argv.includes("--production") ? "start" : "dev",
    "--hostname",
    "0.0.0.0",
    "--port",
    "4173",
  ],
  "Next.js",
);
start(
  "uv",
  ["run", "--project", "worker", "--frozen", "python", "worker/receiver.py"],
  "Receiver",
);
