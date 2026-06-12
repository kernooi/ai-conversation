import { ChatRequest, ChatResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function sendMessage(req: ChatRequest): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json() as Promise<ChatResponse>;
}

export async function* streamMessage(req: ChatRequest): AsyncGenerator<string> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (raw === "[DONE]") return;

      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        continue;
      }

      if (typeof parsed === "object" && parsed !== null && "error" in parsed) {
        throw new Error(String((parsed as { error: unknown }).error));
      }
      if (typeof parsed === "string") yield parsed;
    }
  }
}

export async function clearSession(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/session/${sessionId}`, { method: "DELETE" });
}

// ── Voice: speech-to-text ──

export async function transcribe(audio: Blob): Promise<{ text: string; language: string }> {
  const form = new FormData();
  // Filename extension hints the backend at the container format
  form.append("audio", audio, "recording.webm");

  const res = await fetch(`${API_BASE}/transcribe`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Transcription error ${res.status}: ${await res.text()}`);
  return res.json() as Promise<{ text: string; language: string }>;
}

// ── Voice: text-to-speech (cloned voice) ──

export async function listVoices(): Promise<{ voices: string[]; default: string }> {
  const res = await fetch(`${API_BASE}/voices`);
  if (!res.ok) throw new Error(`Voices error ${res.status}`);
  return res.json() as Promise<{ voices: string[]; default: string }>;
}

export async function synthesizeSpeech(
  text: string,
  voice?: string,
  language?: string
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice, language }),
  });
  if (!res.ok) throw new Error(`TTS error ${res.status}: ${await res.text()}`);
  return res.blob();
}
