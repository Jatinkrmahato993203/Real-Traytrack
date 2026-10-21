// Inspection drafts and the offline outbox live on the inspector's device.
export const DRAFT_KEY = (messId) => `tt_inspection_draft_${messId}`;
export const OUTBOX_KEY = "tt_inspection_outbox";

export function readJson(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}

export function writeJson(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch { /* storage full or blocked */ }
}

export const newRef = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
