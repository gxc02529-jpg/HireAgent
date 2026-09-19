from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from hire_agent.tools import DomainError


def test_thirteen_tool_contracts(tools):
    manifest = tools.describe()
    assert len(manifest) == len({tool["name"] for tool in manifest}) == 13
    assert all(tool["input_schema"]["additionalProperties"] is False for tool in manifest)
    assert {tool["name"] for tool in manifest if tool["mutating"]} == {
        "upsert_candidate", "upsert_job", "schedule_interview", "cancel_interview"}


def test_candidate_job_search_and_fact_summary(tools):
    candidate = {"candidate_id": "test-c", "display_name": "测试数据",
                 "skills": [" Python ", "python", "SQL"], "years_experience": 4,
                 "location": "深圳", "summary": "仅用于自动化测试"}
    saved = tools.invoke("upsert_candidate", candidate)
    assert saved["skills"] == ["python", "sql"]
    assert tools.invoke("get_candidate", {"candidate_id": "test-c"}) == saved
    matches = tools.invoke("search_candidates", {"skill": "SQL", "minimum_years": 3})
    assert [item["candidate_id"] for item in matches] == ["test-c"]
    summary = tools.invoke("summarize_resume", {"candidate_id": "test-c"})
    assert "4 年经验" in summary["summary"]
    assert summary["generated_by"] == "template"
    job = {"job_id": "test-j", "title": "Data engineer", "required_skills": ["SQL"],
           "minimum_years": 0, "location": "深圳", "remote": True}
    assert tools.invoke("upsert_job", job)["required_skills"] == ["sql"]
    assert tools.invoke("get_job", {"job_id": "test-j"})["title"] == "Data engineer"
    assert [item["job_id"] for item in tools.invoke("search_jobs", {
        "query": "sql", "location": "其他城市"})] == ["test-j"]


def test_match_exposes_weighted_evidence_and_stable_ranking(tools):
    perfect = tools.invoke("match_candidate", {"candidate_id": "demo-c1", "job_id": "demo-j1"})
    partial = tools.invoke("match_candidate", {"candidate_id": "demo-c2", "job_id": "demo-j1"})
    assert perfect["score"] == 100
    assert perfect["missing_skills"] == []
    assert partial["score"] == 33.33
    assert partial["components"] == {"skills": 23.33, "experience": 10, "location": 0}
    assert partial["missing_skills"] == ["fastapi", "rag"]
    assert partial["experience_gap_years"] == 1
    assert partial["requires_human_review"] is True
    assert [item["candidate_id"] for item in tools.invoke("rank_candidates", {"job_id": "demo-j1"})] == [
        "demo-c1", "demo-c2"]


def test_empty_skills_and_unknown_fields_are_rejected(tools):
    with pytest.raises(ValidationError):
        tools.invoke("upsert_candidate", {"candidate_id": "bad", "display_name": "bad", "skills": [],
                                         "years_experience": 0, "location": "上海"})
    with pytest.raises(ValidationError):
        tools.invoke("search_candidates", {"limit": 0})
    with pytest.raises(ValidationError):
        tools.invoke("search_candidates", {"sql": "unexpected"})
    with pytest.raises(DomainError, match="does not exist"):
        tools.invoke("get_candidate", {"candidate_id": "missing"})
    with pytest.raises(DomainError, match="Unknown tool"):
        tools.invoke("missing", {})


def test_idempotent_schedule_normalizes_timezones_and_rejects_key_reuse(tools, booking):
    first = tools.invoke("schedule_interview", booking)
    retried = tools.invoke("schedule_interview", {**booking, "starts_at": "2030-01-07T18:00:00+08:00"})
    assert first == retried
    assert len(tools.store.interviews) == 1
    with pytest.raises(DomainError) as caught:
        tools.invoke("schedule_interview", {**booking, "duration_minutes": 30})
    assert caught.value.code == "idempotency_conflict"


@pytest.mark.parametrize("change", [
    {"candidate_id": "demo-c2"},
    {"interviewer_id": "demo-hr2"},
])
def test_either_participant_overlap_rejected(tools, booking, change):
    tools.invoke("schedule_interview", booking)
    with pytest.raises(DomainError) as caught:
        tools.invoke("schedule_interview", {**booking, **change, "idempotency_key": "request-2",
                                           "starts_at": "2030-01-07T10:30:00Z"})
    assert caught.value.code == "interview_conflict"


def test_touching_intervals_allowed_and_cancel_releases_slot(tools, booking):
    first = tools.invoke("schedule_interview", booking)
    next_booking = {**booking, "starts_at": "2030-01-07T11:00:00Z", "idempotency_key": "next"}
    tools.invoke("schedule_interview", next_booking)
    cancelled = tools.invoke("cancel_interview", {"interview_id": first["interview_id"]})
    assert cancelled == tools.invoke("cancel_interview", {"interview_id": first["interview_id"]})
    assert tools.invoke("schedule_interview", booking)["status"] == "cancelled"
    replacement = tools.invoke("schedule_interview", {**booking, "idempotency_key": "replacement"})
    assert replacement["interview_id"] != first["interview_id"]
    assert len(tools.invoke("list_interviews", {})) == 2
    assert len(tools.invoke("list_interviews", {"include_cancelled": True})) == 3
    assert tools.invoke("list_interviews", {"candidate_id": "demo-c2"}) == []


def test_suggested_slots_exclude_conflicts_weekends_and_overrun(tools, booking):
    tools.invoke("schedule_interview", booking)
    slots = tools.invoke("list_interview_slots", {"interviewer_id": "demo-hr1", "day": "2030-01-07"})
    assert len(slots) == 7
    assert not any("T10:00" in item["starts_at"] for item in slots)
    assert tools.invoke("list_interview_slots", {"interviewer_id": "demo-hr1", "day": "2030-01-05"}) == []
    longer = tools.invoke("list_interview_slots", {
        "interviewer_id": "other", "day": "2030-01-07", "duration_minutes": 120})
    assert len(longer) == 7
    assert longer[-1]["ends_at"] == "2030-01-07T17:00:00+00:00"


def test_past_time_naive_time_missing_references_and_unknown_cancel(tools, booking):
    with pytest.raises(ValidationError):
        tools.invoke("schedule_interview", {**booking, "starts_at": "2030-01-07T10:00:00"})
    with pytest.raises(DomainError) as caught:
        tools.invoke("schedule_interview", {**booking, "starts_at": "2029-01-07T10:00:00Z"})
    assert caught.value.code == "past_interview"
    with pytest.raises(DomainError):
        tools.invoke("schedule_interview", {**booking, "job_id": "missing"})
    with pytest.raises(DomainError):
        tools.invoke("cancel_interview", {"interview_id": "missing"})


def test_concurrent_same_key_has_single_effect(tools, booking):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: tools.invoke("schedule_interview", booking), range(16)))
    assert len({item["interview_id"] for item in results}) == 1
    assert len(tools.store.interviews) == 1


def test_concurrent_distinct_keys_cannot_double_book(tools, booking):
    def schedule(number):
        try:
            return tools.invoke("schedule_interview", {**booking, "idempotency_key": f"request-{number}"})
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(schedule, range(16)))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert results.count("interview_conflict") == 15
