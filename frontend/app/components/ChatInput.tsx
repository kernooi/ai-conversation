"use client";

import { KeyboardEvent, useRef, useState } from "react";
import { transcribe } from "@/app/lib/api";
import { useRecorder } from "@/app/lib/useRecorder";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
  autoSendVoice?: boolean; // speak → transcribe → send immediately
}

export default function ChatInput({ onSend, disabled, autoSendVoice = true }: Props) {
  const [value, setValue] = useState("");
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recorder = useRecorder();

  function resizeTextarea() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  async function toggleRecording() {
    setMicError(null);
    if (recorder.isRecording) {
      // Stop → transcribe → drop text into the textarea
      const blob = await recorder.stop();
      if (!blob) return;
      setIsTranscribing(true);
      try {
        const { text } = await transcribe(blob);
        if (text) {
          if (autoSendVoice && !value.trim()) {
            // Voice conversation: send the spoken message straight away
            onSend(text);
          } else {
            // Append to whatever's already typed; user reviews + sends
            setValue((prev) => (prev ? `${prev} ${text}` : text));
            requestAnimationFrame(resizeTextarea);
          }
        }
      } catch (err) {
        setMicError(err instanceof Error ? err.message : "Transcription failed");
      } finally {
        setIsTranscribing(false);
      }
    } else {
      try {
        await recorder.start();
      } catch {
        setMicError("Microphone access denied or unavailable");
      }
    }
  }

  const busy = disabled || isTranscribing;

  return (
    <div className="border-t border-zinc-800 bg-zinc-950 px-4 py-3 shrink-0">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        {/* Push-to-talk */}
        <button
          onClick={toggleRecording}
          disabled={isTranscribing || disabled}
          title={recorder.isRecording ? "Stop & transcribe" : "Record voice"}
          className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-colors mb-1 disabled:opacity-40 disabled:cursor-not-allowed ${
            recorder.isRecording
              ? "bg-red-600 text-white animate-pulse"
              : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
          }`}
          aria-label={recorder.isRecording ? "Stop recording" : "Start recording"}
        >
          {isTranscribing ? <Spinner /> : recorder.isRecording ? <StopIcon /> : <MicIcon />}
        </button>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={resizeTextarea}
          disabled={busy}
          rows={1}
          placeholder={
            recorder.isRecording
              ? "Listening… tap the mic to stop"
              : isTranscribing
                ? "Transcribing…"
                : "Type a message… (Enter to send, Shift+Enter for newline)"
          }
          className="flex-1 resize-none rounded-xl bg-zinc-800 text-zinc-100 placeholder-zinc-500 px-4 py-2.5 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 min-h-[42px]"
        />

        <button
          onClick={submit}
          disabled={busy || !value.trim()}
          className="shrink-0 w-10 h-10 rounded-full bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-500 active:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors mb-1"
          aria-label="Send message"
        >
          <SendIcon />
        </button>
      </div>

      {micError ? (
        <p className="text-red-400 text-xs text-center mt-1.5">{micError}</p>
      ) : (
        <p className="text-zinc-600 text-xs text-center mt-1.5">
          Tap the mic to speak · Whisper STT + CosyVoice3 voice
        </p>
      )}
    </div>
  );
}

function MicIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
      <path d="M12 2a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3Z" />
      <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.92V20H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.08A7 7 0 0 0 19 11Z" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
      <path d="M3.478 2.405a.75.75 0 0 0-.926.94l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94 60.519 60.519 0 0 0 18.445-8.986.75.75 0 0 0 0-1.218A60.517 60.517 0 0 0 3.478 2.405Z" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg className="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4Z" />
    </svg>
  );
}
