# Broadcast beta streamers, English

Date: 2026-08-13
Sender: `Henrique <henrique@send.streamintel.cc>` | reply-to: the same address
List: rows with `language=en` in `data/campaign/lote-*.csv`
HTML body: `ai-generated-messages/broadcast-body-en.html`
No merge tags: the list only has the email and the language, no name, no channel.

The body is not new. It was written on `feat/campanha-beta` together with the
sender that reads it, and this file brings it onto the mainline with the batch
column that feeds it. Subject there: `I built a tool that analyses your Twitch
streams (free while in beta)`.

## What still has to happen before a single English email goes out

The sender already handles two languages. `scripts/send_campaign_batch.py`
(on `feat/campanha-beta`, not here) keeps one body and one subject per language
and reads the language per row, defaulting a column-less old batch to
Portuguese. What blocks English is one layer above it:

- The Apify actor keeps its queue as bare addresses in the Key-Value Store, so
  the language never reaches the send call. It refuses `idiomas=en` on purpose
  rather than mail a Portuguese invite to someone who cannot read it.
- The actor image ships only the Portuguese body.

So the order is: queue carries the language -> image carries both bodies ->
turn the language on in the actor input.

## Where the language comes from

`scripts/build_campaign_batches.py` now writes `email,language` on every row.
It reads a `language` column when the source has one (which is what
`prospect_leads.py` records at collection time) and otherwise takes `--language`
for the whole run:

```bash
uv run python scripts/build_campaign_batches.py --source leads-en.csv
uv run python scripts/build_campaign_batches.py --source leads-en.txt --language en
```

It never guesses. A list with no language stops the run, because guessing is
exactly the bug: the guess would be Portuguese.
