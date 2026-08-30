/**
 * Conversation session id.
 *
 * The backend keys multi-turn context off this value, so it is persisted for
 * the browser tab and regenerated when the user clears the conversation.
 * It is an opaque random id: no personal data, nothing sensitive.
 */

const STORAGE_KEY = 'bi-assistant.session-id'

function createId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return 's-' + Math.random().toString(36).slice(2) + '-' + Date.now().toString(36)
}

export function loadSessionId(): string {
  try {
    const existing = sessionStorage.getItem(STORAGE_KEY)
    if (existing) return existing
    const created = createId()
    sessionStorage.setItem(STORAGE_KEY, created)
    return created
  } catch {
    // Private mode / storage disabled — an in-memory id still works.
    return createId()
  }
}

export function resetSessionId(): string {
  const created = createId()
  try {
    sessionStorage.setItem(STORAGE_KEY, created)
  } catch {
    /* storage unavailable — ignore */
  }
  return created
}
