"use client";

import { useCallback, useRef, useState } from "react";

interface Recorder {
  isRecording: boolean;
  start: () => Promise<void>;
  stop: () => Promise<Blob | null>;
  cancel: () => void;
}

/**
 * Records microphone audio via MediaRecorder.
 * start() begins capture; stop() resolves with the recorded Blob (webm/opus).
 */
export function useRecorder(): Recorder {
  const [isRecording, setIsRecording] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const cleanup = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    mediaRef.current = null;
    chunksRef.current = [];
    setIsRecording(false);
  }, []);

  const start = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    chunksRef.current = [];

    const recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.start();
    mediaRef.current = recorder;
    setIsRecording(true);
  }, []);

  const stop = useCallback(async (): Promise<Blob | null> => {
    const recorder = mediaRef.current;
    if (!recorder) return null;

    return new Promise<Blob | null>((resolve) => {
      recorder.onstop = () => {
        const blob = chunksRef.current.length
          ? new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" })
          : null;
        cleanup();
        resolve(blob);
      };
      recorder.stop();
    });
  }, [cleanup]);

  const cancel = useCallback(() => {
    if (mediaRef.current && mediaRef.current.state !== "inactive") {
      mediaRef.current.onstop = null;
      mediaRef.current.stop();
    }
    cleanup();
  }, [cleanup]);

  return { isRecording, start, stop, cancel };
}
