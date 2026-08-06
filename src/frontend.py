"""
Streamlit-Oberfläche des SmartSellerAgent.

Spricht das Backend ausschließlich über HTTP an — bewusst ohne Import aus
src/, damit die Oberfläche nichts von Agenten, Modellen oder Browsern wissen
muss. Sie läuft im Docker-Aufbau in einem eigenen Container.
"""
import os
import time
from pathlib import Path

import requests
import streamlit as st

# --- Konfiguration ---
# Basis-URL des Backends. Der Default gilt für den lokalen Start (uvicorn und
# Streamlit auf demselben Rechner). Unter Docker zeigt 127.0.0.1 auf den
# Frontend-Container selbst, deshalb setzt docker-compose.yml hier den
# Servicenamen: http://api:8000
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
RUN_TASK_URL = f"{API_BASE_URL}/run-task"
PROFILE_URL = f"{API_BASE_URL}/profile"
SESSION_URL = f"{API_BASE_URL}/marketplace/session"
VERIFY_URL = f"{API_BASE_URL}/marketplace/session/verify"
LOGIN_URL = f"{API_BASE_URL}/marketplace/login"
IMPORT_URL = f"{API_BASE_URL}/marketplace/session/import"

# Anders als die Adressen oben zeigt diese auf den Host: der Link wird im
# Browser des Anwenders geöffnet, nicht aus dem Containernetz heraus.
VNC_URL = os.getenv("VNC_URL", "http://localhost:6080/vnc.html?autoconnect=1&resize=scale")

