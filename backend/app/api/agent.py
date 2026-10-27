"""Authenticated agent controls using existing session and API conventions."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, model_validator
from app.api.auth import SESSION_COOKIE, _token_hash
from app.schemas.api import RequestModel, Envelope
from app.investigation_agent import PlanningBudget


def require_session(request: Request):
    token=request.cookies.get(SESSION_COOKIE)
    if not token or not request.app.state.runtime.store.user_by_session(_token_hash(token),datetime.now(timezone.utc).isoformat()):
        raise HTTPException(401,"Sign in to use autonomous investigations")
    origin=request.headers.get("origin")
    if request.method=="POST" and origin and origin.rstrip("/") != str(request.base_url).rstrip("/") and origin not in ("http://localhost:5173","http://localhost:5175","http://localhost:5176","http://127.0.0.1:5173","http://127.0.0.1:5175","http://127.0.0.1:5176"):
        raise HTTPException(403,"Investigation controls require an approved application origin")


class AgentRequest(RequestModel):
    expected_run_id: str = Field(min_length=1,max_length=256)
    incident_id: str | None = Field(None,min_length=1,max_length=256)
    max_experiments: int = Field(3,ge=1,le=3,strict=True)
    duration_ticks: int = Field(20,ge=1,le=1000,strict=True)
    max_branch_ticks: int = Field(480,ge=1,le=480,strict=True)

    @model_validator(mode="after")
    def validate_budget(self):
        if 2*self.duration_ticks>self.max_branch_ticks: raise ValueError("One paired experiment must fit the branch-tick budget")
        return self


class AutoModeRequest(RequestModel):
    enabled: bool = Field(strict=True)


router=APIRouter(prefix="/api/agent",dependencies=[Depends(require_session)])


@router.get("/status",response_model=Envelope)
async def status(request:Request): return {"data":request.app.state.agent.status()}


@router.post("/auto-mode",response_model=Envelope)
async def auto_mode(request:Request,body:AutoModeRequest):
    return {"data":request.app.state.agent.configure(body.enabled)}


@router.post("/investigate",response_model=Envelope,status_code=202)
async def investigate(request:Request,body:AgentRequest):
    try:
        job=await request.app.state.agent.start(body.incident_id,body.expected_run_id,PlanningBudget(max_experiments=body.max_experiments,duration_ticks=body.duration_ticks,max_branch_ticks=body.max_branch_ticks))
        return {"data":job}
    except KeyError: raise HTTPException(404,"Incident not found")


@router.get("/investigations",response_model=Envelope)
async def recent(request:Request): return {"data":request.app.state.agent.status()["recent"]}


@router.get("/investigations/{ident}",response_model=Envelope)
async def result(request:Request,ident:str):
    try: return {"data":request.app.state.agent.get(ident)}
    except KeyError: raise HTTPException(404,"Investigation not found or expired")
