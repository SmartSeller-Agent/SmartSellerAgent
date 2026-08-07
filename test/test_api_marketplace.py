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
from src import user_profile
from src.login_job import LoginJob
from src.tools import marketplace


@pytest.fixture
def client():
    return TestClient(app_module.api)


@pytest.fixture(autouse=True)
def profile_file(monkeypatch, tmp_path):
    """Das echte Profil des Entwicklers darf in Tests nicht mitreden."""
    path = tmp_path / "profile.json"
    monkeypatch.setattr(user_profile, "PROFILE_FILE", path)
    return path


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    """Der Ausgang darf nicht davon abhängen, ob der Entwickler angemeldet ist.

    Sonst läuft eine echte `.state/kleinanzeigen_session.json` mit, und
    dieselben Tests verhalten sich in der CI anders als hier — ein grüner Lauf
    sagte dann nichts.
    """
    monkeypatch.setattr(marketplace, "SESSION_FILE", tmp_path / "kleinanzeigen_session.json")
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "")
    marketplace.record_session_verdict(marketplace.UNKNOWN, "")


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    path = tmp_path / "kleinanzeigen_session.json"
    monkeypatch.setattr(marketplace, "SESSION_FILE", path)
    return path


@pytest.fixture
def logged_in(session_file):
    """Eine gültige Anmeldung — sonst steht dem Einstellen etwas im Weg."""
    session_file.write_bytes(_session_bytes())
    return session_file


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
# Einstellungen des Anwenders
# --------------------------------------------------------------------------
def test_a_fresh_installation_is_reported_as_incomplete(client):
    """Daran erkennt die Oberfläche, dass sie nach den Angaben fragen muss."""
    body = client.get("/profile").json()

    assert body["complete"] is False
    assert body["zip_code"] == ""


def test_a_saved_profile_survives_and_is_readable(client):
    saved = client.put("/profile", json={"zip_code": "78462"})

    assert saved.status_code == 200
    assert client.get("/profile").json() == {
        "zip_code": "78462",
        "complete": True,
        "path": client.get("/profile").json()["path"],
    }


def test_surrounding_spaces_are_tolerated(client):
    client.put("/profile", json={"zip_code": "  78462  "})

    assert client.get("/profile").json()["zip_code"] == "78462"


def test_an_invalid_zip_code_is_refused_with_a_reason(client, profile_file):
    response = client.put("/profile", json={"zip_code": "784"})

    assert response.status_code == 400
    assert "fünfstellige" in response.json()["detail"]
    assert not profile_file.exists()


def test_discarding_the_session_clears_the_state(client, session_file):
    session_file.write_bytes(_session_bytes())

    body = client.delete("/marketplace/session").json()

    assert body["exists"] is False
    assert not session_file.exists()
    assert client.get("/marketplace/session").json()["verdict"] == "unknown"


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
    # Der Aufzeichner ruft kein Tool auf — also gibt es auch nichts zu melden.
    assert body["publish_attempts"] == []


def test_the_response_says_what_the_tool_did_not_what_the_agent_claims(
    client, monkeypatch
):
    """Der Kern der Sache.

    Ein Agent hat schon gemeldet, eine Anzeige sei online, während das
    Veröffentlichen abgeschaltet und niemand angemeldet war. Deshalb hängt am
    Ergebnis ein Protokoll, das das Tool selbst geschrieben hat.
    """
    monkeypatch.setattr(marketplace, "publish_offer", lambda listing_arg, dry_run: ["ok"])

    class LyingOrchestrator:
        def run(self, task):
            marketplace.publish_listing(
                title="Spiegelschrank", description="gut erhalten", price=60
            )
            return "Ich habe die Anzeige erfolgreich veröffentlicht!"

    monkeypatch.setattr(app_module, "orchestrator", LyingOrchestrator())

    body = client.post("/run-task", json={"task_name": "margin_check"}).json()

    assert "veröffentlicht" in body["result"]  # so behauptet es das Modell
    assert [a["outcome"] for a in body["publish_attempts"]] == ["preview"]


def test_a_forgotten_publishing_step_is_made_up_for(client, monkeypatch, logged_in):
    """Der beobachtete Fall: Der Orchestrator verfing sich in Websuchen,
    erreichte sein Schrittlimit und behauptete in der erzwungenen
    Schlussantwort, die Anzeige sei eingestellt — beauftragt hatte er
    niemanden.

    Nachgeholt wird nur, wenn es überhaupt gehen kann, deshalb die Anmeldung.
    """
    monkeypatch.setattr(marketplace, "publish_offer", lambda listing_arg, dry_run: ["ok"])

    class ForgetfulOrchestrator:
        def run(self, task):
            return "## Titel\nRegal\n\n## Status\nDie Anzeige wurde eingestellt."

    beauftragt = {}

    class Publisher:
        def run(self, task):
            beauftragt["task"] = task
            marketplace.publish_listing(
                title="Regal", description="gut erhalten", price=20
            )
            return "PROBELAUF — die Anzeige wurde NICHT veröffentlicht."

    monkeypatch.setattr(app_module, "orchestrator", ForgetfulOrchestrator())
    monkeypatch.setattr(app_module, "publisher_agent", Publisher())

    body = client.post(
        "/run-task",
        json={"task_name": "create_and_publish_listing", "image_path": "/app/bild.jpg"},
    ).json()

    assert [a["outcome"] for a in body["publish_attempts"]] == ["preview"]
    assert "/app/bild.jpg" in beauftragt["task"]
    # Die Rückmeldung des Nachholers gehört in die Antwort, sonst widerspricht
    # der Text weiterhin dem, was passiert ist.
    assert "PROBELAUF" in body["result"]


