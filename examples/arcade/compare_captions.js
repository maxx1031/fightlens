// Burned-in captions for the UFC side-by-side recording (compare.html):
// [start, end, caption, event line]. Times are clip seconds and follow compare_data.js:
// Cosmos verdicts arrive at 4.5, 5.3, 6.7, 11.0, 15.8 (the kick clip on PEREIRA's low kick
// at 13.1 s) and 22.2 s; the two estimates split at 5 s and the Cosmos one crosses to
// PEREIRA at 14 s. Entries past the clip's end play over the frozen last frame.
const CAPTIONS = [
  [0.0, 3.0, "Two AI models estimate who is winning, from the <b>same</b> video frames.", "Frames only · vs · Frames + Cosmos"],
  [3.0, 4.5, "One of them also reads <em>NVIDIA Cosmos</em>: who threw what, and did it land?", "No Cosmos verdict yet · identical input, identical output"],
  [4.5, 6.7, "<em>Cosmos:</em> so far, every strike was blocked.", "◆ Cosmos · 0:00–0:02 · jabs and a ROUNTREE low kick · all BLOCKED"],
  [6.7, 9.0, "<em>Cosmos:</em> PEREIRA just landed two clean jabs.", "◆ Cosmos · PEREIRA jab → torso, jab → head · LANDED"],
  [9.0, 12.6, "Frames only: ROUNTREE 99%. With Cosmos: 61%.", "Same frames · the only difference is the Cosmos verdicts"],
  [12.6, 15.8, "Watch PEREIRA's lead leg: a low kick.", "YOLO flags the kick → a short, sharp clip goes to Cosmos"],
  [15.8, 18.0, "<em>Cosmos:</em> a low kick to the leg, blocked. Not just “movement”.", "◆ Cosmos · kick clip 0:12–0:13 · PEREIRA low kick → legs · BLOCKED"],
  [18.0, 22.2, "With <em>Cosmos</em>, the estimate now favors PEREIRA.", "Frames only → ROUNTREE 98% · With Cosmos → PEREIRA 65%"],
  [22.2, 25.0, "<em>Cosmos:</em> PEREIRA lands a jab. ROUNTREE's low kick is blocked.", "◆ Cosmos · PEREIRA jab → head LANDED · ROUNTREE low kick → legs BLOCKED"],
  [25.0, 30.0, "Same frames. <b>Different answer.</b>", "Frames only → ROUNTREE · With Cosmos → PEREIRA"],
  [30.0, 32.5, "Pixels show movement. <em>Cosmos</em> tells us what it means.", ""],
  [32.5, 35.0, "The real fight: PEREIRA won by TKO in round 4.", "UFC 307 · the actual result, not a model output"],
];
// Chapter chips under the video: [start, end, label].
const CHAPTERS = [
  [0, 5, "Same input"],
  [5, 12, "Lines split"],
  [12, 18, "The low kick"],
  [18, 30, "The flip"],
];
