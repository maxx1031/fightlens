import { useEffect, useRef, useState } from "react"
import type { PointerEvent } from "react"
import { usePlayback } from "../lib/usePlayback"
import { formatTime } from "../lib/types"
import { Icon } from "./Icon"
import { MomentumChart } from "./MomentumChart"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "./ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "./ui/select"
import { Slider } from "./ui/slider"

export function FightLensPanel({ onClose }: { onClose: () => void }) {
  const playback = usePlayback()
  const [collapsed, setCollapsed] = useState(false)
  const [position, setPosition] = useState<{ x: number; y: number } | null>(
    null
  )
  const [portalContainer, setPortalContainer] = useState<
    HTMLElement | DocumentFragment
  >()
  const panel = useRef<HTMLElement>(null)
  const drag = useRef<{
    x: number
    y: number
    left: number
    top: number
  } | null>(null)

  useEffect(() => {
    const root = panel.current?.getRootNode()
    setPortalContainer(root instanceof ShadowRoot ? root : document.body)
  }, [])

  useEffect(() => {
    const clamp = () =>
      setPosition((previous) => {
        if (!previous || !panel.current) return previous
        return {
          x: Math.max(
            12,
            Math.min(
              previous.x,
              Math.max(12, window.innerWidth - panel.current.offsetWidth - 12)
            )
          ),
          y: Math.max(
            12,
            Math.min(
              previous.y,
              Math.max(12, window.innerHeight - panel.current.offsetHeight - 12)
            )
          )
        }
      })
    window.addEventListener("resize", clamp)
    clamp()
    return () => window.removeEventListener("resize", clamp)
  }, [collapsed])

  function startDrag(event: PointerEvent<HTMLElement>) {
    if ((event.target as Element).closest("button") || event.button !== 0)
      return
    const rect = panel.current?.getBoundingClientRect()
    if (!rect) return
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      left: rect.left,
      top: rect.top
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function moveDrag(event: PointerEvent<HTMLElement>) {
    if (!drag.current || !panel.current) return
    setPosition({
      x: Math.max(
        12,
        Math.min(
          drag.current.left + event.clientX - drag.current.x,
          Math.max(12, window.innerWidth - panel.current.offsetWidth - 12)
        )
      ),
      y: Math.max(
        12,
        Math.min(
          drag.current.top + event.clientY - drag.current.y,
          Math.max(12, window.innerHeight - panel.current.offsetHeight - 12)
        )
      )
    })
  }

  return (
    <aside
      ref={panel}
      className="fl-panel fl-theme"
      aria-label="FightLens momentum overlay"
      style={
        position
          ? {
              left: position.x,
              top: position.y,
              right: "auto",
              maxHeight: `calc(100vh - ${position.y + 12}px)`
            }
          : undefined
      }
    >
      <Card>
        <CardHeader
          className="fl-drag-handle flex-row items-center justify-between space-y-0 px-4 py-3"
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={() => {
            drag.current = null
          }}
          onPointerCancel={() => {
            drag.current = null
          }}
        >
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-semibold">FightLens</CardTitle>
            <Badge variant="outline">Demo</Badge>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={collapsed ? "Expand panel" : "Minimize panel"}
              onClick={() => setCollapsed(!collapsed)}
            >
              <Icon name={collapsed ? "arrow" : "minus"} size={16} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label="Close FightLens"
              onClick={onClose}
            >
              <Icon name="close" size={16} />
            </Button>
          </div>
        </CardHeader>
        {!collapsed && (
          <>
            <CardContent className="space-y-5 px-4 pb-4">
              <div className="flex items-center justify-between text-sm">
                <span>Momentum</span>
                <span className="tabular-nums text-muted-foreground">
                  {formatTime(playback.time)}
                </span>
              </div>
              <MomentumChart snapshot={playback.snapshot} />
              <div className="flex items-center gap-3">
                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  aria-label={
                    playback.playing ? "Pause playback" : "Play playback"
                  }
                  onClick={() => void playback.togglePlay()}
                >
                  <Icon name={playback.playing ? "pause" : "play"} size={16} />
                </Button>
                <Slider
                  aria-label="Playback position"
                  min={0}
                  max={playback.duration || 60}
                  step={0.1}
                  value={[Math.min(playback.time, playback.duration || 60)]}
                  disabled={!!playback.video && !playback.duration}
                  onValueChange={([value]) => playback.seek(value)}
                />
                <span className="text-xs tabular-nums text-muted-foreground">
                  {formatTime(playback.duration)}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  aria-label="Restart playback"
                  disabled={!!playback.video && !playback.duration}
                  onClick={() => playback.seek(0)}
                >
                  <Icon name="refresh" size={16} />
                </Button>
              </div>
              <Select
                value={
                  playback.video
                    ? String(playback.videos.indexOf(playback.video))
                    : "demo"
                }
                onValueChange={(value) =>
                  playback.selectVideo(
                    value === "demo"
                      ? null
                      : playback.videos[Number(value)] || null
                  )
                }
              >
                <SelectTrigger aria-label="Playback source">
                  <SelectValue placeholder="Playback source" />
                </SelectTrigger>
                <SelectContent
                  portalContainer={portalContainer}
                  className="z-[2147483647]"
                >
                  <SelectItem value="demo">
                    Demo timeline · 60 seconds
                  </SelectItem>
                  {playback.videos.map((item, index) => (
                    <SelectItem key={index} value={String(index)}>
                      Page video {index + 1}
                      {Number.isFinite(item.duration)
                        ? ` · ${formatTime(item.duration)}`
                        : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {playback.error && (
                <p className="text-xs text-destructive" role="alert">
                  {playback.error}
                </p>
              )}
            </CardContent>
            <CardFooter className="px-4 pb-4 text-xs text-muted-foreground">
              <p>
                {playback.snapshot.momentum === null
                  ? "Observation gap · unable to assess. "
                  : ""}
                Simulated data · no video analysis.
                {playback.video &&
                  " Demo repeats every 60s against the video clock."}
              </p>
            </CardFooter>
          </>
        )}
      </Card>
    </aside>
  )
}
