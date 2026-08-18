from io import BytesIO

from PIL import Image, ImageDraw

from app.prompts.material_extract import build_material_extract_prompt
from app.providers.base import ProviderOutput
from app.schemas.tasks import JobSubmitRequest
from app.schemas.material_extract import MaterialExtractRequest
from app.services.material_extract_service import (
    calculate_padded_roi,
    choose_background_color,
    crop_material_roi,
    high_resolution_size,
    render_material_extract_output,
)


def png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_material_extract_workspace_routes_to_listing_worker() -> None:
    request = JobSubmitRequest(
        operation_code="asset.extract",
        workspace_type="material_extract",
        queue_name="listing_queue",
        capability="image_edit",
        model_code="image-2",
        idempotency_key="material-extract-test-1",
        input={
            "prompt": "extract object",
            "n": 1,
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "reference_asset_ids": ["asset-1"],
        },
    )
    assert request.workspace_type == "material_extract"
    assert request.operation_code == "asset.extract"


def test_material_extract_accepts_long_continuous_stroke() -> None:
    request = MaterialExtractRequest(
        source_asset_id="asset-1",
        selection_bounds={"x": 0, "y": 0, "width": 100, "height": 100},
        brush_strokes=[{
            "tool": "select",
            "size": 36,
            "points": [{"x": index % 100, "y": index % 100} for index in range(3_175)],
        }],
        idempotency_key="material-long-stroke-test",
    )
    assert len(request.brush_strokes[0].points) == 3_175


def test_roi_padding_is_clamped_and_preserves_source() -> None:
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).rectangle((0, 10, 30, 60), fill="red")
    assert calculate_padded_roi((0, 10, 30, 50), image.size) == (0, 0, 43, 73)
    result = crop_material_roi(png(image), (0, 10, 30, 50))
    assert result.box == (0, 0, 43, 73)
    assert (result.width, result.height) == (43, 73)


def test_high_resolution_size_preserves_ratio() -> None:
    assert high_resolution_size(1000, 500) == (2048, 1024)
    assert high_resolution_size(250, 1000) == (512, 2048)


def test_background_choice_avoids_dominant_subject_color() -> None:
    image = Image.new("RGB", (100, 100), "#00EE00")
    assert choose_background_color(png(image)) != "#00FF00"


def test_prompt_contains_target_and_flat_background_contract() -> None:
    prompt = build_material_extract_prompt(target_description="红色球衣", background_color="#00FFFF")
    assert "红色球衣" in prompt
    assert "#00FFFF" in prompt
    assert "uniform edge to edge" in prompt


def test_alpha_conversion_is_true_rgba_and_keeps_disconnected_same_color_inside_subject() -> None:
    image = Image.new("RGB", (80, 80), "#00FF00")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 60, 65), fill="#CC2222")
    draw.rectangle((32, 28, 48, 50), fill="#00FF00")
    output = render_material_extract_output(
        ProviderOutput(png(image), "image/png", "upstream.png"),
        "#00FF00",
    )
    assert output.mime_type == "image/png"
    with Image.open(BytesIO(output.content)) as result:
        assert result.mode == "RGBA"
        assert result.getpixel((0, 0))[3] == 0
        assert result.getpixel((40, 40))[3] > 245
        assert result.getpixel((20, 40))[3] > 220


def test_alpha_conversion_has_soft_edge_pixels() -> None:
    image = Image.new("RGB", (50, 50), "#00FF00")
    ImageDraw.Draw(image).ellipse((10, 10, 40, 40), fill="#333333")
    output = render_material_extract_output(
        ProviderOutput(png(image), "image/png", "upstream.png"), "#00FF00",
    )
    with Image.open(BytesIO(output.content)) as result:
        alphas = set(result.getchannel("A").getdata())
        assert 0 in alphas
        assert 255 in alphas
        assert any(0 < value < 255 for value in alphas)
