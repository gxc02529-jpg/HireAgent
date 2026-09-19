from datetime import datetime, timezone

import pytest

from hire_agent.store import demo_store
from hire_agent.tools import RecruitingTools


@pytest.fixture
def tools():
    return RecruitingTools(demo_store(), clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def booking():
    return {"candidate_id": "demo-c1", "job_id": "demo-j1", "interviewer_id": "demo-hr1",
            "starts_at": "2030-01-07T10:00:00Z", "duration_minutes": 60,
            "idempotency_key": "request-1"}
