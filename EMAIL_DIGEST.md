# Email digest (weekly/monthly recap)

Status as of 2026-09-21: built, verified end-to-end and **delivered** on the dev
app. Nothing on `main`. `dev` is 30 commits ahead (PRs #78-#87 built the
feature, PR #88 made it production-ready), and PR #89 (`dev` -> `main`) is open
and unmerged.

Production cannot send anything yet, for three separate reasons, in this order:

1. PR #89 is not merged, so neither the code nor migration `0026` is there
   (production alembic measured at `0024`).
2. The production app has no `RESEND_API_KEY`, no `DIGEST_FROM` and no
   `send-digests` job. Only `migrate` PRE_DEPLOY exists.
3. No channel has an email address yet. See "Where the email comes from".

## What it does

A weekly/monthly recap email per channel (`core/digest.py`), sent by an
hourly scheduled job (`scripts/send_email_digests.py`, app spec job
`send-digests`, `cron: 0 * * * *` UTC) once the channel's local clock hits
`DIGEST_SEND_HOUR` and `EmailDigestLog` shows nothing sent yet for that
channel+period+window.

Sections, in render order:
- Headline metrics (lives, chat messages, peak viewers, followers gained,
  revenue, duration) with a delta vs. the previous period and a comparison bar.
- Records broken this period.
- Most-monetized topics (only when at least one money event was attributed
  to a topic window).
- **Top lives**, ranked by revenue and by messages, each row heat-shaded by
  rank.
- Best moments (LLM-summarized chat spikes).
- Biggest single payments.
- Chat mood (sentiment), hidden below `MIN_SENTIMENT_MESSAGES`.
- Most engaged chatters and top payers.
- **Keep / Stop / Improve insights**: an LLM-written takeaway per bucket,
  each required to cite a real numbered fact computed from the digest (never
  invented, see "Insights" below).
- Clips saved.
- **Revenue by day**: a monthly-only calendar heat map, weekday header +
  color-scale legend, darker = more revenue.

## Insights (PR #86)

`core/digest_insights.py::build_digest_facts` computes up to ~11 numbered,
comparative facts per digest (never a bare total, to avoid a tautological
insight): revenue delta, top topics/categories by revenue, records, whale
concentration risk, $/hour by category, best time-of-day, chat-participation
ratio by category, sentiment vs. previous period, subscriber churn, top
redeemed reward.

`generate_digest_insights` asks the LLM for up to 8 takeaways, each tagged
`"keep"|"stop"|"improve"` and required to cite at least one fact id. An
insight with no valid cited fact, or an invalid category, is discarded, never
padded to hit a target count. The three buckets render as separate
mini-sections and only appear when non-empty.

## Formatting fixes (PR #87)

- **Top lives** titles are long free text (stream titles), unlike every
  other ranked list's short label (a login, a metric name). Without a capped
  width they pushed the value/heat-cell columns off the card in email
  clients that honor overflow. Now truncated with an ellipsis
  (`max-width:300px`).
- **Revenue by day** calendar had no weekday header and no color-scale key.
  Added a Mon-Sun header row and a Less→More shade legend.

## Verified in dev while building (PRs #85-#87)

Every round below was verified by a real Resend send to
`tiktachack@gmail.com` from the `streamintel-dev` app
(`3f70eb48-2543-4e97-a9ae-e008317dbbac`, `dev.streamintel.cc`), against
`iklobat`'s real production-shaped data, followed by regenerating the
identical HTML *inside the running container* and reading it directly, not
just trusting the 200 OK from Resend.

- **PR #85** (rankings + heat maps): confirmed Top lives (by revenue/by
  messages), Biggest single payments, Most engaged chatters + Top payers,
  and the monthly Revenue-by-day calendar all rendered correctly with real
  data.
- **PR #86** (categorized insights): confirmed 8 real insights generated
  (5 keep / 1 stop / 2 improve), every one citing a real numbered fact.
- **PR #87** (formatting fixes): confirmed in the regenerated HTML that a
  ~130-character real stream title now renders inside a truncating span,
  and that the calendar gained its `Mon..Sun` header row and the `Less →
  [5 swatches] → More` legend.

## Production readiness (PR #88)

Three things stood between the feature and production, all fixed on
`fix/digest-prod-readiness`:

- **A timed-out send could email the same recap twice.** `send_email` only
  raised `MailerError` on an HTTP status, so an `httpx` timeout escaped
  uncaught: it aborted the hourly run at that channel, and the rollback on the
  way out released the reservation, so the next run sent a digest Resend may
  already have accepted. `MailerUncertain` now marks "no answer came back" and
  the sender KEEPS the reservation, letting the unique constraint block the
  retry. A plain `MailerError` still means nothing was sent, and still retries.
- **The category-engagement fact read as a broken number.** Unique chatters are
  counted over a whole broadcast while peak viewers is a single instant, so the
  ratio legitimately exceeds 1 and the old wording produced "136% of the peak
  audience chatted". It now reads as chatters per peak viewer.
