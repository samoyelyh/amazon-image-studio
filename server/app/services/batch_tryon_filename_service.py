from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
WHITESPACE = re.compile(r"\s+")
KNOWN_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,10}$")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
FORMAT_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "jpeg": "jpg",
    "jpg": "jpg",
    "image/png": "png",
    "png": "png",
    "image/webp": "webp",
    "webp": "webp",
}
MAX_FILENAME_STEM_LENGTH = 180


def normalize_output_extension(output_format: str | None) -> str:
    return FORMAT_EXTENSIONS.get((output_format or "").strip().lower(), "png")


def sanitize_batch_try_on_filename_stem(original_filename: str | None) -> str:
    value = unicodedata.normalize("NFKC", str(original_filename or ""))
    value = INVALID_FILENAME_CHARS.sub("-", value)
    value = WHITESPACE.sub(" ", value)
    value = KNOWN_EXTENSION.sub("", value).strip(" .")
    value = re.sub(r"\s*-\s*", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    if value.upper() in WINDOWS_RESERVED_NAMES:
        value = f"{value}-file"
    return value[:MAX_FILENAME_STEM_LENGTH].rstrip(" .-")


def build_batch_try_on_output_filename(
    original_filename: str | None,
    output_format: str | None,
    version_number: int | None = None,
    is_approved: bool = True,
    duplicate_index: int = 1,
    *,
    item_id: str | None = None,
    template_name: str | None = None,
) -> str:
    extension = normalize_output_extension(output_format)
    stem = sanitize_batch_try_on_filename_stem(original_filename)
    template_stem = sanitize_batch_try_on_filename_stem(template_name)
    if template_stem and stem:
        stem = f"{template_stem}__{stem}"
    if not stem:
        short_id = re.sub(r"[^A-Za-z0-9]", "", item_id or "")[:8] or "output"
        stem = f"batch-tryon-{short_id}"
    suffix = ""
    if version_number and not is_approved:
        suffix += f"-v{max(1, int(version_number))}"
    if duplicate_index > 1:
        suffix += f"-{int(duplicate_index)}"
    max_stem = max(1, MAX_FILENAME_STEM_LENGTH - len(suffix))
    return f"{stem[:max_stem].rstrip(' .-')}{suffix}.{extension}"


def deduplicate_download_filename(filename: str, used_names: set[str]) -> str:
    candidate = filename
    stem = PurePosixPath(filename).stem
    extension = PurePosixPath(filename).suffix
    duplicate_index = 2
    while candidate.casefold() in used_names:
        suffix = f"-{duplicate_index}"
        candidate = f"{stem[:max(1, MAX_FILENAME_STEM_LENGTH - len(suffix))]}{suffix}{extension}"
        duplicate_index += 1
    used_names.add(candidate.casefold())
    return candidate
