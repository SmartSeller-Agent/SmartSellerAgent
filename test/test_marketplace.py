"""
Tests für die Kleinanzeigen-Formularlogik.

Es wird kein Browser gestartet: `fill_offer_form` arbeitet nur auf einem
`page`-Objekt, und das wird hier durch ein Double ersetzt. Damit laufen die
Tests ohne Netz, ohne Playwright-Binaries und ohne Account.

Das Double bildet die Eigenheiten nach, die das echte Formular hat und die uns
schon Fehlschläge eingebracht haben:
  * Kategorievorschläge erscheinen erst nach der Titeleingabe,
  * der Versand-Abschnitt erst nach der Kategoriewahl,
  * 'Versand möglich' ist vorausgewählt,
  * frisch gesetzte Textfelder können vom nachgeladenen Entwurf
    überschrieben werden.
"""
import json
import re
import time
from contextlib import contextmanager

import pytest

from src.tools import marketplace
from src.tools.marketplace import Listing, SessionExpiredError, SessionMissingError

DEFAULT_CATEGORIES = [
    ("91", "Haus & Garten → Badezimmer"),
    ("88", "Haus & Garten → Wohnzimmer → Schränke & Schrankwände"),
    ("87", "Haus & Garten → Weiteres Haus & Garten"),
]

# Radios derselben Gruppe schließen einander aus.
_RADIO_GROUPS = (
    ("ad-type-OFFER", "ad-type-WANTED"),
    ("ad-shipping-enabled-yes", "ad-shipping-enabled-no"),
    ("ad-buy-now-true", "ad-buy-now-false"),
)

_CATEGORY_OPTIONS = '#ad-category-picker input[type="radio"][name="category-suggestions"]'
_PRICE_OPTIONS = '#ad-price-type-menu li[role="option"]'
_PRICE_TYPE_ORDER = ("Festpreis", "VB", "Zu verschenken")


class FakeLocator:
    def __init__(self, page: "FakePage", selector: str):
        self.page = page
        self.selector = selector

    # -- Verkettung ------------------------------------------------------
    def locator(self, sub):
        return FakeLocator(self.page, f"{self.selector} {sub}")

    def nth(self, index):
        return FakeLocator(self.page, f"{self.selector}::nth({index})")

    @property
    def first(self):
        return self.nth(0) if self.selector in (_CATEGORY_OPTIONS, _PRICE_OPTIONS) else self

    # -- Abfragen --------------------------------------------------------
    def count(self):
        return self.page.count_of(self.selector)

    def inner_text(self):
        return self.page.text_of(self.selector)

    def input_value(self):
        return self.page.filled.get(self.selector, "")

    def get_attribute(self, name):
        return self.page.attribute_of(self.selector, name)

    def is_checked(self):
        target = self.page.id_in(self.selector)
        return bool(target) and target in self.page.checked

    def is_enabled(self):
        return True

    def is_visible(self, **_kwargs):
        return self.page.exists(self.selector)

    def wait_for(self, **_kwargs):
        if not self.page.exists(self.selector):
            raise TimeoutError(f"nicht sichtbar: {self.selector}")

    # -- Aktionen --------------------------------------------------------
    def fill(self, value):
        self.wait_for()
        remaining = self.page.overwrites.get(self.selector, 0)
        if remaining > 0:
            self.page.overwrites[self.selector] = remaining - 1
            self.page.filled[self.selector] = ""  # Entwurf überschreibt
            return
        self.page.filled[self.selector] = value

    def click(self, **_kwargs):
        self.wait_for()
        self.page.handle_click(self.selector)

    def check(self):
        self.wait_for()
        self.page.check_radio(self.page.id_in(self.selector) or self.selector)

    def blur(self):
        self.page.blurred.append(self.selector)

    def set_input_files(self, paths):
        self.page.uploaded = list(paths)


