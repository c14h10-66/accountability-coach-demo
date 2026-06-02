"""Message adapters for CLI, HTTP, and future chat platforms."""

from accountability_coach.adapters.base import MessageAdapter
from accountability_coach.adapters.cli import CLIAdapter
from accountability_coach.adapters.http import HTTPAdapter

__all__ = ["CLIAdapter", "HTTPAdapter", "MessageAdapter"]
