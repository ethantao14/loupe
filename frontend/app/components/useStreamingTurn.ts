import { useState } from "react";

import { MessageRequestError, streamMessage, type Message } from "@/lib/api";

import { useConversations } from "./useConversations";

export function useStreamingTurn(replaying: boolean) {
  const [provisional, setProvisional] = useState<Message | null>(null);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [memoryVersion, setMemoryVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [quotaReached, setQuotaReached] = useState(false);
  const conversation = useConversations({
    disabled: isSending || replaying, setDraft, setError, setQuotaReached,
  });
  const { sidebarDisabled, isLoading, conversationId } = conversation;

  async function sendContent(content: string) {
    if (!content || sidebarDisabled || isLoading) return;

    setDraft("");
    setIsSending(true);
    setError(null);
    setQuotaReached(false);
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
        onDone: (result) => {
          setProvisional(null);
          conversation.completeTurn(result);
        },
        onError: (detail) => { throw new Error(detail); },
      });
      await conversation.refreshConversations();
    } catch (cause) {
      setProvisional(null);
      setError(cause instanceof MessageRequestError ? cause.message : "Could not send that message.");
      setQuotaReached(cause instanceof MessageRequestError && cause.status === 429);
      setDraft(content);
    } finally {
      setIsSending(false);
      // A turn that failed may still have stored a fact before failing.
      setMemoryVersion((current) => current + 1);
    }
  }

  return {
    conversation, provisional, draft, setDraft, isSending, memoryVersion,
    error, quotaReached, sendContent,
  };
}
