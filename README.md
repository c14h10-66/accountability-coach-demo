# Accountability Coach Agent

A lightweight conversational coach prototype for academic procrastination support.

This repository is a portfolio/demo version of my thesis work. It explores how human accountability coaching practices can be translated into a stateful dialogue system with onboarding, task planning, check-ins, emotional support, adaptive guidance, and risk-aware boundaries.

**Demo page:** open `docs/index.html` locally, or publish the `docs/` folder with GitHub Pages.  
**Thesis research overview:** `docs/thesis.html`  
**Core demo:** `examples/full_loop_demo.py`  
**Status:** research prototype, not a clinical or production support tool.

## Why This Demo Matters

This demo presents a complete HCI research workflow:

- qualitative fieldwork with accountability coaches and clients
- pattern distillation into the Accountability Coaching Service Pattern
- implementation of a modular LLM-based conversational coach
- adaptive dialogue state, memory, task planning, and emotional support
- mixed-method evaluation of the prototype in a 4-week study
- safety and boundary handling for sensitive academic support contexts

## What The Prototype Includes

- `CentralCoordinator` as the platform-independent coach core.
- Supervision customization for goals, coaching style, intensity, background, and boundaries.
- Three-stage onboarding: contractual parameters, multidimensional alignment, and bidirectional transparency.
- Task planning with priority sorting, Pomodoro/time-blocking, and low-morale schedule adaptation.
- Check-ins with progress, emotion tags, adaptive replanning, guidance, and commitments.
- Emotional support branches such as empathic listening, shared responsibility language, and reframing prompts.
- Risk detection that pauses routine accountability when escalation or boundaries matter.
- CLI, HTTP, chat, and optional WeChat/OpenClaw adapter entry points.

## Quick Start

Requires Python 3.11 or newer. If your default `python3` points to an older macOS system Python, use `python3.11`, `python3.12`, or a newer interpreter explicitly.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python examples/full_loop_demo.py
```

You can also run deterministic CLI commands:

```bash
PYTHONPATH=src python -m accountability_coach.entrypoints.cli onboarding demo_user
PYTHONPATH=src python -m accountability_coach.entrypoints.cli configure demo_user --style gentle --intensity moderate --goal "finish the literature review"
PYTHONPATH=src python -m accountability_coach.entrypoints.cli add-task demo_user "Draft literature review outline" --task-id lit_review --priority urgent --importance 5 --minutes 90
PYTHONPATH=src python -m accountability_coach.entrypoints.cli plan demo_user
```

## Demo Scenario

The packaged demo scenario follows a graduate student who needs to draft a literature review outline but is tired and uncertain about how to structure sources.

The coach:

1. stores the student's supervision preferences and academic context
2. creates a high-priority writing task
3. plans a focused work block
4. receives a partial check-in
5. adapts schedule intensity based on the emotional signal
6. returns a structured guidance plan and next commitment

## Repository Map

```text
src/accountability_coach/     Core agent, dialogue policy, modules, adapters
examples/full_loop_demo.py    Minimal end-to-end scenario
tests/test_acsp_core.py       Unit tests for core behavior and adapters
docs/index.html               Static interactive demo page for quick viewing
docs/thesis.html              Structured visual overview of the thesis work
docs/architecture_notes.md    Architecture mapping and design rationale
docs/research_positioning.md  Concise thesis presentation framing
skills/                       Human-readable coaching strategy SOPs
```

## Positioning For Thesis Discussion

If shared with a professor or reviewer, this project should be introduced as:

> My thesis prototype and study on accountability-driven conversational agents for academic procrastination intervention. It demonstrates the full path from fieldwork and pattern distillation to system implementation and mixed-method evaluation.

See `docs/research_positioning.md` for a concise framing note.

## Safety Note

The prototype is for research and design demonstration only. It does not provide professional counseling, diagnosis, or crisis intervention services. Sensitive data, real user memory, API keys, and platform tokens should never be committed to the repository.
