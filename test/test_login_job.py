"""
Tests für den Hintergrundlauf der Anmeldung.

Ohne Browser und ohne FastAPI: geprüft wird nur, dass ein langer Vorgang
beobachtbar bleibt und nicht doppelt startet.
"""
import threading

from src.login_job import DONE, FAILED, RUNNING, LoginJob


def test_a_finished_run_reports_its_messages():
    job = LoginJob(lambda notify: [notify("Bitte anmelden"), notify("Angemeldet")])

    job.start()
    job.join(timeout=5)

    state = job.snapshot()
    assert state.status == DONE
    assert state.messages == ["Bitte anmelden", "Angemeldet"]
    assert state.error is None
    assert state.finished_at is not None


def test_messages_are_visible_while_the_run_is_still_going():
    """Sonst sähe die Oberfläche fünf Minuten lang nichts."""
    reached = threading.Event()
    may_finish = threading.Event()

    def runner(notify):
        notify("Anmeldefenster geöffnet")
        reached.set()
        may_finish.wait(timeout=5)

    job = LoginJob(runner)
    job.start()
    assert reached.wait(timeout=5)

    running = job.snapshot()
    assert running.status == RUNNING
    assert running.messages == ["Anmeldefenster geöffnet"]

    may_finish.set()
    job.join(timeout=5)
    assert job.snapshot().status == DONE


def test_a_second_start_does_not_open_a_second_browser():
    """Zwei Läufe gleichzeitig schrieben am Ende in dieselbe Datei."""
    started = threading.Event()
    may_finish = threading.Event()
    runs = []

    def runner(notify):
        runs.append(1)
        started.set()
        may_finish.wait(timeout=5)

    job = LoginJob(runner)
    job.start()
    assert started.wait(timeout=5)

    again = job.start()

    assert again.running is True
    may_finish.set()
    job.join(timeout=5)
    assert runs == [1]


def test_a_failure_ends_the_run_instead_of_hanging_on_running():
    """Die Oberfläche darf nicht ewig 'läuft' anzeigen, wenn nichts mehr läuft."""
    def runner(notify):
        raise RuntimeError("Kein sichtbarer Browser")

    job = LoginJob(runner)
    job.start()
    job.join(timeout=5)

    state = job.snapshot()
    assert state.status == FAILED
    assert "Kein sichtbarer Browser" in state.error


def test_a_finished_run_can_be_started_again():
    """Nach einem Fehlschlag muss ein zweiter Versuch möglich sein."""
    job = LoginJob(lambda notify: notify("fertig"))

    job.start()
    job.join(timeout=5)
    job.start()
    job.join(timeout=5)

    assert job.snapshot().status == DONE
