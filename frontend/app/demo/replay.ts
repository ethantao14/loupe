import type { Message, SendResult, Step, StreamStep } from "@/lib/api";

import recording from "./replays.json";

export const stepKinds = {
  memory: true,
  thinking: true,
  tool_call: true,
  tool_result: true,
  tool_error: true,
  tool_repeat: true,
  answer: true,
} satisfies Record<Step["kind"], boolean>;

export type ReplayEvent = { at_ms: number } & (
  | { event: "step"; data: StreamStep }
  | { event: "delta"; data: { text: string } }
  | { event: "done"; data: SendResult }
);

export type Replay = {
  id: string;
  question: string;
  events: ReplayEvent[];
};

export type ReplayId = "memory-and-fetch" | "run-python" | "failure-recovery";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStep(value: unknown): value is StreamStep {
  return isRecord(value)
    && typeof value.kind === "string"
    && Object.hasOwn(stepKinds, value.kind)
    && (value.tool_name === null || typeof value.tool_name === "string")
    && typeof value.detail === "string";
}

function isMessage(value: unknown): value is Message {
  return isRecord(value)
    && typeof value.id === "string"
    && (value.role === "user" || value.role === "assistant")
    && typeof value.content === "string"
    && typeof value.created_at === "string"
    && Array.isArray(value.steps)
    && value.steps.every((step: unknown) => isStep(step) && "id" in step && typeof step.id === "string");
}

function isEvent(value: unknown): value is ReplayEvent {
  if (!isRecord(value) || typeof value.at_ms !== "number"
    || !Number.isFinite(value.at_ms) || value.at_ms < 0) return false;
  if (value.event === "step") return isStep(value.data);
  if (value.event === "delta") return isRecord(value.data) && typeof value.data.text === "string";
  if (value.event === "done") {
    return isRecord(value.data)
      && typeof value.data.conversation_id === "string"
      && isMessage(value.data.user) && value.data.user.role === "user"
      && isMessage(value.data.reply) && value.data.reply.role === "assistant";
  }
  return false;
}

function isReplay(value: unknown): value is Replay {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.question !== "string"
    || !Array.isArray(value.events)) return false;
  const events: unknown[] = value.events;
  if (!events.every(isEvent) || events.length === 0) return false;
  return events.every((event, index) => (
    (index === 0 || event.at_ms >= events[index - 1].at_ms)
    && (event.event === "done") === (index === events.length - 1)
  ));
}

export function loadReplays(value: unknown): Replay[] {
  if (!Array.isArray(value) || !value.every(isReplay)) {
    throw new Error("Invalid replay recording.");
  }
  const replays: Replay[] = value;
  if (new Set(replays.map((replay) => replay.id)).size !== replays.length) {
    throw new Error("Replay ids must be unique.");
  }
  return replays;
}

export const replays = loadReplays(recording);

export function getReplay(id: ReplayId): Replay {
  const replay = replays.find((item) => item.id === id);
  if (!replay) throw new Error(`Missing replay: ${id}`);
  return replay;
}

export function playbackSchedule(replay: Replay) {
  let previous = 0;
  let elapsed = 0;
  return replay.events.map((event) => {
    const delay_ms = Math.min(Math.max(0, event.at_ms - previous), event.event === "delta" ? 60 : 900);
    previous = event.at_ms;
    elapsed += delay_ms;
    return { event, delay_ms, at_ms: elapsed };
  });
}
