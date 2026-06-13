"use client";

import { RefObject, useCallback, useRef } from "react";
import { ApiError, synthesizeSpeech } from "./api";

/**
 * Plays synthesized speech chunks with overlap:
 * each enqueued chunk starts synthesizing immediately, while playback happens
 * strictly in enqueue order. The page decides chunk size so TTS does not have
 * to pay model overhead for every tiny sentence.
 */
export function useSpeechQueue(voiceRef: RefObject<string>, onError?: (message: string) => void) {
  const queueRef = useRef<Array<Promise<Blob | null>>>([]);
  const playingRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const endCurrentRef = useRef<(() => void) | null>(null);
  const unavailableRef = useRef(false);
  const reportedErrorRef = useRef(false);
  // Bumped on reset to invalidate any in-flight playback/queue
  const tokenRef = useRef(0);

  const playBlob = useCallback((blob: Blob) => {
    return new Promise<void>((resolve) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      const finish = () => {
        URL.revokeObjectURL(url);
        endCurrentRef.current = null;
        resolve();
      };
      endCurrentRef.current = finish;
      audio.onended = finish;
      audio.onerror = finish;
      audio.play().catch(finish);
    });
  }, []);

  const drain = useCallback(async () => {
    if (playingRef.current) return;
    playingRef.current = true;
    const token = tokenRef.current;

    while (queueRef.current.length) {
      const next = queueRef.current.shift()!;
      let blob: Blob | null = null;
      try {
        blob = await next;
      } catch {
        blob = null;
      }
      if (token !== tokenRef.current) break; // reset happened mid-synth
      if (blob) await playBlob(blob);
      if (token !== tokenRef.current) break; // reset happened mid-playback
    }
    playingRef.current = false;
  }, [playBlob]);

  const enqueue = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t || unavailableRef.current) return;
      // Fire synthesis immediately so it overlaps prior playback
      queueRef.current.push(
        synthesizeSpeech(t, voiceRef.current).catch((err) => {
          if (err instanceof ApiError && err.status === 412) {
            unavailableRef.current = true;
            queueRef.current = [];
          }
          if (!reportedErrorRef.current) {
            reportedErrorRef.current = true;
            onError?.(err instanceof Error ? err.message : "TTS failed");
          }
          return null;
        })
      );
      void drain();
    },
    [drain, onError, voiceRef]
  );

  const reset = useCallback(() => {
    tokenRef.current += 1;
    queueRef.current = [];
    reportedErrorRef.current = false;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    // Unblock any drain loop awaiting the current clip
    if (endCurrentRef.current) {
      const finish = endCurrentRef.current;
      endCurrentRef.current = null;
      finish();
    }
    playingRef.current = false;
  }, []);

  const retry = useCallback(() => {
    unavailableRef.current = false;
    reportedErrorRef.current = false;
  }, []);

  return { enqueue, reset, retry };
}
