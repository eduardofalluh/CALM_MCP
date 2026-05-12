from __future__ import annotations

from pydantic import BaseModel


class CALMHeaders(BaseModel):
    token: str
    base_url: str
    token_source: str | None = None
