# Live camera MVP

YOLO Pose, annotated WebRTC return video, pause passthrough, and causal engagement are now connected. See [LIVE_YOLO.md](LIVE_YOLO.md) for current local acceptance and measured latency. The diagnostic milestone described below remains the transport baseline.

Implemented from [the live capture specification](LIVE_CAPTURE_SPEC.md): camera preview, one publisher per session, QR pairing, independent received video, LiveKit media, a Python YOLO receiver, bounded frame queues, pause/resume, terminal stop, and authorized snapshots. No full-session recording is included. Physical phone and relay acceptance remains outstanding.

## Local review

Prerequisites: Node.js 22+ with `process.loadEnvFile`, pnpm, uv, and Python 3.12. On macOS, setup can extract the official Homebrew LiveKit bottle into this checkout. Elsewhere, install a compatible `livekit-server` from [the official releases](https://github.com/livekit/livekit/releases) first; setup copies it locally. The tested server is 1.13.9.

```sh
pnpm install --frozen-lockfile
pnpm live:setup
pnpm live:dev
```

Open `http://localhost:4173` or `http://127.0.0.1:4173`. Setup generates fresh server credentials in ignored `.env.local`, a checkout-specific room prefix, and an ignored localhost-only LiveKit configuration. It preserves an existing `.env.local`. No hosted account, cloud resource, or global media-server installation is created. `uv sync` installs the locked Python dependencies into `worker/.venv`.

The launcher runs three processes and closes them together on Ctrl+C:

| Process | Local address / role |
| --- | --- |
| Next.js | Port 4173; pages, credentials, session commands, snapshots |
| LiveKit | Signaling 7880, RTC TCP 7881, UDP 50000–50100; local media |
| Python | RTC subscriber and control-service polling; no public listener |

Choose **Use this camera**, then **Enable camera** for a local framing preview. **Start live** sends the same track through LiveKit. **Received video** requires rendered remote frames; **Backend receiving frames** requires decoded Python frames. These acknowledgments are independent. **Pause analysis** keeps reception active and pauses the diagnostic processing adapter. **Stop live** or **End session** ends the session and releases capture. A new broadcast requires a new session.

The live **YOLO video** shows returned annotations and the engagement curve is a rule signal from actual pose results. **Pause analysis** passes new unannotated frames through that same track. The separate **Explore Demo curve / local video** mode retains the simulated curve and seekable local-file player; it does not analyze the selected video.

For a production build of the same single-process control service:

```sh
pnpm typecheck
pnpm build
pnpm live:start
```

For API regression checks against the running stack:

```sh
pnpm live:check
```

The check creates and ends a test session. It verifies credentials, conflicting pairing claims, scoped token grants, origin validation, request bounds, command retries, and terminal-state enforcement. It does not benchmark media or models.

## Phone and network setup

The generated media configuration binds to localhost. A phone cannot reach that configuration by scanning its local QR code. A computer's plain HTTP LAN address can display the UI but is not a supported phone camera entry point.

For physical-phone review, use a trusted HTTPS origin for Next.js and a reachable LiveKit service with WSS signaling, direct RTC media, and TURN fallback. Set these server-only values in the deployment environment:

| Variable | Meaning |
| --- | --- |
| `FIGHTLENS_PUBLIC_URL` | Canonical HTTPS application origin; used for QR links, origin validation, secure cookies |
| `LIVEKIT_PUBLIC_URL` | WSS URL browsers can reach |
| `LIVEKIT_URL` | LiveKit URL reachable by Next.js and the worker |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Server API/token credentials; never `NEXT_PUBLIC_*` |
| `FIGHTLENS_CONTROL_URL` | Control-service URL reachable by the worker |
| `FIGHTLENS_WORKER_SECRET` | Shared service credential for internal APIs |
| `FIGHTLENS_ROOM_PREFIX` | Unique lowercase/hyphen prefix for this installation, 8–80 characters |

Run Next.js and `uv run --project worker --frozen python worker/receiver.py` against that media service. The local launcher always starts its localhost server; it is not a remote-service deployment launcher. Follow [LiveKit's network guide](https://docs.livekit.io/transport/self-hosting/ports-firewall/) for ports, external addresses, TLS, and TURN. Verify an actual relayed ICE candidate pair; a successful HTTPS/WSS connection alone does not establish media connectivity.

On the desktop, choose **Connect phone**, generate the QR, and scan it on the phone. The invitation expires in five minutes and is single-use. It is removed from the phone's URL during redemption. The publisher credential grants camera publication and session stop; owner-only analysis controls remain on the desktop. Invitations, join tokens, and service credentials must stay out of logs.

## Runtime and timing limits

- Session state is volatile and belongs to one long-lived Next.js process. Restarting it invalidates sessions and reconciles rooms with this installation's prefix. Do not deploy this registry on stateless/multiple server instances. Keep the prefix stable and exclusive to the installation.
- The diagnostic SDK queue holds one waiting frame and the application queue holds one, plus any frame currently being inspected. There is no historical pixel buffer. Reported drops are application-queue drops; SDK/network drops are not included. Worker peak RSS describes the entire daemon, not a per-session allocation.
- Receiver progress uses a monotonic receiver clock. Capture timestamps and physical-camera capture-to-display latency remain unavailable. Returned YOLO frames carry output frame IDs for browser curve alignment; unsupported browsers explicitly display unaligned receiver-relative results.
- Browser codec negotiation remains enabled. The received viewer codec is reported when RTC statistics expose it. The Python diagnostic codec field remains `null` because this receiver API does not expose an authoritative codec value.
- Publication uses one video layer, a 2.5 Mbps / 30 FPS encoding ceiling, and a preference to preserve capture resolution. A constrained browser/network may reduce cadence; always use the actual received FPS and resolution when judging analysis suitability.
- Status becomes stale after two seconds without fresh frames. Worker permissions renew every two seconds and expire after five seconds without control authorization. Republished tracks, worker restarts, camera rotation, and detected timestamp/frame gaps start a new segment.
- Room deletion stops current participants and the application rejects ended-session joins/results. Self-hosted LiveKit may still admit a cached valid token into a recreated old room. This demo does not claim immediate token revocation; verify hosting-specific revocation before offering public viewing.
- Foreground browser use is the target. Background capture, lock-screen behavior, physical iOS/Android interoperability, cellular streaming, and forced TURN relay need device/network tests from the spec.

Pinned SDKs are in `package.json` and `worker/uv.lock`. Current local evidence and remaining acceptance work are recorded in [LIVE_VERIFICATION.md](LIVE_VERIFICATION.md).
