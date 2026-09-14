import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteConversation,
  deleteMemory,
  fetchConversations,
  fetchMemories,
  fetchMessages,
  renameConversation,
  sendMessage,
  streamMessage,
  type SendResult,
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

describe("message streaming API", () => {
  const step = { kind: "answer", tool_name: null, detail: 'Hello\n"world"' };
  const result: SendResult = {
    conversation_id: "chat-1",
    user: { id: "u1", role: "user", content: "Hi", created_at: "today", steps: [] },
    reply: {
      id: "a1", role: "assistant", content: "Hello", created_at: "today",
      steps: [{ id: "s1", kind: "answer", tool_name: null, detail: "Hello" }],
    },
  };

  function handlers() {
    return { onDelta: vi.fn(), onStep: vi.fn(), onDone: vi.fn(), onError: vi.fn() };
  }

  function frame(name: string, payload: unknown): string {
    return `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
  }

  function respond(chunks: Uint8Array[]) {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(chunk));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it.each(["single", "split", "bytes", "crlf"])(
    "routes ordered events from %s chunks", async (chunking) => {
      let events = frame("delta", { text: "Hé" }) + frame("delta", { text: "llo" })
        + frame("step", step) + frame("done", result);
      if (chunking === "crlf") events = events.replaceAll("\n", "\r\n");
      const bytes = new TextEncoder().encode(events);
      const chunks = chunking === "single" ? [bytes]
        : chunking === "split" ? [bytes.slice(0, 23), bytes.slice(23)]
        : Array.from(bytes, (byte) => new Uint8Array([byte]));
      const fetchMock = respond(chunks);
      const callbacks = handlers();

      await streamMessage("Hi", "chat-1", callbacks);

      expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
        expect.stringMatching(/\/api\/messages\/stream$/), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: "Hi", conversation_id: "chat-1" }),
        },
      );
      expect(callbacks.onDelta.mock.calls).toEqual([["Hé"], ["llo"]]);
      expect(callbacks.onStep).toHaveBeenCalledExactlyOnceWith(step);
      expect(callbacks.onDone).toHaveBeenCalledExactlyOnceWith(result);
      expect(callbacks.onError).not.toHaveBeenCalled();
      expect(callbacks.onDelta.mock.invocationCallOrder[1])
        .toBeLessThan(callbacks.onStep.mock.invocationCallOrder[0]);
      expect(callbacks.onStep.mock.invocationCallOrder[0])
        .toBeLessThan(callbacks.onDone.mock.invocationCallOrder[0]);
    },
  );

  it("accepts repeated calls in live steps and the persisted result", async () => {
    const repeat = {
      kind: "tool_repeat" as const, tool_name: "fetch_url", detail: "This exact call already failed.",
    };
    const completed: SendResult = {
      ...result,
      reply: { ...result.reply, steps: [{ id: "repeat-1", ...repeat }] },
    };
    respond([new TextEncoder().encode(frame("step", repeat) + frame("done", completed))]);
    const callbacks = handlers();

    await streamMessage("Hi", "chat-1", callbacks);

    expect(callbacks.onStep).toHaveBeenCalledExactlyOnceWith(repeat);
    expect(callbacks.onDone).toHaveBeenCalledExactlyOnceWith(completed);
    expect(callbacks.onError).not.toHaveBeenCalled();
  });

  it("delivers a delta before the response closes", async () => {
    let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
    const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    let received: () => void = () => {};
    const delta = new Promise<void>((resolve) => { received = resolve; });
    const callbacks = handlers();
    callbacks.onDelta.mockImplementation(received);
    const streaming = streamMessage("Hi", undefined, callbacks);
    controller?.enqueue(new TextEncoder().encode(frame("delta", { text: "Live" })));

    await delta;

    expect(callbacks.onDelta).toHaveBeenCalledExactlyOnceWith("Live");
    expect(callbacks.onDone).not.toHaveBeenCalled();
    controller?.enqueue(new TextEncoder().encode(frame("done", result)));
    await streaming;
  });

  it("routes an error after partial text", async () => {
    const detail = 'Failed\n"try again"';
    respond([new TextEncoder().encode(
      frame("delta", { text: "Partial" }) + frame("error", { detail }),
    )]);
    const callbacks = handlers();

    await streamMessage("Hi", undefined, callbacks);

    expect(callbacks.onDelta).toHaveBeenCalledExactlyOnceWith("Partial");
    expect(callbacks.onError).toHaveBeenCalledExactlyOnceWith(detail);
    expect(callbacks.onDone).not.toHaveBeenCalled();
  });

  it.each([404, 500])("rejects status %s", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));
    await expect(streamMessage("Hi", undefined, handlers()))
      .rejects.toThrow(`Request failed with status ${status}`);
  });

  it("rejects a missing response body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null)));
    await expect(streamMessage("Hi", undefined, handlers())).rejects.toThrow("no response body");
  });

  it("rejects a truncated stream", async () => {
    respond([new TextEncoder().encode(frame("delta", { text: "Partial" }))]);
    await expect(streamMessage("Hi", undefined, handlers())).rejects.toThrow("ended before");
  });

  it.each([
    ["delta", { text: 5 }], ["step", { kind: "answer" }],
    ["done", { conversation_id: "chat-1" }], ["error", { detail: null }],
  ])("rejects invalid %s payloads", async (name, payload) => {
    respond([new TextEncoder().encode(frame(String(name), payload))]);
    await expect(streamMessage("Hi", undefined, handlers())).rejects.toThrow("Invalid");
  });
});
