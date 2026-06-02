"""Paper-inspired coach capability modules."""

from accountability_coach.modules.commitments import CommitmentContractManager
from accountability_coach.modules.copresence import CoPresenceAgent
from accountability_coach.modules.emotional_dialogue import EmotionalDialoguePlaybook
from accountability_coach.modules.emotional_support import (
    EmotionalSupport,
    EmotionalSupportAgent,
)
from accountability_coach.modules.evidence_verification import DaKaEvidenceVerifier
from accountability_coach.modules.knowledge_support import (
    KnowledgeSupport,
    KnowledgeSupportAgent,
)
from accountability_coach.modules.onboarding import TrustOnboardingFlow
from accountability_coach.modules.progress_review import ProgressReviewAgent
from accountability_coach.modules.proactive import ProactiveConversationAgent, ProactivePrompt
from accountability_coach.modules.resource_pool import ResourcePoolAgent
from accountability_coach.modules.reminder_scheduler import ReminderRequest, ReminderScheduler
from accountability_coach.modules.risk_detection import RiskDetector
from accountability_coach.modules.role_arbiter import RoleArbiter
from accountability_coach.modules.schedule_planning import (
    SchedulePlanning,
    SchedulePlanningAgent,
)
from accountability_coach.modules.supervision_customization import (
    SupervisionCustomization,
)
from accountability_coach.modules.task_guidance import TaskGuidance, TaskGuidanceAgent
from accountability_coach.modules.task_tracking import TaskTracking, TaskTrackingAgent

__all__ = [
    "CoPresenceAgent",
    "CommitmentContractManager",
    "DaKaEvidenceVerifier",
    "EmotionalDialoguePlaybook",
    "EmotionalSupport",
    "EmotionalSupportAgent",
    "KnowledgeSupport",
    "KnowledgeSupportAgent",
    "ProgressReviewAgent",
    "ProactiveConversationAgent",
    "ProactivePrompt",
    "ReminderRequest",
    "ReminderScheduler",
    "RiskDetector",
    "RoleArbiter",
    "ResourcePoolAgent",
    "SchedulePlanning",
    "SchedulePlanningAgent",
    "SupervisionCustomization",
    "TaskGuidance",
    "TaskGuidanceAgent",
    "TaskTracking",
    "TaskTrackingAgent",
    "TrustOnboardingFlow",
]
