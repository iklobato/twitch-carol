from datetime import date

from core.db import chat_partition_ddl, month_bounds


def test_month_bounds_mid_year() -> None:
    assert month_bounds(date(2026, 7, 11)) == (date(2026, 7, 1), date(2026, 8, 1))


def test_month_bounds_rolls_over_year() -> None:
    assert month_bounds(date(2026, 12, 15)) == (date(2026, 12, 1), date(2027, 1, 1))


def test_chat_partition_ddl() -> None:
    ddl = chat_partition_ddl(date(2026, 7, 11))
    assert "chat_messages_y2026m07" in ddl
    assert "PARTITION OF chat_messages" in ddl
    assert "FROM ('2026-07-01') TO ('2026-08-01')" in ddl
