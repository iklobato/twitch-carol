import { useEffect, useState } from "react";
import { apiGet, formatTime } from "../api";
import { fmtInt, t, type MessageKey } from "../i18n";
import type { ChatterOut } from "../types";

// The API sends stable keys; wording and colour both live here.
const LABEL_COLOR: Record<string, string> = {
  followed: "border-emerald-800 text-emerald-400",
  peak_active: "border-orange-800 text-orange-400",
};

function LabelChip({ label }: { label: string }) {
  const color = LABEL_COLOR[label] ?? "border-zinc-700 text-zinc-400";
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] ${color}`}>
      {t(`chatterLabel.${label}` as MessageKey)}
    </span>
  );
}

function ChatterRow({
  chatter,
  maxMessages,
}: {
  chatter: ChatterOut;
  maxMessages: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-2 rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => setOpen(!open)}
          className="min-w-32 text-left text-sm font-semibold text-purple-300 hover:text-purple-200"
        >
          {chatter.author_login}
        </button>
        <div className="hidden w-40 md:block">
          <div className="h-2 overflow-hidden rounded bg-zinc-800">
            <div
              className="h-full rounded bg-purple-500"
              style={{ width: `${(chatter.messages / maxMessages) * 100}%` }}
            />
          </div>
        </div>
        <span className="text-xs tabular-nums text-zinc-400">
          {t("chatters.msgs", { n: fmtInt(chatter.messages) })} ·{" "}
          {t("chatters.pctOfChat", { pct: chatter.pct_of_total })} ·{" "}
          {t("chatters.activeMinutes", { n: chatter.active_minutes })}
          {chatter.peak_messages > 0 &&
            ` · ${t("chatters.inPeaks", { n: chatter.peak_messages })}`}
          {chatter.sentiment_score !== null && (
            <>
              {" · "}
              <span
                className={
                  chatter.sentiment_score > 0.15
                    ? "text-emerald-400"
                    : chatter.sentiment_score < -0.15
                      ? "text-red-400"
                      : "text-zinc-400"
                }
              >
                {t("chatters.sentiment")}{" "}
                {chatter.sentiment_score > 0 ? "+" : ""}
                {chatter.sentiment_score}
              </span>
            </>
          )}
        </span>
        <span className="flex flex-wrap gap-1">
          {chatter.labels.map((label) => (
            <LabelChip key={label} label={label} />
          ))}
        </span>
      </div>
      {open && (
        <div className="mt-2 space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-sm">
          {chatter.top_words.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                {t("words.mostUsed")}
              </p>
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                {chatter.top_words.map((word) => (
                  <span
                    key={word.word}
                    title={t("words.times", { n: word.count })}
                    className="text-purple-300"
                    style={{ fontSize: `${12 + Math.min(word.count, 10)}px` }}
                  >
                    {word.word}
                  </span>
                ))}
              </div>
            </div>
          )}
          <div>
            <p className="mb-1 text-xs text-zinc-500">
              {t("chatters.firstLast", {
                first: formatTime(chatter.first_at),
                last: formatTime(chatter.last_at),
              })}
            </p>
            {chatter.sample_messages.map((message, index) => (
              <p key={index}>
                <span className="tabular-nums text-zinc-500">
                  {formatTime(message.sent_at)}
                </span>{" "}
                {message.text}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const PAGE_SIZE = 5;

type SortKey =
  | "messages"
  | "pct_of_total"
  | "active_minutes"
  | "peak_messages"
  | "sentiment_score";

const SORT_KEYS: SortKey[] = [
  "messages",
  "pct_of_total",
  "active_minutes",
  "peak_messages",
  "sentiment_score",
];

function sortValue(chatter: ChatterOut, key: SortKey): number {
  const value = chatter[key];
  // null sentiment sorts to the bottom
  return value === null ? -Infinity : value;
}

export default function ChattersSection({ streamId }: { streamId: number }) {
  const [chatters, setChatters] = useState<ChatterOut[] | null>(null);
  const [page, setPage] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("messages");

  useEffect(() => {
    setPage(0);
    apiGet<ChatterOut[]>(`/api/streams/${streamId}/chatters`).then(setChatters);
  }, [streamId]);

  if (chatters === null || chatters.length === 0) return null;
  const maxMessages = Math.max(
    ...chatters.map((chatter) => chatter.messages),
    1,
  );
  const sorted = [...chatters].sort(
    (a, b) => sortValue(b, sortKey) - sortValue(a, sortKey),
  );
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const visible = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="mb-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-bold">{t("chatters.title")}</h3>
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <span className="mr-1 text-zinc-500">{t("chatters.sortBy")}</span>
          {SORT_KEYS.map((key) => (
            <button
              key={key}
              onClick={() => {
                setSortKey(key);
                setPage(0);
              }}
              className={`rounded-full border px-2.5 py-0.5 ${
                sortKey === key
                  ? "border-purple-500 bg-purple-950 text-purple-200"
                  : "border-zinc-700 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {t(`chatters.sort.${key}` as MessageKey)}
            </button>
          ))}
        </div>
      </div>
      {visible.map((chatter) => (
        <ChatterRow
          key={chatter.author_login}
          chatter={chatter}
          maxMessages={maxMessages}
        />
      ))}
      {totalPages > 1 && (
        <div className="mt-2 flex items-center justify-center gap-4 text-sm">
          <button
            onClick={() => setPage(page - 1)}
            disabled={page === 0}
            className="rounded border border-zinc-700 px-3 py-1 text-zinc-400 hover:text-zinc-200 disabled:opacity-40 disabled:hover:text-zinc-400"
          >
            {t("chatters.prev")}
          </button>
          <span className="tabular-nums text-zinc-500">
            {t("chatters.page", { page: page + 1, total: totalPages })}
          </span>
          <button
            onClick={() => setPage(page + 1)}
            disabled={page >= totalPages - 1}
            className="rounded border border-zinc-700 px-3 py-1 text-zinc-400 hover:text-zinc-200 disabled:opacity-40 disabled:hover:text-zinc-400"
          >
            {t("chatters.next")}
          </button>
        </div>
      )}
    </div>
  );
}
