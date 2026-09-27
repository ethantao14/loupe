import { describe, expect, it } from "vitest";

import type { Step } from "@/lib/api";

import { captionForStep, stepCaptions } from "./captions";
import { getReplay, loadReplays, playbackSchedule, replays, stepKinds, type Replay } from "./replay";

const delta = (at_ms: number, text: string) => ({ at_ms, event: "delta" as const, data: { text } });

describe("playback schedule", () => {
  it("clamps gaps, including the first event, without changing order or data", () => {
    const replay: Replay = {
      id: "test", question: "Question", events: [
        { at_ms: 3000, event: "step", data: { kind: "thinking", tool_name: null, detail: "Planning" } },
        delta(8000, "Hello"),
        delta(8000, " there"),
        delta(8020, "."),
        { at_ms: 15000, event: "step", data: { kind: "answer", tool_name: null, detail: "Hello there." } },
      ],
    };
    const original = structuredClone(replay);
    const schedule = playbackSchedule(replay);
    expect(schedule.map((item) => item.delay_ms)).toEqual([900, 60, 0, 20, 900]);
    expect(schedule.map((item) => item.at_ms)).toEqual([900, 960, 960, 980, 1880]);
    expect(schedule.map((item) => item.event)).toEqual(replay.events);
    schedule.forEach((item, index) => expect(item.event).toBe(replay.events[index]));
    expect(replay).toEqual(original);
  });

  it("handles empty schedules and never creates negative delays", () => {
    expect(playbackSchedule({ id: "empty", question: "", events: [] })).toEqual([]);
    const schedule = playbackSchedule({ id: "backward", question: "", events: [delta(20, "a"), delta(10, "b")] });
    expect(schedule.map((item) => item.delay_ms)).toEqual([20, 0]);
  });
});

describe("replay loading", () => {
  it("loads the three recordings with a final done payload", () => {
    expect(replays.map((replay) => replay.id)).toEqual(["memory-and-fetch", "run-python", "failure-recovery"]);
    replays.forEach((replay) => expect(replay.events.at(-1)?.event).toBe("done"));
  });

  it.each([null, {}, [null], [{ id: "bad", question: "", events: [] }]])("rejects malformed recordings: %j", (value) => {
    expect(() => loadReplays(value)).toThrow("Invalid replay recording.");
  });

  it("rejects unknown kinds, invalid done messages, duplicate ids, and out-of-order events", () => {
    const replay = getReplay("run-python");
    expect(() => loadReplays([{ ...replay, events: [
      { at_ms: 0, event: "step", data: { kind: "unknown", tool_name: null, detail: "" } },
      replay.events.at(-1),
    ] }])).toThrow();
    expect(() => loadReplays([{ ...replay, events: [{ at_ms: 0, event: "done", data: {} }] }])).toThrow();
    expect(() => loadReplays([replay, replay])).toThrow("Replay ids must be unique.");
    expect(() => loadReplays([{ ...replay, events: [...replay.events].reverse() }])).toThrow();
  });
});

describe("captions", () => {
  it("explains every Step kind", () => {
    const kinds = Object.keys(stepKinds) as Step["kind"][];
    expect(Object.keys(stepCaptions).sort()).toEqual(kinds.sort());
    kinds.forEach((kind) => expect(captionForStep({ kind, tool_name: null })).toMatch(/\byou/i));
  });

  it("explains named tools and handles a new tool without relying on step position", () => {
    expect(captionForStep({ kind: "tool_call", tool_name: "fetch_url" })).toContain("fetch_url reads a web page");
    expect(captionForStep({ kind: "tool_call", tool_name: "run_python" })).toContain("run_python runs code for you in a locked-down container");
    expect(captionForStep({ kind: "tool_call", tool_name: "another_tool" })).toContain("another_tool");
  });
});
