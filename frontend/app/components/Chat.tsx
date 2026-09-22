"use client";

import { useCallback, useEffect, useId, useRef, useState, type CSSProperties } from "react";

import {
  deleteConversation,
  deleteMemory,
  fetchConversations,
  fetchMemories,
  fetchMessages,
  renameConversation,
  streamMessage,
  type Conversation,
  type Memory,
  type Message,
  type Step,
} from "@/lib/api";

const stepStyles = {
  thinking: { label: "Thinking", badge: "bg-step-thinking/14 text-step-thinking", color: "var(--color-step-thinking)" },
  tool_call: { label: "Tool call", badge: "bg-step-call/14 text-step-call", color: "var(--color-step-call)" },
  tool_result: { label: "Tool result", badge: "bg-step-result/14 text-step-result", color: "var(--color-step-result)" },
  tool_error: { label: "Tool error", badge: "bg-step-error/14 text-step-error", color: "var(--color-step-error)" },
  tool_repeat: { label: "Repeated call", badge: "bg-step-repeat/14 text-step-repeat", color: "var(--color-step-repeat)" },
  answer: { label: "Answer", badge: "bg-step-answer/14 text-step-answer", color: "var(--color-step-answer)" },
  memory: { label: "Memory", badge: "bg-step-memory/14 text-step-memory", color: "var(--color-step-memory)" },
};

function styleForStep(kind: string) {
  if (Object.prototype.hasOwnProperty.call(stepStyles, kind)) {
    return stepStyles[kind as keyof typeof stepStyles];
  }
  return { label: "Step", badge: "bg-text-secondary/14 text-text-secondary", color: "var(--color-text-secondary)" };
}

