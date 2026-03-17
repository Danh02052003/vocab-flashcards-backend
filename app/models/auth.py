from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    resetCode: str | None = None


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    resetCode: str = Field(min_length=4, max_length=32)
    newPassword: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    createdAt: datetime


class AuthTokenResponse(BaseModel):
    token: str
    user: UserOut
