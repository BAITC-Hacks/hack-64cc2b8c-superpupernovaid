from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.protocols.models import (
    MeetingProtocol,
    ProtocolAction,
    ProtocolDecision,
    ProtocolParticipant,
    ProtocolSegment,
)


def golden_protocol():
    return MeetingProtocol(
        meeting_id=UUID("11111111-1111-4111-8111-111111111111"),
        source_transcript_id=UUID("22222222-2222-4222-8222-222222222222"),
        title="Производственные показатели және тапсырмалар",
        scheduled_at=datetime(2026, 9, 23, 10, tzinfo=timezone(timedelta(hours=5))),
        participants=(
            ProtocolParticipant(speaker_id="SPEAKER_00", participant_name="Данияр Серикович"),
            ProtocolParticipant(speaker_id="SPEAKER_01", participant_name="Әлия Қанатқызы"),
            ProtocolParticipant(speaker_id="SPEAKER_03"),
        ),
        summary="Обсудили производственные показатели. Қазақша: Қ Ғ Ә Ө Ұ Ү І Ң, қ ғ ә ө ұ ү і ң.",
        topics=("Поставка сырья и сроки", "Қауіпсіздік және обучение"),
        decisions=(
            ProtocolDecision(
                text="Запросить расчёт альтернативной поставки.", source_segment_ids=("seg_001",)
            ),
            ProtocolDecision(
                text="Организовать дополнительные группы обучения.", source_segment_ids=("seg_002",)
            ),
        ),
        action_items=(
            ProtocolAction(
                text="Подготовить претензию поставщику.",
                assignee="Ерлан",
                deadline="До конца недели",
                status="in_progress",
                source_segment_ids=("seg_001",),
            ),
            ProtocolAction(text="Салыстыру: цена < 100 & качество > 90."),
        ),
        transcript=(
            ProtocolSegment(
                id="seg_001",
                start=12.8,
                speaker_id="SPEAKER_00",
                participant_name="Данияр Серикович",
                original_text="Обсудим сырьё.",
                canonical_text="Обсудим поставку сырья.",
            ),
            ProtocolSegment(
                id="seg_002",
                start=28.1,
                speaker_id="SPEAKER_01",
                participant_name="Әлия Қанатқызы",
                original_text="Ертең отчетты до обеда жіберіңіз.",
                canonical_text="Ертең отчетты до обеда жіберіңіз.",
            ),
            ProtocolSegment(
                id="seg_003",
                start=5667.9,
                speaker_id="SPEAKER_03",
                original_text="Қ Ғ Ә Ө Ұ Ү І Ң. Unresolved speaker, text unchanged.",
            ),
        ),
    )
