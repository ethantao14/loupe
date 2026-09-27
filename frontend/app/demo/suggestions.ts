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
    prompt: "Summarize https://en.wikipedia.org/wiki/Magnifying_glass in two sentences.",
    shows: "Reads a web page",
    kind: "tool_call",
  },
  {
    prompt: "Use Python to list the first 10 prime numbers.",
    shows: "Runs code",
    kind: "tool_result",
  },
  {
    prompt: "Remember that my favourite programming language is TypeScript.",
    shows: "Saves a memory",
    kind: "memory",
  },
  {
    prompt: "What do you remember about me?",
    shows: "Recalls memories",
    kind: "memory",
  },
];
