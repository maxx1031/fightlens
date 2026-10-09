import { useEffect, useRef, useState } from "react"
import { FightLensPanel } from "../components/FightLensPanel"
import { Button } from "../components/ui/button"
import { Badge } from "../components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card"
import "../styles/ui.css"

export default function ReviewRoom() {
  const [visible, setVisible] = useState(true)
  const [videoUrl, setVideoUrl] = useState("")
  const [filename, setFilename] = useState("")
  const [videoError, setVideoError] = useState("")
  const fileInput = useRef<HTMLInputElement>(null)
  useEffect(() => {
    document.title = "FightLens · Demo room"
  }, [])
  useEffect(
    () => () => {
      if (videoUrl) URL.revokeObjectURL(videoUrl)
    },
    [videoUrl]
  )
  return (
    <div className="fl-theme min-h-screen">
      <header className="flex h-16 items-center justify-between border-b px-6">
        <div className="flex items-center gap-2">
          <h1 className="text-sm font-semibold">FightLens</h1>
          <Badge variant="outline">Demo</Badge>
        </div>
        <Button variant="outline" size="sm" onClick={() => setVisible(true)}>
          Open overlay
        </Button>
      </header>
      <main className="max-w-3xl space-y-4 p-6 min-[1100px]:mr-[480px]">
        <p className="text-sm text-muted-foreground">
          Review the momentum overlay. Optionally choose a local video to test
          playback synchronization.
        </p>
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base">{filename || "Video"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {videoUrl ? (
              <video
                className="aspect-video w-full rounded-md bg-black"
                src={videoUrl}
                controls
                playsInline
                onError={() =>
                  setVideoError(
                    "This video could not be played. Try an MP4 supported by Chrome."
                  )
                }
              />
            ) : (
              <div className="flex aspect-video items-center justify-center rounded-md bg-muted">
                <p className="text-sm text-muted-foreground">
                  No video selected
                </p>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileInput.current?.click()}
              >
                {videoUrl ? "Change video" : "Choose video"}
              </Button>
              <p className="text-xs text-muted-foreground">
                Local playback only. Nothing is uploaded.
              </p>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept="video/*"
              aria-label="Choose local video"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) {
                  setVideoUrl(URL.createObjectURL(file))
                  setFilename(file.name)
                  setVideoError("")
                }
              }}
            />
            {videoUrl && (
              <p className="text-xs text-muted-foreground">
                Select Page video in the overlay to link its playback clock.
              </p>
            )}
            {videoError && (
              <p className="text-sm text-destructive" role="alert">
                {videoError}
              </p>
            )}
          </CardContent>
        </Card>
      </main>
      {visible && <FightLensPanel onClose={() => setVisible(false)} />}
    </div>
  )
}
