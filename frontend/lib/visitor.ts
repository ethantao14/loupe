const STORAGE_KEY = "loupe.visitorId";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
let visitorId: string | undefined;

// crypto.randomUUID exists only on HTTPS and localhost pages, so build a
// version 4 UUID from getRandomValues, which works on any origin.
function newVisitorId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function getVisitorId(): string {
  if (visitorId) return visitorId;
  try {
    // A corrupted value would make every request fail, so replace it instead.
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && UUID_PATTERN.test(saved) && /[1-9a-f]/i.test(saved)) visitorId = saved;
  } catch {
    // Keep the identity in memory when browser storage is unavailable.
  }
  if (!visitorId) {
    visitorId = newVisitorId();
    try {
      window.localStorage.setItem(STORAGE_KEY, visitorId);
    } catch {
      // The in-memory identity lasts until the page is reloaded.
    }
  }
  return visitorId;
}
