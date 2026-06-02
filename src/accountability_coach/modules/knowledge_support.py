"""Knowledge Support Agent: cognitive scaffolding without a RAG dependency."""

from __future__ import annotations

from accountability_coach.core.models import (
    KnowledgeSource,
    Task,
    UserState,
    normalize_knowledge_source,
    now_iso,
)


class KnowledgeSupportAgent:
    """Manage sources and suggest relevant support for capability bottlenecks."""

    def register_source(
        self,
        user_state: UserState,
        source_data: dict,
    ) -> KnowledgeSource:
        source = normalize_knowledge_source(source_data)
        existing = self._find_source(user_state, source.source_id)
        if existing:
            existing.title = source.title or existing.title
            existing.source_type = source.source_type or existing.source_type
            existing.uri = source.uri or existing.uri
            existing.tags = source.tags or existing.tags
            existing.summary = source.summary or existing.summary
            existing.metadata.update(source.metadata)
            source = existing
        else:
            user_state.knowledge_sources.append(source)
        user_state.updated_at = now_iso()
        return source

    def list_sources(self, user_state: UserState) -> list[KnowledgeSource]:
        return list(user_state.knowledge_sources)

    def suggest_relevant_sources(
        self,
        user_state: UserState,
        task: Task,
        query: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeSource]:
        """Stub retrieval heuristic: match tags and title/query tokens."""
        task_terms = set(self._tokens(task.title))
        tag_terms = {tag.lower() for tag in task.tags + task.knowledge_tags}
        query_terms = set(self._tokens(query or ""))
        scored: list[tuple[int, KnowledgeSource]] = []
        for source in user_state.knowledge_sources:
            source_tags = {tag.lower() for tag in source.tags}
            source_terms = set(self._tokens(source.title + " " + source.summary))
            score = 0
            score += 3 * len(source_tags & tag_terms)
            score += 2 * len(source_terms & task_terms)
            score += 2 * len(source_terms & query_terms)
            score += len(source_tags & query_terms)
            if score > 0:
                scored.append((score, source))
        scored.sort(key=lambda item: (-item[0], item[1].title))
        return [source for _, source in scored[:limit]]

    def methodological_guidance(self, task: Task) -> list[str]:
        """Return execution methods that lower the task's cognitive threshold."""
        suggestions = [
            "Define the next observable output before the focus block starts.",
            "Use one Pomodoro cycle, then submit a DaKa with the concrete artifact.",
        ]
        if task.difficulty >= 4:
            suggestions.append(
                "Before writing or solving, spend five minutes listing unknown concepts."
            )
        if "exam" in {tag.lower() for tag in task.tags}:
            suggestions.append(
                "Prefer active recall and error-log review over rereading."
            )
        if "writing" in {tag.lower() for tag in task.tags}:
            suggestions.append(
                "Create a rough outline first; polish only after the argument exists."
            )
        return suggestions

    def _find_source(
        self,
        user_state: UserState,
        source_id: str,
    ) -> KnowledgeSource | None:
        for source in user_state.knowledge_sources:
            if source.source_id == source_id:
                return source
        return None

    def _tokens(self, text: str) -> list[str]:
        return [
            token.strip(".,;:!?()[]{}'\"").lower()
            for token in text.split()
            if len(token.strip(".,;:!?()[]{}'\"")) >= 3
        ]


KnowledgeSupport = KnowledgeSupportAgent
