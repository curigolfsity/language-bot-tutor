from uuid import UUID

from pydantic import BaseModel, Field

from tutor_contracts.learners import LearnerProfileOut


class ResolveUserRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32, examples=["telegram"])
    external_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=128)
    target_lang: str = Field(min_length=2, max_length=8, examples=["es"])
    native_lang: str = Field(min_length=2, max_length=8, examples=["en"])


class ResolveUserResponse(BaseModel):
    user_id: UUID
    profile: LearnerProfileOut
    created: bool = Field(description="True when the profile was created by this call.")
