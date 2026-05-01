from pydantic import BaseModel

from .client import DEFAULT_BASE_URL


class CALMHeaders(BaseModel):
    token: str
    base_url: str = DEFAULT_BASE_URL
