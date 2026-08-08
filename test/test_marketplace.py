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
from pathlib import Path

import pytest

from src import user_profile
from src.tools import marketplace
from src.tools.marketplace import Listing, SessionExpiredError, SessionMissingError

@contextmanager
def _null_context():
    """Ersetzt _browser_page dort, wo die Seite selbst keine Rolle spielt."""
    yield FakePage()


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


class FakeContext:
    """Nur für storage_state — das ist alles, was der Anmeldeablauf braucht."""

    def __init__(self):
        self.saved_to = None

    def storage_state(self, path):
        self.saved_to = path
        Path(path).write_text(
            json.dumps(
                {"cookies": [{"name": "auth", "expires": time.time() + 3600}], "origins": []}
            ),
            encoding="utf-8",
        )


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
        completes_login_after=None,
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
        # Nach so vielen Warterunden hat der Mensch die Anmeldung abgeschlossen.
        # None heisst: er kommt nie zurueck.
        self.completes_login_after = completes_login_after
        self.polls = 0
        self.context = FakeContext()

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
        self._url = "about:blank"
        self.confirm_url = (
            "https://www.kleinanzeigen.de/p-anzeige-aufgeben-bestaetigung.html?adId=1234"
        )

    # -- Anmeldezustand --------------------------------------------------
    def _login_completed(self):
        return (
            self.completes_login_after is not None
            and self.polls >= self.completes_login_after
        )

    @property
    def url(self):
        # Nach erfolgreicher Anmeldung verlässt die Seite die Loginadresse.
        if marketplace._is_login_page(self._url) and self._login_completed():
            return marketplace.MY_ADS_URL
        return self._url

    @url.setter
    def url(self, value):
        self._url = value

    def _shows_logout(self):
        return (self.logged_in and self.shows_logout_link) or self._login_completed()

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
            return 1 if self._shows_logout() else 0
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
        # Ohne gültige Anmeldung landet man auf dem separaten Anmeldedienst,
        # nicht auf www.kleinanzeigen.de.
        self.url = url if self.logged_in else self.login_redirect

    login_redirect = "https://login.kleinanzeigen.de/u/login/identifier?state=abc"

    def locator(self, selector):
        return FakeLocator(self, selector)

    def click(self, selector, **_kwargs):
        self.locator(selector).click()

    def screenshot(self, path, **_kwargs):
        self.screenshots.append(path)

    def wait_for_timeout(self, _ms):
        self.polls += 1

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


@pytest.fixture(autouse=True)
def isolated_profile(monkeypatch, tmp_path):
    """Das echte Profil des Entwicklers darf in Tests nicht mitreden."""
    path = tmp_path / "profile.json"
    monkeypatch.setattr(user_profile, "PROFILE_FILE", path)
    return path


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
    )

    assert seen["dry_run"] is True
    assert result.startswith("PROBELAUF")


def test_tool_publishes_only_when_both_switches_agree(monkeypatch, listing):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")
    seen = {}

    def fake_publish_offer(listing_arg, dry_run):
        seen["dry_run"] = dry_run
        seen["images"] = listing_arg.image_paths
        seen["category"] = listing_arg.category_hint
        return ["ok"]

    monkeypatch.setattr(marketplace, "publish_offer", fake_publish_offer)

    with marketplace.publishing_allowed(True):
        result = marketplace.publish_listing(
            title=listing.title,
            description=listing.description,
            price=listing.price,
            image_paths=f"{listing.image_paths[0]}, {listing.image_paths[0]}",
            category="Badezimmer",
        )

    assert seen["dry_run"] is False
    assert seen["images"] == [listing.image_paths[0], listing.image_paths[0]]
    assert seen["category"] == "Badezimmer"
    assert result.startswith("VERÖFFENTLICHT")


def test_the_location_comes_from_the_profile_not_from_the_model(
    monkeypatch, listing, isolated_profile
):
    """Die PLZ des Anwenders kann ein Sprachmodell nicht wissen.

    Sie steht deshalb nicht in der Tool-Signatur — es gibt keinen Weg, sie
    falsch zu raten.
    """
    user_profile.save_profile(user_profile.Profile(zip_code="10115"))
    seen = {}

    def fake_publish_offer(listing_arg, dry_run):
        seen["zip"] = listing_arg.zip_code
        return ["ok"]

    monkeypatch.setattr(marketplace, "publish_offer", fake_publish_offer)

    marketplace.publish_listing(
        title=listing.title, description=listing.description, price=listing.price
    )

    assert seen["zip"] == "10115"
    # Das Modell bekommt das Feld gar nicht erst angeboten.
    assert "zip_code" not in marketplace.publish_listing.inputs


