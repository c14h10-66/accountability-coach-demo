"""Compatibility wrapper for the core JSON user-state store."""

from accountability_coach.core.json_store import JsonUserStateStore

JsonStorageBackend = JsonUserStateStore

__all__ = ["JsonStorageBackend", "JsonUserStateStore"]