class FakePage:
    """Zeichnet auf, was das Formular getan hätte."""

    def __init__(
        self,
        categories=None,
        has_shipping=True,
        has_buy_now=True,
        missing=(),
        overwrites=None,
        logged_in=True,
        shows_logout_link=True,
    ):
        self.categories = DEFAULT_CATEGORIES if categories is None else list(categories)
        self.has_shipping = has_shipping
        self.has_buy_now = has_buy_now
        self.missing = set(missing)
        # Selektor -> wie oft der nachgeladene Entwurf das fill() noch verwirft.
        self.overwrites = dict(overwrites or {})
        # Ohne gültige Anmeldung leitet die Website auf die Loginseite um.
        self.logged_in = logged_in
        self.shows_logout_link = shows_logout_link

        self.filled = {}
        self.clicked = []
        self.blurred = []
        self.uploaded = []
        self.screenshots = []
        self.visited = []
        self.waited_for_url = []
        self.menu_open = False
        self.price_type = "Festpreis"
        # Vorbelegung wie im echten Formular.
        self.checked = {"ad-type-OFFER", "ad-shipping-enabled-yes"}
        self.url = "about:blank"
        self.confirm_url = (
            "https://www.kleinanzeigen.de/p-anzeige-aufgeben-bestaetigung.html?adId=1234"
        )

    # -- Auflösung -------------------------------------------------------
    @staticmethod
    def id_in(selector):
        match = re.search(r'\[for="([^"]+)"\]|id="([^"]+)"', selector)
        if not match:
            return None
        return match.group(1) or match.group(2)

    @staticmethod
    def _index_in(selector):
        match = re.search(r"::nth\((\d+)\)$", selector)
        return int(match.group(1)) if match else None

    def _known_ids(self):
        ids = {cat_id for cat_id, _ in self.categories}
        ids.update(("ad-type-OFFER", "ad-type-WANTED"))
        if self.has_shipping:
            ids.update(("ad-shipping-enabled-yes", "ad-shipping-enabled-no"))
            if self.has_buy_now:
                ids.update(("ad-buy-now-true", "ad-buy-now-false"))
        return ids

    def exists(self, selector):
        if selector in self.missing:
            return False
        if selector.startswith("text="):
            return False  # Dialoge nur, wenn ein Test sie ausdrücklich setzt
        if selector == "#ad-category-picker":
            return bool(self.categories)
        if selector == "#ad-shipping-enabled":
            return self.has_shipping
        if selector == "#ad-buy-now":
            return self.has_shipping and self.has_buy_now
        if selector.startswith("#ad-price-type-menu") or _PRICE_OPTIONS in selector:
            return self.menu_open
        element_id = self.id_in(selector)
        if element_id and ("label[for=" in selector or 'type="radio"' in selector):
            return element_id in self._known_ids()
        return True

    def count_of(self, selector):
        if selector.startswith(_CATEGORY_OPTIONS):
            return len(self.categories)
        if selector.startswith(_PRICE_OPTIONS):
            return len(_PRICE_TYPE_ORDER) if self.menu_open else 0
        if selector == "text=Ausloggen":
            return 1 if self.logged_in and self.shows_logout_link else 0
        return 0 if selector in self.missing else 1

    def text_of(self, selector):
        if selector == "#ad-price-type":
            return f"{self.price_type} Preistyp"
        if selector == "#ad-price-type-menu":
            return " ".join(_PRICE_TYPE_ORDER)
        index = self._index_in(selector)
        if selector.startswith(_PRICE_OPTIONS) and index is not None:
            return _PRICE_TYPE_ORDER[index]
        element_id = self.id_in(selector)
        for cat_id, text in self.categories:
            if cat_id == element_id:
                return text
        return ""

    def attribute_of(self, selector, name):
        index = self._index_in(selector)
        if selector.startswith(_CATEGORY_OPTIONS) and index is not None and name == "id":
            return self.categories[index][0]
        return None

    # -- Zustandsänderungen ----------------------------------------------
    def check_radio(self, element_id):
        for group in _RADIO_GROUPS:
            if element_id in group:
                self.checked.difference_update(group)
        if any(element_id == cat_id for cat_id, _ in self.categories):
            self.checked.difference_update(cat_id for cat_id, _ in self.categories)
        self.checked.add(element_id)

    def handle_click(self, selector):
        self.clicked.append(selector)

        if selector == "#ad-price-type":
            self.menu_open = True
            return

        index = self._index_in(selector)
        if selector.startswith(_PRICE_OPTIONS) and index is not None:
            self.price_type = _PRICE_TYPE_ORDER[index]
            self.menu_open = False
            return

        element_id = self.id_in(selector)
        if element_id:
            self.check_radio(element_id)

    # -- Playwright-Oberfläche -------------------------------------------
    def goto(self, url):
        self.visited.append(url)
        self.url = url if self.logged_in else "https://www.kleinanzeigen.de/m-einloggen.html"

    def locator(self, selector):
        return FakeLocator(self, selector)

    def click(self, selector, **_kwargs):
        self.locator(selector).click()

    def screenshot(self, path, **_kwargs):
        self.screenshots.append(path)

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_load_state(self, _state, **_kwargs):
        pass

    def wait_for_url(self, pattern, **_kwargs):
        self.waited_for_url.append(pattern)
        self.url = self.confirm_url


