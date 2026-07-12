from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from alerts import AlertKind, Money, StreamAlert, tier_label


class TestMoney:
    def test_from_livepix_uppercases_currency(self):
        money = Money.from_livepix(500, "brl")
        assert money == Money(cents=500, currency="BRL")

    def test_format_brl(self):
        assert Money(500, "BRL").format() == "R$5,00"

    def test_format_zero(self):
        assert Money(0, "BRL").format() == "R$0,00"

    def test_format_sub_real_cents(self):
        assert Money(7, "BRL").format() == "R$0,07"

    def test_format_negative(self):
        # Characterization: negative amounts render with a leading minus.
        assert Money(-150, "BRL").format() == "R$-1,50"

    def test_format_non_brl_uses_currency_code_prefix(self):
        # Comma decimal applies to every currency: pt-BR display convention.
        assert Money(500, "USD").format() == "USD 5,00"

    def test_format_large_amount_has_no_thousands_separator(self):
        # :.2f never emits a thousands separator, so replacing "." with ","
        # only ever touches the decimal point.
        assert Money(123456789, "BRL").format() == "R$1234567,89"

    def test_money_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            Money(100, "BRL").cents = 200


class TestStreamAlert:
    def test_payload_keys_match_overlay_js_contract(self):
        alert = StreamAlert(
            kind=AlertKind.SUBSCRIPTION, headline="oi", detail="detalhe"
        )
        assert set(alert.to_payload()) == {
            "kind",
            "headline",
            "detail",
            "username",
            "amount",
            "createdAt",
        }

    def test_kind_serializes_to_string_value(self):
        payload = StreamAlert(
            kind=AlertKind.PIX_DONATION, headline="h", detail="d"
        ).to_payload()
        assert payload["kind"] == "pix_donation"

    def test_amount_none_stays_none(self):
        payload = StreamAlert(
            kind=AlertKind.RESUB, headline="h", detail="d"
        ).to_payload()
        assert payload["amount"] is None

    def test_amount_is_formatted_string(self):
        payload = StreamAlert(
            kind=AlertKind.PIX_DONATION,
            headline="h",
            detail="d",
            amount=Money(1050, "BRL"),
        ).to_payload()
        assert payload["amount"] == "R$10,50"

    def test_created_at_default_is_utc_and_isoformat_roundtrips(self):
        alert = StreamAlert(kind=AlertKind.GIFT, headline="h", detail="d")
        assert alert.created_at.tzinfo is not None
        assert alert.created_at.utcoffset().total_seconds() == 0
        parsed = datetime.fromisoformat(alert.to_payload()["createdAt"])
        assert parsed == alert.created_at

    def test_created_at_can_be_injected(self):
        fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        alert = StreamAlert(
            kind=AlertKind.GIFT, headline="h", detail="d", created_at=fixed
        )
        assert alert.to_payload()["createdAt"] == "2026-01-01T00:00:00+00:00"


class TestTierLabel:
    @pytest.mark.parametrize(
        ("tier", "label"),
        [
            ("1000", "Tier 1"),
            ("2000", "Tier 2"),
            ("3000", "Tier 3"),
            ("Prime", "Prime"),
        ],
    )
    def test_known_tiers(self, tier, label):
        assert tier_label(tier) == label

    def test_none_defaults_to_tier_1(self):
        assert tier_label(None) == "Tier 1"

    def test_unknown_tier_passes_through_instead_of_lying(self):
        assert tier_label("4000") == "4000"


def test_alert_kind_values_are_valid_css_class_tokens():
    # overlay.js does `box.className = alert.kind` — a space or quote in a
    # kind value would break the styling contract.
    for kind in AlertKind:
        assert kind.value
        assert " " not in kind.value
        assert kind.value == kind.value.lower()
