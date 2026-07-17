from app.core.config import Settings
from app.models.tasks import ProviderType
from app.providers.base import BaseImageProvider
from app.providers.openai_compatible import CustomImageProvider, NewAPIProvider, OpenAICompatibleProvider


def get_provider_adapter(provider_type: str, settings: Settings) -> BaseImageProvider:
    if provider_type == ProviderType.OPENAI_COMPATIBLE.value:
        return OpenAICompatibleProvider(settings)
    if provider_type == ProviderType.NEW_API.value:
        return NewAPIProvider(settings)
    if provider_type == ProviderType.CUSTOM.value:
        return CustomImageProvider(settings)
    raise ValueError(f"Unsupported provider type: {provider_type}")
