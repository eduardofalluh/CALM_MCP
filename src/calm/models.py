from __future__ import annotations

from pydantic import BaseModel


class CALMHeaders(BaseModel):
    token: str
    base_url: str
    token_source: str | None = None
    user_email: str | None = None  # User email for audit logging
