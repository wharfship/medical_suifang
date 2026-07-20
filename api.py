"""HTTP API entry point for the medical follow-up workflow."""

from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from followup_api_service import (
    AlgorithmServiceError,
    FollowupError,
    FollowupNotFoundError,
    FollowupStorageError,
    FollowupValidationError,
    FollowupWorkflow,
)


class CreateFollowupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_name: str = Field(description="患者姓名，2至20个字符")
    student_id: str = Field(description="8位学工号")


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000, description="患者本轮回答")


def create_app(workflow: FollowupWorkflow | None = None):
    app = FastAPI(
        title="AI 医疗随访 API",
        version="0.1.0",
        description="第一版为内存会话服务。服务重启后，未完成随访会失效。当前未包含登录和权限控制，不得直接公开暴露。",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.workflow = workflow or FollowupWorkflow()

    def run(action):
        try:
            return action()
        except FollowupNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FollowupValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AlgorithmServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except FollowupStorageError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except FollowupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/health", tags=["system"])
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/followups", tags=["followups"])
    def create_followup(request: CreateFollowupRequest):
        return run(
            lambda: app.state.workflow.create_followup(
                request.patient_name,
                request.student_id,
            )
        )

    @app.get("/api/v1/followups/{followup_id}", tags=["followups"])
    def get_followup(followup_id: str):
        return run(lambda: app.state.workflow.get_followup(followup_id))

    @app.post("/api/v1/followups/{followup_id}/messages", tags=["followups"])
    def submit_message(followup_id: str, request: MessageRequest):
        return run(lambda: app.state.workflow.submit_message(followup_id, request.content))

    @app.post("/api/v1/followups/{followup_id}/reports", tags=["followups"])
    async def submit_report(followup_id: str, file: UploadFile = File(...)):
        content = await file.read()
        return run(lambda: app.state.workflow.submit_report(followup_id, file.filename or "", content))

    return app


app = create_app()
