import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EVENTS,
  QUOTES,
  receivedCounts,
  visibleEvents,
  quoteAt,
} from "./index";
test("replaying backwards reconstructs heat; blocks, unknowns and misses add no contact", () => {
  assert.deepEqual(receivedCounts(visibleEvents(EVENTS, 15), "A"), {
    head: 1,
    body: 1,
    leg: 1,
  });
  assert.deepEqual(receivedCounts(visibleEvents(EVENTS, 15), "B"), {
    head: 1,
    body: 1,
    leg: 1,
  });
  assert.deepEqual(receivedCounts(visibleEvents(EVENTS, 4.5), "B"), {
    head: 1,
    body: 0,
    leg: 0,
  });
  assert.deepEqual(receivedCounts(visibleEvents(EVENTS, 0), "A"), {
    head: 0,
    body: 0,
    leg: 0,
  });
});
test("duplicate revisions count once and withdrawal removes old contribution", () => {
  const event = EVENTS[0];
  assert.equal(receivedCounts(visibleEvents([event, event], 5), "B").head, 1);
  const withdrawn = { ...event, revision: 2, status: "withdrawn" as const };
  assert.equal(
    receivedCounts(visibleEvents([withdrawn, event], 5), "B").head,
    0,
  );
});
test("market snapshots are discrete, use no future values and update independently of hits", () => {
  assert.deepEqual(quoteAt(1.1), QUOTES[0]);
  assert.deepEqual(quoteAt(1.8), QUOTES[1]);
  assert.deepEqual(quoteAt(6), QUOTES[3]);
});
