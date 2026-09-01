from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    user_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_.\-]+$",
        description="Human-readable label for this workspace (no spaces).",
    )
    password: str = Field(
        min_length=6,
        max_length=128,
        description="Password the user will enter to access their VS Code workspace.",
    )


class WorkspacePublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    container_id: str | None = None
    status: str
    deleted_at: str | None = None
    url: str | None = None
    created_at: str
    last_active: str


class WorkspaceCreateOut(WorkspacePublic):
    """
    Extends the public view with the one-time token.
    The token is the workspace PASSWORD for code-server — share it only with
    the intended user. It is never returned again after this response.
    """

    token: str
