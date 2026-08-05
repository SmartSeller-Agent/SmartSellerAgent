# Konfiguration für die Modell-Provider
#
# Text- und Vision-Modell werden getrennt konfiguriert und können bei
# unterschiedlichen Providern liegen. Beide sprechen das OpenAI-Protokoll,
# damit funktionieren lokales Ollama und gehostete Dienste wie OpenRouter
# ohne Codeänderung — es zählt nur, worauf die Basis-URL zeigt.
#
#   lokal      : http://localhost:11434/v1  (bzw. http://ollama:11434/v1 im Docker)
#   OpenRouter : https://openrouter.ai/api/v1
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Textmodell (Orchestrator und Subagenten) ---
# OLLAMA_* bleibt als Fallback bestehen, damit ältere .env-Dateien weiter funktionieren.
TEXT_API_BASE = os.getenv("TEXT_API_BASE") or os.getenv("OLLAMA_API_BASE", "http://localhost:11434/v1")
TEXT_API_KEY  = os.getenv("TEXT_API_KEY")  or os.getenv("OLLAMA_API_KEY", "ollama")
TEXT_MODEL_ID = os.getenv("TEXT_MODEL_ID", "qwen3:8b")

# --- Vision-Modell (Tool des vision_agent) ---
# Ohne eigene Angabe folgt es dem Textmodell-Provider.
VISION_API_BASE = os.getenv("VISION_API_BASE") or TEXT_API_BASE
VISION_API_KEY  = os.getenv("VISION_API_KEY")  or TEXT_API_KEY
VISION_MODEL_ID = os.getenv("VISION_MODEL_ID", "llava")

# Alte Namen als Alias, damit bestehende Importe nicht brechen.
OLLAMA_API_BASE = TEXT_API_BASE
OLLAMA_API_KEY  = TEXT_API_KEY

# --- Providerspezifische Zusatzparameter (JSON) ---
# Wird als `extra_body` an den Chat-Completions-Aufruf gehängt. Leer = nichts
# senden, damit der lokale Ollama-Pfad unverändert bleibt.
#
# Hintergrund: smolagents setzt bei einem ToolCallingAgent `tool_choice=required`
# (models.py:510). Qwen3 über OpenRouter lehnt das im Reasoning-Modus ab
# ("tool_choice ... does not support being set to required ... in thinking mode").
# Deshalb dort das Reasoning abschalten:
#   MODEL_EXTRA_BODY={"reasoning": {"enabled": false}}
# Falls ein Provider das ignoriert, ist die Alternative, ihn zu umgehen:
#   MODEL_EXTRA_BODY={"provider": {"ignore": ["Alibaba"]}}
_extra_body_raw = os.getenv("MODEL_EXTRA_BODY", "").strip()
if _extra_body_raw:
    try:
        MODEL_EXTRA_BODY = json.loads(_extra_body_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"MODEL_EXTRA_BODY ist kein gültiges JSON: {_extra_body_raw!r} ({exc})"
        ) from exc
elif "openrouter.ai" in TEXT_API_BASE:
    # Ohne das schlägt jeder Aufruf mit HTTP 400 fehl.
    MODEL_EXTRA_BODY = {"reasoning": {"enabled": False}}
else:
    # Lokales Ollama: nichts anhängen, Verhalten bleibt unverändert.
    MODEL_EXTRA_BODY = {}

# --- Kleinanzeigen-Veröffentlichung (Browser-Automatisierung) --------------
# Die Website hat keine API, deshalb steuert src/tools/marketplace.py einen
# echten Browser. Die Anmeldung liegt als Playwright-storage_state auf Platte:
# diese Datei enthält gültige Login-Cookies und gehört daher in ein Volume,
# niemals ins Image und niemals ins Repository.
KLEINANZEIGEN_STATE_DIR = Path(os.getenv("KLEINANZEIGEN_STATE_DIR", ".state"))
KLEINANZEIGEN_SESSION_FILE = KLEINANZEIGEN_STATE_DIR / "kleinanzeigen_session.json"
KLEINANZEIGEN_SCREENSHOT_DIR = Path(os.getenv("KLEINANZEIGEN_SCREENSHOT_DIR", "screenshots"))

# Headless ist der Normalfall — im Container gibt es keinen X-Server.
# Zum Zuschauen bei der Fehlersuche: KLEINANZEIGEN_HEADLESS=false
KLEINANZEIGEN_HEADLESS = os.getenv("KLEINANZEIGEN_HEADLESS", "true").lower() not in (
    "0", "false", "no",
)
KLEINANZEIGEN_SLOW_MO_MS = int(os.getenv("KLEINANZEIGEN_SLOW_MO_MS", "0"))

# Auf ein vorhandenes Feld warten wir kurz; auf serverseitig nachgeladene
# Abschnitte (Kategorievorschläge, Versand) und auf die Bestätigungsseite länger.
KLEINANZEIGEN_FIELD_TIMEOUT_MS = int(os.getenv("KLEINANZEIGEN_FIELD_TIMEOUT_MS", "5000"))
# Wartezeit nach dem Laden, bevor überhaupt geschrieben wird. Die Seite zieht
# in dieser Phase einen Entwurf nach und verwirft dabei bereits gesetzte Werte.
KLEINANZEIGEN_READY_TIMEOUT_MS = int(os.getenv("KLEINANZEIGEN_READY_TIMEOUT_MS", "8000"))
KLEINANZEIGEN_SECTION_TIMEOUT_MS = int(os.getenv("KLEINANZEIGEN_SECTION_TIMEOUT_MS", "20000"))
KLEINANZEIGEN_CONFIRM_TIMEOUT_MS = int(os.getenv("KLEINANZEIGEN_CONFIRM_TIMEOUT_MS", "15000"))

# Configuration for langfuse and open telemetry
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST       = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
# Prints every span export to stdout. Debugging aid, off by default — it adds
# console I/O to the export path.
OTEL_DEBUG_EXPORT   = os.getenv("OTEL_DEBUG_EXPORT", "").lower() in ("1", "true", "yes")
