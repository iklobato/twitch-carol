"""Shared setup for the tests that run against a deployed environment.

These are not unit tests. They call a running deployment over HTTP and check what
it answers, which is the only way to catch the class of bug that keeps reaching
production here: code that is correct in isolation but wrong once it meets real
data, a real migration state and a real Twitch.

Read-only by default. Every request is a GET, so pointing this at production is
safe; the one exception is opt-in and documented in README.md.

    E2E_BASE_URL=https://dev.streamintel.cc \
    E2E_SESSION=<the `session` cookie from a signed-in browser> \
    pytest tests/e2e -q

Without E2E_BASE_URL the whole directory skips, so a normal `pytest` run is
unaffected.
"""

import os

import httpx
import pytest

REQUEST_TIMEOUT_SECONDS = 90.0
METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")
# Paths that are public by design and must NOT be expected to reject an anonymous
# caller. Everything else under /api is expected to.
PUBLIC_PREFIXES = (
    "/healthz",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/auth/",
    "/api/public",
)


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@pytest.fixture(scope="session")
def base_url() -> str:
    url = _env("E2E_BASE_URL")
    if url is None:
        pytest.skip("E2E_BASE_URL not set: these tests need a deployed environment")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def web_url(base_url: str) -> str:
    """Where the static site is served. The same host in a real deployment, but a
    separate port when the API and vite are run side by side locally."""
    return (_env("E2E_WEB_URL") or base_url).rstrip("/")


@pytest.fixture(scope="session")
def anon(base_url: str):
    """A client with no session, for checking what an anonymous caller can reach."""
    with httpx.Client(
        base_url=base_url, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        yield client


@pytest.fixture(scope="session")
def session_cookie() -> str:
    cookie = _env("E2E_SESSION")
    if cookie is None:
        pytest.skip(
            "E2E_SESSION not set: sign in, copy the `session` cookie, and pass it. "
            "There is no API key path, so this cannot be automated from here."
        )
    return cookie


@pytest.fixture(scope="session")
def signed_in(base_url: str, session_cookie: str):
    with httpx.Client(
        base_url=base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        cookies={"session": session_cookie},
    ) as client:
        yield client


@pytest.fixture(scope="session")
def schema() -> dict:
    """The route list, read from this checkout's app.

    Reading it from the deployment would be better and was the first attempt, but
    the schema is not reachable there: only /api, /auth and /healthz route to the
    API component, so /openapi.json lands on the static site and 404s. Exposing it
    publicly is a product decision, not a test's to make.

    So the enumeration comes from the code in hand, which is only trustworthy while
    the code in hand is the code deployed. That is what
    `test_the_checkout_matches_the_deployment` is for, and why E2E_APP_ID is worth
    setting.
    """
    from apps.api.main import app

    return app.openapi()


@pytest.fixture(scope="session")
def deployed_commit() -> str | None:
    """The commit the environment is running, via doctl. None when it cannot be
    established, so the check that uses it skips rather than guessing."""
    app_id = _env("E2E_APP_ID")
    if app_id is None:
        return None
    import json
    import subprocess

    try:
        raw = subprocess.run(
            ["doctl", "apps", "get", app_id, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    services = json.loads(raw)[0].get("active_deployment", {}).get("services") or [{}]
    return services[0].get("source_commit_hash")


def routes(
    schema: dict, *, methods: tuple[str, ...] = ("GET",)
) -> list[tuple[str, str]]:
    return [
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() in methods
    ]


def is_public(path: str) -> bool:
    return path.startswith(PUBLIC_PREFIXES)


def takes_an_id(path: str) -> bool:
    return "{" in path


@pytest.fixture(scope="session")
def me(signed_in: httpx.Client) -> dict:
    """Who the session belongs to. Several checks compare live data against this
    channel, so a wrong answer here should fail once, loudly, not everywhere."""
    response = signed_in.get("/api/me")
    assert response.status_code == 200, (
        f"/api/me answered {response.status_code}: the session cookie is not valid "
        "for this environment (they are signed per FERNET_KEY, so a dev cookie "
        "will not work against production)"
    )
    return response.json()
