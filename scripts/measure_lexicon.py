"""How much of a real chat the sentiment lexicon and the stopword list actually
read, per language.

The Portuguese lists were tuned against real Brazilian Twitch chat. The English
ones were written by hand and, until this script, had only ever been exercised
against a corpus we wrote ourselves, which proves nothing: a lexicon scored
against its own author's vocabulary always looks good.

Two sources, same measurement:
    uv run python scripts/measure_lexicon.py live --channel <login> --seconds 300
    uv run python scripts/measure_lexicon.py stored --language pt

`live` reads a public channel's chat over anonymous IRC, exactly the way the
capture worker does (same parser, same tokenizer). `stored` measures whatever
is already in the database. Nothing is written anywhere.

Coverage is the share of messages that get a sentiment score at all. A chat the
lexicon cannot read comes back neutral, which on screen is indistinguishable
from a chat that felt nothing.
"""

import argparse
import socket
import time
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_engine
from core.irc import parse_privmsg
from core.models import ChatMessage
from core.text import meaningful_words, message_sentiment, strip_emotes, tokenize

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667
# Twitch accepts any justinfan* nick without a token, read-only.
ANON_NICK = "justinfan24681"
READ_CHUNK = 8192


def read_live_chat(channel: str, seconds: int) -> list[tuple[str, dict]]:
    """Anonymous read-only IRC. No token, no writes, no joins beyond the one
    channel asked for."""
    messages: list[tuple[str, dict]] = []
    with socket.create_connection((IRC_HOST, IRC_PORT), timeout=10) as sock:
        sock.sendall(f"NICK {ANON_NICK}\r\n".encode())
        sock.sendall(b"CAP REQ :twitch.tv/tags\r\n")
        sock.sendall(f"JOIN #{channel}\r\n".encode())
        sock.settimeout(5)
        deadline = time.monotonic() + seconds
        buffer = ""
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(READ_CHUNK).decode("utf-8", errors="ignore")
            except TimeoutError:
                continue
            if not chunk:
                break
            buffer += chunk
            *lines, buffer = buffer.split("\r\n")
            for line in lines:
                if line.startswith("PING"):
                    sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                    continue
                parsed = parse_privmsg(line)
                if parsed is not None:
                    messages.append((parsed.text, parsed.emotes))
    return messages


def read_stored_chat(language: str, limit: int) -> list[tuple[str, dict]]:
    with Session(get_engine()) as db:
        rows = db.execute(
            select(ChatMessage.text, ChatMessage.emotes).limit(limit)
        ).all()
    return [(text, emotes or {}) for text, emotes in rows]


def report(messages: list[tuple[str, dict]], language: str) -> None:
    """Emotes are passed through exactly as the capture worker stores them:
    measuring without them counts every emote name as a word and turns the
    'topics of the live' into a list of the channel's own emotes."""
    if not messages:
        print("nenhuma mensagem lida")
        return
    scored = 0
    words: Counter[str] = Counter()
    for text, emotes in messages:
        clean = strip_emotes(text, emotes)
        if message_sentiment(tokenize(clean), language) is not None:
            scored += 1
        words.update(meaningful_words(text, emotes, language))

    print(f"idioma medido: {language}")
    print(f"mensagens: {len(messages)}")
    print(f"pontuadas pelo lexico: {scored} ({scored / len(messages):.1%})")
    print("palavras de conteudo mais comuns (o que viraria 'assunto da live'):")
    for word, count in words.most_common(15):
        print(f"  {word:20} {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="source", required=True)

    live = sub.add_parser("live", help="read a public channel's chat over IRC")
    live.add_argument("--channel", required=True)
    live.add_argument("--seconds", type=int, default=300)
    live.add_argument("--language", default="en")

    stored = sub.add_parser("stored", help="measure chat already in the database")
    stored.add_argument("--language", default="pt")
    stored.add_argument("--limit", type=int, default=20000)

    args = parser.parse_args()
    if args.source == "live":
        messages = read_live_chat(args.channel, args.seconds)
    else:
        messages = read_stored_chat(args.language, args.limit)
    report(messages, args.language)


if __name__ == "__main__":
    main()
