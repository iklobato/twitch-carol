"""The 15-minute blocks of a live as the topics prompt shows them, and the
rule that hands each block to one topic.

A topic used to "last" only from its first to its last cited speech segment,
about 1% of a live. Blocks tile the whole live, so when every block goes to
a topic, money, chat and follows anywhere in the live meet a topic
(core.topics reads the stored blocks)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BlockSummary:
    """One block of a live and what the model said happened in it. number is
    the block's position in the live, so it stays the same when an earlier
    block was skipped."""

    number: int
    start: datetime
    end: datetime
    text: str

    def prompt_line(self) -> str:
        return f"B{self.number} [{self.start:%H:%M}-{self.end:%H:%M} UTC]: {self.text}"

    def evidence(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


class ShownBlocks:
    """The blocks whose label survived the prompt's input budget: a block
    the model never saw cannot be cited, same rule as
    workers.analyze.evidence."""

    def __init__(self, blocks: Mapping[int, BlockSummary]) -> None:
        self._blocks = blocks

    @classmethod
    def none(cls) -> "ShownBlocks":
        return cls({})

    @classmethod
    def in_prompt(cls, blocks: list[BlockSummary], prompt_text: str) -> "ShownBlocks":
        labels = {int(number) for number in re.findall(r"^B(\d+) \[", prompt_text, re.M)}
        return cls({block.number: block for block in blocks if block.number in labels})

    def get(self, number: int) -> BlockSummary | None:
        return self._blocks.get(number)


class TopicBlockClaims:
    """Gives each shown block to at most one topic. Topics claim in rank
    order, so a block two topics ask for stays with the higher-ranked one."""

    def __init__(self, shown: ShownBlocks, claimed: set[int]) -> None:
        self._shown = shown
        self._claimed = claimed

    @classmethod
    def unclaimed(cls, shown: ShownBlocks) -> "TopicBlockClaims":
        return cls(shown, set())

    def claim(self, candidate: Mapping[str, object]) -> list[dict[str, str]]:
        """The evidence entries of the blocks this topic gets, in live order."""
        granted = []
        for number in self._numbers(candidate):
            block = self._shown.get(number)
            if block is None or number in self._claimed:
                continue
            self._claimed.add(number)
            granted.append(block)
        return [block.evidence() for block in sorted(granted, key=self._live_order)]

    def _numbers(self, candidate: Mapping[str, object]) -> list[int]:
        raw = candidate.get("block_ids")
        if not isinstance(raw, list):
            return []
        return [number for number in raw if isinstance(number, int)]

    def _live_order(self, block: BlockSummary) -> int:
        return block.number
