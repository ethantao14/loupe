"use client";

import { useEffect, useState } from "react";

import { fetchMessages, sendMessage, type Message } from "@/lib/api";

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMessages()
      .then(setMessages)
      .catch(() => setError("Could not load conversation history."));
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || isSending) return;

    setDraft("");
    setIsSending(true);
    setError(null);
    try {
      await sendMessage(content);
      setMessages(await fetchMessages());
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
            disabled={isSending}
            className="rounded-md bg-neutral-100 px-4 py-2 font-medium text-neutral-900 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
