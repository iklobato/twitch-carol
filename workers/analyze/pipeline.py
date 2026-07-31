"""Post-transcription analysis: summary, peak explanations and ranked topics.

Budget order follows the PRD's smart-truncation rule: peak windows first,
then the incremental summary, then topics (which reuse the block summaries).
Every insight passes evidence validation before being stored: cited ids must
have been shown in the prompt AND exist in the database.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.analytics import (
    dip_cause,
    load_speech_segments,
    load_viewer_samples,
    retention_and_dips,
)
from core.config import get_settings
from core.follower_ai import generate_follower_ai
from core.follower_intel import build_follower_facts, generate_follower_recommendations
from core.i18n import language_name, t
from core.llm import LLMBackend, TokenBudget
from core.models import (
    Channel,
    ChatMessage,
    Insight,
    InsightType,
    Peak,
    SegmentKind,
    Stream,
    StreamStatus,
    TranscriptSegment,
)
from core.monetization import build_monetization_facts, generate_channel_recommendations
from core.records import RecordMetric, add_record_facts, update_stream_records
from workers.analyze.evidence import validated_evidence
from workers.analyze.peaks import compute_and_store_peaks

logger = logging.getLogger(__name__)

BLOCK_MINUTES = 15
PEAK_PROMPT_INPUT_CAP = 3000
BLOCK_PROMPT_INPUT_CAP = 1800
TOPICS_PROMPT_INPUT_CAP = 3000
# generous output caps: a hard cut mid-JSON makes the whole response invalid
# (small models ramble; 400 was measurably truncating block summaries)
PEAK_OUTPUT_TOKENS = 500
BLOCK_OUTPUT_TOKENS = 600
SUMMARY_OUTPUT_TOKENS = 700
TOPICS_OUTPUT_TOKENS = 700
PEAK_CHAT_SAMPLE = 25
BLOCK_CHAT_SAMPLE = 15
EVIDENCE_SEGMENT_SAMPLE = 12
TOPIC_MAX = 5
# A topic name is a label, not a chat dump; and two topics that share most of
# their words are the same subject sliced twice.
TOPIC_NAME_MAX_CHARS = 60
TOPIC_SIMILARITY_MAX = 0.6
RECOMMEND_OUTPUT_TOKENS = 700
# What summary + topics + recommendations need to be allowed to run at all.
# Block summarizing must never spend below this, whatever the live's length.
FINAL_STEPS_INPUT_RESERVE = 3 * TOPICS_PROMPT_INPUT_CAP
FINAL_STEPS_OUTPUT_RESERVE = (
    SUMMARY_OUTPUT_TOKENS + TOPICS_OUTPUT_TOKENS + RECOMMEND_OUTPUT_TOKENS
)
RECOMMEND_MAX = 3
RECOMMEND_TOP_PEAKS = 3


def _json_instruction(language: str | None) -> str:
    """Prompts stay English whatever the channel speaks; only the model's answer
    is written in the channel's language."""
    return (
        'Reply with valid JSON ONLY: {"content": "<text written in '
        f'{language_name(language)}>", '
        '"message_ids": [ids of the chat messages you cite], '
        '"segment_ids": [ids of the speech segments you cite]}. '
        "Use only ids listed above and cite at least one real piece of evidence. "
        "The content field is at most 400 characters; do not repeat chat messages."
    )


@dataclass
class AnalysisStats:
    insights_stored: int = 0
    insights_discarded: int = 0
    skipped_for_budget: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PromptContext:
    text: str
    message_ids: set[int]
    segment_ids: set[int]


