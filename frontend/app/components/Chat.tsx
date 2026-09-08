"use client";

import { useEffect, useId, useState } from "react";

import { fetchMessages, sendMessage, type Message, type Step } from "@/lib/api";

const stepStyles = {
  thinking: { label: "Thinking", badge: "bg-violet-400/10 text-violet-300" },
  tool_call: { label: "Tool call", badge: "bg-sky-400/10 text-sky-300" },
  tool_result: { label: "Tool result", badge: "bg-amber-400/10 text-amber-300" },
  answer: { label: "Answer", badge: "bg-emerald-400/10 text-emerald-300" },
  memory: { label: "Memory", badge: "bg-rose-400/10 text-rose-300" },
};

function styleForStep(kind: string) {
  if (Object.prototype.hasOwnProperty.call(stepStyles, kind)) {
    return stepStyles[kind as keyof typeof stepStyles];
  }
  return { label: "Step", badge: "bg-neutral-400/10 text-neutral-300" };
}

function StepTrace({ steps }: { steps: Step[] }) {
  const [expanded, setExpanded] = useState(false);
  const traceId = useId();

  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/50">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={traceId}
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-neutral-300 transition-colors hover:bg-neutral-800/60 hover:text-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-sky-400"
      >
        <span aria-hidden="true" className="text-neutral-500">
          {expanded ? "▾" : "▸"}
        </span>
        {expanded ? "Hide" : "Show"} reasoning ({steps.length}{" "}
        {steps.length === 1 ? "step" : "steps"})
      </button>
      <ol
        id={traceId}
        hidden={!expanded}
        aria-label="Reasoning steps"
        className="max-h-[32rem] space-y-4 overflow-y-auto border-t border-neutral-800 p-4"
      >
        {steps.map((step, index) => {
          const style = styleForStep(step.kind);
          return (
            <li key={step.id} className="min-w-0">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="tabular-nums text-neutral-500">{index + 1}.</span>
                <span className={`rounded px-2 py-1 font-medium ${style.badge}`}>
                  {style.label}
                </span>
                {step.tool_name ? (
                  <span className="break-all font-mono text-neutral-300">{step.tool_name}</span>
                ) : null}
              </div>
              <pre
                tabIndex={0}
                aria-label={`Step ${index + 1}: ${style.label} detail`}
                className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-neutral-950 p-3 font-mono text-xs leading-relaxed text-neutral-300 focus-visible:outline-2 focus-visible:outline-sky-400"
              >
                {step.detail}
              </pre>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMessages()
      .then((history) => {
        if (!cancelled) setMessages(history);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load conversation history.");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || isSending || isLoading) return;

    setDraft("");
    setIsSending(true);
    setError(null);
    try {
      const { user, reply } = await sendMessage(content);
      setMessages((current) => [...current, user, reply]);
    } catch {
      setError("Could not send that message.");
      setDraft(content);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-100">
      <header className="border-b border-neutral-800 px-6 py-4">
        <h1 className="text-lg font-semibold">Loupe</h1>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-6">
        {messages.length === 0 && !error ? (
          <p className="text-neutral-500">Start the conversation below.</p>
        ) : null}
        {messages.map((message) => (
          <div key={message.id} className="max-w-2xl">
            <p className="mb-1 text-xs uppercase tracking-wide text-neutral-500">
              {message.role}
            </p>
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.role === "assistant" && message.steps.length > 0 ? (
              <StepTrace steps={message.steps} />
            ) : null}
          </div>
        ))}
        {isSending ? <p className="text-neutral-500">Thinking...</p> : null}
        {error ? <p className="text-red-400">{error}</p> : null}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-neutral-800 px-6 py-4">
        <div className="flex gap-3">
          <input
            aria-label="Message"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask something"
            className="flex-1 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 outline-none focus:border-neutral-500"
          />
          <button
            type="submit"
            disabled={isSending || isLoading}
            className="rounded-md bg-neutral-100 px-4 py-2 font-medium text-neutral-900 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
