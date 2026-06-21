from urllib.parse import urlparse, urlunparse


LOOPBACK_ALIASES = {
    "localhost": "127.0.0.1",
    "127.0.0.1": "localhost",
}


def _normalize_origin(origin: str) -> str:
    value = origin.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    return value


def _loopback_alias(origin: str) -> str | None:
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    alias_host = LOOPBACK_ALIASES.get(parsed.hostname)
    if not alias_host:
        return None

    netloc = f"{alias_host}:{parsed.port}" if parsed.port else alias_host
    return urlunparse((parsed.scheme, netloc, "", "", "", ""))


def build_cors_origins(frontend_url: str, extra_origins: str | None = None) -> list[str]:
    origins: list[str] = []
    seen: set[str] = set()

    def add(origin: str | None) -> None:
        if not origin:
            return
        normalized = _normalize_origin(origin)
        if normalized and normalized not in seen:
            origins.append(normalized)
            seen.add(normalized)

    add(frontend_url)
    add(_loopback_alias(_normalize_origin(frontend_url)))
    for origin in (extra_origins or "").split(","):
        add(origin)

    return origins