def run_analysis(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    strong_backend: LLMBackend | None = None,
) -> AnalysisStats:
    settings = get_settings()
    # High-value tasks (recommendations, follower AI) use the stronger model;
    # mechanical summaries use the default. Falls back to one model if unset.
    strong = strong_backend or backend
    budget = TokenBudget(
        backend, settings.llm_max_input_tokens, settings.llm_max_output_tokens
    )
    stats = AnalysisStats()
    # Everything the streamer reads out of this run is written in their own
    # channel's language: the model answers in it, and the SQL facts we store
    # alongside are built in it too.
    language = db.scalar(
        select(Channel.language).where(Channel.id == stream.channel_id)
    )

    db.execute(delete(Insight).where(Insight.stream_id == stream.id))
    broke_records = update_stream_records(db, stream)
    peaks = compute_and_store_peaks(db, stream)

    for peak in peaks:
        _explain_peak(db, stream, backend, budget, peak, stats, language)

    block_summaries = _summarize_blocks(db, stream, backend, budget, stats, language)
    if block_summaries:
        _final_summary(db, stream, backend, budget, block_summaries, stats, language)
        _rank_topics(db, stream, backend, budget, block_summaries, stats, language)

    _recommend(db, stream, strong, budget, stats, language)
    _recommend_channel(db, stream, strong, budget, broke_records, language)

    db.flush()
    logger.info(
        "analysis done: %d stored, %d discarded, skipped=%s, tokens in/out %d/%d",
        stats.insights_stored,
        stats.insights_discarded,
        stats.skipped_for_budget,
        budget.input_spent,
        budget.output_spent,
        extra={"stream_id": stream.id},
    )
    return stats


def _recommend_channel(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    broke_records: list[RecordMetric],
    language: str | None,
) -> None:
    """Refresh the account-level monetization recommendations after each stream
    is analyzed, grounded in the channel's SQL facts (records included)."""
    ready_ids = list(
        db.scalars(
            select(Stream.id)
            .where(Stream.channel_id == stream.channel_id)
            .where(Stream.status == StreamStatus.READY)
        )
    )
    facts = build_monetization_facts(db, stream.channel_id, ready_ids, language)
    add_record_facts(db, stream.channel_id, broke_records, facts, language)
    generate_channel_recommendations(
        db, stream.channel_id, facts, backend, budget, language
    )
    follower_facts = build_follower_facts(db, stream.channel_id, language)
    generate_follower_recommendations(
        db, stream.channel_id, follower_facts, backend, budget, language
    )
    generate_follower_ai(db, stream.channel_id, backend, budget, language)


def _window_context(
    db: Session, stream: Stream, start: datetime, end: datetime, chat_sample: int
) -> PromptContext:
    """Evidence candidates for a window: transcript excerpts and chat
    messages, each prefixed with its real DB id."""
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.stream_id == stream.id)
        .where(TranscriptSegment.kind == SegmentKind.SPEECH)
        .where(TranscriptSegment.started_at < end)
        .where(TranscriptSegment.ended_at > start)
        .order_by(TranscriptSegment.started_at)
    ).all()
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.stream_id == stream.id)
        .where(ChatMessage.sent_at >= start)
        .where(ChatMessage.sent_at < end)
        .order_by(ChatMessage.sent_at)
        .limit(chat_sample)
    ).all()

    lines = ["TRECHOS DA FALA (segment_id: texto):"]
    lines.extend(f"{s.id}: {s.text}" for s in segments if s.text)
    lines.append("MENSAGENS DO CHAT (message_id: autor: texto):")
    lines.extend(f"{m.id}: {m.author_login}: {m.text}" for m in messages)
    return PromptContext(
        text="\n".join(lines),
        message_ids={m.id for m in messages},
        segment_ids={s.id for s in segments},
    )


