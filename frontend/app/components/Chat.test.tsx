import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Memory, Message, Step } from "@/lib/api";

import Chat from "./Chat";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn(),
  sendMessage: vi.fn(),
  fetchMemories: vi.fn(),
  deleteMemory: vi.fn(),
}));

const api = await import("@/lib/api");
const fetchMessages = vi.mocked(api.fetchMessages);
const sendMessage = vi.mocked(api.sendMessage);
const fetchMemories = vi.mocked(api.fetchMemories);
const deleteMemory = vi.mocked(api.deleteMemory);

const rememberedFacts: Memory[] = [
  { id: "memory-2", fact: "The user prefers Python.", created_at: "2026-01-02T00:00:00Z" },
  { id: "memory-1", fact: "The user lives in Boston.", created_at: "2026-01-01T00:00:00Z" },
];

function message(
  id: string,
  role: "user" | "assistant",
  content: string,
  steps: Step[] = [],
): Message {
  return { id, role, content, created_at: "2026-01-01T00:00:00Z", steps };
}

const traceSteps: Step[] = [
  { id: "s1", kind: "thinking", tool_name: null, detail: "Checking the page." },
  { id: "s2", kind: "tool_call", tool_name: "fetch_url", detail: '{"url":"https://example.com"}' },
  { id: "s3", kind: "tool_result", tool_name: "fetch_url", detail: "Page said hello." },
  { id: "s4", kind: "answer", tool_name: null, detail: "The page says hello." },
];

