from surya_slim.client import (
    EndpointUnavailableError,
    FailureCallback,
    FailureContext,
    ModelDiscoveryError,
    OCRResponseError,
    SuryaSlimClient,
    SuryaSlimError,
    ocr_image,
)
from surya_slim.config import ConfigError, EndpointConfig
from surya_slim.models import BlockOCRResult, PageOCRResult

__all__ = [
    "BlockOCRResult",
    "ConfigError",
    "EndpointConfig",
    "EndpointUnavailableError",
    "FailureCallback",
    "FailureContext",
    "ModelDiscoveryError",
    "OCRResponseError",
    "PageOCRResult",
    "SuryaSlimClient",
    "SuryaSlimError",
    "ocr_image",
]
