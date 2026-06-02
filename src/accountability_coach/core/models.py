"""JSON-serializable ACSP domain model for the accountability coach.

The paper describes a three-layer Accountability Coaching Service Pattern
(ACSP): foundational trust and needs alignment, operational lifecycle support,
and regulatory role switching.  These dataclasses keep that structure explicit
without requiring a separate ACSP runtime object.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, TypeVar, get_args, get_origin, get_type_hints
from uuid import uuid4


STYLE_GENTLE = "gentle"
STYLE_SERIOUS = "serious"
STYLE_PLAYFUL = "playful"
STYLE_CUSTOM = "custom"

INTENSITY_STRICT = "strict"
INTENSITY_MODERATE = "moderate"
INTENSITY_LENIENT = "lenient"

ROLE_MENTOR = "mentor"
ROLE_COACH = "coach"
ROLE_EXPERT = "expert"
ROLE_PARTNER = "partner"

TASK_PENDING = "pending"
TASK_PLANNED = "planned"
TASK_IN_PROGRESS = "in_progress"
TASK_COMPLETED = "completed"
TASK_SKIPPED = "skipped"
TASK_DEFERRED = "deferred"

CHECKIN_COMPLETED = "completed"
CHECKIN_PARTIAL = "partial"
CHECKIN_SKIPPED = "skipped"
CHECKIN_DELAYED = "delayed"

REMINDER_SCHEDULED = "scheduled"
REMINDER_ADAPTIVE = "adaptive"
REMINDER_SPOT_CHECK = "spot_check"

EVIDENCE_CONSISTENT = "consistent"
EVIDENCE_UNCERTAIN = "uncertain"
EVIDENCE_SUSPICIOUS = "suspicious"
EVIDENCE_MISSING = "missing"

COMMITMENT_PROPOSED = "proposed"
COMMITMENT_ACTIVE = "active"
COMMITMENT_FULFILLED = "fulfilled"
COMMITMENT_BREACHED = "breached"

COPRESENCE_ACTIVE = "active"
COPRESENCE_COMPLETED = "completed"
COPRESENCE_INTERRUPTED = "interrupted"

ONBOARDING_CONTRACT = "contractual_parameters"
ONBOARDING_ALIGNMENT = "multidimensional_alignment"
ONBOARDING_TRANSPARENCY = "bidirectional_transparency"

RISK_NONE = "none"
RISK_MONITOR = "monitor"
RISK_ESCALATE = "escalate"
RISK_CRITICAL = "critical"


def now_iso() -> str:
    """Return a UTC timestamp using a stable JSON-friendly representation."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_id(prefix: str) -> str:
    """Create a short stable identifier with a semantic prefix."""
    return f"{prefix}_{uuid4().hex[:12]}"


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp or return None when the value is absent/invalid."""
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def iso_from_datetime(value: datetime) -> str:
    """Convert a datetime to an ISO string, assuming UTC when tzinfo is absent."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.replace(microsecond=0).isoformat()


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a float into a closed interval."""
    return max(low, min(high, value))


@dataclass(slots=True)
class SupervisionProfile:
    """Foundational layer: style, intensity, persona, goals, and background."""

    style: str = STYLE_GENTLE
    intensity: str = INTENSITY_MODERATE
    persona_description: str = (
        "A calm accountability coach who balances behavioral structure with "
        "non-judgmental support."
    )
    tone: str = "warm, specific, and practical"
    goals: list[str] = field(default_factory=list)
    exam_target_dates: dict[str, str] = field(default_factory=dict)
    academic_background: str = ""
    major: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    service_boundaries: list[str] = field(default_factory=list)
    trust_level: float = 0.5
    alignment_status: str = "new"
    reminder_strength: float = 1.0
    escalation_threshold: int = 2


@dataclass(slots=True)
class Task:
    """Operational layer: an academic unit that can be planned and tracked."""

    task_id: str = ""
    title: str = ""
    deadline: str | None = None
    priority: str = "medium"
    importance: int = 3
    estimated_minutes: int = 50
    remaining_minutes: int | None = None
    status: str = TASK_PENDING
    tags: list[str] = field(default_factory=list)
    knowledge_tags: list[str] = field(default_factory=list)
    difficulty: int = 3
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    completed_at: str | None = None
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduleBlock:
    """Operational layer: a Pomodoro/time-blocking unit tied to one task."""

    block_id: str = ""
    task_id: str = ""
    title: str = ""
    start_at: str = ""
    end_at: str = ""
    focus_minutes: int = 25
    break_minutes: int = 5
    status: str = TASK_PLANNED
    pomodoro_index: int = 1
    quadrant: str = "important_not_urgent"
    priority_score: float = 0.0
    cognitive_load: str = "medium"
    energy_alignment: str = "neutral"
    is_essential: bool = False
    reminder_offsets_minutes: list[int] = field(default_factory=lambda: [-10, 0])
    checkin_due_at: str | None = None
    completed_checkin_id: str | None = None
    strategy_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CheckInRecord:
    """A DaKa check-in that links subjective state to task execution."""

    checkin_id: str = ""
    task_id: str = ""
    block_id: str | None = None
    status: str = CHECKIN_COMPLETED
    created_at: str = field(default_factory=now_iso)
    completed_at: str | None = None
    progress_percent: int = 0
    quality_rating: int | None = None
    focus_minutes: int | None = None
    delay_reason: str = ""
    justified_delay: bool = False
    evidence_type: str = "text"
    evidence_ref: str | None = None
    note: str = ""
    emotion_tags: list[str] = field(default_factory=list)
    authenticity_confidence: float = 0.8
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EmotionState:
    """Emotional support state and global cross-agent control signal source."""

    valence: float = 0.0
    arousal: float = 0.5
    morale: float = 0.7
    stress: float = 0.3
    energy: float = 0.7
    self_efficacy: float = 0.6
    dominant_tags: list[str] = field(default_factory=list)
    tag_history: list[str] = field(default_factory=list)
    distress_detected: bool = False
    support_flags: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class KnowledgeSource:
    """Knowledge support source for subject-specific or methodological help."""

    source_id: str = ""
    title: str = ""
    source_type: str = "note"
    uri: str | None = None
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    created_at: str = field(default_factory=now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReminderEvent:
    """A reminder decision. The system does not send notifications itself."""

    reminder_id: str = ""
    user_id: str = ""
    task_id: str = ""
    block_id: str | None = None
    scheduled_for: str = ""
    reminder_type: str = REMINDER_SCHEDULED
    strength: str = "normal"
    message_hint: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrackingInsights:
    """Execution metrics used for adaptive accountability."""

    total_checkins: int = 0
    completed_checkins: int = 0
    skipped_checkins: int = 0
    partial_checkins: int = 0
    on_time_rate: float = 0.0
    average_progress: float = 0.0
    recent_skip_streak: int = 0
    under_completion_streak: int = 0
    needs_escalation: bool = False
    suggested_tracking_mode: str = "asynchronous"


@dataclass(slots=True)
class AdjustmentAction:
    """A structured plan or environment adjustment produced by guidance."""

    action_type: str = ""
    target_id: str | None = None
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommitmentSuggestion:
    """A lightweight pre-commitment contract suggestion."""

    commitment_id: str = ""
    task_id: str | None = None
    text: str = ""
    penalty: str = ""
    checkin_at: str | None = None
    status: str = COMMITMENT_PROPOSED
    created_at: str = field(default_factory=now_iso)
    due_at: str | None = None
    proof_required: str = "DaKa check-in"
    stake_type: str = "loss_aversion"
    stake_description: str = ""
    activation_condition: str = "user_accepts"
    fulfilled_at: str | None = None
    breached_at: str | None = None


@dataclass(slots=True)
class GuidancePlan:
    """Structured execution scaffolding generated from DaKa outcomes."""

    reflection_questions: list[str] = field(default_factory=list)
    reinforcement_messages: list[str] = field(default_factory=list)
    plan_adjustments: list[AdjustmentAction] = field(default_factory=list)
    commitments: list[CommitmentSuggestion] = field(default_factory=list)
    environment_suggestions: list[str] = field(default_factory=list)
    role: str = ROLE_COACH
    tone: str = "neutral"
    needs_replan: bool = False
    emotional_support_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvidenceAssessment:
    """DaKa consistency ritual based on OCR/activity metadata, not lie detection."""

    assessment_id: str = ""
    checkin_id: str = ""
    task_id: str = ""
    consistency_level: str = EVIDENCE_MISSING
    evidence_text: str = ""
    detected_activity: str = ""
    checks: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    ritual_prompt: str = ""
    confidence: float = 0.0
    created_at: str = field(default_factory=now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CoPresencePing:
    """A short companion ping during virtual co-presence."""

    ping_id: str = ""
    scheduled_at: str = ""
    message_hint: str = ""
    response_required: bool = False
    intervention_level: str = "light"
    observed_activity: str = ""
    flags: list[str] = field(default_factory=list)
    responded_at: str | None = None


@dataclass(slots=True)
class CoPresenceSession:
    """Pomodoro companion mode or authorized screen-activity supervision."""

    session_id: str = ""
    task_id: str = ""
    block_id: str | None = None
    mode: str = "pomodoro_companion"
    status: str = COPRESENCE_ACTIVE
    started_at: str = field(default_factory=now_iso)
    ends_at: str = ""
    ping_interval_minutes: int = 5
    authorized_screen_activity: bool = False
    pings: list[CoPresencePing] = field(default_factory=list)
    activity_log: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class EmotionalDialoguePlan:
    """Structured emotional dialogue branch, ICBT-informed but non-clinical."""

    strategy_tags: list[str] = field(default_factory=list)
    reflective_response: str = ""
    validation: str = ""
    responsibility_sharing: str = ""
    distortion_labels: list[str] = field(default_factory=list)
    reframing_prompt: str = ""
    next_micro_action: str = ""
    tone: str = "peer-like"
    created_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class ResourceItem:
    """Shareable social/learning resource for AI-to-human support bridging."""

    resource_id: str = ""
    title: str = ""
    resource_type: str = "tool"
    url: str | None = None
    tags: list[str] = field(default_factory=list)
    target_profile: list[str] = field(default_factory=list)
    summary: str = ""
    source: str = "default_pool"


@dataclass(slots=True)
class ProgressReview:
    """Periodic reflection report over check-ins, tasks, and emotion."""

    review_id: str = ""
    period: str = "weekly"
    period_start: str = ""
    period_end: str = ""
    total_checkins: int = 0
    completion_rate: float = 0.0
    average_progress: float = 0.0
    emotion_summary: dict[str, Any] = field(default_factory=dict)
    recurring_blockers: list[str] = field(default_factory=list)
    task_type_patterns: dict[str, int] = field(default_factory=dict)
    narrative: str = ""
    self_efficacy_message: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class OnboardingScript:
    """Trust-building onboarding output from ACSP Section 3.3.1."""

    stage: str = ONBOARDING_CONTRACT
    questions: list[str] = field(default_factory=list)
    self_disclosure: list[str] = field(default_factory=list)
    service_boundaries: list[str] = field(default_factory=list)
    next_action: str = ""
    completed: bool = False
    created_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class RoleDecision:
    """Regulatory-layer role selection and its downstream control knobs."""

    role: str = ROLE_COACH
    triggers: list[str] = field(default_factory=list)
    rationale: str = ""
    tone_template: str = "specific, practical, and accountable"
    reminder_strength_multiplier: float = 1.0
    guidance_strategy_weights: dict[str, float] = field(default_factory=dict)
    decided_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class RiskAssessment:
    """Escalation and soft-exit assessment from ACSP Section 3.3.6."""

    risk_id: str = ""
    level: str = RISK_NONE
    categories: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    pause_regular_intervention: bool = False
    assessed_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class UserState:
    """Aggregate root for all ACSP state.

    Foundational fields are represented by profile, goals, supervision, trust,
    and alignment status. Operational fields hold tasks, schedules, check-ins,
    emotion, and knowledge sources. Regulatory fields derive the active coach
    role and adaptation signals.
    """

    user_id: str
    profile: dict[str, Any] = field(default_factory=dict)
    supervision: SupervisionProfile = field(default_factory=SupervisionProfile)
    tasks: list[Task] = field(default_factory=list)
    schedule: list[ScheduleBlock] = field(default_factory=list)
    checkins: list[CheckInRecord] = field(default_factory=list)
    emotion: EmotionState = field(default_factory=EmotionState)
    knowledge_sources: list[KnowledgeSource] = field(default_factory=list)
    current_role: str = ROLE_COACH
    role_decision: RoleDecision = field(default_factory=RoleDecision)
    acsp_layer: str = "foundational"
    tracking_state: dict[str, Any] = field(default_factory=dict)
    commitments: list[CommitmentSuggestion] = field(default_factory=list)
    onboarding_scripts: list[OnboardingScript] = field(default_factory=list)
    risk_assessments: list[RiskAssessment] = field(default_factory=list)
    evidence_assessments: list[EvidenceAssessment] = field(default_factory=list)
    copresence_sessions: list[CoPresenceSession] = field(default_factory=list)
    emotional_dialogue_history: list[EmotionalDialoguePlan] = field(default_factory=list)
    resource_pool: list[ResourceItem] = field(default_factory=list)
    progress_reviews: list[ProgressReview] = field(default_factory=list)
    intervention_paused: bool = False
    version: int = 1
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


T = TypeVar("T")


def dataclass_from_dict(cls: type[T], data: dict[str, Any] | None) -> T:
    """Build a dataclass from JSON data, recursively handling nested lists."""
    data = data or {}
    kwargs: dict[str, Any] = {}
    type_hints = get_type_hints(cls)
    for item in fields(cls):
        if item.name not in data:
            continue
        value = data[item.name]
        annotation = type_hints.get(item.name, item.type)
        origin = get_origin(annotation)
        args = get_args(annotation)
        if hasattr(annotation, "__dataclass_fields__") and isinstance(value, dict):
            kwargs[item.name] = dataclass_from_dict(annotation, value)
        elif origin is list and args and hasattr(args[0], "__dataclass_fields__"):
            kwargs[item.name] = [
                dataclass_from_dict(args[0], entry)
                for entry in value
                if isinstance(entry, dict)
            ]
        else:
            kwargs[item.name] = value
    return cls(**kwargs)


def user_state_from_dict(data: dict[str, Any]) -> UserState:
    """Deserialize a UserState from JSON-compatible data."""
    state = dataclass_from_dict(UserState, data)
    if state.supervision is None:
        state.supervision = SupervisionProfile()
    if state.emotion is None:
        state.emotion = EmotionState()
    return state


def normalize_task(data: dict[str, Any]) -> Task:
    """Create or update a Task from loosely structured input."""
    task = dataclass_from_dict(Task, data)
    if not task.task_id:
        task.task_id = make_id("task")
    if task.remaining_minutes is None:
        task.remaining_minutes = max(0, int(task.estimated_minutes or 0))
    task.updated_at = now_iso()
    return task


def normalize_checkin(data: dict[str, Any]) -> CheckInRecord:
    """Create a check-in with defaults suitable for DaKa processing."""
    payload = dict(data or {})
    metadata = dict(payload.get("metadata") or {})
    for key in (
        "ocr_text",
        "screenshot_ocr_text",
        "evidence_text",
        "activity_app",
        "activity_title",
        "screen_activity",
        "window_title",
    ):
        if key in payload and key not in metadata:
            metadata[key] = payload[key]
    if metadata:
        payload["metadata"] = metadata
    if "emotion_tag" in payload and "emotion_tags" not in payload:
        tag = str(payload.get("emotion_tag", "")).strip()
        payload["emotion_tags"] = [tag] if tag else []
    checkin = dataclass_from_dict(CheckInRecord, payload)
    if not checkin.checkin_id:
        checkin.checkin_id = make_id("checkin")
    checkin.progress_percent = int(clamp(checkin.progress_percent, 0, 100))
    return checkin


def normalize_knowledge_source(data: dict[str, Any]) -> KnowledgeSource:
    """Create a KnowledgeSource with a stable id."""
    source = dataclass_from_dict(KnowledgeSource, data)
    if not source.source_id:
        source.source_id = make_id("source")
    return source
