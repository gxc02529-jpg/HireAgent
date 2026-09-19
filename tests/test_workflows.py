import json

from fastapi.testclient import TestClient
import pytest

from hire_agent.agents import Orchestrator, ROUTES
from hire_agent.api import create_app
from hire_agent.domain import Intent, WorkflowRequest
from hire_agent.store import demo_store
from hire_agent.tools import DomainError


def test_all_nine_routes_cover_their_agents(tools):
    orchestrator = Orchestrator(tools)
    assert set(ROUTES) == set(Intent)
    assert len(ROUTES) == 9
    for agent, tool in ROUTES.values():
        assert tool in orchestrator.agents[agent].allowed_tools
    with pytest.raises(DomainError) as caught:
        orchestrator.agents["ResumeAgent"].execute("schedule_interview", {})
    assert caught.value.code == "agent_scope_violation"


def test_matching_workflow_runs_context_steps_and_returns_evidence(tools):
    result = Orchestrator(tools).run(WorkflowRequest(intent="candidate_match", arguments={
        "candidate_id": "demo-c1", "job_id": "demo-j1"}))
    assert result["result"]["score"] == 100
    assert [(item["agent"], item["tool"]) for item in result["trace"]] == [
        ("ResumeAgent", "get_candidate"), ("JobAgent", "get_job"), ("JobAgent", "match_candidate")]


@pytest.fixture
def client():
    with TestClient(create_app(demo_store())) as client:
        yield client


def test_http_catalog_and_tool_errors(client):
    assert client.get("/health").json()["storage"] == "in_memory"
    assert len(client.get("/tools").json()) == 13
    assert len(client.get("/agents").json()) == 3
    response = client.post("/tools/search_candidates", json={"skill": "RAG"})
    assert response.status_code == 200
    assert response.json()["result"][0]["candidate_id"] == "demo-c1"
    assert client.post("/tools/missing", json={}).status_code == 404
    invalid = client.post("/tools/search_candidates", json={"limit": -1})
    assert invalid.status_code == 422
    assert invalid.json()["error"] == "invalid_arguments"


def test_http_mutation_and_conflict_status(client, booking):
    # Fixed far-future timestamp keeps this API test independent of the current year.
    booking = {**booking, "starts_at": "2099-01-07T10:00:00Z"}
    first = client.post("/tools/schedule_interview", json=booking)
    assert first.status_code == 200
    retry = client.post("/tools/schedule_interview", json=booking)
    assert retry.json() == first.json()
    conflict = client.post("/tools/schedule_interview", json={**booking, "idempotency_key": "other"})
    assert conflict.status_code == 409


def parse_events(response):
    result = []
    for block in response.text.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        result.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return result


def test_sse_success_has_ordered_tool_events_and_terminal_result(client):
    response = client.post("/workflows/stream", json={"intent": "candidate_match", "arguments": {
        "candidate_id": "demo-c1", "job_id": "demo-j1"}})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_events(response)
    assert [name for name, _ in events] == ["routed", "tool_started", "tool_completed",
        "tool_started", "tool_completed", "tool_started", "tool_completed", "completed"]
    assert events[-1][1]["result"]["score"] == 100
    normal = client.post("/workflows", json={"intent": "candidate_summary", "arguments": {
        "candidate_id": "demo-c1"}})
    assert normal.json()["agent"] == "ResumeAgent"


def test_sse_validates_before_headers_and_reports_runtime_error(client):
    invalid = client.post("/workflows/stream", json={"intent": "candidate_match", "arguments": {}})
    assert invalid.status_code == 422
    unknown = client.post("/workflows/stream", json={"intent": "arbitrary", "arguments": {}})
    assert unknown.status_code == 422
    missing = client.post("/workflows/stream", json={"intent": "candidate_match", "arguments": {
        "candidate_id": "missing", "job_id": "demo-j1"}})
    assert missing.status_code == 200
    events = parse_events(missing)
    assert events[-1][0] == "error"
    assert events[-1][1]["error"] == "candidate_not_found"
    assert "completed" not in [event for event, _ in events]
