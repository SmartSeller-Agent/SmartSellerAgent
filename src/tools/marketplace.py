"""
Veröffentlichung einer Anzeige auf kleinanzeigen.de per Browser-Automatisierung.

Die Website bietet keine öffentliche API. Dieses Modul steuert deshalb einen
echten Browser (Playwright) durch das Anzeigenformular.

Aufbau — bewusst zweigeteilt:

  fill_offer_form(page, listing, dry_run)
      Reine Formularlogik. Arbeitet ausschließlich auf einem Playwright-
      ``page``-Objekt und ist damit ohne echten Browser testbar
      (siehe test/test_marketplace.py).

  publish_listing(...)
      Die @tool-Hülle für den Agenten: startet den Browser, lädt die
      gespeicherte Session und gibt ein Textergebnis zurück.

Warum die Sync-API und nicht async: smolagents ruft Tools synchron auf.
``playwright.sync_api`` darf nicht innerhalb eines laufenden Event-Loops
benutzt werden — das ist hier erfüllt, weil FastAPI den Endpoint
(``def run_agent_task``, kein ``async def``) in einem Worker-Thread ohne
Event-Loop ausführt.

Eigenheiten des Formulars, die den Ablauf bestimmen (per
scripts/inspect_offer_form.py ermittelt):

* Es baut sich schrittweise auf. Die Kategorievorschläge holt die Seite erst
  nach der Titeleingabe vom Server, und der Versand-Abschnitt existiert erst,
  wenn eine Kategorie gewählt ist. Die Reihenfolge unten ist deshalb nicht
  beliebig.
* Direkt nach dem Laden zieht die Seite einen gespeicherten Entwurf nach und
  überschreibt dabei frisch gesetzte Werte, ohne dass ``fill()`` einen Fehler
  meldet. Textfelder werden deshalb zurückgelesen und notfalls neu gesetzt.
* Kategorie- und Preistyp-Auswahl sind keine nativen Formularelemente. Der
  Preistyp ist ein Button mit Popup-Liste, die Kategorie eine Radiogruppe mit
  optisch verdeckten Inputs — geklickt wird darum immer das ``<label>``.
"""
import contextvars
import json
import os
import re
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

from smolagents import tool

from src.config import (
    KLEINANZEIGEN_BROWSER_ARGS,
    KLEINANZEIGEN_BROWSER_CDP,
    KLEINANZEIGEN_CONFIRM_TIMEOUT_MS,
    KLEINANZEIGEN_FIELD_TIMEOUT_MS,
    KLEINANZEIGEN_HEADLESS,
    KLEINANZEIGEN_LOCALE,
    KLEINANZEIGEN_LOGIN_TIMEOUT_S,
    KLEINANZEIGEN_NO_SANDBOX,
    KLEINANZEIGEN_READY_TIMEOUT_MS,
    KLEINANZEIGEN_SCREENSHOT_DIR,
    KLEINANZEIGEN_SECTION_TIMEOUT_MS,
    KLEINANZEIGEN_SESSION_FILE,
    KLEINANZEIGEN_SLOW_MO_MS,
    KLEINANZEIGEN_STATE_DIR,
    KLEINANZEIGEN_TIMEZONE,
)
from src.user_profile import load_profile

# Kurze Namen fürs Modul. Ein Alias statt eines zweiten Env-Zugriffs, damit die
# Auswertung von .env an genau einer Stelle passiert (src/config.py).
STATE_DIR = KLEINANZEIGEN_STATE_DIR
SESSION_FILE = KLEINANZEIGEN_SESSION_FILE
SCREENSHOT_DIR = KLEINANZEIGEN_SCREENSHOT_DIR
HEADLESS = KLEINANZEIGEN_HEADLESS
SLOW_MO_MS = KLEINANZEIGEN_SLOW_MO_MS
NO_SANDBOX = KLEINANZEIGEN_NO_SANDBOX
LOGIN_TIMEOUT_S = KLEINANZEIGEN_LOGIN_TIMEOUT_S
LOCALE = KLEINANZEIGEN_LOCALE
TIMEZONE = KLEINANZEIGEN_TIMEZONE
EXTRA_BROWSER_ARGS = KLEINANZEIGEN_BROWSER_ARGS
BROWSER_CDP = KLEINANZEIGEN_BROWSER_CDP
FIELD_TIMEOUT_MS = KLEINANZEIGEN_FIELD_TIMEOUT_MS
READY_TIMEOUT_MS = KLEINANZEIGEN_READY_TIMEOUT_MS
SECTION_TIMEOUT_MS = KLEINANZEIGEN_SECTION_TIMEOUT_MS
CONFIRM_TIMEOUT_MS = KLEINANZEIGEN_CONFIRM_TIMEOUT_MS

LOGIN_URL = "https://www.kleinanzeigen.de/m-einloggen.html"
OFFER_FORM_URL = "https://www.kleinanzeigen.de/p-anzeige-aufgeben-schritt2.html"
CONFIRM_URL_GLOB = "https://www.kleinanzeigen.de/p-anzeige-aufgeben-bestaetigung.html**"
MY_ADS_URL = "https://www.kleinanzeigen.de/m-meine-anzeigen.html"

# Ohne gültige Anmeldung leitet die Website auf die Anmeldung um. Das ist das
# verlässlichste Signal — verlässlicher als ein Selektor, der sich ändern kann.
#
# Zwei Adressen, weil /m-einloggen.html nur die Einstiegsseite ist: von dort
# geht es auf einen eigenen Anmeldedienst unter login.kleinanzeigen.de weiter.
# Nur auf den ersten Namen zu prüfen, ginge an genau der Seite vorbei, auf der
# man am Ende landet.
LOGIN_URL_MARKERS = ("m-einloggen", "login.kleinanzeigen.de")


def _is_login_page(url: str) -> bool:
    return any(marker in url for marker in LOGIN_URL_MARKERS)

# Titellänge laut Formular. Im ersten echten Testlauf gegenzuprüfen.
MAX_TITLE_LEN = 65

PRICE_TYPES = ("FIXED", "NEGOTIABLE", "GIVE_AWAY")
_PRICE_TYPE_LABELS = {
    "FIXED": "Festpreis",
    "NEGOTIABLE": "VB",
    "GIVE_AWAY": "Zu verschenken",
}


# --------------------------------------------------------------------------
# Anmeldung
# --------------------------------------------------------------------------
class SessionExpiredError(RuntimeError):
    """Die gespeicherte Anmeldung wird von der Website nicht mehr akzeptiert."""


