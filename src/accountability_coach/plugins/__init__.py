"""Plugin extension points."""

from accountability_coach.plugins.base import CoachPlugin, PluginContext
from accountability_coach.plugins.registry import PluginRegistry

__all__ = ["CoachPlugin", "PluginContext", "PluginRegistry"]
