from app.core.config import Settings


def test_normalizes_supabase_database_url():
    settings = Settings(DATABASE_URL="postgresql://user:pass@example.com/postgres")
    assert settings.database_url == "postgresql+psycopg://user:pass@example.com/postgres"


def test_parses_frontend_origins():
    settings = Settings(FRONTEND_ORIGINS="http://localhost:5173,https://example.com")
    assert settings.frontend_origins == ["http://localhost:5173", "https://example.com"]
