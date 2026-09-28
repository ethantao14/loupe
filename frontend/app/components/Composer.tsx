import type { RefObject } from "react";

const MAX_MESSAGE_CHARS = 2000;

export default function Composer({ hidden, composerRef, draft, setDraft, sidebarDisabled, isLoading, sendContent }: {
  hidden: boolean;
  composerRef: RefObject<HTMLInputElement | null>;
  draft: string;
  setDraft: (draft: string) => void;
  sidebarDisabled: boolean;
  isLoading: boolean;
  sendContent: (content: string) => Promise<void>;
}) {
  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    await sendContent(draft.trim());
  }

  return (
    <form hidden={hidden} onSubmit={handleSubmit} className="composer glass-surface shrink-0 border-t border-glass-border px-3 py-4 sm:px-7">
      <div className="flex max-w-2xl flex-wrap gap-3">
        <input
          ref={composerRef}
          aria-label="Message"
          maxLength={MAX_MESSAGE_CHARS}
          aria-describedby={draft.length >= MAX_MESSAGE_CHARS - 200 ? "message-character-count" : undefined}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask something"
          className="composer-input min-w-0 flex-1 rounded-md border border-glass-border bg-glass px-3 py-3 text-sm text-text-primary placeholder:text-text-secondary focus:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
        <button
          type="submit"
          disabled={sidebarDisabled || isLoading}
          className="send-button rounded-md bg-accent px-4 py-2 text-sm font-medium text-canvas shadow-sm shadow-black/20 hover:bg-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
        >
          Send
        </button>
      </div>
      {draft.length >= MAX_MESSAGE_CHARS - 200 ? (
        <p id="message-character-count" className="mt-2 max-w-2xl text-right text-xs text-text-muted">
          {draft.length} / {MAX_MESSAGE_CHARS}
        </p>
      ) : null}
    </form>
  );
}
