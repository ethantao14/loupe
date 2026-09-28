"use client";

import { useRef } from "react";

import Composer from "./Composer";
import ConversationSidebar from "./ConversationSidebar";
import EmptyState, { WatchChips } from "./EmptyState";
import MemoryPanel from "./MemoryPanel";
import MessageView from "./MessageView";
import ReplayTour from "./ReplayTour";
import { useReplayTour } from "./useReplayTour";
import { useStreamingTurn } from "./useStreamingTurn";

export default function Chat() {
  const composerRef = useRef<HTMLInputElement>(null);
  const { session, startReplay, endReplay } = useReplayTour(composerRef);
  const { conversation, provisional, draft, setDraft, isSending, memoryVersion,
    error, quotaReached, sendContent } = useStreamingTurn(session !== null);
  const { messages, isLoading, isUpdatingConversation, sidebarDisabled } = conversation;

  return (
    <div className="chat-shell flex h-dvh min-w-0 overflow-hidden bg-canvas text-text-primary">
      <ConversationSidebar model={conversation} replaying={session !== null} />
      <main className="chat-main flex min-w-0 flex-1 flex-col">
        <header className="chat-header flex shrink-0 flex-wrap items-center gap-2.5 px-3 py-5 sm:px-7">
          <span aria-hidden="true" className="brand-mark" />
          <h1 className="brand-name">Loupe</h1>
          <button
            type="button"
            onClick={() => startReplay("memory-and-fetch")}
            disabled={isSending || isUpdatingConversation}
            className="tour-text-button ml-auto"
          >
            Take the tour
          </button>
          {isSending && provisional ? (
            <span className="live-indicator">
              <span aria-hidden="true" className="live-dot" />
              TRACING
            </span>
          ) : null}
        </header>

        <div hidden={session !== null} className="message-list min-h-0 flex-1 space-y-6 overflow-y-auto px-3 pb-7 pt-1 sm:px-7 [overflow-wrap:anywhere]">
          <MemoryPanel refreshToken={memoryVersion} />
          {isLoading ? <p className="text-sm text-text-secondary">Loading conversation...</p> : null}
          {messages.length === 0 && !provisional && !isLoading ? (
            <EmptyState
              sidebarDisabled={sidebarDisabled}
              quotaReached={quotaReached}
              sendContent={sendContent}
              startReplay={startReplay}
            />
          ) : null}
          {[...messages, ...(provisional ? [provisional] : [])].map((message) => (
            <MessageView key={message.id} message={message} streaming={message === provisional && isSending} />
          ))}
          {error ? (
            <div className="max-w-2xl space-y-3">
              <p role="alert" className="text-sm text-step-error">{error}</p>
              {quotaReached ? (
                <div role="group" aria-label="Explore the demo" className="space-y-3">
                  <WatchChips onReplay={startReplay} />
                  <button type="button" className="tour-text-button" onClick={() => startReplay("memory-and-fetch")}>
                    Take the tour
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {session ? (
          <ReplayTour
            key={session.key}
            replayId={session.id}
            onClose={endReplay}
            memoryPanel={<MemoryPanel refreshToken={memoryVersion} />}
          />
        ) : null}

        <Composer
          hidden={session !== null}
          composerRef={composerRef}
          draft={draft}
          setDraft={setDraft}
          sidebarDisabled={sidebarDisabled}
          isLoading={isLoading}
          sendContent={sendContent}
        />
      </main>
    </div>
  );
}
