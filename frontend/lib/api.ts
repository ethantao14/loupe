import { getVisitorId } from "./visitor";

export const STEP_KINDS = [
  "thinking", "tool_call", "tool_result", "tool_error", "tool_repeat", "answer", "memory",
] as const;

export type StepKind = typeof STEP_KINDS[number];

export type Step = {
  id: string;
  kind: StepKind;
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

export class MessageRequestError extends Error {
  constructor(public readonly status: 429 | 422, detail: string) {
    super(detail);
    this.name = "MessageRequestError";
  }
}

async function checkResponse(response: Response): Promise<void> {
  if (response.ok) return;
  if (response.status === 429 || response.status === 422) {
    const payload: unknown = await response.json().catch(() => null);
    if (isRecord(payload) && typeof payload.detail === "string") {
      throw new MessageRequestError(response.status, payload.detail);
    }
  }
  throw new Error(`Request failed with status ${response.status}`);
}

async function parseOrThrow(response: Response): Promise<unknown> {
  await checkResponse(response);
  return response.json();
}

export async function fetchConversations(): Promise<Conversation[]> {
  const response = await fetch(`${API_BASE}/api/conversations`, {
    headers: { "X-Visitor-Id": getVisitorId() },
  });
  return (await parseOrThrow(response)) as Conversation[];
}

export async function renameConversation(conversationId: string, title: string): Promise<Conversation> {
  const response = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-Visitor-Id": getVisitorId() },
    body: JSON.stringify({ title }),
  });
  return (await parseOrThrow(response)) as Conversation;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    headers: { "X-Visitor-Id": getVisitorId() },
  });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
}

export async function fetchMessages(conversationId?: string): Promise<Message[]> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
  const response = await fetch(`${API_BASE}/api/messages${query}`, {
    headers: { "X-Visitor-Id": getVisitorId() },
  });
  return (await parseOrThrow(response)) as Message[];
}

export async function fetchMemories(): Promise<Memory[]> {
  const response = await fetch(`${API_BASE}/api/memories`, {
    headers: { "X-Visitor-Id": getVisitorId() },
  });
  return (await parseOrThrow(response)) as Memory[];
}

export async function deleteMemory(memoryId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/memories/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
    headers: { "X-Visitor-Id": getVisitorId() },
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
    headers: { "Content-Type": "application/json", "X-Visitor-Id": getVisitorId() },
    body: JSON.stringify({ content, conversation_id: conversationId }),
  });
  return (await parseOrThrow(response)) as SendResult;
}

export type StreamStep = Omit<Step, "id">;

export type StreamHandlers = {
  onDelta: (text: string) => void;
  onStep: (step: StreamStep) => void;
  onDone: (result: SendResult) => void;
  onError: (detail: string) => void;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStreamStep(value: unknown): value is StreamStep {
  return isRecord(value)
    && typeof value.kind === "string"
    && STEP_KINDS.some((kind) => kind === value.kind)
    && (value.tool_name === null || typeof value.tool_name === "string")
    && typeof value.detail === "string";
}

function isMessage(value: unknown): value is Message {
  return isRecord(value)
    && typeof value.id === "string"
    && (value.role === "user" || value.role === "assistant")
    && typeof value.content === "string"
    && typeof value.created_at === "string"
    && Array.isArray(value.steps)
    && value.steps.every((step: unknown) => isStreamStep(step) && "id" in step
      && typeof step.id === "string");
}

function isSendResult(value: unknown): value is SendResult {
  return isRecord(value)
    && typeof value.conversation_id === "string"
    && isMessage(value.user)
    && isMessage(value.reply);
}

function dispatchStreamEvent(frame: string, handlers: StreamHandlers): boolean {
  let name = "";
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return false;
  const payload: unknown = JSON.parse(data.join("\n"));
  switch (name) {
    case "delta":
      if (isRecord(payload) && typeof payload.text === "string") {
        handlers.onDelta(payload.text);
        return false;
      }
      break;
    case "step":
      if (isStreamStep(payload)) {
        handlers.onStep(payload);
        return false;
      }
      break;
    case "done":
      if (isSendResult(payload)) {
        handlers.onDone(payload);
        return true;
      }
      break;
    case "error":
      if (isRecord(payload) && typeof payload.detail === "string") {
        handlers.onError(payload.detail);
        return true;
      }
      break;
    default:
      return false;
  }
  throw new Error(`Invalid ${name} event in message stream.`);
}

export async function streamMessage(
  content: string,
  conversationId: string | undefined,
  handlers: StreamHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Visitor-Id": getVisitorId() },
    body: JSON.stringify({ content, conversation_id: conversationId }),
  });
  await checkResponse(response);
  if (!response.body) throw new Error("Message stream has no response body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        if (dispatchStreamEvent(frame, handlers)) return;
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
      if (done) throw new Error("Message stream ended before a done or error event.");
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
