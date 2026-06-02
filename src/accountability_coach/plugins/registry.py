"""Plugin registry for lifecycle-aware coach extensions."""

from __future__ import annotations

from accountability_coach.plugins.base import CoachPlugin, PluginContext


class PluginRegistry:
    """Collects plugins and coordinates lifecycle hooks."""

    def __init__(self) -> None:
        self._plugins: list[CoachPlugin] = []

    @property
    def plugins(self) -> tuple[CoachPlugin, ...]:
        return tuple(self._plugins)

    def register(self, plugin: CoachPlugin) -> None:
        if plugin not in self._plugins:
            self._plugins.append(plugin)

    async def initialize_all(self, context: PluginContext) -> None:
        for plugin in self._plugins:
            await plugin.initialize(context)

    async def terminate_all(self) -> None:
        for plugin in reversed(self._plugins):
            await plugin.terminate()
