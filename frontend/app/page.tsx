"use client";

import { useCallback, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { Message } from "@/app/lib/types";
import { streamMessage, clearSession } from "@/app/lib/api";
import ChatWindow from "@/app/components/ChatWindow";
import ChatInput from "@/app/components/ChatInput";

// One session ID per browser tab, lives for the page lifetime
const SESSION_ID = uuidv4();

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const handleSend = useCallback(async (text: string) => {
    // Cancel any in-flight request
    abortRef.current?.abort();
    abortRef.current = new AbortController();

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

    try {
      for await (const chunk of streamMessage({ message: text, session_id: SESSION_ID })) {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, content: m.content + chunk } : m))
        );
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      // Remove the empty/partial AI message on hard failure
      setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleNewChat = useCallback(async () => {
    abortRef.current?.abort();
    setMessages([]);
    setError(null);
    setIsLoading(false);
    await clearSession(SESSION_ID).catch(() => null);
  }, []);

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
            <p className="text-zinc-500 text-xs mt-0.5">MythoMax-L2 13B · Ollama</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleNewChat}
            className="text-zinc-400 hover:text-zinc-100 text-xs px-2.5 py-1.5 rounded-lg hover:bg-zinc-800 transition-colors"
          >
            New chat
          </button>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span className="text-zinc-500 text-xs">Local</span>
          </div>
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
