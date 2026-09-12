import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteMemory, fetchMemories } from "./api";

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
