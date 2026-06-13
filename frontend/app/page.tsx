"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { Message } from "@/app/lib/types";
import {
  analyzeImage,
  clearSession,
  getImageGenerationResult,
  getImageGenerationStatus,
  startImageGeneration,
  streamMessage,
} from "@/app/lib/api";
import { useSpeechQueue } from "@/app/lib/useSpeechQueue";
import ChatWindow from "@/app/components/ChatWindow";
import ChatInput, { PendingImage } from "@/app/components/ChatInput";
import VoiceControls from "@/app/components/VoiceControls";

// One session ID per browser tab, lives for the page lifetime
const SESSION_ID = uuidv4();

// Sentence terminators (Latin + CJK). Short fragments are held back so we don't
// split on "3.14" or "Mr."; the leftover is flushed when the stream ends.
const SENTENCE_END = /[.!?\u3002\uff01\uff1f\n]/;
const MIN_SENTENCE_LEN = 12;
const TTS_BATCH_MIN_CHARS = 90;
const TTS_BATCH_MAX_SENTENCES = 2;
const IMAGE_POLL_INTERVAL_MS = 2500;
const IMAGE_POLL_MAX_ATTEMPTS = 240;
const EXPLICIT_IMAGE_REQUEST =
  /\b(generate|draw|create|make|show|visuali[sz]e|render|image|picture|photo)\b|生成|画|圖片|图片|照片|圖像|图像/i;
const IMAGE_ACTION_REQUEST =
  /\b(running|run|walking|playing|jumping|flying|swimming|driving|wearing|turn .* into|imagine)\b|跑|奔跑|走|玩|跳|飞|飛|游泳|穿|变成|變成/i;

