import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { fmtInt, fmtMoney, t } from "../i18n";
import type { FinanceOut } from "../types";

export default function FinanceSection({ streamId }: { streamId: number }) {
  const [finance, setFinance] = useState<FinanceOut | null>(null);

  useEffect(() => {
    apiGet<FinanceOut>(`/api/streams/${streamId}/finance`)
      .then(setFinance)
      .catch(() => setFinance(null));
  }, [streamId]);

  if (finance === null || finance.money_events === 0) return null;
  const maxTopic = Math.max(
    ...finance.by_topic.map((topic) => topic.estimated_usd),
    0.01,
  );

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">{t("financeSection.title")}</h3>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-emerald-900/60 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t("money.estimated")}</p>
          <p className="text-xl font-bold text-emerald-400">
            {fmtMoney(finance.estimated_usd)}
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t("money.bits")}</p>
          <p className="text-xl font-bold">{fmtInt(finance.total_bits)}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t("money.subs")}</p>
          <p className="text-xl font-bold">{fmtInt(finance.total_subs)}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t("money.gifts")}</p>
          <p className="text-xl font-bold">{fmtInt(finance.total_gifts)}</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {finance.top_contributors.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t("contributors.title")}
            </p>
            <div className="space-y-1.5 text-sm">
              {finance.top_contributors.map((contributor, index) => (
                <div
                  key={contributor.login}
                  className="flex items-center justify-between"
                >
                  <span>
                    <span className="mr-2 text-zinc-600">{index + 1}.</span>
                    <span className="text-purple-300">{contributor.login}</span>
                    <span className="ml-2 text-xs text-zinc-500">
                      {contributor.bits > 0 &&
                        t("financeSection.bits", { n: contributor.bits })}
                      {contributor.bits > 0 && contributor.subs > 0 && " · "}
                      {contributor.subs > 0 &&
                        t("financeSection.subs", { n: contributor.subs })}
                    </span>
                  </span>
                  <span className="font-semibold text-emerald-400">
                    {fmtMoney(contributor.estimated_usd)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {finance.by_topic.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t("financeSection.topTopics")}
            </p>
            <div className="space-y-2 text-sm">
              {finance.by_topic.map((topic) => (
                <div key={topic.name} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 truncate">{topic.name}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                    <div
                      className="h-full rounded bg-emerald-500"
                      style={{
                        width: `${(topic.estimated_usd / maxTopic) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right text-emerald-400">
                    {fmtMoney(topic.estimated_usd)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">{t("money.disclaimer")}</p>
    </div>
  );
}
