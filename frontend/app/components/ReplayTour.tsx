"use client";

import { useEffect, useMemo, useReducer, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";

import type { Message } from "@/lib/api";

import { captionForStep, closingCaption, introCaption } from "../demo/captions";
import { getReplay, playbackSchedule, type Replay, type ReplayEvent, type ReplayId } from "../demo/replay";
import MessageView, { styleForStep } from "./MessageView";

function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (notify) => {
      const media = window.matchMedia?.(query);
      media?.addEventListener("change", notify);
      return () => media?.removeEventListener("change", notify);
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  );
}

function playbackFrames(replay: Replay, reducedMotion: boolean) {
  const schedule = playbackSchedule(replay);
  const frames: { event: ReplayEvent; delay_ms: number }[] = [];
  for (let index = 0; index < schedule.length; index++) {
    const item = schedule[index];
    if (item.event.event !== "delta") {
      frames.push({ ...item, delay_ms: reducedMotion ? 0 : item.delay_ms });
      continue;
    }
    let text = item.event.data.text;
    let duration = item.delay_ms;
    // Join adjacent chunks so a word split across stream events stays whole.
    while (schedule[index + 1]?.event.event === "delta") {
      const next = schedule[++index];
      if (next.event.event === "delta") text += next.event.data.text;
      duration += next.delay_ms;
    }
    const words = reducedMotion ? [text] : text.match(/\s*\S+|\s+$/g) ?? [];
    words.forEach((word, wordIndex) => frames.push({
      event: { event: "delta", at_ms: item.event.at_ms, data: { text: word } },
      delay_ms: reducedMotion ? 0 : wordIndex === 0 ? item.delay_ms
        : Math.min(60, Math.max(30, duration / words.length)),
    }));
  }
  return frames;
}

type Playback = {
  index: number;
  user: Message;
  reply: Message;
  caption: "question" | "answer" | number | null;
  complete: boolean;
};

type Action = { type: "continue" } | { type: "event"; event: ReplayEvent; narrated: boolean };

function advance(state: Playback, action: Action): Playback {
  if (action.type === "continue") return { ...state, caption: null };
  const { event, narrated } = action;
  const next = { ...state, index: state.index + 1 };
  switch (event.event) {
    case "step":
      return {
        ...next,
        caption: narrated ? state.reply.steps.length : null,
        reply: {
          ...state.reply,
          content: event.data.kind === "tool_call" ? "" : state.reply.content,
          steps: [...state.reply.steps, { ...event.data, id: `replay-step-${state.index}` }],
        },
      };
    case "delta":
      return { ...next, reply: { ...state.reply, content: state.reply.content + event.data.text } };
    case "done":
      return {
        ...next, user: event.data.user, reply: event.data.reply,
        complete: true, caption: narrated ? "answer" : null,
      };
  }
}

export default function ReplayTour({ replayId, onClose, memoryPanel }: {
  replayId: ReplayId;
  onClose: () => void;
  memoryPanel: ReactNode;
}) {
  const replay = getReplay(replayId);
  const narrated = replayId === "memory-and-fetch";
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const narrow = useMediaQuery("(max-width: 767px)");
  // A playback keeps its initial pacing if the system preference changes mid-turn.
  const [initialMotion] = useState(reducedMotion);
  const frames = useMemo(() => playbackFrames(replay, initialMotion), [replay, initialMotion]);
  const [state, dispatch] = useReducer(advance, { replay, narrated }, ({ replay, narrated }): Playback => ({
    index: 0,
    user: { id: "replay-question", role: "user", content: replay.question, created_at: "", steps: [] },
    reply: { id: "replay-reply", role: "assistant", content: "", created_at: "", steps: [] },
    caption: narrated ? "question" : null,
    complete: false,
  }));
  const continueRef = useRef<HTMLButtonElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const paused = state.caption !== null;

  useEffect(() => {
    if (paused || state.complete) return;
    const frame = frames[state.index];
    if (!frame) return;
    const timer = window.setTimeout(() => {
      dispatch({ type: "event", event: frame.event, narrated });
    }, frame.delay_ms);
    return () => window.clearTimeout(timer);
  }, [frames, narrated, paused, state.complete, state.index]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (paused) continueRef.current?.focus({ preventScroll: true });
    const scroll = scrollRef.current;
    const anchor = scroll?.querySelector<HTMLElement>('[data-caption-anchor="true"]');
    if (anchor) anchor.scrollIntoView?.({ block: "nearest", behavior: "instant" });
    else if (scroll) scroll.scrollTop = scroll.scrollHeight;
  }, [paused, state.caption, state.index, narrow]);

  const step = typeof state.caption === "number" ? state.reply.steps[state.caption] : undefined;
  const style = step ? styleForStep(step.kind) : {
    label: "", color: state.caption === "question" ? "var(--color-accent)" : "var(--color-step-answer)",
  };
  const caption = step ? { title: style.label, text: captionForStep(step) }
    : state.caption === "question" ? introCaption : closingCaption;
  const captionCard = paused ? (
    <div
      className="tour-caption glass-surface"
      style={{ "--step-color": style.color } as CSSProperties}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <h2>{caption.title}</h2>
      <p>{caption.text}</p>
    </div>
  ) : null;
  const progress = state.complete ? 100 : Math.round(state.index / frames.length * 100);
  const memoryVisible = state.reply.steps.some((item) => item.kind === "memory");

  return (
    <section className="replay-view" aria-label={narrated ? "Narrated replay" : "Example replay"}>
      <div ref={scrollRef} className="replay-scroll message-list space-y-6 px-3 pb-7 pt-1 sm:px-7">
        <div inert data-replay-dimmed={!memoryVisible} className="replay-memory">
          {memoryPanel}
        </div>
        {!narrated ? (
          <p className="replay-legend">
            <span className="text-step-memory">Pink: memory</span>{" · "}
            <span className="text-step-thinking">Purple: thinking</span>{" · "}
            <span className="text-step-call">Blue: tool call</span>{" · "}
            <span className="text-step-result">Green: result</span>{" · "}
            <span className="text-step-error">Red: error</span>{" · "}
            <span className="text-step-repeat">Amber: repeat blocked</span>{" · "}
            <span className="text-step-answer">Light: answer</span>
          </p>
        ) : null}
        <div className={narrated ? "replay-exchange replay-narrated space-y-6" : "replay-exchange space-y-6"}>
          <MessageView message={state.user} replay caption={!narrow && state.caption === "question" ? captionCard : null} />
          <MessageView
            message={state.reply}
            replay
            streaming={!state.complete && !paused && !reducedMotion}
            caption={!narrow && state.caption !== "question" ? captionCard : null}
            captionStep={typeof state.caption === "number" ? state.caption : undefined}
          />
        </div>
      </div>
      <div className="replay-controls">
        {narrow ? captionCard : null}
        <div className="replay-player glass-surface">
          <span>{paused ? "Paused" : state.complete ? "Replay complete" : "Replaying a real turn"}</span>
          <div className="replay-progress" role="progressbar" aria-label="Replay progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
            <span style={{ width: `${progress}%` }} />
          </div>
          {paused ? (
            <button
              ref={continueRef}
              type="button"
              className="send-button tour-continue"
              onClick={() => state.complete ? onClose() : dispatch({ type: "continue" })}
            >
              {state.complete ? "Try it yourself" : "Continue"}
            </button>
          ) : null}
          <button type="button" className="tour-text-button" onClick={onClose}>
            {narrated ? "Skip tour" : "Close"}
          </button>
        </div>
      </div>
    </section>
  );
}
