from io import BytesIO

from PIL import Image, ImageDraw

from app.providers.base import ProviderOutput
from app.services.region_replace_service import composite_mask_edit_output, precompose_region_replace_base


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_composite_mask_edit_output_preserves_unmasked_pixels() -> None:
    base = Image.new("RGBA", (20, 20), (20, 40, 60, 255))
    edited = Image.new("RGBA", (20, 20), (250, 10, 10, 255))
    mask = Image.new("RGBA", (20, 20), (255, 255, 255, 255))
    ImageDraw.Draw(mask).rectangle((5, 5, 14, 14), fill=(0, 0, 0, 0))

    result = composite_mask_edit_output(
        _png(base), _png(mask), ProviderOutput(_png(edited), "image/png", "edited.png"),
    )
    output = Image.open(BytesIO(result.content)).convert("RGBA")

    assert output.getpixel((0, 0)) == base.getpixel((0, 0))
    assert output.getpixel((10, 10)) == edited.getpixel((10, 10))


def test_precompose_region_replace_base_maps_patch_exactly_into_target_frame() -> None:
    base = Image.new("RGBA", (100, 80), (20, 40, 60, 255))
    patch = Image.new("RGBA", (10, 20), (240, 30, 50, 255))

    result = precompose_region_replace_base(
        _png(base),
        _png(patch),
        {"normalized_bounds": {"x": 0.2, "y": 0.25, "width": 0.4, "height": 0.5}},
    )
    output = Image.open(BytesIO(result)).convert("RGBA")

    assert output.size == base.size
    assert output.getpixel((0, 0)) == base.getpixel((0, 0))
    assert output.getpixel((20, 20)) == patch.getpixel((0, 0))
    assert output.getpixel((59, 59)) == patch.getpixel((9, 19))
    assert output.getpixel((60, 60)) == base.getpixel((60, 60))