def _call_and_store(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    prompt: str,
    output_tokens: int,
    insight_type: InsightType,
    context: PromptContext,
    stats: AnalysisStats,
    extra_evidence: dict | None = None,
) -> str | None:
    """Runs one LLM call and stores the insight only if its evidence checks
    out against the prompt candidates and the database."""
    response = backend.generate(prompt, output_tokens)
    budget.spend(prompt, response)
    parsed = _parse_json(response)
    if parsed is None or not str(parsed.get("content", "")).strip():
        stats.insights_discarded += 1
        logger.warning(
            "insight discarded: unparseable output", extra={"stream_id": stream.id}
        )
        return None

    evidence = validated_evidence(
        db, stream.id, parsed, context.message_ids, context.segment_ids
    )
    if evidence is None:
        stats.insights_discarded += 1
        logger.warning(
            "insight discarded: no verifiable evidence",
            extra={"stream_id": stream.id, "event_type": insight_type.value},
        )
        return None
    if extra_evidence:
        evidence.update(extra_evidence)

    db.add(
        Insight(
            stream_id=stream.id,
            type=insight_type,
            content=str(parsed["content"]).strip(),
            evidence=evidence,
            model_used=backend.model_name,
            tokens_in=budget.input_spent,
            tokens_out=budget.output_spent,
        )
    )
    stats.insights_stored += 1
    return str(parsed["content"]).strip()


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _parse_json(response: str) -> dict | None:
    # Some models (e.g. Anthropic via OpenRouter) wrap JSON in a markdown code
    # fence despite response_format=json_object; unwrap before parsing.
    fenced = _JSON_FENCE.match(response)
    text = fenced.group(1) if fenced else response
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _explain_peak(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    peak: Peak,
    stats: AnalysisStats,
    language: str | None,
) -> None:
    if not budget.can_afford(PEAK_PROMPT_INPUT_CAP, PEAK_OUTPUT_TOKENS):
        stats.skipped_for_budget.append(f"peak@{peak.window_start:%H:%M}")
        return
    context = _window_context(
        db, stream, peak.window_start, peak.window_end, PEAK_CHAT_SAMPLE
    )
    fitted = budget.fit_input(context.text, PEAK_PROMPT_INPUT_CAP)
    prompt = (
        f"The chat of a Twitch live hit {peak.score:.1f}x its normal pace between "
        f"{peak.window_start:%H:%M:%S} and {peak.window_end:%H:%M:%S} (UTC).\n{fitted}\n"
        "Explain in 2 or 3 sentences what caused this chat peak. "
        + _json_instruction(language)
    )
    _call_and_store(
        db,
        stream,
        backend,
        budget,
        prompt,
        PEAK_OUTPUT_TOKENS,
        InsightType.PEAK_EXPLANATION,
        context,
        stats,
        extra_evidence={
            "window": {
                "start": peak.window_start.isoformat(),
                "end": peak.window_end.isoformat(),
            },
            "peak_id": peak.id,
        },
    )


def _stream_blocks(stream: Stream) -> list[tuple[datetime, datetime]]:
    if stream.ended_at is None:
        return []
    blocks = []
    cursor = stream.started_at
    while cursor < stream.ended_at:
        end = min(cursor + timedelta(minutes=BLOCK_MINUTES), stream.ended_at)
        blocks.append((cursor, end))
        cursor = end
    return blocks


def _summarize_blocks(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    stats: AnalysisStats,
    language: str | None,
) -> list[str]:
    summaries: list[str] = []
    for start, end in _stream_blocks(stream):
        # Blocks scale with how long the live ran, the final steps do not, and
        # the final steps are the ones the streamer actually reads. Without this
        # reserve a long live spends the whole budget narrating its own middle
        # and arrives at summary/topics/recommendations with nothing left.
        if not budget.can_afford(
            BLOCK_PROMPT_INPUT_CAP + FINAL_STEPS_INPUT_RESERVE,
            BLOCK_OUTPUT_TOKENS + FINAL_STEPS_OUTPUT_RESERVE,
        ):
            stats.skipped_for_budget.append(f"block@{start:%H:%M}")
            continue
        context = _window_context(db, stream, start, end, BLOCK_CHAT_SAMPLE)
        fitted = budget.fit_input(context.text, BLOCK_PROMPT_INPUT_CAP)
        previous = (
            f"Resumo do que aconteceu antes: {summaries[-1]}\n" if summaries else ""
        )
        prompt = (
            f"{previous}Bloco de {start:%H:%M} a {end:%H:%M} (UTC) de uma live na Twitch.\n"
            f"{fitted}\nSummarize this block in at most 3 sentences. "
            + _json_instruction(language)
        )
        response = backend.generate(prompt, BLOCK_OUTPUT_TOKENS)
        budget.spend(prompt, response)
        parsed = _parse_json(response)
        if parsed is None or not str(parsed.get("content", "")).strip():
            logger.warning(
                "block summary unparseable, block skipped",
                extra={"stream_id": stream.id},
            )
            continue
        summaries.append(str(parsed["content"]).strip())
    return summaries