class SessionMissingError(FileNotFoundError):
    """Es wurde noch nie eine Anmeldung gespeichert."""


@dataclass
class SessionStatus:
    """Was sich über die Anmeldung sagen lässt, ohne einen Browser zu starten."""

    path: Path
    exists: bool
    saved_at: Optional[datetime] = None
    live_cookies: int = 0
    expired_cookies: int = 0
    # Späteste Ablaufzeit aller noch gültigen Cookies. Eine Obergrenze, kein
    # Versprechen: welches Cookie die Anmeldung trägt, wissen wir nicht.
    latest_expiry: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def usable(self) -> bool:
        """Lohnt sich ein Versuch überhaupt?

        Nur eine Vorprüfung. Der Server kann eine Sitzung jederzeit verwerfen,
        auch wenn die Cookies lokal noch gültig aussehen.
        """
        return self.exists and self.error is None and self.live_cookies > 0

    def describe(self) -> str:
        if not self.exists:
            return f"Keine gespeicherte Anmeldung unter {self.path}."
        if self.error:
            return f"Anmeldedatei {self.path} ist unbrauchbar: {self.error}"

        saved = self.saved_at.strftime("%d.%m.%Y %H:%M") if self.saved_at else "unbekannt"
        lines = [
            f"Anmeldung gespeichert unter {self.path} (Stand {saved}).",
            f"Cookies: {self.live_cookies} gültig, {self.expired_cookies} abgelaufen.",
        ]
        if self.latest_expiry:
            lines.append(
                f"Spätestens gültig bis {self.latest_expiry.strftime('%d.%m.%Y %H:%M')}."
            )
        if not self.usable:
            lines.append("Alle dauerhaften Cookies sind abgelaufen — neu anmelden.")
        return " ".join(lines)


# Ergebnis der letzten echten Prüfung gegen den Anbieter.
#
# Die Datei allein sagt nur, dass Cookies noch nicht abgelaufen sind. Ob der
# Anbieter sie akzeptiert, weiß man erst nach einem Versuch — und dieses
# Wissen soll nicht sofort wieder verloren gehen, sonst zeigt die Oberfläche
# weiter "in Ordnung", obwohl die Prüfung eben abgelehnt wurde.
UNKNOWN = "unknown"
ACCEPTED = "accepted"
REJECTED = "rejected"


@dataclass(frozen=True)
class SessionVerdict:
    status: str = UNKNOWN
    detail: str = ""
    at: Optional[datetime] = None


_last_verdict = SessionVerdict()


def record_session_verdict(status: str, detail: str = "") -> None:
    global _last_verdict
    _last_verdict = SessionVerdict(status=status, detail=detail, at=datetime.now())


def last_session_verdict() -> SessionVerdict:
    return _last_verdict


def read_session_status(path: Optional[Path] = None) -> SessionStatus:
    """Liest die gespeicherte Anmeldung, ohne sie zu benutzen.

    Ein Playwright-storage_state ist eine JSON-Datei mit Cookies. Deren
    Ablaufzeiten verraten schon auf der Platte, ob ein Versuch aussichtslos
    ist — das spart einen Browserstart von mehreren Sekunden.
    """
    path = path or SESSION_FILE
    if not path.is_file():
        return SessionStatus(path=path, exists=False)

    saved_at = datetime.fromtimestamp(path.stat().st_mtime)
    try:
        cookies = json.loads(path.read_text(encoding="utf-8")).get("cookies", [])
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return SessionStatus(path=path, exists=True, saved_at=saved_at, error=str(e))

    now = time.time()
    # expires <= 0 kennzeichnet ein Sitzungscookie ohne festes Ablaufdatum;
    # über dessen Gültigkeit lässt sich hier nichts aussagen.
    expiries = [c.get("expires", -1) for c in cookies]
    live = [e for e in expiries if e > now]
    expired = [e for e in expiries if 0 < e <= now]

    return SessionStatus(
        path=path,
        exists=True,
        saved_at=saved_at,
        live_cookies=len(live),
        expired_cookies=len(expired),
        latest_expiry=datetime.fromtimestamp(max(live)) if live else None,
    )


def import_session(source: Path) -> SessionStatus:
    """Rückfall: übernimmt eine anderswo erzeugte Anmeldung.

    Der vorgesehene Weg ist login_interactive() im sichtbaren Browser. Er kann
    aber an Umständen scheitern, die nichts mit dem Code zu tun haben — etwa
    wenn der Anbieter den Adressbereich des Containers vorübergehend sperrt.
    Dann meldet man sich auf dem eigenen Rechner an und bringt nur das
    Ergebnis hierher.

    Geprüft wird vor dem Überschreiben, damit eine unbrauchbare Datei nicht
    eine noch funktionierende Anmeldung verdrängt.
    """
    candidate = read_session_status(Path(source))

    if not candidate.exists:
        raise SessionMissingError(f"Datei nicht gefunden: {source}")
    if candidate.error:
        raise ValueError(f"Datei ist keine gültige Anmeldung: {candidate.error}")
    if not candidate.usable:
        raise SessionExpiredError(
            f"Die Datei enthält keine gültigen Cookies mehr. {candidate.describe()}"
        )

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_bytes(Path(source).read_bytes())
    # Eine neue Datei ist ungeprüft — die Bewertung der alten gilt nicht weiter.
    record_session_verdict(UNKNOWN, "Übernommene Anmeldung ist noch ungeprüft.")
    return read_session_status()


def session_lives_in_browser() -> bool:
    """Trägt der Browser die Anmeldung selbst?

    Beim Browser auf dem Host ist das so: Sein Profil bleibt bestehen, die
    Anmeldung steckt darin. Eine Datei mit Sitzungsdaten wird dann nicht
    gebraucht — und ihr Fehlen ist kein Grund, das Veröffentlichen zu
    verweigern. Ob die Anmeldung wirklich trägt, zeigt ohnehin erst der
    Seitenaufruf.
    """
    return bool(BROWSER_CDP)


