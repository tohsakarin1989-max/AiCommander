import pytest
from fastapi import HTTPException

from app.api.map_mcp import _require_external_geo_enabled
from app.config import settings


def test_legacy_external_geo_is_disabled_by_default():
    assert settings.ENABLE_LEGACY_EXTERNAL_GEO is False
    with pytest.raises(HTTPException) as exc_info:
        _require_external_geo_enabled()

    assert exc_info.value.status_code == 410
