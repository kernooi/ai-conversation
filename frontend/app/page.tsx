"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { Message } from "@/app/lib/types";
import { streamMessage, clearSession } from "@/app/lib/api";
import { useSpeechQueue } from "@/app/lib/useSpeechQueue";
import ChatWindow from "@/app/components/ChatWindow";
import ChatInput from "@/app/components/ChatInput";
import VoiceControls from "@/app/components/VoiceControls";

// One session ID per browser tab, lives for the page lifetime
const SESSION_ID = uuidv4();

// Sentence terminators (Latin + CJK). Short fragments are held back so we don't
// split on "3.14" or "Mr." — the leftover is flushed when the stream ends.
const SENTENCE_END = /[.!?。！？\n]/;
const MIN_SENTENCE_LEN = 12;

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

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Voice playback (TTS)
  const [voiceMode, setVoiceMode] = useState(false);
  const [voice, setVoice] = useState("default");
  const voiceModeRef = useRef(voiceMode);
  const voiceRef = useRef(voice);
  useEffect(() => void (voiceModeRef.current = voiceMode), [voiceMode]);
  useEffect(() => void (voiceRef.current = voice), [voice]);

  const speech = useSpeechQueue(voiceRef);

  const handleSend = useCallback(
    async (text: string) => {
      const voiceOn = voiceModeRef.current;
      speech.reset(); // stop any current playback when a new turn starts

      const userMsg: Message = {
        id: uuidv4(),
        role: "user",
        content: text,
        timestamp: Date.now(),
      };
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
      try {
        for await (const chunk of streamMessage({ message: text, session_id: SESSION_ID })) {
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsgId ? { ...m, content: m.content + chunk } : m))
          );

          // Speak complete sentences as they arrive, overlapping generation
          if (voiceOn) {
            ttsBuffer += chunk;
            const { sentences, rest } = extractSentences(ttsBuffer);
            ttsBuffer = rest;
            for (const s of sentences) speech.enqueue(s);
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
      if (voiceOn && ttsBuffer.trim()) speech.enqueue(ttsBuffer);

      setIsLoading(false);
    },
    [speech]
  );

  const handleNewChat = useCallback(async () => {
    speech.reset();
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
            <p className="text-zinc-500 text-xs mt-0.5">Local · Ollama + Whisper + XTTS</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <VoiceControls
            voiceMode={voiceMode}
            onToggle={(on) => {
              setVoiceMode(on);
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
