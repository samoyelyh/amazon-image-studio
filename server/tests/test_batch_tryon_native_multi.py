import base64
from email.parser import BytesParser
from email.policy import default

import httpx
import pytest

from app.core.config import Settings
from app.providers.base import ProviderError, ProviderOutput, ProviderResult
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.services.batch_tryon_native_multi_service import (
    CollageTryOnItem, build_collage_multi_output_request, native_multi_output_config,
    validate_native_multi_output,
)
from tests.test_provider_adapters import install_transport


def request():
    items = [CollageTryOnItem(f"pair-{i}", "template-id", f"garment-{i}", i,
        str(i), (0, (i - 1) / 4, 1, 1 / 4)) for i in range(1, 5)]
    return build_collage_multi_output_request(items=items,
        template_collage={"filename": "templates.png", "content": b"templates"},
        garment_collage={"filename": "garments.png", "content": b"garments"})


def test_two_inputs_and_explicit_n_preserve_stable_pair_manifest():
    payload = request()
    assert payload["n"] == 4
    assert len(payload["reference_images"]) == 2
    assert '"garment_asset_id": "garment-4"' in payload["prompt"]
    assert "separate, independently encoded" in payload["prompt"]
    assert "not a grid" in payload["prompt"]


def test_probe_config_adds_n_without_changing_production_config():
    original = {"edit_body_fields": ["model", "prompt", "aspect_ratio"]}
    assert native_multi_output_config(original)["edit_body_fields"][-1] == "n"
    assert original["edit_body_fields"] == ["model", "prompt", "aspect_ratio"]


@pytest.mark.parametrize("actual", [0, 1, 3, 5])
def test_wrong_count_never_silently_passes_or_splits(actual):
    result = ProviderResult([ProviderOutput(str(i).encode(), "image/png", f"{i}.png") for i in range(actual)])
    with pytest.raises(ProviderError, match="实际返回") as error:
        validate_native_multi_output(result, 4)
    assert error.value.code == "provider.multi_output_count_mismatch"


def test_duplicate_files_are_not_distinct_outputs():
    result = ProviderResult([ProviderOutput(b"same", "image/png", f"{i}.png") for i in range(4)])
    with pytest.raises(ProviderError) as error:
        validate_native_multi_output(result, 4)
    assert error.value.code == "provider.multi_output_duplicate"


async def test_wire_request_really_contains_n_and_two_images(monkeypatch):
    def handler(req):
        parts = BytesParser(policy=default).parsebytes(
            ("Content-Type: " + req.headers["content-type"] + "\r\n\r\n").encode() + req.content)
        form, files = {}, []
        for part in parts.iter_parts():
            if part.get_filename():
                files.append(part.get_filename())
            else:
                form[part.get_param("name", header="Content-Disposition")] = part.get_payload(decode=True).decode()
        assert form["n"] == "4"
        assert files == ["templates.png", "garments.png"]
        assert req.url.path == "/v1/images/edits"
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(str(i).encode()).decode()} for i in range(4)]})
    install_transport(monkeypatch, handler)
    result = await OpenAICompatibleProvider(Settings(_env_file=None)).execute(
        base_url="https://relay.example/v1", api_key="test-only", upstream_model="image-model",
        capability="image_edit", payload=request(), config=native_multi_output_config({
            "edit_body_fields": ["model", "prompt", "aspect_ratio"],
            "edit_dimension_mode": "aspect_ratio", "supported_edit_aspect_ratios": ["3:4"],
        }))
    validate_native_multi_output(result, 4)
