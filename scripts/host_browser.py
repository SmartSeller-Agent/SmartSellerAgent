"""
Startet auf dem Host einen sichtbaren Browser, an den sich der Container hängt.

Warum das gebraucht wird: Der Browser im Container bringt eine eigene Umgebung
mit — Software-Grafikausgabe, kaum Schriftarten, virtueller Bildschirm — und
wird von kleinanzeigen.de wie ein fremdes Gerät behandelt. Eine dort gültige
Anmeldung wird nicht anerkannt. Ein Browser auf deinem Rechner hat die
Umgebung, die die Website von dir kennt.

Nebeneffekt: Das Fenster steht auf dem Desktop statt hinter noVNC.

Aufruf (in einem eigenen Terminal, das offen bleibt):

    uv run python -m scripts.host_browser

Danach in der .env eintragen und die Container neu starten:

    KLEINANZEIGEN_BROWSER_CDP=http://host.docker.internal:9222
    KLEINANZEIGEN_VNC=false

Zur Sicherheit: Die Fernsteuerung lauscht auf allen Schnittstellen, sonst
käme der Container nicht heran. Wer den Port erreicht, steuert diesen Browser.
Das ist für einen Entwicklungsrechner hinter einer Firewall vertretbar, für
ein offenes Netz nicht.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import KLEINANZEIGEN_STATE_DIR  # noqa: E402

PORT = 9222
# Eigenes Profil, nicht das des Alltagsbrowsers: es bleibt erhalten, sammelt
# mit der Zeit die Wiedererkennung, die eine Website von einem bekannten Gerät
# erwartet — und es kommt dem täglichen Surfen nicht in die Quere.
PROFILE_DIR = KLEINANZEIGEN_STATE_DIR / "host-browser-profile"


def main() -> None:
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            args=[
                f"--remote-debugging-port={PORT}",
                # Ohne das lauscht die Fernsteuerung nur auf 127.0.0.1 und der
                # Container käme nicht heran.
                "--remote-debugging-address=0.0.0.0",
                "--disable-notifications",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context.new_page().goto("https://www.kleinanzeigen.de/")

        print(f"Browser läuft. Fernsteuerung auf Port {PORT}.")
        print(f"Profil: {PROFILE_DIR}")
        print()
        print("In der .env eintragen und die Container neu starten:")
        print("  KLEINANZEIGEN_BROWSER_CDP=http://host.docker.internal:9222")
        print("  KLEINANZEIGEN_VNC=false")
        print()
        print("Fenster offen lassen. Beenden mit Strg+C.")

        # Offen halten, solange noch ein Fenster steht. Schließt der Anwender
        # das letzte, endet auch dieses Skript.
        try:
            while context.pages:
                context.pages[0].wait_for_timeout(1000)
        except KeyboardInterrupt:
            print("\nBeendet.")
        except Exception:
            # Browser vom Anwender geschlossen — kein Fehlerfall.
            pass
        finally:
            try:
                context.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
