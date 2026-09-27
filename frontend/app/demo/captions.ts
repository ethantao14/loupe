import type { Step } from "@/lib/api";

export const introCaption = {
  title: "Your question",
  text: "Watch how Loupe works out an answer for you. This real recorded turn pauses to explain each new step.",
};

export const closingCaption = {
  title: "Your answer",
  text: "Your answer is built from the steps above, so you can check how it got there. Now try it yourself.",
};

export const stepCaptions = {
  memory: () => "Before answering, Loupe checks what it remembers about you. Pink steps are recalled memories.",
  thinking: () => "Purple shows you what Loupe is thinking about before its next move.",
  tool_call: (toolName) => {
    const explanation = toolName === "fetch_url" ? "fetch_url reads a web page for you."
      : toolName === "run_python" ? "run_python runs code for you in a locked-down container."
        : toolName ? `You can see the call to ${toolName} here.`
          : "You can see what it asks the tool to do here.";
    return `Blue means it decided to use a tool. ${explanation}`;
  },
  tool_result: () => "Green shows you what came back from the tool. Loupe uses this information to work out your answer.",
  tool_error: () => "Red shows you that a tool failed. Loupe sees the error too and can recover to help you.",
  tool_repeat: () => "Amber shows you a repeat that Loupe refused to run because the same call already failed.",
  answer: () => "This light step shows you the answer Loupe settled on. You can follow the steps above to see why.",
} satisfies Record<Step["kind"], (toolName: string | null) => string>;

export function captionForStep(step: Pick<Step, "kind" | "tool_name">): string {
  return stepCaptions[step.kind](step.tool_name);
}
