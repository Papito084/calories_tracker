import asyncio
import sqlite3
from io import BytesIO
from time import sleep
from uuid import uuid4

import pytest
from PIL import Image
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(test_environment):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_dashboard_requires_authentication(client):
    response = client.get("/api/dashboard")

    assert response.status_code == 401


def test_registration_sets_session_and_allows_dashboard(client):
    response = client.post(
        "/api/register",
        json={
            "username": f"test-{uuid4().hex}",
            "password": "a-secure-test-password-123",
        },
    )

    assert response.status_code == 200
    assert response.json()["first_time"] is True
    assert response.cookies.get("access_token")
    assert response.headers["set-cookie"].lower().find("httponly") >= 0

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["has_profile"] is False


def test_registration_rejects_short_password(client):
    response = client.post(
        "/api/register",
        json={"username": f"test-{uuid4().hex}", "password": "short"},
    )

    assert response.status_code == 422


def test_google_sign_in_is_optional_when_not_configured(client):
    status = client.get("/api/auth/google/status")

    assert status.status_code == 200
    assert status.json() == {"enabled": False}


def test_food_scan_runs_provider_off_event_loop(client, monkeypatch):
    from app import main

    username = f"scan-{uuid4().hex}"
    registration = client.post(
        "/api/register",
        json={"username": username, "password": "a-secure-test-password-123"},
    )
    assert registration.status_code == 200

    image = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image, format="PNG")
    analysis = {"dish_name": "Test meal", "total_calories": 100}
    provider_calls = []

    def fake_analyze_food_image(contents, mime_type):
        provider_calls.append((contents, mime_type))
        return analysis

    original_to_thread = asyncio.to_thread
    dispatched_functions = []

    async def tracked_to_thread(function, *args, **kwargs):
        dispatched_functions.append(function)
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(main.vision_service, "analyze_food_image", fake_analyze_food_image)
    monkeypatch.setattr(main.asyncio, "to_thread", tracked_to_thread)

    response = client.post(
        "/api/scan-food",
        files={"file": ("meal.png", image.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["analysis"] == analysis
    assert provider_calls == [(image.getvalue(), "image/png")]
    assert dispatched_functions == [fake_analyze_food_image]


def test_food_scan_provider_errors_return_json(client, monkeypatch):
    from app import main

    registration = client.post(
        "/api/register",
        json={
            "username": f"scan-error-{uuid4().hex}",
            "password": "a-secure-test-password-123",
        },
    )
    assert registration.status_code == 200

    image = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image, format="PNG")

    def fail_analysis(contents, mime_type):
        raise RuntimeError("Provider request failed")

    monkeypatch.setattr(main.vision_service, "analyze_food_image", fail_analysis)

    response = client.post(
        "/api/scan-food",
        files={"file": ("meal.png", image.getvalue(), "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Food analysis is temporarily unavailable"


def test_food_scan_timeout_returns_json_instead_of_losing_worker(client, monkeypatch):
    from app import main

    registration = client.post(
        "/api/register",
        json={
            "username": f"scan-timeout-{uuid4().hex}",
            "password": "a-secure-test-password-123",
        },
    )
    assert registration.status_code == 200

    image = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image, format="PNG")

    def slow_analysis(contents, mime_type):
        sleep(0.1)
        return {}

    monkeypatch.setattr(main, "_FOOD_ANALYSIS_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(main.vision_service, "analyze_food_image", slow_analysis)

    response = client.post(
        "/api/scan-food",
        files={"file": ("meal.png", image.getvalue(), "image/png")},
    )

    assert response.status_code == 504
    assert response.json()["detail"] == (
        "El análisis de la imagen tardó demasiado. Inténtalo de nuevo."
    )


def test_legacy_render_entry_point_imports_application(test_environment):
    from app.main import app as package_app
    from main import app as legacy_app

    assert legacy_app is package_app


def test_settings_and_mobile_layout_render_nickname_and_responsive_rules(client):
    page = client.get("/")

    assert page.status_code == 200
    assert client.get("/assets/cal-tracker-welcome.svg").status_code == 200
    assert 'id="account-nickname"' in page.text
    assert "account-last-name" not in page.text
    assert "Reiniciar Todos los Datos y Perfil" in page.text
    assert "user-scalable=no" not in page.text
    assert "@media (max-width: 360px)" in page.text
    assert "@media (max-height: 500px) and (orientation: landscape)" in page.text


def test_account_profile_can_be_updated_without_losing_account(client):
    username = f"account-{uuid4().hex}"
    password = "a-secure-test-password-123"
    registration = client.post(
        "/api/register",
        json={"username": username, "password": password},
    )
    assert registration.status_code == 200
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    account = client.get("/api/account-profile", headers=headers)
    assert account.status_code == 200
    assert account.json()["account"]["username"] == username

    updated_username = f"updated-{uuid4().hex}"
    update = client.put(
        "/api/account-profile",
        headers=headers,
        json={
            "username": updated_username,
            "first_name": "Ana",
            "nickname": "NutriAna",
        },
    )
    assert update.status_code == 200
    assert update.json()["account"]["first_name"] == "Ana"
    assert update.json()["account"]["nickname"] == "NutriAna"

    login = client.post(
        "/api/login",
        json={"username": updated_username, "password": password},
    )
    assert login.status_code == 200

    reset = client.post("/api/reset-profile", headers=headers)
    assert reset.status_code == 200
    account_after_reset = client.get("/api/account-profile", headers=headers)
    assert account_after_reset.status_code == 200
    assert account_after_reset.json()["account"]["username"] == updated_username


def test_nickname_migration_preserves_existing_account_data(monkeypatch, tmp_path):
    from app import database
    from app.config import settings

    database_path = tmp_path / "legacy-v3.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", database_path)
    monkeypatch.setattr(settings, "DATABASE_URL", "")

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY);
            INSERT INTO schema_migrations (version) VALUES (3);
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                google_sub TEXT,
                email TEXT,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO users (username, password_hash, first_name, last_name)
            VALUES ('existing-user', 'existing-hash', 'Ana', 'Garcia');
            """
        )

    database.init_db()

    account = database.get_user_account(1)
    assert account == {
        "id": 1,
        "username": "existing-user",
        "first_name": "Ana",
        "nickname": "",
    }
