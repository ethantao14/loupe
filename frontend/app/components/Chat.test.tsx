import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Message, Step } from "@/lib/api";

import Chat from "./Chat";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn(),
  sendMessage: vi.fn(),
}));

const api = await import("@/lib/api");
const fetchMessages = vi.mocked(api.fetchMessages);
const sendMessage = vi.mocked(api.sendMessage);

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
  });

  it("renders history loaded on mount", async () => {
    fetchMessages.mockResolvedValue([message("1", "user", "Hello there")]);

    render(<Chat />);

    expect(await screen.findByText("Hello there")).toBeInTheDocument();
  });

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
});
