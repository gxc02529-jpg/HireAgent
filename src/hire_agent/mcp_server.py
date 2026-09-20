"""FastMCP protocol adapter for the thirteen recruiting domain tools."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import date, datetime
from fastmcp import FastMCP

from .store import MemoryStore, demo_store
from .tools import RecruitingTools


def create_mcp_server(
    store: MemoryStore | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> FastMCP:
    """Build an MCP server over the same validated tool layer as the HTTP API."""

    tools = RecruitingTools(store or demo_store(), clock=clock)
    mcp = FastMCP(
        name="HireAgent",
        instructions=(
            "Recruiting workflow tools for candidates, jobs, matching and interview scheduling. "
            "Matching output is advisory and requires human review. Mutating calls must use "
            "caller-managed identifiers and idempotency keys."
        ),
    )

    @mcp.tool
    def upsert_candidate(
        candidate_id: str,
        display_name: str,
        skills: list[str],
        years_experience: float,
        location: str,
        summary: str = "",
    ) -> dict:
        """Create or replace one structured candidate profile."""
        return tools.invoke("upsert_candidate", {
            "candidate_id": candidate_id,
            "display_name": display_name,
            "skills": skills,
            "years_experience": years_experience,
            "location": location,
            "summary": summary,
        })

    @mcp.tool
    def get_candidate(candidate_id: str) -> dict:
        """Get one candidate by its stable identifier."""
        return tools.invoke("get_candidate", {"candidate_id": candidate_id})

    @mcp.tool
    def search_candidates(skill: str = "", minimum_years: float = 0, limit: int = 20) -> list[dict]:
        """Filter candidates by normalized skill and minimum experience."""
        return tools.invoke("search_candidates", {
            "skill": skill,
            "minimum_years": minimum_years,
            "limit": limit,
        })

    @mcp.tool
    def summarize_resume(candidate_id: str) -> dict:
        """Create a fact-only template summary from a structured candidate profile."""
        return tools.invoke("summarize_resume", {"candidate_id": candidate_id})

    @mcp.tool
    def upsert_job(
        job_id: str,
        title: str,
        required_skills: list[str],
        minimum_years: float,
        location: str,
        remote: bool = False,
    ) -> dict:
        """Create or replace one structured job requirement."""
        return tools.invoke("upsert_job", {
            "job_id": job_id,
            "title": title,
            "required_skills": required_skills,
            "minimum_years": minimum_years,
            "location": location,
            "remote": remote,
        })

    @mcp.tool
    def get_job(job_id: str) -> dict:
        """Get one job by its stable identifier."""
        return tools.invoke("get_job", {"job_id": job_id})

    @mcp.tool
    def search_jobs(query: str = "", location: str = "", limit: int = 20) -> list[dict]:
        """Search job title, normalized skills and location."""
        return tools.invoke("search_jobs", {"query": query, "location": location, "limit": limit})

    @mcp.tool
    def match_candidate(candidate_id: str, job_id: str) -> dict:
        """Return explainable skill, experience and location matching evidence."""
        return tools.invoke("match_candidate", {"candidate_id": candidate_id, "job_id": job_id})

    @mcp.tool
    def rank_candidates(job_id: str) -> list[dict]:
        """Rank all known candidates for one job using the transparent scoring rule."""
        return tools.invoke("rank_candidates", {"job_id": job_id})

    @mcp.tool
    def list_interview_slots(
        interviewer_id: str,
        day: date,
        duration_minutes: int = 60,
    ) -> list[dict]:
        """List available UTC weekday slots for an interviewer."""
        return tools.invoke("list_interview_slots", {
            "interviewer_id": interviewer_id,
            "day": day,
            "duration_minutes": duration_minutes,
        })

    @mcp.tool
    def schedule_interview(
        candidate_id: str,
        job_id: str,
        interviewer_id: str,
        starts_at: datetime,
        duration_minutes: int,
        idempotency_key: str,
    ) -> dict:
        """Schedule an interview with idempotency and participant conflict checks."""
        return tools.invoke("schedule_interview", {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "interviewer_id": interviewer_id,
            "starts_at": starts_at,
            "duration_minutes": duration_minutes,
            "idempotency_key": idempotency_key,
        })

    @mcp.tool
    def cancel_interview(interview_id: str) -> dict:
        """Idempotently cancel one interview and release its slot."""
        return tools.invoke("cancel_interview", {"interview_id": interview_id})

    @mcp.tool
    def list_interviews(
        candidate_id: str | None = None,
        interviewer_id: str | None = None,
        include_cancelled: bool = False,
    ) -> list[dict]:
        """List interviews with optional candidate and interviewer filters."""
        return tools.invoke("list_interviews", {
            "candidate_id": candidate_id,
            "interviewer_id": interviewer_id,
            "include_cancelled": include_cancelled,
        })

    return mcp


mcp = create_mcp_server()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HireAgent MCP server")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