@pytest.fixture
def listing(tmp_path):
    image = tmp_path / "offer.jpg"
    image.write_bytes(b"fake-image")
    return Listing(
        title="Spiegelschrank | Badschrank",
        description="Sehr gut erhalten, Abholung in Konstanz.",
        price=60,
        zip_code="78462",
        image_paths=[str(image)],
    )


@pytest.fixture(autouse=True)
def no_screenshots_on_disk(monkeypatch, tmp_path):
    """Verhindert, dass die Tests screenshots/ im Projekt anlegen."""
    monkeypatch.setattr(marketplace, "SCREENSHOT_DIR", tmp_path / "screenshots")


# --------------------------------------------------------------------------
# Validierung
# --------------------------------------------------------------------------
def test_valid_listing_has_no_problems(listing):
    assert listing.validate() == []


def test_validate_reports_every_problem_at_once(tmp_path):
    """Der Agent soll in einer Runde alles erfahren, nicht Fehler für Fehler."""
    problems = Listing(
        title="",
        description="",
        price=-5,
        zip_code="784",
        price_type="CHEAP",
        image_paths=[str(tmp_path / "gibt-es-nicht.jpg")],
    ).validate()

    assert len(problems) == 6
    assert any("Titel ist leer" in p for p in problems)
    assert any("Beschreibung ist leer" in p for p in problems)
    assert any("negativ" in p for p in problems)
    assert any("PLZ" in p for p in problems)
    assert any("CHEAP" in p for p in problems)
    assert any("nicht gefunden" in p for p in problems)


def test_validate_rejects_overlong_title(listing):
    listing.title = "A" * (marketplace.MAX_TITLE_LEN + 1)

    problems = listing.validate()

    assert len(problems) == 1
    assert str(marketplace.MAX_TITLE_LEN) in problems[0]


# --------------------------------------------------------------------------
# Formularablauf
# --------------------------------------------------------------------------
def test_dry_run_fills_the_form_but_does_not_submit(listing):
    page = FakePage()

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.visited == [marketplace.OFFER_FORM_URL]
    assert page.filled['input[id="ad-title"]'] == listing.title
    assert page.filled['textarea[id="ad-description"]'] == listing.description
    assert page.filled['input[id="ad-price-amount"]'] == "60"
    assert page.filled['input[id="ad-zip-code"]'] == listing.zip_code
    assert page.uploaded == listing.image_paths
    # Der entscheidende Punkt: nichts abgeschickt, keine Bestätigungsseite.
    assert not any("Anzeige aufgeben" in sel for sel in page.clicked)
    assert page.waited_for_url == []
    assert any("PROBELAUF" in line for line in log)


def test_publish_run_submits_and_reports_the_url(listing):
    page = FakePage()

    log = marketplace.fill_offer_form(page, listing, dry_run=False)

    assert any("Anzeige aufgeben" in sel for sel in page.clicked)
    assert page.waited_for_url == [marketplace.CONFIRM_URL_GLOB]
    assert any("VERÖFFENTLICHT" in line for line in log)
    assert any(page.url in line for line in log)


# --------------------------------------------------------------------------
# Kategorie — schaltet alles Weitere frei
# --------------------------------------------------------------------------
def test_category_hint_picks_the_matching_suggestion(listing):
    listing.category_hint = "Badezimmer"
    page = FakePage()

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert "91" in page.checked
    assert any("Kategorie gewählt: Haus & Garten → Badezimmer" in line for line in log)


def test_category_hint_matches_a_later_suggestion(listing):
    """Der erste Vorschlag darf nicht einfach gewinnen."""
    listing.category_hint = "Schränke"
    page = FakePage()

    marketplace.fill_offer_form(page, listing, dry_run=True)

    assert "88" in page.checked
    assert "91" not in page.checked


def test_unmatched_hint_falls_back_to_the_first_suggestion_with_a_warning(listing):
    listing.category_hint = "Fahrrad"
    page = FakePage()

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert "91" in page.checked
    warning = next(line for line in log if line.startswith("WARNUNG"))
    assert "Fahrrad" in warning
    # Die Alternativen gehören ins Protokoll, sonst rät der Mensch beim Prüfen.
    assert "Badezimmer" in warning