def _evidence_segment_context(db: Session, stream: Stream) -> PromptContext:
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.stream_id == stream.id)
        .where(TranscriptSegment.kind == SegmentKind.SPEECH)
        .order_by(TranscriptSegment.started_at)
        .limit(EVIDENCE_SEGMENT_SAMPLE)
    ).all()
    text = "\n".join(f"{s.id}: {s.text}" for s in segments if s.text)
    return PromptContext(
        text=f"TRECHOS DA FALA (segment_id: texto):\n{text}",
        message_ids=set(),
        segment_ids={s.id for s in segments},
    )


def _final_summary(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    block_summaries: list[str],
    stats: AnalysisStats,
    language: str | None,
) -> None:
    if not budget.can_afford(TOPICS_PROMPT_INPUT_CAP, SUMMARY_OUTPUT_TOKENS):
        stats.skipped_for_budget.append("summary")
        return
    context = _evidence_segment_context(db, stream)
    joined = budget.fit_input(
        "\n".join(f"- {s}" for s in block_summaries), TOPICS_PROMPT_INPUT_CAP
    )
    prompt = (
        f"Resumos por bloco de uma live na Twitch, em ordem:\n{joined}\n{context.text}\n"
        f"Write the overall summary of the live in one paragraph. "
        + _json_instruction(language)
    )
    _call_and_store(
        db,
        stream,
        backend,
        budget,
        prompt,
        SUMMARY_OUTPUT_TOKENS,
        InsightType.SUMMARY,
        context,
        stats,
    )


def _rank_topics(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    block_summaries: list[str],
    stats: AnalysisStats,
    language: str | None,
) -> None:
    """One insight per topic, ranked; each topic validates its own evidence."""
    if not budget.can_afford(TOPICS_PROMPT_INPUT_CAP, TOPICS_OUTPUT_TOKENS):
        stats.skipped_for_budget.append("topics")
        return
    context = _evidence_segment_context(db, stream)
    joined = budget.fit_input(
        "\n".join(f"- {s}" for s in block_summaries), TOPICS_PROMPT_INPUT_CAP
    )
    prompt = (
        f"Resumos por bloco de uma live na Twitch:\n{joined}\n{context.text}\n"
        "Identify the main topics of the live, from most to least talked about. "
        'Reply with valid JSON ONLY: {"topics": [{"name": "<topic in a few words>", '
        f'"description": "<1 sentence written in {language_name(language)}>", '
        '"segment_ids": [ids of the speech segments], "message_ids": []}]}. '
        f"Use only ids listed above, at most {TOPIC_MAX} DISTINCT topics (do not "
        "slice the same topic), cite at least one id per topic. The name is a "
        "short label, never a chat message."
    )
    response = backend.generate(prompt, TOPICS_OUTPUT_TOKENS)
    budget.spend(prompt, response)
    parsed = _parse_json(response)
    topics = parsed.get("topics") if parsed else None
    if not isinstance(topics, list):
        stats.insights_discarded += 1
        logger.warning(
            "topics discarded: unparseable output", extra={"stream_id": stream.id}
        )
        return
    _store_topics(db, stream, backend, budget, topics, context, stats)


def _topic_words(name: str) -> set[str]:
    return {
        word for word in re.sub(r"[^\w\s]", " ", name.lower()).split() if len(word) > 2
    }


def _is_duplicate_topic(name: str, kept_names: list[str]) -> bool:
    """True when `name` overlaps an already-kept topic on most of its words:
    the same subject the model split into fragments."""
    words = _topic_words(name)
    if not words:
        return False
    for other in kept_names:
        other_words = _topic_words(other)
        if not other_words:
            continue
        jaccard = len(words & other_words) / len(words | other_words)
        if jaccard >= TOPIC_SIMILARITY_MAX:
            return True
    return False


