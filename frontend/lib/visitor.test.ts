import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("visitor identity", () => {
  it("creates one UUID, persists it, and reuses it after a reload", async () => {
    const getRandomValues = vi.spyOn(crypto, "getRandomValues");
    const { getVisitorId } = await import("./visitor");
    const id = getVisitorId();

    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(getVisitorId()).toBe(id);
    expect(window.localStorage.getItem("loupe.visitorId")).toBe(id);
    vi.resetModules();
    expect((await import("./visitor")).getVisitorId()).toBe(id);
    expect(getRandomValues).toHaveBeenCalledTimes(1);
  });

  it("works where crypto.randomUUID is unavailable, as on plain HTTP", async () => {
    vi.stubGlobal("crypto", { getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto) });
    const { getVisitorId } = await import("./visitor");

    expect(getVisitorId()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("uses a saved identity without generating another", async () => {
    const saved = "12345678-1234-4234-8234-123456789abc";
    window.localStorage.setItem("loupe.visitorId", saved);
    const getRandomValues = vi.spyOn(crypto, "getRandomValues");
    const { getVisitorId } = await import("./visitor");

    expect(getVisitorId()).toBe(saved);
    expect(getRandomValues).not.toHaveBeenCalled();
  });

  it.each(["not-a-uuid", "00000000-0000-0000-0000-000000000000"])(
    "replaces a saved identity the backend would reject: %s", async (saved) => {
      window.localStorage.setItem("loupe.visitorId", saved);
      const { getVisitorId } = await import("./visitor");
      const id = getVisitorId();

      expect(id).not.toBe(saved);
      expect(window.localStorage.getItem("loupe.visitorId")).toBe(id);
    },
  );

  it.each(["getItem", "setItem", "storage access"])(
    "keeps the same identity on requests when %s throws", async (failure) => {
      if (failure === "storage access") {
        Object.defineProperty(window, "localStorage", {
          configurable: true,
          get() { throw new Error("Storage blocked"); },
        });
      } else {
        vi.spyOn(window.localStorage, failure as "getItem" | "setItem").mockImplementation(() => {
          throw new Error("Storage blocked");
        });
      }
      const getRandomValues = vi.spyOn(crypto, "getRandomValues");
      const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(Response.json([])));
      vi.stubGlobal("fetch", fetchMock);
      const { fetchConversations, fetchMessages, fetchMemories } = await import("./api");
      const { getVisitorId } = await import("./visitor");

      await fetchConversations();
      await fetchMessages();
      await fetchMemories();

      const id = getVisitorId();
      expect(getRandomValues).toHaveBeenCalledTimes(1);
      for (const [, options] of fetchMock.mock.calls) {
        expect(options.headers).toEqual({ "X-Visitor-Id": id });
      }
    },
  );
});
