from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from typing import Optional

from src.health_check import check_llm_health
from src.config import settings
from src import constants
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", tags=["System"])
async def service_health(request: Request) -> JSONResponse:
    llm_ok = check_llm_health()
    pdf_processor: Optional[object] = getattr(request.app.state, "pdf_processor", None)
    pdf_ok = pdf_processor is not None

    payload = {
        "status": "healthy" if (llm_ok and pdf_ok) else "degraded",
        "components": {
            "llm": {"status": "ok" if llm_ok else "error"},
            "pdf_processor": {"status": "ok" if pdf_ok else "not_ready"},
        },
        "api_version": settings.app.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    status_code = 200 if payload["status"] == "healthy" else 503
    return JSONResponse(content=payload, status_code=status_code)
