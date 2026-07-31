"""Language for everything the streamer reads that the backend writes.

Two kinds of text live here, and only these two:

- SQL-derived "facts". They are persisted (Insight.evidence, recommendation
  evidence) and rendered verbatim in the web app, so they have to be written in
  the channel's language at generation time. Retranslating stored text later is
  not possible.
- Fixed labels a fact interpolates (weekday, day period, record metric).

LLM *prompts* are deliberately NOT here: they stay in English in their own
modules and carry an "answer in <language>" instruction, so there is one prompt
to maintain instead of one per language. Only the model's answer is localized.

The channel's language comes from channels.language (Helix, see
core.channels.channel_language); anything not English falls back to Portuguese,
which is what every channel registered so far speaks.
"""

from typing import Final

DEFAULT_LANGUAGE: Final = "pt"
SUPPORTED_LANGUAGES: Final = ("en", "pt")

# What to tell the model to write in. Spelled out ("Brazilian Portuguese", not
# "pt") because model output quality is noticeably better with the full name.
_LANGUAGE_NAMES: Final[dict[str, str]] = {
    "en": "English",
    "pt": "Brazilian Portuguese",
}

_MESSAGES: Final[dict[str, dict[str, str]]] = {
    # monetization facts
    "fact.whale_risk": {
        "en": (
            "Your biggest contributor ({login}) accounts for {pct}% of the "
            "revenue: a risk of depending on one person."
        ),
        "pt": (
            "Seu maior contribuinte ({login}) concentra {pct}% da receita: "
            "risco de depender de uma pessoa só."
        ),
    },
    "fact.category_efficiency": {
        "en": (
            "The '{category}' category earns US$ {rate}/h, {lift}x your channel "
            "average (US$ {average}/h): give it more room on the schedule."
        ),
        "pt": (
            "A categoria '{category}' rende US$ {rate}/h, {lift}x a média das "
            "suas lives (US$ {average}/h): priorize-a na grade."
        ),
    },
    "fact.best_period": {
        "en": (
            "Lives in the {best} earn US$ {best_rate}/h, {lift}x the ones in "
            "the {worst}: concentrate on that slot."
        ),
        "pt": (
            "Lives no período da {best} rendem US$ {best_rate}/h, {lift}x as da "
            "{worst}: concentre nesse horário."
        ),
    },
    "fact.subscriber_trend": {
        "en": (
            "Across the analyzed lives you gained {gained} and lost {lost} "
            "subscriber(s) (net {net})."
        ),
        "pt": (
            "Nas lives analisadas você ganhou {gained} e perdeu {lost} assinante(s) (saldo {net})."
        ),
    },
    "fact.category_engagement": {
        "en": (
            "'{best}' lives get {best_pct}% of the audience into chat, {lift}x "
            "'{worst}' ({worst_pct}%): that theme builds more community."
        ),
        "pt": (
            "Lives de '{best}' têm {best_pct}% do público no chat, {lift}x "
            "'{worst}' ({worst_pct}%): esse tema cria mais comunidade."
        ),
    },
    "fact.top_reward": {
        "en": (
            "The most redeemed channel-points reward is '{title}' ({times}x), "
            "ahead of the rest: feature it to drive engagement."
        ),
        "pt": (
            "A recompensa de pontos mais resgatada é '{title}' ({times}x), à "
            "frente das demais: destaque-a para engajar."
        ),
    },
    # record facts
    "fact.best_marks": {
        "en": "Channel best marks (targets to beat): {marks}",
        "pt": "Melhores marcas do canal (metas a superar): {marks}",
    },
    "fact.broke_records": {
        "en": "The last analyzed live broke the channel record in: {labels}",
        "pt": "A última live analisada bateu o recorde do canal em: {labels}",
    },
    # follower facts
    "fact.silent_share": {
        "en": "{silent} of your {total} followers ({pct}%) have never written in chat.",
        "pt": "{silent} dos seus {total} seguidores ({pct}%) nunca escreveram no chat.",
    },
    "fact.streamer_followers": {
        "en": (
            "{affiliates} followers are Twitch affiliates and {partners} are "
            "partners (streamers, so collab candidates)."
        ),
        "pt": (
            "{affiliates} seguidores são afiliados e {partners} são parceiros "
            "da Twitch (ou seja, streamers, candidatos a collab)."
        ),
    },
    "fact.young_accounts": {
        "en": (
            "{pct}% of followers followed with accounts under {days} days old "
            "(possible follow-bot or bought follows)."
        ),
        "pt": (
            "{pct}% dos seguidores seguiram com contas de menos de {days} dias "
            "(possível follow-bot ou follows comprados)."
        ),
    },
    "fact.follow_timing": {
        "en": "{pct}% of your follows arrive on {weekday}.",
        "pt": "{pct}% dos seus follows chegam na {weekday}.",
    },
    # per-live analysis facts
    "fact.retention": {
        "en": "[context] RETENTION: you kept {pct}% of the viewer peak",
        "pt": "[contexto] RETENÇÃO: você segurou {pct}% do pico de audiência",
    },
    "fact.retention_vs_median": {
        "en": (
            "[context] RETENTION: you kept {pct}% of the peak, {points} points "
            "{direction} your average ({median}%)"
        ),
        "pt": (
            "[contexto] RETENÇÃO: você segurou {pct}% do pico, {points} pontos "
            "{direction} da sua média ({median}%)"
        ),
    },
    "fact.peak": {
        "en": ("PEAK at {time}: chat ran {score}x normal while you were saying '{text}'"),
        "pt": ("PICO às {time}: o chat foi {score}x o normal enquanto você falava '{text}'"),
    },
    "fact.dip": {
        "en": ("DIP at {time}: lost {pct}% of the audience{cause} while you were saying '{text}'"),
        "pt": ("QUEDA às {time}: perdeu {pct}% da audiência{cause} enquanto você falava '{text}'"),
    },
    "fact.dip_cause": {
        "en": ", right after {cause},",
        "pt": ", logo após {cause},",
    },
    # what was on screen / what caused a viewer drop
    "scene.music": {"en": "playing music", "pt": "tocando música"},
    "scene.silence": {"en": "not speaking", "pt": "sem falar"},
    "scene.guest": {"en": "talking to a guest", "pt": "conversa com convidado"},
    "cause.adBreak": {"en": "an ad", "pt": "anúncio"},
    "cause.adBreakSeconds": {
        "en": "a {seconds}s ad",
        "pt": "anúncio de {seconds}s",
    },
    "cause.categoryChange": {
        "en": "a switch to {category}",
        "pt": "troca para {category}",
    },
    # labels facts interpolate
    "direction.above": {"en": "above", "pt": "acima"},
    "direction.below": {"en": "below", "pt": "abaixo"},
    "period.morning": {"en": "morning", "pt": "manhã"},
    "period.afternoon": {"en": "afternoon", "pt": "tarde"},
    "period.evening": {"en": "evening", "pt": "noite"},
    "weekday.0": {"en": "Monday", "pt": "segunda"},
    "weekday.1": {"en": "Tuesday", "pt": "terça"},
    "weekday.2": {"en": "Wednesday", "pt": "quarta"},
    "weekday.3": {"en": "Thursday", "pt": "quinta"},
    "weekday.4": {"en": "Friday", "pt": "sexta"},
    "weekday.5": {"en": "Saturday", "pt": "sábado"},
    "weekday.6": {"en": "Sunday", "pt": "domingo"},
    "record.messages": {"en": "chat messages", "pt": "mensagens no chat"},
    "record.chatters": {"en": "unique chatters", "pt": "chatters únicos"},
    "record.events": {"en": "events", "pt": "eventos"},
    "record.follows": {"en": "followers gained", "pt": "seguidores ganhos"},
    "record.peak_viewers": {"en": "peak viewers", "pt": "pico de viewers"},
    "record.avg_viewers": {"en": "average viewers", "pt": "média de viewers"},
    "record.duration_minutes": {"en": "duration", "pt": "duração"},
    "record.subs": {"en": "subscriptions", "pt": "inscrições"},
    "record.gifts": {"en": "gifted subs", "pt": "subs presenteados"},
    "record.bits": {"en": "bits", "pt": "bits"},
    "record.raids": {"en": "raids received", "pt": "raids recebidos"},
    "record.revenue_usd": {"en": "estimated revenue", "pt": "receita estimada"},
    "record.messages_per_min": {
        "en": "chat pace (msgs/min)",
        "pt": "ritmo de chat (msgs/min)",
    },
    "record.resubs": {"en": "resubs", "pt": "resubs"},
    # weekly digest email
    "weekly.greeting": {"en": "Hi, {name}.", "pt": "Oi, {name}."},
    "weekly.intro": {
        "en": "Recap of your lives from {week}.",
        "pt": "Resumo das suas lives de {week}.",
    },
    # Dates in the email follow the reader's convention, not the server's.
    "weekly.dateFormat": {"en": "%m/%d", "pt": "%d/%m"},
    "weekly.lives": {"en": "{n} live", "pt": "{n} live"},
    "weekly.livesPlural": {"en": "{n} lives", "pt": "{n} lives"},
    "weekly.metricLine": {
        "en": "{label}: <strong>{value}</strong>{delta}",
        "pt": "{label}: <strong>{value}</strong>{delta}",
    },
    "weekly.uniqueChatters": {
        "en": "different people in chat",
        "pt": "pessoas diferentes no chat",
    },
    "weekly.delta": {
        "en": " ({sign}{pct}% vs last week)",
        "pt": " ({sign}{pct}% vs semana passada)",
    },
    "weekly.records": {
        "en": "<strong>Records you broke:</strong> {broken}.",
        "pt": "<strong>Recordes que você bateu:</strong> {broken}.",
    },
    "weekly.moments": {
        "en": "<strong>Best moments</strong>",
        "pt": "<strong>Melhores momentos</strong>",
    },
    "weekly.momentIn": {"en": ' in "{title}"', "pt": ' em "{title}"'},
    "weekly.topTopic": {
        "en": "<strong>Topic that came up most:</strong> {name} ({count} of {total}).",
        "pt": "<strong>Assunto que mais apareceu:</strong> {name} ({count} de {total}).",
    },
    "weekly.otherTopics": {
        "en": "Also talked about: {rest}.",
        "pt": "Também falou de: {rest}.",
    },
    "weekly.clips": {
        "en": "<strong>Clips you saved</strong>",
        "pt": "<strong>Clips que você guardou</strong>",
    },
    "weekly.untitledClip": {"en": "untitled clip", "pt": "clip sem título"},
    "weekly.untitledLive": {"en": "No title", "pt": "Sem título"},
    "weekly.cta": {
        "en": "See everything in the dashboard",
        "pt": "Ver tudo no painel",
    },
}


def resolve(language: str | None) -> str:
    """Any BCP-47 tag narrowed to a catalog we ship."""
    return "en" if (language or "").lower().startswith("en") else DEFAULT_LANGUAGE


def language_name(language: str | None) -> str:
    """Full language name, for the 'answer in X' line of an LLM prompt."""
    return _LANGUAGE_NAMES[resolve(language)]


def format_number(value: float, language: str | None, decimals: int = 0) -> str:
    """Thousands and decimal separators the reader expects: 1,234.5 in English,
    1.234,5 in Portuguese."""
    text = f"{value:,.{decimals}f}"
    if resolve(language) == "en":
        return text
    # swap , and . in one pass, via a placeholder the input can never contain
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def t(language: str | None, key: str, **params: object) -> str:
    """Message in the channel's language, with `{name}` placeholders filled."""
    return _MESSAGES[key][resolve(language)].format(**params)
