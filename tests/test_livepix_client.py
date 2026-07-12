from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from livepix import (
    LIVEPIX_API_BASE,
    LIVEPIX_SCOPES,
    LIVEPIX_TOKEN_URL,
    LivePixClient,
    LivePixMessage,
    LivePixPayment,
    LivePixSubscription,
)


@pytest.fixture
def client(make_settings):
    return LivePixClient(make_settings())


def mock_token_route(respx_mock, token: str = "tok-1"):
    return respx_mock.post(LIVEPIX_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": token})
    )


@respx.mock
async def test_authorize_posts_credentials_and_scopes(client):
    token_route = mock_token_route(respx.mock)
    token = await client._authorize()
    assert token == "tok-1"
    body = parse_qs(token_route.calls.last.request.content.decode())
    assert body == {
        "grant_type": ["client_credentials"],
        "client_id": ["lp-id"],
        "client_secret": ["lp-secret"],
        "scope": [LIVEPIX_SCOPES],
    }


@respx.mock
async def test_token_is_cached_across_gets(client):
    token_route = mock_token_route(respx.mock)
    api_route = respx.mock.get(f"{LIVEPIX_API_BASE}/v2/payments/x").mock(
        return_value=httpx.Response(200, json={"amount": 1, "currency": "BRL"})
    )
    await client._get("/v2/payments/x")
    await client._get("/v2/payments/x")
    assert token_route.call_count == 1
    assert api_route.call_count == 2


@respx.mock
async def test_authorize_failure_raises_and_keeps_token_unset(client):
    respx.mock.post(LIVEPIX_TOKEN_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await client._authorize()
    assert client._token is None


@respx.mock
async def test_get_sends_bearer_header(client):
    mock_token_route(respx.mock, token="tok-abc")
    api_route = respx.mock.get(f"{LIVEPIX_API_BASE}/v2/payments/x").mock(
        return_value=httpx.Response(200, json={"amount": 1, "currency": "BRL"})
    )
    await client._get("/v2/payments/x")
    assert api_route.calls.last.request.headers["Authorization"] == "Bearer tok-abc"


@respx.mock
async def test_401_invalidates_token_without_automatic_retry(client):
    # Contract: a 401 clears the cached token and raises; only the NEXT call
    # re-authenticates. There is no in-flight retry.
    token_route = mock_token_route(respx.mock)
    respx.mock.get(f"{LIVEPIX_API_BASE}/v2/payments/x").mock(
        return_value=httpx.Response(401)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client._get("/v2/payments/x")
    assert client._token is None
    with pytest.raises(httpx.HTTPStatusError):
        await client._get("/v2/payments/x")
    assert token_route.call_count == 2


@respx.mock
async def test_concurrent_cold_gets_fetch_token_once(client):
    token_route = mock_token_route(respx.mock)
    respx.mock.get(f"{LIVEPIX_API_BASE}/v2/payments/x").mock(
        return_value=httpx.Response(200, json={"amount": 1, "currency": "BRL"})
    )
    await asyncio.gather(
        client._get("/v2/payments/x"),
        client._get("/v2/payments/x"),
        client._get("/v2/payments/x"),
    )
    assert token_route.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    ("method", "path", "payload", "model"),
    [
        (
            "fetch_payment",
            "/v2/payments/id-1",
            {"amount": 500, "currency": "BRL"},
            LivePixPayment,
        ),
        (
            "fetch_message",
            "/v2/messages/id-1",
            {"username": "Ana", "message": "oi", "amount": 500, "currency": "BRL"},
            LivePixMessage,
        ),
        (
            "fetch_subscription",
            "/v2/subscriptions/id-1",
            {"subscriber": "Bea", "months": 2, "amount": 500, "currency": "BRL"},
            LivePixSubscription,
        ),
    ],
)
async def test_fetch_methods_hit_expected_urls(client, method, path, payload, model):
    mock_token_route(respx.mock)
    api_route = respx.mock.get(f"{LIVEPIX_API_BASE}{path}").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await getattr(client, method)("id-1")
    assert api_route.call_count == 1
    assert isinstance(result, model)


async def test_context_manager_closes_http_client(make_settings):
    async with LivePixClient(make_settings()) as client:
        assert not client._http.is_closed
    assert client._http.is_closed
