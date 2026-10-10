"""Local win-probability endpoint for the live arcade page.

    .venv/bin/python winprob_server.py            # http://127.0.0.1:8787

The page (served from http://localhost:4173) posts the frames of one engaged second:
    POST /winprob {"session": "...", "segment": "...", "t0": 12.0, "t1": 13.0,
                   "fighters": {"A": "...", "B": "..."}, "frames": ["data:image/jpeg;base64,...", ...]}
The server asks Luna Decisions (OpenRouter) twice, with A/B listed in both orders, and
returns the averaged probabilities. The OpenRouter key stays on this machine (.env); it
never reaches the browser. Each session/segment keeps its own previous state.
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import sys
import threading
import time

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from openrouter_win_probability import (  # noqa: E402
    DEFAULT_API_URL, DEFAULT_DECISION_PROMPT, OpenRouterDecisionClient, parse_winner_probabilities,
)
from win_prob import DEFAULT_MODEL, read_api_key  # noqa: E402

ALLOWED_ORIGINS = {"http://localhost:4173", "http://127.0.0.1:4173"}
MAX_FRAMES = 12
MAX_BODY = 6 * 1024 * 1024


def payload(frames, fighters, previous, t0, t1, model):
    context = {"fighter_map": fighters, "previous_state": previous,
               "window": {"start_s": t0, "end_s": t1, "frame_order": "从早到晚",
                          "note": "Frames come from a live YOLO overlay; boxes are labelled A and B."}}
    state = [json.dumps(context, ensure_ascii=False, separators=(",", ":"))]
    state += [{"type": "image_url", "image_url": {"url": f, "detail": "low"}} for f in frames]
    return {"model": model, "state": state, "questions": {"winner": {
        "type": "choice", "instructions": DEFAULT_DECISION_PROMPT,
        "criteria": {"A": "选手 A 最终通过判定、KO/TKO 或降服获胜", "B": "选手 B 最终通过判定、KO/TKO 或降服获胜"}}}}


class State:
    def __init__(self, client, model):
        self.client, self.model = client, model
        self.previous = {}  # (session, segment) -> debiased previous result
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=4)

    def decide(self, body):
        frames = [f for f in body["frames"] if isinstance(f, str) and f.startswith("data:image/jpeg;base64,")][:MAX_FRAMES]
        if len(frames) < 2:
            raise ValueError("need at least two JPEG frames")
        fighters = {k: str(body["fighters"].get(k) or f"fighter labelled {k} in the overlay")[:160] for k in ("A", "B")}
        key = (str(body["session"]), str(body["segment"]))
        t0, t1 = float(body["t0"]), float(body["t1"])
        with self.lock:
            prev = self.previous.get(key)
        swapped_prev = prev and {**prev, "probabilities": {"A": prev["probabilities"]["B"], "B": prev["probabilities"]["A"]}}
        started = time.monotonic()
        jobs = [self.pool.submit(self.client.submit, payload(frames, fighters, prev, t0, t1, self.model)),
                self.pool.submit(self.client.submit, payload(frames, {"A": fighters["B"], "B": fighters["A"]},
                                                             swapped_prev, t0, t1, self.model))]
        listed, swapped = (parse_winner_probabilities(j.result())["probabilities"] for j in jobs)
        a = round((listed["A"] + swapped["B"]) / 2, 4)
        result = {"start_s": t0, "end_s": t1, "probabilities": {"A": a, "B": round(1 - a, 4)}}
        with self.lock:
            self.previous[key] = result
        return {**result, "raw_as_listed": listed, "raw_swapped": swapped, "model": self.model,
                "frames": len(frames), "latency_s": round(time.monotonic() - started, 3)}


def handler(state):
    class Handler(BaseHTTPRequestHandler):
        def cors(self):
            origin = self.headers.get("Origin", "")
            if origin in ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def reply(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self.cors()
            self.end_headers()

        def do_GET(self):
            self.reply(200, {"ok": True, "model": state.model}) if self.path == "/health" else self.reply(404, {})

        def do_POST(self):
            if self.path != "/winprob" or self.headers.get("Origin", "") not in ALLOWED_ORIGINS:
                return self.reply(403, {"error": "forbidden"})
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                return self.reply(413, {"error": "body too large"})
            try:
                result = state.decide(json.loads(self.rfile.read(length)))
            except Exception as exc:  # report, never leak the key
                return self.reply(502, {"error": f"{type(exc).__name__}: {exc}"[:300]})
            print(f"{result['start_s']:7.1f}s  A {result['probabilities']['A']:.2f}  "
                  f"(raw {result['raw_as_listed']['A']:.2f} / swapped-A {result['raw_swapped']['A']:.2f})  "
                  f"{result['latency_s']}s", flush=True)
            self.reply(200, result)

        def log_message(self, *args):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    key = read_api_key()
    if not key:
        raise SystemExit(f"OPENROUTER_API_KEY missing: add it to {REPO / '.env'}")
    state = State(OpenRouterDecisionClient(DEFAULT_API_URL, key), args.model)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(state))
    print(f"win-probability server on http://127.0.0.1:{args.port} ({args.model})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