def test_missing_category_suggestions_abort_the_run(listing):
    """Ohne Kategorie erscheinen Versand und Merkmale nie — weitermachen wäre sinnlos."""
    page = FakePage(categories=[])

    with pytest.raises(TimeoutError):
        marketplace.fill_offer_form(page, listing, dry_run=True)


def test_title_is_blurred_before_the_category_is_read(listing):
    """Erst der Fokusverlust stößt die Kategorieabfrage beim Server an."""
    page = FakePage()

    marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.blurred == ['input[id="ad-title"]']


# --------------------------------------------------------------------------
# Versand — 'Versand möglich' ist vorausgewählt
# --------------------------------------------------------------------------
def test_pickup_only_must_actively_deselect_shipping(listing):
    page = FakePage()
    assert "ad-shipping-enabled-yes" in page.checked  # Ausgangslage der Website

    marketplace.fill_offer_form(page, listing, dry_run=True)

    assert "ad-shipping-enabled-no" in page.checked
    assert "ad-shipping-enabled-yes" not in page.checked


def test_shipping_keeps_the_preselected_option_and_declines_direct_buy(listing):
    listing.shipping = True
    page = FakePage()

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert "ad-shipping-enabled-yes" in page.checked
    # Bei 'Direkt kaufen' ist nichts vorbelegt, das Formular verlangt aber eine
    # Entscheidung — und die darf nicht versehentlich 'ja' lauten.
    assert "ad-buy-now-false" in page.checked
    assert any("'Direkt kaufen': nein" in line for line in log)


def test_category_without_shipping_section_is_not_fatal(listing):
    page = FakePage(has_shipping=False)

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert any("keine Versandoption" in line for line in log)
    assert page.filled['input[id="ad-zip-code"]'] == listing.zip_code


def test_wanted_shipping_without_a_section_warns(listing):
    listing.shipping = True
    page = FakePage(has_shipping=False)

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert any(line.startswith("WARNUNG") and "Versand war aber gewünscht" in line for line in log)


# --------------------------------------------------------------------------
# Preisart — Button mit Popup-Liste, kein <select>
# --------------------------------------------------------------------------
def test_price_type_is_chosen_from_the_popup_list(listing):
    listing.price_type = "NEGOTIABLE"
    page = FakePage()

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.price_type == "VB"
    assert "#ad-price-type" in page.clicked
    assert any("Preisart 'VB' gewählt" in line for line in log)


def test_already_correct_price_type_does_not_open_the_list(listing):
    page = FakePage()  # steht bereits auf Festpreis

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert "#ad-price-type" not in page.clicked
    assert any("steht bereits auf 'Festpreis'" in line for line in log)


def test_give_away_skips_the_price_field(listing):
    listing.price_type = "GIVE_AWAY"
    page = FakePage()

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.price_type == "Zu verschenken"
    assert 'input[id="ad-price-amount"]' not in page.filled
    assert any("kein Betrag" in line for line in log)


# --------------------------------------------------------------------------
# Nachgeladener Entwurf überschreibt Felder
# --------------------------------------------------------------------------
def test_overwritten_field_is_written_again(listing):
    """Die Seite verwirft den ersten Wert stillschweigend — wir schreiben nach."""
    page = FakePage(overwrites={'input[id="ad-title"]': 1})

    marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.filled['input[id="ad-title"]'] == listing.title


def test_a_late_draft_is_still_outlasted(listing):
    """Der Auslöser des Fehlschlags: drei kurze Versuche reichten nicht.

    Vier Verwerfungen in Folge müssen überstanden werden — genau dafür wächst
    die Wartezeit zwischen den Versuchen.
    """
    page = FakePage(overwrites={'input[id="ad-title"]': 4})

    marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.filled['input[id="ad-title"]'] == listing.title


def test_permanently_overwritten_field_raises_instead_of_publishing_garbage(listing):
    page = FakePage(overwrites={'input[id="ad-title"]': 99})

    with pytest.raises(RuntimeError, match="Titel ließ sich"):
        marketplace.fill_offer_form(page, listing, dry_run=True)


