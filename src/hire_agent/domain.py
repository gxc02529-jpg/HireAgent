"""Validated inputs shared by HTTP, agents and recruiting tools."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Candidate(Input):
    candidate_id: Identifier
    display_name: Text
    skills: list[Text] = Field(min_length=1, max_length=50)
    years_experience: float = Field(ge=0, le=60)
    location: Text
    summary: str = Field(default="", max_length=2000)

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: list[str]) -> list[str]:
        return sorted({item.casefold() for item in value})


class Job(Input):
    job_id: Identifier
    title: Text
    required_skills: list[Text] = Field(min_length=1, max_length=50)
    minimum_years: float = Field(ge=0, le=60)
    location: Text
    remote: bool = False

    @field_validator("required_skills")
    @classmethod
    def normalize_skills(cls, value: list[str]) -> list[str]:
        return sorted({item.casefold() for item in value})


class CandidateId(Input):
    candidate_id: Identifier


class JobId(Input):
    job_id: Identifier


class SearchCandidates(Input):
    skill: str = Field(default="", max_length=200)
    minimum_years: float = Field(default=0, ge=0, le=60)
    limit: int = Field(default=20, ge=1, le=100)


class SearchJobs(Input):
    query: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=100)


class MatchRequest(CandidateId, JobId):
    pass


class SlotRequest(Input):
    interviewer_id: Identifier
    day: date
    duration_minutes: int = Field(default=60, ge=15, le=120)


class ScheduleRequest(MatchRequest):
    interviewer_id: Identifier
    starts_at: AwareDatetime
    duration_minutes: int = Field(default=60, ge=15, le=120)
    idempotency_key: Identifier


class CancelRequest(Input):
    interview_id: Identifier


class ListInterviews(Input):
    candidate_id: Identifier | None = None
    interviewer_id: Identifier | None = None
    include_cancelled: bool = False


class Interview(Input):
    interview_id: Identifier
    candidate_id: Identifier
    job_id: Identifier
    interviewer_id: Identifier
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    status: Literal["scheduled", "cancelled"] = "scheduled"


class Intent(StrEnum):
    CANDIDATE_UPSERT = "candidate_upsert"
    CANDIDATE_SEARCH = "candidate_search"
    CANDIDATE_SUMMARY = "candidate_summary"
    JOB_UPSERT = "job_upsert"
    JOB_SEARCH = "job_search"
    CANDIDATE_MATCH = "candidate_match"
    INTERVIEW_SLOTS = "interview_slots"
    INTERVIEW_SCHEDULE = "interview_schedule"
    INTERVIEW_CANCEL = "interview_cancel"


class WorkflowRequest(Input):
    intent: Intent
    arguments: dict = Field(default_factory=dict)
