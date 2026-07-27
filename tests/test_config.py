from app.config import Settings


def test_cors_origins_splits_comma_separated_values():
    settings = Settings(cors_allowed_origins="http://localhost:3000,http://localhost:5173")

    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:5173"]


def test_cors_origins_trims_whitespace():
    settings = Settings(cors_allowed_origins=" http://localhost:3000 , http://localhost:5173 ")

    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:5173"]


def test_cors_origins_empty_string_returns_empty_list():
    settings = Settings(cors_allowed_origins="")

    assert settings.cors_origins == []


def test_cors_origins_single_value():
    settings = Settings(cors_allowed_origins="http://localhost:3000")

    assert settings.cors_origins == ["http://localhost:3000"]
