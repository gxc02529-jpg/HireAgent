"""Explicit intent routing and scoped local specialist agents (not an A2A server)."""

from dataclasses import dataclass
from typing import Iterator
from uuid import uuid4

from .domain import Intent, WorkflowRequest
from .tools import DomainError, RecruitingTools


ROUTES = {
    Intent.CANDIDATE_UPSERT: ("ResumeAgent", "upsert_candidate"),
    Intent.CANDIDATE_SEARCH: ("ResumeAgent", "search_candidates"),
    Intent.CANDIDATE_SUMMARY: ("ResumeAgent", "summarize_resume"),
    Intent.JOB_UPSERT: ("JobAgent", "upsert_job"),
    Intent.JOB_SEARCH: ("JobAgent", "search_jobs"),
    Intent.CANDIDATE_MATCH: ("JobAgent", "match_candidate"),
    Intent.INTERVIEW_SLOTS: ("InterviewAgent", "list_interview_slots"),
    Intent.INTERVIEW_SCHEDULE: ("InterviewAgent", "schedule_interview"),
    Intent.INTERVIEW_CANCEL: ("InterviewAgent", "cancel_interview"),
}


@dataclass(frozen=True)
class Step:
    agent: str
    tool: str
    arguments: dict


class SpecialistAgent:
    def __init__(self, name: str, allowed_tools: set[str], tools: RecruitingTools):
        self.name, self.allowed_tools, self.tools = name, frozenset(allowed_tools), tools

    def execute(self, tool: str, arguments: dict):
        if tool not in self.allowed_tools:
            raise DomainError("agent_scope_violation", f"{self.name} cannot invoke {tool}", 403)
        return self.tools.invoke(tool, arguments)


class Orchestrator:
    def __init__(self, tools: RecruitingTools):
        self.tools = tools
        self.agents = {
            "ResumeAgent": SpecialistAgent("ResumeAgent", {
                "upsert_candidate", "get_candidate", "search_candidates", "summarize_resume"}, tools),
            "JobAgent": SpecialistAgent("JobAgent", {
                "upsert_job", "get_job", "search_jobs", "match_candidate", "rank_candidates"}, tools),
            "InterviewAgent": SpecialistAgent("InterviewAgent", {
                "list_interview_slots", "schedule_interview", "cancel_interview", "list_interviews"}, tools),
        }

    def plan(self, request: WorkflowRequest) -> list[Step]:
        agent, tool = ROUTES[request.intent]
        validated = self.tools.validate(tool, request.arguments).model_dump(mode="json")
        steps = []
        if request.intent == Intent.CANDIDATE_MATCH:
            steps.extend([
                Step("ResumeAgent", "get_candidate", {"candidate_id": validated["candidate_id"]}),
                Step("JobAgent", "get_job", {"job_id": validated["job_id"]}),
            ])
        steps.append(Step(agent, tool, validated))
        return steps

    def events(self, request: WorkflowRequest, steps: list[Step] | None = None) -> Iterator[dict]:
        steps = steps if steps is not None else self.plan(request)
        workflow_id = f"wf-{uuid4().hex}"
        trace = []
        yield {"event": "routed", "data": {"workflow_id": workflow_id,
               "intent": request.intent.value, "agent": ROUTES[request.intent][0], "steps": len(steps)}}
        for number, step in enumerate(steps, start=1):
            event = {"workflow_id": workflow_id, "step": number, "agent": step.agent, "tool": step.tool}
            yield {"event": "tool_started", "data": event}
            result = self.agents[step.agent].execute(step.tool, step.arguments)
            trace.append({**event, "status": "completed"})
            yield {"event": "tool_completed", "data": {**event, "result": result}}
        yield {"event": "completed", "data": {"workflow_id": workflow_id,
               "intent": request.intent.value, "agent": ROUTES[request.intent][0],
               "result": result, "trace": trace}}

    def run(self, request: WorkflowRequest) -> dict:
        events = list(self.events(request))
        return events[-1]["data"]
