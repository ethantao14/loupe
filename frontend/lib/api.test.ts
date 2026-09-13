import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteConversation,
  deleteMemory,
  fetchConversations,
  fetchMemories,
  fetchMessages,
  renameConversation,
  sendMessage,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("memory API", () => {
  it("fetches stored facts", async () => {
    const memories = [{ id: "memory-1", fact: "A fact", created_at: "2026-01-01T00:00:00Z" }];
    const fetchMock = vi.fn().mockResolvedValue(Response.json(memories));
    vi.stubGlobal("fetch", fetchMock);

    expect(await fetchMemories()).toEqual(memories);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(expect.stringMatching(/\/api\/memories$/));
  });

  it("accepts an empty 204 delete response without parsing JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(deleteMemory("memory-1")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      expect.stringMatching(/\/api\/memories\/memory-1$/), { method: "DELETE" },
    );
  });

  it.each([404, 500])("rejects failed deletes with status %s", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));

    await expect(deleteMemory("memory-1")).rejects.toThrow(`Request failed with status ${status}`);
  });

  it("rejects failed list requests", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    await expect(fetchMemories()).rejects.toThrow("Request failed with status 500");
  });
});

describe("conversation API", () => {
  it("fetches the conversation list", async () => {
    const conversations = [{ id: "chat-1", title: null, created_at: "2026-01-01T00:00:00Z" }];
    const fetchMock = vi.fn().mockResolvedValue(Response.json(conversations));
    vi.stubGlobal("fetch", fetchMock);

    expect(await fetchConversations()).toEqual(conversations);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      expect.stringMatching(/\/api\/conversations$/),
    );
  });

  it.each([undefined, "chat /1"])("fetches history for %s", async (id) => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json([]));
    vi.stubGlobal("fetch", fetchMock);

    expect(await fetchMessages(id)).toEqual([]);
    const suffix = id ? `/api/messages?conversation_id=${encodeURIComponent(id)}` : "/api/messages";
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(expect.stringContaining(suffix));
    expect(new URL(fetchMock.mock.calls[0][0]).searchParams.get("conversation_id")).toBe(id ?? null);
  });

  it.each([undefined, "chat-1"])("sends the optional conversation id %s", async (id) => {
    const result = { conversation_id: id ?? "created-id", user: {}, reply: {} };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(result));
    vi.stubGlobal("fetch", fetchMock);

    expect(await sendMessage("Hello", id)).toEqual(result);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(expect.stringMatching(/\/api\/messages$/), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(id ? { content: "Hello", conversation_id: id } : { content: "Hello" }),
    });
  });
});

describe("conversation mutation API", () => {
  it("renames a conversation and encodes its id", async () => {
    const conversation = { id: "chat /1", title: "New title", created_at: "2026-01-01T00:00:00Z" };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(conversation));
    vi.stubGlobal("fetch", fetchMock);

    expect(await renameConversation("chat /1", "New title")).toEqual(conversation);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      expect.stringMatching(/\/api\/conversations\/chat%20%2F1$/),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New title" }),
      },
    );
  });

  it("deletes with an encoded id and accepts an empty 204 response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(deleteConversation("chat /1")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      expect.stringMatching(/\/api\/conversations\/chat%20%2F1$/), { method: "DELETE" },
    );
  });

  it.each([404, 422, 500])("rejects failed renames with status %s", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));

    await expect(renameConversation("chat-1", "New title"))
      .rejects.toThrow(`Request failed with status ${status}`);
  });

  it.each([404, 500])("rejects failed deletes with status %s", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));

    await expect(deleteConversation("chat-1")).rejects.toThrow(`Request failed with status ${status}`);
  });
});
