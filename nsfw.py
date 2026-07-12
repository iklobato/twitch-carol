from __future__ import annotations

import logging
from pathlib import Path

from better_profanity import profanity

logger = logging.getLogger(__name__)


class NsfwFilter:
    def __init__(self, extra_words: list[str]) -> None:
        profanity.load_censor_words()
        if extra_words:
            profanity.add_censor_words(extra_words)

    @classmethod
    def from_path(cls, path: Path) -> "NsfwFilter":
        words = cls._read_wordlist(path)
        if not words:
            logger.warning("no NSFW wordlist at %s; using English defaults only", path)
        return cls(words)

    @staticmethod
    def _read_wordlist(path: Path) -> list[str]:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        words = [line.strip().lower() for line in lines]
        return [w for w in words if w and not w.startswith("#")]

    def is_flagged(self, text: str) -> bool:
        return profanity.contains_profanity(text)
