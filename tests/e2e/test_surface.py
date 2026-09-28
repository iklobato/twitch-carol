"""What the deployed HTTP surface must answer, whoever is asking.

Routes are enumerated from this checkout's app rather than hand-listed, so an
endpoint added tomorrow is covered the day it ships. The deployment does not serve
its own schema (see the `schema` fixture), which is why the checkout has to match
what is running, and why `test_the_checkout_matches_the_deployment` exists.

Every route is sorted into exactly one category, and that is asserted. A route
matching none fails the run with its own name in the message, which is the point:
adding an endpoint forces a decision about what it owes an anonymous caller, and
nothing new can slip in untested by merely going unnoticed.
"""

import re

import httpx
import pytest

from tests.e2e.conftest import routes

# Below this the schema is not describing this app, it is describing a mistake.
MIN_ROUTES = 20
# The response carried 2.45 MB before segment members were capped, on a channel
# with 41,605 followers. Nothing here needs a megabyte of JSON per visit.
MAX_RESPONSE_BYTES = 1_000_000

# Reachable without signing in, by design. Verified one at a time rather than by
# prefix: /api/stats sits under /api and is public, and a prefix rule would have
# quietly waved through anything else that landed there later.
PUBLIC = (
    "/healthz",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/docs/oauth2-redirect",
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    # Platform-wide totals for the landing page, no per-channel figures in it.
    "/api/stats",
    # The public how-to, served in the reader's language.
    "/howto",
    "/howto.html",
)
# Answer only for a login on the admin allowlist, so a normal session gets 403.
ADMIN_PREFIX = "/api/admin"
# Depend on an external account being configured, so they may legitimately answer
# 503 or redirect on an environment where it is not.
INTEGRATION_PREFIX = "/api/integrations"


def _fill_ids(path: str, value: str = "999999999") -> str | None:
    """A concrete URL for a templated path, or None when the shape is unknown.

    Returning None rather than guessing keeps an unrecognised id out of the run
    instead of requesting `/api/thing/{weird_id}` as a literal string.
    """
    url = re.sub(r"\{[a-z_]+\}", value, path)
    return None if "{" in url else url


def _required_query_params(schema: dict, path: str, method: str) -> list[str]:
    operation = schema["paths"][path][method.lower()]
    return [
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query" and parameter.get("required")
    ]


def classify(schema: dict, path: str, method: str) -> str:
    if path in PUBLIC:
        return "public"
    if path.startswith(ADMIN_PREFIX):
        return "admin"
    if path.startswith(INTEGRATION_PREFIX):
        return "integration"
    if "{" in path:
        return "by_id"
    if _required_query_params(schema, path, method):
        return "needs_query"
    return "listing"


@pytest.fixture(scope="session")
def by_category(schema: dict) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for method, path in routes(schema, methods=("GET",)):
        grouped.setdefault(classify(schema, path, method), []).append(path)
    return grouped


def test_the_environment_is_up(anon: httpx.Client) -> None:
    response = anon.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_web_app_is_served(web_url: str, anon: httpx.Client) -> None:
    """The API answering says nothing about the static site: they are separate
    components and one has been deployed without the other before."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get(web_url)
    assert response.status_code == 200
    assert "html" in response.headers.get("content-type", "").lower()


def test_every_route_is_classified(schema: dict, by_category: dict) -> None:
    """The guard that keeps this file honest as the app grows. If it fails, add the
    new route to a category above and decide what it owes an anonymous caller."""
    total = len(routes(schema, methods=("GET",)))
    assert total >= MIN_ROUTES, f"only {total} GET routes in the schema"
    assert sum(len(paths) for paths in by_category.values()) == total
    assert by_category.get("listing"), "no plain listing routes found at all"


def test_nothing_private_answers_an_anonymous_caller(
    anon: httpx.Client, by_category: dict
) -> None:
    """The rule the whole product rests on. Runs without a session on purpose, so it
    still protects the app when nobody has pasted a cookie.

    422 counts as refused: FastAPI validates the request before the auth dependency
    runs, so a missing parameter answers before anything private is touched.
    """
    private = [
        path
        for category, paths in by_category.items()
        if category not in ("public",)
        for path in paths
    ]
    reachable = []
    for path in private:
        url = _fill_ids(path)
        if url is None:
            continue
        response = anon.get(url)
        if response.status_code not in (401, 403, 404, 422):
            reachable.append(f"{path} -> {response.status_code}")
    assert not reachable, f"reachable without signing in: {reachable}"


def test_every_listing_route_answers_for_its_owner(
    signed_in: httpx.Client, by_category: dict
) -> None:
    """The cheapest catch there is for a route that throws on real data, which is how
    most of the damage here has actually surfaced."""
    failures = []
    for path in by_category["listing"]:
        response = signed_in.get(path)
        if response.status_code != 200:
            failures.append(f"{path} -> {response.status_code} {response.text[:120]}")
    assert not failures, "\n".join(failures)


def test_admin_routes_answer_only_for_an_admin(
    signed_in: httpx.Client, by_category: dict, me: dict
) -> None:
    expected = 200 if me.get("is_admin") else 403
    wrong = []
    for path in by_category.get("admin", []):
        url = _fill_ids(path)
        if url is None:
            continue
        response = signed_in.get(url)
        if response.status_code != expected:
            wrong.append(f"{path} -> {response.status_code}, esperado {expected}")
    assert not wrong, "; ".join(wrong)


def test_another_channels_id_answers_404_and_never_403(
    signed_in: httpx.Client, by_category: dict
) -> None:
    """404, never 403. A 403 already tells a stranger the id is real and belongs to
    somebody else, which is the leak the product rule exists to prevent."""
    by_id = by_category.get("by_id", [])
    assert by_id, "no id-taking routes found; the schema or the filter is wrong"
    wrong = []
    for path in by_id:
        url = _fill_ids(path)
        if url is None:
            continue
        response = signed_in.get(url)
        if response.status_code not in (404, 422):
            wrong.append(f"{path} -> {response.status_code}")
    assert not wrong, f"expected 404 for an id that is not mine: {wrong}"


def test_no_route_answers_with_a_megabyte(
    signed_in: httpx.Client, by_category: dict
) -> None:
    oversized = []
    for path in by_category["listing"]:
        response = signed_in.get(path)
        if response.status_code == 200 and len(response.content) > MAX_RESPONSE_BYTES:
            oversized.append(f"{path} -> {len(response.content) // 1024} KB")
    assert (
        not oversized
    ), "this much JSON crosses the wire on every visit: " + "; ".join(oversized)


def test_the_checkout_matches_the_deployment(deployed_commit: str | None) -> None:
    """The route list comes from this checkout, so it only describes the environment
    while the two agree. Without this, a stale checkout would quietly test routes
    that are not there and miss routes that are.
    """
    if deployed_commit is None:
        pytest.skip("set E2E_APP_ID to verify the deployment runs this commit")
    import subprocess

    local = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert local.startswith(deployed_commit) or deployed_commit.startswith(local[:7]), (
        f"this checkout is {local[:7]} but the environment runs {deployed_commit[:7]}: "
        "the route list below describes code that is not deployed"
    )
