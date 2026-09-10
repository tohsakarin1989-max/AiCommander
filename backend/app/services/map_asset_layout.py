"""Canonical schema-2 storage layout, independent of application configuration."""
from app.services.map_font_profiles import font_profile
from app.services.map_glyph_validation import glyph_asset_range


def storage_key(package_hash: str, asset: dict, manifest: dict | None = None) -> str:
    if asset['role'] == 'glyphs':
        span = glyph_asset_range(asset['name'])
        profile = font_profile(manifest or {})
        return f'bundles/{package_hash}/glyphs/{profile.storage_slug}/{span}.pbf'
    return f"bundles/{package_hash}/assets/{asset['name']}"
