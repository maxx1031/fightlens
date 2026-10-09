import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { DEMO_DURATION, getDemoSnapshot } from "./demo"

export function usePlayback() {
  const [videos, setVideos] = useState<HTMLVideoElement[]>([])
  const [video, setVideo] = useState<HTMLVideoElement | null>(null)
  const [time, setTime] = useState(22)
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(DEMO_DURATION)
  const [error, setError] = useState("")
  const clockTime = useRef(time)
  clockTime.current = time

  const scan = useCallback(() => {
    const found = Array.from(document.querySelectorAll("video")).filter(
      (item) => !!(item.currentSrc || item.src || item.srcObject)
    )
    setVideos((previous) =>
      previous.length === found.length &&
      previous.every((item, index) => item === found[index])
        ? previous
        : found
    )
    setVideo((previous) =>
      previous && found.includes(previous) ? previous : null
    )
  }, [])

  useEffect(() => {
    scan()
    const interval = window.setInterval(scan, 1500)
    return () => window.clearInterval(interval)
  }, [scan])

  useEffect(() => {
    setError("")
    if (!video) {
      setDuration(DEMO_DURATION)
      setTime(22)
      setPlaying(false)
      return
    }
    const sync = () => {
      setTime(video.currentTime || 0)
      setPlaying(!video.paused && !video.ended)
      setDuration(
        Number.isFinite(video.duration) && video.duration > 0
          ? video.duration
          : 0
      )
    }
    const events = [
      "timeupdate",
      "play",
      "pause",
      "seeking",
      "seeked",
      "loadedmetadata",
      "durationchange",
      "ended",
      "emptied"
    ]
    events.forEach((event) => video.addEventListener(event, sync))
    sync()
    return () =>
      events.forEach((event) => video.removeEventListener(event, sync))
  }, [video])

  useEffect(() => {
    if (video || !playing) return
    const started = performance.now()
    const initialTime = clockTime.current
    const interval = window.setInterval(() => {
      const next = initialTime + (performance.now() - started) / 1000
      setTime(Math.min(next, DEMO_DURATION))
      if (next >= DEMO_DURATION) setPlaying(false)
    }, 100)
    return () => window.clearInterval(interval)
    // Playback starts from the current position without restarting on each tick.
  }, [video, playing])

  async function togglePlay() {
    setError("")
    if (video) {
      try {
        if (video.paused) await video.play()
        else video.pause()
      } catch {
        setError("The player could not start. Use the website's play button.")
      }
    } else {
      if (time >= DEMO_DURATION) setTime(0)
      setPlaying((value) => !value)
    }
  }

  function seek(next: number) {
    setError("")
    const target = Math.max(0, Math.min(next, duration || next))
    if (video) {
      try {
        video.currentTime = target
        setTime(target)
      } catch {
        setError("This player does not support seeking.")
      }
    } else {
      // Restart the clock's elapsed-time anchor on the next playback effect.
      setPlaying(false)
      setTime(target)
    }
  }

  const snapshot = useMemo(() => getDemoSnapshot(time), [time])
  return {
    videos,
    video,
    selectVideo: setVideo,
    time,
    duration,
    playing,
    togglePlay,
    seek,
    error,
    snapshot
  }
}
