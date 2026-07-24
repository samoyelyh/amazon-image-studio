from io import BytesIO

from PIL import Image

from app.providers.base import ProviderOutput
from app.services.image_delivery_service import image_dimensions, reinforce_delivery_prompt, render_delivery_output


def source_output(width: int = 300, height: int = 400) -> ProviderOutput:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (20, 80, 180)).save(buffer, format="PNG")
    return ProviderOutput(buffer.getvalue(), "image/png", "generated.png")


def test_delivery_prompt_reinforces_exact_size_quality_and_no_crop_contract():
    payload = {
        "prompt": "Keep the product unchanged.",
        "aspect_ratio": "16:9",
        "provider_aspect_ratio": "1:1",
        "requested_width": 4096,
        "requested_height": 2304,
        "quality": "high",
        "output_format": "jpeg",
        "output_compression": 82,
    }
    reinforced = reinforce_delivery_prompt(payload)
    assert "DELIVERY COMPOSITION CONTRACT" in reinforced["prompt"]
    assert "4096x2304" in reinforced["prompt"]
    assert "16:9" in reinforced["prompt"]
    assert "quality is HIGH" in reinforced["prompt"]
    assert "format is JPEG" in reinforced["prompt"]
    assert "Nothing may be cropped out" in reinforced["prompt"]


def test_worker_delivery_render_has_exact_requested_dimensions_and_format():
    rendered = render_delivery_output(source_output(), {
        "requested_width": 640,
        "requested_height": 360,
        "output_format": "jpeg",
        "output_compression": 82,
    })
    assert rendered.mime_type == "image/jpeg"
    assert rendered.filename.endswith("-640x360.jpg")
    assert image_dimensions(rendered.content) == (640, 360)


def test_ratio_mismatch_preserves_both_outer_edges_instead_of_cropping():
    source = Image.new("RGB", (300, 100), "green")
    for x in range(10):
        for y in range(100):
            source.putpixel((x, y), (255, 0, 0))
            source.putpixel((299 - x, y), (0, 0, 255))
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    rendered = render_delivery_output(
        ProviderOutput(buffer.getvalue(), "image/png", "wide.png"),
        {"requested_width": 100, "requested_height": 100, "output_format": "png"},
    )
    with Image.open(BytesIO(rendered.content)) as delivered:
        assert delivered.size == (100, 100)
        assert delivered.getpixel((0, 50))[0] > 200
        assert delivered.getpixel((99, 50))[2] > 200
