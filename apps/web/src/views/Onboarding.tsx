import { useState } from "react";

import { apiPost } from "../api";
import { t } from "../i18n";

/** Languages the analysis actually ships a stopword list and a sentiment
 * lexicon for. Offering anything else would store a language that reads as
 * Portuguese downstream. */
const STREAM_LANGUAGES = [
  { value: "en", label: "English" },
  { value: "pt", label: "Português" },
] as const;

/** The browser already knows; the streamer confirms rather than answers. */
function guessLanguage(): string {
  return navigator.language?.toLowerCase().startsWith("pt") ? "pt" : "en";
}

export default function Onboarding({ onDone }: { onDone: () => void }) {
  const [language, setLanguage] = useState(guessLanguage);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  async function submit() {
    setSaving(true);
    setFailed(false);
    try {
      await apiPost("/api/channel/onboarding", { stream_language: language });
      onDone();
    } catch {
      setFailed(true);
      setSaving(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 p-4 text-zinc-100">
      <div className="w-full max-w-md rounded-lg border border-zinc-800 bg-zinc-900 p-6">
        <h1 className="text-xl font-bold">{t("onboarding.title")}</h1>
        <p className="mt-2 text-sm text-zinc-400">{t("onboarding.why")}</p>

        <label className="mt-6 block text-sm font-medium" htmlFor="stream-language">
          {t("onboarding.language.label")}
        </label>
        <select
          id="stream-language"
          className="mt-2 w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2"
          value={language}
          onChange={(event) => setLanguage(event.target.value)}
        >
          {STREAM_LANGUAGES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        {failed && (
          <p role="alert" className="mt-4 text-sm text-red-400">
            {t("onboarding.failed")}
          </p>
        )}

        <button
          type="button"
          className="mt-6 w-full rounded bg-violet-600 px-4 py-2 font-medium disabled:opacity-50"
          onClick={submit}
          disabled={saving}
        >
          {saving ? t("onboarding.saving") : t("onboarding.submit")}
        </button>
      </div>
    </div>
  );
}
