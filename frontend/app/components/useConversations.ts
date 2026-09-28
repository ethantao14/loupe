import { useEffect, useRef, useState } from "react";

import {
  deleteConversation, fetchConversations, fetchMessages, renameConversation,
  type Conversation, type Message, type SendResult,
} from "@/lib/api";

export function useConversations({ disabled, setDraft, setError, setQuotaReached }: {
  disabled: boolean;
  setDraft: (draft: string) => void;
  setError: (error: string | null) => void;
  setQuotaReached: (reached: boolean) => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [isUpdatingConversation, setIsUpdatingConversation] = useState(false);
  const loadSequence = useRef(0);
  const conversationSequence = useRef(0);
  const sidebarDisabled = disabled || isUpdatingConversation;

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
  }, [setError]);

  async function selectConversation(id?: string) {
    const sequence = ++loadSequence.current;
    setConversationId(id);
    setMessages([]);
    setDraft("");
    setError(null);
    setQuotaReached(false);
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

  async function saveConversationTitle(conversation: Conversation, titleDraft: string) {
    if (sidebarDisabled) return false;
    const title = titleDraft.trim().replace(/\s+/g, " ");
    if (!title || title === (conversation.title ?? "New conversation")) {
      return true;
    }
    setIsUpdatingConversation(true);
    setConversationError(null);
    try {
      const updated = await renameConversation(conversation.id, title);
      setConversations((current) => current.map((item) => item.id === updated.id ? updated : item));
      return true;
    } catch {
      setConversationError(
        `Could not rename "${conversation.title ?? "New conversation"}". Please try again.`,
      );
      return false;
    } finally {
      setIsUpdatingConversation(false);
    }
  }

  async function removeConversation(conversation: Conversation) {
    if (sidebarDisabled) return false;
    setIsUpdatingConversation(true);
    setConversationError(null);
    try {
      await deleteConversation(conversation.id);
      const remaining = conversations.filter((item) => item.id !== conversation.id);
      setConversations(remaining);
      if (conversation.id === conversationId) {
        void selectConversation(remaining[0]?.id);
      }
      return true;
    } catch {
      setConversationError(
        `Could not delete "${conversation.title ?? "New conversation"}". Please try again.`,
      );
      return false;
    } finally {
      setIsUpdatingConversation(false);
    }
  }

  function completeTurn({ conversation_id: savedId, user, reply }: SendResult) {
    setConversationId(savedId);
    setMessages((current) => [...current, user, reply]);
    ++conversationSequence.current;
    setConversations((current) => current.some((item) => item.id === savedId) ? current : [
      { id: savedId, title: null, created_at: user.created_at },
      ...current,
    ]);
  }

  async function refreshConversations() {
    setConversationError(null);
    try {
      setConversations(await fetchConversations());
    } catch {
      setConversationError("Could not refresh conversations.");
    }
  }

  return {
    conversations, conversationId, messages, isLoading, conversationError,
    isUpdatingConversation, sidebarDisabled, selectConversation,
    saveConversationTitle, removeConversation, setConversationError,
    completeTurn, refreshConversations,
  };
}
