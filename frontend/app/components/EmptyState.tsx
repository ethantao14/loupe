import type { CSSProperties } from "react";

import { suggestions } from "../demo/suggestions";
import type { ReplayId } from "../demo/replay";
import { styleForStep } from "./MessageView";

export function WatchChips({ onReplay }: { onReplay: (id: ReplayId) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button type="button" className="replay-chip" onClick={() => onReplay("run-python")}>
        Watch: running Python
      </button>
      <button type="button" className="replay-chip" onClick={() => onReplay("failure-recovery")}>
        Watch: recovering from a failure
      </button>
    </div>
  );
}

export default function EmptyState({ sidebarDisabled, quotaReached, sendContent, startReplay }: {
  sidebarDisabled: boolean;
  quotaReached: boolean;
  sendContent: (content: string) => Promise<void>;
  startReplay: (id: ReplayId) => void;
}) {
  return (
    <div className="max-w-2xl space-y-3">
      <p className="text-sm text-text-secondary">Start the conversation below.</p>
      <p className="text-sm text-text-secondary">Not sure what to ask? Try one of these.</p>
      <ul aria-label="Suggested prompts" className="suggestion-grid">
        {suggestions.map((suggestion) => (
          <li key={suggestion.prompt}>
            <button
              type="button"
              className="suggestion-card glass-surface"
              style={{ "--step-color": styleForStep(suggestion.kind).color } as CSSProperties}
              disabled={sidebarDisabled}
              onClick={() => void sendContent(suggestion.prompt)}
            >
              <span className="suggestion-shows">{suggestion.shows}</span>
              <span className="suggestion-prompt">{suggestion.prompt}</span>
            </button>
          </li>
        ))}
      </ul>
      {!quotaReached ? (
        <>
          <p className="pt-2 text-sm text-text-secondary">Or watch an example</p>
          <WatchChips onReplay={startReplay} />
        </>
      ) : null}
    </div>
  );
}