def test_without_a_profile_the_sites_own_prefill_is_left_alone(listing):
    """Ohne PLZ wird das Feld nicht angefasst statt den Lauf abzubrechen.

    Die Website belegt es aus dem Konto vor — das ist besser als nichts.
    """
    listing.zip_code = ""
    page = FakePage()

    assert listing.validate() == []

    log = marketplace.fill_offer_form(page, listing, dry_run=True)

    assert 'input[id="ad-zip-code"]' not in page.filled
    assert any("Vorbelegung aus dem Konto" in line for line in log)


# --------------------------------------------------------------------------
# Browser auf dem Host statt im Container
# --------------------------------------------------------------------------
def test_a_hostname_is_resolved_before_connecting(monkeypatch):
    """Chromium quittiert DevTools-Anfragen mit einem Namen im Host-Header
    mit HTTP 500 — erlaubt sind nur localhost und IP-Adressen."""
    monkeypatch.setattr(marketplace.socket, "gethostbyname", lambda host: "192.168.65.254")

    assert (
        marketplace._cdp_endpoint("http://host.docker.internal:9222")
        == "http://192.168.65.254:9222"
    )


def test_localhost_is_left_alone():
    assert marketplace._cdp_endpoint("http://localhost:9222") == "http://localhost:9222"


def test_an_address_that_is_already_numeric_survives_unchanged(monkeypatch):
    monkeypatch.setattr(marketplace.socket, "gethostbyname", lambda host: host)

    assert marketplace._cdp_endpoint("http://127.0.0.1:9222") == "http://127.0.0.1:9222"


def test_a_host_browser_carries_the_login_itself(monkeypatch):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")

    assert marketplace.session_lives_in_browser() is True


def test_publishing_needs_no_session_file_when_the_browser_has_one(
    monkeypatch, session_file, listing
):
    """Sonst verweigert die Anwendung die Arbeit, während im Fenster daneben
    das Konto offen steht."""
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(
        marketplace,
        "_browser_page",
        lambda use_session=True, keep_page_open=False: _null_context(),
    )
    reached = {}

    def fake_fill(page, listing_arg, dry_run):
        reached["yes"] = True
        return ["ok"]

    monkeypatch.setattr(marketplace, "fill_offer_form", fake_fill)

    # Keine Datei vorhanden — und trotzdem kein Abbruch.
    assert not session_file.exists()
    marketplace.publish_offer(listing, dry_run=True)

    assert reached == {"yes": True}


def test_publishing_still_demands_a_file_for_the_container_browser(
    monkeypatch, session_file, listing
):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "")

    with pytest.raises(SessionMissingError):
        marketplace.publish_offer(listing, dry_run=True)


@pytest.fixture
def watch_browser_page(monkeypatch):
    """Fängt ab, wie der Browser angefordert wird."""
    seen = {}

    @contextmanager
    def fake(use_session=True, keep_page_open=False):
        seen["keep_page_open"] = keep_page_open
        yield FakePage()

    monkeypatch.setattr(marketplace, "_browser_page", fake)
    monkeypatch.setattr(
        marketplace, "fill_offer_form", lambda page, listing, dry_run: ["ausgefüllt"]
    )
    return seen


def test_the_preview_stays_open_in_the_host_browser(
    monkeypatch, listing, watch_browser_page
):
    """Ein Screenshot ist ein schwacher Ersatz dafür, das Formular anzusehen."""
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")

    log = marketplace.publish_offer(listing, dry_run=True)

    assert watch_browser_page["keep_page_open"] is True
    assert any("bleibt im Browser stehen" in line for line in log)


def test_a_real_publication_leaves_no_tab_behind(
    monkeypatch, listing, watch_browser_page
):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")

    marketplace.publish_offer(listing, dry_run=False)

    assert watch_browser_page["keep_page_open"] is False


