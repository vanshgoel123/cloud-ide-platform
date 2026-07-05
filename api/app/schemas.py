from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")


class WorkspacePublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    container_id: str | None = None
    port: int | None = None
    status: str
    deleted_at: str | None = None
    url: str | None = None
    created_at: str
    last_active: str


class WorkspaceCreateOut(WorkspacePublic):
    token: str
