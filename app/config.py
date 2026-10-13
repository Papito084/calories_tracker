"""
Application configuration and environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Explicitly load .env file from base directory
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

class Settings:
    APP_NAME: str = "Calories Tracker"
    APP_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", 8001))

    # Use PostgreSQL when DATABASE_URL is configured; SQLite remains the local default.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    DATABASE_PATH: Path = Path(
        os.getenv("DATABASE_PATH", str(BASE_DIR / "cal_ai.db"))
    ).expanduser()

    # AI API Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()

    # Model configuration
    JWT_SECRET: str = os.getenv("JWT_SECRET", "").strip()
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    COOKIE_SECURE: bool = os.getenv(
        "COOKIE_SECURE", "true" if os.getenv("RENDER") else "false"
    ).lower() in {"1", "true", "yes"}
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]

settings = Settings()

# Validate essential configuration
if settings.DATABASE_URL and not settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
    raise RuntimeError("DATABASE_URL must be a PostgreSQL connection string.")
if not settings.JWT_SECRET:
    raise RuntimeError("JWT_SECRET is required. Set a random secret of at least 32 characters.")
if len(settings.JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET must be at least 32 characters for secure JWT signing.")
