"""Split the raw email list into daily sending batches.

The order is not arbitrary: a new sending domain needs history before volume.
Business contacts go first (someone who publishes a contact address expects a
proposal and rarely marks spam) and Microsoft goes last (the harshest filter on
a sender with no reputation).

Every row carries the language its copy has to be written in. The batches used
to be a bare list of addresses, so the sender had a single body to choose from
and it was Portuguese: an English-speaking streamer got a Portuguese email or
nothing at all. The language is never guessed here. It comes from the source
file when the source knows it (a CSV with a `language` column), and otherwise
has to be stated on the command line for the whole run.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

SOURCE = Path("emails_extracted.txt")
OUTPUT_DIR = Path("data/campaign")
EMAIL_PATTERN = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
BUSINESS_MARKERS = ("business@", "contact@")
MICROSOFT_DOMAINS = frozenset({"hotmail.com", "outlook.com", "live.com", "msn.com"})
WARMUP_SIZES = (20, 40, 60)
PRIORITY_BUSINESS, PRIORITY_DEFAULT, PRIORITY_MICROSOFT = 0, 1, 2
# Languages a full campaign body exists for. Sending to anyone else means
# writing the copy first, not falling back to a language they cannot read.
CAMPAIGN_LANGUAGES = ("pt", "en")


class Contact(NamedTuple):
    address: str
    language: str


def read_contacts(source: Path, language: str | None) -> list[Contact]:
    """Contacts from a CSV that names the language per row, or from a plain
    list of addresses that the caller labels with one language."""
    if source.suffix == ".csv":
        return _read_csv(source, language)
    if language is None:
        raise SystemExit(
            f"{source} carries no language: pass --language "
            f"({'|'.join(CAMPAIGN_LANGUAGES)}) to say which copy this list gets"
        )
    addresses = sorted(set(EMAIL_PATTERN.findall(source.read_text().lower())))
    return [Contact(address, _validated(language)) for address in addresses]


def _read_csv(source: Path, fallback: str | None) -> list[Contact]:
    with source.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_address: dict[str, str] = {}
    for row in rows:
        address = (row.get("email") or "").strip().lower()
        if not EMAIL_PATTERN.fullmatch(address):
            continue
        language = (row.get("language") or "").strip().lower() or fallback
        if language is None:
            raise SystemExit(
                f"{source} names no language for {address}: add a language "
                "column, or pass --language for the whole file"
            )
        by_address[address] = _validated(language)
    return [Contact(address, by_address[address]) for address in sorted(by_address)]


def _validated(language: str) -> str:
    if language not in CAMPAIGN_LANGUAGES:
        raise SystemExit(f"no campaign copy exists in {language!r}: write it before sending")
    return language


def send_priority(contact: Contact) -> int:
    if any(marker in contact.address for marker in BUSINESS_MARKERS):
        return PRIORITY_BUSINESS
    if contact.address.rpartition("@")[2] in MICROSOFT_DOMAINS:
        return PRIORITY_MICROSOFT
    return PRIORITY_DEFAULT


def split_batches(contacts: list[Contact]) -> list[list[Contact]]:
    ordered = sorted(contacts, key=send_priority)
    warmup = [c for c in ordered if send_priority(c) != PRIORITY_MICROSOFT]
    microsoft = [c for c in ordered if send_priority(c) == PRIORITY_MICROSOFT]

    batches, start = [], 0
    for size in WARMUP_SIZES:
        batches.append(warmup[start : start + size])
        start += size
    batches.append(warmup[start:])
    batches.append(microsoft)
    return [batch for batch in batches if batch]


def write_batches(batches: list[list[Contact]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for number, batch in enumerate(batches, start=1):
        path = output_dir / f"lote-{number}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["email", "language"])
            writer.writerows(batch)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--language",
        choices=CAMPAIGN_LANGUAGES,
        help="language of every contact in a source that does not name one",
    )
    args = parser.parse_args()

    contacts = read_contacts(args.source, args.language)
    batches = split_batches(contacts)

    assert sum(len(b) for b in batches) == len(contacts), "a batch lost or duplicated"
    assert set().union(*batches) == set(contacts), "batches do not cover the source"

    written = write_batches(batches, args.output_dir)
    for path, batch in zip(written, batches, strict=True):
        per_language = Counter(contact.language for contact in batch)
        counts = ", ".join(f"{lang}={n}" for lang, n in sorted(per_language.items()))
        print(f"{path}: {len(batch)} ({counts})")
    print(f"total: {len(contacts)}")


if __name__ == "__main__":
    main()
