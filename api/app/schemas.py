from pydantic import BaseModel


class WorkspaceCreate(BaseModel):
    user_id: str = "default"


class WorkspaceOut(BaseModel):
    id: str
    token: str
    user_id: str
    container_id: str | None = None
    port: int | None = None
    status: str
    url: str | None = None
    created_at: str
    last_active: str
