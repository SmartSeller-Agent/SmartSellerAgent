"""
Tests der HTTP-Schnittstelle für die Marktplatz-Anmeldung.

Das ist der Vertrag, auf den sich das Frontend verlässt. Ein Browser wird nie
gestartet: der Hintergrundlauf wird durch einen harmlosen Ersatz getauscht.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from src import app as app_module
from src.login_job import LoginJob
from src.tools import marketplace


@pytest.fixture
def client():
    return TestClient(app_module.api)


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    path = tmp_path / "kleinanzeigen_session.json"
    monkeypatch.setattr(marketplace, "SESSION_FILE", path)
    return path


def _session_bytes(expires_in=3600):
    return json.dumps(
        {"cookies": [{"name": "auth", "expires": time.time() + expires_in}], "origins": []}
    ).encode()


# --------------------------------------------------------------------------
# Stand der Anmeldung
# --------------------------------------------------------------------------
def test_session_endpoint_reports_a_missing_login(client, session_file):
    response = client.get("/marketplace/session")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["usable"] is False
    assert "Keine gespeicherte Anmeldung" in body["description"]


def test_session_endpoint_reports_a_valid_login(client, session_file):
    session_file.write_bytes(_session_bytes())

    body = client.get("/marketplace/session").json()

    assert body["usable"] is True
    assert body["saved_at"] is not None


# --------------------------------------------------------------------------
# Freigabe zum Veröffentlichen
# --------------------------------------------------------------------------
def test_session_endpoint_says_whether_publishing_is_allowed(
    client, session_file, monkeypatch
):
    """Damit die Oberfläche einen gesperrten Schalter erklären kann."""
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "false")
    assert client.get("/marketplace/session").json()["publishing_enabled"] is False

    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")
    assert client.get("/marketplace/session").json()["publishing_enabled"] is True


class _RecordingOrchestrator:
    """Merkt sich, was das Tool zum Zeitpunkt des Laufs gesehen hätte."""

    def __init__(self):
        self.dry_runs = []

    def run(self, task):
        self.dry_runs.append(marketplace.is_dry_run())
        return "fertige Anzeige"


def test_a_task_may_publish_only_when_it_asks(client, monkeypatch):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")
    orchestrator = _RecordingOrchestrator()
    monkeypatch.setattr(app_module, "orchestrator", orchestrator)

    client.post(
        "/run-task", json={"task_name": "margin_check", "allow_publish": True}
    )
    client.post("/run-task", json={"task_name": "margin_check"})

    # Erst mit Bitte, dann ohne — und ohne heisst Probelauf.
    assert orchestrator.dry_runs == [False, True]


def test_a_task_cannot_publish_against_the_installation(client, monkeypatch):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "false")
    orchestrator = _RecordingOrchestrator()
    monkeypatch.setattr(app_module, "orchestrator", orchestrator)

    body = client.post(
        "/run-task", json={"task_name": "margin_check", "allow_publish": True}
    ).json()

    assert orchestrator.dry_runs == [True]
    assert body["published"] is False


def test_the_permission_is_gone_once_the_request_is_over(client, monkeypatch):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")
    monkeypatch.setattr(app_module, "orchestrator", _RecordingOrchestrator())

    client.post("/run-task", json={"task_name": "margin_check", "allow_publish": True})

    assert marketplace.is_dry_run() is True


# --------------------------------------------------------------------------
# Die echte Prüfung — dafür muss ein Browser laufen
# --------------------------------------------------------------------------
def test_verify_confirms_a_session_the_server_still_accepts(
    client, session_file, monkeypatch
):
    session_file.write_bytes(_session_bytes())
    monkeypatch.setattr(
        marketplace, "verify_session_online", lambda: ["Angemeldet — die Sitzung ist gültig."]
    )

    body = client.post("/marketplace/session/verify").json()

    assert body["messages"] == ["Angemeldet — die Sitzung ist gültig."]
    assert body["session"]["usable"] is True


def test_verify_reports_a_session_the_server_has_dropped(
    client, session_file, monkeypatch
):
    """Der Fall, den die reine Dateiprüfung nicht sehen kann.

    Die Cookies sehen lokal noch gültig aus, der Anbieter hat die Sitzung aber
    verworfen — etwa nach einer Passwortänderung.
    """
    session_file.write_bytes(_session_bytes())

    def rejected():
        raise marketplace.SessionExpiredError("Die Website hat auf die Anmeldeseite umgeleitet")

    monkeypatch.setattr(marketplace, "verify_session_online", rejected)

    response = client.post("/marketplace/session/verify")

    assert response.status_code == 409
    assert "Anmeldeseite" in response.json()["detail"]


def test_verify_does_not_start_a_browser_without_a_session(
    client, session_file, monkeypatch
):
    monkeypatch.setattr(
        marketplace,
        "verify_session_online",
        lambda: pytest.fail("Ohne Anmeldedatei darf kein Browser starten"),
    )

    response = client.post("/marketplace/session/verify")

    assert response.status_code == 409


# --------------------------------------------------------------------------
# Anmeldung anstoßen
# --------------------------------------------------------------------------
@pytest.fixture
def visible_browser(monkeypatch):
    monkeypatch.setattr(marketplace, "HEADLESS", False)


def test_login_start_returns_immediately(client, monkeypatch, visible_browser):
    """Der Vorgang wartet minutenlang — die Antwort darf das nicht tun."""
    monkeypatch.setattr(
        app_module, "_login_job", LoginJob(lambda notify: notify("Bitte anmelden"))
    )

    response = client.post("/marketplace/login")

    assert response.status_code == 200
    assert response.json()["status"] in ("running", "done")


def test_login_start_is_refused_without_a_visible_browser(client, monkeypatch):
    """Headless gäbe es nichts zu bedienen — das soll der Aufrufer sofort erfahren."""
    monkeypatch.setattr(marketplace, "HEADLESS", True)
    monkeypatch.setattr(
        app_module,
        "_login_job",
        LoginJob(lambda notify: pytest.fail("Es darf kein Browser starten")),
    )

    response = client.post("/marketplace/login")

    assert response.status_code == 409
    assert "KLEINANZEIGEN_VNC" in response.json()["detail"]


def test_login_status_carries_the_messages_and_the_session(
    client, session_file, monkeypatch, visible_browser
):
    job = LoginJob(lambda notify: notify("Anmeldefenster geöffnet"))
    monkeypatch.setattr(app_module, "_login_job", job)

    client.post("/marketplace/login")
    job.join(timeout=5)

    body = client.get("/marketplace/login").json()

    assert body["status"] == "done"
    assert body["messages"] == ["Anmeldefenster geöffnet"]
    # Die Oberfläche braucht beides in einer Runde: Fortschritt und Ergebnis.
    assert body["session"]["exists"] is False


# --------------------------------------------------------------------------
# Rückfall: Anmeldung hochladen
# --------------------------------------------------------------------------
def test_import_endpoint_takes_over_a_valid_session(client, session_file):
    response = client.post(
        "/marketplace/session/import",
        files={"file": ("session.json", _session_bytes(), "application/json")},
    )

    assert response.status_code == 200
    assert response.json()["usable"] is True
    assert session_file.exists()


def test_import_endpoint_rejects_an_expired_session(client, session_file):
    response = client.post(
        "/marketplace/session/import",
        files={"file": ("alt.json", _session_bytes(expires_in=-10), "application/json")},
    )

    assert response.status_code == 400
    assert "keine gültigen Cookies" in response.json()["detail"]
    assert not session_file.exists()


def test_import_endpoint_rejects_something_that_is_not_a_session(client, session_file):
    response = client.post(
        "/marketplace/session/import",
        files={"file": ("urlaub.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )

    assert response.status_code == 400
    assert not session_file.exists()


def test_a_rejected_upload_leaves_the_existing_login_alone(client, session_file):
    """Das ist der wichtige Teil: kaputte Datei darf nichts kaputt machen."""
    session_file.write_bytes(_session_bytes())
    before = session_file.read_bytes()

    client.post(
        "/marketplace/session/import",
        files={"file": ("kaputt.json", b"kein json", "application/json")},
    )

    assert session_file.read_bytes() == before
