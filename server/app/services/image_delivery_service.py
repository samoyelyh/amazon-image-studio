from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.providers.base import ProviderOutput


DELIVERY_PROMPT_MARKER = "DELIVERY COMPOSITION CONTRACT"
FORMAT_DETAILS = {
    "jpeg": ("JPEG", "image/jpeg", "jpg"),
    "png": ("PNG", "image/png", "png"),
    "webp": ("WEBP", "image/webp", "webp"),
}


class ImageDeliveryError(ValueError):
    pass


def reinforce_delivery_prompt(payload: dict[str, object]) -> dict[str, object]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or DELIVERY_PROMPT_MARKER in prompt:
        return payload

    contract = delivery_prompt_contract(payload)
    if not contract:
        return payload
    payload["prompt"] = f"{prompt}\n\n{contract}"
    return payload


def delivery_prompt_contract(payload: dict[str, object]) -> str:
    """Build the deterministic technical contract appended to business prompts."""

    width = _positive_int(payload.get("requested_width"))
    height = _positive_int(payload.get("requested_height"))
    target_ratio = str(payload.get("aspect_ratio") or "auto")
    provider_ratio = str(payload.get("provider_aspect_ratio") or target_ratio)
    quality = str(payload.get("quality") or "auto").strip().lower()
    output_format = str(payload.get("output_format") or "png").strip().upper()
    compression = _compression(payload.get("output_compression"))
    if not width or not height:
        return ""

    return (
        f"{DELIVERY_PROMPT_MARKER}: The final delivery canvas is exactly {width}x{height} "
        f"pixels with a {target_ratio} aspect ratio. The upstream working canvas uses the verified "
        f"{provider_ratio} aspect ratio. Requested rendering quality is {quality.upper()}; produce "
        f"{_quality_instruction(quality)}. The delivery format is {output_format} with quality/compression "
        f"value {compression}. Compose natively for the complete final {target_ratio} canvas and keep the "
        "entire product, face, garment, text-free focal details, and all critical edges visible. Nothing "
        "may be cropped out. Leave sufficient natural background around the subject. Do not add borders, "
        "letterboxing, pillarboxing, frames, or artificial blank margins. Preserve natural perspective "
        "and avoid stretching."
    )


def render_delivery_output(output: ProviderOutput, payload: dict[str, object]) -> ProviderOutput:
    width = _positive_int(payload.get("requested_width"))
    height = _positive_int(payload.get("requested_height"))
    if not width or not height:
        return output

    output_format = str(payload.get("output_format") or "png").strip().lower()
    if output_format not in FORMAT_DETAILS:
        raise ImageDeliveryError(f"Unsupported delivery format: {output_format}")
    pil_format, mime_type, extension = FORMAT_DETAILS[output_format]
    compression = _compression(payload.get("output_compression"))

    try:
        with Image.open(BytesIO(output.content)) as source:
            source.load()
            normalized = ImageOps.exif_transpose(source)
            working = _delivery_mode(normalized, pil_format)
            delivered = _resize_without_crop(working, width, height)

            buffer = BytesIO()
            save_options: dict[str, object] = {}
            if pil_format == "JPEG":
                save_options.update(quality=compression, optimize=True, progressive=True)
            elif pil_format == "WEBP":
                save_options.update(quality=compression, method=6)
            else:
                save_options.update(optimize=True, compress_level=9)
            delivered.save(buffer, format=pil_format, **save_options)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageDeliveryError("Upstream output could not be rendered as the requested delivery image") from error

    stem = output.filename.rsplit(".", 1)[0] if "." in output.filename else output.filename
    return ProviderOutput(buffer.getvalue(), mime_type, f"{stem}-{width}x{height}.{extension}")


def image_dimensions(content: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(content)) as image:
            return image.size
    except (UnidentifiedImageError, OSError) as error:
        raise ImageDeliveryError("Upstream returned an unreadable image") from error


def delivery_transform(source_width: int, source_height: int, target_width: int, target_height: int) -> str:
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height
    return "resize" if abs(source_ratio - target_ratio) / target_ratio <= 0.002 else "pad"


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _compression(value: object) -> int:
    try:
        parsed = int(value) if value is not None else 90
    except (TypeError, ValueError):
        return 90
    return max(1, min(100, parsed))


def _quality_instruction(quality: str) -> str:
    return {
        "high": "maximum fine detail, clean edges, realistic texture, and professional commercial polish",
        "medium": "balanced detail, clean edges, and commercially usable texture",
        "low": "a clean coherent result while prioritizing efficient rendering",
        "auto": "the best available detail and commercial finish for the selected model",
    }.get(quality, "the best available detail and commercial finish")


def _delivery_mode(image: Image.Image, pil_format: str) -> Image.Image:
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    if pil_format in {"PNG", "WEBP"} and has_alpha:
        return image.convert("RGBA")
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _resize_without_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    if delivery_transform(image.width, image.height, width, height) == "resize":
        return image.resize((width, height), Image.Resampling.LANCZOS)

    contained = ImageOps.contain(image, (width, height), method=Image.Resampling.LANCZOS)
    if image.mode == "RGBA":
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        left = (width - contained.width) // 2
        top = (height - contained.height) // 2
        canvas.alpha_composite(contained, (left, top))
        return canvas

    canvas = Image.new(image.mode, (width, height), _average_corner_color(image))
    canvas.paste(contained, ((width - contained.width) // 2, (height - contained.height) // 2))
    return canvas


def _average_corner_color(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    points = [(0, 0), (rgb.width - 1, 0), (0, rgb.height - 1), (rgb.width - 1, rgb.height - 1)]
    colors = [rgb.getpixel(point) for point in points]
    return tuple(sum(color[channel] for color in colors) // len(colors) for channel in range(3))
