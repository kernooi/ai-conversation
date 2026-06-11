"use client";

import { useEffect, useRef } from "react";
import { Message } from "@/app/lib/types";
import MessageBubble from "./MessageBubble";

interface Props {
  messages: Message[];
  isLoading: boolean;
}

export default function ChatWindow({ messages, isLoading }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const lastMsg = messages[messages.length - 1];
  // Show typing dots only while waiting for the FIRST chunk (AI placeholder not yet added)
  const showTypingDots = isLoading && lastMsg?.role !== "assistant";

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 min-h-0">
      <div className="max-w-3xl mx-auto">
        {messages.length === 0 && !isLoading && (
          <div className="flex flex-col items-center justify-center h-64 text-zinc-500 select-none">
            <div className="w-16 h-16 rounded-full bg-indigo-600/20 flex items-center justify-center mb-4">
              <span className="text-indigo-400 text-2xl font-bold">AI</span>
            </div>
            <p className="text-lg font-medium text-zinc-400">How can I help you?</p>
            <p className="text-sm mt-1">Start a conversation below</p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} isStreaming={isLoading && msg.id === messages[messages.length - 1]?.id} />
        ))}

        {showTypingDots && <TypingIndicator />}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-start mb-4">
      <div className="shrink-0 w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center mr-3">
        <span className="text-white text-xs font-bold">AI</span>
      </div>
      <div className="bg-zinc-800 rounded-2xl rounded-bl-sm px-4 py-3">
        <div className="flex gap-1.5 items-center h-4">
          <span className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce [animation-delay:0ms]" />
          <span className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce [animation-delay:150ms]" />
          <span className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}
