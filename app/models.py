from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class SubmitRequest(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None

    @field_validator("url", "text", mode="before")
    @classmethod
    def at_least_one(cls, v):
        return v

    def model_post_init(self, __context):
        if not self.url and not self.text:
            raise ValueError("Either 'url' or 'text' must be provided")
        if self.url and self.text:
            raise ValueError("Provide either 'url' or 'text', not both")


class SubmitResponse(BaseModel):
    job_id: str
    status: str


class StatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime


class ResultResponse(BaseModel):
    job_id: str
    original_url: Optional[str] = None
    summary: Optional[str] = None
    cached: bool
    processing_time_ms: Optional[int] = None
    error: Optional[str] = None
