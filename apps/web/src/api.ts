import { locale, t, type MessageKey } from "./i18n";
import enCatalog from "./locales/en";

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`GET ${path}: ${response.status}`);
  }
  return response.json();
}

export async function apiPost(path: string, body: unknown): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`POST ${path}: ${response.status}`);
  }
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(locale(), {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(locale(), {
    day: "2-digit",
    month: "short",
  });
}

export const STATUS_KEYS = [
  "capturing",
  "queued_transcription",
  "transcribing",
  "queued_analysis",
  "analyzing",
  "ready",
  "failed",
] as const;

/** Backend status/event names are stable ids; the label comes from the catalog,
 * and an id we don't have a message for falls back to the id itself. */
export function statusLabel(status: string): string {
  const key = `status.${status}` as MessageKey;
  return key in enCatalog ? t(key) : status;
}

export function eventLabel(type: string): string {
  const key = `event.${type}` as MessageKey;
  return key in enCatalog ? t(key) : type;
}
