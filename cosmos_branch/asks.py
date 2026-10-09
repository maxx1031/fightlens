"""What Cosmos is asked about a clip, and how its answer is read.

    exchange   "list every strike in this clip": when, who, with what, at what, with what result,
               then who got the better of the passage and one sentence on it
    context    "what would a strike count miss": who is pressing, anything notable, one sentence

Three things about the questions:

  - Nothing in them comes from the pose tracker except who is called A and who B. The model is not told what
    to expect, so what goes into the memory is what it saw and not an echo of a suspicion.
  - "unclear" is offered in so many words. A reviewer forced to choose between landed and missed will choose,
    and the memory would hold a guess as a fact.
  - Time is asked for as the number printed under the frame (see clips.py), never as time into the clip.

The answer is read strictly where it counts and loosely elsewhere: a strike with no attacker is dropped and
counted as dropped, a time outside the window is discarded (the strike stays), a word that is not one of the
offered ones becomes "unclear" or empty.

[UNVERIFIED] No fight footage and no real endpoint has seen these questions. How well a model trained on
robots, traffic and first-person video lists the strikes of an exchange is exactly what is not known yet:
`python review.py <clip> --window T0 T1` puts the question to the real endpoint for a stretch of your choosing.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from cosmos import CosmosError, extract_json
from windows import EXCHANGE

TIME_SLACK_S = 0.3       # a time this far outside the window is still taken as meant for it

EXCHANGE_SYSTEM = ("You log the strikes of a combat sports bout from short video clips. Report only what the frames "
                   "show. Reply with a single JSON object and nothing else.")
CONTEXT_SYSTEM = ("You watch stretches of a combat sports bout between its exchanges and note how they went. Report "
                  "only what the frames show. Reply with a single JSON object and nothing else.")


def question(window, clip, fighters: Optional[dict] = None) -> tuple[str, str]:
    """(system prompt, prompt) for this window's clip. fighters: {"A": "red trunks", "B": "black trunks"}, optional."""
    if window.kind == EXCHANGE:
        return EXCHANGE_SYSTEM, exchange_prompt(clip, fighters)
    return CONTEXT_SYSTEM, context_prompt(clip, fighters)


def read(window, reply: str) -> dict:
    """The model's reply as the fields of a memory entry. Raises CosmosError when it is not an answer."""
    return read_exchange(reply, window) if window.kind == EXCHANGE else read_context(reply)


def _opening(clip, fighters: Optional[dict]) -> list[str]:
    seconds = clip.t1 - clip.t0
    if clip.speed <= 0.67:
        pace = f"This clip shows {seconds:.1f} seconds of a bout in slow motion, about {1 / clip.speed:.0f} times slower than real time."
    elif clip.speed >= 1.5:
        pace = f"This clip shows {seconds:.0f} seconds of a bout, sped up about {clip.speed:.0f} times."
    else:
        pace = f"This clip shows {seconds:.1f} seconds of a bout at about real speed."
    framing = " It is cropped to the two fighters." if clip.cropped else ""
    lines = [f"{pace}{framing} The time in the bout is printed under every frame: the clip runs from "
             f"{clip.t0:.2f} s to {clip.t1:.2f} s."]

    described = {label: str(text).strip() for label, text in (fighters or {}).items() if str(text or "").strip()}
    if clip.tagged and described:
        lines.append("The two fighters are tagged A and B above their heads. "
                     + " ".join(f"{label}: {text}." for label, text in sorted(described.items()))
                     + " The tags follow a pose tracker and can slip onto the wrong fighter when the two are tangled: "
                       "where a tag and a description disagree, go by the description.")
    elif clip.tagged:
        lines.append("The two fighters are tagged A and B above their heads.")
    elif described:
        lines.append("The two fighters: " + " ".join(f"{label} is {text}." for label, text in sorted(described.items())))
    else:      # only good for a single clip looked at by hand: across clips, left and right do not stay with a fighter
        lines.append("Call the fighter on the left in the first frame A and the other one B.")
    return lines


def exchange_prompt(clip, fighters: Optional[dict] = None) -> str:
    return "\n".join(_opening(clip, fighters) + [
        "",
        "List every strike thrown in this clip, in the order they happen: punches, kicks, elbows, knees. For each one:",
        "- t: the time printed under the frame where it lands, is stopped, or passes closest",
        '- attacker: "A" or "B"',
        '- limb: "hand", "foot", "elbow" or "knee"',
        '- move: its usual name if you can tell (jab, cross, hook, uppercut, low kick, body kick, head kick), else ""',
        '- target: "head", "torso" or "legs", where it was aimed',
        '- outcome: "landed" (you see it connect with the target), "blocked" (arms, gloves or a raised leg stop it), '
        '"missed" (it reaches nothing), or "unclear" (these frames do not show which: say so, do not guess)',
        "A feint, a pawing hand or a raised guard is not a strike. If nobody throws anything, the list is empty.",
        "",
        "Then:",
        '- advantage: who got the better of this passage: "A", "B", "even" or "unclear"',
        "- note: one sentence on what happened, in words a viewer could check against the clip",
        "",
        "Reply with exactly this JSON shape:",
        '{"strikes": [{"t": <seconds>, "attacker": "<A|B>", "limb": "<hand|foot|elbow|knee>", "move": "<name or empty>", '
        '"target": "<head|torso|legs>", "outcome": "<landed|blocked|missed|unclear>"}], '
        '"advantage": "<A|B|even|unclear>", "note": "<one sentence>"}',
    ])


