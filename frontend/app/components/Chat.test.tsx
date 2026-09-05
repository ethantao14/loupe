import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Chat from "./Chat";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn(),
  sendMessage: vi.fn(),
}));

const api = await import("@/lib/api");
const fetchMessages = vi.mocked(api.fetchMessages);
const sendMessage = vi.mocked(api.sendMessage);

function message(id: string, role: "user" | "assistant", content: string) {
  return { id, role, content, created_at: "2026-01-01T00:00:00Z" };
}

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
});
