from __future__ import annotations

from math import gcd, log
import re

SIZE_PATTERN = re.compile(r"^(\d{1,5})x(\d{1,5})$")
RATIO_PATTERN = re.compile(r"^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$")
SIZE_ALIASES = {"outputSize", "output_size", "image_size", "resolved_size", "resolvedSize"}
MAX_DELIVERY_EDGE = 10_000
MAX_DELIVERY_PIXELS = 40_000_000


class ImageSizeError(ValueError):
    def __init__(self, code: str, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def normalize_image_job_input(value: dict[str, object]) -> dict[str, object]:
    payload = dict(value)
    aliases = sorted(SIZE_ALIASES.intersection(payload))
    if aliases:
        raise ValueError(f"unknown image size field(s): {', '.join(aliases)}; use input.size")

    size = payload.get("size")
    if not isinstance(size, str) or not size.strip():
        raise ValueError("input.size is required for image tasks")
    size = re.sub(r"\s+", "", size.strip().lower()).replace("×", "x")
    aspect_ratio = _normalize_ratio(str(payload.get("aspect_ratio") or "auto"))

    if size == "auto":
        if aspect_ratio != "auto" and not _valid_ratio(aspect_ratio):
            raise ValueError("input.aspect_ratio must use width:height format")
        width = height = None
    else:
        match = SIZE_PATTERN.fullmatch(size)
        if not match:
            raise ValueError("input.size must be auto or WIDTHxHEIGHT")
        width, height = int(match.group(1)), int(match.group(2))
        if width < 1 or height < 1 or width > MAX_DELIVERY_EDGE or height > MAX_DELIVERY_EDGE:
            raise ValueError(f"input.size dimensions must be between 1 and {MAX_DELIVERY_EDGE}")
        if width * height > MAX_DELIVERY_PIXELS:
            raise ValueError(f"input.size must not exceed {MAX_DELIVERY_PIXELS} pixels")
        if aspect_ratio == "auto":
            divisor = gcd(width, height)
            aspect_ratio = f"{width // divisor}:{height // divisor}"
        elif not _valid_ratio(aspect_ratio):
            raise ValueError("input.aspect_ratio must use width:height format")

    payload.update({
        "size": size,
        "delivery_size": size,
        "aspect_ratio": aspect_ratio,
        "requested_width": width,
        "requested_height": height,
    })
    # These are trusted internal working parameters and are resolved from the
    # selected model configuration after operation/resource-pool validation.
    payload.pop("provider_size", None)
    payload.pop("provider_aspect_ratio", None)
    return payload


def validate_provider_size(size: object, config: dict[str, object]) -> str:
    if not isinstance(size, str) or not size.strip():
        raise ImageSizeError("provider.invalid_size", "图片任务缺少明确的尺寸参数")
    normalized = size.strip().lower().replace("×", "x")
    if normalized != "auto" and not SIZE_PATTERN.fullmatch(normalized):
        raise ImageSizeError("provider.invalid_size", "图片尺寸必须使用 WIDTHxHEIGHT 格式")
    configured = config.get("supported_sizes")
    if isinstance(configured, list) and configured:
        supported = {str(item).strip().lower().replace("×", "x") for item in configured}
        if normalized not in supported:
            raise ImageSizeError(
                "provider.unsupported_size",
                f"当前模型不支持所选尺寸 {normalized}，请在模型配置中选择受支持的尺寸。",
            )
    return normalized


def provider_dimension_fields(
    payload: dict[str, object], config: dict[str, object], *, is_edit: bool,
) -> tuple[dict[str, str], str, str]:
    prefix = "edit" if is_edit else "generation"
    mode = str(config.get(f"{prefix}_dimension_mode") or "size")
    if mode == "aspect_ratio":
        aspect_ratio = str(payload.get("provider_aspect_ratio") or payload.get("aspect_ratio") or "auto").strip().lower()
        if aspect_ratio == "auto":
            size = validate_provider_size(payload.get("provider_size") or payload.get("size"), config)
            match = SIZE_PATTERN.fullmatch(size)
            if match:
                divisor = gcd(int(match.group(1)), int(match.group(2)))
                aspect_ratio = f"{int(match.group(1)) // divisor}:{int(match.group(2)) // divisor}"
        if not _valid_ratio(aspect_ratio):
            raise ImageSizeError("provider.invalid_aspect_ratio", "当前模型需要明确的 width:height 图片比例")
        supported = config.get(f"supported_{prefix}_aspect_ratios")
        if isinstance(supported, list) and supported and aspect_ratio not in {str(item) for item in supported}:
            raise ImageSizeError(
                "provider.unsupported_size",
                f"当前模型尚未验证支持所选比例 {aspect_ratio}，请使用已验证比例。",
            )
        field = str(config.get(f"{prefix}_aspect_ratio_field") or "aspect_ratio")
        return {field: aspect_ratio}, field, aspect_ratio

    size = validate_provider_size(payload.get("provider_size") or payload.get("size"), config)
    return {"size": size}, "size", size


def validate_submission_dimensions(payload: dict[str, object], config: dict[str, object], *, capability: str) -> None:
    is_edit = capability != "image_generation"
    prefix = "edit" if is_edit else "generation"
    mode = str(config.get(f"{prefix}_dimension_mode") or "size")
    target_ratio = str(payload.get("aspect_ratio") or "auto").strip().lower()

    if target_ratio == "auto":
        width = payload.get("requested_width")
        height = payload.get("requested_height")
        if width and height:
            target_ratio = _ratio_from_dimensions(int(width), int(height))
            payload["aspect_ratio"] = target_ratio

    if mode == "aspect_ratio":
        supported = _string_list(config.get(f"supported_{prefix}_aspect_ratios"))
        verified = config.get(f"verified_{prefix}_output_sizes")
        if isinstance(verified, dict):
            verified_ratios = [str(item) for item in verified if _valid_ratio(str(item))]
            supported = [item for item in supported if item in verified_ratios] or verified_ratios or supported
        if not supported:
            raise ImageSizeError(
                "provider.missing_verified_ratio",
                "当前模型没有配置已验证的图片比例，无法安全提交图片任务。",
            )
        provider_ratio = _nearest_ratio(target_ratio, supported)
        payload["provider_aspect_ratio"] = provider_ratio
        if isinstance(verified, dict) and provider_ratio in verified:
            provider_size = str(verified[provider_ratio]).strip().lower().replace("×", "x")
            if not SIZE_PATTERN.fullmatch(provider_size):
                raise ImageSizeError("provider.invalid_size_config", "模型的已验证输出尺寸配置无效")
            payload["provider_size"] = provider_size
        else:
            payload["provider_size"] = "auto"
    else:
        target_size = str(payload.get("delivery_size") or payload.get("size") or "auto")
        supported_sizes = _string_list(config.get("supported_sizes"))
        if supported_sizes and target_size not in supported_sizes:
            payload["provider_size"] = _nearest_size(target_ratio, supported_sizes)
        else:
            payload["provider_size"] = target_size

    # Only validate the internal provider working parameters. The requested
    # delivery dimensions remain untouched and are fulfilled by the Worker.
    provider_dimension_fields(payload, config, is_edit=is_edit)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower().replace("×", "x") for item in value if str(item).strip()]