def test_the_container_browser_closes_its_tab(
    monkeypatch, listing, session_file, watch_browser_page
):
    """Dort wäre ein offener Tab wirkungslos — der Browser endet ohnehin."""
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "")
    _write_session(session_file, [{"name": "auth", "expires": time.time() + 3600}])

    marketplace.publish_offer(listing, dry_run=True)

    assert watch_browser_page["keep_page_open"] is False


def test_no_host_browser_configured_means_the_question_does_not_arise(monkeypatch):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "")

    assert marketplace.browser_reachable() is None


def test_a_running_host_browser_is_reported_as_reachable(monkeypatch):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(marketplace.socket, "gethostbyname", lambda host: "192.168.65.254")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(
        marketplace.socket, "create_connection", lambda address, timeout: FakeConnection()
    )

    assert marketplace.browser_reachable() is True


def test_a_stopped_host_browser_is_reported_instead_of_crashing(monkeypatch):
    """Die Oberfläche soll sagen können, was zu tun ist.

    Der Container kann den Browser nicht selbst starten — ein Programm auf dem
    Rechner des Anwenders zu starten ist genau das, was ein Container nicht
    darf.
    """
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(marketplace.socket, "gethostbyname", lambda host: "192.168.65.254")

    def refused(address, timeout):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(marketplace.socket, "create_connection", refused)

    assert marketplace.browser_reachable() is False


def test_an_unresolvable_name_is_passed_on_untouched(monkeypatch):
    """Dann soll die Fehlermeldung von Playwright kommen, nicht von uns."""
    def fails(host):
        raise OSError("Name or service not known")

    monkeypatch.setattr(marketplace.socket, "gethostbyname", fails)

    assert marketplace._cdp_endpoint("http://nirgends:9222") == "http://nirgends:9222"


# --------------------------------------------------------------------------
# Was wirklich passiert ist — nicht was das Modell erzählt
# --------------------------------------------------------------------------
def test_a_preview_is_recorded_as_a_preview(monkeypatch, listing):
    monkeypatch.setattr(marketplace, "publish_offer", lambda listing_arg, dry_run: ["ok"])

    with marketplace.publishing_allowed(False):
        result = marketplace.publish_listing(
            title=listing.title, description=listing.description, price=listing.price
        )
        records = marketplace.publish_records()

    assert [r["outcome"] for r in records] == [marketplace.PREVIEW]
    # Auch der Text an den Agenten muss eindeutig sein.
    assert result.startswith("PROBELAUF")


def test_a_real_publication_is_recorded_as_one(monkeypatch, listing):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")
    monkeypatch.setattr(marketplace, "publish_offer", lambda listing_arg, dry_run: ["ok"])

    with marketplace.publishing_allowed(True):
        result = marketplace.publish_listing(
            title=listing.title, description=listing.description, price=listing.price
        )
        records = marketplace.publish_records()

    assert [r["outcome"] for r in records] == [marketplace.PUBLISHED]
    assert result.startswith("VERÖFFENTLICHT")


def test_nothing_recorded_means_the_tool_was_never_called():
    """Der Fall, in dem ein Agent behauptet, er habe etwas eingestellt.

    Die leere Liste ist der Gegenbeweis, mit dem die Oberfläche widersprechen
    kann.
    """
    with marketplace.publishing_allowed(True):
        assert marketplace.publish_records() == []


def test_a_missing_login_is_recorded_and_not_dressed_up(monkeypatch, listing):
    def rejected(listing_arg, dry_run):
        raise SessionExpiredError("Sitzung wird nicht mehr akzeptiert")

    monkeypatch.setattr(marketplace, "publish_offer", rejected)

    with marketplace.publishing_allowed(True):
        result = marketplace.publish_listing(
            title=listing.title, description=listing.description, price=listing.price
        )
        records = marketplace.publish_records()

    assert [r["outcome"] for r in records] == [marketplace.NOT_LOGGED_IN]
    assert result.startswith("Anzeige NICHT erstellt")
    # Und die Ablehnung merkt sich die Anwendung für die Anzeige im Frontend.
    assert marketplace.last_session_verdict().status == marketplace.REJECTED


def test_unusable_input_is_recorded_without_starting_a_browser(monkeypatch):
    monkeypatch.setattr(
        marketplace,
        "publish_offer",
        lambda *_a, **_k: pytest.fail("Browser darf nicht starten"),
    )

    with marketplace.publishing_allowed(True):
        marketplace.publish_listing(title="", description="", price=1)
        records = marketplace.publish_records()

    assert [r["outcome"] for r in records] == [marketplace.INVALID]


