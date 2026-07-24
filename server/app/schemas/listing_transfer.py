from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SendListingOutputRequest(BaseModel):
    target_mode: Literal["create_project", "existing_project"]
    project_name: str | None = Field(default=None, max_length=160)
    project_description: str | None = Field(default=None, max_length=500)
    target_project_id: str | None = None
    replace_existing_template: bool = False
    idempotency_key: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def validate_target(self):
        if self.target_mode == "create_project" and not (self.project_name or "").strip():
            raise ValueError("创建新项目时必须填写项目名称")
        if self.target_mode == "existing_project" and not self.target_project_id:
            raise ValueError("请选择目标批量套图项目")
        return self


class SendListingOutputResponse(BaseModel):
    batch_project_id: str
    batch_project_name: str
    model_asset_id: str
    listing_output_id: str
    listing_project_id: str | None
    redirect_path: str
    template_replaced: bool
    created_project: bool
    replayed: bool = False
    warnings: list[str] = Field(default_factory=list)
