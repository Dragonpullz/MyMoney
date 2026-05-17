"""Smoke tests for the MyMoney Flask app.

Strategy: spin up the app with TestConfig (no auth, no CSRF), point it at a
temp cache, and assert every route returns a sensible response both when the
cache is empty and when it contains fixture data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mymoney import create_app


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app(tmp_path, monkeypatch):
    # Point the test app at a temp cache dir so we don't touch the real one.
    cache_dir = tmp_path / ".banksync-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("MYMONEY_ENV", "test")
    application = create_app("test")
    application.config["CACHE_DIR"] = cache_dir
    application.config["SUMMARY_PATH"] = cache_dir / "summary.json"
    application.config["NORMALIZED_PATH"] = cache_dir / "normalized.jsonl"
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def app_with_fixture(app):
    """App with a tiny but valid summary.json fixture loaded."""
    # Use the real default account ID from rules.json so headline_kpis() finds
    # this account (default_account_id() reads it at runtime).
    with app.app_context():
        from mymoney.data import default_account_id, invalidate_cache
        invalidate_cache()
        account_id = default_account_id()
    summary = {
        "accounts": {
            account_id: {
                "accountName": "House Checking",
                "monthly": {
                    "2026-04": {"spend": 1200.50, "income": 5000.0, "net": 3799.50},
                    "2026-05": {"spend": 950.25, "income": 5000.0, "net": 4049.75},
                },
            }
        }
    }
    app.config["SUMMARY_PATH"].write_text(json.dumps(summary), encoding="utf-8")
    # Also write empty normalized jsonl so subscriptions/anomalies don't error.
    app.config["NORMALIZED_PATH"].write_text("", encoding="utf-8")
    return app


# --- empty-cache smoke ------------------------------------------------------

EMPTY_OK_ROUTES = [
    "/",
    "/query",
    "/cashflow",
    "/budgets",
    "/subscriptions",
    "/anomalies",
    "/opportunities",
    "/projection",
    "/api/status",
    "/api/kpis",
    "/api/rules",
]


@pytest.mark.parametrize("path", EMPTY_OK_ROUTES)
def test_route_renders_with_empty_cache(client, path):
    response = client.get(path)
    assert response.status_code == 200, f"{path} returned {response.status_code}"


def test_report_route_missing_month(client):
    response = client.get("/report/2026-05")
    assert response.status_code == 200
    assert b"No report found" in response.data


def test_report_route_rejects_bad_month(client):
    response = client.get("/report/../../etc/passwd")
    assert response.status_code == 404


# --- security ---------------------------------------------------------------

def test_security_headers_present(client):
    response = client.get("/")
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in response.headers


def test_refresh_requires_post(client):
    response = client.get("/refresh")
    assert response.status_code in (404, 405)


def test_refresh_with_no_files_redirects(client):
    response = client.post("/refresh", data={})
    # No files -> flash + redirect to Home (302).
    assert response.status_code == 302


def test_refresh_rejects_non_json_upload(client):
    from io import BytesIO
    response = client.post(
        "/refresh",
        data={"dumps": (BytesIO(b"not json"), "evil.exe")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302  # flashes error, redirects home


def test_csrf_enforced_when_enabled(app):
    """When CSRF is on, POST without token must be rejected."""
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    response = client.post("/refresh", data={})
    assert response.status_code in (400, 403)


# --- with-fixture smoke -----------------------------------------------------

def test_home_renders_kpis_with_fixture(app_with_fixture):
    client = app_with_fixture.test_client()
    response = client.get("/")
    assert response.status_code == 200
    # Latest month from fixture.
    assert b"2026-05" in response.data


def test_api_kpis_returns_json(app_with_fixture):
    client = app_with_fixture.test_client()
    response = client.get("/api/kpis")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["month"] == "2026-05"
    assert payload["spend"] == 950.25
