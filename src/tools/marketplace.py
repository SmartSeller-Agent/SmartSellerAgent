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
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from smolagents import tool

# --- Konfiguration (wandert im nächsten Schritt nach src/config.py) ---
STATE_DIR = Path(os.getenv("KLEINANZEIGEN_STATE_DIR", ".state"))
SESSION_FILE = STATE_DIR / "kleinanzeigen_session.json"
SCREENSHOT_DIR = Path(os.getenv("KLEINANZEIGEN_SCREENSHOT_DIR", "screenshots"))

# Headless ist der Normalfall — im Container gibt es keinen X-Server. Für die
# manuelle Fehlersuche auf dem Host: KLEINANZEIGEN_HEADLESS=false
HEADLESS = os.getenv("KLEINANZEIGEN_HEADLESS", "true").lower() not in ("0", "false", "no")
SLOW_MO_MS = int(os.getenv("KLEINANZEIGEN_SLOW_MO_MS", "0"))

OFFER_FORM_URL = "https://www.kleinanzeigen.de/p-anzeige-aufgeben-schritt2.html"
CONFIRM_URL_GLOB = "https://www.kleinanzeigen.de/p-anzeige-aufgeben-bestaetigung.html**"

# Auf ein vorhandenes Feld warten wir kurz; auf serverseitig nachgeladene
# Abschnitte und auf die Bestätigungsseite deutlich länger.
FIELD_TIMEOUT_MS = int(os.getenv("KLEINANZEIGEN_FIELD_TIMEOUT_MS", "5000"))
SECTION_TIMEOUT_MS = int(os.getenv("KLEINANZEIGEN_SECTION_TIMEOUT_MS", "20000"))
CONFIRM_TIMEOUT_MS = int(os.getenv("KLEINANZEIGEN_CONFIRM_TIMEOUT_MS", "15000"))

# Titellänge laut Formular. Im ersten echten Testlauf gegenzuprüfen.
MAX_TITLE_LEN = 65

PRICE_TYPES = ("FIXED", "NEGOTIABLE", "GIVE_AWAY")
_PRICE_TYPE_LABELS = {
    "FIXED": "Festpreis",
    "NEGOTIABLE": "VB",
    "GIVE_AWAY": "Zu verschenken",
}


def is_dry_run() -> bool:
    """Soll nur ausgefüllt (True) oder auch veröffentlicht (False) werden?

    Bewusst *kein* Tool-Parameter: sonst entscheidet das Sprachmodell, ob eine
    öffentliche Anzeige entsteht. Bis der Schalter aus dem Frontend
    durchgereicht wird, steuert die Umgebung — und der Default ist der sichere
    Fall.
    """
    return os.getenv("KLEINANZEIGEN_ALLOW_PUBLISH", "").lower() not in ("1", "true", "yes")


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

        if not re.fullmatch(r"\d{5}", self.zip_code):
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


def _fill_verified(page, locator, value: str, what: str, attempts: int = 3) -> None:
    """Schreibt einen Wert und liest ihn zurück.

    Die Seite lädt kurz nach dem Öffnen einen Entwurf nach und überschreibt
    dabei bereits gesetzte Felder. ``fill()`` meldet das nicht — der Wert ist
    einfach wieder weg. Deshalb nachkontrollieren statt hoffen.
    """
    for _ in range(attempts):
        locator.fill(value)
        page.wait_for_timeout(500)
        if locator.input_value() == value:
            return
    raise RuntimeError(
        f"{what} ließ sich nach {attempts} Versuchen nicht setzen — "
        "die Seite überschreibt das Feld."
    )


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
    _accept_cookies(page, log)
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
def publish_offer(listing: Listing, dry_run: bool = True) -> List[str]:
    """Startet den Browser mit gespeicherter Session und füllt das Formular."""
    from playwright.sync_api import sync_playwright

    if not SESSION_FILE.is_file():
        raise FileNotFoundError(
            f"Keine gespeicherte Anmeldung unter {SESSION_FILE}. "
            "Bitte zuerst bei kleinanzeigen.de anmelden."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO_MS,
            # Verhindert Berechtigungs-Blasen des Browsers über der Seite.
            args=["--disable-notifications", "--deny-permission-prompts"],
        )
        context = browser.new_context(storage_state=str(SESSION_FILE), no_viewport=True)
        page = context.new_page()
        try:
            return fill_offer_form(page, listing, dry_run=dry_run)
        except Exception:
            _screenshot(page, "99_error.png")
            raise
        finally:
            browser.close()


# --------------------------------------------------------------------------
# Tool-Hülle für den Agenten
# --------------------------------------------------------------------------
def _parse_image_paths(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


@tool
def publish_listing(
    title: str,
    description: str,
    price: float,
    zip_code: str,
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
        zip_code: Fünfstellige Postleitzahl des Standorts, zum Beispiel '78462'.
        image_paths: Bilddateien, mehrere durch Komma getrennt. Leer lassen, wenn keine vorliegen.
        price_type: 'FIXED' für Festpreis, 'NEGOTIABLE' für Verhandlungsbasis, 'GIVE_AWAY' zum Verschenken.
        shipping: True, wenn Versand möglich ist, False für 'Nur Abholung'.
        category: Stichwort zur gewünschten Kategorie, zum Beispiel 'Badezimmer'. Die Website schlägt anhand des Titels Kategorien vor; passt keine, wird die erste genommen.
    """
    listing = Listing(
        title=title,
        description=description,
        price=price,
        zip_code=zip_code,
        image_paths=_parse_image_paths(image_paths or ""),
        price_type=price_type,
        shipping=shipping,
        category_hint=category or "",
    )

    problems = listing.validate()
    if problems:
        # Als Text zurückgeben, nicht werfen: der Agent kann so nachbessern.
        return "Anzeige nicht erstellt, bitte korrigieren:\n- " + "\n- ".join(problems)

    dry_run = is_dry_run()
    try:
        log = publish_offer(listing, dry_run=dry_run)
    except Exception as e:
        return f"Fehler beim Veröffentlichen: {e}"

    mode = "Probelauf (nicht veröffentlicht)" if dry_run else "Veröffentlichung"
    return f"{mode}\n" + "\n".join(log)


# --------------------------------------------------------------------------
# Manueller Testlauf: python -m src.tools.marketplace --help
# --------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kleinanzeige ausfüllen und optional veröffentlichen")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--price", type=float, required=True)
    parser.add_argument("--zip", dest="zip_code", required=True)
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

    for line in publish_offer(listing, dry_run=not args.publish):
        print(line)


if __name__ == "__main__":
    main()
