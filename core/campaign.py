"""Campaign funnel per batch, without a tracking pixel.

The cold email links to /howto?ref=<batch>. The visit and the click on Connect
are rows in campaign_clicks; the sign-up is channels.signup_ref. The batch rides
from /howto to the OAuth callback in a cookie, because Twitch's redirect drops
our query string.

Counting is best-effort: a database error here must never cost the visitor the
page or the login, so callers log it and carry on.
"""

import logging
import re

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.models import CampaignClick, CampaignStep

logger = logging.getLogger(__name__)

REF_COOKIE = "campaign_ref"
# Long enough for someone who reads the email today and connects next week.
REF_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 3600
# Batch names the actor writes: lote-23, lote-en-20. Anything else is ignored,
# so a hand-typed ?ref= cannot fill the table with junk.
_REF_PATTERN = re.compile(r"lote-[a-z0-9-]{1,24}")


def valid_ref(value: str | None) -> str | None:
    return value if value and _REF_PATTERN.fullmatch(value) else None


def record_step(db: Session, ref: str, step: CampaignStep) -> None:
    try:
        db.add(CampaignClick(ref=ref, step=step))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("campaign step not recorded", extra={"ref": ref, "step": step})