def test_the_record_does_not_survive_the_request(monkeypatch, listing):
    monkeypatch.setattr(marketplace, "publish_offer", lambda listing_arg, dry_run: ["ok"])

    with marketplace.publishing_allowed(False):
        marketplace.publish_listing(
            title=listing.title, description=listing.description, price=listing.price
        )

    # Ausserhalb des Rahmens gibt es nichts mehr zu berichten — sonst zeigte
    # der nächste Auftrag das Ergebnis des vorherigen.
    assert marketplace.publish_records() == []


# --------------------------------------------------------------------------
# Gedächtnis für die letzte echte Anmeldeprüfung
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def forget_previous_verdict():
    marketplace.record_session_verdict(marketplace.UNKNOWN, "")


def test_a_successful_check_is_remembered(use_fake_browser):
    use_fake_browser(FakePage())

    marketplace.verify_session_online()

    assert marketplace.last_session_verdict().status == marketplace.ACCEPTED


def test_a_rejected_check_is_remembered(use_fake_browser):
    """Ohne das zeigte die Oberfläche weiter grün, direkt nach der Absage."""
    use_fake_browser(FakePage(logged_in=False))

    with pytest.raises(SessionExpiredError):
        marketplace.verify_session_online()

    verdict = marketplace.last_session_verdict()
    assert verdict.status == marketplace.REJECTED
    assert verdict.at is not None


def test_an_unclear_check_is_not_counted_as_good(use_fake_browser):
    use_fake_browser(FakePage(shows_logout_link=False))

    marketplace.verify_session_online()

    assert marketplace.last_session_verdict().status == marketplace.UNKNOWN


def test_a_rejected_check_does_not_delete_anything(session_file, use_fake_browser):
    """Löschen wäre unumkehrbar, die Diagnose ist es nicht.

    Eine Umleitung zur Anmeldeseite erscheint auch bei gesperrter Adresse oder
    einer Störung beim Anbieter — dann wäre eine intakte Anmeldung weg.
    """
    _write_session(session_file, [{"name": "auth", "expires": time.time() + 3600}])
    use_fake_browser(FakePage(logged_in=False))

    with pytest.raises(SessionExpiredError):
        marketplace.verify_session_online()

    assert session_file.exists()


def test_discarding_is_explicit_and_forgets_the_verdict(session_file):
    _write_session(session_file, [{"name": "auth", "expires": time.time() + 3600}])
    marketplace.record_session_verdict(marketplace.REJECTED, "abgelehnt")

    status = marketplace.discard_session()

    assert not session_file.exists()
    assert status.exists is False
    assert marketplace.last_session_verdict().status == marketplace.UNKNOWN


def test_discarding_a_session_that_is_not_there_is_harmless(session_file):
    assert marketplace.discard_session().exists is False


def test_an_imported_session_starts_out_unchecked(session_file, tmp_path):
    """Die Bewertung der alten Datei darf nicht auf die neue abfärben."""
    marketplace.record_session_verdict(marketplace.ACCEPTED, "alte Sitzung war gut")
    source = _write_session(
        tmp_path / "neu.json", [{"name": "auth", "expires": time.time() + 3600}]
    )

    marketplace.import_session(source)

    assert marketplace.last_session_verdict().status == marketplace.UNKNOWN


# --------------------------------------------------------------------------
# Zwei Hände am Auslöser
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "installation_allows, task_asks, expected_dry_run",
    [
        (False, False, True),
        # Die Installation erlaubt es, aber niemand hat darum gebeten.
        (True, False, True),
        # Jemand bittet darum, die Installation verbietet es — die Bitte
        # allein darf nichts auslösen.
        (False, True, True),
        (True, True, False),
    ],
)
def test_publishing_needs_both_switches(
    monkeypatch, installation_allows, task_asks, expected_dry_run
):
    monkeypatch.setenv(
        "KLEINANZEIGEN_ALLOW_PUBLISH", "true" if installation_allows else "false"
    )

    with marketplace.publishing_allowed(task_asks):
        assert marketplace.is_dry_run() is expected_dry_run


