export type Step = {
  id: string;
  kind: "thinking" | "tool_call" | "tool_result" | "tool_error" | "answer" | "memory";
  tool_name: string | null;
  detail: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  steps: Step[];
};

export type Memory = {
  id: string;
  fact: string;
  created_at: string;
};

export type Conversation = {
  id: string;
  title: string | null;
  created_at: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function parseOrThrow(response: Response): Promise<unknown> {
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}

export async function fetchConversations(): Promise<Conversation[]> {
  const response = await fetch(`${API_BASE}/api/conversations`);
  return (await parseOrThrow(response)) as Conversation[];
}

export async function fetchMessages(conversationId?: string): Promise<Message[]> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
  const response = await fetch(`${API_BASE}/api/messages${query}`);
  return (await parseOrThrow(response)) as Message[];
}

export async function fetchMemories(): Promise<Memory[]> {
  const response = await fetch(`${API_BASE}/api/memories`);
  return (await parseOrThrow(response)) as Memory[];
}

export async function deleteMemory(memoryId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/memories/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
}

export type SendResult = {
  conversation_id: string;
  user: Message;
  reply: Message;
};

export async function sendMessage(content: string, conversationId?: string): Promise<SendResult> {
  const response = await fetch(`${API_BASE}/api/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, conversation_id: conversationId }),
  });
  return (await parseOrThrow(response)) as SendResult;
}