describe("Chat", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    fetchMemories.mockResolvedValue(rememberedFacts);
    deleteMemory.mockResolvedValue(undefined);
  });

  it("keeps memories collapsed without fetching until opened and retains the loaded count", async () => {
    fetchMessages.mockResolvedValue([]);
    const { rerender } = render(<Chat />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());

    const control = screen.getByRole("button", { name: "Remembered facts (not loaded)" });
    expect(control).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(control.getAttribute("aria-controls") ?? "")).not.toBeVisible();
    expect(fetchMemories).not.toHaveBeenCalled();

    await userEvent.click(control);

    expect(await screen.findByText(rememberedFacts[0].fact)).toBeVisible();
    expect(screen.getByText(rememberedFacts[1].fact)).toBeVisible();
    expect(control).toHaveAttribute("aria-expanded", "true");
    expect(control).toHaveAccessibleName("Remembered facts (2)");
    expect(document.getElementById(control.getAttribute("aria-controls") ?? "")).toContainElement(
      screen.getByRole("list", { name: "Remembered facts" }),
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    rememberedFacts.forEach((memory, index) => expect(items[index]).toHaveTextContent(memory.fact));

    await userEvent.click(control);
    expect(control).toHaveAttribute("aria-expanded", "false");
    expect(control).toHaveAccessibleName("Remembered facts (2)");
    expect(screen.getByText(rememberedFacts[0].fact)).not.toBeVisible();
    rerender(<Chat />);
    await userEvent.click(control);
    expect(fetchMemories).toHaveBeenCalledTimes(1);
  });

  it("forgets a fact and updates the count without reloading", async () => {
    fetchMessages.mockResolvedValue([]);
    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "Remembered facts (not loaded)" }));
    await userEvent.click(await screen.findByRole("button", {
      name: `Forget fact: ${rememberedFacts[0].fact}`,
    }));

    await waitFor(() => expect(screen.queryByText(rememberedFacts[0].fact)).not.toBeInTheDocument());
    expect(deleteMemory).toHaveBeenCalledExactlyOnceWith(rememberedFacts[0].id);
    expect(screen.getByText(rememberedFacts[1].fact)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remembered facts (1)" })).toBeVisible();
    expect(fetchMemories).toHaveBeenCalledTimes(1);
    expect(fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("keeps the fact on a failed delete and allows retrying", async () => {
    fetchMessages.mockResolvedValue([]);
    deleteMemory.mockRejectedValueOnce(new Error("network"));
    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "Remembered facts (not loaded)" }));
    const forget = await screen.findByRole("button", {
      name: `Forget fact: ${rememberedFacts[0].fact}`,
    });
    await userEvent.click(forget);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      `Could not forget "${rememberedFacts[0].fact}". Please try again.`,
    );
    expect(screen.getByText(rememberedFacts[0].fact)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remembered facts (2)" })).toBeVisible();
    expect(forget).toBeEnabled();

    await userEvent.click(forget);
    await waitFor(() => expect(screen.queryByText(rememberedFacts[0].fact)).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a loading error and can retry an empty memory list", async () => {
    fetchMessages.mockResolvedValue([]);
    fetchMemories.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce([]);
    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "Remembered facts (not loaded)" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load remembered facts.");
    await userEvent.click(screen.getByRole("button", { name: "Retry loading remembered facts" }));

    expect(await screen.findByText("No remembered facts.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Remembered facts (0)" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMemories).toHaveBeenCalledTimes(2);
  });

  it("does not duplicate pending memory requests when toggling the panel", async () => {
    fetchMessages.mockResolvedValue([]);
    let finishLoading: (memories: Memory[]) => void = () => {};
    fetchMemories.mockReturnValue(new Promise((resolve) => { finishLoading = resolve; }));
    render(<Chat />);
    const control = screen.getByRole("button", { name: "Remembered facts (not loaded)" });
    await userEvent.click(control);
    expect(screen.getByRole("status")).toHaveTextContent("Loading remembered facts...");
    await userEvent.click(control);
    await userEvent.click(control);
    expect(fetchMemories).toHaveBeenCalledTimes(1);

    finishLoading(rememberedFacts);
    expect(await screen.findByText(rememberedFacts[0].fact)).toBeVisible();
  });

  it("keeps a fact visible and prevents duplicate deletes until deletion succeeds", async () => {
    fetchMessages.mockResolvedValue([]);
    let finishDelete: () => void = () => {};
    deleteMemory.mockReturnValue(new Promise((resolve) => { finishDelete = resolve; }));
    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "Remembered facts (not loaded)" }));
    const forget = await screen.findByRole("button", {
      name: `Forget fact: ${rememberedFacts[0].fact}`,
    });
    await userEvent.click(forget);
    expect(forget).toBeDisabled();
    expect(screen.getByText(rememberedFacts[0].fact)).toBeVisible();
    await userEvent.click(forget);
    expect(deleteMemory).toHaveBeenCalledTimes(1);

    finishDelete();
    await waitFor(() => expect(screen.queryByText(rememberedFacts[0].fact)).not.toBeInTheDocument());
  });

  it("renders history loaded on mount", async () => {
    fetchMessages.mockResolvedValue([message("1", "user", "Hello there")]);

    render(<Chat />);

    expect(await screen.findByText("Hello there")).toBeInTheDocument();
  });

  it("renders recalled memories with their label", async () => {
    fetchMessages.mockResolvedValue([message("1", "assistant", "Hello", [{
      id: "memory-1", kind: "memory", tool_name: null, detail: "The user prefers Python.",
    }])]);

    render(<Chat />);
    await userEvent.click(await screen.findByRole("button", { name: "Show reasoning (1 step)" }));

    expect(screen.getByText("Memory")).toBeVisible();
    expect(screen.getByLabelText("Step 1: Memory detail")).toHaveTextContent(
      "The user prefers Python.",
    );
  });

  it.each(["future_kind", "toString", "__proto__"])(
    "renders an unknown step kind safely: %s", async (kind) => {
      const unknownStep = {
        id: "unknown-1", kind, tool_name: null, detail: "Future step detail",
      } as unknown as Step;
      fetchMessages.mockResolvedValue([message("1", "assistant", "Hello", [unknownStep])]);

      render(<Chat />);
      await userEvent.click(await screen.findByRole("button", { name: "Show reasoning (1 step)" }));

      expect(screen.getByText("Step")).toBeVisible();
      expect(screen.getByLabelText("Step 1: Step detail")).toHaveTextContent("Future step detail");
    },
  );

  it("sends a message and shows both turns", async () => {
    fetchMessages.mockResolvedValue([]);
    sendMessage.mockResolvedValue({
      user: message("1", "user", "Hello"),
      reply: message("2", "assistant", "Hi back"),
    });

    render(<Chat />);
    await userEvent.type(screen.getByLabelText("Message"), "Hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith("Hello"));
    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(await screen.findByText("Hi back")).toBeInTheDocument();
  });

  it("keeps the draft when sending fails", async () => {
    fetchMessages.mockResolvedValue([]);
    sendMessage.mockRejectedValue(new Error("network"));

    render(<Chat />);
    await userEvent.type(screen.getByLabelText("Message"), "Hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Could not send that message.")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("Hello");
  });

  it("keeps the trace collapsed by default", async () => {
    fetchMessages.mockResolvedValue([message("1", "assistant", "Summary", traceSteps)]);

    render(<Chat />);

    const control = await screen.findByRole("button", { name: "Show reasoning (4 steps)" });
    expect(control).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Checking the page.")).not.toBeVisible();
    expect(screen.queryByRole("list", { name: "Reasoning steps" })).not.toBeInTheDocument();
  });

  it("expands and collapses the ordered trace", async () => {
    fetchMessages.mockResolvedValue([message("1", "assistant", "Summary", traceSteps)]);

    render(<Chat />);
    await userEvent.click(await screen.findByRole("button", { name: "Show reasoning (4 steps)" }));

    const control = screen.getByRole("button", { name: "Hide reasoning (4 steps)" });
    expect(control).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("list", { name: "Reasoning steps" })).toHaveAttribute(
      "id", control.getAttribute("aria-controls"),
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    ["Thinking", "Tool call", "Tool result", "Answer"].forEach((label, index) => {
      expect(items[index]).toHaveTextContent(label);
      expect(items[index]).toHaveTextContent(traceSteps[index].detail);
      expect(items[index]).toBeVisible();
    });
    expect(items[1]).toHaveTextContent("fetch_url");
    expect(items[2]).toHaveTextContent("fetch_url");

    await userEvent.click(control);
    expect(control).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Checking the page.")).not.toBeVisible();
  });

  it("renders no trace control for messages without steps", async () => {
    fetchMessages.mockResolvedValue([
      message("1", "user", "Hello"),
      message("2", "assistant", "Hi back"),
    ]);

    render(<Chat />);

    expect(await screen.findByText("Hi back")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reasoning/ })).not.toBeInTheDocument();
  });

  it("shows a new reply's trace without refetching history", async () => {
    fetchMessages.mockResolvedValue([]);
    sendMessage.mockResolvedValue({
      user: message("1", "user", "Read the page"),
      reply: message("2", "assistant", "Summary", traceSteps),
    });

    render(<Chat />);
    await userEvent.type(screen.getByLabelText("Message"), "Read the page");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show reasoning (4 steps)" }));

    expect(screen.getByText("Page said hello.")).toBeVisible();
    expect(fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("does not restore a deleted fact when an older refresh finishes", async () => {
    fetchMessages.mockResolvedValue([]);
    let finishRefresh: (memories: Memory[]) => void = () => {};
    fetchMemories.mockResolvedValueOnce(rememberedFacts).mockReturnValueOnce(
      new Promise((resolve) => { finishRefresh = resolve; }),
    );
    let finishDelete: () => void = () => {};
    deleteMemory.mockReturnValueOnce(new Promise((resolve) => { finishDelete = resolve; }));
    sendMessage.mockResolvedValue({
      user: message("1", "user", "Hello"),
      reply: message("2", "assistant", "Hi back"),
    });

    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "Remembered facts (not loaded)" }));
    expect(await screen.findByText(rememberedFacts[0].fact)).toBeVisible();
    await userEvent.type(screen.getByLabelText("Message"), "Hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(fetchMemories).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("status")).toHaveTextContent("Loading remembered facts...");

    await userEvent.click(screen.getByRole("button", {
      name: `Forget fact: ${rememberedFacts[0].fact}`,
    }));
    await act(async () => { finishDelete(); });
    expect(screen.queryByText(rememberedFacts[0].fact)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remembered facts (1)" })).toBeVisible();

    await act(async () => { finishRefresh(rememberedFacts); });

    expect(screen.queryByText(rememberedFacts[0].fact)).not.toBeInTheDocument();
    expect(screen.getByText(rememberedFacts[1].fact)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remembered facts (1)" })).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fetchMemories).toHaveBeenCalledTimes(2);
  });

  it("refreshes after a chat turn completes during the initial memory load", async () => {
    fetchMessages.mockResolvedValue([]);
    let finishLoading: (memories: Memory[]) => void = () => {};
    const newFact: Memory = {
      id: "new", fact: "The user's dog is a corgi", created_at: "2026-01-02T00:00:00Z",
    };
    fetchMemories.mockReturnValueOnce(
      new Promise((resolve) => { finishLoading = resolve; }),
    ).mockResolvedValueOnce([...rememberedFacts, newFact]);
    sendMessage.mockResolvedValue({
      user: message("1", "user", "Remember my dog is a corgi"),
      reply: message("2", "assistant", "Noted."),
    });

    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "Remembered facts (not loaded)" }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading remembered facts...");
    await userEvent.type(screen.getByLabelText("Message"), "Remember my dog is a corgi");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Noted.")).toBeVisible();
    expect(fetchMemories).toHaveBeenCalledTimes(1);

    await act(async () => { finishLoading(rememberedFacts); });

    expect(await screen.findByText(newFact.fact)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remembered facts (3)" })).toBeVisible();
    expect(fetchMemories).toHaveBeenCalledTimes(2);
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("retries a failed refresh while remembered facts are already listed", async () => {
    fetchMessages.mockResolvedValue([]);
    const newFact: Memory = {
      id: "new", fact: "The user's dog is a corgi", created_at: "2026-01-02T00:00:00Z",
    };
    fetchMemories.mockResolvedValueOnce(rememberedFacts)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce([...rememberedFacts, newFact]);
    sendMessage.mockResolvedValue({
      user: message("1", "user", "Remember my dog is a corgi"),
      reply: message("2", "assistant", "Noted."),
    });

    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "Remembered facts (not loaded)" }));
    expect(await screen.findByText(rememberedFacts[0].fact)).toBeVisible();
    await userEvent.type(screen.getByLabelText("Message"), "Remember my dog is a corgi");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load remembered facts.");
    expect(screen.getByText(rememberedFacts[0].fact)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remembered facts (2)" })).toBeVisible();

    const retry = screen.getByRole("button", { name: "Retry loading remembered facts" });
    expect(retry).toBeEnabled();
    await userEvent.click(retry);

    expect(await screen.findByText(newFact.fact)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remembered facts (3)" })).toBeVisible();
    expect(fetchMemories).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry loading remembered facts" }))
      .not.toBeInTheDocument();
  });

  it("refreshes an open panel after a turn stores a new fact", async () => {
    // The panel used to cache forever, so a fact remembered during a later
    // turn never appeared and could not be forgotten without a reload.
    fetchMessages.mockResolvedValue([]);
    fetchMemories.mockResolvedValueOnce(rememberedFacts);
    sendMessage.mockResolvedValue({
      user: message("1", "user", "Remember my dog is a corgi"),
      reply: message("2", "assistant", "Noted."),
    });
    fetchMemories.mockResolvedValueOnce([
      ...rememberedFacts,
      { id: "new", fact: "The user's dog is a corgi", created_at: "2026-01-02T00:00:00Z" },
    ]);

    render(<Chat />);
    await userEvent.click(await screen.findByRole("button", { name: /Remembered facts/ }));
    expect(await screen.findByText(rememberedFacts[0].fact)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Message"), "Remember my dog is a corgi");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("The user's dog is a corgi")).toBeInTheDocument();
  });

  it("keeps a newly saved fact when a delete invalidates the refresh carrying it", async () => {
    // The delete discarded the whole in flight response, new facts included.
    fetchMessages.mockResolvedValue([]);
    sendMessage.mockResolvedValue({
      user: message("1", "user", "remember something"),
      reply: message("2", "assistant", "Noted."),
    });
    fetchMemories.mockResolvedValueOnce(rememberedFacts);
    let releaseRefresh: (facts: Memory[]) => void = () => {};
    fetchMemories.mockReturnValueOnce(
      new Promise<Memory[]>((resolve) => {
        releaseRefresh = resolve;
      }),
    );
    fetchMemories.mockResolvedValue([
      { id: "new", fact: "A newly saved fact", created_at: "2026-01-03T00:00:00Z" },
    ]);
    deleteMemory.mockResolvedValue(undefined);

    render(<Chat />);
    await userEvent.click(await screen.findByRole("button", { name: /Remembered facts/ }));
    expect(await screen.findByText(rememberedFacts[0].fact)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Message"), "remember something");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await userEvent.click(screen.getByRole("button", {
      name: `Forget fact: ${rememberedFacts[0].fact}`,
    }));
    releaseRefresh([...rememberedFacts, {
      id: "new", fact: "A newly saved fact", created_at: "2026-01-03T00:00:00Z",
    }]);

    expect(await screen.findByText("A newly saved fact")).toBeInTheDocument();
  });

  it("refreshes remembered facts even when the turn fails", async () => {
    // remember can succeed before the turn fails, so the fact is already stored.
    fetchMessages.mockResolvedValue([]);
    fetchMemories.mockResolvedValueOnce(rememberedFacts);
    sendMessage.mockRejectedValue(new Error("turn failed"));
    fetchMemories.mockResolvedValue([
      ...rememberedFacts,
      { id: "saved", fact: "Stored before the failure", created_at: "2026-01-04T00:00:00Z" },
    ]);

    render(<Chat />);
    await userEvent.click(await screen.findByRole("button", { name: /Remembered facts/ }));
    expect(await screen.findByText(rememberedFacts[0].fact)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Message"), "remember this");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Stored before the failure")).toBeInTheDocument();
  });
});
