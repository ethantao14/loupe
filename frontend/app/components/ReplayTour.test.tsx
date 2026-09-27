import { StrictMode } from "react";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api";

import { captionForStep, closingCaption, introCaption } from "../demo/captions";
import { getReplay, type ReplayId } from "../demo/replay";
import Chat from "./Chat";

const fetchMock = vi.fn<typeof fetch>();
let reducedMotion = false;
let narrow = false;

async function tick(ms = 1000) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

async function mount() {
  const result = render(<StrictMode><Chat /></StrictMode>);
  await tick(0);
  return result;
}

function user() {
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

async function reachPause() {
  for (let index = 0; index < 300; index++) {
    if (screen.queryByRole("button", { name: /^(Continue|Try it yourself)$/ })) return;
    await tick();
  }
  throw new Error("Replay did not pause.");
}

async function finishExample() {
  for (let index = 0; index < 300; index++) {
    if (screen.queryByText("Replay complete")) return;
    await tick();
  }
  throw new Error("Example did not finish.");
}

describe("replay experiences", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) => values.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
    });
    reducedMotion = false;
    narrow = false;
    fetchMock.mockReset().mockResolvedValue(Response.json([]));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: query.includes("reduced-motion") ? reducedMotion : narrow,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));
    vi.spyOn(api, "streamMessage");
    vi.spyOn(api, "sendMessage");
  });

  afterEach(() => {
    expect(api.streamMessage).not.toHaveBeenCalled();
    expect(api.sendMessage).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.filter(([url, options]) => (
      String(url).includes("/api/messages") && options?.method === "POST"
    ))).toEqual([]);
    cleanup();
    expect(vi.getTimerCount()).toBe(0);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("auto-starts on a first visit even when the backend is offline, then remembers a skip", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    const view = await mount();
    expect(screen.getByText(introCaption.text)).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toHaveFocus();
    expect(screen.queryByText("Could not load conversations or history.")).not.toBeVisible();
    expect(document.querySelector(".chat-sidebar")).toHaveAttribute("data-replay-dimmed", "true");
    expect(document.querySelector(".replay-memory")).toHaveAttribute("data-replay-dimmed", "true");
    await user().click(screen.getByRole("button", { name: "Skip tour" }));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
    expect(localStorage.getItem("loupe.tourSeen")).toBe("true");
    expect(document.querySelector(".chat-sidebar")).toHaveAttribute("data-replay-dimmed", "false");
    view.unmount();
    await mount();
    expect(screen.queryByRole("region", { name: "Narrated replay" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Watch: running Python" })).toBeVisible();
  });

  it("respects stored completion and restores the live draft after Escape", async () => {
    localStorage.setItem("loupe.tourSeen", "true");
    await mount();
    expect(screen.queryByText(introCaption.text)).not.toBeInTheDocument();
    const keyboard = user();
    await keyboard.type(screen.getByRole("textbox", { name: "Message" }), "Keep my draft");
    await keyboard.click(screen.getByRole("button", { name: "Take the tour" }));
    await keyboard.keyboard("{Escape}");
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Keep my draft");
    await keyboard.click(screen.getByRole("button", { name: "Take the tour" }));
    expect(screen.getByText(introCaption.text)).toBeVisible();
  });

  it("pauses at every recorded step, accepts Enter and Space, and finishes with the exact saved reply", async () => {
    await mount();
    const keyboard = user();
    const replay = getReplay("memory-and-fetch");
    for (const event of replay.events.filter((item) => item.event === "step")) {
      await keyboard.keyboard("{Enter}");
      await reachPause();
      expect(screen.getByRole("status")).toHaveTextContent(captionForStep(event.data));
      expect(screen.getByRole("button", { name: "Continue" })).toHaveFocus();
      expect(document.querySelector(".replay-memory")).toHaveAttribute("data-replay-dimmed", "false");
    }
    await keyboard.keyboard(" ");
    await reachPause();
    expect(screen.getByText(closingCaption.text)).toBeVisible();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    const done = replay.events.at(-1);
    if (done?.event !== "done") throw new Error("Missing done event");
    expect(document.querySelector(".replay-exchange .answer-block")?.textContent).toBe(done.data.reply.content);
    expect(document.querySelectorAll(".replay-exchange .trace-step")).toHaveLength(done.data.reply.steps.length);
    await keyboard.click(screen.getByRole("button", { name: "Try it yourself" }));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
    expect(localStorage.getItem("loupe.tourSeen")).toBe("true");
  });

  it("cancels pending playback on restart, skip, and unmount", async () => {
    const view = await mount();
    const keyboard = user();
    await keyboard.click(screen.getByRole("button", { name: "Continue" }));
    await keyboard.click(screen.getByRole("button", { name: "Take the tour" }));
    await tick(10000);
    expect(screen.getByText(introCaption.text)).toBeVisible();
    expect(document.querySelectorAll(".replay-exchange .trace-step")).toHaveLength(0);
    await keyboard.click(screen.getByRole("button", { name: "Continue" }));
    await keyboard.click(screen.getByRole("button", { name: "Skip tour" }));
    await tick(10000);
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
    await keyboard.click(screen.getByRole("button", { name: "Take the tour" }));
    await keyboard.click(screen.getByRole("button", { name: "Continue" }));
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    ["Watch: running Python", "run-python"],
    ["Watch: recovering from a failure", "failure-recovery"],
  ] as const)("plays %s without captions or requests and closes to the empty state", async (label, id: ReplayId) => {
    localStorage.setItem("loupe.tourSeen", "true");
    await mount();
    const keyboard = user();
    fetchMock.mockClear();
    await keyboard.click(screen.getByRole("button", { name: label }));
    expect(screen.getByText(getReplay(id).question)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(screen.getByText("Red: error")).toBeVisible();
    await finishExample();
    const done = getReplay(id).events.at(-1);
    if (done?.event !== "done") throw new Error("Missing done event");
    expect(document.querySelector(".replay-exchange .answer-block")?.textContent).toBe(done.data.reply.content);
    expect(fetchMock).not.toHaveBeenCalled();
    await keyboard.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByText("Start the conversation below.")).toBeVisible();
    expect(screen.getByRole("button", { name: label })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
  });

  it("docks narrow-screen captions above the player and shows whole text with reduced motion", async () => {
    reducedMotion = true;
    narrow = true;
    await mount();
    const controls = document.querySelector(".replay-controls");
    if (!(controls instanceof HTMLElement)) throw new Error("Missing controls");
    expect(within(controls).getByRole("status")).toHaveTextContent(introCaption.text);
    const keyboard = user();
    await keyboard.click(screen.getByRole("button", { name: "Continue" }));
    await tick(0);
    expect(screen.getByRole("status")).toHaveTextContent("Pink steps are recalled memories.");
    await keyboard.keyboard("{Escape}");
    await keyboard.click(screen.getByRole("button", { name: "Watch: running Python" }));
    await tick(0);
    await tick(0);
    await tick(0);
    expect(document.querySelector(".replay-exchange .answer-block")?.textContent).toBe("The 40th Fibonacci number is **102,334,155**.");
  });

  it("works when localStorage throws and does not auto-start again during this page lifetime", async () => {
    vi.spyOn(localStorage, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(localStorage, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const view = await mount();
    expect(screen.getByText(introCaption.text)).toBeVisible();
    await user().click(screen.getByRole("button", { name: "Skip tour" }));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
    view.unmount();
    await mount();
    expect(screen.queryByText(introCaption.text)).not.toBeInTheDocument();
    await user().click(screen.getByRole("button", { name: "Take the tour" }));
    expect(screen.getByText(introCaption.text)).toBeVisible();
  });
});
