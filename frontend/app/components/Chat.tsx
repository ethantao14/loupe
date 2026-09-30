"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Composer from "./Composer";
import ConversationSidebar from "./ConversationSidebar";
import EmptyState, { WatchChips } from "./EmptyState";
import MemoryPanel from "./MemoryPanel";
import MessageView from "./MessageView";
import ReplayTour from "./ReplayTour";
import { useMediaQuery } from "./useMediaQuery";
import { useReplayTour } from "./useReplayTour";
import { useStreamingTurn } from "./useStreamingTurn";

export default function Chat() {
  const composerRef = useRef<HTMLInputElement>(null);
  const { session, startReplay, endReplay } = useReplayTour(composerRef);
  const { conversation, provisional, draft, setDraft, isSending, memoryVersion,
    error, quotaReached, sendContent } = useStreamingTurn(session !== null);
  const { messages, isLoading, isUpdatingConversation, sidebarDisabled } = conversation;
  const mobile = useMediaQuery("(max-width: 767px)");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const replaying = session !== null;

  if (drawerOpen && (!mobile || replaying)) setDrawerOpen(false);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  useEffect(() => {
    if (!mobile || !drawerOpen) return;
    const menu = menuRef.current;
    closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDrawer();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    // Focus returns here, after the page behind the drawer stops being inert.
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      menu?.focus();
    };
  }, [mobile, drawerOpen, closeDrawer]);

  return (
    <div className="chat-shell flex h-dvh min-w-0 overflow-hidden bg-canvas text-text-primary">
      {mobile && drawerOpen ? (
        <div className="drawer-scrim md:hidden" onClick={closeDrawer} aria-hidden="true" />
      ) : null}
      <ConversationSidebar
        model={conversation}
        replaying={replaying}
        mobile={mobile}
        drawerOpen={drawerOpen}
        closeRef={closeRef}
        onClose={closeDrawer}
      />
      <main inert={mobile && drawerOpen} className="chat-main flex min-w-0 flex-1 flex-col">
        <header className="chat-header flex shrink-0 flex-wrap items-center gap-2.5 px-4 py-3 md:px-7 md:py-5">
          <button
            ref={menuRef}
            type="button"
            aria-label="Open conversations"
            aria-expanded={mobile && drawerOpen}
            aria-controls="conversation-drawer"
            disabled={replaying}
            onClick={() => setDrawerOpen(true)}
            className="drawer-toggle glass-surface flex size-10 shrink-0 items-center justify-center rounded-md border border-glass-border focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 md:hidden"
          >
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
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

        <div hidden={session !== null} className="message-list min-h-0 flex-1 space-y-6 overflow-y-auto px-4 pb-7 pt-1 md:px-7 [overflow-wrap:anywhere]">
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
