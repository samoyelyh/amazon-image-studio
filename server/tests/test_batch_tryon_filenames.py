from app.services.batch_tryon_filename_service import (
    build_batch_try_on_output_filename,
    deduplicate_download_filename,
    sanitize_batch_try_on_filename_stem,
)
from app.services.asset_service import content_disposition_header


def test_batch_try_on_output_filename_preserves_source_stem_and_format() -> None:
    assert build_batch_try_on_output_filename("A001-front.jpg", "png") == "A001-front.png"
    assert build_batch_try_on_output_filename("中文 款式.jpeg", "image/png") == "中文 款式.png"
    assert build_batch_try_on_output_filename("06-blue-jersey.webp", "png") == "06-blue-jersey.png"
    assert build_batch_try_on_output_filename("photo.png", "jpeg") == "photo.jpg"


def test_batch_try_on_output_filename_sanitizes_unsafe_and_reserved_names() -> None:
    assert build_batch_try_on_output_filename('  A/\\:*?"<>|  shirt.jpg', "png") == "A-shirt.png"
    assert build_batch_try_on_output_filename("CON.png", "png") == "CON-file.png"
    assert build_batch_try_on_output_filename("...jpg", "png", item_id="abc12345-extra") == "batch-tryon-abc12345.png"
    assert len(sanitize_batch_try_on_filename_stem(f"{'长' * 240}.png")) == 180


def test_batch_try_on_version_and_duplicate_names_do_not_overwrite() -> None:
    assert build_batch_try_on_output_filename("shirt.jpg", "png", 1, False) == "shirt-v1.png"
    assert build_batch_try_on_output_filename("shirt.jpg", "png", 2, False) == "shirt-v2.png"
    assert build_batch_try_on_output_filename("shirt.jpg", "png", 2, True) == "shirt.png"
    assert build_batch_try_on_output_filename("shirt.webp", "png", duplicate_index=2) == "shirt-2.png"
    used: set[str] = set()
    assert deduplicate_download_filename("shirt.png", used) == "shirt.png"
    assert deduplicate_download_filename("SHIRT.png", used) == "SHIRT-2.png"
    assert deduplicate_download_filename("shirt.png", used) == "shirt-3.png"


def test_multi_template_output_filename_includes_template_name() -> None:
    assert build_batch_try_on_output_filename(
        "06-blue-jersey.webp",
        "png",
        template_name="欧美男模-01",
    ) == "欧美男模-01__06-blue-jersey.png"
    assert build_batch_try_on_output_filename(
        "06-blue-jersey.webp",
        "png",
        version_number=2,
        is_approved=False,
        template_name="欧美男模-01",
    ) == "欧美男模-01__06-blue-jersey-v2.png"


def test_utf8_content_disposition_has_ascii_and_rfc5987_filenames() -> None:
    header = content_disposition_header("中文款式.png")
    assert 'filename="download.png"' in header
    assert "filename*=UTF-8''%E4%B8%AD%E6%96%87%E6%AC%BE%E5%BC%8F.png" in header
