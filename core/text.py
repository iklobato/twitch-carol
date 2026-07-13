"""Chat text analysis primitives shared by the community and dashboard
endpoints: tokenizer, Portuguese stopwords, BR-Twitch sentiment lexicon,
word extraction and emote recovery from IRC ranges.

Sentiment is a transparent lexicon heuristic (slang, laughter, emojis); its
ceiling (no sarcasm/negation) is accepted for v1. Upgrade path: sampling
messages through the local LLM at analyze time.
"""

import re

MIN_WORD_LENGTH = 3
LAUGH_SCORE = 0.6

STOPWORDS = frozenset(
    """a o e é de da do das dos em no na nos nas um uma uns umas que com para pra pro
    por se não nao sim mais menos muito muita muitos muitas pouco ja já foi ser ter
    tem tinha vai vou como quando onde quem qual quais isso isto aquilo ele ela eles
    elas você voce vc vcs eu tu nós nos meu minha seu sua teu tua dele dela deles
    ao aos à às até entre sobre sem sob mas ou nem porque porquê pois então entao
    lá la aqui ali agora hoje ontem amanhã amanha depois antes sempre nunca também
    tambem só so ainda outra outro outros outras esse essa esses essas este esta
    estes estas era são sao está esta estão estao estou tô to tava fazer faz fez
    dia gente cara mano tipo coisa pelo pela pelos pelas desse dessa deste desta
    disso nisso nesse nessa neste nesta num numa hein né ne aí ai eh tá ta pode
    the is are was and you for this that with
    """.split()
)

# score in [-1, 1]; BR Twitch chat vocabulary
LEXICON: dict[str, float] = {
    "bom": 0.5,
    "boa": 0.5,
    "ótimo": 1.0,
    "otimo": 1.0,
    "incrível": 1.0,
    "incrivel": 1.0,
    "top": 0.7,
    "brabo": 0.8,
    "braba": 0.8,
    "foda": 0.8,
    "lindo": 0.7,
    "linda": 0.7,
    "amei": 1.0,
    "amo": 0.9,
    "adoro": 0.8,
    "perfeito": 1.0,
    "perfeita": 1.0,
    "gg": 0.6,
    "pog": 0.8,
    "poggers": 0.8,
    "hype": 0.7,
    "demais": 0.5,
    "massa": 0.7,
    "maneiro": 0.6,
    "legal": 0.5,
    "show": 0.6,
    "aula": 0.6,
    "genial": 0.9,
    "obrigado": 0.6,
    "obrigada": 0.6,
    "valeu": 0.5,
    "parabéns": 0.8,
    "parabens": 0.8,
    "melhor": 0.6,
    "vitória": 0.8,
    "vitoria": 0.8,
    "ganhou": 0.6,
    "clipa": 0.6,
    "absurda": 0.6,
    "absurdo": 0.6,
    "ruim": -0.6,
    "péssimo": -1.0,
    "pessimo": -1.0,
    "horrível": -1.0,
    "horrivel": -1.0,
    "lixo": -1.0,
    "chato": -0.6,
    "chata": -0.6,
    "triste": -0.6,
    "odeio": -1.0,
    "flop": -0.7,
    "cringe": -0.6,
    "bosta": -1.0,
    "merda": -0.9,
    "lag": -0.5,
    "travou": -0.5,
    "caiu": -0.5,
    "bugou": -0.4,
    "perdeu": -0.5,
    "derrota": -0.7,
    "fail": -0.6,
    "aff": -0.5,
    "credo": -0.6,
    "pior": -0.7,
    "😂": 0.6,
    "❤️": 0.8,
    "🔥": 0.7,
    "👏": 0.6,
    "😍": 0.9,
    "🎉": 0.7,
    "😡": -0.8,
    "👎": -0.7,
    "😢": -0.6,
    "💀": 0.3,
}
LAUGH_PATTERN = re.compile(
    r"^(?:k{3,}|(?:ha){2,}h?|(?:rs){2,}|lol|lul|omegalul|kekw)$", re.IGNORECASE
)
TOKEN_PATTERN = re.compile(r"[0-9a-zà-öø-ÿ_]+|[\U0001F300-\U0001FAFF❤️]", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def message_sentiment(tokens: list[str]) -> float | None:
    """Mean of matched lexicon scores; None when nothing matched (neutral
    messages don't dilute the averages)."""
    scores = []
    for token in tokens:
        if LAUGH_PATTERN.match(token):
            scores.append(LAUGH_SCORE)
            continue
        if token in LEXICON:
            scores.append(LEXICON[token])
    if not scores:
        return None
    return sum(scores) / len(scores)


def strip_emotes(text: str, emotes: dict | None) -> str:
    if not emotes:
        return text
    result = list(text)
    for ranges in emotes.values():
        for span in ranges:
            start, _, end = span.partition("-")
            if start.isdigit() and end.isdigit():
                for index in range(int(start), min(int(end) + 1, len(result))):
                    result[index] = " "
    return "".join(result)


def emote_occurrences(text: str, emotes: dict | None) -> list[tuple[str, str]]:
    """(emote_id, name) per occurrence, recovered from the IRC ranges. The id
    builds the Twitch CDN url; the name is the text slice the id covered."""
    if not emotes:
        return []
    found = []
    for emote_id, ranges in emotes.items():
        for span in ranges:
            start, _, end = span.partition("-")
            if start.isdigit() and end.isdigit():
                name = text[int(start) : int(end) + 1].strip()
                if name:
                    found.append((str(emote_id), name))
    return found


def emote_names(text: str, emotes: dict | None) -> list[str]:
    """Emote occurrences by name only."""
    return [name for _, name in emote_occurrences(text, emotes)]


def meaningful_words(text: str, emotes: dict | None) -> list[str]:
    """Content words from a message: emotes stripped, stopwords/digits/laughter
    and very short tokens removed."""
    result = []
    for token in tokenize(strip_emotes(text, emotes)):
        if (
            len(token) >= MIN_WORD_LENGTH
            and token not in STOPWORDS
            and not token.isdigit()
            and not LAUGH_PATTERN.match(token)
        ):
            result.append(token)
    return result
