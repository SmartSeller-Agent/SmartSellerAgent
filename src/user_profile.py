"""
Dauerhafte Einstellungen des Anwenders.

Liegt als profile.json neben der gespeicherten Anmeldung im Zustandsordner,
hat also dieselbe Lebensdauer: übersteht einen Neustart der Container und
verschwindet erst, wenn das Volume weggeräumt wird.

Hier gehört hinein, was die Anwendung über ihren Nutzer weiß und was ein
Sprachmodell nicht erraten kann oder soll. Die Postleitzahl ist der erste
Fall dieser Art — sie steht deshalb nicht in der Tool-Signatur.
"""
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import KLEINANZEIGEN_STATE_DIR

PROFILE_FILE = KLEINANZEIGEN_STATE_DIR / "profile.json"

_ZIP_PATTERN = re.compile(r"\d{5}")


@dataclass
class Profile:
    """Was der Anwender einmal angibt und danach ändern kann."""

    zip_code: str = ""

    @property
    def complete(self) -> bool:
        """Reicht das Profil, um eine Anzeige aufzugeben?"""
        return bool(_ZIP_PATTERN.fullmatch(self.zip_code))

    def problems(self) -> list:
        if not self.zip_code:
            return ["Postleitzahl fehlt."]
        if not _ZIP_PATTERN.fullmatch(self.zip_code):
            return [f"'{self.zip_code}' ist keine fünfstellige Postleitzahl."]
        return []


def load_profile() -> Profile:
    """Liest das Profil. Ein fehlendes oder kaputtes ergibt ein leeres.

    Bewusst ohne Fehler: ein unlesbares Profil darf die Anwendung nicht am
    Starten hindern — der Anwender wird ohnehin nach den Angaben gefragt,
    solange sie fehlen.
    """
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return Profile()

    if not isinstance(data, dict):
        return Profile()

    # Nur bekannte Felder übernehmen, damit eine ältere oder neuere Datei
    # nicht mit unerwarteten Schlüsseln hereinplatzt.
    return Profile(zip_code=str(data.get("zip_code", "")).strip())


def save_profile(profile: Profile) -> Profile:
    """Schreibt das Profil, nachdem es geprüft wurde."""
    problems = profile.problems()
    if problems:
        raise ValueError(" ".join(problems))

    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(
        json.dumps(asdict(profile), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return load_profile()


def profile_path() -> Path:
    """Der Ablageort — zum Anzeigen, und damit Tests ihn ersetzen können."""
    return PROFILE_FILE