def context_prompt(clip, fighters: Optional[dict] = None) -> str:
    return "\n".join(_opening(clip, fighters) + [
        "",
        "Strikes are logged separately, so do not count them here. Say what a strike count would miss:",
        '- pressure: who is moving forward and making the other give ground: "A", "B", "neither" or "unclear"',
        "- notable: anything a viewer would call important, such as a knockdown, a clinch or takedown, "
        'a fighter visibly hurt, tired or cut. "" when there is nothing',
        "- note: one sentence on how this stretch went, in words a viewer could check against the clip",
        "",
        "Reply with exactly this JSON shape:",
        '{"pressure": "<A|B|neither|unclear>", "notable": "<what, or empty>", "note": "<one sentence>"}',
    ])


# ───────────────────────── Reading the answers ─────────────────────────

_OUTCOMES = {
    "landed": ("landed", "lands", "land", "hit", "hits", "connected", "connects", "clean"),
    "blocked": ("blocked", "block", "parried", "checked", "guarded", "deflected", "stopped"),
    "missed": ("missed", "miss", "misses", "whiffed", "short", "evaded", "slipped", "dodged"),
    "unclear": ("unclear", "unknown", "uncertain", "unsure"),
}
_LIMBS = {       # elbow and knee first: "knee to the leg" is a knee
    "elbow": ("elbow",),
    "knee": ("knee",),
    "hand": ("hand", "punch", "fist", "glove", "arm", "jab", "cross", "hook", "uppercut"),
    "foot": ("foot", "kick", "shin", "leg"),
}
_TARGETS = {
    "head": ("head", "face", "chin", "jaw", "temple", "nose"),
    "torso": ("torso", "body", "chest", "ribs", "stomach", "abdomen", "midsection", "liver"),
    "legs": ("legs", "leg", "thigh", "calf", "knee", "shin"),
}
_NOTHING = ("", "none", "nothing", "no", "n/a", "na", "null", "nil", "-")


def read_exchange(reply: str, window) -> dict:
    data = extract_json(reply)
    listed = data.get("strikes")
    if not isinstance(listed, list):
        raise CosmosError(f"The reply has no list of strikes (an empty list is an answer, no list is not): {str(data)[:200]}")
    strikes, dropped = [], 0
    for item in listed:
        attacker = _fighter(item.get("attacker")) if isinstance(item, dict) else None
        if attacker is None:
            dropped += 1               # a strike nobody threw cannot be counted for anybody
            continue
        t = _seconds(item.get("t", item.get("time")))
        if t is not None and not window.t0 - TIME_SLACK_S <= t <= window.t1 + TIME_SLACK_S:
            t = None                   # most likely time into the clip and not the printed time: the strike stays, its time goes
        strikes.append({
            "t": None if t is None else round(t, 2),
            "attacker": attacker,
            "limb": _one_of(item.get("limb"), _LIMBS),
            "move": _text(item.get("move"))[:40].lower(),
            "target": _one_of(item.get("target", item.get("region")), _TARGETS),
            "outcome": _one_of(item.get("outcome", item.get("result")), _OUTCOMES) or "unclear",
        })
    strikes.sort(key=lambda s: (s["t"] is None, s["t"] or 0.0))
    return {"strikes": strikes, "advantage": _fighter(data.get("advantage")) or _level(data.get("advantage")),
            "note": _text(data.get("note")), "dropped": dropped}


def read_context(reply: str) -> dict:
    data = extract_json(reply)
    if not {"pressure", "notable", "note"} & set(data):
        raise CosmosError(f"The reply answers none of the three questions: {str(data)[:200]}")
    word = _text(data.get("pressure")).lower()
    pressure = _fighter(data.get("pressure")) or ("neither" if word in ("neither", "none", "nobody", "both", "even") else "unclear")
    notable = _text(data.get("notable"))
    return {"pressure": pressure, "notable": "" if notable.lower() in _NOTHING else notable, "note": _text(data.get("note"))}


def _fighter(value: Any) -> Optional[str]:
    """ "A", "a", "Fighter B", "B (blue)" -> the letter. None when it names neither or both."""
    found = set(re.findall(r"(?<![A-Za-z])([AB])(?![A-Za-z])", str(value or "").upper()))
    return found.pop() if len(found) == 1 else None


def _level(value: Any) -> str:
    return "even" if _text(value).lower() in ("even", "equal", "neither", "level", "draw", "tie", "both") else "unclear"


def _one_of(value: Any, words: dict) -> Optional[str]:
    said = re.findall(r"[a-z]+", str(value or "").lower())
    if {"not", "no", "never"} & set(said):
        return None                    # "not landed" is not "landed"
    return next((key for key, names in words.items() if any(word in names for word in said)), None)


def _seconds(value: Any) -> Optional[float]:
    """A time as the model wrote it: 12.34, "12.34", "t = 12.34 s"."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    number = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(number.group()) if number else None


def _text(value: Any) -> str:
    return "" if value is None else " ".join(str(value).split())
