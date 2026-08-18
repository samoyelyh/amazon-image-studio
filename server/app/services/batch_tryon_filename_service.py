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
MAX_TEMPLATE_STEM_LENGTH = 72


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
    template_index: int | None = None,
) -> str:
    extension = normalize_output_extension(output_format)
    garment_stem = sanitize_batch_try_on_filename_stem(original_filename)
    template_stem = sanitize_batch_try_on_filename_stem(template_name)
    if not template_stem and template_index is not None and int(template_index) > 0:
        template_stem = f"template-{int(template_index)}"
    if not garment_stem:
        short_id = re.sub(r"[^A-Za-z0-9]", "", item_id or "")[:8] or "output"
        garment_stem = f"batch-tryon-{short_id}"
    stem = _join_template_and_garment_stems(template_stem, garment_stem)
    suffix = ""
    if version_number and not is_approved:
        suffix += f"-v{max(1, int(version_number))}"
    if duplicate_index > 1:
        suffix += f"-{int(duplicate_index)}"
    max_stem = max(1, MAX_FILENAME_STEM_LENGTH - len(suffix))
    return f"{stem[:max_stem].rstrip(' .-')}{suffix}.{extension}"


def _join_template_and_garment_stems(template_stem: str, garment_stem: str) -> str:
    if not template_stem:
        return garment_stem
    if len(template_stem) + len(garment_stem) + 1 <= MAX_FILENAME_STEM_LENGTH:
        return f"{template_stem}-{garment_stem}"
    template_limit = min(len(template_stem), MAX_TEMPLATE_STEM_LENGTH)
    garment_limit = max(1, MAX_FILENAME_STEM_LENGTH - template_limit - 1)
    if len(garment_stem) < garment_limit:
        template_limit = min(len(template_stem), MAX_FILENAME_STEM_LENGTH - len(garment_stem) - 1)
        garment_limit = len(garment_stem)
    return f"{template_stem[:template_limit].rstrip(' .-')}-{garment_stem[:garment_limit].rstrip(' .-')}"


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
