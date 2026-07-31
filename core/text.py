"""Chat text analysis primitives shared by the community and dashboard
endpoints: tokenizer, Portuguese stopwords, BR-Twitch sentiment lexicon,
word extraction and emote recovery from IRC ranges.

Sentiment is a transparent lexicon heuristic (slang, laughter, emojis); its
ceiling (no sarcasm/negation) is accepted for v1. Upgrade path: sampling
messages through the local LLM at analyze time.
"""

import re

from core.i18n import resolve

MIN_WORD_LENGTH = 3
LAUGH_SCORE = 0.6

STOPWORDS_PT = frozenset(
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

# Ingles: lista curta de funcao, no mesmo espirito da de portugues. O que decide
# "assunto da live" e a palavra de conteudo, entao tudo que e cola gramatical sai.
STOPWORDS_EN = frozenset(
    """a an the this that these those i you he she it we they me him her us them
    my your his its our their mine yours is are was were be been being am do does
    did doing have has had having will would shall should can could may might must
    of in on at by for with about against between into through during before after
    above below to from up down out off over under again further then once here
    there when where why how all any both each few more most other some such no
    nor not only own same so than too very just now got get gets like really
    yeah yes ok okay lol lmao bro dude guys gonna wanna kinda sorta
    what who whom which whose and but or if because as until while
    """.split()
)

# Idioma -> palavras que nao viram assunto. Sem isso, canal em ingles lista
# `the`, `you` e `and` como principais temas da live.
STOPWORDS: dict[str, frozenset[str]] = {"pt": STOPWORDS_PT, "en": STOPWORDS_EN}

# score in [-1, 1]; BR Twitch chat vocabulary
LEXICON_PT: dict[str, float] = {
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

# Ingles: vocabulario de chat de Twitch, nao dicionario. Emote e risada ja sao
# neutros (o LAUGH_PATTERN cobre kkk, haha, lol, lul, kekw), entao aqui entra o
# que o chat em ingles escreve com palavra.
LEXICON_EN: dict[str, float] = {
    "good": 0.5,
    "nice": 0.6,
    "great": 0.8,
    "amazing": 1.0,
    "awesome": 0.9,
    "insane": 0.9,
    "cracked": 0.8,
    "clutch": 0.9,
    "clean": 0.7,
    "smooth": 0.6,
    "goat": 1.0,
    "based": 0.7,
    "pog": 0.8,
    "poggers": 0.8,
    "pogchamp": 0.8,
    "hype": 0.7,
    "gg": 0.6,
    "ez": 0.5,
    "w": 0.6,
    "dub": 0.6,
    "banger": 0.8,
    "sick": 0.7,
    "love": 0.9,
    "loved": 0.9,
    "beautiful": 0.8,
    "perfect": 1.0,
    "legend": 0.9,
    "king": 0.7,
    "queen": 0.7,
    "respect": 0.7,
    "congrats": 0.8,
    "thanks": 0.5,
    "welcome": 0.4,
    "funny": 0.7,
    "hilarious": 0.9,
    "cute": 0.6,
    "wholesome": 0.8,
    "bad": -0.5,
    "awful": -0.9,
    "terrible": -0.9,
    "trash": -0.8,
    "garbage": -0.8,
    "cringe": -0.6,
    "boring": -0.7,
    "l": -0.6,
    "rip": -0.4,
    "sad": -0.6,
    "unlucky": -0.4,
    "scam": -0.8,
    "toxic": -0.7,
    "annoying": -0.6,
    "broken": -0.5,
    "lag": -0.5,
    "laggy": -0.5,
    "stop": -0.3,
    "worst": -1.0,
    "hate": -0.9,
}

# Idioma -> lexico de sentimento. Canal em ingles com o lexico de portugues
# devolve reacao vazia, porque nenhuma palavra casa.
LEXICON: dict[str, dict[str, float]] = {"pt": LEXICON_PT, "en": LEXICON_EN}
LAUGH_PATTERN = re.compile(
    r"^(?:k{3,}|(?:ha){2,}h?|(?:rs){2,}|lol|lul|omegalul|kekw)$", re.IGNORECASE
)
TOKEN_PATTERN = re.compile(r"[0-9a-zà-öø-ÿ_]+|[\U0001F300-\U0001FAFF❤️]", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def message_sentiment(tokens: list[str], language: str | None = None) -> float | None:
    """Mean of matched lexicon scores; None when nothing matched (neutral
    messages don't dilute the averages).

    The lexicon is per language: an English channel scored with the Portuguese
    one matches nothing and the chat-reaction chart comes back empty, which is
    exactly what the invite email promises to show."""
    lexico = LEXICON[resolve(language)]
    scores = []
    for token in tokens:
        if LAUGH_PATTERN.match(token):
            scores.append(LAUGH_SCORE)
            continue
        if token in lexico:
            scores.append(lexico[token])
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


def meaningful_words(
    text: str, emotes: dict | None, language: str | None = None
) -> list[str]:
    """Content words from a message: emotes stripped, stopwords/digits/laughter
    and very short tokens removed. Stopwords follow the channel language, or
    `the`/`you`/`and` end up as the top topics of an English stream."""
    palavras_vazias = STOPWORDS[resolve(language)]
    result = []
    for token in tokenize(strip_emotes(text, emotes)):
        if (
            len(token) >= MIN_WORD_LENGTH
            and token not in palavras_vazias
            and not token.isdigit()
            and not LAUGH_PATTERN.match(token)
        ):
            result.append(token)
    return result