function StepTrace({ steps }: { steps: Step[] }) {
  const [expanded, setExpanded] = useState(true);
  const traceId = useId();

  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-border-subtle bg-surface-1">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={traceId}
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-text-secondary transition-colors duration-150 hover:bg-surface-3 hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
      >
        <span aria-hidden="true" className="text-text-muted">
          {expanded ? "▾" : "▸"}
        </span>
        {expanded ? "Hide" : "Show"} reasoning ({steps.length}{" "}
        {steps.length === 1 ? "step" : "steps"})
      </button>
      <div hidden={!expanded} className="max-h-[32rem] overflow-y-auto border-t border-border-subtle">
        <ol
          id={traceId}
          hidden={!expanded}
          aria-label="Reasoning steps"
          className="step-timeline relative space-y-4 py-4 pl-8 pr-3 sm:pr-4"
        >
          {steps.map((step, index) => {
            const style = styleForStep(step.kind);
            return (
              <li
                key={step.id}
                className="trace-step relative min-w-0"
                style={{
                  "--step-color": style.color,
                  animationDelay: `${Math.min(index * 40, 400)}ms`,
                } as CSSProperties}
              >
                <span aria-hidden="true" className="step-node" />
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className="tabular-nums text-text-secondary">{index + 1}.</span>
                  <span className={`rounded-sm px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>
                    {style.label}
                  </span>
                  {step.tool_name ? (
                    <span className="break-all font-mono text-text-secondary">{step.tool_name}</span>
                  ) : null}
                </div>
                <pre
                  tabIndex={0}
                  aria-label={`Step ${index + 1}: ${style.label} detail`}
                  className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border-subtle border-l-2 border-l-[var(--step-color)] bg-surface-2 p-3 shadow-sm shadow-black/20 font-mono text-xs leading-relaxed text-text-secondary focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {step.detail}
                </pre>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function MemoryPanel({ refreshToken }: { refreshToken: number }) {
  const [expanded, setExpanded] = useState(false);
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const hasOpened = useRef(false);
  const loadInFlight = useRef(false);
  const refreshPending = useRef(false);
  const loadSequence = useRef(0);
  const deletedIds = useRef(new Set<string>());
  const panelId = useId();

  const loadMemories = useCallback(async () => {
    if (loadInFlight.current) {
      refreshPending.current = true;
      return;
    }

    loadInFlight.current = true;
    setIsLoading(true);
    do {
      refreshPending.current = false;
      const sequence = ++loadSequence.current;
      setLoadError(null);
      try {
        const facts = await fetchMemories();
        if (sequence === loadSequence.current) {
          setMemories(facts.filter((fact) => !deletedIds.current.has(fact.id)));
        }
      } catch {
        if (sequence === loadSequence.current) {
          setLoadError("Could not load remembered facts. Please try again.");
        }
      }
    } while (refreshPending.current);

    // Loading tracks the whole queue, even when a delete invalidates a result.
    loadInFlight.current = false;
    setIsLoading(false);
  }, []);

  // Opening enables refreshes immediately, including during the first load.
  useEffect(() => {
    if (hasOpened.current) void loadMemories();
  }, [refreshToken, loadMemories]);

  function togglePanel() {
    setExpanded(!expanded);
    if (!expanded) hasOpened.current = true;
    if (!expanded && memories === null && !loadInFlight.current) {
      void loadMemories();
    }
  }

  async function forgetMemory(memory: Memory) {
    setDeletingId(memory.id);
    setDeleteError(null);
    try {
      await deleteMemory(memory.id);
      // A read already in flight may carry facts saved this turn, so it is
      // filtered rather than discarded, which would lose them.
      deletedIds.current.add(memory.id);
      setMemories((current) => current?.filter((fact) => fact.id !== memory.id) ?? null);
    } catch {
      setDeleteError(`Could not forget "${memory.fact}". Please try again.`);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="max-w-2xl overflow-hidden rounded-lg border border-border-subtle bg-surface-1">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={togglePanel}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-text-secondary transition-colors duration-150 hover:bg-surface-3 hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
      >
        <span aria-hidden="true" className="text-text-muted">
          {expanded ? "▾" : "▸"}
        </span>
        Remembered facts ({memories === null ? "not loaded" : memories.length})
      </button>
      <div id={panelId} hidden={!expanded} className="space-y-3 border-t border-border-subtle p-4">
        {isLoading ? (
          <p role="status" className="text-sm text-text-secondary">Loading remembered facts...</p>
        ) : null}
        {loadError ? <p role="alert" className="break-words text-sm text-step-error">{loadError}</p> : null}
        {deleteError ? <p role="alert" className="break-words text-sm text-step-error">{deleteError}</p> : null}
        {loadError ? (
          <button
            type="button"
            onClick={() => void loadMemories()}
            disabled={isLoading}
            className="rounded-sm px-2 py-1 text-sm text-accent hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
          >
            Retry loading remembered facts
          </button>
        ) : null}
        {memories?.length === 0 ? (
          <p className="text-sm text-text-secondary">No remembered facts.</p>
        ) : null}
        {memories && memories.length > 0 ? (
          <ul aria-label="Remembered facts" className="max-h-64 space-y-3 overflow-y-auto">
            {memories.map((memory) => (
              <li key={memory.id} className="flex items-start justify-between gap-4">
                <p className="min-w-0 whitespace-pre-wrap break-words text-sm text-text-secondary">
                  {memory.fact}
                </p>
                <button
                  type="button"
                  aria-label={`Forget fact: ${memory.fact}`}
                  disabled={deletingId !== null}
                  onClick={() => void forgetMemory(memory)}
                  className="shrink-0 rounded-sm px-2 py-1 text-sm text-step-error hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                >
                  {deletingId === memory.id ? "Forgetting..." : "Forget"}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

export default function Chat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [provisional, setProvisional] = useState<Message | null>(null);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [memoryVersion, setMemoryVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [conversationAction, setConversationAction] = useState<{
    id: string;
    kind: "rename" | "delete";
  } | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [isUpdatingConversation, setIsUpdatingConversation] = useState(false);
  const sidebarDisabled = isSending || isUpdatingConversation;
  const loadSequence = useRef(0);
  const conversationSequence = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const sequence = ++loadSequence.current;
    const listSequence = ++conversationSequence.current;
    async function loadInitialConversation() {
      try {
        const available = await fetchConversations();
        if (cancelled) return;
        if (listSequence === conversationSequence.current) setConversations(available);
        if (sequence !== loadSequence.current) return;
        const latestId = available[0]?.id;
        setConversationId(latestId);
        if (latestId) {
          const history = await fetchMessages(latestId);
          if (!cancelled && sequence === loadSequence.current) setMessages(history);
        }
      } catch {
        if (!cancelled && sequence === loadSequence.current) {
          setError("Could not load conversations or history.");
        }
      } finally {
        if (!cancelled && sequence === loadSequence.current) setIsLoading(false);
      }
    }
    void loadInitialConversation();
    return () => {
      cancelled = true;
    };
  }, []);

  async function selectConversation(id?: string) {
    const sequence = ++loadSequence.current;
    setConversationId(id);
    setMessages([]);
    setDraft("");
    setError(null);
    setIsLoading(id !== undefined);
    if (id === undefined) return;
    try {
      const history = await fetchMessages(id);
      if (sequence === loadSequence.current) setMessages(history);
    } catch {
      if (sequence === loadSequence.current) setError("Could not load conversation history.");
    } finally {
      if (sequence === loadSequence.current) setIsLoading(false);
    }
  }

  async function saveConversationTitle(conversation: Conversation) {
    if (sidebarDisabled) return;
    const title = titleDraft.trim().replace(/\s+/g, " ");
    if (!title || title === (conversation.title ?? "New conversation")) {
      setConversationAction(null);
      return;
    }
    setIsUpdatingConversation(true);
    setConversationError(null);
    try {
      const updated = await renameConversation(conversation.id, title);
      setConversations((current) => current.map((item) => item.id === updated.id ? updated : item));
      setConversationAction(null);
    } catch {
      setConversationError(
        `Could not rename "${conversation.title ?? "New conversation"}". Please try again.`,
      );
    } finally {
      setIsUpdatingConversation(false);
    }
  }

  async function removeConversation(conversation: Conversation) {
    if (sidebarDisabled) return;
    setIsUpdatingConversation(true);
    setConversationError(null);
    try {
      await deleteConversation(conversation.id);
      const remaining = conversations.filter((item) => item.id !== conversation.id);
      setConversations(remaining);
      setConversationAction(null);
      if (conversation.id === conversationId) {
        void selectConversation(remaining[0]?.id);
      }
    } catch {
      setConversationError(
        `Could not delete "${conversation.title ?? "New conversation"}". Please try again.`,
      );
    } finally {
      setIsUpdatingConversation(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || sidebarDisabled || isLoading) return;

    setDraft("");
    setIsSending(true);
    setError(null);
    setProvisional({
      id: "streaming-reply", role: "assistant", content: "", created_at: "", steps: [],
    });
    try {
      await streamMessage(content, conversationId, {
        onDelta: (text) => setProvisional((current) => current ? {
          ...current, content: current.content + text,
        } : null),
        onStep: (step) => setProvisional((current) => current ? {
          ...current,
          // Text before a tool call is interim and is kept as a thinking step,
          // so clear it rather than leaving it to vanish when done arrives.
          content: step.kind === "tool_call" ? "" : current.content,
          steps: [...current.steps, { ...step, id: `streaming-step-${current.steps.length}` }],
        } : null),
        onDone: ({ conversation_id: savedId, user, reply }) => {
          setConversationId(savedId);
          setProvisional(null);
          setMessages((current) => [...current, user, reply]);
          ++conversationSequence.current;
          setConversations((current) => current.some((item) => item.id === savedId) ? current : [
            { id: savedId, title: null, created_at: user.created_at },
            ...current,
          ]);
        },
        onError: (detail) => { throw new Error(detail); },
      });
      setConversationError(null);
      try {
        setConversations(await fetchConversations());
      } catch {
        setConversationError("Could not refresh conversations.");
      }
    } catch {
      setProvisional(null);
      setError("Could not send that message.");
      setDraft(content);
    } finally {
      setIsSending(false);
      // A turn that failed may still have stored a fact before failing.
      setMemoryVersion((current) => current + 1);
    }
  }

  return (
    <div className="flex h-screen min-w-0 overflow-hidden bg-canvas text-text-primary">
      <aside className="flex w-32 shrink-0 flex-col border-r border-border-subtle bg-surface-1 p-2 min-[480px]:w-56 sm:w-64 sm:p-4">
        <button
          type="button"
          onClick={() => void selectConversation()}
          disabled={sidebarDisabled}
          className="mb-4 rounded-md border border-border-strong bg-surface-2 px-3 py-2 text-left text-sm font-medium shadow-sm shadow-black/20 transition-colors duration-150 hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
        >
          New chat
        </button>
        <nav aria-label="Conversations" className="min-h-0 space-y-1 overflow-y-auto">
          {conversations.map((conversation) => {
            const title = conversation.title ?? "New conversation";
            const action = conversationAction?.id === conversation.id ? conversationAction.kind : null;
            const actionClass = "rounded-sm px-2 py-1 text-sm text-text-secondary hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
            return (
              <div
                key={conversation.id}
                className={`conversation-row rounded-md border border-border-subtle border-l-2 p-1 ${
                  conversation.id === conversationId
                    ? "border-l-accent bg-surface-3"
                    : "border-l-transparent bg-surface-1 hover:bg-surface-2"
                }`}
              >
                <button
                  type="button"
                  aria-current={conversation.id === conversationId ? "page" : undefined}
                  disabled={sidebarDisabled}
                  onClick={() => void selectConversation(conversation.id)}
                  className={`block w-full truncate rounded-md px-3 py-2 text-left text-sm hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 ${
                    conversation.id === conversationId ? "bg-surface-3 text-text-primary" : "text-text-secondary"
                  }`}
                >
                  {title}
                </button>
                {action === "rename" ? (
                  <form
                    className="space-y-1"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void saveConversationTitle(conversation);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Escape" && !sidebarDisabled) setConversationAction(null);
                    }}
                  >
                    <input
                      aria-label={`Title for conversation: ${title}`}
                      autoFocus
                      value={titleDraft}
                      maxLength={200}
                      disabled={sidebarDisabled}
                      onChange={(event) => setTitleDraft(event.target.value)}
                      className="w-full min-w-0 rounded-sm border border-border-strong bg-surface-2 px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                    />
                    <div className="flex flex-wrap gap-1">
                      <button
                        type="submit"
                        aria-label={`Save title for conversation: ${title}`}
                        disabled={sidebarDisabled}
                        className={actionClass}
                      >
                        {isUpdatingConversation ? "Saving..." : "Save"}
                      </button>
                      <button
                        type="button"
                        aria-label={`Cancel rename conversation: ${title}`}
                        disabled={sidebarDisabled}
                        onClick={() => setConversationAction(null)}
                        className={actionClass}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : action === "delete" ? (
                  <div className="space-y-1">
                    <p className="break-words px-2 text-sm text-text-secondary">
                      Permanently delete &quot;{title}&quot; and all its messages? This cannot be undone.
                    </p>
                    <div className="flex flex-wrap gap-1">
                      <button
                        type="button"
                        aria-label={`Confirm permanently delete conversation and all its messages: ${title}`}
                        disabled={sidebarDisabled}
                        onClick={() => void removeConversation(conversation)}
                        className={actionClass}
                      >
                        {isUpdatingConversation ? "Deleting..." : "Confirm"}
                      </button>
                      <button
                        type="button"
                        aria-label={`Cancel delete conversation: ${title}`}
                        disabled={sidebarDisabled}
                        onClick={() => setConversationAction(null)}
                        className={actionClass}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    <button
                      type="button"
                      aria-label={`Rename conversation: ${title}`}
                      disabled={sidebarDisabled}
                      onClick={() => {
                        setConversationError(null);
                        setTitleDraft(title);
                        setConversationAction({ id: conversation.id, kind: "rename" });
                      }}
                      className={actionClass}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete conversation: ${title}`}
                      disabled={sidebarDisabled}
                      onClick={() => {
                        setConversationError(null);
                        setConversationAction({ id: conversation.id, kind: "delete" });
                      }}
                      className={actionClass}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </nav>
        {conversationError ? <p role="alert" className="mt-3 text-sm text-step-error">{conversationError}</p> : null}
      </aside>
      <main className="chat-main flex min-w-0 flex-1 flex-col">
        <header className="chat-header relative border-b border-border-subtle bg-surface-1 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">Loupe</h1>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-6 sm:px-6 [overflow-wrap:anywhere]">
          <MemoryPanel refreshToken={memoryVersion} />
          {isLoading ? <p className="text-sm text-text-secondary">Loading conversation...</p> : null}
          {messages.length === 0 && !provisional && !error && !isLoading ? (
            <p className="text-sm text-text-secondary">Start the conversation below.</p>
          ) : null}
          {[...messages, ...(provisional ? [provisional] : [])].map((message) => (
            <div
              key={message.id}
              data-streaming={message === provisional && isSending}
              className={`max-w-2xl rounded-lg border border-border-subtle p-3 shadow-sm shadow-black/20 sm:p-4 ${
                message.role === "user" ? "message-user border-l-2 border-l-accent" : "bg-surface-2"
              }`}
            >
              <p className="mb-2 text-xs uppercase tracking-wide text-text-secondary">
                {message.role}
              </p>
              <p className="whitespace-pre-wrap text-base leading-relaxed text-text-primary">{message.content}</p>
              {message === provisional && !message.content && message.steps.length === 0 ? (
                <p role="status" className="thinking-indicator text-sm">Thinking...</p>
              ) : null}
              {message.role === "assistant" && message.steps.length > 0 ? (
                <StepTrace steps={message.steps} />
              ) : null}
            </div>
          ))}
          {error ? <p className="text-sm text-step-error">{error}</p> : null}
        </div>

        <form onSubmit={handleSubmit} className="border-t border-border-subtle bg-surface-1 px-3 py-4 sm:px-6">
          <div className="flex flex-wrap gap-3">
            <input
              aria-label="Message"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Ask something"
              className="composer-input min-w-0 flex-1 rounded-md border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary focus:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
            <button
              type="submit"
              disabled={sidebarDisabled || isLoading}
              className="send-button rounded-md bg-accent px-4 py-2 text-sm font-medium text-canvas shadow-sm shadow-black/20 hover:bg-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
