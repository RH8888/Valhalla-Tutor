from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class HealthCheckResponse(BaseModel):
    status: str = Field(..., description="Overall health status: 'healthy' or 'unhealthy'")
    app_name: str
    environment: str
    database_connected: bool
    timezone: str
    server_time_utc: datetime
    server_time_local: str
    database_error: Optional[str] = None


class SimpleHealthResponse(BaseModel):
    status: str
    app_name: str