def test_a_publishing_step_that_happened_is_not_repeated(client, monkeypatch):
    """Sonst entstünde eine zweite Anzeige — die lässt sich nicht zurücknehmen."""
    monkeypatch.setattr(marketplace, "publish_offer", lambda listing_arg, dry_run: ["ok"])

    class ThoroughOrchestrator:
        def run(self, task):
            marketplace.publish_listing(
                title="Regal", description="gut erhalten", price=20
            )
            return "fertig"

    monkeypatch.setattr(app_module, "orchestrator", ThoroughOrchestrator())
    monkeypatch.setattr(
        app_module,
        "publisher_agent",
        type("Nie", (), {"run": lambda self, task: pytest.fail("darf nicht laufen")})(),
    )

    body = client.post(
        "/run-task", json={"task_name": "create_and_publish_listing"}
    ).json()

    assert len(body["publish_attempts"]) == 1


def test_other_tasks_are_left_alone(client, monkeypatch):
    """margin_check soll nichts einstellen — auch nicht nachträglich."""
    monkeypatch.setattr(app_module, "orchestrator", _RecordingOrchestrator())
    monkeypatch.setattr(
        app_module,
        "publisher_agent",
        type("Nie", (), {"run": lambda self, task: pytest.fail("darf nicht laufen")})(),
    )

    body = client.post("/run-task", json={"task_name": "margin_check"}).json()

    assert body["publish_attempts"] == []


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


# --------------------------------------------------------------------------
# Ohne Anmeldung: der Text entsteht, mehr nicht — und das steht auch da
# --------------------------------------------------------------------------
def test_the_answer_says_why_only_the_text_came_out(client, monkeypatch):
    """Beobachtet: Der Lauf ohne Anmeldung ist gewollt und funktioniert.

    Die Auskunft danach war aber irreführend — sie klang nach einem
    vergessenen Arbeitsschritt, während schlicht niemand angemeldet war.
    """
    class Orchestrator:
        def run(self, task):
            return "## Titel\nRegal\n\n## Status\nDie Anzeige wurde eingestellt."

    monkeypatch.setattr(app_module, "orchestrator", Orchestrator())
    monkeypatch.setattr(
        app_module,
        "publisher_agent",
        type("Nie", (), {"run": lambda self, task: pytest.fail("darf nicht laufen")})(),
    )

    body = client.post(
        "/run-task", json={"task_name": "create_and_publish_listing"}
    ).json()

    # Der Text ist da und bleibt brauchbar.
    assert "Regal" in body["result"]
    # Und daneben steht der Grund, statt dass der Anwender ihn erraten muss.
    assert "anmelden" in body["publish_blocker"]


def test_a_hopeless_publishing_step_is_not_retried(client, monkeypatch):
    """Der zweite Anlauf endete am selben Hindernis und kostete eine
    Modellrunde — lokal sind das Minuten."""
    class Orchestrator:
        def run(self, task):
            return "fertiger Text"

    monkeypatch.setattr(app_module, "orchestrator", Orchestrator())
    monkeypatch.setattr(
        app_module,
        "publisher_agent",
        type("Nie", (), {"run": lambda self, task: pytest.fail("darf nicht laufen")})(),
    )

    body = client.post(
        "/run-task", json={"task_name": "create_and_publish_listing"}
    ).json()

    assert body["publish_attempts"] == []
    assert body["publish_blocker"] is not None


def test_nothing_is_blamed_when_everything_is_ready(client, monkeypatch, logged_in):
    class Orchestrator:
        def run(self, task):
            marketplace.publish_listing(
                title="Regal", description="gut erhalten", price=20
            )
            return "fertig"

    monkeypatch.setattr(marketplace, "publish_offer", lambda listing_arg, dry_run: ["ok"])
    monkeypatch.setattr(app_module, "orchestrator", Orchestrator())

    body = client.post(
        "/run-task", json={"task_name": "create_and_publish_listing"}
    ).json()

    assert body["publish_blocker"] is None
    assert [a["outcome"] for a in body["publish_attempts"]] == ["preview"]


def test_the_sidebar_learns_the_reason_before_a_run(client):
    """Ein Lauf dauert Minuten — die Enttäuschung danach ist vermeidbar."""
    body = client.get("/marketplace/session").json()

    assert "anmelden" in body["publish_blocker"]
