"""Fixed offline font identities; no caller-selected fonts or storage paths."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FontProfile:
    fonts: tuple[str, ...]
    storage_slug: str

    @property
    def fontstack(self) -> str:
        return ','.join(self.fonts)


PROFILES = {
    'cjk-v1': FontProfile(('Noto Sans CJK SC Regular',), 'noto-sans-cjk-sc-regular'),
    'cjk-mongolian-emoji-v1': FontProfile(
        ('Noto Sans CJK SC Regular', 'Noto Sans Mongolian Regular', 'Noto Emoji Regular'),
        'cjk-mongolian-emoji-v1'),
}


def font_profile(manifest: dict) -> FontProfile:
    key = manifest.get('font_profile', 'cjk-v1')
    if not isinstance(key, str) or key not in PROFILES:
        raise ValueError('invalid_font_profile')
    return PROFILES[key]


def validate_fontstack(value: str) -> None:
    if not isinstance(value, str) or value not in {profile.fontstack for profile in PROFILES.values()}:
        raise ValueError('invalid_fontstack')