function joinSpeechParts(parts: string[]): string {
  return parts
    .join(" ")
    .replace(/\s+([,.!?;:\u3002\uff01\uff1f\uff0c\uff1b\uff1a])/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function extractSentences(buffer: string): { sentences: string[]; rest: string } {
  const sentences: string[] = [];
  let start = 0;
  for (let i = 0; i < buffer.length; i++) {
    if (SENTENCE_END.test(buffer[i])) {
      const piece = buffer.slice(start, i + 1).trim();
      if (piece.length >= MIN_SENTENCE_LEN) {
        sentences.push(piece);
        start = i + 1;
      }
    }
  }
  return { sentences, rest: buffer.slice(start) };
}

function shouldGenerateConversationImage(text: string, imageCount: number): boolean {
  if (EXPLICIT_IMAGE_REQUEST.test(text)) return true;
  if (imageCount > 0 && IMAGE_ACTION_REQUEST.test(text)) return true;
  return false;
}

async function waitForGeneratedImage(jobId: string): Promise<Blob> {
  for (let attempt = 0; attempt < IMAGE_POLL_MAX_ATTEMPTS; attempt++) {
    const status = await getImageGenerationStatus(jobId);
    if (status.status === "done") return getImageGenerationResult(jobId);
    if (status.status === "error") {
      throw new Error(status.error || "Image generation failed");
    }
    await new Promise((resolve) => setTimeout(resolve, IMAGE_POLL_INTERVAL_MS));
  }
  throw new Error("Image generation timed out while waiting for ComfyUI");
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Voice playback (TTS)
  const [voiceMode, setVoiceMode] = useState(false);
  const [voice, setVoice] = useState("default");
  const voiceModeRef = useRef(voiceMode);
  const voiceRef = useRef(voice);
  const messageImageUrlsRef = useRef<Set<string>>(new Set());
  useEffect(() => void (voiceModeRef.current = voiceMode), [voiceMode]);
  useEffect(() => void (voiceRef.current = voice), [voice]);
  useEffect(() => {
    const imageUrls = messageImageUrlsRef.current;
    return () => {
      for (const url of imageUrls) URL.revokeObjectURL(url);
      imageUrls.clear();
    };
  }, []);

  const speech = useSpeechQueue(voiceRef, (message) => {
    setError(message);
    setVoiceMode(false);
  });

  const handleSend = useCallback(
    async (text: string, images: PendingImage[] = []) => {
      const voiceOn = voiceModeRef.current;
      speech.reset(); // stop any current playback when a new turn starts

      const userMsg: Message = {
        id: uuidv4(),
        role: "user",
        content: text,
        images: images.map(({ id, name, url }) => ({ id, name, url })),
        timestamp: Date.now(),
      };
      for (const image of images) messageImageUrlsRef.current.add(image.url);
      const aiMsgId = uuidv4();
      const aiMsg: Message = {
        id: aiMsgId,
        role: "assistant",
        content: "",
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, userMsg, aiMsg]);
      setIsLoading(true);
      setError(null);

      let ttsBuffer = "";
      let imageContext = "";
      let assistantText = "";
      let speechBatch: string[] = [];
      const flushSpeechBatch = () => {
        if (!speechBatch.length) return;
        speech.enqueue(joinSpeechParts(speechBatch));
        speechBatch = [];
      };
      const enqueueSpeechSentences = (sentences: string[]) => {
        for (const sentence of sentences) {
          speechBatch.push(sentence);
          const batchText = joinSpeechParts(speechBatch);
          if (
            speechBatch.length >= TTS_BATCH_MAX_SENTENCES ||
            batchText.length >= TTS_BATCH_MIN_CHARS
          ) {
            speech.enqueue(batchText);
            speechBatch = [];
          }
        }
      };

      try {
        if (images.length > 0) {
          const analyses = await Promise.all(
            images.map(async (image, index) => {
              const result = await analyzeImage(image.file, text);
              return `Image ${index + 1} (${image.name}):\n${result.description}`;
            })
          );
          imageContext = analyses.join("\n\n");
        }

        for await (const chunk of streamMessage({
          message: text,
          session_id: SESSION_ID,
          image_context: imageContext || undefined,
        })) {
          assistantText += chunk;
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsgId ? { ...m, content: m.content + chunk } : m))
          );

          // Speak complete sentences as they arrive, overlapping generation
          if (voiceOn) {
            ttsBuffer += chunk;
            const { sentences, rest } = extractSentences(ttsBuffer);
            ttsBuffer = rest;
            enqueueSpeechSentences(sentences);
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        setError(msg);
        setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));
        setIsLoading(false);
        return;
      }

      // Flush any trailing text that never hit a sentence boundary
      if (voiceOn) {
        if (ttsBuffer.trim()) speechBatch.push(ttsBuffer.trim());
        flushSpeechBatch();
      }

      setIsLoading(false);

      if (shouldGenerateConversationImage(text, images.length)) {
        void (async () => {
          try {
            const job = await startImageGeneration({
              prompt: text,
              image_context: imageContext || undefined,
              assistant_response: assistantText || undefined,
              reference_image: images[0]?.file,
            });
            const blob = await waitForGeneratedImage(job.job_id);
            const url = URL.createObjectURL(blob);
            messageImageUrlsRef.current.add(url);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId
                  ? {
                      ...m,
                      images: [
                        ...(m.images ?? []),
                        { id: uuidv4(), name: "generated-image.png", url },
                      ],
                    }
                  : m
              )
            );
          } catch (err) {
            setError(err instanceof Error ? err.message : "Image generation failed");
          }
        })();
      }
    },
    [speech]
  );

  const handleNewChat = useCallback(async () => {
    speech.reset();
    for (const url of messageImageUrlsRef.current) URL.revokeObjectURL(url);
    messageImageUrlsRef.current.clear();
    setMessages([]);
    setError(null);
    setIsLoading(false);
    await clearSession(SESSION_ID).catch(() => null);
  }, [speech]);

  return (
    <div className="flex flex-col h-screen bg-zinc-950">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-zinc-800 bg-zinc-950 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center">
            <span className="text-white text-xs font-bold">AI</span>
          </div>
          <div>
            <h1 className="text-zinc-100 text-sm font-semibold leading-none">AI Assistant</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Local · Ollama + Whisper + CosyVoice3</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <VoiceControls
            voiceMode={voiceMode}
            onToggle={(on) => {
              setVoiceMode(on);
              if (on) speech.retry();
              if (!on) speech.reset();
            }}
            voice={voice}
            onVoiceChange={setVoice}
          />
          <button
            onClick={handleNewChat}
            className="text-zinc-400 hover:text-zinc-100 text-xs px-2.5 py-1.5 rounded-lg hover:bg-zinc-800 transition-colors"
          >
            New chat
          </button>
        </div>
      </header>

      {/* Error banner */}
      {error && (
        <div className="bg-red-950 border-b border-red-800 px-4 py-2 text-red-300 text-sm flex items-center justify-between shrink-0">
          <span>
            <strong>Error:</strong> {error}
          </span>
          <button
            onClick={() => setError(null)}
            className="text-red-400 hover:text-red-200 ml-4 text-lg leading-none"
          >
            ✕
          </button>
        </div>
      )}

      {/* Chat area */}
      <ChatWindow messages={messages} isLoading={isLoading} />

      {/* Input */}
      <ChatInput onSend={handleSend} disabled={isLoading} />
    </div>
  );
}
