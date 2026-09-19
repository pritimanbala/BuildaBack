from pydantic import BaseModel, EmailStr, Field
from typing import Literal
from uuid import UUID


class SignUpRequest(BaseModel):
    email: EmailStr
    role: Literal["ADMIN", "EXE"]
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=255)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str | None
    role: Literal["ADMIN", "EXE"]
    model_config = {"from_attributes": True}
