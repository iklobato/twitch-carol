import { useEffect, useState } from "react";
import { setLang, t } from "./i18n";
import Onboarding from "./views/Onboarding";
import { useRoute } from "./router";
import ChannelView from "./views/ChannelView";
import FinanceView from "./views/FinanceView";
import FollowersView from "./views/FollowersView";
import Landing from "./views/Landing";
import StreamReport from "./views/StreamReport";
import StreamsList from "./views/StreamsList";
import SearchView from "./views/SearchView";
import SettingsView from "./views/SettingsView";
import Sidebar from "./components/Sidebar";
import type { ChannelOption, Me } from "./types";

function SearchBox() {
  const [value, setValue] = useState("");
  return (
    <form
      role="search"
      className="w-full sm:w-auto sm:max-w-md sm:flex-1"
      onSubmit={(event) => {
        event.preventDefault();
        if (value.trim().length >= 2) {
          window.location.hash = `#/search?q=${encodeURIComponent(value.trim())}`;
        }
      }}
    >
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={t("app.search.placeholder")}
        aria-label={t("app.search.placeholder")}
        className="min-h-11 w-full rounded-xl border border-line-strong bg-panel px-4 text-sm placeholder-ink-faint focus:border-accent focus:outline-none"
      />
    </form>
  );
}

function ImpersonatePicker() {
  const [options, setOptions] = useState<ChannelOption[] | null>(null);
  useEffect(() => {
    fetch("/api/admin/channels")
      .then((response) => (response.ok ? response.json() : []))
      .then(setOptions)
      .catch(() => setOptions([]));
  }, []);

  async function impersonate(login: string) {
    if (!login) return;
    await fetch(`/api/admin/impersonate/${login}`, { method: "POST" });
    window.location.reload();
  }

  if (!options || options.length === 0) return null;
  return (
    <select
      defaultValue=""
      onChange={(event) => impersonate(event.target.value)}
      aria-label={t("app.impersonate.placeholder")}
      className="min-h-11 rounded-lg border border-line-strong bg-panel px-2 text-sm text-ink-muted focus:border-accent focus:outline-none"
    >
      <option value="" disabled>
        {t("app.impersonate.placeholder")}
      </option>
      {options.map((option) => (
        <option key={option.login} value={option.login}>
          {option.display_name} (@{option.login})
        </option>
      ))}
    </select>
  );
}

function ImpersonationBanner({ login }: { login: string }) {
  async function stop() {
    await fetch("/api/admin/impersonate/stop", { method: "POST" });
    window.location.reload();
  }
  return (
    <div className="flex items-center justify-center gap-3 bg-red-700 px-4 py-2 text-sm text-white">
      <span>
        {t("app.impersonate.viewingAs")} <strong>@{login}</strong>
      </span>
      <button
        onClick={stop}
        className="rounded bg-red-900 px-2 py-0.5 hover:bg-red-950"
      >
        {t("app.impersonate.stop")}
      </button>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const route = useRoute();

  useEffect(() => {
    // The screen language is fixed once, before the first render that has
    // content: the channel's own language when signed in, the browser's while
    // signed out on the landing page.
    fetch("/api/me")
      .then((response) => (response.ok ? response.json() : null))
      .then((current: Me | null) => {
        setLang(current?.language ?? navigator.language);
        setMe(current);
      })
      .catch(() => {
        setLang(navigator.language);
        setMe(null);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-canvas p-8 font-sans text-ink-muted">
        {t("app.loading")}
      </div>
    );
  }
  if (!me) {
    return <Landing />;
  }
  // A gate, not a suggestion: every screen below reads the chat and the speech
  // in a language this channel has not declared yet.
  if (me.needs_onboarding) {
    return (
      <Onboarding onDone={() => setMe({ ...me, needs_onboarding: false })} />
    );
  }

  return (
    <div className="min-h-screen bg-canvas font-sans text-ink">
      {me.impersonating && (
        <ImpersonationBanner login={me.impersonating.as_login} />
      )}
      <div className="md:flex">
        <Sidebar route={route} />
        <div className="min-w-0 flex-1">
          <header className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 pt-5 md:px-8">
            <SearchBox />
            <div className="flex items-center gap-3 text-sm">
              {me.is_admin && <ImpersonatePicker />}
              <span className="text-ink-muted">@{me.login}</span>
              <a
                href="/auth/logout"
                className="inline-flex min-h-11 items-center text-ink-faint hover:text-ink"
              >
                {t("app.logout")}
              </a>
            </div>
          </header>
          <main className="mx-auto max-w-5xl px-4 py-6 md:px-8">
            {route.view === "home" && <StreamsList />}
            {route.view === "channel" && <ChannelView />}
            {route.view === "audience" && <FollowersView />}
            {route.view === "money" && <FinanceView />}
            {route.view === "settings" && <SettingsView me={me} />}
            {route.view === "stream" && (
              <StreamReport streamId={route.streamId} />
            )}
            {route.view === "search" && <SearchView query={route.query} />}
          </main>
        </div>
      </div>
    </div>
  );
}
