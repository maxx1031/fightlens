import {
  existsSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  copyFileSync,
  chmodSync,
} from "node:fs";
import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
process.chdir(resolve(dirname(fileURLToPath(import.meta.url)), ".."));
const fresh = () => randomBytes(32).toString("hex");
mkdirSync("output/livekit", { recursive: true });
if (!existsSync(".env.local")) {
  writeFileSync(
    ".env.local",
    `LIVEKIT_URL=ws://127.0.0.1:7880\nLIVEKIT_API_KEY=fl${randomBytes(8).toString("hex")}\nLIVEKIT_API_SECRET=${fresh()}\nFIGHTLENS_WORKER_SECRET=${fresh()}\nFIGHTLENS_ROOM_PREFIX=fightlens-${randomBytes(8).toString("hex")}-\nFIGHTLENS_CONTROL_URL=http://127.0.0.1:4173\n`,
    { mode: 0o600 },
  );
}
process.loadEnvFile(".env.local");
// A file containing only Cosmos settings must also work with local setup.
// Preserve explicitly supplied values (including blanks requiring completion).
const existingEnvironment = readFileSync(".env.local", "utf8");
const localDefaults = {
  LIVEKIT_URL: "ws://127.0.0.1:7880",
  LIVEKIT_API_KEY: `fl${randomBytes(8).toString("hex")}`,
  LIVEKIT_API_SECRET: fresh(),
  FIGHTLENS_WORKER_SECRET: fresh(),
  FIGHTLENS_ROOM_PREFIX: `fightlens-${randomBytes(8).toString("hex")}-`,
  FIGHTLENS_CONTROL_URL: "http://127.0.0.1:4173",
};
const missingDefaults = Object.entries(localDefaults).filter(
  ([name]) =>
    !process.env[name] &&
    !new RegExp(`^\\s*(?:export\\s+)?${name}\\s*=`, "m").test(
      existingEnvironment,
    ),
);
if (missingDefaults.length) {
  writeFileSync(
    ".env.local",
    `${existingEnvironment.trimEnd()}\n${missingDefaults.map(([name, value]) => `${name}=${value}`).join("\n")}\n`,
    { mode: 0o600 },
  );
  process.loadEnvFile(".env.local");
}
chmodSync(".env.local", 0o600);
if (
  !process.env.LIVEKIT_API_KEY ||
  !process.env.LIVEKIT_API_SECRET ||
  !process.env.FIGHTLENS_WORKER_SECRET ||
  !process.env.FIGHTLENS_ROOM_PREFIX
)
  throw new Error(
    "Complete .env.local with server-only credentials. Existing configuration was preserved.",
  );
const config = `port: 7880\nbind_addresses: ["127.0.0.1"]\nrtc:\n  tcp_port: 7881\n  port_range_start: 50000\n  port_range_end: 50100\n  use_external_ip: false\nkeys:\n  ${process.env.LIVEKIT_API_KEY}: ${process.env.LIVEKIT_API_SECRET}\nlogging:\n  level: warn\n`;
writeFileSync("output/livekit/local.yaml", config, { mode: 0o600 });
const binary = resolve("output/livekit/livekit-server");
if (!existsSync(binary)) {
  let installed = "";
  try {
    installed = execFileSync("which", ["livekit-server"], {
      encoding: "utf8",
    }).trim();
  } catch {}
  if (installed) copyFileSync(installed, binary);
  else if (process.platform === "darwin") {
    // Extract the official Homebrew bottle without globally installing the server.
    execFileSync("brew", ["fetch", "--force-bottle", "livekit"], {
      stdio: "inherit",
      env: { ...process.env, HOMEBREW_NO_AUTO_UPDATE: "1" },
    });
    const archive = execFileSync("brew", ["--cache", "livekit"], {
      encoding: "utf8",
      env: { ...process.env, HOMEBREW_NO_AUTO_UPDATE: "1" },
    }).trim();
    const entry = execFileSync("tar", ["-tf", archive], { encoding: "utf8" })
      .split("\n")
      .find((path) => path.endsWith("/bin/livekit-server"));
    if (!entry)
      throw new Error("LiveKit server missing from the official bottle.");
    const data = execFileSync("tar", ["-xOf", archive, entry], {
      maxBuffer: 64 * 1024 * 1024,
    });
    writeFileSync(binary, data, { mode: 0o755 });
  } else
    throw new Error(
      "Install LiveKit server from its official release, then rerun setup. See docs/LIVE_SETUP.md.",
    );
  chmodSync(binary, 0o755);
}
execFileSync("uv", ["sync", "--project", "worker", "--python", "3.12"], {
  stdio: "inherit",
});
console.log(
  "Local LiveKit and Python receiver ready. Run pnpm live:dev. Credentials stay in ignored .env.local.",
);
