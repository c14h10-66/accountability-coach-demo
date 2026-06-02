"""Social resource sharing and public learning-resource pool."""

from __future__ import annotations

from accountability_coach.core.models import ResourceItem, Task, UserState, make_id, now_iso


class ResourcePoolAgent:
    """Bridge standardized AI coaching with shareable human-like resources."""

    DEFAULT_RESOURCES = [
        ResourceItem(
            resource_id="res_purdue_owl",
            title="Purdue OWL writing resources",
            resource_type="writing_center",
            url="https://owl.purdue.edu/",
            tags=["writing", "citation", "essay", "thesis"],
            summary="Writing, citation, and academic style references.",
        ),
        ResourceItem(
            resource_id="res_zotero",
            title="Zotero reference manager",
            resource_type="tool",
            url="https://www.zotero.org/",
            tags=["paper", "literature", "citation", "thesis"],
            summary="Reference collection and citation workflow tool.",
        ),
        ResourceItem(
            resource_id="res_mit_ocw",
            title="MIT OpenCourseWare",
            resource_type="open_course",
            url="https://ocw.mit.edu/",
            tags=["course", "math", "engineering", "computer science"],
            summary="Open university course materials.",
        ),
        ResourceItem(
            resource_id="res_khan_academy",
            title="Khan Academy",
            resource_type="open_course",
            url="https://www.khanacademy.org/",
            tags=["math", "exam", "practice", "science"],
            summary="Practice-oriented learning materials for foundational subjects.",
        ),
    ]

    def register_resource(self, state: UserState, resource_data: dict) -> ResourceItem:
        resource = ResourceItem(**{k: v for k, v in resource_data.items() if k in ResourceItem.__dataclass_fields__})
        if not resource.resource_id:
            resource.resource_id = make_id("resource")
        resource.source = resource.source or "user_pool"
        state.resource_pool.append(resource)
        state.updated_at = now_iso()
        return resource

    def suggest_resources(
        self,
        state: UserState,
        task: Task | None = None,
        query: str = "",
        limit: int = 5,
    ) -> list[ResourceItem]:
        candidates = list(self.DEFAULT_RESOURCES) + list(state.resource_pool)
        target_terms = set(self._tokens(query))
        if task:
            target_terms.update(self._tokens(" ".join([task.title, *task.tags, *task.knowledge_tags])))
        profile_terms = self._tokens(" ".join(str(v) for v in state.profile.values()) + " " + state.supervision.major)
        target_terms.update(profile_terms)

        scored: list[tuple[int, ResourceItem]] = []
        for resource in candidates:
            haystack_terms = set(self._tokens(" ".join([resource.title, resource.summary, *resource.tags, *resource.target_profile])))
            score = len(target_terms & haystack_terms)
            if score:
                scored.append((score, resource))
        scored.sort(key=lambda item: (-item[0], item[1].title))
        return [resource for _, resource in scored[:limit]]

    def _tokens(self, text: str) -> list[str]:
        return [
            token.strip(".,;:!?()[]{}'\"").lower()
            for token in text.split()
            if len(token.strip(".,;:!?()[]{}'\"")) >= 3
        ]
