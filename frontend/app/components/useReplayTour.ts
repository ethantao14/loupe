"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import type { ReplayId } from "../demo/replay";

let completedWithoutStorage = false;

function shouldStartTour() {
  if (completedWithoutStorage) return false;
  try {
    return localStorage.getItem("loupe.tourSeen") === null;
  } catch {
    return true;
  }
}

export function useReplayTour(composer: RefObject<HTMLInputElement | null>) {
  const [session, setSession] = useState<{ id: ReplayId; key: number } | null>(null);
  const sequence = useRef(0);
  const focusComposer = useRef(false);

  const startReplay = useCallback((id: ReplayId) => {
    setSession({ id, key: ++sequence.current });
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (shouldStartTour()) startReplay("memory-and-fetch");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [startReplay]);

  const endReplay = useCallback(() => {
    if (session?.id === "memory-and-fetch") {
      try {
        localStorage.setItem("loupe.tourSeen", "true");
      } catch {
        completedWithoutStorage = true;
      }
    }
    focusComposer.current = true;
    setSession(null);
  }, [session]);

  useEffect(() => {
    if (session === null && focusComposer.current) {
      focusComposer.current = false;
      composer.current?.focus();
    }
  }, [session, composer]);

  return { session, startReplay, endReplay };
}