def discard_session() -> SessionStatus:
    """Wirft die gespeicherte Anmeldung weg.

    Bewusst nur auf ausdrückliche Anweisung und nicht automatisch, sobald eine
    Prüfung fehlschlägt: Eine Umleitung zur Anmeldeseite bedeutet nicht
    zwingend, dass die Sitzung ungültig ist — dieselbe Seite erscheint bei
    einer vorübergehenden Sperre des Adressbereichs oder einer Störung beim
    Anbieter. Das Löschen wäre unumkehrbar, die Diagnose ist es nicht.
    """
    SESSION_FILE.unlink(missing_ok=True)
    record_session_verdict(UNKNOWN, "Anmeldung wurde verworfen.")
    return read_session_status()


def require_session() -> SessionStatus:
    """Prüft vorab, damit nicht erst der Browser hochfährt und dann scheitert."""
    status = read_session_status()
    if not status.exists:
        raise SessionMissingError(
            f"{status.describe()} Bitte zuerst bei kleinanzeigen.de anmelden."
        )
    if not status.usable:
        raise SessionExpiredError(status.describe())
    return status


def _ensure_logged_in(page) -> None:
    """Nach dem Seitenaufruf prüfen, ob die Website die Sitzung akzeptiert hat.

    Kostet nichts extra — die Seite ist ohnehin geladen. Ohne diese Prüfung
    liefe der Ablauf in einen unverständlichen Timeout auf dem Titelfeld,
    weil auf der Loginseite schlicht kein Formular steht.
    """
    if _is_login_page(page.url):
        raise SessionExpiredError(
            "Die Website hat auf die Anmeldeseite umgeleitet — die gespeicherte "
            f"Anmeldung ({SESSION_FILE}) gilt nicht mehr. Bitte neu anmelden."
        )


# Freigabe für genau einen Auftrag. Bewusst *kein* Tool-Parameter: sonst
# entschiede das Sprachmodell darüber, ob eine öffentliche Anzeige entsteht.
#
# Ein ContextVar und keine schlichte Variable, weil FastAPI synchrone
# Endpunkte in einem Threadpool ausführt, dessen Threads wiederverwendet
# werden. Ohne sauberes Zurücksetzen könnte eine Freigabe in eine spätere,
# fremde Anfrage lecken.
_publish_allowed = contextvars.ContextVar("kleinanzeigen_publish_allowed", default=False)

# Was das Tool tatsächlich getan hat, mitgeschrieben vom Tool selbst.
#
# Der Grund: ein Sprachmodell darf nicht die einzige Quelle darüber sein, ob
# eine öffentliche Anzeige entstanden ist. Es kann sich irren oder das
# Ergebnis beschönigen — beobachtet und beides erlebt. Die Anwendung weiß es
# genau und soll es auch berichten.
_publish_records = contextvars.ContextVar("kleinanzeigen_publish_records", default=None)

# Mögliche Ausgänge eines Tool-Aufrufs.
PUBLISHED = "published"      # eine öffentliche Anzeige ist entstanden
PREVIEW = "preview"          # Formular ausgefüllt, nicht abgesendet
NOT_LOGGED_IN = "not_logged_in"
INVALID = "invalid"          # Angaben des Modells unbrauchbar
FAILED = "failed"


@contextmanager
def publishing_allowed(allowed: bool):
    """Rahmen für genau einen Auftrag.

    Gibt das Veröffentlichen frei oder eben nicht und beginnt ein frisches
    Protokoll der Tool-Aufrufe.
    """
    allowed_token = _publish_allowed.set(bool(allowed))
    records_token = _publish_records.set([])
    try:
        yield
    finally:
        _publish_allowed.reset(allowed_token)
        _publish_records.reset(records_token)


def publish_records() -> List[dict]:
    """Was innerhalb des laufenden Auftrags versucht wurde.

    Eine leere Liste heißt: das Tool wurde gar nicht aufgerufen. Behauptet der
    Agent dann trotzdem, er habe etwas eingestellt, ist das nachweislich falsch.
    """
    records = _publish_records.get()
    return list(records) if records is not None else []


def _record(outcome: str, detail: str = "") -> str:
    records = _publish_records.get()
    if records is not None:
        records.append({"outcome": outcome, "detail": detail})
    return outcome


def publishing_enabled() -> bool:
    """Erlaubt diese Installation das Veröffentlichen überhaupt?

    Der Schalter der Betreiberseite, gesetzt über die Umgebung. Er kann nur
    verbieten, nie anordnen — veröffentlicht wird ausschließlich, wenn
    zusätzlich ein Auftrag ausdrücklich darum bittet.
    """
    return os.getenv("KLEINANZEIGEN_ALLOW_PUBLISH", "").lower() in ("1", "true", "yes")


def is_dry_run() -> bool:
    """Soll nur ausgefüllt (True) oder auch veröffentlicht (False) werden?

    Veröffentlicht wird nur, wenn beide Schalter zustimmen: die Installation
    erlaubt es grundsätzlich, und dieser eine Auftrag verlangt es. Eine
    öffentliche Anzeige lässt sich nicht zurücknehmen — deshalb zwei Hände am
    Auslöser, und der sichere Fall ist der Standard.
    """
    return not (publishing_enabled() and _publish_allowed.get())


@dataclass
class Listing:
    """Die Felder des Anzeigenformulars."""

    title: str
    description: str
    price: float
    zip_code: str
    image_paths: List[str] = field(default_factory=list)
    price_type: str = "FIXED"
    shipping: bool = False
    # Freitext, der gegen die Kategorievorschläge der Seite abgeglichen wird,
    # z. B. "Badezimmer". Ohne Treffer wird der erste Vorschlag genommen.
    category_hint: str = ""
    # "Direkt kaufen" — nur relevant, wenn Versand aktiv ist. Nicht an den
    # Agenten durchgereicht: eine Kaufabwicklung ist nichts, was ein Modell
    # nebenbei einschalten sollte.
    direct_buy: bool = False

    def validate(self) -> List[str]:
        """Gibt alle Probleme zurück, statt beim ersten abzubrechen.

        Der Agent soll in einer Runde erfahren, was alles fehlt.
        """
        problems: List[str] = []

        if not self.title.strip():
            problems.append("Titel ist leer.")
        elif len(self.title) > MAX_TITLE_LEN:
            problems.append(
                f"Titel ist {len(self.title)} Zeichen lang, erlaubt sind {MAX_TITLE_LEN}."
            )

        if not self.description.strip():
            problems.append("Beschreibung ist leer.")

        if self.price < 0:
            problems.append("Preis darf nicht negativ sein.")

        # Leer ist erlaubt: dann bleibt stehen, was die Website aus dem
        # Kontoprofil vorbelegt hat.
        if self.zip_code and not re.fullmatch(r"\d{5}", self.zip_code):
            problems.append(f"PLZ '{self.zip_code}' ist keine fünfstellige Zahl.")

        if self.price_type not in PRICE_TYPES:
            problems.append(
                f"price_type '{self.price_type}' ist unbekannt, erlaubt: {', '.join(PRICE_TYPES)}."
            )

        for path in self.image_paths:
            if not Path(path).is_file():
                problems.append(f"Bilddatei nicht gefunden: {path}")

        return problems