def _normalize_ratio(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.strip().lower())
    normalized = normalized.removeprefix("≈").replace("×", ":").replace("x", ":")
    if normalized == "template":
        return "auto"
    return normalized or "auto"


def _ratio_from_dimensions(width: int, height: int) -> str:
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _ratio_value(value: str) -> float | None:
    match = RATIO_PATTERN.fullmatch(value)
    if not match:
        return None
    width, height = float(match.group(1)), float(match.group(2))
    return width / height if width > 0 and height > 0 else None


def _nearest_ratio(target: str, candidates: list[str]) -> str:
    target_value = _ratio_value(target)
    if target_value is None:
        return candidates[0]

    def score(candidate: str) -> tuple[float, int]:
        value = _ratio_value(candidate)
        if value is None:
            return (float("inf"), candidates.index(candidate))
        return (abs(log(target_value / value)), candidates.index(candidate))

    return min(candidates, key=score)


def _nearest_size(target_ratio: str, candidates: list[str]) -> str:
    valid: list[tuple[str, str]] = []
    for size in candidates:
        match = SIZE_PATTERN.fullmatch(size)
        if match:
            valid.append((size, _ratio_from_dimensions(int(match.group(1)), int(match.group(2)))))
    if not valid:
        raise ImageSizeError("provider.invalid_size_config", "模型支持尺寸配置无效")
    selected_ratio = _nearest_ratio(target_ratio, [ratio for _, ratio in valid])
    return next(size for size, ratio in valid if ratio == selected_ratio)


def _valid_ratio(value: str) -> bool:
    match = RATIO_PATTERN.fullmatch(value)
    if not match:
        return False
    width, height = float(match.group(1)), float(match.group(2))
    return width > 0 and height > 0
