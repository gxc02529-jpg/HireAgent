"""Local demo API; launch one worker bound to loopback."""

import json
import os

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from . import __version__
from .agents import Orchestrator, ROUTES
from .domain import WorkflowRequest
from .store import MemoryStore, demo_store
from .tools import DomainError, RecruitingTools


def create_app(store: MemoryStore | None = None) -> FastAPI:
    app = FastAPI(title="HireAgent", version=__version__, description="Offline recruiting workflow demo")
    if store is None:
        store = demo_store() if os.getenv("HIREAGENT_DEMO_DATA", "true").lower() == "true" else MemoryStore()
    tools = RecruitingTools(store)
    orchestrator = Orchestrator(tools)
    app.state.tools, app.state.orchestrator = tools, orchestrator

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, error: DomainError):
        return JSONResponse(status_code=error.status, content={"error": error.code, "message": error.message})

    @app.exception_handler(ValidationError)
    async def validation_error(_request: Request, error: ValidationError):
        details = [{"loc": item["loc"], "type": item["type"], "msg": item["msg"]}
                   for item in error.errors()]
        return JSONResponse(status_code=422, content={"error": "invalid_arguments", "details": details})

    @app.get("/health")
    def health():
        return {"status": "ok", "storage": "in_memory", "version": __version__}

    @app.get("/tools")
    def list_tools():
        return tools.describe()

    @app.post("/tools/{tool_name}")
    def invoke_tool(tool_name: str, arguments: dict = Body(...)):
        return {"tool": tool_name, "result": tools.invoke(tool_name, arguments)}

    @app.get("/agents")
    def list_agents():
        return [{"name": agent.name, "tools": sorted(agent.allowed_tools),
                 "intents": [intent.value for intent, route in ROUTES.items() if route[0] == agent.name]}
                for agent in orchestrator.agents.values()]

    @app.post("/workflows")
    def run_workflow(request: WorkflowRequest):
        return orchestrator.run(request)

    @app.post("/workflows/stream")
    def stream_workflow(request: WorkflowRequest):
        # Invalid arguments retain HTTP 422, before streaming sends the HTTP headers.
        steps = orchestrator.plan(request)

        def stream():
            try:
                for event in orchestrator.events(request, steps):
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            except DomainError as error:
                payload = {"error": error.code, "message": error.message}
                yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


app = create_app()
