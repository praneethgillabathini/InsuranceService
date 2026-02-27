import logging
import sys
from contextvars import ContextVar
from .config import settings

from typing import Optional

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


def setup_logging():
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s'
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    log_level = getattr(logging, settings.logging.level.upper(), logging.INFO)
    uvicorn_level = getattr(logging, settings.logging.uvicorn_access_level.upper(), logging.WARNING)
    logging.basicConfig(level=log_level, handlers=[handler], force=True)
    logging.getLogger("uvicorn.access").setLevel(uvicorn_level)