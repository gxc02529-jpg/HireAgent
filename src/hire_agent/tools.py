"""Thirteen recruiting operations with one validated, concurrency-safe entrypoint."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel

from .domain import (
    CancelRequest, Candidate, CandidateId, Interview, Job, JobId, ListInterviews,
    MatchRequest, ScheduleRequest, SearchCandidates, SearchJobs, SlotRequest,
)
from .store import MemoryStore


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable
    mutating: bool = False


def json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    return value


class RecruitingTools:
    def __init__(self, store: MemoryStore, clock: Callable[[], datetime] | None = None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        definitions = [
            ("upsert_candidate", "创建或更新结构化候选人档案", Candidate, self.upsert_candidate, True),
            ("get_candidate", "按 ID 获取候选人档案", CandidateId, self.get_candidate, False),
            ("search_candidates", "按技能和工作年限筛选候选人", SearchCandidates, self.search_candidates, False),
            ("summarize_resume", "从已录入的结构化档案生成事实摘要", CandidateId, self.summarize_resume, False),
            ("upsert_job", "创建或更新岗位要求", Job, self.upsert_job, True),
            ("get_job", "按 ID 获取岗位", JobId, self.get_job, False),
            ("search_jobs", "搜索岗位名称、技能和地点", SearchJobs, self.search_jobs, False),
            ("match_candidate", "计算可解释的技能、经验、地点匹配分", MatchRequest, self.match_candidate, False),
            ("rank_candidates", "对全部候选人与一个岗位进行匹配排序", JobId, self.rank_candidates, False),
            ("list_interview_slots", "列出面试官 UTC 工作日候选时段", SlotRequest, self.list_interview_slots, False),
            ("schedule_interview", "通过幂等键排期并检查双方时间冲突", ScheduleRequest, self.schedule_interview, True),
            ("cancel_interview", "幂等取消面试并释放占用时段", CancelRequest, self.cancel_interview, True),
            ("list_interviews", "按候选人或面试官筛选排期", ListInterviews, self.list_interviews, False),
        ]
        self.registry = {row[0]: Tool(*row) for row in definitions}

    def describe(self) -> list[dict]:
        return [dict(name=tool.name, description=tool.description,
                     mutating=tool.mutating, input_schema=tool.input_model.model_json_schema())
                for tool in self.registry.values()]

    def validate(self, name: str, arguments: dict) -> BaseModel:
        if name not in self.registry:
            raise DomainError("unknown_tool", f"Unknown tool: {name}", 404)
        return self.registry[name].input_model.model_validate(arguments)

    def invoke(self, name: str, arguments: dict) -> Any:
        request = self.validate(name, arguments)
        # Validation, writes and result snapshots share a consistent call boundary.
        with self.store.lock:
            return json_value(self.registry[name].handler(request))

    def _candidate(self, candidate_id: str) -> Candidate:
        if candidate_id not in self.store.candidates:
            raise DomainError("candidate_not_found", "Candidate does not exist", 404)
        return self.store.candidates[candidate_id]

    def _job(self, job_id: str) -> Job:
        if job_id not in self.store.jobs:
            raise DomainError("job_not_found", "Job does not exist", 404)
        return self.store.jobs[job_id]

    def upsert_candidate(self, request: Candidate) -> Candidate:
        self.store.candidates[request.candidate_id] = request.model_copy(deep=True)
        return request

    def get_candidate(self, request: CandidateId) -> Candidate:
        return self._candidate(request.candidate_id)

    def search_candidates(self, request: SearchCandidates) -> list[Candidate]:
        skill = request.skill.casefold()
        matches = [candidate for candidate in self.store.candidates.values()
                   if (not skill or skill in candidate.skills)
                   and candidate.years_experience >= request.minimum_years]
        return sorted(matches, key=lambda item: item.candidate_id)[:request.limit]

    def summarize_resume(self, request: CandidateId) -> dict:
        candidate = self._candidate(request.candidate_id)
        return {"candidate_id": candidate.candidate_id,
                "summary": f"{candidate.display_name}；{candidate.years_experience:g} 年经验；"
                           f"技能：{', '.join(candidate.skills)}；地点：{candidate.location}。",
                "source": "structured_profile", "generated_by": "template"}

    def upsert_job(self, request: Job) -> Job:
        self.store.jobs[request.job_id] = request.model_copy(deep=True)
        return request

    def get_job(self, request: JobId) -> Job:
        return self._job(request.job_id)

    def search_jobs(self, request: SearchJobs) -> list[Job]:
        query, location = request.query.casefold(), request.location.casefold()
        matches = [job for job in self.store.jobs.values()
                   if (not query or query in job.title.casefold()
                       or any(query in skill for skill in job.required_skills))
                   and (not location or location == job.location.casefold() or job.remote)]
        return sorted(matches, key=lambda item: item.job_id)[:request.limit]

    def match_candidate(self, request: MatchRequest) -> dict:
        candidate, job = self._candidate(request.candidate_id), self._job(request.job_id)
        matched = sorted(set(candidate.skills) & set(job.required_skills))
        missing = sorted(set(job.required_skills) - set(candidate.skills))
        skills_score = len(matched) / len(job.required_skills)
        experience_score = (min(candidate.years_experience / job.minimum_years, 1)
                            if job.minimum_years else 1)
        location_score = int(job.remote or candidate.location.casefold() == job.location.casefold())
        components = {"skills": round(70 * skills_score, 2),
                      "experience": round(20 * experience_score, 2),
                      "location": 10 * location_score}
        return {"candidate_id": candidate.candidate_id, "job_id": job.job_id,
                "score": round(sum(components.values()), 2), "components": components,
                "matched_skills": matched, "missing_skills": missing,
                "experience_gap_years": max(job.minimum_years - candidate.years_experience, 0),
                "location_compatible": bool(location_score), "requires_human_review": True}

    def rank_candidates(self, request: JobId) -> list[dict]:
        self._job(request.job_id)
        matches = [self.match_candidate(MatchRequest(candidate_id=key, job_id=request.job_id))
                   for key in self.store.candidates]
        return sorted(matches, key=lambda item: (-item["score"], item["candidate_id"]))

    def _conflicts(self, start: datetime, end: datetime, *, interviewer_id: str,
                   candidate_id: str | None = None) -> list[Interview]:
        return [item for item in self.store.interviews.values()
                if item.status == "scheduled" and start < item.ends_at and item.starts_at < end
                and (item.interviewer_id == interviewer_id
                     or (candidate_id is not None and item.candidate_id == candidate_id))]

    def list_interview_slots(self, request: SlotRequest) -> list[dict]:
        if request.day.weekday() >= 5:
            return []
        close = datetime.combine(request.day, time(17), timezone.utc)
        slots = []
        for hour in range(9, 17):
            start = datetime.combine(request.day, time(hour), timezone.utc)
            end = start + timedelta(minutes=request.duration_minutes)
            if start <= self.clock() or end > close:
                continue
            if not self._conflicts(start, end, interviewer_id=request.interviewer_id):
                slots.append({"starts_at": start.isoformat(), "ends_at": end.isoformat()})
        return slots

    def schedule_interview(self, request: ScheduleRequest) -> Interview:
        normalized = request.model_copy(update={"starts_at": request.starts_at.astimezone(timezone.utc)})
        payload = normalized.model_dump(mode="json", exclude={"idempotency_key"})
        fingerprint = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        previous = self.store.idempotency.get(request.idempotency_key)
        if previous:
            if previous[0] != fingerprint:
                raise DomainError("idempotency_conflict", "The key was already used for a different request")
            return self.store.interviews[previous[1]]
        self._candidate(request.candidate_id)
        self._job(request.job_id)
        start = normalized.starts_at
        if start <= self.clock():
            raise DomainError("past_interview", "Interview start must be in the future", 422)
        end = start + timedelta(minutes=request.duration_minutes)
        if self._conflicts(start, end, interviewer_id=request.interviewer_id,
                           candidate_id=request.candidate_id):
            raise DomainError("interview_conflict", "Candidate or interviewer already has an overlapping interview")
        interview = Interview(interview_id=f"iv-{uuid4().hex}", candidate_id=request.candidate_id,
                              job_id=request.job_id, interviewer_id=request.interviewer_id,
                              starts_at=start, ends_at=end)
        self.store.interviews[interview.interview_id] = interview
        self.store.idempotency[request.idempotency_key] = (fingerprint, interview.interview_id)
        return interview

    def cancel_interview(self, request: CancelRequest) -> Interview:
        if request.interview_id not in self.store.interviews:
            raise DomainError("interview_not_found", "Interview does not exist", 404)
        current = self.store.interviews[request.interview_id]
        cancelled = current.model_copy(update={"status": "cancelled"})
        self.store.interviews[request.interview_id] = cancelled
        return cancelled

    def list_interviews(self, request: ListInterviews) -> list[Interview]:
        return sorted([item for item in self.store.interviews.values()
                       if (request.include_cancelled or item.status == "scheduled")
                       and (request.candidate_id is None or item.candidate_id == request.candidate_id)
                       and (request.interviewer_id is None or item.interviewer_id == request.interviewer_id)],
                      key=lambda item: (item.starts_at, item.interview_id))
