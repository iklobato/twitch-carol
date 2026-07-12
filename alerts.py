from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

TIERS = {"1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3", "Prime": "Prime"}


class AlertKind(str, Enum):
    SUBSCRIPTION = "subscription"
    RESUB = "resub"
    GIFT = "gift"
    PIX_DONATION = "pix_donation"


@dataclass(frozen=True)
class Money:
    cents: int
    currency: str

    @classmethod
    def from_livepix(cls, amount: int, currency: str) -> "Money":
        return cls(cents=int(amount), currency=currency.upper())

    def format(self) -> str:
        symbol = "R$" if self.currency == "BRL" else f"{self.currency} "
        return f"{symbol}{self.cents / 100:.2f}".replace(".", ",")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class StreamAlert:
    kind: AlertKind
    headline: str
    detail: str
    username: str | None = None
    amount: Money | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def to_payload(self) -> dict:
        return {
            "kind": self.kind.value,
            "headline": self.headline,
            "detail": self.detail,
            "username": self.username,
            "amount": self.amount.format() if self.amount else None,
            "createdAt": self.created_at.isoformat(),
        }


def tier_label(tier: str | None) -> str:
    if tier is None:
        return "Tier 1"
    return TIERS.get(str(tier), str(tier))