def test_the_permission_ends_with_the_block(monkeypatch):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")

    with marketplace.publishing_allowed(True):
        assert marketplace.is_dry_run() is False

    assert marketplace.is_dry_run() is True


def test_a_failed_run_still_gives_the_permission_back(monkeypatch):
    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")

    with pytest.raises(RuntimeError):
        with marketplace.publishing_allowed(True):
            raise RuntimeError("Anzeige fehlgeschlagen")

    assert marketplace.is_dry_run() is True


def test_the_permission_does_not_leak_into_the_next_request(monkeypatch):
    """FastAPI führt synchrone Endpunkte in wiederverwendeten Threads aus.

    Ohne sauberes Zurücksetzen könnte ein Auftrag mit Freigabe einem späteren,
    fremden Auftrag im selben Thread das Veröffentlichen erlauben.
    """
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("KLEINANZEIGEN_ALLOW_PUBLISH", "true")

    def request(asks_for_it):
        with marketplace.publishing_allowed(asks_for_it):
            pass
        return marketplace.is_dry_run()

    # max_workers=1 erzwingt, dass beide Aufträge denselben Thread benutzen.
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(request, True).result() is True
        assert pool.submit(request, False).result() is True


def test_tool_returns_validation_problems_without_opening_a_browser(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("Browser darf bei ungültigen Daten nicht starten")

    monkeypatch.setattr(marketplace, "publish_offer", fail)

    result = marketplace.publish_listing(title="", description="x", price=1)

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
    """Ersetzt den Browser und merkt sich, wie er angefordert wurde."""
    calls = []

    def install(page):
        @contextmanager
        def fake_browser_page(use_session=True, keep_page_open=False):
            calls.append(use_session)
            yield page

        monkeypatch.setattr(marketplace, "_browser_page", fake_browser_page)
        page.browser_calls = calls
        return page

    return install


def test_redirect_to_login_aborts_the_form_immediately(listing):
    """Sonst liefe der Ablauf in einen Timeout auf dem Titelfeld."""
    page = FakePage(logged_in=False)

    with pytest.raises(SessionExpiredError, match="Anmeldeseite"):
        marketplace.fill_offer_form(page, listing, dry_run=True)

    assert page.filled == {}


@pytest.mark.parametrize(
    "url",
    [
        "https://www.kleinanzeigen.de/m-einloggen.html",
        # Der eigentliche Anmeldedienst liegt auf einer anderen Domain — nur
        # auf den ersten Namen zu prüfen, ginge daran vorbei.
        "https://login.kleinanzeigen.de/u/login/identifier?state=hKFo2SBKbTl",
    ],
)
def test_both_login_addresses_count_as_not_logged_in(url):
    assert marketplace._is_login_page(url) is True


def test_the_offer_form_is_not_mistaken_for_a_login_page():
    assert marketplace._is_login_page(marketplace.OFFER_FORM_URL) is False


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
# Rückfall: Anmeldung von anderswo übernehmen
# --------------------------------------------------------------------------
def test_import_takes_over_a_valid_session(session_file, tmp_path):
    source = _write_session(
        tmp_path / "von-woanders.json", [{"name": "auth", "expires": time.time() + 3600}]
    )

    status = marketplace.import_session(source)

    assert status.usable is True
    assert session_file.read_bytes() == source.read_bytes()


def test_import_refuses_an_expired_file_without_touching_the_current_one(
    session_file, tmp_path
):
    """Eine tote Datei darf keine noch funktionierende Anmeldung verdrängen."""
    _write_session(session_file, [{"name": "auth", "expires": time.time() + 3600}])
    before = session_file.read_bytes()
    source = _write_session(
        tmp_path / "alt.json", [{"name": "auth", "expires": time.time() - 1}]
    )

    with pytest.raises(SessionExpiredError):
        marketplace.import_session(source)

    assert session_file.read_bytes() == before


def test_import_refuses_a_file_that_is_not_a_session(session_file, tmp_path):
    source = tmp_path / "urlaubsfoto.json"
    source.write_text("kein json", encoding="utf-8")

    with pytest.raises(ValueError, match="keine gültige Anmeldung"):
        marketplace.import_session(source)

    assert not session_file.exists()


def test_import_reports_a_missing_file(session_file, tmp_path):
    with pytest.raises(SessionMissingError):
        marketplace.import_session(tmp_path / "gibt-es-nicht.json")


# --------------------------------------------------------------------------
# Anmelden — manuell, weil Captcha und 2FA kein Skript lösen kann
# --------------------------------------------------------------------------
@pytest.fixture
def visible_browser(monkeypatch):
    """Ohne sichtbaren Browser lehnt die Anmeldung ab — hier tun wir so."""
    monkeypatch.setattr(marketplace, "HEADLESS", False)


def test_login_saves_the_session_once_the_user_is_done(
    session_file, use_fake_browser, visible_browser
):
    page = use_fake_browser(
        FakePage(logged_in=False, completes_login_after=2)
    )

    log = marketplace.login_interactive(timeout_s=10)

    assert page.visited == [marketplace.LOGIN_URL]
    assert page.context.saved_to == str(session_file)
    assert marketplace.read_session_status().usable is True
    assert any("Sitzung gespeichert" in line for line in log)


def test_login_starts_from_a_clean_profile(session_file, use_fake_browser, visible_browser):
    """Eine alte, ungültige Sitzung würde die neue Anmeldung nur stören."""
    page = use_fake_browser(FakePage(logged_in=False, completes_login_after=1))

    marketplace.login_interactive(timeout_s=10)

    assert page.browser_calls == [False]


def test_login_gives_up_without_saving_anything(
    session_file, use_fake_browser, visible_browser
):
    # completes_login_after=None: der Mensch kommt nie zurück.
    use_fake_browser(FakePage(logged_in=False))

    with pytest.raises(TimeoutError, match="Nichts gespeichert"):
        marketplace.login_interactive(timeout_s=3)

    assert not session_file.exists()


def test_login_refuses_when_there_is_nothing_to_look_at(monkeypatch, use_fake_browser):
    """Headless würde fünf Minuten auf eine Eingabe warten, die niemand machen kann."""
    monkeypatch.setattr(marketplace, "HEADLESS", True)
    use_fake_browser(FakePage())

    with pytest.raises(RuntimeError, match="sichtbaren Browser"):
        marketplace.login_interactive(timeout_s=10)


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
    )

    # Die erste Zeile sagt unmissverständlich, dass nichts entstanden ist —
    # der publisher_agent gibt genau sie wörtlich weiter.
    assert result.startswith("Anzeige NICHT erstellt")
    assert str(error) in result


