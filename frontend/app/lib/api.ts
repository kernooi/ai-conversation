import { ChatRequest, ChatResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

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

// Voice: speech-to-text

export async function transcribe(audio: Blob): Promise<{ text: string; language: string }> {
  const form = new FormData();
  // Filename extension hints the backend at the container format
  form.append("audio", audio, "recording.webm");

  const res = await fetch(`${API_BASE}/transcribe`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Transcription error ${res.status}: ${await res.text()}`);
  return res.json() as Promise<{ text: string; language: string }>;
}

// Vision: image understanding

export async function analyzeImage(
  image: File,
  prompt?: string
): Promise<{ description: string; model: string }> {
  const form = new FormData();
  form.append("image", image, image.name || "image");
  form.append("prompt", prompt ?? "");

  const res = await fetch(`${API_BASE}/vision/analyze`, { method: "POST", body: form });
  if (!res.ok) throw new ApiError(res.status, `Vision error ${res.status}: ${await res.text()}`);
  return res.json() as Promise<{ description: string; model: string }>;
}

// Image generation

export async function generateImage(req: {
  prompt: string;
  image_context?: string;
  assistant_response?: string;
}): Promise<Blob> {
  const res = await fetch(`${API_BASE}/image/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new ApiError(res.status, `Image generation error ${res.status}: ${await res.text()}`);
  }
  return res.blob();
}

export async function startImageGeneration(req: {
  prompt: string;
  image_context?: string;
  assistant_response?: string;
  reference_image?: File;
}): Promise<{ job_id: string; status: string }> {
  if (req.reference_image) {
    const form = new FormData();
    form.append("prompt", req.prompt);
    if (req.image_context) form.append("image_context", req.image_context);
    if (req.assistant_response) form.append("assistant_response", req.assistant_response);
    form.append("reference_image", req.reference_image, req.reference_image.name || "reference.png");

    const res = await fetch(`${API_BASE}/image/generate/start`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      throw new ApiError(res.status, `Image generation error ${res.status}: ${await res.text()}`);
    }
    return res.json() as Promise<{ job_id: string; status: string }>;
  }

  const res = await fetch(`${API_BASE}/image/generate/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new ApiError(res.status, `Image generation error ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<{ job_id: string; status: string }>;
}

export async function getImageGenerationStatus(
  jobId: string
): Promise<{ job_id: string; status: string; error?: string | null }> {
  const res = await fetch(`${API_BASE}/image/generate/${jobId}`);
  if (!res.ok) {
    throw new ApiError(res.status, `Image generation status error ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<{ job_id: string; status: string; error?: string | null }>;
}

export async function getImageGenerationResult(jobId: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/image/generate/${jobId}/result`);
  if (!res.ok) {
    throw new ApiError(res.status, `Image generation result error ${res.status}: ${await res.text()}`);
  }
  return res.blob();
}

// Voice: text-to-speech (cloned voice)

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
  if (!res.ok) throw new ApiError(res.status, `TTS error ${res.status}: ${await res.text()}`);
  return res.blob();
}
