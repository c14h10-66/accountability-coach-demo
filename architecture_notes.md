# Architecture Notes

## Primary Paper Mapping

The implementation treats "More Than Supervision: Accountability-Driven
Coach Agent for Mitigating Academic Procrastination" as the behavioral
specification.

- Section 3.3.1 and 4.2 map to `SupervisionCustomization`, which stores
  style, intensity, persona, goals, background, boundaries, trust, and
  alignment status. `TrustOnboardingFlow` implements the three-stage
  onboarding flow: contractual parameters, multidimensional alignment, and
  bidirectional transparency.
- Section 3.3.2 and 4.3 map to `SchedulePlanningAgent`, which combines
  Eisenhower-style priority sorting, Pomodoro/time blocking, and low-morale
  schedule downgrades.
- Section 3.3.3 and 4.4 map to `TaskTrackingAgent`, which derives scheduled
  reminders from blocks, adds adaptive reminders from deviation/emotion/focus
  conditions, and processes DaKa check-ins. `DaKaEvidenceVerifier` adds
  multidimensional consistency checks over OCR/activity metadata as a
  non-punitive ritual rather than forensic lie detection.
- Section 3.3.3 and 4.5 map to `TaskGuidanceAgent`, which outputs structured
  reflection, reward, contextual restructuring, and pre-commitment actions.
  `CommitmentContractManager` makes these contracts executable by tracking
  active, fulfilled, and breached commitments from later DaKa records.
- Section 3.3.4 and 4.6 map to `KnowledgeSupportAgent`, which manages source
  metadata and tag-based source suggestions as a RAG-ready stub.
  `ResourcePoolAgent` adds a social-resource-sharing layer for public courses,
  tools, templates, and community-like links.
- Section 3.3.5 and 4.7 map to `EmotionalSupportAgent`, which updates valence,
  arousal, morale, stress, energy, and self-efficacy, then emits the global
  control signal consumed by planning/tracking/guidance.
  `EmotionalDialoguePlaybook` provides talk-level branches for empathic
  listening, companionate validation, shared responsibility, and CBT/ICBT-style
  cognitive reframing prompts.
- The synchronous-tracking mechanism in Section 3.3.3 maps to `CoPresenceAgent`,
  which implements Pomodoro companion pings and optional authorized activity
  samples for redirect interventions.
- Periodic performance-based reflection is supported by `ProgressReviewAgent`,
  which generates weekly/monthly summaries of completion, emotion, and repeated
  blockers.
- Section 3.4 maps to `UserState`: foundational state is stored in
  `SupervisionProfile`; operational state is tasks, schedule, check-ins,
  knowledge, and emotion; regulatory state is `current_role` and emotional
  adaptation. `RoleArbiter` makes regulatory-layer role decisions and emits
  role-conditioned tone, reminder, and guidance weights.
- Section 3.3.6 maps to `RiskDetector`, which detects clinical risk,
  goal-capacity mismatch, and relationship rupture. Critical risk pauses
  routine accountability and returns escalation actions rather than normal
  task pressure.

## Reference Patterns

Hermes Agent patterns to borrow:

- Keep the main agent loop platform-agnostic. Entry points such as CLI,
  gateway, cron, and editor integrations adapt input into the same core.
- Separate prompt or policy assembly, tool dispatch, persistence, and runtime
  concerns so the loop can stay observable and interruptible.
- Treat skills as procedural memory: small `SKILL.md` documents with optional
  supporting files, loaded only when relevant.
- Keep memory external to the model and persistent across sessions. Hermes uses
  profile-aware memory and SQLite-backed session storage; this project starts
  with a small storage interface and can grow to SQLite later.
- Model scheduled work and delegation as first-class agent tasks. This project
  reserves scheduling and sub-agent-style modules without implementing a full
  fleet yet.

AstrBot patterns to borrow:

- Use platform adapters to normalize platform-specific messages into one
  internal event shape.
- Route messages through an async event bus and a pipeline of stages instead
  of coupling adapters directly to business logic.
- Expose plugins as lifecycle-aware extension points. Plugins should register
  handlers or hooks without reaching into the core coordinator internals.
- Keep managers narrow: platform, plugin, knowledge, conversation, and pipeline
  concerns remain separate.

## Local Mapping

- `accountability_coach.core.CentralCoordinator` is the stable API surface for
  supervision configuration, schedule planning, check-ins, guidance, and state
  queries.
- `accountability_coach.modules` contains the six paper-inspired coach
  capabilities as engineering modules.
- `skills/` stores human-readable strategy SOPs and will be loaded by a
  `SkillRepository`.
- `accountability_coach.storage` defines persistence boundaries; no module
  should know whether data is stored in JSON, SQLite, or another backend.
- `accountability_coach.messaging`, `adapters`, and `plugins` are the future
  message-entry layer inspired by AstrBot's adapter plus plugin model.

## Dependency Boundary

Hermes Agent and AstrBot are reference material only. This package must not
import from `hermes-agent-main` or `AstrBot-master`, and those directories
should remain untouched by this implementation.
