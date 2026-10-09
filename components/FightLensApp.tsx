"use client"

import { useEffect, useRef, useState } from "react"
import { Pause, Play, RotateCcw } from "lucide-react"
import { MomentumChart } from "@/components/MomentumChart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle
} from "@/components/ui/card"
import { Slider } from "@/components/ui/slider"
import { formatTime } from "@/lib/types"
import { usePlayback } from "@/lib/usePlayback"
import { cn } from "@/lib/utils"

export function FightLensApp() {
  const [media, setMedia] = useState<{ url: string; name: string } | null>(null)
  const [video, setVideo] = useState<HTMLVideoElement | null>(null)
  const [fileError, setFileError] = useState("")
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const playback = usePlayback(video, media?.url || null)
  const source = media?.url

  useEffect(
    () => () => {
      if (source) URL.revokeObjectURL(source)
    },
    [source]
  )

  function chooseVideo(file: File | undefined) {
    if (!file) return
    if (
      !file.type.startsWith("video/") &&
      !/\.(mp4|webm|mov|m4v|ogv|ogg)$/i.test(file.name)
    ) {
      setFileError("Choose a video file, such as an MP4 or WebM.")
      return
    }
    setFileError("")
    setMedia({ url: URL.createObjectURL(file), name: file.name })
  }

  function useDemo() {
    setMedia(null)
    setFileError("")
    if (input.current) input.current.value = ""
  }

  return (
    <div className="arcade-app min-h-svh pb-[max(24px,env(safe-area-inset-bottom))]">
      <header className="arcade-header border-b">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 sm:px-6">
          <h1 className="arcade-brand">FightLens</h1>
          <Badge variant="outline">Demo</Badge>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-4 px-4 py-5 sm:space-y-6 sm:px-6 sm:py-8">
        <p className="text-sm text-muted-foreground">
          Choose a video or try the demo timeline.
        </p>
        <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] lg:gap-6">
          <Card
            className="min-w-0"
            aria-label="Video player"
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={(event) => {
              if (
                !event.currentTarget.contains(
                  event.relatedTarget as Node | null
                )
              )
                setDragging(false)
            }}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              chooseVideo(event.dataTransfer.files[0])
            }}
          >
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0 p-4">
              <CardTitle className="text-base">Video</CardTitle>
              <div className="flex items-center gap-2">
                {media && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-11 sm:h-9"
                    onClick={useDemo}
                  >
                    Use demo
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className="h-11 sm:h-9"
                  onClick={() => input.current?.click()}
                >
                  {media ? "Change video" : "Choose video"}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 px-4 pb-4">
              {media ? (
                <video
                  ref={setVideo}
                  src={media.url}
                  className="aspect-video w-full rounded-md bg-black object-contain"
                  controls
                  playsInline
                  preload="metadata"
                  aria-label="Selected video"
                />
              ) : (
                <div
                  className={cn(
                    "flex aspect-video items-center justify-center rounded-md bg-muted px-6 text-center",
                    dragging && "ring-2 ring-ring"
                  )}
                >
                  <p className="text-sm text-muted-foreground">
                    {dragging ? (
                      "Drop your video here"
                    ) : (
                      <>
                        No video selected
                        <span className="hidden sm:block">
                          Choose a file or drop it here.
                        </span>
                      </>
                    )}
                  </p>
                </div>
              )}
              <input
                ref={input}
                type="file"
                accept="video/*"
                aria-label="Choose local video"
                hidden
                onChange={(event) => {
                  chooseVideo(event.target.files?.[0])
                  event.target.value = ""
                }}
              />
              {media && (
                <p
                  className="truncate text-xs text-muted-foreground"
                  title={media.name}
                >
                  {media.name}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Local playback only. Nothing is uploaded.
              </p>
              {(fileError || playback.error) && (
                <p className="text-sm text-destructive" role="alert">
                  {fileError || playback.error}
                </p>
              )}
            </CardContent>
          </Card>
          <Card className="min-w-0" aria-label="Momentum chart">
            <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
              <CardTitle className="text-base">Momentum</CardTitle>
              <span
                className="text-sm tabular-nums text-muted-foreground"
                aria-label="Current playback time"
              >
                {formatTime(playback.time)}
              </span>
            </CardHeader>
            <CardContent className="space-y-4 px-4 pb-4">
              <MomentumChart snapshot={playback.snapshot} />
              <div className="flex min-w-0 items-center gap-2 sm:gap-3">
                <Button
                  variant="outline"
                  size="icon"
                  className="h-11 w-11 shrink-0 sm:h-9 sm:w-9"
                  aria-label={
                    playback.playing ? "Pause playback" : "Play playback"
                  }
                  disabled={playback.disabled}
                  onClick={() => void playback.togglePlay()}
                >
                  {playback.playing ? <Pause /> : <Play />}
                </Button>
                <Slider
                  aria-label="Playback position"
                  className="h-11 min-w-0 sm:h-9"
                  min={0}
                  max={playback.duration || 60}
                  step={0.1}
                  value={[Math.min(playback.time, playback.duration || 60)]}
                  disabled={playback.disabled}
                  onValueChange={([value]) => playback.seek(value)}
                />
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {formatTime(playback.duration)}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-11 w-11 shrink-0 sm:h-9 sm:w-9"
                  aria-label="Restart playback"
                  disabled={playback.disabled}
                  onClick={() => playback.seek(0)}
                >
                  <RotateCcw />
                </Button>
              </div>
            </CardContent>
            <CardFooter className="px-4 pb-4 text-xs text-muted-foreground">
              <p>
                {playback.snapshot.momentum === null
                  ? "Observation gap · unable to assess. "
                  : ""}
                {media
                  ? "Demo curve synced to video. The 60s signal repeats."
                  : "60-second demo timeline."}{" "}
                No video analysis is running.
              </p>
            </CardFooter>
          </Card>
        </div>
      </main>
    </div>
  )
}
