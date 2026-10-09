"""How to reach Cosmos: the address, the request, and the one JSON object in a reply.

    COSMOS3_REASON_URL      the endpoint, e.g. http://host:port (already set on the organisers' VM)
    COSMOS3_REASON_MODEL    optional: when unset, the name is asked from GET /v1/models
    COSMOS_API_KEY          optional: the organisers' endpoint needs none

The call is OpenAI-compatible chat/completions with the video embedded as base64:

    POST {url}/v1/chat/completions
    {"model": "...", "max_tokens": 4096, "temperature": 0, "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": [
            {"type": "text", "text": "..."},
            {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,..."}}]}]}
    the reply is in choices[0].message.content

A question without a video (the running notes, the caption) goes to the same endpoint with the text alone.

[UNVERIFIED] The request shape follows the organisers' starter repo. It was tested against fake_cosmos.py only,
never against the real endpoint. The first real call to make is `python review.py <clip> --window T0 T1`:
it prints the question, the raw reply and how it was read.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests

MAX_TOKENS = 4096        # a cap, not a target: the model reasons inside <think> first, and a low cap cuts the answer off
TIMEOUT_S = 120.0
RETRIES = 2              # asked again after a refused connection, a timeout, 429 or 5xx


class CosmosError(RuntimeError):
    """No usable answer: the call failed, or the reply could not be read."""


class Cosmos:
    def __init__(self, url: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None,
                 timeout_s: float = TIMEOUT_S, max_tokens: int = MAX_TOKENS, retries: int = RETRIES, http: Any = None):
        url = (url or os.environ.get("COSMOS3_REASON_URL") or os.environ.get("COSMOS_API_BASE") or "").strip().rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        if not url:
            raise CosmosError("No Cosmos endpoint: set COSMOS3_REASON_URL, or pass --url")
        self.url = url
        # None = take it from the environment; "" = this endpoint has nothing to do with those variables
        self._model = (os.environ.get("COSMOS3_REASON_MODEL") or os.environ.get("COSMOS_MODEL", "")) if model is None else model
        key = (os.environ.get("GPU_BEARER_TOKEN") or os.environ.get("COSMOS_API_KEY", "")) if api_key is None else api_key
        self._headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._timeout_s, self._max_tokens, self._retries = timeout_s, max_tokens, retries
        self._http = http or requests          # anything with .request(method, url, json=, headers=, timeout=)

    @property
    def model(self) -> str:
        """The model's name. Asked from the endpoint the first time when none was configured."""
        if not self._model:
            listing = self._send("get", "/v1/models")
            try:
                self._model = str(listing["data"][0]["id"])
            except (KeyError, IndexError, TypeError) as exc:
                raise CosmosError(f"GET /v1/models did not name a model: {str(listing)[:200]}") from exc
        return self._model

    def ask(self, system: str, prompt: str, video: Optional[Path] = None) -> str:
        """One question, about one video or about none. Returns the reply as the model wrote it."""
        if video is None:
            content: Any = prompt
        else:
            encoded = base64.b64encode(Path(video).read_bytes()).decode("ascii")
            content = [{"type": "text", "text": prompt},
                       {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{encoded}"}}]
        reply = self._send("post", "/v1/chat/completions", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "max_tokens": self._max_tokens,
            "temperature": 0,
        })
        try:
            text = reply["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CosmosError(f"The reply has no message: {str(reply)[:200]}") from exc
        if not isinstance(text, str) or not text.strip():
            raise CosmosError("The reply is empty")
        return text

    def _send(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        problem = ""
        for attempt in range(self._retries + 1):
            try:
                reply = self._http.request(method, self.url + path, json=payload, headers=self._headers,
                                           timeout=self._timeout_s)
            except requests.RequestException as exc:
                problem = f"{type(exc).__name__}: {exc}"
            else:
                if reply.status_code < 400:
                    try:
                        return reply.json()
                    except ValueError as exc:
                        raise CosmosError(f"{method.upper()} {path}: the reply is not JSON: {reply.text[:200]}") from exc
                problem = f"HTTP {reply.status_code}: {reply.text[:300]}"
                if reply.status_code not in (408, 429) and reply.status_code < 500:
                    break                      # the request itself is refused: asking again will not help
            if attempt < self._retries:
                time.sleep(1.5 * (attempt + 1))
        raise CosmosError(f"{method.upper()} {self.url}{path} failed: {problem}")


def extract_json(reply: str) -> dict:
    """The one JSON object in a reply, whatever the model wrapped around it (<think>, <answer>, code fences, chatter)."""
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S)
    tagged = re.search(r"<answer>(.*?)</answer>", text, flags=re.S)
    if tagged:
        text = tagged.group(1)
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            whole = json.loads(text[start:end + 1])
            if isinstance(whole, dict):
                return whole
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder()           # chatter with braces of its own: take the first object that parses
        for at in (m.start() for m in re.finditer(r"\{", text)):
            try:
                found, _ = decoder.raw_decode(text[at:])
            except json.JSONDecodeError:
                continue
            if isinstance(found, dict):
                return found
    if "<think>" in text:
        raise CosmosError("The reply was cut off while the model was still reasoning (<think> never closes): "
                          "raise MAX_TOKENS in cosmos.py")
    raise CosmosError(f"The reply contains no JSON object: {(reply or '')[:200]!r}")
