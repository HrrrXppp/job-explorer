from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_USER_AGENT = "job-explorer/0.1"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LooseModel(BaseModel):
    """Runtime / email-state objects: ignore unknown fields."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class HttpRequest(FrozenModel):
    method: Literal["GET", "POST", "PUT", "PATCH"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    follow_redirects: bool = False

    @field_validator("method", mode="before")
    @classmethod
    def upper_method(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("url")
    @classmethod
    def require_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("url is required")
        return value

    @field_validator("headers", mode="before")
    @classmethod
    def stringify_headers(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {str(key): str(item) for key, item in value.items()}


class KeepIfSpec(FrozenModel):
    """Drop extracted items unless any named field contains any of the needles."""

    fields: list[str] = Field(min_length=1)
    contains_any: list[str] = Field(min_length=1)


class ItemsSpec(FrozenModel):
    kind: Literal["json", "html"]
    list: str
    fields: dict[str, str]
    url_template: str | None = None
    keep_if: KeepIfSpec | None = None

    @field_validator("fields")
    @classmethod
    def require_id_field(cls, value: dict[str, str]) -> dict[str, str]:
        if "id" not in value:
            raise ValueError("fields.id is required — name the item id field in config.json")
        return value

    @field_validator("url_template")
    @classmethod
    def strip_url_template(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def keep_if_fields_exist(self) -> ItemsSpec:
        if self.keep_if is None:
            return self
        missing = [name for name in self.keep_if.fields if name not in self.fields]
        if missing:
            raise ValueError(f"keep_if.fields must be keys in items.fields: {missing}")
        return self


class DetailSpec(FrozenModel):
    request: HttpRequest
    description: str

    @field_validator("description", mode="before")
    @classmethod
    def field_path_only(cls, value: object) -> object:
        if isinstance(value, dict):
            return (
                value.get("path")
                or value.get("selector")
                or value.get("field")
                or value.get("pattern")
            )
        return value

    @field_validator("description")
    @classmethod
    def require_description_field(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("detail_request.description names the field that holds the job text")
        return stripped

    @model_validator(mode="before")
    @classmethod
    def split_flat_config(cls, data: object) -> object:
        if not isinstance(data, dict) or "request" in data:
            return data
        if "url" not in data and "method" not in data:
            return data
        description = data.get("description")
        request = {key: value for key, value in data.items() if key != "description"}
        return {"request": request, "description": description}


class Source(FrozenModel):
    id: str
    search_request: HttpRequest
    items: ItemsSpec
    detail_request: DetailSpec | None = None
    max_detail_requests: int = Field(default=100, ge=0)


class ResumeSpec(FrozenModel):
    id: str
    path: str


class EmailSpec(FrozenModel):
    to: list[str] = Field(default_factory=list)

    @field_validator("to", mode="before")
    @classmethod
    def coerce_to(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class MatchingSpec(FrozenModel):
    model: str = DEFAULT_MODEL
    cache_dir: str = ".models"


class AppConfig(FrozenModel):
    resumes: list[ResumeSpec] = Field(min_length=1)
    sources: list[Source] = Field(min_length=1)
    matching: MatchingSpec = Field(default_factory=MatchingSpec)
    email: EmailSpec = Field(default_factory=EmailSpec)
    user_agent: str = DEFAULT_USER_AGENT
    config_dir: str = "."

    @field_validator("user_agent")
    @classmethod
    def strip_user_agent(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("user_agent must be a non-empty string")
        return stripped


class CrawledItem(LooseModel):
    id: str
    source_id: str
    title: str
    url: str
    description: str | None
    skipped_detail: bool


class CachedPosition(LooseModel):
    id: str
    title: str = ""
    url: str = ""
    source_id: str = ""
    scores: dict[str, float] = Field(default_factory=dict)

    @field_validator("scores", mode="before")
    @classmethod
    def coerce_scores(cls, value: object) -> object:
        if not isinstance(value, dict):
            return {}
        return {str(key): float(item) for key, item in value.items()}


class PreviousState(LooseModel):
    version: int = 2
    resume_fingerprints: dict[str, str] = Field(default_factory=dict)
    positions: list[CachedPosition] = Field(default_factory=list)
    position_ids: set[str] = Field(default_factory=set)

    @model_validator(mode="after")
    def merge_position_ids(self) -> PreviousState:
        ids = set(self.position_ids)
        ids.update(row.id for row in self.positions)
        if ids == self.position_ids:
            return self
        return self.model_copy(update={"position_ids": ids})


class ScoredPosition(LooseModel):
    id: str
    title: str
    url: str
    source_id: str
    scores: dict[str, float]
    snippet: str | None = None

    @property
    def best_percent(self) -> float:
        return max(self.scores.values()) if self.scores else 0.0

    @property
    def best_resume_id(self) -> str:
        if not self.scores:
            return ""
        return max(self.scores.items(), key=lambda item: item[1])[0]
