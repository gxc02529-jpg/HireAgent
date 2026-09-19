"""One-process demo repository. Compound operations use the same re-entrant lock."""

from threading import RLock

from .domain import Candidate, Interview, Job


class MemoryStore:
    def __init__(self) -> None:
        self.lock = RLock()
        self.candidates: dict[str, Candidate] = {}
        self.jobs: dict[str, Job] = {}
        self.interviews: dict[str, Interview] = {}
        self.idempotency: dict[str, tuple[str, str]] = {}


def demo_store() -> MemoryStore:
    """Synthetic records; no real CVs, phone numbers or email addresses."""
    store = MemoryStore()
    for candidate in (
        Candidate(candidate_id="demo-c1", display_name="演示候选人甲",
                  skills=["Python", "FastAPI", "RAG"], years_experience=3, location="上海"),
        Candidate(candidate_id="demo-c2", display_name="演示候选人乙",
                  skills=["Python", "SQL"], years_experience=1, location="杭州"),
    ):
        store.candidates[candidate.candidate_id] = candidate
    job = Job(job_id="demo-j1", title="AI 应用开发工程师", required_skills=["python", "fastapi", "rag"],
              minimum_years=2, location="上海", remote=False)
    store.jobs[job.job_id] = job
    return store
