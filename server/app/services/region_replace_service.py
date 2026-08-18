from io import BytesIO

from PIL import Image

from app.core.errors import AppError
from app.providers.base import ProviderOutput


def precompose_region_replace_base(
    base_content: bytes,
    patch_content: bytes,
    target_metadata: dict[str, object] | None,
) -> bytes:
    """Map the exact Image C patch into the selected target frame before AI blending.

    This is a deterministic pixel transfer, equivalent to a rectangular free
    transform in an image editor. The provider receives the already placed
    artwork and is only responsible for local surface integration.
    """
    try:
        with Image.open(BytesIO(base_content)) as base_source:
            base = base_source.convert("RGBA")
        with Image.open(BytesIO(patch_content)) as patch_source:
            patch = patch_source.convert("RGBA")
    except OSError as error:
        raise AppError("batch_tryon.invalid_region_replace_image", "区域替换输入包含无效图片。", 422) from error

    metadata = target_metadata if isinstance(target_metadata, dict) else {}
    raw_bounds = metadata.get("normalized_bounds")
    if not isinstance(raw_bounds, dict):
        raise AppError("batch_tryon.region_target_bounds_missing", "区域替换缺少目标框坐标。", 422)
    try:
        x = float(raw_bounds.get("x", 0))
        y = float(raw_bounds.get("y", 0))
        width = float(raw_bounds.get("width", 0))
        height = float(raw_bounds.get("height", 0))
    except (TypeError, ValueError) as error:
        raise AppError("batch_tryon.region_target_bounds_invalid", "区域替换目标框坐标无效。", 422) from error
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    width = max(0.0, min(1.0 - x, width))
    height = max(0.0, min(1.0 - y, height))
    if width <= 0 or height <= 0:
        raise AppError("batch_tryon.region_target_bounds_invalid", "区域替换目标框不能为空。", 422)

    left = min(base.width - 1, max(0, round(x * base.width)))
    top = min(base.height - 1, max(0, round(y * base.height)))
    right = min(base.width, max(left + 1, round((x + width) * base.width)))
    bottom = min(base.height, max(top + 1, round((y + height) * base.height)))
    # Intentionally use independent X/Y scaling: the two UI frames may have
    # different dimensions and the target frame is the explicit destination.
    mapped_patch = patch.resize((right - left, bottom - top), Image.Resampling.LANCZOS)
    precomposed = base.copy()
    precomposed.alpha_composite(mapped_patch, (left, top))
    buffer = BytesIO()
    precomposed.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def composite_mask_edit_output(base_content: bytes, mask_content: bytes, output: ProviderOutput) -> ProviderOutput:
    """Guarantee that pixels outside the editable alpha region come from the base image.

    Providers may introduce small global reconstruction differences even when
    they honor the mask. Compositing with the same mask makes the product
    contract deterministic without cropping or resizing the user's result.
    """
    try:
        with Image.open(BytesIO(base_content)) as base_source:
            base = base_source.convert("RGBA")
        with Image.open(BytesIO(mask_content)) as mask_source:
            mask = mask_source.convert("RGBA")
        with Image.open(BytesIO(output.content)) as edited_source:
            edited = edited_source.convert("RGBA")
    except OSError as error:
        raise AppError("batch_tryon.invalid_region_replace_image", "区域替换返回了无效图片。", 502) from error
    if mask.size != base.size:
        raise AppError("batch_tryon.region_mask_size_mismatch", "区域替换蒙版与基础结果尺寸不一致。", 422)
    if edited.size != base.size:
        edited = edited.resize(base.size, Image.Resampling.LANCZOS)
    editable = mask.getchannel("A").point(lambda value: 255 - value)
    composed = Image.composite(edited, base, editable)
    buffer = BytesIO()
    composed.save(buffer, format="PNG", optimize=True)
    return ProviderOutput(buffer.getvalue(), "image/png", output.filename.rsplit(".", 1)[0] + ".png")
