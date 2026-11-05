"""Opt-in native multi-output request builder; not enabled in production routing.

Two numbered input sheets do not establish native multi-output support. Count,
duplicate and visual correspondence checks must pass before business integration.
No output splitting or positional assignment is performed here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from app.providers.base import ProviderError, ProviderResult


@dataclass(frozen=True)
class CollageTryOnItem:
    pair_id: str
    template_asset_id: str
    garment_asset_id: str
    panel_number: int
    position: str
    # x, y, width, height, normalized against each complete input sheet.
    reference_rect: tuple[float, float, float, float]


def build_collage_multi_output_request(
    *, items: list[CollageTryOnItem], template_collage: dict, garment_collage: dict,
    custom_prompt: str = "", size: str = "1536x2048", aspect_ratio: str = "3:4",
) -> dict[str, object]:
    if not 2 <= len(items) <= 10:
        raise ValueError("Native multi-output probes require 2 to 10 distinct pairs")
    if len({item.pair_id for item in items}) != len(items):
        raise ValueError("pair_id must be unique")
    if len({item.panel_number for item in items}) != len(items):
        raise ValueError("panel_number must be unique")
    for item in items:
        x, y, width, height = item.reference_rect
        if not (0 <= x < 1 and 0 <= y < 1 and width > 0 and height > 0
                and x + width <= 1 and y + height <= 1):
            raise ValueError("reference_rect must be normalized inside the input sheet")
    if any(not isinstance(ref.get("content"), bytes) or not ref["content"]
           for ref in (template_collage, garment_collage)):
        raise ValueError("Both input sheets must contain image bytes")
    count = len(items)
    prompt = f"""This is ONE native multi-output image-edit request for {count} DIFFERENT products.
Return exactly {count} separate, independently encoded result images in the API response as individual image results.
Do NOT return one collage, contact sheet, grid, multi-panel poster or a single image containing multiple results.
Do NOT return {count} variations of the same garment. Each output must use a different input pair below.

Image A is a numbered sheet of model templates. Image B is a numbered sheet of garments.
The numbered panels and gray gutters only identify INPUT references; they are NOT the output layout.
For output i, extract ONLY the complete model composition from panel i of Image A,
and dress that model in ONLY the garment from matching panel i of Image B.
Return one full-frame standalone model composition per output, without the input sheet gutters or panel labels.
Requested response order follows the pair manifest below. Never swap, duplicate or mix products between outputs.
Coordinates are normalized x,y,width,height within both input sheets:
{json.dumps([asdict(item) for item in items], ensure_ascii=False)}

For EACH pair: keep the template's people, identities, faces, hairstyles, expressions, poses,
hands, body proportions, non-target clothing, props, background, lighting, camera angle,
composition, original headline and captions unchanged. Replace only the target foreground garment.
Use the current garment's actual front design when the model faces forward. Do not transfer back-view
thumbnail artwork onto the chest. Preserve its colors, collar, cuffs, sleeves, silhouette, print,
logos, original text and numbers, font shapes, outlines and fabric details faithfully.
Remove the old garment's design and incompatible structures. Adapt fabric perspective, folds,
shadows and occlusions naturally. Never copy another pair's garment details.
Each separate output should be {size}, high-quality photorealistic e-commerce photography.
Do not reduce quality to produce more outputs. Return independent images, not a grid.
"""
    if custom_prompt.strip():
        prompt += "\nOperator requirements:\n" + custom_prompt.strip()
    return {"prompt": prompt, "n": count, "size": size, "aspect_ratio": aspect_ratio,
        "quality": "high", "reference_images": [dict(template_collage), dict(garment_collage)]}


def native_multi_output_config(config: dict[str, object]) -> dict[str, object]:
    """Keep the production config untouched; explicitly send n in this opt-in probe."""
    result = dict(config)
    fields = result.get("edit_body_fields")
    if isinstance(fields, list):
        result["edit_body_fields"] = list(dict.fromkeys([*fields, "n"]))
    return result


def validate_native_multi_output(result: ProviderResult, expected_count: int) -> None:
    if len(result.outputs) != expected_count:
        raise ProviderError("provider.multi_output_count_mismatch",
            f"本次请求{expected_count}张独立图片，上游实际返回{len(result.outputs)}张；不切分、不补发，也不标记整组成功。")
    hashes = [sha256(output.content).digest() for output in result.outputs]
    if len(set(hashes)) != expected_count:
        raise ProviderError("provider.multi_output_duplicate",
            "上游返回了重复图片，未形成每件服装独立对应的结果。")
    # Distinct bytes are necessary, not sufficient: visual mapping still needs review.
