"""LLM-facing dialogue layer for the accountability coach."""

from accountability_coach.dialogue.access_control import AccessControl, AccessDecision
from accountability_coach.dialogue.agent import DialogueAgent
from accountability_coach.dialogue.llm import (
    LLMClient,
    LLMError,
    NullLLMClient,
    OpenAICompatibleLLMClient,
    build_llm_from_env,
)
from accountability_coach.dialogue.input_signals import EmojiEmotionInterpreter, InputSignal
from accountability_coach.dialogue.memory import DialogueMemory
from accountability_coach.dialogue.models import DialogueTurn
from accountability_coach.dialogue.policy import DialoguePolicy, DialoguePolicyContext, RuntimeContext
from accountability_coach.dialogue.stickers import Sticker, StickerLibrary
from accountability_coach.dialogue.user_preferences import PreferenceCommandResult, UserPreferenceManager

__all__ = [
    "AccessControl",
    "AccessDecision",
    "DialogueAgent",
    "DialogueMemory",
    "DialoguePolicy",
    "DialoguePolicyContext",
    "DialogueTurn",
    "EmojiEmotionInterpreter",
    "InputSignal",
    "LLMClient",
    "LLMError",
    "NullLLMClient",
    "OpenAICompatibleLLMClient",
    "RuntimeContext",
    "Sticker",
    "StickerLibrary",
    "PreferenceCommandResult",
    "UserPreferenceManager",
    "build_llm_from_env",
]