# --------------------------------------------------------------------------
# Vorab: kann überhaupt eine Anzeige entstehen?
# --------------------------------------------------------------------------
# Beobachtet: Ohne Anmeldung lief der Auftrag durch und lieferte den fertigen
# Anzeigentext, aber die Oberfläche meldete nur, der Agent habe das Tool nicht
# aufgerufen. Das klingt nach einem Fehler und ist doch der Normalfall — es
# fehlte schlicht der Browser oder die Anmeldung.
def test_a_stopped_browser_is_named_as_the_reason(monkeypatch):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(marketplace, "browser_reachable", lambda: False)

    blocker = marketplace.publish_blocker()

    assert blocker is not None
    # Der Anwender muss erfahren, was er tun kann.
    assert "scripts.host_browser" in blocker


def test_a_missing_login_is_named_as_the_reason(monkeypatch, session_file):
    """Im Container trägt die Datei die Anmeldung — fehlt sie, fehlt sie."""
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "")

    blocker = marketplace.publish_blocker()

    assert blocker is not None
    assert "anmelden" in blocker


def test_a_rejected_login_is_named_as_the_reason(monkeypatch):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(marketplace, "browser_reachable", lambda: True)
    marketplace.record_session_verdict(marketplace.REJECTED, "abgelehnt")

    assert marketplace.publish_blocker() is not None


def test_nothing_stands_in_the_way_when_the_browser_carries_the_login(monkeypatch):
    """Die Datei sagt beim Browser mit eigenem Profil nichts aus.

    Ihr Fehlen darf deshalb kein Hinderungsgrund sein — sonst meldete die
    Oberfläche ein Problem, während im Fenster daneben das Konto offen steht.
    """
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(marketplace, "browser_reachable", lambda: True)

    assert marketplace.publish_blocker() is None


