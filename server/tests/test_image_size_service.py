import pytest

from app.services.image_size_service import (
    ImageSizeError, normalize_image_job_input, validate_provider_size, validate_submission_dimensions,
)


@pytest.mark.parametrize(("size", "ratio", "portrait", "landscape"), [
    ("1024x1024", "1:1", False, False),
    ("1024x1536", "3:4", True, False),
    ("1536x1024", "4:3", False, True),
    ("1536x864", "16:9", False, True),
    ("864x1536", "9:16", True, False),
])
def test_image_size_snapshot_keeps_requested_orientation(size, ratio, portrait, landscape):
    payload = normalize_image_job_input({"size": size, "aspect_ratio": ratio})
    assert (payload["requested_width"] < payload["requested_height"]) is portrait
    assert (payload["requested_width"] > payload["requested_height"]) is landscape
    assert payload["delivery_size"] == size
    assert "provider_size" not in payload
    assert payload["aspect_ratio"] == ratio


def test_unknown_size_alias_is_rejected_instead_of_ignored():
    with pytest.raises(ValueError, match="use input.size"):
        normalize_image_job_input({"size": "1024x1024", "outputSize": "1024x1536"})


@pytest.mark.parametrize(("ratio", "expected"), [
    ("≈3:4", "3:4"),
    (" 4 × 3 ", "4:3"),
])
def test_display_ratio_formats_are_normalized_for_api_requests(ratio, expected):
    payload = normalize_image_job_input({"size": "1088 × 1440", "aspect_ratio": ratio})
    assert payload["aspect_ratio"] == expected
    assert payload["size"] == "1088x1440"


def test_template_ratio_uses_exact_delivery_dimensions():
    payload = normalize_image_job_input({"size": "1088x1440", "aspect_ratio": "template"})
    assert payload["aspect_ratio"] == "34:45"


def test_provider_rejects_unconfigured_size_without_fallback():
    with pytest.raises(ImageSizeError) as error:
        validate_provider_size("1024x1536", {"supported_sizes": ["1024x1024"]})
    assert error.value.code == "provider.unsupported_size"


def test_4k_delivery_is_accepted_while_provider_uses_verified_working_ratio():
    payload = normalize_image_job_input({"size": "2880x3840", "aspect_ratio": "3:4"})
    validate_submission_dimensions(payload, {
        "edit_dimension_mode": "aspect_ratio",
        "supported_edit_aspect_ratios": ["1:1", "3:4"],
        "verified_edit_output_sizes": {"1:1": "1254x1254", "3:4": "1024x1536"},
    }, capability="image_edit")
    assert payload["delivery_size"] == "2880x3840"
    assert payload["requested_width"] == 2880
    assert payload["requested_height"] == 3840
    assert payload["provider_aspect_ratio"] == "3:4"
    assert payload["provider_size"] == "1024x1536"


def test_free_delivery_ratio_maps_to_nearest_verified_provider_ratio():
    payload = normalize_image_job_input({"size": "4096x2304", "aspect_ratio": "16:9"})
    validate_submission_dimensions(payload, {
        "edit_dimension_mode": "aspect_ratio",
        "supported_edit_aspect_ratios": ["1:1", "3:4"],
        "verified_edit_output_sizes": {"1:1": "1254x1254", "3:4": "1024x1536"},
    }, capability="image_edit")
    assert payload["aspect_ratio"] == "16:9"
    assert payload["provider_aspect_ratio"] == "1:1"
    assert payload["requested_width"] == 4096
    assert payload["requested_height"] == 2304


def test_square_4k_delivery_request_is_not_rejected_by_verified_1k_working_canvas():
    payload = normalize_image_job_input({"size": "4096x4096", "aspect_ratio": "1:1"})
    validate_submission_dimensions(payload, {
        "edit_dimension_mode": "aspect_ratio",
        "supported_edit_aspect_ratios": ["1:1", "3:4"],
        "verified_edit_output_sizes": {"1:1": "1254x1254", "3:4": "1024x1536"},
    }, capability="image_edit")
    assert payload["delivery_size"] == "4096x4096"
    assert payload["provider_size"] == "1254x1254"
