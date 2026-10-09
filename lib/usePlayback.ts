"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { DEMO_DURATION, getDemoSnapshot } from "./demo"

export function usePlayback(
  video: HTMLVideoElement | null,
  source: string | null
) {
  const [time, setTime] = useState(22)
  const [duration, setDuration] = useState(DEMO_DURATION)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState("")
  const clockTime = useRef(time)
  clockTime.current = time

  useEffect(() => {
    setError("")
    setPlaying(false)
    if (!video || !source) {
      setTime(22)
      setDuration(DEMO_DURATION)
      return
    }
    const sync = () => {
      setTime(Number.isFinite(video.currentTime) ? video.currentTime : 0)
      setDuration(
        Number.isFinite(video.duration) && video.duration > 0
          ? video.duration
          : 0
      )
      setPlaying(!video.paused && !video.ended)
    }
    const failed = () => {
      setPlaying(false)
      setError(
        "This video could not be played. Try an MP4 or WebM supported by your browser."
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
    video.addEventListener("error", failed)
    sync()
    return () => {
      events.forEach((event) => video.removeEventListener(event, sync))
      video.removeEventListener("error", failed)
    }
  }, [video, source])

  useEffect(() => {
    if (source || !playing) return
    const started = performance.now()
    const initialTime = clockTime.current
    const interval = window.setInterval(() => {
      const next = Math.min(
        initialTime + (performance.now() - started) / 1000,
        DEMO_DURATION
      )
      setTime(next)
      if (next >= DEMO_DURATION) setPlaying(false)
    }, 100)
    return () => window.clearInterval(interval)
  }, [source, playing])

  async function togglePlay() {
    setError("")
    if (source) {
      if (!video) return
      try {
        if (video.paused) await video.play()
        else video.pause()
      } catch {
        setError(
          "Playback could not start. Try the video's native play button."
        )
      }
    } else {
      if (time >= DEMO_DURATION) setTime(0)
      setPlaying((previous) => !previous)
    }
  }

  function seek(next: number) {
    setError("")
    const target = Math.max(0, Math.min(next, duration || next))
    if (source) {
      if (!video || !duration) return
      try {
        video.currentTime = target
        setTime(target)
      } catch {
        setError("This video cannot seek to that position.")
      }
    } else {
      setPlaying(false)
      setTime(target)
    }
  }

  const snapshot = useMemo(() => getDemoSnapshot(time), [time])
  return {
    time,
    duration,
    playing,
    togglePlay,
    seek,
    error,
    snapshot,
    disabled: !!source && (!video || !duration || !!error)
  }
}
