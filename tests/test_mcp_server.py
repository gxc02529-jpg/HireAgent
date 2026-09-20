from datetime import datetime, timezone

from fastmcp import Client

from hire_agent.mcp_server import create_mcp_server
from hire_agent.store import demo_store


async def test_mcp_protocol_exposes_all_thirteen_tools_and_structured_schemas():
    server = create_mcp_server(
        demo_store(),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    async with Client(server) as client:
        catalog = await client.list_tools()

    assert len(catalog) == 13
    assert {tool.name for tool in catalog} == {
        "upsert_candidate", "get_candidate", "search_candidates", "summarize_resume",
        "upsert_job", "get_job", "search_jobs", "match_candidate", "rank_candidates",
        "list_interview_slots", "schedule_interview", "cancel_interview", "list_interviews",
    }
    schedule = next(tool for tool in catalog if tool.name == "schedule_interview")
    assert set(schedule.input_schema["required"]) == {
        "candidate_id", "job_id", "interviewer_id", "starts_at", "duration_minutes",
        "idempotency_key",
    }


async def test_mcp_calls_share_domain_validation_matching_and_idempotency():
    server = create_mcp_server(
        demo_store(),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    booking = {
        "candidate_id": "demo-c1",
        "job_id": "demo-j1",
        "interviewer_id": "demo-hr1",
        "starts_at": "2030-01-07T10:00:00Z",
        "duration_minutes": 60,
        "idempotency_key": "mcp-request-1",
    }

    async with Client(server) as client:
        matched = await client.call_tool(
            "match_candidate", {"candidate_id": "demo-c1", "job_id": "demo-j1"}
        )
        first = await client.call_tool("schedule_interview", booking)
        retry = await client.call_tool("schedule_interview", booking)
        listed = await client.call_tool("list_interviews", {"candidate_id": "demo-c1"})

    assert matched.data["score"] == 100
    assert matched.data["requires_human_review"] is True
    assert first.data["interview_id"] == retry.data["interview_id"]
    assert len(listed.data) == 1
    assert listed.data[0]["interview_id"] == first.data["interview_id"]
