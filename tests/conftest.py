import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def test_environment(tmp_path_factory):
    database_path = tmp_path_factory.mktemp("calories-tracker-tests") / "test.db"
    os.environ["JWT_SECRET"] = "test-only-secret-with-at-least-32-characters"
    os.environ["DATABASE_PATH"] = str(database_path)
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("GOOGLE_CLIENT_ID", None)
    os.environ.pop("GOOGLE_CLIENT_SECRET", None)
    os.environ.pop("GOOGLE_REDIRECT_URI", None)
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
