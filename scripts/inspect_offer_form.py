"""
Entwicklungswerkzeug: liest den Aufbau des Kleinanzeigen-Formulars aus.

Ersetzt tmp_browser_automation/inspect_offer.py. Zwei Unterschiede zum
Original:

1. Das Formular baut sich schrittweise auf — Felder erscheinen erst, wenn
   vorherige ausgefüllt sind. Das Skript protokolliert deshalb nach jedem
   Schritt nur, *was neu dazugekommen ist*.
2. Kategorie- und Preistyp-Auswahl sind keine nativen Formularelemente,
   sondern eigene Komponenten, die in versteckte Felder schreiben. Erfasst
   werden daher auch Elemente mit ARIA-Rollen, und von den interessanten
   Abschnitten wird das Markup ausgegeben (ohne class/style, sonst unlesbar).

Aufruf (Session muss vorhanden sein):

    $env:KLEINANZEIGEN_STATE_DIR = "tmp_browser_automation"
    $env:KLEINANZEIGEN_HEADLESS  = "false"
    uv run python -m scripts.inspect_offer_form
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools import marketplace  # noqa: E402

TITLE = "Spiegelschrank | Badschrank | Schrank Bad"

# Rollen, die für eine Auswahl in Frage kommen. Alles andere wäre nur Rauschen.
_INTERESTING_ROLES = [
    "radio", "radiogroup", "combobox", "listbox", "option",
    "checkbox", "switch", "menuitem", "tab",
]

_DUMP_JS = """
(roles) => {
    const out = [];
    const add = (el, source) => {
        const labels = Array.from(el.labels || []).map(l => l.innerText.trim());
        const wrapping = el.closest ? el.closest('label') : null;
        if (wrapping) labels.push(wrapping.innerText.trim());
        out.push({
            source,
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            id: el.id || '',
            name: el.getAttribute('name') || '',
            role: el.getAttribute('role') || '',
            testid: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || '',
            aria: el.getAttribute('aria-label') || '',
            checked: el.getAttribute('aria-checked') || (el.checked === true ? 'true' : ''),
            label: labels.filter(Boolean).join(' | ').replace(/\\s+/g, ' ').slice(0, 70),
            text: (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 70),
            options: el.tagName === 'SELECT'
                ? Array.from(el.options).map(o => `${o.value}=${o.text.trim()}`)
                : undefined,
            visible: !!(el.offsetParent || el.offsetWidth || el.offsetHeight),
        });
    };

    document.querySelectorAll('input, select, textarea').forEach(el => add(el, 'form'));
    roles.forEach(role => {
        document.querySelectorAll(`[role="${role}"]`).forEach(el => add(el, 'role'));
    });
    document.querySelectorAll('button').forEach(el => {
        if (el.offsetParent || el.offsetWidth) add(el, 'button');
    });
    return out;
}
"""

# Markup eines Abschnitts, gefunden über seine Beschriftung. class/style raus,
# sonst ist der Ausdruck von React-Klassennamen unlesbar.
_HTML_AROUND_JS = """
(needle) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let hit = null;
    while (walker.nextNode()) {
        const el = walker.currentNode;
        if (el.children.length === 0 && el.textContent.trim() === needle) { hit = el; break; }
    }
    if (!hit) return null;

    let node = hit;
    for (let i = 0; i < 8 && node.parentElement; i++) {
        node = node.parentElement;
        if (node.querySelector('input, select, textarea, [role], button')) break;
    }

    const clone = node.cloneNode(true);
    clone.querySelectorAll('svg, path, style, script').forEach(e => e.remove());
    [clone, ...clone.querySelectorAll('*')].forEach(e => {
        e.removeAttribute('class');
        e.removeAttribute('style');
    });
    return clone.outerHTML;
}
"""


def _key(element: dict) -> str:
    return "|".join(
        str(element[k]) for k in ("source", "tag", "type", "id", "name", "role", "testid", "label", "text")
    )


def _describe(element: dict) -> str:
    parts = [f"<{element['tag']}"]
    for attr in ("type", "id", "name", "role", "testid"):
        if element[attr]:
            parts.append(f'{attr}="{element[attr]}"')
    line = " ".join(parts) + ">"

    for attr, caption in (("label", "label"), ("aria", "aria-label"), ("text", "text")):
        if element[attr]:
            line += f"   {caption}: {element[attr]!r}"
    if element["checked"]:
        line += f"   checked={element['checked']}"
    if not element["visible"]:
        line += "   [unsichtbar]"
    if element.get("options"):
        line += "\n      Optionen: " + json.dumps(element["options"], ensure_ascii=False)
    return line


def _snapshot(page) -> list:
    return page.evaluate(_DUMP_JS, _INTERESTING_ROLES)


def _report(page, heading: str, seen: set) -> list:
    print(f"\n{'=' * 70}\n{heading}\n{'=' * 70}")
    new = [el for el in _snapshot(page) if _key(el) not in seen]
    if not new:
        print("  (nichts Neues)")
    for el in new:
        seen.add(_key(el))
        print("  " + _describe(el))
    return new


def _wait_for_change(page, seen: set, timeout_s: float = 15.0) -> None:
    """Wartet, bis neue Elemente auftauchen.

    Die Kategorie-Vorschläge kommen erst nach einer Serverabfrage zum Titel.
    Ein fester Timer ist dafür zu unzuverlässig — beim letzten Lauf war er
    schlicht zu kurz.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if any(_key(el) not in seen for el in _snapshot(page)):
            page.wait_for_timeout(500)  # kurz nachlaufen lassen
            return
        page.wait_for_timeout(500)
    print(f"  (keine Änderung innerhalb von {timeout_s:.0f}s)")