# Ordner für Datei-Uploads anlegen. Relativ zum Arbeitsverzeichnis, das sich
# api und frontend über ein gemeinsames Volume teilen.
UPLOAD_DIR = Path("test/images/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Wie lange auf das Backend gewartet wird. Der Agentenlauf darf dauern, alles
# rund um die Anmeldung antwortet dagegen sofort.
TASK_TIMEOUT_S = int(os.getenv("FRONTEND_TASK_TIMEOUT_S", "1800"))
QUICK_TIMEOUT_S = 15
# Die echte Prüfung startet einen Browser und lädt eine Seite — das dauert
# länger als eine Dateiabfrage, aber nicht annähernd so lange wie ein Agentenlauf.
VERIFY_TIMEOUT_S = 90


def _call(method: str, url: str, **kwargs):
    """Gibt (Erfolg, Nutzlast-oder-Meldung) zurück statt zu werfen.

    Die Oberfläche soll bei einem nicht erreichbaren Backend einen Hinweis
    zeigen und weiterlaufen, nicht mit einem Stacktrace stehenbleiben.
    """
    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        return True, response.json()
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = (e.response.text or "")[:200]
        return False, detail or str(e)
    except requests.RequestException as e:
        return False, f"Backend nicht erreichbar: {e}"


# --------------------------------------------------------------------------
# Einstellungen des Anwenders
# --------------------------------------------------------------------------
def _save_profile(zip_code: str, container) -> bool:
    ok, result = _call(
        "PUT", PROFILE_URL, json={"zip_code": zip_code}, timeout=QUICK_TIMEOUT_S
    )
    if ok:
        container.success("Gespeichert.")
        return True
    container.error(result)
    return False


def render_first_run_setup() -> None:
    """Wird beim ersten Aufruf gezeigt, solange Angaben fehlen."""
    st.subheader("Einmalige Einrichtung")
    st.write(
        "Bevor Anzeigen erstellt werden können, fehlt noch dein Standort. "
        "Er steht später in jeder Anzeige und lässt sich jederzeit in der "
        "Seitenleiste ändern."
    )
    zip_code = st.text_input("Postleitzahl", max_chars=5, placeholder="78462")
    if st.button("Speichern") and _save_profile(zip_code, st):
        st.rerun()


def render_profile_settings(sidebar, profile: dict) -> None:
    with sidebar.expander("Einstellungen"):
        st.caption(
            "Bleibt erhalten, bis der Docker-Aufbau samt Volumes entfernt wird "
            "— wie die Anmeldung."
        )
        zip_code = st.text_input(
            "Postleitzahl", value=profile.get("zip_code", ""), max_chars=5
        )
        if st.button("Änderung speichern") and _save_profile(zip_code, st):
            st.rerun()


# --------------------------------------------------------------------------
# Seitenleiste: Anmeldung beim Marktplatz
# --------------------------------------------------------------------------
def render_login_progress(sidebar) -> None:
    """Zeigt den Stand eines laufenden oder beendeten Anmeldevorgangs.

    Wird weit oben gezeichnet: Ein Fehlschlag im Hintergrund ist sonst nicht
    von einem Erfolg zu unterscheiden — beides sähe aus wie "nichts passiert".
    """
    ok, data = _call("GET", LOGIN_URL, timeout=QUICK_TIMEOUT_S)
    if not ok or data.get("status") == "idle":
        return

    status = data["status"]
    if status == "done":
        # Nichts anzeigen: Das Ergebnis steht bereits in der Statuszeile
        # darüber. Ein zweiter Erfolgshinweis samt Dateipfad wäre nur Lärm,
        # der nach jedem Neuzeichnen wieder auftaucht.
        return

    if status == "running":
        sidebar.info("Anmeldung läuft — bitte im Browserfenster fortfahren.")
    elif status == "failed":
        sidebar.error(f"Anmeldung fehlgeschlagen: {data.get('error')}")

    for message in data.get("messages", []):
        sidebar.caption(message)


def _verify_and_rerun() -> None:
    with st.spinner("Ruft eine geschützte Seite auf …"):
        _call("POST", VERIFY_URL, timeout=VERIFY_TIMEOUT_S)
    # Neu zeichnen, damit die Kopfzeile das Ergebnis zeigt und nicht mehr den
    # Stand von vor der Prüfung.
    st.rerun()


def _render_start_browser(container) -> None:
    """Der Container kann kein Programm auf dem Rechner des Anwenders starten.

    Das ist keine Einstellung, sondern die Grenze, die einen Container
    ausmacht. Also sagen wir, was zu tun ist.
    """
    container.warning("Der Browser auf deinem Rechner läuft nicht.")
    container.code("uv run python -m scripts.host_browser")
    container.caption("In einem eigenen Terminal starten und offen lassen.")
    if container.button("Erneut nach dem Browser suchen", use_container_width=True):
        st.rerun()


def _render_login_button(container, session: dict, label: str = "Jetzt anmelden") -> None:
    if not container.button(label, use_container_width=True):
        return

    started, result = _call("POST", LOGIN_URL, timeout=QUICK_TIMEOUT_S)
    if not started:
        container.error(result)
        return

    # Kurz warten und neu zeichnen, statt den Start zu melden und zu hoffen.
    # Scheitert der Vorgang sofort, steht der Grund dann gleich oben.
    time.sleep(2)
    st.rerun()


def render_session_sidebar():
    """Zeichnet die Seitenleiste und gibt den Sitzungsstand zurück."""
    sidebar = st.sidebar
    sidebar.header("Anmeldung bei Kleinanzeigen")

    ok, session = _call("GET", SESSION_URL, timeout=QUICK_TIMEOUT_S)
    if not ok:
        sidebar.error(session)
        return None

    # Grün gibt es nur nach einer echten Prüfung. Die Datei allein sagt bloß,
    # dass Cookies noch nicht abgelaufen sind — das hat schon einmal "in
    # Ordnung" gemeldet, während der Anbieter die Sitzung längst abgelehnt hatte.
    verdict = session.get("verdict", "unknown")
    # Trägt der Browser die Anmeldung in seinem Profil, sagt unsere Datei
    # nichts über den Anmeldezustand aus — dann wäre "keine gültige Anmeldung"
    # schlicht falsch, während im Fenster daneben das Konto offen ist.
    in_browser = bool(session.get("session_in_browser"))

    if in_browser and not session["usable"]:
        if verdict == "accepted":
            sidebar.success("Angemeldet und geprüft")
        elif verdict == "rejected":
            sidebar.error("Anmeldung wird nicht mehr akzeptiert — bitte neu anmelden")
        else:
            sidebar.info("Anmeldung liegt im Browser — Zustand ungeprüft")
    elif not session["usable"]:
        sidebar.warning("Keine gültige Anmeldung")
    elif verdict == "accepted":
        sidebar.success("Angemeldet und geprüft")
    elif verdict == "rejected":
        sidebar.error("Anmeldung wird nicht mehr akzeptiert — bitte neu anmelden")
    else:
        sidebar.info("Anmeldung vorhanden, aber ungeprüft")

    # Ganz oben, weil hier der Grund steht, wenn eine Anmeldung eben
    # fehlgeschlagen ist. Weiter unten würde man ihn übersehen.
    render_login_progress(sidebar)

    if session.get("verdict_detail"):
        sidebar.caption(session["verdict_detail"])

    # Die Cookie-Bilanz nur zeigen, solange sie etwas Nützliches aussagt. Nach
    # einer Absage würde "7 Cookies gültig" der roten Meldung direkt darüber
    # widersprechen — und beim Browser mit eigenem Profil sagt die Datei
    # ohnehin nichts über den Anmeldezustand.
    if in_browser:
        sidebar.caption(
            "Die Anmeldung steckt im Profil des Browsers auf deinem Rechner "
            "und bleibt dort erhalten. Das Fenster erscheint auf deinem "
            "Desktop; Sicherheitsabfrage und Zwei-Faktor-Bestätigung erledigst "
            "du dort selbst."
        )
    else:
        if verdict != "rejected":
            sidebar.caption(session["description"])
        sidebar.caption(
            f"Der Browser der Anwendung ist unter [dieser Ansicht]({VNC_URL}) zu "
            "sehen — dort ist nur etwas zu sehen, solange gerade ein Browser "
            "geöffnet ist."
        )

    # An jeder Stelle gibt es genau einen sinnvollen nächsten Schritt. Zwei
    # gleichrangige Knöpfe zu zeigen, zwingt den Anwender zu einer Entscheidung,
    # für die er den Unterschied zwischen "prüfen" und "anmelden" kennen müsste.
    browser_missing = bool(
        session.get("browser_on_host") and not session.get("browser_reachable")
    )
    # Wir wissen, dass die Anmeldung fehlt — nicht bloß, dass sie ungeprüft ist.
    login_known_bad = verdict == "rejected" or (not in_browser and not session["usable"])

    if browser_missing:
        _render_start_browser(sidebar)
    elif login_known_bad:
        _render_login_button(sidebar, session)
        if sidebar.button("Trotzdem erneut prüfen", use_container_width=True):
            _verify_and_rerun()
    else:
        label = "Anmeldung erneut prüfen" if verdict == "accepted" else "Anmeldung prüfen"
        if sidebar.button(label, use_container_width=True):
            _verify_and_rerun()

    with sidebar.expander("Weitere Möglichkeiten"):
        if not browser_missing and not login_known_bad:
            st.caption("Um das Konto zu wechseln oder eine Anmeldung zu erneuern:")
            _render_login_button(st, session, label="Anmeldefenster öffnen")

        # Verwerfen nur, wenn die Anmeldung ohnehin nichts mehr taugt — eine
        # funktionierende soll man nicht mit einem Fehlklick verlieren.
        if session["exists"] and (verdict == "rejected" or not session["usable"]):
            if st.button("Gespeicherte Anmeldung verwerfen", use_container_width=True):
                ok, result = _call("DELETE", SESSION_URL, timeout=QUICK_TIMEOUT_S)
                if not ok:
                    st.error(result)
                else:
                    st.rerun()

        st.caption(
            "Auf einem anderen Rechner erzeugte Anmeldung hochladen. "
            "Die Datei wird geprüft, bevor sie die vorhandene ersetzt."
        )
        # Der Schlüssel wechselt nach jedem Import. Ohne das behält Streamlit
        # die einmal gewählte Datei bei — und ein zweiter Klick schickte
        # wieder die alte los, obwohl inzwischen eine neuere existiert.
        round_number = st.session_state.get("session_upload_round", 0)
        upload = st.file_uploader(
            "Sitzungsdatei (JSON)", type=["json"], key=f"session_upload_{round_number}"
        )
        if upload is not None and st.button("Übernehmen"):
            ok, result = _call(
                "POST",
                IMPORT_URL,
                files={"file": (upload.name, upload.getvalue(), "application/json")},
                timeout=QUICK_TIMEOUT_S,
            )
            if not ok:
                st.error(result)
            else:
                st.session_state["session_upload_round"] = round_number + 1
                # Neu zeichnen, damit die Kopfzeile den übernommenen Stand
                # zeigt. Sonst bleibt die alte Auskunft stehen und man hält
                # eine tote Anmeldung für die gerade hochgeladene.
                st.rerun()

    return session


# --------------------------------------------------------------------------
# Was tatsächlich passiert ist
# --------------------------------------------------------------------------
def render_publish_outcome(attempts: list) -> None:
    """Zeigt den Ausgang so an, wie das Tool ihn protokolliert hat.

    Bewusst nicht aus dem Text des Agenten abgeleitet: Ein Sprachmodell hat
    hier schon berichtet, eine Anzeige sei online gegangen, obwohl das
    Veröffentlichen abgeschaltet und niemand angemeldet war. Was mit einer
    unumkehrbaren Aktion geschehen ist, darf nicht Erzählung sein.
    """
    if not attempts:
        st.warning(
            "Es wurde **keine** Anzeige eingestellt — der Agent hat das "
            "Veröffentlichungs-Tool gar nicht aufgerufen. Falls der Text unten "
            "etwas anderes behauptet, gilt diese Meldung.",
            icon="⚠️",
        )
        return

    for attempt in attempts:
        outcome = attempt.get("outcome")
        detail = attempt.get("detail", "")

        if outcome == "published":
            st.success("Die Anzeige ist online und öffentlich sichtbar.", icon="✅")
        elif outcome == "preview":
            st.info(
                "Probelauf: Das Formular wurde ausgefüllt, aber **nicht** "
                "abgesendet. Es ist keine Anzeige entstanden.",
                icon="👀",
            )
        elif outcome == "not_logged_in":
            st.error(f"Keine Anzeige erstellt — nicht angemeldet. {detail}", icon="🔒")
        elif outcome == "invalid":
            st.error(f"Keine Anzeige erstellt — die Angaben waren unbrauchbar:\n\n{detail}")
        else:
            st.error(f"Keine Anzeige erstellt — Fehler: {detail}")


# --------------------------------------------------------------------------
# Hauptbereich: Anzeige erstellen
# --------------------------------------------------------------------------
st.set_page_config(page_title="SmartSeller Agent", page_icon="🛍️")
st.title("🛍️ SmartSeller")

session = render_session_sidebar()

profile_ok, profile = _call("GET", PROFILE_URL, timeout=QUICK_TIMEOUT_S)
if profile_ok:
    render_profile_settings(st.sidebar, profile)

# Solange die Angaben fehlen, hat der Hauptablauf keinen Sinn — die Anzeige
# bekäme keinen Standort.
if profile_ok and not profile["complete"]:
    render_first_run_setup()
    st.stop()

st.write(
    "Lade ein Bild deines Artikels hoch. Der Agent erkennt das Produkt, "
    "recherchiert Marktpreise und schreibt eine fertige Anzeige!"
)

uploaded_file = st.file_uploader("Produktbild hochladen (JPG/PNG)", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Dein Produkt", use_container_width=True)

    # Der Schalter für den unumkehrbaren Teil. Aus als Standard, und der Text
    # sagt in beiden Stellungen, was tatsächlich passiert.
    installation_allows = bool(session and session.get("publishing_enabled"))
    allow_publish = st.checkbox(
        "Anzeige anschließend wirklich veröffentlichen",
        value=False,
        disabled=not installation_allows,
        help=(
            "Aus: das Formular wird nur ausgefüllt und ein Screenshot abgelegt. "
            "An: es entsteht eine öffentliche Anzeige unter deinem Konto, die "
            "sich nur von Hand wieder löschen lässt."
        ),
    )

    if not installation_allows:
        st.caption(
            "Veröffentlichen ist in dieser Installation gesperrt. "
            "Zum Freigeben KLEINANZEIGEN_ALLOW_PUBLISH=true in der .env setzen "
            "und die Container neu starten."
        )
    elif allow_publish:
        st.warning(
            "Es wird eine echte, öffentlich sichtbare Anzeige erstellt.",
            icon="⚠️",
        )

    if st.button("Verkaufsanzeige generieren"):
        with st.spinner("Agent arbeitet: Analysiert Bild und recherchiert Preise im Web..."):
            # Das Backend erwartet einen Dateipfad, also legen wir das Bild im
            # gemeinsamen Volume ab.
            file_path = UPLOAD_DIR / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            ok, result = _call(
                "POST",
                RUN_TASK_URL,
                json={
                    # Der Ablauf endet mit dem Einstellen. Ob dabei wirklich
                    # etwas online geht, entscheidet allein allow_publish.
                    "task_name": "create_and_publish_listing",
                    "image_path": str(file_path.absolute()),
                    "purchase_price": 0.0,
                    "allow_publish": allow_publish,
                },
                timeout=TASK_TIMEOUT_S,
            )

        if ok:
            render_publish_outcome(result.get("publish_attempts", []))
            st.markdown("### Dein Anzeigentext:")
            st.info(result.get("result", "Kein Text generiert."))
        else:
            st.error(f"Fehler bei der Kommunikation mit dem Backend: {result}")