def test_the_check_does_not_open_a_page(monkeypatch, session_file):
    """Sie läuft bei jedem Zeichnen der Oberfläche — sie muss billig bleiben."""
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "")
    monkeypatch.setattr(
        marketplace,
        "_browser_page",
        lambda *_a, **_k: pytest.fail("Für diese Auskunft darf kein Browser starten"),
    )

    marketplace.publish_blocker()


# --------------------------------------------------------------------------
# Der fehlende Browser als eigener Fall
# --------------------------------------------------------------------------
def test_a_stopped_browser_is_reported_in_words_instead_of_a_refused_socket(monkeypatch):
    """Playwright meldet 'connect ECONNREFUSED 192.168.65.254:9222'.

    Das steht sonst als Begründung im Frontend und sagt niemandem, was zu tun ist.
    """
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(marketplace, "browser_reachable", lambda: False)

    with pytest.raises(marketplace.BrowserUnavailableError, match="host_browser"):
        with marketplace._browser_page():
            pytest.fail("Es darf gar nicht erst verbunden werden")


def test_the_publish_tool_records_a_missing_browser_separately(monkeypatch, listing):
    """Nicht als Anmeldeproblem: Die Anmeldung kann tadellos sein."""
    def no_browser(*_args, **_kwargs):
        raise marketplace.BrowserUnavailableError(marketplace.BROWSER_MISSING_HINT)

    monkeypatch.setattr(marketplace, "publish_offer", no_browser)

    with marketplace.publishing_allowed(True):
        result = marketplace.publish_listing(
            title=listing.title, description=listing.description, price=listing.price
        )
        records = marketplace.publish_records()

    assert [r["outcome"] for r in records] == [marketplace.NO_BROWSER]
    assert result.startswith("Anzeige NICHT erstellt")
    # Und die Anmeldung wird dabei nicht in Verruf gebracht.
    assert marketplace.last_session_verdict().status != marketplace.REJECTED


def test_the_session_check_writes_down_that_nobody_is_logged_in(monkeypatch, session_file):
    """Sonst bliebe das Protokoll leer, obwohl der Grund bekannt ist.

    Der publisher_agent bricht nach dieser Auskunft ab und ruft das
    Veröffentlichungs-Tool gar nicht mehr auf. Ohne Eintrag sähe der Lauf aus
    wie einer, in dem der Agent den Schritt schlicht vergessen hat.
    """
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "")

    with marketplace.publishing_allowed(True):
        answer = marketplace.check_marketplace_session()
        records = marketplace.publish_records()

    assert answer.startswith("Nicht angemeldet")
    assert [r["outcome"] for r in records] == [marketplace.NOT_LOGGED_IN]


def test_the_session_check_writes_down_a_missing_browser(monkeypatch, session_file):
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    monkeypatch.setattr(marketplace, "browser_reachable", lambda: False)

    def no_browser():
        raise marketplace.BrowserUnavailableError(marketplace.BROWSER_MISSING_HINT)

    monkeypatch.setattr(marketplace, "verify_session_online", no_browser)

    with marketplace.publishing_allowed(True):
        answer = marketplace.check_marketplace_session()
        records = marketplace.publish_records()

    assert "host_browser" in answer
    assert [r["outcome"] for r in records] == [marketplace.NO_BROWSER]


def test_a_working_session_is_not_recorded_as_a_problem(session_file, use_fake_browser):
    """Das Protokoll sammelt Gründe, keine Routine."""
    _write_session(session_file, [{"name": "auth", "expires": time.time() + 3600}])
    use_fake_browser(FakePage())

    with marketplace.publishing_allowed(True):
        marketplace.check_marketplace_session()

        assert marketplace.publish_records() == []


def test_the_session_check_keeps_quiet_about_a_file_that_says_nothing(
    monkeypatch, session_file, use_fake_browser
):
    """Beobachtet: "Keine gespeicherte Anmeldung ..." gefolgt von "Angemeldet".

    Beim Browser mit eigenem Profil gibt es keine Datei, und ihr Fehlen ist
    keine Aussage über die Anmeldung. Der Agent gibt diese Meldung wörtlich
    weiter, also darf sie sich nicht selbst widersprechen.
    """
    monkeypatch.setattr(marketplace, "BROWSER_CDP", "http://host.docker.internal:9222")
    use_fake_browser(FakePage())

    answer = marketplace.check_marketplace_session()

    assert "Keine gespeicherte Anmeldung" not in answer
    assert "Sitzung ist gültig" in answer
