#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VIDEO_PATH="${1:-$PROJECT_ROOT/videos/pereira_rountree_45s.mp4}"
MAX_WINDOWS="${2:-3}"
OUTPUT_PATH="${OUTPUT_PATH:-$PROJECT_ROOT/runs/openrouter/smoke_test_${MAX_WINDOWS}s.jsonl}"
DEFAULT_FIGHTER_MAP='{"A":{"name":"Alex Pereira"},"B":{"name":"Khalil Rountree Jr."}}'
FIGHTER_MAP="${FIGHTER_MAP:-$DEFAULT_FIGHTER_MAP}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required." >&2
  exit 2
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "Error: ffmpeg and ffprobe are required." >&2
  exit 2
fi

if [[ ! -f "$VIDEO_PATH" ]]; then
  echo "Error: video not found: $VIDEO_PATH" >&2
  exit 2
fi

if [[ ! "$MAX_WINDOWS" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: seconds must be a positive integer, received: $MAX_WINDOWS" >&2
  exit 2
fi

if [[ -z "${OPENROUTER_API_KEY:-}" && ! -f "$PROJECT_ROOT/.env" ]]; then
  echo "Error: set OPENROUTER_API_KEY or create $PROJECT_ROOT/.env first." >&2
  exit 2
fi

PROMPT_ARGS=()
if [[ -n "${DECISION_PROMPT_FILE:-}" ]]; then
  if [[ ! -f "$DECISION_PROMPT_FILE" ]]; then
    echo "Error: prompt file not found: $DECISION_PROMPT_FILE" >&2
    exit 2
  fi
  PROMPT_ARGS=(--prompt-file "$DECISION_PROMPT_FILE")
fi

cd "$PROJECT_ROOT"

echo "[1/2] Checking ${MAX_WINDOWS} second(s) of five-frame sampling..." >&2
python3 scripts/openrouter_win_probability.py \
  "$VIDEO_PATH" \
  --fighter-map "$FIGHTER_MAP" \
  --max-windows "$MAX_WINDOWS" \
  "${PROMPT_ARGS[@]}" \
  --dry-run

echo "[2/2] Calling OpenRouter once per source-video second..." >&2
python3 scripts/openrouter_win_probability.py \
  "$VIDEO_PATH" \
  --fighter-map "$FIGHTER_MAP" \
  --max-windows "$MAX_WINDOWS" \
  "${PROMPT_ARGS[@]}" \
  --realtime \
  --retries 0 \
  --output "$OUTPUT_PATH" \
  --overwrite

echo "Smoke test passed. Detailed JSONL: $OUTPUT_PATH" >&2
