"""Divide a lista bruta de emails em lotes diarios de envio.

A ordem nao e arbitraria: dominio remetente novo precisa de historico antes de
volume. Contatos de negocio vao primeiro (quem publica um endereco de contato
espera proposta e raramente marca spam) e Microsoft vai por ultimo (o filtro
mais duro com remetente sem reputacao).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

SOURCE = Path("emails_extracted.txt")
OUTPUT_DIR = Path("data/campaign")
EMAIL_PATTERN = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
BUSINESS_MARKERS = ("business@", "contact@")
MICROSOFT_DOMAINS = frozenset({"hotmail.com", "outlook.com", "live.com", "msn.com"})
WARMUP_SIZES = (20, 40, 60)
PRIORITY_BUSINESS, PRIORITY_DEFAULT, PRIORITY_MICROSOFT = 0, 1, 2


def read_addresses(source: Path) -> list[str]:
    return sorted(set(EMAIL_PATTERN.findall(source.read_text().lower())))


def send_priority(address: str) -> int:
    if any(marker in address for marker in BUSINESS_MARKERS):
        return PRIORITY_BUSINESS
    if address.rpartition("@")[2] in MICROSOFT_DOMAINS:
        return PRIORITY_MICROSOFT
    return PRIORITY_DEFAULT


def split_batches(addresses: list[str]) -> list[list[str]]:
    ordered = sorted(addresses, key=send_priority)
    warmup = [a for a in ordered if send_priority(a) != PRIORITY_MICROSOFT]
    microsoft = [a for a in ordered if send_priority(a) == PRIORITY_MICROSOFT]

    batches, start = [], 0
    for size in WARMUP_SIZES:
        batches.append(warmup[start : start + size])
        start += size
    batches.append(warmup[start:])
    batches.append(microsoft)
    return [batch for batch in batches if batch]


def write_batches(batches: list[list[str]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for number, batch in enumerate(batches, start=1):
        path = output_dir / f"lote-{number}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["email"])
            writer.writerows([address] for address in batch)
        paths.append(path)
    return paths


def main() -> None:
    addresses = read_addresses(SOURCE)
    batches = split_batches(addresses)

    assert sum(len(b) for b in batches) == len(addresses), "lote perdeu ou duplicou email"
    assert set().union(*batches) == set(addresses), "lotes nao cobrem a lista original"

    for path, batch in zip(write_batches(batches, OUTPUT_DIR), batches, strict=False):
        print(f"{path}: {len(batch)}")
    print(f"total: {len(addresses)}")


if __name__ == "__main__":
    main()
