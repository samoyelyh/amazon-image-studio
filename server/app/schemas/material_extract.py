from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.tasks import JobResponse


class MaterialPoint(BaseModel):
    x: float = Field(ge=0, le=32768)
    y: float = Field(ge=0, le=32768)


class MaterialStroke(BaseModel):
    tool: Literal["select", "erase"]
    size: float = Field(ge=1, le=1000)
    points: list[MaterialPoint] = Field(min_length=1, max_length=10_000)


class MaterialSelectionBounds(BaseModel):
    x: float = Field(ge=0, le=32768)
    y: float = Field(ge=0, le=32768)
    width: float = Field(gt=0, le=32768)
    height: float = Field(gt=0, le=32768)


class MaterialExtractRequest(BaseModel):
    source_asset_id: str = Field(min_length=1, max_length=36)
    target_description: str = Field(default="", max_length=1000)
    selection_bounds: MaterialSelectionBounds
    brush_strokes: list[MaterialStroke] = Field(default_factory=list, max_length=200)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_stroke_volume(self) -> "MaterialExtractRequest":
        if sum(len(stroke.points) for stroke in self.brush_strokes) > 50_000:
            raise ValueError("brush_strokes contains too many points")
        return self


class MaterialExtractResponse(BaseModel):
    job: JobResponse
    source_asset_id: str
    roi_asset_id: str
    background_color: str
