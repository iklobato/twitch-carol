from __future__ import annotations

import logging
from pathlib import Path

from nsfw import NsfwFilter

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestReadWordlist:
    def test_missing_path_returns_empty(self, tmp_path):
        assert NsfwFilter._read_wordlist(tmp_path / "nope.txt") == []

    def test_blank_lines_skipped(self, tmp_path):
        path = tmp_path / "words.txt"
        path.write_text("palavrao\n\n   \noutropalavrao\n", encoding="utf-8")
        assert NsfwFilter._read_wordlist(path) == ["palavrao", "outropalavrao"]

    def test_comment_lines_skipped(self, tmp_path):
        path = tmp_path / "words.txt"
        path.write_text("# comentario\npalavrao\n", encoding="utf-8")
        assert NsfwFilter._read_wordlist(path) == ["palavrao"]

    def test_indented_comment_lines_skipped(self, tmp_path):
        path = tmp_path / "words.txt"
        path.write_text("  # comentario indentado\npalavrao\n", encoding="utf-8")
        assert NsfwFilter._read_wordlist(path) == ["palavrao"]

    def test_words_are_stripped_and_lowercased(self, tmp_path):
        path = tmp_path / "words.txt"
        path.write_text("  PaLaVrAo  \n", encoding="utf-8")
        assert NsfwFilter._read_wordlist(path) == ["palavrao"]

    def test_shipped_wordlist_is_clean(self):
        words = NsfwFilter._read_wordlist(REPO_ROOT / "nsfw_words_pt.txt")
        assert words
        assert not [w for w in words if w.startswith("#")]


class TestNsfwFilter:
    def test_from_path_missing_file_warns_and_uses_english_defaults(
        self, tmp_path, caplog
    ):
        with caplog.at_level(logging.WARNING, logger="nsfw"):
            nsfw = NsfwFilter.from_path(tmp_path / "missing.txt")
        assert "no NSFW wordlist" in caplog.text
        assert nsfw.is_flagged("this is shit") is True

    def test_extra_word_is_flagged_case_insensitively(self, tmp_path):
        path = tmp_path / "words.txt"
        path.write_text("xesque\n", encoding="utf-8")
        nsfw = NsfwFilter.from_path(path)
        assert nsfw.is_flagged("que xesque total") is True
        assert nsfw.is_flagged("QUE XESQUE TOTAL") is True

    def test_clean_text_not_flagged(self, tmp_path):
        path = tmp_path / "words.txt"
        path.write_text("xesque\n", encoding="utf-8")
        nsfw = NsfwFilter.from_path(path)
        assert nsfw.is_flagged("bom dia pessoal, tudo bem?") is False
