"use client";

import { Message } from "@/app/lib/types";

interface Props {
  message: Message;
  isStreaming?: boolean;
}

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function MessageBubble({ message, isStreaming }: Props) {
  const isUser = message.role === "user";
  const isEmpty = message.content === "" && !message.images?.length;

  return (
    <div className={`flex w-full mb-4 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div className="shrink-0 w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center mr-3 mt-1">
          <span className="text-white text-xs font-bold">AI</span>
        </div>
      )}

      <div className={`max-w-[72%] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div
          className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap wrap-break-word ${
            isUser
              ? "bg-indigo-600 text-white rounded-br-sm"
              : "bg-zinc-800 text-zinc-100 rounded-bl-sm"
          }`}
        >
          {message.images && message.images.length > 0 && (
            <div className="grid grid-cols-2 gap-2 mb-2">
              {message.images.map((image) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={image.id}
                  src={image.url}
                  alt={image.name}
                  className="max-h-48 w-full rounded-lg object-cover border border-white/15"
                />
              ))}
            </div>
          )}
          {isEmpty ? (
            // Blinking cursor while waiting for first chunk
            <span className="inline-block w-2 h-4 bg-zinc-400 rounded-sm animate-pulse align-middle" />
          ) : (
            <>
              {message.content}
              {/* Inline cursor while stream is still live */}
              {isStreaming && (
                <span className="inline-block w-0.5 h-4 bg-zinc-400 rounded-sm animate-pulse align-middle ml-0.5" />
              )}
            </>
          )}
        </div>
        {!isEmpty && (
          <span className="text-zinc-500 text-xs mt-1 px-1">{formatTime(message.timestamp)}</span>
        )}
      </div>

      {isUser && (
        <div className="shrink-0 w-8 h-8 rounded-full bg-zinc-600 flex items-center justify-center ml-3 mt-1">
          <span className="text-white text-xs font-bold">U</span>
        </div>
      )}
    </div>
  );
}
