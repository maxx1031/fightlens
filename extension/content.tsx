import cssText from "data-text:~styles/ui.css"
import type { PlasmoCSConfig, PlasmoGetStyle, PlasmoMountShadowHost } from "plasmo"
import { useEffect, useState } from "react"
import { FightLensPanel } from "./components/FightLensPanel"

export const config: PlasmoCSConfig = {
  matches: ["http://*/*", "https://*/*"],
  run_at: "document_idle",
  all_frames: false
}
export const getShadowHostId = () => "fightlens-overlay-host"
// Radix's accessible Select hides body siblings while open. Its ShadowRoot
// host must live inside body for that containment check to work correctly.
export const mountShadowHost: PlasmoMountShadowHost = ({ shadowHost }) => {
  document.body.appendChild(shadowHost)
}
export const getStyle: PlasmoGetStyle = () => {
  const style = document.createElement("style")
  // Sites such as YouTube use a 10px root font. Shadow DOM does not isolate rem
  // units, so preserve shadcn's normal 16px scale without changing the page.
  style.textContent = cssText.replace(
    /(-?[\d.]+)rem\b/g,
    (_, value) => `${Number(value) * 16}px`
  )
  return style
}

export default function FightLensOverlay() {
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    const listener = (
      message: { type?: string },
      sender: chrome.runtime.MessageSender,
      respond: (value: unknown) => void
    ) => {
      if (sender.id !== chrome.runtime.id) return
      if (message.type === "fightlens:open") {
        setVisible(true)
        respond({ ok: true })
      }
      if (message.type === "fightlens:close") {
        setVisible(false)
        respond({ ok: true })
      }
    }
    chrome.runtime.onMessage.addListener(listener)
    return () => chrome.runtime.onMessage.removeListener(listener)
  }, [])
  return visible ? <FightLensPanel onClose={() => setVisible(false)} /> : null
}
