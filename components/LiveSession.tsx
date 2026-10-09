"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { QRCodeSVG } from "qrcode.react";
import {
  LogLevel,
  Room,
  RoomEvent,
  TrackEvent,
  Track,
  VideoQuality,
  setLogLevel,
} from "livekit-client";
import { LiveImpactMirrors } from "@/components/LiveImpactMirrors";
import { CameraPublisher } from "@/components/CameraPublisher";
import { EngagementChart } from "@/components/EngagementChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { liveRequest, LiveRequestError } from "@/lib/live/api";
import {
  diagnosticSchema,
  poseSchema,
  type JoinInfo,
  type LiveSnapshot,
} from "@/lib/live/types";
import { formatTime } from "@/lib/types";

// The UI owns connection diagnostics. SDK logs may include signaling parameters.
setLogLevel(LogLevel.silent);

export function LiveSession({
  id,
  publish = false,
}: {
  id: string;
  publish?: boolean;
}) {
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const current = useRef<LiveSnapshot | null>(null);
  const [error, setError] = useState("");
  const [pairing, setPairing] = useState<{
    url: string;
    expiresAt: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [retry, setRetry] = useState(0);
  const [viewer, setViewer] = useState("Waiting for video");
  const [viewerCodec, setViewerCodec] = useState("");
  const [frameSize, setFrameSize] = useState("");
  const [dataCount, setDataCount] = useState(0);
  const [viewMode, setViewMode] = useState<"yolo" | "original">("yolo");
  const [viewerReady, setViewerReady] = useState(0);
  const [renderedFrame, setRenderedFrame] = useState<number | null>(null);
  const viewerRoom = useRef<Room | null>(null);
  const chosenTrack = useRef<string | null>(null);
  const received = useRef<HTMLVideoElement>(null);
  const lastDecoded = useRef(0);
  const refreshed = useRef<() => void>(() => {});
  const redeeming = useRef<Promise<unknown> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await liveRequest<LiveSnapshot>(`/api/sessions/${id}`);
      const previous = current.current;
      if (previous && next.revision < previous.revision) return;
      if (
        previous?.latest &&
        next.state === "active" &&
        next.segmentId === previous.segmentId &&
        next.workerGeneration === previous.workerGeneration &&
        next.latest &&
        next.latest.seq < previous.latest.seq
      ) {
        next.latest = previous.latest;
        next.updatedAt = previous.updatedAt;
      }
      if (
        previous?.pose &&
        next.pose &&
        next.analysisRevision === previous.analysisRevision &&
        next.segmentId === previous.segmentId &&
        next.workerGeneration === previous.workerGeneration &&
        next.pose.seq < previous.pose.seq
      ) {
        next.pose = previous.pose;
        next.history = previous.history;
      }
      current.current = next;
      setSnapshot(next);
      setError("");
    } catch (error) {
      // A lost/expired control registry invalidates the session, including cached media tokens.
      if (
        error instanceof LiveRequestError &&
        [403, 404, 410].includes(error.status)
      ) {
        const previous = current.current;
        if (previous) {
          const terminal = {
            ...previous,
            state: "ended" as const,
            latest: null,
            workerAvailable: false,
            cleanupPending: false,
          };
          current.current = terminal;
          setSnapshot(terminal);
        }
      }
      setError((error as Error).message);
    }
  }, [id]);
  refreshed.current = () => void refresh();

  useEffect(() => {
    let cancelled = false;
    async function enter() {
      try {
        const invitation = new URLSearchParams(location.hash.slice(1)).get(
          "invite",
        );
        if (publish && invitation) {
          // Clear pairing secret before any other navigation or UI logging.
          history.replaceState(null, "", location.pathname + location.search);
          redeeming.current ??= liveRequest(`/api/sessions/${id}/redeem`, {
            invitation,
          });
        }
        if (redeeming.current) await redeeming.current;
        if (!cancelled) await refresh();
      } catch (error) {
        if (!cancelled) setError((error as Error).message);
      }
    }
    void enter();
    return () => {
      cancelled = true;
    };
  }, [id, publish, refresh]);
  useEffect(() => {
    if (!snapshot || (snapshot.state === "ended" && !snapshot.cleanupPending))
      return;
    const timer = setInterval(() => {
      setNow(Date.now());
      void refresh();
    }, 1000);
    return () => clearInterval(timer);
  }, [
    !!snapshot,
    snapshot?.state === "ended",
    snapshot?.cleanupPending,
    refresh,
  ]);

  useEffect(() => {
    const room = viewerRoom.current;
    if (!room || !snapshot || snapshot.state === "ended") return;
    chosenTrack.current = null;
    for (const participant of room.remoteParticipants.values()) {
      for (const publication of participant.trackPublications.values()) {
        const selected =
          viewMode === "yolo"
            ? participant.identity === snapshot.workerIdentity &&
              publication.trackSid === snapshot.outputTrackId
            : participant.identity === snapshot.publisherIdentity &&
              publication.source === Track.Source.Camera;
        if (selected) chosenTrack.current = publication.trackSid;
        if (publication.isSubscribed !== selected)
          publication.setSubscribed(selected);
      }
    }
  }, [
    snapshot?.workerIdentity,
    snapshot?.publisherIdentity,
    snapshot?.outputTrackId,
    snapshot?.state,
    viewMode,
    viewerReady,
  ]);

  useEffect(() => {
    if (!snapshot || snapshot.state === "ended") return;
    let cancelled = false;
    let room: Room | null = null;
    let frameCallback = 0;
    let track: import("livekit-client").RemoteVideoTrack | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let metadataWorker: Worker | null = null;
    const element = received.current;
    const started = Date.now();
    const timer = setInterval(() => {
      if (cancelled) return;
      if (lastDecoded.current && Date.now() - lastDecoded.current > 2000)
        setViewer("Video stalled");
      else if (!lastDecoded.current && Date.now() - started > 10000)
        setViewer("Waiting for first frame · check publisher");
    }, 500);
    function decoded() {
      if (cancelled || !element) return;
      if (element.videoWidth) {
        lastDecoded.current = Date.now();
        setViewer("Receiving video");
        setFrameSize(`${element.videoWidth} × ${element.videoHeight}`);
      }
      frameCallback = element.requestVideoFrameCallback(decoded);
    }
    async function connect() {
      try {
        const info = await liveRequest<JoinInfo>(`/api/sessions/${id}/join`, {
          mode: "viewer",
        });
        if (cancelled) return;
        if ("RTCRtpScriptTransform" in window)
          metadataWorker = new Worker(
            new URL("livekit-client/frame-metadata-worker", import.meta.url),
          );
        room = new Room({
          adaptiveStream: false,
          dynacast: false,
          ...(metadataWorker
            ? { frameMetadata: { worker: metadataWorker } }
            : {}),
        });
        viewerRoom.current = room;
        room.on(RoomEvent.TrackPublished, () =>
          setViewerReady((count) => count + 1),
        );
        room.on(
          RoomEvent.TrackSubscribed,
          async (candidate, publication, participant) => {
            await refresh();
            if (cancelled) return;
            if (
              candidate.kind !== Track.Kind.Video ||
              publication.trackSid !== chosenTrack.current ||
              publication.source !== Track.Source.Camera ||
              !element
            )
              return;
            publication.setVideoQuality(VideoQuality.HIGH);
            if (frameCallback && element.cancelVideoFrameCallback)
              element.cancelVideoFrameCallback(frameCallback);
            track = candidate as import("livekit-client").RemoteVideoTrack;
            const subscribedTrack = track;
            setRenderedFrame(null);
            track.on(TrackEvent.TimeSyncUpdate, ({ rtpTimestamp }) => {
              const metadata = subscribedTrack.lookupFrameMetadata({
                rtpTimestamp,
              });
              if (
                !cancelled &&
                subscribedTrack === track &&
                publication.trackSid === chosenTrack.current &&
                metadata?.frameId != null
              )
                setRenderedFrame(metadata.frameId);
            });
            track.attach(element);
            lastDecoded.current = 0;
            if (element.requestVideoFrameCallback)
              frameCallback = element.requestVideoFrameCallback(decoded);
            try {
              await element.play();
            } catch {
              setViewer("Tap the video to play");
            }
            const stats = await track.getRTCStatsReport();
            if (!cancelled)
              stats?.forEach((report) => {
                if (
                  report.type === "codec" &&
                  report.mimeType?.startsWith("video/")
                )
                  setViewerCodec(report.mimeType);
              });
          },
        );
        room.on(RoomEvent.TrackUnsubscribed, (candidate) => {
          if (candidate === track) {
            if (frameCallback && element?.cancelVideoFrameCallback)
              element.cancelVideoFrameCallback(frameCallback);
            track?.detach();
            lastDecoded.current = 0;
            setFrameSize("");
            setViewerCodec("");
            setRenderedFrame(null);
            setViewer("Waiting for video");
          }
        });
        room.on(
          RoomEvent.DataReceived,
          (payload, participant, _kind, topic) => {
            if (
              participant?.identity !== current.current?.workerIdentity ||
              payload.length > 8192
            )
              return;
            try {
              if (topic === "fightlens.pose") {
                const parsed = poseSchema.safeParse(
                  JSON.parse(new TextDecoder().decode(payload)),
                );
                if (!parsed.success) return;
                const pose = parsed.data,
                  state = current.current;
                if (
                  !state ||
                  state.state !== "active" ||
                  state.paused ||
                  pose.session_id !== id ||
                  pose.worker_generation !== state.workerGeneration ||
                  pose.source_generation !== state.sourceGeneration ||
                  pose.segment_id !== state.segmentId ||
                  pose.analysis_revision !== state.analysisRevision ||
                  pose.output_track_id !== state.outputTrackId
                ) {
                  refreshed.current();
                  return;
                }
                if (state.pose && pose.seq <= state.pose.seq) return;
                const history = [
                  ...state.history,
                  {
                    frame_id: pose.output_frame_id,
                    t_ms: pose.received_position_ms,
                    engaged: pose.signals.engaged,
                    distance: pose.signals.distance,
                  },
                ]
                  .filter((p) => p.t_ms >= pose.received_position_ms - 60_000)
                  .slice(-600);
                const next = { ...state, pose, history };
                current.current = next;
                setSnapshot(next);
                setDataCount((count) => count + 1);
                return;
              }
              if (topic !== "fightlens.receiver") return;
              const parsed = diagnosticSchema.safeParse(
                JSON.parse(new TextDecoder().decode(payload)),
              );
              if (!parsed.success) return;
              const update = parsed.data;
              const state = current.current;
              if (
                !state ||
                state.state !== "active" ||
                update.session_id !== id ||
                update.worker_generation !== state.workerGeneration ||
                update.source_generation !== state.sourceGeneration ||
                update.segment_id !== state.segmentId ||
                update.analysis_revision !== state.analysisRevision
              ) {
                refreshed.current();
                return;
              }
              if (state.latest && update.seq <= state.latest.seq) return;
              if (state.latest && update.seq > state.latest.seq + 1)
                refreshed.current();
              const next = { ...state, latest: update, updatedAt: Date.now() };
              current.current = next;
              setSnapshot(next);
              setDataCount((count) => count + 1);
            } catch {
              /* Invalid packets never alter the live signal. */
            }
          },
        );
        room.on(RoomEvent.Reconnecting, () => {
          setViewer("Reconnecting…");
          reconnectTimer = setTimeout(() => {
            void room?.disconnect();
            setViewer("Connection interrupted · retry connection");
          }, 15000);
        });
        room.on(RoomEvent.Reconnected, () => {
          if (reconnectTimer) clearTimeout(reconnectTimer);
          refreshed.current();
        });
        room.on(RoomEvent.Disconnected, () => {
          if (!cancelled) setViewer("Viewer disconnected · retry connection");
        });
        await room.connect(info.url, info.token, { autoSubscribe: false });
        if (!cancelled) setViewerReady((count) => count + 1);
        if (cancelled) await room.disconnect();
      } catch (error) {
        if (!cancelled) setError((error as Error).message);
      }
    }
    void connect();
    return () => {
      cancelled = true;
      clearInterval(timer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (element && frameCallback)
        element.cancelVideoFrameCallback(frameCallback);
      track?.detach();
      void room?.disconnect();
      if (viewerRoom.current === room) viewerRoom.current = null;
      metadataWorker?.terminate();
      lastDecoded.current = 0;
    };
  }, [id, !!snapshot, snapshot?.state === "ended", retry]);

  async function pair() {
    setBusy(true);
    setError("");
    try {
      setPairing(await liveRequest(`/api/sessions/${id}/pairing`, {}));
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function command(action: string, data = {}) {
    setBusy(true);
    try {
      await liveRequest(`/api/sessions/${id}/${action}`, data);
      await refresh();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const latest = snapshot?.latest;
  const ended = snapshot?.state === "ended";
  const fresh =
    !!latest &&
    now - (snapshot?.updatedAt || 0) < 2000 &&
    latest.metrics.last_frame_age_ms < 2000 &&
    !ended;
  const backend = ended
    ? "Session ended"
    : fresh
      ? "Backend receiving frames"
      : latest
        ? "Backend frames stale"
        : snapshot?.state === "active"
          ? "Waiting for backend frames"
          : "Waiting for publisher";
  const analysis = snapshot?.paused
    ? latest?.analysis.mode === "paused"
      ? "Analysis paused"
      : "Pause requested…"
    : latest?.analysis.mode === "paused"
      ? "Resume requested…"
      : latest?.analysis.mode === "yolo_pose"
        ? "YOLO Pose running"
        : latest?.analysis.mode === "failed"
          ? "YOLO unavailable · video continues without annotation"
          : "YOLO initializing · video continues without annotation";
  return (
    <div className="arcade-app min-h-svh pb-6">
      <header className="arcade-header border-b">
        <div className="mx-auto flex min-h-14 max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-2 sm:px-6">
          <div className="flex items-center gap-2">
            <Link href="/" className="arcade-brand">
              FightLens
            </Link>
            <Badge variant="outline">{ended ? "Ended" : "Live camera"}</Badge>
          </div>
          <Link href="/" className="text-xs text-muted-foreground underline">
            New session / Demo
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-4 px-4 py-5 sm:px-6 sm:py-8">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {!snapshot && (
          <p className="text-sm text-muted-foreground">
            {error
              ? "Open the pairing link on your publishing device, or create a new session."
              : "Loading session…"}
          </p>
        )}
        {snapshot && (
          <>
            {snapshot.role === "owner" &&
              !snapshot.publisherIdentity &&
              !publish && (
                <Card>
                  <CardContent className="space-y-3 p-4">
                    <p className="text-sm">
                      Connect a phone to this session, or use this computer’s
                      camera.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        className="h-11"
                        disabled={busy || ended}
                        onClick={() => void pair()}
                      >
                        Generate phone QR
                      </Button>
                      <Button className="h-11" variant="outline" asChild>
                        <Link href={`/sessions/${id}/publish`}>
                          Use this camera
                        </Link>
                      </Button>
                    </div>
                    {pairing && !snapshot.publisherIdentity && (
                      <div className="flex flex-col items-start gap-3 sm:flex-row">
                        <div className="rounded-md bg-white p-3">
                          <QRCodeSVG
                            value={pairing.url}
                            size={160}
                            title="Phone publisher pairing link"
                          />
                        </div>
                        <div className="min-w-0 space-y-2 text-sm">
                          <p>
                            {now > pairing.expiresAt
                              ? "Pairing expired. Generate a new QR."
                              : "Scan to open the camera publisher. Link expires in 5 minutes."}
                          </p>
                          <Button
                            variant="outline"
                            className="h-11"
                            onClick={() =>
                              void navigator.clipboard.writeText(pairing.url)
                            }
                          >
                            Copy pairing link
                          </Button>
                          <p className="text-xs text-muted-foreground">
                            Phone capture needs a trusted HTTPS page and a
                            reachable media server.
                          </p>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
              <div className="min-w-0 space-y-4">
                {publish && (
                  <CameraPublisher
                    id={id}
                    snapshot={snapshot}
                    refresh={refresh}
                  />
                )}
                <Card className="min-w-0" aria-label="Received video">
                  <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0 p-4">
                    <CardTitle className="text-base">
                      {viewMode === "yolo" ? "YOLO video" : "Original video"}
                    </CardTitle>
                    <span
                      className="text-xs text-muted-foreground"
                      role="status"
                    >
                      {ended ? "Session ended" : viewer}
                    </span>
                  </CardHeader>
                  <CardContent className="space-y-3 px-4 pb-4">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        className="h-11"
                        variant={viewMode === "yolo" ? "default" : "outline"}
                        aria-pressed={viewMode === "yolo"}
                        onClick={() => setViewMode("yolo")}
                        disabled={ended}
                      >
                        YOLO video
                      </Button>
                      <Button
                        className="h-11"
                        variant={
                          viewMode === "original" ? "default" : "outline"
                        }
                        aria-pressed={viewMode === "original"}
                        onClick={() => setViewMode("original")}
                        disabled={ended}
                      >
                        Original video
                      </Button>
                    </div>
                    <video
                      ref={received}
                      autoPlay
                      muted
                      playsInline
                      className="aspect-video w-full rounded-md bg-muted object-contain"
                      aria-label="Remote session video"
                      onClick={() => void received.current?.play()}
                    />
                    <p className="text-xs text-muted-foreground">
                      {frameSize || "Waiting for the published track"}
                      {viewerCodec ? ` · ${viewerCodec}` : ""}. Viewing playback
                      has no historical seek.
                    </p>
                    <Button
                      className="h-11"
                      variant="outline"
                      disabled={ended}
                      onClick={() => {
                        setRetry((count) => count + 1);
                        void refresh();
                      }}
                    >
                      Retry connection
                    </Button>
                  </CardContent>
                </Card>
                <LiveImpactMirrors
                  pose={snapshot.pose}
                  history={snapshot.history}
                  renderedFrame={renderedFrame}
                  aligned={viewMode === "yolo" && renderedFrame !== null}
                  available={
                    fresh &&
                    !snapshot.paused &&
                    latest?.analysis.mode === "yolo_pose" &&
                    snapshot.pose?.identity_status === "stable" &&
                    latest.timing.received_position_ms - snapshot.pose.received_position_ms < 2000
                  }
                />
              </div>
              <Card
                className="min-w-0"
                aria-label="Live momentum and receiver status"
              >
                <CardHeader className="p-4">
                  <CardTitle className="text-base">Live engagement</CardTitle>
                </CardHeader>
                <CardContent className="space-y-5 px-4 pb-4">
                  <EngagementChart
                    history={snapshot.history}
                    renderedFrame={renderedFrame}
                    paused={snapshot.paused}
                    aligned={viewMode === "yolo" && renderedFrame !== null}
                  />
                  <div className="space-y-2 text-sm" aria-live="polite">
                    <p>{backend}</p>
                    <p className="text-xs text-muted-foreground">{analysis}</p>
                    {snapshot.pose && !snapshot.paused && (
                      <p className="text-xs text-muted-foreground">
                        {snapshot.pose.signals.state} · Identity{" "}
                        {snapshot.pose.identity_status}
                      </p>
                    )}
                    {latest?.analysis.error && (
                      <p className="text-xs text-destructive" role="alert">
                        {latest.analysis.error}
                      </p>
                    )}
                    {snapshot.cleanupPending && (
                      <p className="text-xs text-destructive">
                        Media cleanup pending. The session is ended.
                      </p>
                    )}
                  </div>
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-4 text-sm">
                    <Metric
                      label="YOLO inference"
                      value={
                        fresh && !snapshot.paused
                          ? `${latest?.analysis.inference_ms.toFixed(1)} ms`
                          : "—"
                      }
                    />
                    <Metric
                      label="Worker pipeline"
                      value={
                        fresh && !snapshot.paused
                          ? `${latest?.analysis.worker_latency_ms.toFixed(1)} ms`
                          : "—"
                      }
                    />
                    <Metric
                      label="Output FPS"
                      value={
                        fresh
                          ? `${latest?.analysis.output_fps.toFixed(1)}`
                          : "—"
                      }
                    />
                    <Metric
                      label="Frames analyzed"
                      value={
                        latest ? String(latest.analysis.processed_frames) : "—"
                      }
                    />
                    <Metric
                      label="Backend FPS"
                      value={
                        fresh
                          ? `${latest?.metrics.received_fps.toFixed(1)}`
                          : "—"
                      }
                    />
                    <Metric
                      label="Backend resolution"
                      value={
                        latest
                          ? `${latest.metrics.width} × ${latest.metrics.height}`
                          : "—"
                      }
                    />
                    <Metric
                      label="Frames received"
                      value={latest ? String(latest.metrics.frame_count) : "—"}
                    />
                    <Metric
                      label="Receiver progress"
                      value={
                        latest
                          ? formatTime(
                              latest.timing.received_position_ms / 1000,
                            )
                          : "—"
                      }
                    />
                    <Metric
                      label="Queue / dropped"
                      value={
                        latest
                          ? `${latest.metrics.queue_depth} / ${latest.metrics.dropped_frames}`
                          : "—"
                      }
                    />
                    <Metric
                      label="Worker peak RSS"
                      value={
                        latest
                          ? `${latest.metrics.memory_mb.toFixed(1)} MB`
                          : "—"
                      }
                    />
                  </dl>
                  <p className="text-xs text-muted-foreground">
                    Worker pipeline measures receiver arrival through
                    annotated-frame submission. Capture-to-display latency is
                    unmeasured.{" "}
                    {dataCount > 0
                      ? "Live result messages received."
                      : "Status restored from the session snapshot."}
                  </p>
                  {latest?.analysis.model_version && (
                    <p className="text-xs text-muted-foreground break-words">
                      {latest.analysis.model_version}
                    </p>
                  )}
                  {snapshot.role === "owner" && !ended && (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        className="h-11"
                        disabled={busy || snapshot.state !== "active"}
                        onClick={() =>
                          void command("analysis", { paused: !snapshot.paused })
                        }
                      >
                        {snapshot.paused ? "Resume analysis" : "Pause analysis"}
                      </Button>
                      <Button
                        variant="outline"
                        className="h-11"
                        disabled={busy}
                        onClick={() => void command("stop")}
                      >
                        End session
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words pt-1 tabular-nums">{value}</dd>
    </div>
  );
}
