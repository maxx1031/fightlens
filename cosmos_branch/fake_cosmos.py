"""A stand-in for the Cosmos endpoint, to run the whole branch before the real one is there.

    python fake_cosmos.py                 # http://127.0.0.1:9001
    python fake_cosmos.py --delay 2       # pretend to think for 2 seconds
    python fake_cosmos.py --think         # reason out loud first, in <think>...</think>, as the real model does

    COSMOS3_REASON_URL=http://127.0.0.1:9001 python review.py <clip_dir>
    COSMOS3_REASON_URL=http://127.0.0.1:9001 python narrate.py <clip_dir> --p-a 0.6

It never looks at the video. It tells the four questions apart by their wording and makes up an answer of the
right shape: for an exchange, strikes at times inside the window it was asked about, the same ones every time
for the same window. Everything it writes says "(fake)".
"""
from __future__ import annotations

import argparse
import json
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "fake/cosmos3-reason"
_MOVES = (("hand", "jab", "head"), ("hand", "cross", "head"), ("hand", "hook", "torso"),
          ("foot", "low kick", "legs"), ("foot", "body kick", "torso"))
_OUTCOMES = ("landed", "landed", "blocked", "missed", "unclear")


def answer(prompt: str) -> tuple[str, str]:
    """(which question this is, the made-up reply)."""
    span = re.search(r"runs from ([\d.]+) s to ([\d.]+) s", prompt)
    t0, t1 = (float(span.group(1)), float(span.group(2))) if span else (0.0, 1.0)
    dice = random.Random(int(t0 * 100))
    if "List every strike thrown in this clip" in prompt:
        strikes = []
        for _ in range(dice.choice((0, 1, 2, 2, 3))):
            limb, move, target = dice.choice(_MOVES)
            strikes.append({"t": round(dice.uniform(t0, t1), 2), "attacker": dice.choice("AB"), "limb": limb,
                            "move": move, "target": target, "outcome": dice.choice(_OUTCOMES)})
        landed = {who: sum(s["attacker"] == who and s["outcome"] == "landed" for s in strikes) for who in "AB"}
        better = "A" if landed["A"] > landed["B"] else "B" if landed["B"] > landed["A"] else "even"
        return "exchange", json.dumps({"strikes": sorted(strikes, key=lambda s: s["t"]), "advantage": better,
                                       "note": f"(fake) made-up exchange between {t0:.1f} s and {t1:.1f} s; nothing was watched."})
    if "Strikes are logged separately" in prompt:
        return "context", json.dumps({"pressure": dice.choice(("A", "B", "neither")), "notable": "",
                                      "note": f"(fake) made-up stretch between {t0:.1f} s and {t1:.1f} s; nothing was watched."})
    ids = re.findall(r"^\[([xc][\d.]+)\]", prompt, flags=re.M)
    if "Rewrite the notes" in prompt:
        return "notes", json.dumps({"summary": f"(fake) notes folding in {len(ids)} new entries; nothing was read."})
    if "Write the caption" in prompt:
        return "caption", json.dumps({"text": "(fake) caption: the record was not read.", "evidence": ids[-2:], "agrees": "partly"})
    return "other", "OK"


def serve(port: int = 9001, delay: float = 0.0, think: bool = False) -> ThreadingHTTPServer:
    """Start the fake endpoint on a background thread. server.asked lists the questions it got; server.shutdown() stops it."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _reply(self, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._reply({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            prompt, has_video = "", False
            for message in body.get("messages", []):
                content = message.get("content")
                for part in content if isinstance(content, list) else [{"type": "text", "text": content or ""}]:
                    prompt += part.get("text", "") if part.get("type") == "text" else ""
                    has_video = has_video or part.get("type") in ("video_url", "video_frames")
            kind, text = answer(prompt)
            server.asked.append((kind, has_video))
            time.sleep(delay)
            if think:
                text = f"<think>\n(fake reasoning, with a stray brace {{ in it)\n</think>\n\n{text}"
            self._reply({"id": "chatcmpl-fake", "object": "chat.completion", "model": body.get("model", MODEL),
                         "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}]})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.asked = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A stand-in for the Cosmos endpoint")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--delay", type=float, default=0.0, help="seconds each answer pretends to take")
    parser.add_argument("--think", action="store_true", help="put <think>...</think> before every answer")
    args = parser.parse_args()
    serve(args.port, args.delay, args.think)
    print(f"Fake Cosmos at http://127.0.0.1:{args.port}   (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
