"use client";

import { useEffect, useRef, useState } from "react";
import {
  LocalVideoTrack,
  Room,
  RoomEvent,
  Track,
  type TrackPublishOptions,
} from "livekit-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { liveRequest } from "@/lib/live/api";
import type { JoinInfo, LiveSnapshot } from "@/lib/live/types";

const cameraPublication: TrackPublishOptions = {
  source: Track.Source.Camera,
  simulcast: false,
  degradationPreference: "maintain-resolution",
  videoEncoding: { maxBitrate: 2_500_000, maxFramerate: 30 },
};

const cameraError = (error: unknown) => {
  const name = (error as Error).name;
  if (name === "NotAllowedError")
    return "Camera permission was denied. Allow camera access in your browser, then retry.";
  if (name === "NotFoundError")
    return "No camera was found. Connect a camera and retry.";
  if (name === "NotReadableError")
    return "The camera is unavailable or in use by another application.";
  if (name === "OverconstrainedError")
    return "This camera does not support the requested settings. Choose another device.";
  return (error as Error).message || "Camera capture failed. Please retry.";
};
export function CameraPublisher({
  id,
  snapshot,
  refresh,
  showPreview = true,
  onStarted,
  onSetup,
}: {
  id: string;
  snapshot: LiveSnapshot;
  refresh: () => void;
  showPreview?: boolean;
  onStarted: () => void;
  onSetup: () => void;
}) {
  const preview = useRef<HTMLVideoElement>(null);
  const track = useRef<LocalVideoTrack | null>(null);
  const room = useRef<Room | null>(null);
  const operation = useRef(0);
  const mounted = useRef(true);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState("Camera off");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [device, setDevice] = useState("");
  const [facing, setFacing] = useState("environment");
  const [settings, setSettings] = useState("");

  function release() {
    operation.current += 1;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    track.current?.stop();
    track.current = null;
    void room.current?.disconnect();
    room.current = null;
    if (preview.current) preview.current.srcObject = null;
  }
  useEffect(() => {
    mounted.current = true;
    function abandon() {
      const capturing = !!track.current || !!room.current;
      release();
      if (capturing) {
        navigator.sendBeacon(
          `/api/sessions/${id}/stop`,
          new Blob([JSON.stringify({ requestId: crypto.randomUUID() })], {
            type: "application/json",
          }),
        );
      }
    }
    window.addEventListener("pagehide", abandon);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", abandon);
      const capturing = !!track.current || !!room.current;
      release();
      if (capturing)
        void liveRequest(`/api/sessions/${id}/stop`, {}).catch(() => {});
    };
  }, [id]);
  useEffect(() => {
    if (snapshot.state === "ended") {
      release();
      setEnabled(false);
      setPublishing(false);
      setStatus("Session ended");
    }
  }, [snapshot.state]);
  useEffect(() => {
    function rotated() {
      if (!room.current || !track.current || snapshot.state === "ended") return;
      void liveRequest(`/api/sessions/${id}/segment`, {})
        .then(() => {
          setStatus("Publishing · check framing after rotation");
          refresh();
        })
        .catch((error: Error) => setError(error.message));
    }
    window.addEventListener("orientationchange", rotated);
    return () => window.removeEventListener("orientationchange", rotated);
  }, [id, snapshot.state, refresh]);

  useEffect(() => {
    const element = preview.current;
    const media = track.current?.mediaStreamTrack;
    if (showPreview && enabled && element && media?.readyState === "live") {
      element.srcObject = new MediaStream([media]);
      void element.play().catch(() => setError("Tap the preview to play."));
    }
  }, [showPreview, enabled]);

  async function acquire(selected = device, selectedFacing = facing) {
    if (!navigator.mediaDevices?.getUserMedia)
      throw new Error(
        "Camera capture needs HTTPS on a phone, or localhost on this computer.",
      );
    const generation = ++operation.current;
    const oldRoom = room.current;
    if (track.current && oldRoom)
      await oldRoom.localParticipant.unpublishTrack(track.current);
    track.current?.stop();
    track.current = null;
    setEnabled(false);
    setPublishing(false);
    if (preview.current) preview.current.srcObject = null;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 },
        ...(selected
          ? { deviceId: { exact: selected } }
          : { facingMode: { ideal: selectedFacing } }),
      },
    });
    if (!mounted.current || generation !== operation.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    const media = stream.getVideoTracks()[0];
    media.addEventListener("ended", () => {
      if (mounted.current && track.current?.mediaStreamTrack === media) {
        setEnabled(false);
        setPublishing(false);
        setStatus("Camera interrupted · enable camera to retry");
      }
    });
    const ownedTrack = new LocalVideoTrack(media, undefined, true);
    track.current = ownedTrack;
    if (preview.current) {
      preview.current.srcObject = stream;
      await preview.current.play();
    }
    const actual = media.getSettings();
    setSettings(
      `${actual.width || "?"} × ${actual.height || "?"} · ${Math.round(actual.frameRate || 0)} FPS capture`,
    );
    setDevices(
      (await navigator.mediaDevices.enumerateDevices()).filter(
        (device) => device.kind === "videoinput",
      ),
    );
    if (!mounted.current || generation !== operation.current) return;
    setEnabled(true);
    setStatus("Local preview");
    if (oldRoom) {
      await liveRequest(`/api/sessions/${id}/segment`, {});
      if (!mounted.current || generation !== operation.current) return;
      await oldRoom.localParticipant.publishTrack(
        ownedTrack,
        cameraPublication,
      );
      if (!mounted.current || generation !== operation.current) return;
      setStatus("Publishing · camera changed");
      setPublishing(true);
      refresh();
    }
  }
  async function enable(selected = device, selectedFacing = facing) {
    setBusy(true);
    setError("");
    try {
      await acquire(selected, selectedFacing);
    } catch (error) {
      setError(cameraError(error));
      setStatus("Camera unavailable");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function start() {
    if (!track.current) return;
    setBusy(true);
    setError("");
    setStatus("Connecting…");
    const generation = ++operation.current;
    const connection = new Room({
      adaptiveStream: false,
      dynacast: false,
      // The embedded browser rejects the single-PC offer-with-join config update.
      singlePeerConnection: false,
    });
    room.current = connection;
    connection.on(RoomEvent.Reconnecting, () => {
      setStatus("Reconnecting…");
      reconnectTimer.current = setTimeout(() => {
        void connection.disconnect();
        setPublishing(false);
        setError("Connection interrupted. Select Start live to retry.");
      }, 15000);
    });
    connection.on(RoomEvent.Reconnected, () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      setStatus("Publishing");
    });
    connection.on(RoomEvent.Disconnected, () => {
      if (mounted.current && room.current === connection) {
        setPublishing(false);
        setStatus("Disconnected");
        room.current = null;
      }
    });
    try {
      const info = await liveRequest<JoinInfo>(`/api/sessions/${id}/join`, {
        mode: "publisher",
      });
      if (!mounted.current || generation !== operation.current) return;
      await connection.connect(info.url, info.token);
      if (
        !mounted.current ||
        generation !== operation.current ||
        !track.current
      ) {
        await connection.disconnect();
        return;
      }
      await connection.localParticipant.publishTrack(
        track.current,
        cameraPublication,
      );
      if (!mounted.current || generation !== operation.current) {
        await connection.disconnect();
        return;
      }
      setPublishing(true);
      setStatus("Publishing");
      refresh();
      onStarted();
    } catch (error) {
      await connection.disconnect();
      setError((error as Error).message);
      setStatus("Connection failed");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function stop() {
    release();
    setEnabled(false);
    setPublishing(false);
    setStatus("Stopping…");
    setBusy(true);
    try {
      await liveRequest(`/api/sessions/${id}/stop`, {});
      refresh();
      setStatus("Session ended");
    } catch (error) {
      setError((error as Error).message);
      setStatus("Camera released · retry ending session");
    } finally {
      setBusy(false);
    }
  }
  const ended = snapshot.state === "ended";
  if (!showPreview)
    return (
      <div
        className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"
        aria-label="Camera publishing controls"
      >
        <span className="text-xs text-muted-foreground" role="status">
          {status}
        </span>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            className="h-11"
            onClick={onSetup}
            disabled={busy || ended}
          >
            {enabled ? "Camera settings" : "Set up camera"}
          </Button>
          <Button
            variant="outline"
            className="h-11"
            onClick={() => void stop()}
            disabled={busy || ended || !enabled}
          >
            Stop live
          </Button>
        </div>
        {error && (
          <p role="alert" className="w-full text-sm text-destructive">
            {error}
          </p>
        )}
      </div>
    );
  return (
    <Card className="min-w-0" aria-label="Camera publisher">
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
        <CardTitle className="text-base">Camera preview</CardTitle>
        <span className="text-xs text-muted-foreground" role="status">
          {status}
        </span>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4">
        <video
          ref={preview}
          autoPlay
          muted
          playsInline
          className="aspect-video w-full rounded-md bg-muted object-contain"
          aria-label="Local camera preview"
          onClick={() => void preview.current?.play()}
        />
        <div className="flex flex-wrap gap-2">
          {publishing && (
            <Button className="h-11" onClick={onStarted}>
              Return to live session
            </Button>
          )}
          <Button
            className="h-11"
            variant="outline"
            disabled={busy || ended || publishing}
            onClick={() => void enable()}
          >
            {enabled ? "Retry camera" : "Enable camera"}
          </Button>
          <Button
            className="h-11"
            disabled={!enabled || busy || ended || publishing}
            onClick={() => void start()}
          >
            Start live
          </Button>
          <Button
            className="h-11"
            variant="outline"
            disabled={busy || ended}
            onClick={() => void stop()}
          >
            Stop live
          </Button>
        </div>
        {enabled && (
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="space-y-1 text-xs text-muted-foreground">
              Camera
              <select
                aria-label="Camera device"
                className="h-11 w-full rounded-md border bg-background px-2 text-sm text-foreground"
                disabled={busy}
                value={device}
                onChange={(event) => {
                  const next = event.target.value;
                  setDevice(next);
                  void enable(next);
                }}
              >
                <option value="">Automatic</option>
                {devices.map((device) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || "Camera"}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              Facing
              <select
                aria-label="Camera facing"
                className="h-11 w-full rounded-md border bg-background px-2 text-sm text-foreground"
                disabled={busy}
                value={facing}
                onChange={(event) => {
                  const next = event.target.value;
                  setFacing(next);
                  setDevice("");
                  void enable("", next);
                }}
              >
                <option value="environment">Rear / environment</option>
                <option value="user">Front / user</option>
              </select>
            </label>
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          {settings || "Keep both fighters fully in frame."}
        </p>
        <p className="text-xs text-muted-foreground">
          Preview is local. Start live sends video to the media and analysis
          services. When optional model analysis is enabled, short sampled
          windows are sent to the configured Cosmos or OpenRouter service. This
          app keeps them only in memory and saves no recording.
        </p>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
