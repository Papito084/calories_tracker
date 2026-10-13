from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(test_environment):
    from main import app

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
            "last_name": "García",
        },
    )
    assert update.status_code == 200
    assert update.json()["account"]["first_name"] == "Ana"
    assert update.json()["account"]["last_name"] == "García"

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
