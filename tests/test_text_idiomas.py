"""A analise de chat tem que funcionar no idioma do canal.

O convite promete duas telas: "quais assuntos fazem o chat reagir" e a reacao do
chat. As duas saem daqui. Com o lexico e as stopwords fixos em portugues, um canal
em ingles recebe `the`/`you` como assuntos e reacao vazia, que e pior que interface
em portugues: e produto que nao funciona, e vira reclamacao de spam.
"""

from core.text import meaningful_words, message_sentiment, tokenize


def sentimento(frase: str, idioma: str) -> float | None:
    return message_sentiment(tokenize(frase), idioma)


def test_chat_em_ingles_pontua_com_o_lexico_ingles():
    assert sentimento("that was an insane clutch", "en") > 0.5


def test_chat_em_ingles_com_lexico_portugues_nao_pontua_nada():
    """E o bug que a fase 2 existe para consertar."""
    assert sentimento("that was an insane clutch", "pt") is None


def test_chat_em_portugues_continua_pontuando():
    assert sentimento("que jogada incrivel", "pt") > 0.5


def test_reclamacao_em_ingles_pontua_negativo():
    assert sentimento("this is boring and trash", "en") < 0


def test_risada_vale_nos_dois_idiomas():
    """`kkkk` e `lmao` ja caem no mesmo padrao, entao nao dependem de lexico."""
    assert sentimento("kkkk", "pt") == sentimento("lol", "en")


def test_assuntos_em_ingles_descartam_cola_gramatical():
    palavras = meaningful_words(
        "bro that boss fight was really just insane", None, "en"
    )

    assert "boss" in palavras and "fight" in palavras
    assert "bro" not in palavras and "really" not in palavras and "just" not in palavras


def test_assuntos_em_ingles_com_stopwords_portuguesas_devolvem_lixo():
    palavras = meaningful_words(
        "bro that boss fight was really just insane", None, "pt"
    )

    assert "bro" in palavras and "just" in palavras


def test_emoji_pontua_igual_nos_dois_idiomas():
    """Emoji nao tem idioma. Sem isso, o chat em ingles que responde em 🔥 e 💀
    marca reacao neutra, e o grafico de sentimento sai vazio justamente no canal
    que o convite foi buscar."""
    assert sentimento("🔥", "en") == sentimento("🔥", "pt") > 0
    assert sentimento("😡", "en") == sentimento("😡", "pt") < 0


def test_coracao_pontua_apesar_do_seletor_de_variacao():
    """O teclado manda ❤ seguido de U+FE0F. A chave tinha os dois codepoints, o
    tokenizador separava, e nada casava: o coracao nunca pontuou em idioma
    nenhum."""
    assert tokenize("❤️") == ["❤"]
    assert sentimento("❤️", "pt") == sentimento("❤️", "en") > 0


def test_idioma_desconhecido_cai_em_portugues():
    """`resolve` normaliza qualquer tag BCP-47; login nunca deve quebrar a analise."""
    assert sentimento("que jogada incrivel", None) > 0.5
    assert sentimento("que jogada incrivel", "pt-BR") > 0.5