# --------------------------------------------------------------------------
# Bausteine
# --------------------------------------------------------------------------
def _screenshot(page, name: str) -> None:
    """Screenshot als Beleg. Darf den Ablauf nie zum Scheitern bringen."""
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / name), full_page=True)
    except Exception:
        pass


def _await_ready(page) -> None:
    """Der Seite Zeit geben, bevor wir schreiben.

    Kurz nach dem Laden zieht die Seite einen gespeicherten Entwurf nach und
    überschreibt dabei alles, was schon im Formular steht. Solange die
    Hintergrundabfragen laufen, hält kein Wert. ``networkidle`` läuft hier oft
    in den Timeout (die Seite pollt dauernd) — das ist kein Fehler: dann hat
    sie die Zeit trotzdem gehabt.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=READY_TIMEOUT_MS)
    except Exception:
        pass


def _fill_verified(page, locator, value: str, what: str, attempts: int = 5) -> None:
    """Schreibt einen Wert und liest ihn zurück.

    ``fill()`` meldet nicht, wenn die Seite den Wert gleich wieder verwirft —
    er ist einfach weg. Die Wartezeit verdoppelt sich mit jedem Versuch
    (0,5 s bis 8 s), damit auch ein spät eintreffender Entwurf noch überholt
    wird. Feste kurze Abstände haben genau daran gescheitert.
    """
    wait_ms = 500
    for _ in range(attempts):
        locator.fill(value)
        page.wait_for_timeout(wait_ms)
        # Leerraum normalisiert die Seite selbst; das ist kein Verlust.
        if locator.input_value().strip() == value.strip():
            return
        wait_ms *= 2

    raise RuntimeError(
        f"{what} ließ sich in {attempts} Versuchen nicht setzen — die Seite "
        "überschreibt das Feld immer wieder. Mit KLEINANZEIGEN_READY_TIMEOUT_MS "
        "lässt sich die Wartezeit vor dem Ausfüllen erhöhen."
    )


def _verify_form_state(page, listing: Listing, log: List[str]) -> None:
    """Vor dem Absenden noch einmal alles gegenlesen.

    Ein Feld kann auch dann noch verworfen werden, wenn es beim Setzen
    stehengeblieben ist. Ohne diese Kontrolle ginge im schlechtesten Fall eine
    Anzeige ohne Titel online.
    """
    expected = {
        'input[id="ad-title"]': listing.title,
        'textarea[id="ad-description"]': listing.description,
    }
    if listing.zip_code:
        expected['input[id="ad-zip-code"]'] = listing.zip_code

    drifted = []
    for selector, want in expected.items():
        got = page.locator(selector).input_value()
        # Die Seite normalisiert Leerraum, das ist kein Abweichen.
        if got.strip() != want.strip():
            drifted.append(f"{selector} enthält {got!r} statt {want!r}")

    if listing.price_type != "GIVE_AWAY":
        got = page.locator('input[id="ad-price-amount"]').input_value()
        try:
            matches = float(got.replace(",", ".")) == listing.price
        except ValueError:
            matches = False
        if not matches:
            drifted.append(f"Preisfeld enthält {got!r} statt {listing.price:.0f}")

    if drifted:
        raise RuntimeError("Formular stimmt nicht mehr: " + "; ".join(drifted))

    log.append("Formularinhalt vor dem Absenden gegengelesen.")


def _check_radio(page, input_id: str) -> None:
    """Setzt ein Radio über sein <label>.

    Das Formular blendet die echten Inputs aus und zeichnet eigene Grafiken;
    ``check()`` scheitert daran. Anschließend wird geprüft, dass der Klick
    gewirkt hat.
    """
    radio = page.locator(f'input[type="radio"][id="{input_id}"]')
    if radio.is_checked():
        return

    label = page.locator(f'label[for="{input_id}"]')
    label.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
    label.click()

    if not radio.is_checked():
        raise RuntimeError(f"Radio '{input_id}' wurde geklickt, ist aber nicht gesetzt.")


# --------------------------------------------------------------------------
# Formularschritte
# --------------------------------------------------------------------------
def _accept_cookies(page, log: List[str]) -> None:
    try:
        page.click("#gdpr-banner-accept", timeout=FIELD_TIMEOUT_MS)
        log.append("Cookie-Banner akzeptiert.")
    except Exception:
        log.append("Kein Cookie-Banner vorhanden.")


def _select_ad_type_offer(page, log: List[str]) -> None:
    _check_radio(page, "ad-type-OFFER")
    log.append("Anzeigentyp 'Angebot' gewählt.")


def _fill_title(page, listing: Listing, log: List[str]):
    field_ = page.locator('input[id="ad-title"]')
    field_.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
    _fill_verified(page, field_, listing.title, "Titel")
    log.append(f"Titel gesetzt: {listing.title}")
    return field_


def _select_category(page, listing: Listing, log: List[str]) -> None:
    """Wählt eine der Kategorien, die die Seite aus dem Titel ableitet.

    Ohne Kategorie erscheinen die nachfolgenden Abschnitte (Versand,
    kategoriespezifische Merkmale) gar nicht erst. Die Radio-IDs sind hier die
    numerischen Kategorie-IDs von Kleinanzeigen, die Beschriftung steht im
    zugehörigen <label>.
    """
    picker = page.locator("#ad-category-picker")
    picker.wait_for(state="visible", timeout=SECTION_TIMEOUT_MS)

    options = picker.locator('input[type="radio"][name="category-suggestions"]')
    count = options.count()
    if count == 0:
        raise RuntimeError("Die Seite hat keine Kategorievorschläge geliefert.")

    choices = []
    for index in range(count):
        category_id = options.nth(index).get_attribute("id") or ""
        text = page.locator(f'label[for="{category_id}"]').inner_text().strip()
        choices.append((category_id, text))

    hint = listing.category_hint.strip().lower()
    match = next((c for c in choices if hint and hint in c[1].lower()), None)

    if match is None:
        match = choices[0]
        if hint:
            log.append(
                f"WARNUNG: Kein Vorschlag passt zu '{listing.category_hint}'. "
                f"Verfügbar: {', '.join(text for _, text in choices)}"
            )

    category_id, text = match
    _check_radio(page, category_id)
    log.append(f"Kategorie gewählt: {text} (ID {category_id})")


def _select_shipping(page, listing: Listing, log: List[str]) -> None:
    """Versand oder Abholung — der Abschnitt hängt an der Kategorie.

    Nicht jede Kategorie bietet Versand an. Fehlt der Abschnitt, ist das für
    'Nur Abholung' kein Problem; bei gewünschtem Versand aber schon.
    """
    try:
        page.locator("#ad-shipping-enabled").wait_for(
            state="visible", timeout=SECTION_TIMEOUT_MS
        )
    except Exception:
        message = "Diese Kategorie bietet keine Versandoption an"
        log.append(
            f"WARNUNG: {message} — Versand war aber gewünscht."
            if listing.shipping
            else f"{message}."
        )
        return

    # Achtung: 'Versand möglich' ist vorausgewählt. 'Nur Abholung' muss also
    # aktiv gesetzt werden, sonst geht die Anzeige mit Versand online.
    input_id = "ad-shipping-enabled-yes" if listing.shipping else "ad-shipping-enabled-no"
    label = "Versand möglich" if listing.shipping else "Nur Abholung"
    _check_radio(page, input_id)
    log.append(f"Versandoption '{label}' gewählt.")

    _select_direct_buy(page, listing, log)


def _select_direct_buy(page, listing: Listing, log: List[str]) -> None:
    """'Direkt kaufen' — erscheint nur zusammen mit aktivem Versand.

    Vorausgewählt ist nichts, das Formular verlangt aber eine Entscheidung.
    """
    if not page.locator("#ad-buy-now").is_visible():
        return

    input_id = "ad-buy-now-true" if listing.direct_buy else "ad-buy-now-false"
    try:
        _check_radio(page, input_id)
        log.append(f"'Direkt kaufen': {'ja' if listing.direct_buy else 'nein'}.")
    except Exception as e:
        log.append(f"WARNUNG: 'Direkt kaufen' konnte nicht gesetzt werden ({e}).")


def _fill_description(page, listing: Listing, log: List[str]) -> None:
    field_ = page.locator('textarea[id="ad-description"]')
    field_.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
    _fill_verified(page, field_, listing.description, "Beschreibung")
    log.append(f"Beschreibung gesetzt ({len(listing.description)} Zeichen).")


def _select_price_type(page, listing: Listing, log: List[str]) -> None:
    """Festpreis / VB / Zu verschenken.

    Kein <select>, sondern ein Button, der eine Liste aufklappt. Im
    Ursprungsskript fehlte dieser Schritt komplett — der Betrag wurde gesetzt,
    die Preisart blieb still auf 'Festpreis'.
    """
    wanted = _PRICE_TYPE_LABELS[listing.price_type]
    combo = page.locator("#ad-price-type")
    combo.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)

    if combo.inner_text().strip().startswith(wanted):
        log.append(f"Preisart steht bereits auf '{wanted}'.")
        return

    combo.click()
    menu = page.locator("#ad-price-type-menu")
    menu.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)

    options = menu.locator('li[role="option"]')
    for index in range(options.count()):
        option = options.nth(index)
        if option.inner_text().strip() == wanted:
            option.click()
            log.append(f"Preisart '{wanted}' gewählt.")
            return

    raise RuntimeError(
        f"Preisart '{wanted}' steht nicht zur Auswahl "
        f"(angeboten: {menu.inner_text().strip()!r})."
    )


def _fill_price(page, listing: Listing, log: List[str]) -> None:
    if listing.price_type == "GIVE_AWAY":
        log.append("Zu verschenken — kein Betrag einzutragen.")
        return

    field_ = page.locator('input[id="ad-price-amount"]')
    field_.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
    _fill_verified(page, field_, f"{listing.price:.0f}", "Preis")
    log.append(f"Preis gesetzt: {listing.price:.0f} €")


def _upload_images(page, listing: Listing, log: List[str]) -> None:
    if not listing.image_paths:
        log.append("Keine Bilder angegeben.")
        return

    file_input = page.locator('input[type="file"]')
    if file_input.count() == 0:
        log.append("WARNUNG: Kein Datei-Upload-Feld im Formular gefunden.")
        return

    file_input.first.set_input_files(listing.image_paths)
    page.wait_for_timeout(2000)  # Upload läuft asynchron im Hintergrund
    log.append(f"{len(listing.image_paths)} Bild(er) hochgeladen.")


def _fill_zip(page, listing: Listing, log: List[str]) -> None:
    if not listing.zip_code:
        log.append("Keine PLZ angegeben — die Vorbelegung aus dem Konto bleibt stehen.")
        return

    field_ = page.locator('input[id="ad-zip-code"]')
    field_.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
    _fill_verified(page, field_, listing.zip_code, "PLZ")
    log.append(f"PLZ gesetzt: {listing.zip_code}")


_SUBMIT_SELECTORS = (
    'button[type="submit"]:has-text("Anzeige aufgeben")',
    'button:has-text("Anzeige aufgeben")',
    'button:has-text("Veröffentlichen")',
)


def _submit(page, log: List[str]) -> None:
    for selector in _SUBMIT_SELECTORS:
        try:
            locator = page.locator(selector)
            locator.wait_for(state="visible", timeout=3000)
            if not locator.first.is_enabled():
                continue
            locator.first.click(timeout=FIELD_TIMEOUT_MS)
            log.append(f"Absenden geklickt ({selector}).")
            return
        except Exception:
            continue

    raise RuntimeError(
        f"Absenden-Button nicht gefunden. Screenshot: {SCREENSHOT_DIR / '99_error.png'}"
    )


def _confirm_without_images(page, log: List[str]) -> None:
    """Rückfrage 'ohne Bild veröffentlichen' wegklicken, falls sie erscheint."""
    try:
        dialog = page.locator("text=Keine Bilder hochgeladen")
        if dialog.is_visible(timeout=3000):
            page.click('button:has-text("Ohne Bild veröffentlichen")')
            log.append("Hinweis 'ohne Bild veröffentlichen' bestätigt.")
    except Exception:
        pass


def fill_offer_form(page, listing: Listing, dry_run: bool = True) -> List[str]:
    """Füllt das Anzeigenformular aus und sendet es ab, wenn dry_run False ist.

    Gibt das Protokoll als Liste von Zeilen zurück, statt zu drucken — der
    Aufrufer (das Tool) macht daraus den Rückgabewert für den Agenten.

    Die Reihenfolge folgt den Abhängigkeiten des Formulars: Titel schaltet die
    Kategorievorschläge frei, die Kategorie den Versand-Abschnitt.
    """
    log: List[str] = []

    page.goto(OFFER_FORM_URL)
    _ensure_logged_in(page)
    _accept_cookies(page, log)
    # Erst schreiben, wenn die Seite mit dem Nachladen fertig ist.
    _await_ready(page)
    _select_ad_type_offer(page, log)

    title_field = _fill_title(page, listing, log)
    # Erst der Fokusverlust stößt die Kategorieabfrage beim Server an.
    title_field.blur()

    _select_category(page, listing, log)
    _select_shipping(page, listing, log)

    _fill_description(page, listing, log)
    _select_price_type(page, listing, log)
    _fill_price(page, listing, log)
    _upload_images(page, listing, log)
    _fill_zip(page, listing, log)

    _verify_form_state(page, listing, log)
    _screenshot(page, "06_form_filled.png")

    if dry_run:
        log.append(
            "PROBELAUF: Formular ausgefüllt, aber NICHT abgesendet. "
            f"Kontrolle: {SCREENSHOT_DIR / '06_form_filled.png'}"
        )
        return log

    _submit(page, log)
    _confirm_without_images(page, log)

    try:
        page.wait_for_url(CONFIRM_URL_GLOB, timeout=CONFIRM_TIMEOUT_MS)
        log.append("Bestätigungsseite erreicht.")
    except Exception:
        # Nicht tödlich: die Anzeige kann trotzdem online sein.
        log.append("WARNUNG: Bestätigungsseite nicht erkannt — Screenshot prüfen.")

    _screenshot(page, "07_result.png")
    log.append(f"VERÖFFENTLICHT. URL: {page.url}")
    return log


# --------------------------------------------------------------------------
# Browser-Lebenszyklus
# --------------------------------------------------------------------------
def _cdp_endpoint(url: str) -> str:
    """Ersetzt den Hostnamen durch seine IP-Adresse.

    Chromium prüft bei DevTools-Anfragen den Host-Header und lässt nur
    ``localhost`` und IP-Adressen zu; alles andere quittiert es mit HTTP 500.
    Aus dem Container heraus heißt der Host aber ``host.docker.internal``.
    Statt den Anwender eine IP eintragen zu lassen, die sich beim nächsten
    Start von Docker ändern kann, lösen wir den Namen hier selbst auf.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host or host == "localhost":
        return url

    try:
        address = socket.gethostbyname(host)
    except OSError:
        # Auflösung fehlgeschlagen: unverändert weiterreichen, damit die
        # Fehlermeldung von Playwright kommt und nicht von hier.
        return url

    netloc = f"{address}:{parsed.port}" if parsed.port else address
    return urlunparse(parsed._replace(netloc=netloc))


