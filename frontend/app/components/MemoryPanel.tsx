import { useCallback, useEffect, useId, useRef, useState } from "react";

import { deleteMemory, fetchMemories, type Memory } from "@/lib/api";

export default function MemoryPanel({ refreshToken }: { refreshToken: number }) {
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
    <div className="memory-panel glass-surface max-w-2xl overflow-hidden rounded-lg border border-glass-border">
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
      <div id={panelId} hidden={!expanded} className="space-y-3 border-t border-glass-border p-4">
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
              <li key={memory.id} className="memory-fact flex flex-wrap items-start justify-between gap-3">
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

