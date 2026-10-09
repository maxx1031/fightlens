import { useState } from "react"
import { Button } from "./components/ui/button"
import { Badge } from "./components/ui/badge"
import "./styles/ui.css"

export default function Popup() {
  const [error, setError] = useState("")
  async function openOverlay() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (!tab?.id || !tab.url?.startsWith("http")) {
      setError("Open a regular website first, or use the demo room.")
      return
    }
    try {
      await chrome.tabs.sendMessage(tab.id, { type: "fightlens:open" })
      window.close()
    } catch {
      setError("Refresh this page after loading the extension, then try again.")
    }
  }
  return (
    <main className="fl-theme w-72 space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold">FightLens</h1>
        <Badge variant="outline">Demo</Badge>
      </div>
      <p className="text-sm text-muted-foreground">
        A momentum curve alongside your video.
      </p>
      <div className="space-y-2">
        <Button className="w-full" onClick={() => void openOverlay()}>
          Show on this page
        </Button>
        <Button
          variant="outline"
          className="w-full"
          onClick={() =>
            void chrome.tabs.create({
              url: chrome.runtime.getURL("tabs/review.html")
            })
          }
        >
          Open demo room
        </Button>
      </div>
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Simulated data · no video analysis.
      </p>
    </main>
  )
}