def browser_reachable() -> Optional[bool]:
    """Läuft der Browser auf dem Host und nimmt Verbindungen an?

    ``None`` bedeutet: Die Frage stellt sich nicht, weil der Container seinen
    eigenen Browser startet.

    Nur ein Verbindungsversuch auf TCP-Ebene, keine Anfrage — das kostet
    Millisekunden und darf deshalb bei jedem Zeichnen der Oberfläche passieren.
    """
    if not BROWSER_CDP:
        return None

    parsed = urlparse(_cdp_endpoint(BROWSER_CDP))
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.5):
            return True
    except OSError:
        return False


def _context_options(use_session: bool) -> dict:
    """Einstellungen des Browserkontexts.

    Sprache und Zeitzone werden gesetzt, weil ein Container von sich aus keine
    hat: ein englischsprachiger Browser mit UTC auf einer deutschen Seite fällt
    auf. Auf dem Host ändert es nichts, dort stimmen die Werte ohnehin.
    """
    options = {
        "no_viewport": True,
        "locale": LOCALE,
        "timezone_id": TIMEZONE,
    }
    if use_session:
        options["storage_state"] = str(SESSION_FILE)
    return options


@contextmanager
def _browser_page(use_session: bool = True):
    """Browser, danach zuverlässig geschlossen.

    ``use_session=False`` startet mit einem leeren Profil — das ist der Fall
    für eine neue Anmeldung, bei der eine alte, ungültige Sitzung nur stören
    würde.
    """
    from playwright.sync_api import sync_playwright

    if BROWSER_CDP:
        with sync_playwright() as p:
            # Ein fremder Browser: wir hängen uns an, wir starten ihn nicht.
            browser = p.chromium.connect_over_cdp(_cdp_endpoint(BROWSER_CDP))

            # Den bestehenden Kontext benutzen, keinen neuen anlegen. Dort
            # sitzt die Anmeldung des Anwenders — mitsamt allem, was die
            # Website als bekanntes Gerät wiedererkennt. Ein frischer Kontext
            # wäre privat: keine Cookies, keine Wiedererkennung, und die Seite
            # verlangt eine Anmeldung, obwohl im Fenster daneben längst eine
            # besteht.
            borrowed = bool(browser.contexts)
            context = (
                browser.contexts[0]
                if borrowed
                else browser.new_context(**_context_options(use_session))
            )

            page = context.new_page()
            try:
                yield page
            finally:
                # Nur den eigenen Tab schließen. Kontext und Browser gehören
                # dem Anwender; sie zu schließen würde ihm sein Fenster unter
                # den Händen wegnehmen.
                try:
                    page.close()
                except Exception:
                    pass
                if not borrowed:
                    context.close()
        return

    args = [
        # Verhindert Berechtigungs-Blasen des Browsers über der Seite.
        "--disable-notifications",
        "--deny-permission-prompts",
        # Ohne das meldet der Browser navigator.webdriver = true. Das ist das
        # deutlichste Signal, an dem Schutzmechanismen einen ferngesteuerten
        # Browser erkennen — und der Grund, warum die Sicherheitsabfrage bei
        # der Anmeldung gar nicht erst zu Ende lädt. Gelöst wird die Abfrage
        # weiterhin von Hand; hier geht es nur darum, nicht vorab
        # aussortiert zu werden.
        "--disable-blink-features=AutomationControlled",
    ]
    if NO_SANDBOX:
        # Im Container startet Chromium sonst nicht: seine Sandbox verlangt
        # Rechte, die ein unprivilegierter Prozess dort nicht bekommt. Die
        # Abschottung übernimmt hier der Container.
        args += ["--no-sandbox", "--disable-setuid-sandbox"]

    # Zuletzt, damit sich Versuche über die Umgebung durchsetzen können.
    args += EXTRA_BROWSER_ARGS

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO_MS,
            args=args,
        )
        try:
            context = browser.new_context(**_context_options(use_session))
            yield context.new_page()
        finally:
            browser.close()


