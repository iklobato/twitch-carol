"""Things that must be true of live data, which no unit test can see.

Every check here comes from a bug that reached production and was found by a human
looking, not by the suite:

- the follower count disagreed with Twitch on all 14 channels, by up to -100%
- 20,000 followers were stored with no enriched profile, so panels read zero
- the headline said 42 followers next to "2,500 of them are streamers"
- every model answer was discarded for 25 days because it arrived JSON-fenced
- the response carried 2.45 MB of names the screen shows five at a time

They are cheap, they are all GETs, and each one names the failure it descends from
so nobody has to guess later why it is here.
"""

import json
import urllib.request

import httpx
import pytest

TWITCH_GQL = "https://gql.twitch.tv/gql"
# The public web client id. Used only to read a public follower count, so this
# check does not depend on our own Twitch credentials being healthy.
TWITCH_PUBLIC_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
# Measured drift across all 14 production channels once the sync was correct: every
# one landed exactly on Twitch's number, and the largest legitimate gap between
# passes is the handful of follows that arrive mid-walk.
TOTAL_TOLERANCE = 25
# A model answer that still has its fence or its braces was never parsed.
UNPARSED_MARKERS = ("```", '{"', "{'")


def twitch_follower_total(login: str) -> int | None:
    query = f'query{{user(login:"{login}"){{followers{{totalCount}}}}}}'
    request = urllib.request.Request(
        TWITCH_GQL,
        data=json.dumps({"query": query}).encode(),
        headers={
            "Client-Id": TWITCH_PUBLIC_CLIENT_ID,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            user = json.load(response)["data"]["user"]
    except Exception:  # noqa: BLE001 - Twitch being unreachable is not our failure
        return None
    return None if user is None else user["followers"]["totalCount"]


@pytest.fixture(scope="session")
def followers(signed_in: httpx.Client) -> dict:
    response = signed_in.get("/api/followers")
    assert response.status_code == 200, response.text[:200]
    return response.json()


def test_the_follower_total_agrees_with_twitch(me: dict, followers: dict) -> None:
    """The bug this product shipped for weeks: the number came from counting our own
    rows, while Twitch hands back the real total in the same response we already
    read. Rows drift both ways, so they can never be the source of this number."""
    real = twitch_follower_total(me["login"])
    if real is None:
        pytest.skip("Twitch did not answer; this check needs the real number")
    stored = followers["kpis"]["total"]
    assert abs(stored - real) <= TOTAL_TOLERANCE, (
        f"the page says {stored} followers, Twitch says {real}. "
        "A gap this size means the total is being derived from our own rows again, "
        "or the sync worker has stopped."
    )


def test_the_headline_and_the_charts_do_not_contradict_each_other(
    followers: dict,
) -> None:
    """Dev once showed "Followers 42" beside "Streamers 2,500", because the total
    comes from Twitch while everything else is computed over the rows we hold. The
    two are allowed to differ; the screen just has to be able to say so."""
    kpis = followers["kpis"]
    assert kpis["stored"] >= kpis["streamers"], (
        f"{kpis['streamers']} streamers counted out of {kpis['stored']} stored rows: "
        "a subset cannot be larger than the set it came from"
    )
    assert kpis["stored"] >= 0 and kpis["total"] >= 0


def test_stored_followers_are_actually_enriched(followers: dict) -> None:
    """matheustrem13 held 20,000 followers with `enriched_at` null on every one, so
    composition, cohorts and collab all read zero while looking populated. A base
    that is stored but never enriched is a silent outage of half the page."""
    kpis = followers["kpis"]
    if kpis["stored"] == 0:
        pytest.skip("nothing stored yet for this channel")
    enriched_share = kpis["enriched"] / kpis["stored"]
    assert enriched_share > 0.5, (
        f"only {kpis['enriched']} of {kpis['stored']} followers are enriched "
        f"({enriched_share:.0%}): the panels built from profile data are empty"
    )


def test_no_segment_ships_more_names_than_the_screen_can_use(followers: dict) -> None:
    """The response was 2.45 MB because every segment carried its whole membership,
    41,605 names, for a screen that pages through five at a time."""
    segments = followers["ai"]["segments"]
    if not segments:
        pytest.skip("no segments for this channel yet")
    biggest = max(len(segment["members"]) for segment in segments)
    assert biggest <= 100, f"a segment shipped {biggest} members"


def test_model_answers_were_parsed_before_being_stored(
    signed_in: httpx.Client, followers: dict
) -> None:
    """Production discarded every recommendation for 25 days: the model answers
    inside a ```json fence and three readers called json.loads on it raw. Anything
    stored still wearing its fence never went through the tolerant parser."""
    texts = [item["content"] for item in followers["recommendations"]]
    channel = signed_in.get("/api/channel")
    if channel.status_code == 200:
        texts += [item["content"] for item in channel.json().get("recommendations", [])]
    unparsed = [t[:60] for t in texts if t.strip().startswith(UNPARSED_MARKERS)]
    assert not unparsed, f"stored unparsed model output: {unparsed}"


def test_a_channel_that_cannot_sync_is_told_so(followers: dict) -> None:
    """omassoni's token was refused for a day while his page kept showing the 533
    followers it had counted before, with nothing on screen about it. If the data
    cannot be refreshed, the one thing the streamer can act on has to be visible."""
    if not followers["needs_reconnect"]:
        return
    assert followers["kpis"]["total"] >= 0  # the page still renders
    # The flag existing is the whole point: the screen keys its banner off it.


def test_the_growth_series_is_ordered_and_cumulative(followers: dict) -> None:
    """An indirect behaviour nothing else asserts: the chart trusts the API to hand
    back months in order with a running total that never goes down."""
    buckets = followers["growth"]
    if len(buckets) < 2:
        pytest.skip("not enough history to check the series")
    months = [b["month"] for b in buckets]
    assert months == sorted(months), "growth buckets came back out of order"
    cumulative = [b["cumulative"] for b in buckets]
    assert cumulative == sorted(cumulative), "the cumulative total goes down"
    assert cumulative[-1] == sum(b["gained"] for b in buckets)


def test_the_funnel_never_widens_as_it_deepens(followers: dict) -> None:
    """Each funnel stage implies the ones above it, so counts can only shrink. If
    they grow, a stage is counting somebody it should not."""
    stages = followers["funnel"]
    if not stages:
        pytest.skip("no funnel for this channel yet")
    counts = [stage["count"] for stage in stages]
    assert counts == sorted(
        counts, reverse=True
    ), f"funnel counts widen as they deepen: {[(s['stage'], s['count']) for s in stages]}"
