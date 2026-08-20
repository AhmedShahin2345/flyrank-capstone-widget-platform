from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class WidgetInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    widget_type: Literal["signup", "contact", "popover"] = "signup"
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    button_text: str = Field(default="Submit", min_length=1, max_length=60)
    fields: list[dict] = Field(min_length=1, max_length=10)
    allowed_origins: list[str] = Field(min_length=1, max_length=20)

    @field_validator("allowed_origins")
    @classmethod
    def origins_are_real_origins(cls, origins: list[str]) -> list[str]:
        if any(not value.startswith(("http://", "https://")) for value in origins):
            raise ValueError("Allowed origins must start with http:// or https://")
        return origins


class PublicSubmission(BaseModel):
    fields: dict[str, str] = Field(min_length=1)
    honeypot: str = Field(default="", max_length=200)
