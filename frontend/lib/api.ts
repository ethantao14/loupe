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

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function parseOrThrow(response: Response): Promise<unknown> {
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}

export async function fetchMessages(): Promise<Message[]> {
  const response = await fetch(`${API_BASE}/api/messages`);
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
  user: Message;
  reply: Message;
};

export async function sendMessage(content: string): Promise<SendResult> {
  const response = await fetch(`${API_BASE}/api/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return (await parseOrThrow(response)) as SendResult;
}