def _store_topics(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    topics: list,
    context: PromptContext,
    stats: AnalysisStats,
) -> None:
    rank = 0
    kept_names: list[str] = []
    for topic in topics[:TOPIC_MAX]:
        if not isinstance(topic, dict):
            continue
        name = str(topic.get("name", "")).strip()
        if not name or len(name) > TOPIC_NAME_MAX_CHARS:
            # a name longer than a label is a chat dump, not a topic
            continue
        if _is_duplicate_topic(name, kept_names):
            continue
        evidence = validated_evidence(
            db, stream.id, topic, context.message_ids, context.segment_ids
        )
        if evidence is None:
            stats.insights_discarded += 1
            logger.warning(
                "topic discarded: no verifiable evidence",
                extra={"stream_id": stream.id, "event_type": InsightType.TOPIC.value},
            )
            continue
        kept_names.append(name)
        rank += 1
        evidence["rank"] = rank
        description = str(topic.get("description", "")).strip()
        # first line = topic name, rest = description (the UI splits on this)
        content = f"{name}\n{description}" if description else name
        db.add(
            Insight(
                stream_id=stream.id,
                type=InsightType.TOPIC,
                content=content,
                evidence=evidence,
                model_used=backend.model_name,
                tokens_in=budget.input_spent,
                tokens_out=budget.output_spent,
            )
        )
        stats.insights_stored += 1


RECOMMEND_NEAREST_GAP = timedelta(seconds=120)


def _segment_near(
    segments: list[TranscriptSegment], moment: datetime
) -> TranscriptSegment | None:
    """Speech segment overlapping the moment, else the closest one within
    RECOMMEND_NEAREST_GAP (a peak/dip may fall between segments)."""
    best: TranscriptSegment | None = None
    best_gap = RECOMMEND_NEAREST_GAP.total_seconds()
    for segment in segments:
        if not segment.text:
            continue
        if segment.started_at <= moment <= segment.ended_at:
            return segment
        gap = min(
            abs((segment.started_at - moment).total_seconds()),
            abs((segment.ended_at - moment).total_seconds()),
        )
        if gap <= best_gap:
            best = segment
            best_gap = gap
    return best


def _channel_median_retention(
    db: Session, channel_id: int, exclude_stream_id: int
) -> float | None:
    """Median retained-% across the channel's other analyzed streams, so this
    stream's retention can be stated as above/below the streamer's own norm."""
    # ponytail: reloads sibling streams' samples each run; fine at low stream counts.
    other_ids = db.scalars(
        select(Stream.id)
        .where(Stream.channel_id == channel_id)
        .where(Stream.status == StreamStatus.READY)
        .where(Stream.id != exclude_stream_id)
    )
    rates: list[float] = []
    for other_id in other_ids:
        samples = load_viewer_samples(db, other_id)
        counts = [sample.viewer_count for sample in samples]
        peak = max(counts) if counts else 0
        if peak > 0:
            rates.append(counts[-1] / peak * 100)
    return median(rates) if rates else None


def _retention_line(
    db: Session, stream: Stream, retained_pct: float, language: str | None
) -> str:
    """A retention number alone only invites 'improve retention'; compared to
    the channel's own median it says whether THIS live held better or worse."""
    channel_median = _channel_median_retention(db, stream.channel_id, stream.id)
    if channel_median is None:
        return t(language, "fact.retention", pct=retained_pct)
    delta = retained_pct - channel_median
    direction = "direction.above" if delta >= 0 else "direction.below"
    return t(
        language,
        "fact.retention_vs_median",
        pct=retained_pct,
        points=f"{abs(delta):.0f}",
        direction=t(language, direction),
        median=f"{channel_median:.0f}",
    )


