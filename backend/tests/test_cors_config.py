from app.cors import build_cors_origins


def test_localhost_frontend_allows_127_loopback_alias():
    origins = build_cors_origins("http://localhost:3000")

    assert origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_127_frontend_allows_localhost_alias():
    origins = build_cors_origins("http://127.0.0.1:3000")

    assert origins == ["http://127.0.0.1:3000", "http://localhost:3000"]


def test_extra_cors_origins_are_normalized_and_deduplicated():
    origins = build_cors_origins(
        "http://localhost:3000/",
        " http://10.0.0.2:3000/ , http://127.0.0.1:3000 ",
    )

    assert origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://10.0.0.2:3000",
    ]
