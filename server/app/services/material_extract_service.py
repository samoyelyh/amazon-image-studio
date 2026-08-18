from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

from app.core.errors import AppError
from app.providers.base import ProviderOutput


BACKGROUND_CANDIDATES = ("#00FF00", "#FF00FF", "#00FFFF")


@dataclass(frozen=True)
class CropResult:
    content: bytes
    width: int
    height: int
    box: tuple[int, int, int, int]


def calculate_padded_roi(
    bounds: tuple[float, float, float, float],
    image_size: tuple[int, int],
    *,
    padding_ratio: float = 0.25,
) -> tuple[int, int, int, int]:
    x, y, width, height = bounds
    image_width, image_height = image_size
    if image_width < 1 or image_height < 1 or width <= 0 or height <= 0:
        raise AppError("material_extract.invalid_selection", "请先在图片中涂抹需要提取的素材", 422)
    padding = max(12.0, max(width, height) * padding_ratio)
    left = max(0, math.floor(x - padding))
    top = max(0, math.floor(y - padding))
    right = min(image_width, math.ceil(x + width + padding))
    bottom = min(image_height, math.ceil(y + height + padding))
    if right - left < 2 or bottom - top < 2:
        raise AppError("material_extract.invalid_selection", "涂抹区域过小，请扩大选择范围", 422)
    return left, top, right, bottom


def crop_material_roi(content: bytes, bounds: tuple[float, float, float, float]) -> CropResult:
    try:
        with Image.open(BytesIO(content)) as source:
            source.load()
            normalized = ImageOps.exif_transpose(source).convert("RGBA")
            box = calculate_padded_roi(bounds, normalized.size)
            cropped = normalized.crop(box)
            buffer = BytesIO()
            cropped.save(buffer, format="PNG", optimize=True)
            return CropResult(buffer.getvalue(), cropped.width, cropped.height, box)
    except AppError:
        raise
    except (UnidentifiedImageError, OSError) as error:
        raise AppError("material_extract.source_unreadable", "上传的参考图片无法读取", 422) from error


def choose_background_color(content: bytes) -> str:
    try:
        with Image.open(BytesIO(content)) as source:
            sample = ImageOps.exif_transpose(source).convert("RGB")
            sample.thumbnail((160, 160), Image.Resampling.LANCZOS)
            pixels = list(sample.getdata())
    except (UnidentifiedImageError, OSError) as error:
        raise AppError("material_extract.source_unreadable", "上传的参考图片无法读取", 422) from error
    if not pixels:
        return BACKGROUND_CANDIDATES[0]

    def score(hex_color: str) -> float:
        background = tuple(int(hex_color[index:index + 2], 16) for index in (1, 3, 5))
        distances = sorted(
            max(abs(pixel[channel] - background[channel]) for channel in range(3))
            for pixel in pixels
        )
        return float(distances[max(0, len(distances) // 20)])

    return max(BACKGROUND_CANDIDATES, key=score)


def high_resolution_size(width: int, height: int, *, max_edge: int = 2048) -> tuple[int, int]:
    if width < 1 or height < 1:
        raise ValueError("Image dimensions must be positive")
    scale = max_edge / max(width, height)
    target_width = max(256, round(width * scale))
    target_height = max(256, round(height * scale))
    return min(max_edge, target_width), min(max_edge, target_height)


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lstrip("#")
    if len(normalized) != 6:
        raise ValueError("Background color must be a six-digit hex value")
    return tuple(int(normalized[index:index + 2], 16) for index in (0, 2, 4))


def _border_connected_mask(distance: Image.Image, threshold: int) -> Image.Image:
    candidate = distance.point(lambda value: 255 if value <= threshold else 0, mode="L")
    padded = Image.new("L", (candidate.width + 2, candidate.height + 2), 255)
    padded.paste(candidate, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    connected = padded.crop((1, 1, candidate.width + 1, candidate.height + 1))
    return connected.point(lambda value: 255 if value == 128 else 0, mode="L")


def _soft_alpha(distance: Image.Image, inner: int, outer: int) -> Image.Image:
    span = max(1, outer - inner)

    def convert(value: int) -> int:
        if value <= inner:
            return 0
        if value >= outer:
            return 255
        position = (value - inner) / span
        smooth = position * position * (3 - 2 * position)
        return round(smooth * 255)

    return distance.point(convert, mode="L")


def _decontaminate_channel(channel: Image.Image, alpha: Image.Image, background: int) -> Image.Image:
    # Recover the foreground color from C = a*F + (1-a)*B. Fully transparent
    # pixels are forced to zero, avoiding bright green/magenta fringes in PNG viewers.
    return Image.frombytes(
        "L",
        channel.size,
        bytes(
            0 if a == 0 else max(0, min(255, round((c * 255 - background * (255 - a)) / a)))
            for c, a in zip(channel.getdata(), alpha.getdata())
        ),
    )


def render_material_extract_output(
    output: ProviderOutput,
    background_color: str,
    *,
    inner_threshold: int = 18,
    outer_threshold: int = 92,
) -> ProviderOutput:
    background = _parse_hex_color(background_color)
    try:
        with Image.open(BytesIO(output.content)) as source:
            source.load()
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError) as error:
        raise AppError("material_extract.output_unreadable", "上游返回的素材图片无法读取", 502) from error

    rgb = rgba.convert("RGB")
    reference = Image.new("RGB", rgb.size, background)
    difference = ImageChops.difference(rgb, reference)
    distance = ImageChops.lighter(ImageChops.lighter(*difference.split()[:2]), difference.split()[2])
    connected = _border_connected_mask(distance, outer_threshold)
    soft = _soft_alpha(distance, inner_threshold, outer_threshold)
    opaque = Image.new("L", rgb.size, 255)
    alpha = Image.composite(soft, opaque, connected)
    alpha = ImageChops.multiply(alpha, rgba.getchannel("A"))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.35))

    extrema = alpha.getextrema()
    if extrema[0] >= 255:
        raise AppError(
            "material_extract.background_not_detected",
            "未检测到可安全移除的纯色背景，请重新提取并扩大目标描述",
            502,
        )
    if extrema[1] <= 0:
        raise AppError("material_extract.empty_result", "素材提取结果为空，请重新涂抹目标区域", 502)

    red, green, blue = rgb.split()
    cleaned = Image.merge("RGBA", (
        _decontaminate_channel(red, alpha, background[0]),
        _decontaminate_channel(green, alpha, background[1]),
        _decontaminate_channel(blue, alpha, background[2]),
        alpha,
    ))
    buffer = BytesIO()
    cleaned.save(buffer, format="PNG", optimize=True, compress_level=9)
    return ProviderOutput(buffer.getvalue(), "image/png", "material-extracted.png")
