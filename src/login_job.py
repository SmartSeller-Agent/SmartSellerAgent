"""
Hintergrundlauf für die manuelle Anmeldung bei kleinanzeigen.de.

Die Anmeldung wartet bis zu fünf Minuten darauf, dass ein Mensch sich im
sichtbaren Browser anmeldet — Captcha und Zwei-Faktor-Abfrage inbegriffen.
So lange kann keine HTTP-Anfrage offen bleiben, also läuft sie in einem
eigenen Thread und die Oberfläche fragt den Stand ab.

Bewusst getrennt von src/tools/marketplace.py: dort geht es um die Steuerung
des Browsers, hier nur darum, einen langen Vorgang beobachtbar zu machen.
"""
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, List, Optional

IDLE = "idle"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass(frozen=True)
class LoginState:
    """Momentaufnahme. Unveränderlich, damit Leser nichts halb Fertiges sehen."""

    status: str = IDLE
    messages: List[str] = field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def running(self) -> bool:
        return self.status == RUNNING

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "messages": list(self.messages),
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class LoginJob:
    """Führt die Anmeldung höchstens einmal gleichzeitig aus.

    Zwei parallele Anmeldungen wären schädlich, nicht nur unnötig: beide
    öffneten ein Browserfenster auf demselben Bildschirm und schrieben am Ende
    in dieselbe Datei.
    """

    def __init__(self, runner: Callable[..., List[str]]):
        self._runner = runner
        self._lock = threading.Lock()
        self._state = LoginState()
        self._thread: Optional[threading.Thread] = None

    def snapshot(self) -> LoginState:
        with self._lock:
            return self._state

    def start(self) -> LoginState:
        """Startet die Anmeldung, sofern nicht schon eine läuft.

        Gibt in beiden Fällen den aktuellen Stand zurück — der Aufrufer sieht
        an ``running``, ob sein Anstoß etwas bewirkt hat.
        """
        with self._lock:
            if self._state.running:
                return self._state

            self._state = LoginState(
                status=RUNNING, messages=[], started_at=datetime.now()
            )

        self._thread = threading.Thread(
            target=self._run, name="kleinanzeigen-login", daemon=True
        )
        self._thread.start()
        return self.snapshot()

    def _append(self, message: str) -> None:
        with self._lock:
            self._state = replace(
                self._state, messages=[*self._state.messages, message]
            )

    def _finish(self, status: str, error: Optional[str] = None) -> None:
        with self._lock:
            self._state = replace(
                self._state, status=status, error=error, finished_at=datetime.now()
            )

    def _run(self) -> None:
        try:
            self._runner(notify=self._append)
        except Exception as e:
            # Auch Fehler sind ein Ergebnis: die Oberfläche soll sie anzeigen,
            # nicht ewig "läuft" melden.
            self._finish(FAILED, error=str(e))
        else:
            self._finish(DONE)

    def join(self, timeout: Optional[float] = None) -> None:
        """Nur für Tests: auf das Ende des Laufs warten."""
        if self._thread:
            self._thread.join(timeout)
