"use client";

import { KeyboardEvent, useRef, useState } from "react";
import { transcribe } from "@/app/lib/api";
import { ImageAttachment } from "@/app/lib/types";
import { useRecorder } from "@/app/lib/useRecorder";

export interface PendingImage extends ImageAttachment {
  file: File;
}

interface Props {
  onSend: (text: string, images?: PendingImage[]) => void;
  disabled?: boolean;
  autoSendVoice?: boolean;
}

export default function ChatInput({ onSend, disabled, autoSendVoice = true }: Props) {
  const [value, setValue] = useState("");
  const [images, setImages] = useState<PendingImage[]>([]);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recorder = useRecorder();

  function resizeTextarea() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  function submit() {
    const trimmed = value.trim();
    if ((!trimmed && images.length === 0) || disabled) return;
    const outgoingImages = images;
    onSend(trimmed || "What do you see in this image?", outgoingImages);
    setValue("");
    setImages([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  function addImages(files: FileList | null) {
    if (!files) return;
    const remaining = Math.max(0, 4 - images.length);
    const next = Array.from(files)
      .filter((file) => file.type.startsWith("image/"))
      .slice(0, remaining)
      .map((file) => ({
        id: crypto.randomUUID(),
        file,
        name: file.name || "image",
        url: URL.createObjectURL(file),
      }));
    if (next.length) setImages((prev) => [...prev, ...next].slice(0, 4));
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removeImage(id: string) {
    setImages((prev) => {
      const image = prev.find((item) => item.id === id);
      if (image) URL.revokeObjectURL(image.url);
      return prev.filter((item) => item.id !== id);
    });
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
      const blob = await recorder.stop();
      if (!blob) return;
      setIsTranscribing(true);
      try {
        const { text } = await transcribe(blob);
        if (text) {
          if (autoSendVoice && !value.trim() && images.length === 0) {
            onSend(text);
          } else {
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
      <div className="max-w-3xl mx-auto">
        {images.length > 0 && (
          <div className="flex gap-2 mb-2 overflow-x-auto pb-1">
            {images.map((image) => (
              <div
                key={image.id}
                className="relative w-20 h-20 rounded-lg overflow-hidden bg-zinc-800 border border-zinc-700 shrink-0"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={image.url} alt={image.name} className="w-full h-full object-cover" />
                <button
                  type="button"
                  onClick={() => removeImage(image.id)}
                  className="absolute top-1 right-1 w-5 h-5 rounded-full bg-zinc-950/80 text-zinc-100 flex items-center justify-center hover:bg-zinc-900"
                  aria-label="Remove image"
                >
                  <CloseIcon />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          <button
            onClick={toggleRecording}
            disabled={isTranscribing || disabled}
            title={recorder.isRecording ? "Stop and transcribe" : "Record voice"}
            className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-colors mb-1 disabled:opacity-40 disabled:cursor-not-allowed ${
              recorder.isRecording
                ? "bg-red-600 text-white animate-pulse"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
            }`}
            aria-label={recorder.isRecording ? "Stop recording" : "Start recording"}
          >
            {isTranscribing ? <Spinner /> : recorder.isRecording ? <StopIcon /> : <MicIcon />}
          </button>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => addImages(e.target.files)}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={busy || images.length >= 4}
            title="Attach image"
            className="shrink-0 w-10 h-10 rounded-full bg-zinc-800 text-zinc-300 flex items-center justify-center hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors mb-1"
            aria-label="Attach image"
          >
            <ImageIcon />
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
                ? "Listening... tap the mic to stop"
                : isTranscribing
                  ? "Transcribing..."
                  : images.length
                    ? "Ask about the image..."
                    : "Type a message... (Enter to send, Shift+Enter for newline)"
            }
            className="flex-1 resize-none rounded-xl bg-zinc-800 text-zinc-100 placeholder-zinc-500 px-4 py-2.5 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 min-h-[42px]"
          />

          <button
            onClick={submit}
            disabled={busy || (!value.trim() && images.length === 0)}
            className="shrink-0 w-10 h-10 rounded-full bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-500 active:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors mb-1"
            aria-label="Send message"
          >
            <SendIcon />
          </button>
        </div>
      </div>

      {micError ? (
        <p className="text-red-400 text-xs text-center mt-1.5">{micError}</p>
      ) : (
        <p className="text-zinc-600 text-xs text-center mt-1.5">
          Tap the mic to speak - attach images for vision
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

function ImageIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
      <path
        fillRule="evenodd"
        d="M2.25 6A3.75 3.75 0 0 1 6 2.25h12A3.75 3.75 0 0 1 21.75 6v12A3.75 3.75 0 0 1 18 21.75H6A3.75 3.75 0 0 1 2.25 18V6ZM6 3.75A2.25 2.25 0 0 0 3.75 6v8.69l3.22-3.22a2.25 2.25 0 0 1 3.18 0l1.19 1.19 3.72-3.72a2.25 2.25 0 0 1 3.18 0l2.01 2.01V6A2.25 2.25 0 0 0 18 3.75H6Zm12.75 16.5H6A2.25 2.25 0 0 1 3.75 18v-1.19l4.28-4.28a.75.75 0 0 1 1.06 0l1.72 1.72a.75.75 0 0 0 1.06 0l4.25-4.25a.75.75 0 0 1 1.06 0l3.07 3.07V18a2.25 2.25 0 0 1-1.5 2.12v.13Z"
        clipRule="evenodd"
      />
      <path d="M8.25 8.25a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z" />
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

function CloseIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
      <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
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
