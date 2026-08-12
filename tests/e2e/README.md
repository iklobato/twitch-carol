# Tests against a running environment

The suite under `tests/` proves the code is right on its own. This one proves a
deployment is right, which is a different question and the one that keeps being
answered by a human noticing something instead of by a test.

Everything here is a **GET**. Nothing is created, changed or deleted, so pointing
it at production is safe.

## Running it

```bash
# dev, everything that needs no session
E2E_BASE_URL=https://dev.streamintel.cc \
E2E_APP_ID=3f70eb48-2543-4e97-a9ae-e008317dbbac \
  pytest tests/e2e -q

# dev, including the checks that need a signed-in channel
E2E_BASE_URL=https://dev.streamintel.cc \
E2E_APP_ID=3f70eb48-2543-4e97-a9ae-e008317dbbac \
E2E_SESSION="$(: paste the `session` cookie from a signed-in browser)" \
  pytest tests/e2e -q

# production is the same, with its own app id
E2E_BASE_URL=https://streamintel.cc E2E_APP_ID=9154182f-3392-4bfd-b76c-8da53ea52aa9 ...
```

| variable | what it does |
|---|---|
| `E2E_BASE_URL` | required; without it the whole directory skips, so a normal `pytest` run is unaffected |
| `E2E_SESSION` | the `session` cookie value. Checks needing a channel skip without it |
| `E2E_APP_ID` | the DigitalOcean app, used to confirm the deployment runs this checkout |
| `E2E_WEB_URL` | only when the static site is on another host, e.g. vite on :5173 locally |

There is no API key or service account, so **the session cookie has to come from a
real browser sign-in**. Cookies are signed per `FERNET_KEY`, so a dev cookie will
not work against production and the failure says so.

## Why the route list comes from the checkout

The first version read `/openapi.json` from the environment, which would have been
better. It is not reachable: only `/api`, `/auth` and `/healthz` are routed to the
API component, so `/openapi.json` lands on the static site and 404s.

So routes are enumerated from `apps.api.main.app`, which only describes the
environment while the checkout matches what is deployed.
`test_the_checkout_matches_the_deployment` is the guard for exactly that, and it is
why `E2E_APP_ID` is worth passing. Without it that check skips and the rest of the
run is only as trustworthy as your working copy.

## The two halves

**`test_surface.py`** sorts every route into one category and asserts the sort is
total. A new endpoint that matches nothing fails the run by name.

That is the part that makes this a base rather than a snapshot: adding a route
forces a decision about what it owes an anonymous caller, instead of arriving
untested because nobody remembered it.

| category | what is expected |
|---|---|
| `public` | answers anyone, listed one path at a time and never by prefix |
| `listing` | 200 for its owner, 401/403/404/422 for a stranger |
| `by_id` | 404 for an id that is not yours, **never 403** |
| `admin` | 200 only for a login on the allowlist, 403 otherwise |
| `integration` | may answer 503 where the external account is not configured |
| `needs_query` | has a required query parameter, so it is checked for auth only |

`/api/stats` is public and lives under `/api`, which is why membership is by exact
path: a prefix rule would have waved through whatever landed there next.

**`test_invariants.py`** checks things that are only true or false against live
data. Every one descends from a bug that reached production and was found by a
person, not by a test:

- the follower total disagreed with Twitch on all 14 channels, by up to -100%
- 20,000 followers were stored with no enriched profile, so half the page read zero
- the headline said "42 followers" beside "2,500 of them are streamers"
- every model answer was discarded for 25 days because it arrived JSON-fenced
- the response carried 2.45 MB of names for a screen that shows five at a time

## Adding to it

Put it in `test_invariants.py` if it can only be judged against real data, and in
`test_surface.py` if it is about what an endpoint owes its caller.

Two things worth keeping:

- **Name the failure a check descends from.** Every assertion here says which real
  incident it is guarding, so nobody later deletes it as noise.
- **Assert that a list is not empty before looping over it.** A parametrized test
  over an empty list passes while testing nothing, and this repo has already lost
  time to exactly that in `tests/test_isolation.py`.

## What this does not cover

- Anything requiring a write, on purpose.
- The workers. A follower sync or a capture is minutes long and needs its own
  harness; `scripts/benchmark_followers_page.py` and
  `scripts/seed_demo_followers.py` are the tools for that.
- Rendering. The API answering correctly and the screen showing it are different
  things, and this repo has the scar to prove it: `{list.length > 0 && (...)}`
  means an empty block disappears, so a feature with no data looks identical to a
  feature that does not exist. `scripts/seed_demo_followers.py` builds accounts
  that force each state so the screens can be looked at.