- **The `send-digests` job was not in the app spec.** It existed only on the dev
  app, created by hand in the dashboard, so `deploy/app.yaml` described an app
  that could not send. The job and the two settings are now in the file.
  `DIGEST_RECIPIENT_OVERRIDE` is deliberately absent from it: it exists so dev
  never emails a real streamer, and in production it would divert every digest
  to a single address.

Also fixed there: `tests/test_send_email_digests.py` pinned `NOW` to a fixed
date while `make_stream` places a live relative to the real clock, so 6 of its 9
tests had quietly degraded to `skipped (no lives)`. `NOW` is now anchored to
today.

## Verified on the dev app after PR #88

A real monthly digest for `iklobat`, Resend message
`01a0c46d-3629-72b9-bc2c-8f4e94fbd7a7`. Delivery confirmed at the provider
(`GET /emails/<id>` returned `last_event: delivered`), not inferred from the
200. The digest was then rebuilt inside the running container and read: 11
facts, 8 insights, each citing a real fact, and fact [8] came out as `In
'League of Legends' lives, 1.36 unique chatters per peak viewer this period,
7.6x 'ROBLOX' lives (0.18)`: real data landing exactly on the bug the wording
fix addressed. A second run answered `skipped (already sent)`, and
`email_digest_log` holds `sent_at` plus the provider id.

Not proven live: the `MailerUncertain` path, which would need a real Resend
timeout. It is covered by unit tests only.

## Where the email comes from

`channels.email` is filled from the Twitch login grant (`user:read:email`) in
`core/channels.py`, and nowhere else. Every channel that logged in before that
scope existed has `email` null, and the job answers `skipped (no recipient)`
for them.

Nothing was built to force a re-login, on purpose. `SESSION_MAX_AGE_SECONDS` is
7 days and the cookie is written only in `/auth/callback`, never slid by another
route, so every streamer passes back through `/auth/login` within a week and
fills their own email. Forcing it would buy "next visit" instead of "within 7
days", worth at most one missed weekly recap per streamer, once. A streamer who
never returns gets no digest either way.

If it is ever built, `/api/me` already carries `email`, `digest_weekly`,
`digest_monthly` and `impersonating`, so it is a frontend-only gate in
`App.tsx` next to `needs_onboarding`, and it MUST carry a one-shot
`sessionStorage` mark: an account with no verified Twitch email would otherwise
bounce to `/auth/login` forever.

## Promoting to production

1. Merge PR #89. Migration `0026` runs in the existing `migrate` PRE_DEPLOY job;
   it is additive only (three columns with constant defaults plus one new
   table), so the old containers keep serving correctly against the new schema
   while it applies.
2. Set `RESEND_API_KEY` and `DIGEST_FROM` on the production app, scoped to the
   `send-digests` component so the key never enters the api or worker
   environment. Leave `DIGEST_RECIPIENT_OVERRIDE` unset.
3. Apply the spec with `doctl apps update --spec`, so the job exists. A git push
   does NOT apply `deploy/app.yaml`: App Platform runs the spec it already
   holds. Build that spec from `doctl apps spec get` output, never from the repo
   file, whose secrets are valueless names that would wipe the live ones.

Fastest kill switch, before any email has gone out, needs no deploy:
`update channels set digest_weekly = false, digest_monthly = false`.

## Known gaps / caveats (not bugs introduced by this work)

- **Most-monetized topics** didn't render for `iklobat` this month: real
  data had zero money events attributable to any topic window. Pre-existing
  gate (`if digest.topic_revenue:`), unaffected by this cycle's changes:
  a data gap for this specific channel/period, not a code defect.
- **Category-engagement fact could read above 100%**: fixed in PR #88, see
  "Production readiness" above.

## Delivery metrics: none

Nothing consumes Resend's webhooks, and `EmailDigestLog` stores only the
provider message id, so opens, clicks and bounces are invisible from here. The
cheapest check today is `GET https://api.resend.com/emails/<id>`, which returns
`last_event`. A webhook consumer is the obvious next piece of work if this ever
needs to be measured rather than spot-checked.

## Testing this against the dev app

The dev database has one channel (`iklobat`, `America/Sao_Paulo`) and 87
streams, all between 2026-07-14 and 2026-08-05. Only a MONTHLY digest with
`--now` in September has data behind it; weekly always answers
`skipped (no lives)`.

    python scripts/send_email_digests.py --channel iklobat --period monthly \
      --now 2026-09-21T11:00:00+00:00

11:00 UTC is 08:00 in Sao Paulo, which is `DIGEST_SEND_HOUR`. A bare date string
parses to midnight UTC and silently reports "not due yet". To send the same
window twice, delete that channel's `email_digest_log` row first.

Running it inside the container needs a TTY wrapper, because `doctl apps
console` fails with `inappropriate ioctl for device` when piped:

    (echo '<command>'; sleep 30; echo exit) \
      | script -q /dev/null doctl apps console <app-id> api
