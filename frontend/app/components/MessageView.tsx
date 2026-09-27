"use client";

import { useId, useState, type CSSProperties, type ReactNode } from "react";

import type { Message, Step } from "@/lib/api";

const stepStyles = {
  thinking: { label: "Thinking", badge: "text-step-thinking", color: "var(--color-step-thinking)" },
  tool_call: { label: "Tool call", badge: "text-step-call", color: "var(--color-step-call)" },
  tool_result: { label: "Tool result", badge: "text-step-result", color: "var(--color-step-result)" },
  tool_error: { label: "Tool error", badge: "text-step-error", color: "var(--color-step-error)" },
  tool_repeat: { label: "Repeated call", badge: "text-step-repeat", color: "var(--color-step-repeat)" },
  answer: { label: "Answer", badge: "text-step-answer", color: "var(--color-step-answer)" },
  memory: { label: "Memory", badge: "text-step-memory", color: "var(--color-step-memory)" },
};

export function styleForStep(kind: string) {
  if (Object.prototype.hasOwnProperty.call(stepStyles, kind)) {
    return stepStyles[kind as keyof typeof stepStyles];
  }
  return { label: "Step", badge: "text-text-secondary", color: "var(--color-text-secondary)" };
}

function StepTrace({ steps, caption, captionStep, replay }: {
  steps: Step[];
  caption?: ReactNode;
  captionStep?: number;
  replay?: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const traceId = useId();

  return (
    <div className="trace-panel">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={traceId}
        disabled={replay}
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-text-secondary transition-colors duration-150 hover:bg-surface-3 hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
      >
        <span aria-hidden="true" className="text-text-muted">
          {expanded ? "▾" : "▸"}
        </span>
        {expanded ? "Hide" : "Show"} reasoning ({steps.length}{" "}
        {steps.length === 1 ? "step" : "steps"})
      </button>
      <div hidden={!expanded} className={replay ? "trace-scroll" : "trace-scroll max-h-[32rem] overflow-y-auto"}>
        <ol
          id={traceId}
          hidden={!expanded}
          aria-label="Reasoning steps"
          className="step-timeline"
        >
          {steps.map((step, index) => {
            const style = styleForStep(step.kind);
            return (
              <li
                key={step.id}
                data-caption-anchor={captionStep === index || undefined}
                className="trace-step glass-surface relative min-w-0"
                style={{
                  "--step-color": style.color,
                  animationDelay: `${Math.min(index * 80, 320)}ms`,
                } as CSSProperties}
              >
                <span aria-hidden="true" className="step-node" />
                <div className="step-kind flex flex-wrap items-center gap-x-2">
                  <span className="sr-only">{index + 1}.</span>
                  <span className={style.badge}>
                    {style.label}
                  </span>
                  {step.tool_name ? (
                    <span className="break-all">{step.tool_name}</span>
                  ) : null}
                </div>
                <pre
                  tabIndex={0}
                  aria-label={`Step ${index + 1}: ${style.label} detail`}
                  className="step-detail max-h-48 overflow-auto whitespace-pre-wrap break-words focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {step.detail}
                </pre>
                {captionStep === index ? caption : null}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

export default function MessageView({ message, streaming = false, replay = false, caption, captionStep }: {
  message: Message;
  streaming?: boolean;
  replay?: boolean;
  caption?: ReactNode;
  captionStep?: number;
}) {
  return (
    <div
      data-streaming={streaming}
      className={`max-w-2xl min-w-0 ${message.role === "user" ? "message-user" : "message-assistant"}`}
    >
      <p className="sr-only">{message.role}</p>
      {streaming && !message.content && message.steps.length === 0 ? (
        <p role="status" className="thinking-indicator text-sm">Thinking...</p>
      ) : null}
      {message.role === "assistant" && message.steps.length > 0 ? (
        <StepTrace steps={message.steps} replay={replay} caption={caption} captionStep={captionStep} />
      ) : null}
      {message.content ? (
        <div className="message-content relative" data-caption-anchor={caption && captionStep === undefined ? true : undefined}>
          <p className={message.role === "user" ? "question whitespace-pre-wrap" : "answer-block whitespace-pre-wrap"}>
            {message.content}
          </p>
          {captionStep === undefined ? caption : null}
        </div>
      ) : null}
    </div>
  );
}
