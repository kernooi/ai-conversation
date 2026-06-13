export type Role = "user" | "assistant";

export interface Message {
  id: string;
  role: Role;
  content: string;
  timestamp: number;
  images?: ImageAttachment[];
}

export interface ImageAttachment {
  id: string;
  name: string;
  url: string;
}

export interface Session {
  sessionId: string;
  messages: Message[];
  isLoading: boolean;
}

export interface ChatRequest {
  message: string;
  session_id: string;
  image_context?: string;
}

export interface ChatResponse {
  response: string;
  session_id: string;
}