def _recommend(
    db: Session,
    stream: Stream,
    backend: LLMBackend,
    budget: TokenBudget,
    stats: AnalysisStats,
    language: str | None,
) -> None:
    """Grounded recommendations: the LLM only phrases advice around SQL facts
    (peaks, dips, retention), and each recommendation must cite a real speech
    segment from those facts, so nothing is invented."""
    if not budget.can_afford(TOPICS_PROMPT_INPUT_CAP, RECOMMEND_OUTPUT_TOKENS):
        stats.skipped_for_budget.append("recommendations")
        return

    speech = load_speech_segments(db, stream.id)
    retention, dips = retention_and_dips(
        load_viewer_samples(db, stream.id), RECOMMEND_MAX
    )
    peaks = db.scalars(
        select(Peak)
        .where(Peak.stream_id == stream.id)
        .order_by(Peak.score.desc())
        .limit(RECOMMEND_TOP_PEAKS)
    ).all()

    # Facts are numbered 1..N and each maps to a real speech segment id. The
    # model cites the small fact number (reliable for a small model); we map
    # it back to the segment id, so grounding stays SQL-anchored either way.
    lines: list[str] = []
    fact_segment: dict[int, int] = {}
    for peak in peaks:
        segment = _segment_near(speech, peak.window_start)
        if segment is not None:
            number = len(lines) + 1
            fact_segment[number] = segment.id
            lines.append(
                f"[{number}] "
                + t(
                    language,
                    "fact.peak",
                    time=f"{peak.window_start:%H:%M}",
                    score=f"{peak.score:.1f}",
                    text=segment.text,
                )
            )
    for dip in dips:
        segment = _segment_near(speech, dip.at)
        if segment is not None:
            number = len(lines) + 1
            fact_segment[number] = segment.id
            cause = dip_cause(db, stream.id, dip.at)
            cause_text = t(language, "fact.dip_cause", cause=cause) if cause else ""
            lines.append(
                f"[{number}] "
                + t(
                    language,
                    "fact.dip",
                    time=f"{dip.at:%H:%M}",
                    pct=dip.pct_drop,
                    cause=cause_text,
                    text=segment.text,
                )
            )
    if retention is not None:
        lines.append(_retention_line(db, stream, retention.retained_pct, language))

    if not fact_segment:
        return  # nothing SQL-grounded to recommend on

    prompt = (
        "FACTS measured from this Twitch live (each numbered in brackets):\n"
        + "\n".join(lines)
        + "\nBased ONLY on these facts, give practical recommendations for the "
        "next lives (do more of what worked, fix what emptied the room). Reply "
        'with valid JSON ONLY: {"recommendations": [{"content": "<recommendation '
        f'in 1-2 sentences, written in {language_name(language)}>", '
        '"fact_ids": [numbers of the facts behind it]}]}. Cite at least one fact '
        f"number per recommendation, at most {RECOMMEND_MAX}, be concrete."
    )
    response = backend.generate(prompt, RECOMMEND_OUTPUT_TOKENS)
    budget.spend(prompt, response)
    parsed = _parse_json(response)
    recommendations = parsed.get("recommendations") if parsed else None
    if not isinstance(recommendations, list):
        stats.insights_discarded += 1
        logger.warning(
            "recommendations discarded: unparseable", extra={"stream_id": stream.id}
        )
        return

    rank = 0
    for item in recommendations[:RECOMMEND_MAX]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        raw_facts = item.get("fact_ids", [])
        fact_ids = (
            [n for n in raw_facts if isinstance(n, int)]
            if isinstance(raw_facts, list)
            else []
        )
        cited_segments = sorted(
            {fact_segment[n] for n in fact_ids if n in fact_segment}
        )
        if not content or not cited_segments:
            stats.insights_discarded += 1
            logger.warning(
                "recommendation discarded: no grounded fact cited",
                extra={
                    "stream_id": stream.id,
                    "event_type": InsightType.RECOMMENDATION.value,
                },
            )
            continue
        rank += 1
        db.add(
            Insight(
                stream_id=stream.id,
                type=InsightType.RECOMMENDATION,
                content=content,
                evidence={
                    "segment_ids": cited_segments,
                    "message_ids": [],
                    "rank": rank,
                },
                model_used=backend.model_name,
                tokens_in=budget.input_spent,
                tokens_out=budget.output_spent,
            )
        )
        stats.insights_stored += 1
