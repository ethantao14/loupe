const STORAGE_KEY = "loupe.visitorId";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
let visitorId: string | undefined;

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
    visitorId = crypto.randomUUID();
    try {
      window.localStorage.setItem(STORAGE_KEY, visitorId);
    } catch {
      // The in-memory identity lasts until the page is reloaded.
    }
  }
  return visitorId;
}