def test_a_field_lost_after_being_set_is_caught_before_submitting(listing, monkeypatch):
    """Sonst ginge im schlechtesten Fall eine Anzeige ohne Titel online."""
    page = FakePage()
    original = marketplace._fill_zip

    def wipe_title_while_filling_zip(page_arg, listing_arg, log):
        original(page_arg, listing_arg, log)
        page_arg.filled['input[id="ad-title"]'] = ""

    monkeypatch.setattr(marketplace, "_fill_zip", wipe_title_while_filling_zip)

    with pytest.raises(RuntimeError, match="Formular stimmt nicht mehr"):
        marketplace.fill_offer_form(page, listing, dry_run=False)

    # Entscheidend: der Abbruch kommt VOR dem Absenden.
    assert not any("Anzeige aufgeben" in sel for sel in page.clicked)


def test_normalized_whitespace_is_not_treated_as_drift(listing, monkeypatch):
    """Die Seite trimmt Eingaben — das darf weder Wiederholungen noch Abbruch auslösen."""
    listing.description = "  Sehr gut erhalten.  "
    page = FakePage()
    monkeypatch.setattr(
        FakeLocator,
        "fill",
        lambda self, value: self.page.filled.__setitem__(self.selector, value.strip()),
    )

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert any("gegengelesen" in line for line in log)
    assert page.filled['textarea[id="ad-description"]'] == "Sehr gut erhalten."


def test_missing_submit_button_raises(listing):
    page = FakePage(missing=set(marketplace._SUBMIT_SELECTORS))

    with pytest.raises(RuntimeError, match="Absenden-Button nicht gefunden"):
        marketplace.fill_offer_form(page, listing, dry_run=False)


# --------------------------------------------------------------------------
# Tool-Hülle
# --------------------------------------------------------------------------
def test_tool_defaults_to_dry_run(monkeypatch, listing):
    """Ohne ausdrückliche Freigabe darf nichts veröffentlicht werden."""
    monkeypatch.delenv("KLEINANZEIGEN_ALLOW_PUBLISH", raising=False)
    seen = {}

    def fake_publish_offer(listing_arg, dry_run):
        seen["dry_run"] = dry_run
        return ["ok"]

    monkeypatch.setattr(marketplace, "publish_offer", fake_publish_offer)

    result = marketplace.publish_listing(
        title=listing.title,
        description=listing.description,
        price=listing.price,
        zip_code=listing.zip_code,
    )

    assert seen["dry_run"] is True
    assert "Probelauf" in result


def test_tool_publishes_only_when_explicitly_allowed(monkeypatch, listing):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")
    seen = {}

    def fake_publish_offer(listing_arg, dry_run):
        seen["dry_run"] = dry_run
        seen["images"] = listing_arg.image_paths
        seen["category"] = listing_arg.category_hint
        return ["ok"]

    monkeypatch.setattr(marketplace, "publish_offer", fake_publish_offer)

    result = marketplace.publish_listing(
        title=listing.title,
        description=listing.description,
        price=listing.price,
        zip_code=listing.zip_code,
        image_paths=f"{listing.image_paths[0]}, {listing.image_paths[0]}",
        category="Badezimmer",
    )

    assert seen["dry_run"] is False
    assert seen["images"] == [listing.image_paths[0], listing.image_paths[0]]
    assert seen["category"] == "Badezimmer"
    assert "Veröffentlichung" in result


