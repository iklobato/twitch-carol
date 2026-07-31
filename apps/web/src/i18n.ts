// Screen language. Picked once at boot from the signed-in channel's language
// (channels.language, captured from Helix) and, while signed out, from the
// browser. It never changes mid-session, so a plain module variable is enough:
// no context, no provider, no re-render plumbing.

import en from "./locales/en";
import pt from "./locales/pt";

export type Lang = "en" | "pt";
export type MessageKey = keyof typeof en;

const CATALOGS: Record<Lang, Record<MessageKey, string>> = { en, pt };
const LOCALES: Record<Lang, string> = { en: "en-US", pt: "pt-BR" };

let current: Lang = "en";

/** Narrows any BCP-47 tag ("pt", "pt-BR", "en-GB") to a catalog we ship. */
export function resolveLang(tag: string | null | undefined): Lang {
  return tag?.toLowerCase().startsWith("pt") ? "pt" : "en";
}

export function setLang(tag: string | null | undefined): void {
  current = resolveLang(tag);
  if (typeof document !== "undefined") {
    document.documentElement.lang = LOCALES[current];
  }
}

export function lang(): Lang {
  return current;
}

export function locale(): string {
  return LOCALES[current];
}

/** Looks a message up and fills `{name}` placeholders. */
export function t(
  key: MessageKey,
  params?: Record<string, string | number>,
): string {
  const message = CATALOGS[current][key];
  if (params === undefined) return message;
  return message.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    name in params ? String(params[name]) : placeholder,
  );
}

export function fmtInt(value: number): string {
  return value.toLocaleString(locale());
}

export function fmtMoney(value: number): string {
  return value.toLocaleString(locale(), { style: "currency", currency: "USD" });
}
