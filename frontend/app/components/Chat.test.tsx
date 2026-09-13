import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation, Memory, Message, Step } from "@/lib/api";

import Chat from "./Chat";

vi.mock("@/lib/api", () => ({
  fetchConversations: vi.fn(),
  fetchMessages: vi.fn(),
  sendMessage: vi.fn(),
  fetchMemories: vi.fn(),
  deleteMemory: vi.fn(),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
}));

const api = await import("@/lib/api");
const fetchConversations = vi.mocked(api.fetchConversations);
const fetchMessages = vi.mocked(api.fetchMessages);
const sendMessage = vi.mocked(api.sendMessage);
const fetchMemories = vi.mocked(api.fetchMemories);
const deleteMemory = vi.mocked(api.deleteMemory);
const renameConversation = vi.mocked(api.renameConversation);
const deleteConversation = vi.mocked(api.deleteConversation);

const conversations: Conversation[] = [
  { id: "chat-2", title: "Latest chat", created_at: "2026-01-02T00:00:00Z" },
  { id: "chat-1", title: "Earlier chat", created_at: "2026-01-01T00:00:00Z" },
];

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
    fetchConversations.mockResolvedValue(conversations);
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

  it("renders a failed tool step with a red Tool error badge", async () => {
    fetchMessages.mockResolvedValue([message("1", "assistant", "Trying again", [{
      id: "error-1", kind: "tool_error", tool_name: "fetch_url", detail: "Error: Could not fetch",
    }])]);

    render(<Chat />);
    await userEvent.click(await screen.findByRole("button", { name: "Show reasoning (1 step)" }));

    const badge = screen.getByText("Tool error");
    expect(badge).toBeVisible();
    expect(badge).toHaveClass("bg-red-400/10", "text-red-300");
    expect(screen.getByText("fetch_url")).toBeVisible();
    expect(screen.getByLabelText("Step 1: Tool error detail")).toHaveTextContent(
      "Error: Could not fetch",
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
      conversation_id: "chat-2",
      user: message("1", "user", "Hello"),
      reply: message("2", "assistant", "Hi back"),
    });

    render(<Chat />);
    await userEvent.type(screen.getByLabelText("Message"), "Hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith("Hello", "chat-2"));
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
      conversation_id: "chat-2",
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
      conversation_id: "chat-2",
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
      conversation_id: "chat-2",
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
      conversation_id: "chat-2",
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
      conversation_id: "chat-2",
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
      conversation_id: "chat-2",
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

describe("conversations", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    fetchConversations.mockResolvedValue(conversations);
    fetchMessages.mockImplementation(async (id) => [
      message(`${id}-message`, "user", `History for ${id}`),
    ]);
    fetchMemories.mockResolvedValue(rememberedFacts);
  });

  it("lists conversations newest first and loads the latest on mount", async () => {
    render(<Chat />);

    expect(await screen.findByText("History for chat-2")).toBeVisible();
    const buttons = screen.getByRole("navigation", { name: "Conversations" })
      .querySelectorAll(":scope > div > button");
    expect(Array.from(buttons, (button) => button.textContent)).toEqual([
      "Latest chat", "Earlier chat",
    ]);
    expect(buttons[0]).toHaveAttribute("aria-current", "page");
    expect(buttons[1]).not.toHaveAttribute("aria-current");
    expect(fetchMessages).toHaveBeenCalledExactlyOnceWith("chat-2");
  });

  it("switches history and marks the selected conversation", async () => {
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await userEvent.click(screen.getByRole("button", { name: "Earlier chat" }));

    expect(await screen.findByText("History for chat-1")).toBeVisible();
    expect(screen.queryByText("History for chat-2")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Earlier chat" }))
      .toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Latest chat" })).not.toHaveAttribute("aria-current");
    expect(fetchMessages).toHaveBeenLastCalledWith("chat-1");
  });

  it("clears history and the draft for an unsaved new chat", async () => {
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await userEvent.type(screen.getByLabelText("Message"), "Unsent draft");
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(screen.queryByText("History for chat-2")).not.toBeInTheDocument();
    expect(screen.getByText("Start the conversation below.")).toBeVisible();
    expect(screen.getByLabelText("Message")).toHaveValue("");
    expect(document.querySelector('[aria-current="page"]')).toBeNull();
    expect(fetchMessages).toHaveBeenCalledTimes(1);
    expect(sendMessage).not.toHaveBeenCalled();
    expect(fetchConversations).toHaveBeenCalledTimes(1);
  });

  it("creates a conversation on first send and uses its id for the next send", async () => {
    const created: Conversation = {
      id: "chat-3", title: "A new topic", created_at: "2026-01-03T00:00:00Z",
    };
    fetchConversations.mockResolvedValueOnce(conversations)
      .mockResolvedValue([created, ...conversations]);
    sendMessage.mockResolvedValueOnce({
      conversation_id: created.id,
      user: message("u1", "user", "A new topic"),
      reply: message("a1", "assistant", "New reply"),
    }).mockResolvedValueOnce({
      conversation_id: created.id,
      user: message("u2", "user", "Continue"),
      reply: message("a2", "assistant", "Next reply"),
    });
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    await userEvent.type(screen.getByLabelText("Message"), "A new topic");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    const saved = await screen.findByRole("button", { name: "A new topic" });
    expect(saved).toHaveAttribute("aria-current", "page");
    expect(saved.parentElement?.parentElement?.firstElementChild).toBe(saved.parentElement);
    expect(screen.getByText("New reply")).toBeVisible();
    expect(sendMessage).toHaveBeenNthCalledWith(1, "A new topic", undefined);
    await userEvent.type(screen.getByLabelText("Message"), "Continue");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Next reply")).toBeVisible();
    expect(sendMessage).toHaveBeenNthCalledWith(2, "Continue", "chat-3");
    expect(fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("shows a fallback title and starts empty when there are no conversations", async () => {
    fetchConversations.mockResolvedValueOnce([]);
    const { unmount } = render(<Chat />);
    expect(await screen.findByText("Start the conversation below.")).toBeVisible();
    expect(fetchMessages).not.toHaveBeenCalled();
    unmount();
    fetchConversations.mockResolvedValue([{ ...conversations[0], title: null }]);
    render(<Chat />);
    expect(await screen.findByRole("button", { name: "New conversation" })).toBeVisible();
  });

  it("ignores an out-of-order response after switching away", async () => {
    let finishSlowLoad: (history: Message[]) => void = () => {};
    render(<Chat />);
    await screen.findByText("History for chat-2");
    fetchMessages.mockReturnValueOnce(new Promise((resolve) => { finishSlowLoad = resolve; }));
    await userEvent.click(screen.getByRole("button", { name: "Earlier chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Latest chat" }));
    expect(await screen.findByText("History for chat-2")).toBeVisible();

    await act(async () => { finishSlowLoad([message("old", "user", "Stale history")]); });

    expect(screen.queryByText("Stale history")).not.toBeInTheDocument();
    expect(screen.getByText("History for chat-2")).toBeVisible();
    expect(screen.getByRole("button", { name: "Latest chat" })).toHaveAttribute("aria-current", "page");
  });

  it("ignores an initial history load after New chat is selected", async () => {
    let finishSlowLoad: (history: Message[]) => void = () => {};
    fetchMessages.mockReturnValueOnce(new Promise((resolve) => { finishSlowLoad = resolve; }));
    render(<Chat />);
    await screen.findByRole("button", { name: "Latest chat" });
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));

    await act(async () => { finishSlowLoad([message("old", "user", "Stale history")]); });

    expect(screen.queryByText("Stale history")).not.toBeInTheDocument();
    expect(screen.getByText("Start the conversation below.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  it("keeps a successful exchange when refreshing conversations fails", async () => {
    fetchConversations.mockResolvedValueOnce(conversations).mockRejectedValueOnce(new Error("offline"));
    sendMessage.mockResolvedValue({
      conversation_id: "chat-3",
      user: message("u1", "user", "New topic"),
      reply: message("a1", "assistant", "Saved reply"),
    });
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    await userEvent.type(screen.getByLabelText("Message"), "New topic");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Saved reply")).toBeVisible();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not refresh conversations.");
    expect(screen.queryByText("Could not send that message.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("");
    expect(screen.getByRole("button", { name: "New conversation" }))
      .toHaveAttribute("aria-current", "page");
    expect(sendMessage).toHaveBeenCalledTimes(1);
  });

  it("does not let a slow initial list overwrite a newly saved conversation", async () => {
    let finishInitialList: (items: Conversation[]) => void = () => {};
    const created: Conversation = {
      id: "chat-3", title: "New topic", created_at: "2026-01-03T00:00:00Z",
    };
    fetchConversations.mockReturnValueOnce(new Promise((resolve) => { finishInitialList = resolve; }))
      .mockResolvedValueOnce([created, ...conversations]);
    sendMessage.mockResolvedValue({
      conversation_id: created.id,
      user: message("u1", "user", "New topic"),
      reply: message("a1", "assistant", "Saved reply"),
    });
    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    await userEvent.type(screen.getByLabelText("Message"), "New topic");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("button", { name: "New topic" });

    await act(async () => { finishInitialList(conversations); });

    expect(screen.getByRole("button", { name: "New topic" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Saved reply")).toBeVisible();
    expect(fetchMessages).not.toHaveBeenCalled();
  });

});

describe("conversation actions", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    fetchConversations.mockResolvedValue(conversations);
    fetchMessages.mockImplementation(async (id) => [
      message(`${id}-message`, "user", `History for ${id}`),
    ]);
    deleteConversation.mockResolvedValue(undefined);
    renameConversation.mockImplementation(async (id, title) => ({
      ...conversations.find((item) => item.id === id)!, title,
    }));
  });

  async function startRename(title = "Latest chat") {
    await userEvent.click(screen.getByRole("button", { name: `Rename conversation: ${title}` }));
    return screen.getByRole("textbox", { name: `Title for conversation: ${title}` });
  }

  async function confirmDelete(title: string) {
    await userEvent.click(screen.getByRole("button", { name: `Delete conversation: ${title}` }));
    await userEvent.click(screen.getByRole("button", {
      name: `Confirm permanently delete conversation and all its messages: ${title}`,
    }));
  }

  it.each(["Enter", "Save"])("renames in place using %s", async (save) => {
    render(<Chat />);
    await screen.findByText("History for chat-2");
    const input = await startRename();
    expect(input).toHaveValue("Latest chat");
    expect(input).toHaveFocus();
    await userEvent.clear(input);
    await userEvent.type(input, "  Updated   title  ");
    if (save === "Enter") {
      await userEvent.keyboard("{Enter}");
    } else {
      await userEvent.click(screen.getByRole("button", { name: "Save title for conversation: Latest chat" }));
    }

    expect(await screen.findByRole("button", { name: "Updated title" }))
      .toHaveAttribute("aria-current", "page");
    expect(renameConversation).toHaveBeenCalledExactlyOnceWith("chat-2", "Updated title");
    expect(screen.queryByRole("button", { name: "Latest chat" })).not.toBeInTheDocument();
    expect(screen.getByText("History for chat-2")).toBeVisible();
    expect(fetchMessages).toHaveBeenCalledTimes(1);
    expect(fetchConversations).toHaveBeenCalledTimes(1);
  });

  it.each(["Escape", "Cancel"])("cancels rename using %s", async (cancel) => {
    render(<Chat />);
    await screen.findByText("History for chat-2");
    const input = await startRename();
    await userEvent.clear(input);
    await userEvent.type(input, "Discarded title");
    if (cancel === "Escape") {
      await userEvent.keyboard("{Escape}");
    } else {
      await userEvent.click(screen.getByRole("button", { name: "Cancel rename conversation: Latest chat" }));
    }

    expect(screen.queryByRole("textbox", { name: /Title for conversation/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Latest chat" })).toBeVisible();
    expect(renameConversation).not.toHaveBeenCalled();
  });

  it.each(["", "   ", "Latest chat", "  Latest   chat  "])("cancels an empty or unchanged title: %s", async (title) => {
    render(<Chat />);
    await screen.findByText("History for chat-2");
    const input = await startRename();
    await userEvent.clear(input);
    if (title) await userEvent.type(input, title);
    await userEvent.keyboard("{Enter}");

    expect(renameConversation).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: /Title for conversation/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Latest chat" })).toBeVisible();
  });

  it("keeps the old title after a failed rename and permits retry", async () => {
    renameConversation.mockRejectedValueOnce(new Error("offline"));
    render(<Chat />);
    await screen.findByText("History for chat-2");
    const input = await startRename();
    await userEvent.clear(input);
    await userEvent.type(input, "New title{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent('Could not rename "Latest chat".');
    expect(screen.getByRole("button", { name: "Latest chat" })).toBeVisible();
    const save = screen.getByRole("button", { name: "Save title for conversation: Latest chat" });
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(await screen.findByRole("button", { name: "New title" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("requires an explicit delete confirmation and allows cancel", async () => {
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await userEvent.click(screen.getByRole("button", { name: "Delete conversation: Latest chat" }));

    expect(deleteConversation).not.toHaveBeenCalled();
    expect(screen.getByText('Permanently delete "Latest chat" and all its messages? This cannot be undone.'))
      .toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Cancel delete conversation: Latest chat" }));
    expect(deleteConversation).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete conversation: Latest chat" })).toBeVisible();
  });

  it("deletes the active conversation and loads the newest remaining one", async () => {
    fetchConversations.mockResolvedValue([...conversations, {
      id: "chat-0", title: "Oldest chat", created_at: "2025-12-31T00:00:00Z",
    }]);
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await confirmDelete("Latest chat");

    expect(await screen.findByText("History for chat-1")).toBeVisible();
    expect(deleteConversation).toHaveBeenCalledExactlyOnceWith("chat-2");
    expect(screen.queryByRole("button", { name: "Latest chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Earlier chat" })).toHaveAttribute("aria-current", "page");
    expect(fetchMessages).toHaveBeenLastCalledWith("chat-1");
  });

  it("deletes a non-active conversation without changing history or the draft", async () => {
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await userEvent.type(screen.getByLabelText("Message"), "Keep this draft");
    await confirmDelete("Earlier chat");

    expect(deleteConversation).toHaveBeenCalledExactlyOnceWith("chat-1");
    expect(screen.queryByRole("button", { name: "Earlier chat" })).not.toBeInTheDocument();
    expect(screen.getByText("History for chat-2")).toBeVisible();
    expect(screen.getByLabelText("Message")).toHaveValue("Keep this draft");
    expect(screen.getByRole("button", { name: "Latest chat" })).toHaveAttribute("aria-current", "page");
    expect(fetchMessages).toHaveBeenCalledExactlyOnceWith("chat-2");
  });

  it("deletes the only conversation and starts an empty new chat", async () => {
    fetchConversations.mockResolvedValue([conversations[0]]);
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await userEvent.type(screen.getByLabelText("Message"), "Discard this draft");
    await confirmDelete("Latest chat");

    expect(await screen.findByText("Start the conversation below.")).toBeVisible();
    expect(screen.queryByText("History for chat-2")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("");
    expect(document.querySelector('[aria-current="page"]')).toBeNull();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("shows a failed delete without removing rows and permits retry", async () => {
    deleteConversation.mockRejectedValueOnce(new Error("offline"));
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await confirmDelete("Latest chat");

    expect(await screen.findByRole("alert")).toHaveTextContent('Could not delete "Latest chat".');
    expect(screen.getByRole("button", { name: "Latest chat" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Earlier chat" })).toBeVisible();
    expect(screen.getByText("History for chat-2")).toBeVisible();
    const confirm = screen.getByRole("button", {
      name: "Confirm permanently delete conversation and all its messages: Latest chat",
    });
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(await screen.findByText("History for chat-1")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores a slow history response after deleting that conversation", async () => {
    let finishLoading: (history: Message[]) => void = () => {};
    fetchMessages.mockReturnValueOnce(new Promise((resolve) => { finishLoading = resolve; }));
    render(<Chat />);
    await screen.findByRole("button", { name: "Latest chat" });
    await confirmDelete("Latest chat");
    await screen.findByText("History for chat-1");

    await act(async () => { finishLoading([message("stale", "user", "Deleted history")]); });

    expect(screen.queryByText("Deleted history")).not.toBeInTheDocument();
    expect(screen.getByText("History for chat-1")).toBeVisible();
    expect(screen.getByRole("button", { name: "Earlier chat" })).toHaveAttribute("aria-current", "page");
  });

  it("disables sidebar controls and sending during a delete", async () => {
    let finishDelete: () => void = () => {};
    deleteConversation.mockReturnValueOnce(new Promise((resolve) => { finishDelete = resolve; }));
    render(<Chat />);
    await screen.findByText("History for chat-2");
    await confirmDelete("Latest chat");

    for (const button of screen.getByRole("navigation", { name: "Conversations" }).querySelectorAll("button")) {
      expect(button).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "New chat" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await act(async () => { finishDelete(); });
    expect(await screen.findByText("History for chat-1")).toBeVisible();
    expect(screen.getByRole("button", { name: "New chat" })).toBeEnabled();
  });
});