def _dump_html(page, label: str) -> None:
    html = page.evaluate(_HTML_AROUND_JS, label)
    print(f"\n----- Markup um '{label}' " + "-" * max(0, 50 - len(label)))
    if not html:
        print("  (Beschriftung nicht gefunden)")
        return
    print(html[:3000] + ("\n  ...gekürzt..." if len(html) > 3000 else ""))


_CLEAN_HTML_JS = """
(selector) => {
    const node = document.querySelector(selector);
    if (!node) return null;
    const clone = node.cloneNode(true);
    clone.querySelectorAll('svg, path, style, script').forEach(e => e.remove());
    [clone, ...clone.querySelectorAll('*')].forEach(e => {
        e.removeAttribute('class');
        e.removeAttribute('style');
    });
    return clone.outerHTML;
}
"""


def _dump_selector(page, selector: str) -> None:
    html = page.evaluate(_CLEAN_HTML_JS, selector)
    print(f"\n----- Markup von '{selector}' " + "-" * max(0, 46 - len(selector)))
    if not html:
        print("  (nicht im DOM)")
        return
    print(html[:3000] + ("\n  ...gekürzt..." if len(html) > 3000 else ""))


def _fill_verified(page, locator, value: str, attempts: int = 4) -> bool:
    """Schreibt und prüft nach.

    Die Seite lädt einen Entwurf nach und überschreibt frisch gesetzte Werte —
    ein einmaliges fill() wirft dabei keinen Fehler, der Wert ist trotzdem weg.
    """
    for attempt in range(1, attempts + 1):
        locator.fill(value)
        page.wait_for_timeout(800)
        current = locator.input_value()
        if current == value:
            print(f"    Wert steht (Versuch {attempt})")
            return True
        print(f"    Versuch {attempt}: Feld enthält {current!r} statt {value!r} — nochmal")
    return False


def main() -> None:
    from playwright.sync_api import sync_playwright

    if not marketplace.SESSION_FILE.is_file():
        raise SystemExit(f"Keine Session unter {marketplace.SESSION_FILE}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=marketplace.HEADLESS,
            slow_mo=200,
            # Unterdrückt Berechtigungs-Popups des Browsers, die beim letzten
            # Lauf über der Seite lagen.
            args=["--disable-notifications", "--deny-permission-prompts"],
        )
        context = browser.new_context(
            storage_state=str(marketplace.SESSION_FILE), no_viewport=True
        )
        page = context.new_page()
        seen: set = set()

        try:
            page.goto(marketplace.OFFER_FORM_URL)
            try:
                page.click('button:has-text("Alle akzeptieren")', timeout=5000)
            except Exception:
                pass

            # Erst wenn die Seite ihren Entwurf nachgeladen hat, bleiben
            # geschriebene Werte stehen.
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                print("  (networkidle nicht erreicht — weiter)")

            _report(page, "SCHRITT 1 — Formular frisch geladen", seen)

            # Titel setzen und Fokus wegnehmen — das stößt die Kategorieabfrage an.
            print("\n>>> setze den Titel")
            title = page.locator('input[id="ad-title"]')
            title.wait_for(state="visible", timeout=10000)
            if not _fill_verified(page, title, TITLE):
                print("    ABBRUCH: Titel bleibt leer, ohne ihn gibt es keine Kategorien.")
            title.blur()

            _wait_for_change(page, seen)
            _report(page, "SCHRITT 2 — neu nach Titeleingabe", seen)
            _dump_selector(page, "#ad-category-suggestions")
            _dump_html(page, "Preistyp")

            # Kategorie: der erste Vorschlag im Vorschlagsblock. Über die
            # Position statt über den Text, denn der hängt vom Titel ab.
            print("\n>>> klicke den ersten Kategorievorschlag")
            suggestion = page.locator(
                "#ad-category-suggestions a, #ad-category-suggestions input,"
                ' #ad-category-suggestions [role="radio"], #ad-category-suggestions label'
            ).first
            try:
                print(f"    Kandidaten: {page.locator('#ad-category-suggestions *').count()} Elemente")
                suggestion.click(timeout=5000)
            except Exception as e:
                print(f"    fehlgeschlagen: {e}")

            _wait_for_change(page, seen)
            _report(page, "SCHRITT 3 — neu nach Kategorieauswahl", seen)
            _dump_selector(page, "#ad-category-suggestions")
            _dump_html(page, "Versand")

            # Preistyp-Widget öffnen, damit die Optionen im DOM erscheinen.
            print("\n>>> öffne das Preistyp-Widget")
            for selector in ("text=Festpreis", '[name="priceType"]'):
                try:
                    page.locator(selector).first.click(timeout=3000)
                    print(f"    geklickt: {selector}")
                    break
                except Exception:
                    continue

            _wait_for_change(page, seen, timeout_s=5)
            _report(page, "SCHRITT 4 — neu nach Öffnen des Preistyps", seen)

            marketplace.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            target = marketplace.SCREENSHOT_DIR / "inspect_final.png"
            page.screenshot(path=str(target), full_page=True)
            print(f"\nScreenshot: {target}")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
