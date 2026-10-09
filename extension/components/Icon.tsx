import type { CSSProperties } from "react"

export function Icon({
  name,
  size = 18,
  style
}: {
  name:
    | "play"
    | "pause"
    | "close"
    | "minus"
    | "refresh"
    | "grip"
    | "arrow"
    | "lens"
  size?: number
  style?: CSSProperties
}) {
  const paths = {
    play: <path d="m8 5 11 7-11 7Z" />,
    pause: (
      <>
        <path d="M8 5v14M16 5v14" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
    minus: <path d="M5 12h14" />,
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" />
      </>
    ),
    grip: (
      <>
        <path
          d="M8 6h.01M16 6h.01M8 12h.01M16 12h.01M8 18h.01M16 18h.01"
          strokeWidth="3"
        />
      </>
    ),
    arrow: <path d="m7 17 10-10M7 7h10v10" />,
    lens: (
      <>
        <path d="m12 3 8 5v8l-8 5-8-5V8Z" />
        <path d="M7 12h3l2-4 2 8 2-4h2" />
      </>
    )
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  )
}