def publish_offer(listing: Listing, dry_run: bool = True) -> List[str]:
    """Startet den Browser mit gespeicherter Session und füllt das Formular."""
    # Trägt der Browser die Anmeldung selbst, gibt es keine Datei zu prüfen.
    # Fehlt die Anmeldung dort, meldet _ensure_logged_in() das gleich nach dem
    # ersten Seitenaufruf.
    if not session_lives_in_browser():
        require_session()

    with _browser_page() as page:
        try:
            return fill_offer_form(page, listing, dry_run=dry_run)
        except Exception:
            _screenshot(page, "99_error.png")
            raise


# Wie oft nachgesehen wird, ob die Anmeldung inzwischen durch ist.
_LOGIN_POLL_MS = 1000


def _has_logout_link(page) -> bool:
    """Den Abmelde-Link gibt es nur auf angemeldeten Seiten."""
    return page.locator("text=Ausloggen").count() > 0


def login_interactive(timeout_s: Optional[int] = None, notify=None) -> List[str]:
    """Öffnet die Anmeldeseite und wartet, bis sich ein Mensch angemeldet hat.

    Bewusst ohne Zugangsdaten: kleinanzeigen.de stellt bei automatisierten
    Anmeldungen Captcha und Zwei-Faktor-Abfragen, die kein Skript löst. Ein
    gespeichertes Passwort brächte deshalb nichts — es wäre nur ein weiteres
    Geheimnis, das irgendwo liegen müsste. Gespeichert wird am Ende allein der
    entstandene Sitzungszustand.

    Setzt einen sichtbaren Browser voraus. Im Container liefert den der
    virtuelle Bildschirm, den docker/entrypoint.sh startet.
    """
    timeout_s = timeout_s or LOGIN_TIMEOUT_S
    log: List[str] = []

    def say(message: str) -> None:
        log.append(message)
        if notify:
            notify(message)

    if HEADLESS:
        raise RuntimeError(
            "Die Anmeldung braucht einen sichtbaren Browser — headless gibt es "
            "nichts zu bedienen. Im Container: KLEINANZEIGEN_VNC=true und "
            "KLEINANZEIGEN_HEADLESS=false setzen (macht docker-compose bereits)."
        )

    with _browser_page(use_session=False) as page:
        page.goto(LOGIN_URL)
        try:
            page.click("#gdpr-banner-accept", timeout=FIELD_TIMEOUT_MS)
        except Exception:
            pass

        say(
            f"Bitte im Browserfenster anmelden. Es wird bis zu {timeout_s} Sekunden "
            "gewartet — Captcha und Zwei-Faktor-Abfrage gehören dazu."
        )

        # Über Runden statt Uhrzeit: so lässt sich der Ablauf testen, ohne
        # wirklich Minuten zu warten.
        for _ in range(max(1, timeout_s * 1000 // _LOGIN_POLL_MS)):
            if not _is_login_page(page.url) and _has_logout_link(page):
                SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                page.context.storage_state(path=str(SESSION_FILE))
                # Gerade eben mit eigenen Augen gesehen.
                record_session_verdict(ACCEPTED, "Soeben angemeldet.")
                say(f"Angemeldet. Sitzung gespeichert unter {SESSION_FILE}.")
                say(read_session_status().describe())
                return log
            page.wait_for_timeout(_LOGIN_POLL_MS)

        _screenshot(page, "11_login_timeout.png")

    raise TimeoutError(
        f"Innerhalb von {timeout_s} Sekunden kam keine Anmeldung zustande. "
        "Nichts gespeichert."
    )


def verify_session_online() -> List[str]:
    """Ruft eine geschützte Seite auf und schaut, ob die Anmeldung trägt.

    Die lokale Prüfung sieht nur Ablaufzeiten. Eine serverseitig verworfene
    Sitzung — nach Passwortwechsel oder Abmeldung auf einem anderen Gerät —
    fällt erst hier auf.
    """
    log: List[str] = []

    with _browser_page() as page:
        page.goto(MY_ADS_URL)
        if _is_login_page(page.url):
            _screenshot(page, "10_session_rejected.png")
            message = (
                "Die Website hat auf die Anmeldeseite umgeleitet — die Sitzung "
                "wird nicht mehr akzeptiert."
            )
            record_session_verdict(REJECTED, message)
            raise SessionExpiredError(message)

        _accept_cookies(page, log)

        if _has_logout_link(page):
            log.append("Angemeldet — die Sitzung ist gültig.")
            record_session_verdict(ACCEPTED, log[-1])
            return log

        _screenshot(page, "10_session_unclear.png")
        log.append(
            "Kein Abmelde-Link gefunden, aber auch keine Umleitung zur Anmeldung. "
            "Zustand unklar — bitte screenshots/10_session_unclear.png prüfen."
        )
        # Ausdrücklich nicht als "in Ordnung" verbuchen: unklar ist nicht gut.
        record_session_verdict(UNKNOWN, log[-1])
        return log


# --------------------------------------------------------------------------
# Tool-Hülle für den Agenten
# --------------------------------------------------------------------------
def _parse_image_paths(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


@tool
def check_marketplace_session() -> str:
    """
    Prüft, ob die gespeicherte Anmeldung bei kleinanzeigen.de noch gültig ist.

    Vor dem Veröffentlichen aufrufen. Ist die Anmeldung abgelaufen, muss sich
    ein Mensch neu anmelden — das kann kein Tool erledigen.
    """
    status = read_session_status()
    if not status.usable and not session_lives_in_browser():
        return f"Nicht angemeldet. {status.describe()}"

    try:
        log = verify_session_online()
    except SessionExpiredError as e:
        return f"Nicht angemeldet. {e}"
    except Exception as e:
        # Netzwerk- oder Browserproblem: sagt nichts über die Anmeldung aus.
        return f"Anmeldung konnte nicht geprüft werden: {e}"

    return f"{status.describe()}\n" + "\n".join(log)


@tool
def publish_listing(
    title: str,
    description: str,
    price: float,
    image_paths: Optional[str] = None,
    price_type: str = "FIXED",
    shipping: bool = False,
    category: Optional[str] = None,
) -> str:
    """
    Veröffentlicht eine fertige Verkaufsanzeige auf kleinanzeigen.de.

    Ob wirklich veröffentlicht oder nur ausgefüllt wird, entscheidet die
    Anwendung, nicht dieses Tool. Standard ist ein Probelauf ohne Veröffentlichung.

    Args:
        title: Überschrift der Anzeige, höchstens 65 Zeichen.
        description: Beschreibungstext der Anzeige, auf Deutsch.
        price: Preis in Euro. Bei price_type 'GIVE_AWAY' wird der Wert ignoriert.
        image_paths: Bilddateien, mehrere durch Komma getrennt. Leer lassen, wenn keine vorliegen.
        price_type: 'FIXED' für Festpreis, 'NEGOTIABLE' für Verhandlungsbasis, 'GIVE_AWAY' zum Verschenken.
        shipping: True, wenn Versand möglich ist, False für 'Nur Abholung'.
        category: Stichwort zur gewünschten Kategorie, zum Beispiel 'Badezimmer'. Die Website schlägt anhand des Titels Kategorien vor; passt keine, wird die erste genommen.
    """
    # Der Standort kommt aus dem Profil des Anwenders, nicht aus dem Modell:
    # seine Postleitzahl kann es nicht wissen und soll sie nicht raten.
    listing = Listing(
        title=title,
        description=description,
        price=price,
        zip_code=load_profile().zip_code,
        image_paths=_parse_image_paths(image_paths or ""),
        price_type=price_type,
        shipping=shipping,
        category_hint=category or "",
    )

    problems = listing.validate()
    if problems:
        # Als Text zurückgeben, nicht werfen: der Agent kann so nachbessern.
        detail = "\n- ".join(problems)
        _record(INVALID, detail)
        return f"Anzeige NICHT erstellt, bitte korrigieren:\n- {detail}"

    dry_run = is_dry_run()
    try:
        log = publish_offer(listing, dry_run=dry_run)
    except (SessionMissingError, SessionExpiredError) as e:
        # Eigener Zweig, weil hier ein Mensch handeln muss: erneut anmelden.
        # Ein Wiederholungsversuch des Agenten wäre sinnlos.
        record_session_verdict(REJECTED, str(e))
        _record(NOT_LOGGED_IN, str(e))
        return f"Anzeige NICHT erstellt: nicht angemeldet. {e}"
    except Exception as e:
        _record(FAILED, str(e))
        return f"Anzeige NICHT erstellt, Fehler beim Veröffentlichen: {e}"

    if dry_run:
        _record(PREVIEW)
        headline = (
            "PROBELAUF — die Anzeige wurde NICHT veröffentlicht. "
            "Das Formular wurde nur ausgefüllt."
        )
    else:
        _record(PUBLISHED)
        headline = "VERÖFFENTLICHT — die Anzeige ist jetzt öffentlich sichtbar."

    return f"{headline}\n" + "\n".join(log)


# --------------------------------------------------------------------------
# Manueller Testlauf: python -m src.tools.marketplace --help
# --------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kleinanzeige ausfüllen und optional veröffentlichen")
    parser.add_argument(
        "--login",
        action="store_true",
        help="Anmeldefenster öffnen und die Sitzung speichern (braucht einen sichtbaren Browser)",
    )
    parser.add_argument(
        "--import-session",
        metavar="DATEI",
        help="Rückfall: eine auf einem anderen Rechner erzeugte Anmeldung übernehmen",
    )
    parser.add_argument(
        "--check-session",
        action="store_true",
        help="Nur die gespeicherte Anmeldung prüfen, keine Anzeige anlegen",
    )
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--price", type=float)
    parser.add_argument("--zip", dest="zip_code")
    parser.add_argument("--images", default="", help="Pfade, durch Komma getrennt")
    parser.add_argument("--price-type", default="FIXED", choices=PRICE_TYPES)
    parser.add_argument("--category", default="", help="Stichwort, z. B. 'Badezimmer'")
    parser.add_argument("--shipping", action="store_true")
    # Kein --dry-run-Schalter, der stillschweigend überschrieben wird: das
    # Veröffentlichen muss man ausdrücklich verlangen.
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Anzeige wirklich veröffentlichen (ohne diesen Schalter nur ausfüllen)",
    )
    args = parser.parse_args()

    if args.login:
        # notify=print, damit man den Fortschritt sieht, während der Browser
        # noch offen ist — sonst käme die Ausgabe erst ganz am Ende.
        login_interactive(notify=print)
        return

    if args.import_session:
        print(import_session(Path(args.import_session)).describe())
        return

    if args.check_session:
        status = read_session_status()
        print(status.describe())
        if not status.usable:
            raise SystemExit(1)
        for line in verify_session_online():
            print(line)
        return

    # Nicht über required=True, sonst ließe sich --check-session nicht allein
    # aufrufen.
    missing = [
        name
        for name, value in (
            ("--title", args.title),
            ("--description", args.description),
            ("--price", args.price),
            ("--zip", args.zip_code),
        )
        if value is None
    ]
    if missing:
        parser.error(f"fehlende Angaben: {', '.join(missing)}")

    listing = Listing(
        title=args.title,
        description=args.description,
        price=args.price,
        zip_code=args.zip_code,
        image_paths=_parse_image_paths(args.images),
        price_type=args.price_type,
        shipping=args.shipping,
        category_hint=args.category,
    )

    problems = listing.validate()
    if problems:
        raise SystemExit("Ungültige Anzeige:\n- " + "\n- ".join(problems))

    if args.publish and not publishing_enabled():
        raise SystemExit(
            "Veröffentlichen ist in dieser Installation nicht freigegeben. "
            "Dafür KLEINANZEIGEN_ALLOW_PUBLISH=true setzen. --publish allein "
            "genügt bewusst nicht: eine öffentliche Anzeige lässt sich nicht "
            "zurücknehmen."
        )

    for line in publish_offer(listing, dry_run=not args.publish):
        print(line)


if __name__ == "__main__":
    main()
