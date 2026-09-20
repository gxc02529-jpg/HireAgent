"""Deterministic step-level and end-to-end evaluation for the public demo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .agents import Orchestrator
from .domain import WorkflowRequest
from .store import MemoryStore, demo_store
from .tools import DomainError, RecruitingTools


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    request: WorkflowRequest
    expected_changed_fields: frozenset[str]
    expected_result: dict[str, Any]


DEFAULT_CASES = (
    EvaluationCase(
        name="read_only_candidate_match",
        request=WorkflowRequest(
            intent="candidate_match",
            arguments={"candidate_id": "demo-c1", "job_id": "demo-j1"},
        ),
        expected_changed_fields=frozenset(),
        expected_result={"score": 100},
    ),
    EvaluationCase(
        name="update_candidate_location_only",
        request=WorkflowRequest(
            intent="candidate_upsert",
            arguments={
                "candidate_id": "demo-c2",
                "display_name": "演示候选人乙",
                "skills": ["Python", "SQL"],
                "years_experience": 1,
                "location": "苏州",
            },
        ),
        expected_changed_fields=frozenset({"candidates.demo-c2.location"}),
        expected_result={"candidate_id": "demo-c2", "location": "苏州"},
    ),
    EvaluationCase(
        name="update_job_title_only",
        request=WorkflowRequest(
            intent="job_upsert",
            arguments={
                "job_id": "demo-j1",
                "title": "大模型应用开发工程师",
                "required_skills": ["python", "fastapi", "rag"],
                "minimum_years": 2,
                "location": "上海",
                "remote": False,
            },
        ),
        expected_changed_fields=frozenset({"jobs.demo-j1.title"}),
        expected_result={"job_id": "demo-j1", "title": "大模型应用开发工程师"},
    ),
)


def snapshot_store(store: MemoryStore) -> dict[str, Any]:
    """Return a stable representation of fields that a workflow may mutate."""

    return {
        "candidates": {
            key: value.model_dump(mode="json") for key, value in sorted(store.candidates.items())
        },
        "jobs": {key: value.model_dump(mode="json") for key, value in sorted(store.jobs.items())},
        "interviews": {
            key: value.model_dump(mode="json") for key, value in sorted(store.interviews.items())
        },
        "idempotency": dict(sorted(store.idempotency.items())),
    }


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> frozenset[str]:
    before_flat = _flatten(before)
    after_flat = _flatten(after)
    keys = before_flat.keys() | after_flat.keys()
    return frozenset(key for key in keys if before_flat.get(key) != after_flat.get(key))


def evaluate_cases(cases: tuple[EvaluationCase, ...] = DEFAULT_CASES) -> dict[str, Any]:
    """Measure tool completion and state-transition correctness on synthetic fixtures."""

    case_results: list[dict[str, Any]] = []
    tools_started = 0
    tools_completed = 0

    for case in cases:
        store = demo_store()
        tools = RecruitingTools(
            store,
            clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        orchestrator = Orchestrator(tools)
        before = snapshot_store(store)
        terminal: dict[str, Any] | None = None
        error: str | None = None

        try:
            for event in orchestrator.events(case.request):
                if event["event"] == "tool_started":
                    tools_started += 1
                elif event["event"] == "tool_completed":
                    tools_completed += 1
                elif event["event"] == "completed":
                    terminal = event["data"]
        except DomainError as exc:
            error = exc.code

        actual_changed = changed_fields(before, snapshot_store(store))
        result = terminal["result"] if terminal else {}
        state_ok = actual_changed == case.expected_changed_fields
        result_ok = all(result.get(key) == value for key, value in case.expected_result.items())
        task_success = terminal is not None and error is None and state_ok and result_ok
        case_results.append(
            {
                "name": case.name,
                "success": task_success,
                "expected_changed_fields": sorted(case.expected_changed_fields),
                "actual_changed_fields": sorted(actual_changed),
                "unexpected_changed_fields": sorted(actual_changed - case.expected_changed_fields),
                "missing_changed_fields": sorted(case.expected_changed_fields - actual_changed),
                "error": error,
            }
        )

    successful_tasks = sum(item["success"] for item in case_results)
    return {
        "evaluation_scope": "synthetic_regression_fixtures",
        "step_level": {
            "tools_started": tools_started,
            "tools_completed": tools_completed,
            "tool_call_success_rate": tools_completed / tools_started if tools_started else 0.0,
        },
        "end_to_end": {
            "tasks_total": len(case_results),
            "tasks_successful": successful_tasks,
            "task_success_rate": successful_tasks / len(case_results) if case_results else 0.0,
        },
        "cases": case_results,
    }


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(item, child))
        return result
    return {prefix: value}
