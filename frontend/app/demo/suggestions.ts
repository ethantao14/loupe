import type { Step } from "@/lib/api";

// Each suggestion exercises a different part of the trace, so a visitor who
// cannot think of a question still sees the step it produces.
export type Suggestion = {
  prompt: string;
  shows: string;
  kind: Step["kind"];
};

export const suggestions: Suggestion[] = [
  {
    prompt: "Look up the populations of Tokyo and New York City on Wikipedia, then use Python to work out the ratio.",
    shows: "Chains fetches into code",
    kind: "tool_call",
  },
  {
    prompt: "Simulate 10,000 rolls of two dice in Python and show which sums come up most as a text histogram.",
    shows: "Runs code",
    kind: "tool_result",
  },
  {
    prompt: "Summarize https://en.wikipedia.org/wiki/Loupe_(tool). If that link is broken, find the right page.",
    shows: "Recovers from a failure",
    kind: "tool_error",
  },
  {
    prompt: "Remember that I like answers in exactly three short bullet points, then tell me what a loupe is.",
    shows: "Saves a memory it keeps using",
    kind: "memory",
  },
];