def test_tool_returns_validation_problems_without_opening_a_browser(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("Browser darf bei ungültigen Daten nicht starten")

    monkeypatch.setattr(marketplace, "publish_offer", fail)

    result = marketplace.publish_listing(
        title="", description="x", price=1, zip_code="784"
    )

    assert "bitte korrigieren" in result
    assert "Titel ist leer" in result


# --------------------------------------------------------------------------
# Anmeldung — lokale Prüfung ohne Browser
# --------------------------------------------------------------------------
def _write_session(path, cookies):
    path.write_text(json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8")
    return path


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    path = tmp_path / "kleinanzeigen_session.json"
    monkeypatch.setattr(marketplace, "SESSION_FILE", path)
    return path


def test_missing_session_file_is_reported(session_file):
    status = marketplace.read_session_status()

    assert status.exists is False
    assert status.usable is False
    assert "Keine gespeicherte Anmeldung" in status.describe()


def test_damaged_session_file_is_reported_not_raised(session_file):
    """Eine kaputte Datei darf den Aufrufer nicht mit einem Stacktrace treffen."""
    session_file.write_text("{kein json", encoding="utf-8")

    status = marketplace.read_session_status()

    assert status.exists is True
    assert status.usable is False
    assert "unbrauchbar" in status.describe()


def test_expired_cookies_make_the_session_unusable(session_file):
    _write_session(session_file, [{"name": "auth", "expires": time.time() - 3600}])

    status = marketplace.read_session_status()

    assert status.expired_cookies == 1
    assert status.live_cookies == 0
    assert status.usable is False
    assert "abgelaufen" in status.describe()


def test_a_live_cookie_makes_the_session_worth_trying(session_file):
    later = time.time() + 7 * 24 * 3600
    _write_session(
        session_file,
        [
            {"name": "auth", "expires": later},
            {"name": "alt", "expires": time.time() - 10},
            # Sitzungscookie ohne Ablaufdatum — zählt in keine der Gruppen.
            {"name": "tmp", "expires": -1},
        ],
    )

    status = marketplace.read_session_status()

    assert status.live_cookies == 1
    assert status.expired_cookies == 1
    assert status.usable is True
    assert status.latest_expiry.timestamp() == pytest.approx(later)


def test_require_session_distinguishes_missing_from_expired(session_file):
    with pytest.raises(SessionMissingError):
        marketplace.require_session()

    _write_session(session_file, [{"name": "auth", "expires": time.time() - 1}])
    with pytest.raises(SessionExpiredError):
        marketplace.require_session()


# --------------------------------------------------------------------------
# Anmeldung — was der Browser sagt
# --------------------------------------------------------------------------
@pytest.fixture
def use_fake_browser(monkeypatch):
    def install(page):
        @contextmanager
        def fake_browser_page():
            yield page

        monkeypatch.setattr(marketplace, "_browser_page", fake_browser_page)
        return page

    return install


def test_redirect_to_login_aborts_the_form_immediately(listing):
    """Sonst liefe der Ablauf in einen Timeout auf dem Titelfeld."""
    page = FakePage(logged_in=False)

    with pytest.raises(SessionExpiredError, match="Anmeldeseite"):
        marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.filled == {}


def test_online_check_accepts_a_valid_session(use_fake_browser):
    page = use_fake_browser(FakePage())

    log = marketplace.verify_session_online()

    assert page.visited == [marketplace.MY_ADS_URL]
    assert any("Sitzung ist gültig" in line for line in log)


def test_online_check_detects_a_rejected_session(use_fake_browser):
    use_fake_browser(FakePage(logged_in=False))

    with pytest.raises(SessionExpiredError):
        marketplace.verify_session_online()


def test_online_check_admits_when_it_cannot_tell(use_fake_browser):
    """Kein Abmelde-Link, aber auch keine Umleitung — das ist kein 'gültig'."""
    page = use_fake_browser(FakePage(shows_logout_link=False))

    log = marketplace.verify_session_online()

    assert any("unklar" in line for line in log)
    assert any("10_session_unclear.png" in str(shot) for shot in page.screenshots)


def test_session_tool_does_not_start_a_browser_when_the_file_is_gone(
    session_file, monkeypatch
):
    monkeypatch.setattr(
        marketplace,
        "_browser_page",
        lambda: pytest.fail("Browser darf ohne Anmeldedatei nicht starten"),
    )

    result = marketplace.check_marketplace_session()

    assert result.startswith("Nicht angemeldet")


def test_session_tool_confirms_a_working_session(session_file, use_fake_browser):
    _write_session(session_file, [{"name": "auth", "expires": time.time() + 3600}])
    use_fake_browser(FakePage())

    result = marketplace.check_marketplace_session()

    assert "Sitzung ist gültig" in result
    assert "Cookies: 1 gültig" in result


# --------------------------------------------------------------------------
# Tool-Hülle: Anmeldefehler sind Handlungsanweisungen, keine Pannen
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "error",
    [
        SessionMissingError("Keine gespeicherte Anmeldung unter .state/session.json"),
        SessionExpiredError("Die Website hat auf die Anmeldeseite umgeleitet"),
    ],
)
def test_tool_reports_login_problems_as_something_a_human_must_fix(
    monkeypatch, listing, error
):
    """Ein Wiederholungsversuch des Agenten wäre sinnlos — das muss die Antwort sagen."""
    def fake_publish_offer(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(marketplace, "publish_offer", fake_publish_offer)

    result = marketplace.publish_listing(
        title=listing.title,
        description=listing.description,
        price=listing.price,
        zip_code=listing.zip_code,
    )

    assert result.startswith("Nicht angemeldet")
    assert str(error) in result
