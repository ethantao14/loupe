import { useState, type RefObject } from "react";

import type { Conversation } from "@/lib/api";

import type { useConversations } from "./useConversations";

type ConversationModel = ReturnType<typeof useConversations>;

function ConversationRow({ conversation, model, activeId, activate, onSelect }: {
  conversation: Conversation;
  model: ConversationModel;
  activeId: string | null;
  activate: (id: string) => void;
  onSelect: () => void;
}) {
  const [action, setAction] = useState<"rename" | "delete" | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const { conversationId, sidebarDisabled, isUpdatingConversation, selectConversation,
    saveConversationTitle, removeConversation } = model;
  const title = conversation.title ?? "New conversation";
  const visibleAction = activeId === conversation.id ? action : null;
  const actionClass = "rounded-sm px-2 py-1 text-sm text-text-secondary hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";

  async function saveTitle() {
    if (await saveConversationTitle(conversation, titleDraft)) setAction(null);
  }

  async function remove() {
    if (await removeConversation(conversation)) setAction(null);
  }

  return (
    <div
      className={`conversation-row rounded-md border border-glass-border border-l-2 p-1 ${
        conversation.id === conversationId
          ? "conversation-selected border-l-accent"
          : "border-l-transparent hover:bg-glass"
      }`}
    >
      <button
        type="button"
        aria-current={conversation.id === conversationId ? "page" : undefined}
        disabled={sidebarDisabled}
        onClick={() => {
          void selectConversation(conversation.id);
          onSelect();
        }}
        className={`block w-full truncate rounded-md px-3 py-2 text-left text-sm hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 ${
          conversation.id === conversationId ? "text-text-primary" : "text-text-secondary"
        }`}
      >
        {title}
      </button>
      {visibleAction === "rename" ? (
        <form
          className="space-y-1"
          onSubmit={(event) => {
            event.preventDefault();
            void saveTitle();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !sidebarDisabled) setAction(null);
          }}
        >
          <input
            aria-label={`Title for conversation: ${title}`}
            autoFocus
            value={titleDraft}
            maxLength={200}
            disabled={sidebarDisabled}
            onChange={(event) => setTitleDraft(event.target.value)}
            className="w-full min-w-0 rounded-sm border border-border-strong bg-surface-2 px-2 py-1 text-base focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 md:text-sm"
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
              onClick={() => setAction(null)}
              className={actionClass}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : visibleAction === "delete" ? (
        <div className="space-y-1">
          <p className="break-words px-2 text-sm text-text-secondary">
            Permanently delete &quot;{title}&quot; and all its messages? This cannot be undone.
          </p>
          <div className="flex flex-wrap gap-1">
            <button
              type="button"
              aria-label={`Confirm permanently delete conversation and all its messages: ${title}`}
              disabled={sidebarDisabled}
              onClick={() => void remove()}
              className={actionClass}
            >
              {isUpdatingConversation ? "Deleting..." : "Confirm"}
            </button>
            <button
              type="button"
              aria-label={`Cancel delete conversation: ${title}`}
              disabled={sidebarDisabled}
              onClick={() => setAction(null)}
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
              activate(conversation.id);
              setTitleDraft(title);
              setAction("rename");
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
              activate(conversation.id);
              setAction("delete");
            }}
            className={actionClass}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

export default function ConversationSidebar({ model, replaying, mobile, drawerOpen, closeRef, onClose }: {
  model: ConversationModel;
  replaying: boolean;
  mobile: boolean;
  drawerOpen: boolean;
  closeRef: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
}) {
  // Only one row may show an action, while each row owns its form state.
  const [activeId, setActiveId] = useState<string | null>(null);
  const { conversations, sidebarDisabled, selectConversation, conversationError,
    setConversationError } = model;

  return (
    <aside
      id="conversation-drawer"
      inert={replaying || (mobile && !drawerOpen)}
      data-replay-dimmed={replaying}
      data-drawer-open={mobile && drawerOpen}
      className="chat-sidebar glass-surface flex shrink-0 flex-col border-r border-glass-border md:w-64 md:p-4"
    >
      <div className="mb-4 flex items-center justify-between gap-3 md:hidden">
        <h2 className="text-sm font-medium">Conversations</h2>
        <button
          ref={closeRef}
          type="button"
          aria-label="Close conversations"
          onClick={onClose}
          className="flex size-10 shrink-0 items-center justify-center rounded-md border border-glass-border focus-visible:outline-2 focus-visible:outline-accent"
        >
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </div>
      <button
        type="button"
        onClick={() => {
          void selectConversation();
          onClose();
        }}
        disabled={sidebarDisabled}
        className="new-chat mb-4 rounded-md border px-3 py-2.5 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
      >
        New chat
      </button>
      <nav aria-label="Conversations" className="min-h-0 space-y-1 overflow-y-auto">
        {conversations.map((conversation) => (
          <ConversationRow
            key={conversation.id}
            conversation={conversation}
            model={model}
            activeId={activeId}
            onSelect={onClose}
            activate={(id) => {
              setActiveId(id);
              setConversationError(null);
            }}
          />
        ))}
      </nav>
      {conversationError ? <p role="alert" className="mt-3 text-sm text-step-error">{conversationError}</p> : null}
    </aside>
  );
}
