"""Run after `python -m pip install -e .`; no API server or model credentials needed."""

from datetime import datetime, timedelta, timezone
import json

from hire_agent.agents import Orchestrator
from hire_agent.domain import WorkflowRequest
from hire_agent.store import demo_store
from hire_agent.tools import RecruitingTools


def main():
    tools = RecruitingTools(demo_store())
    orchestrator = Orchestrator(tools)
    matched = orchestrator.run(WorkflowRequest(intent="candidate_match", arguments={
        "candidate_id": "demo-c1", "job_id": "demo-j1"}))
    scheduled = orchestrator.run(WorkflowRequest(intent="interview_schedule", arguments={
        "candidate_id": "demo-c1", "job_id": "demo-j1", "interviewer_id": "demo-hr1",
        "starts_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "duration_minutes": 60, "idempotency_key": "example-request-1"}))
    print(json.dumps({"match": matched, "interview": scheduled}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
