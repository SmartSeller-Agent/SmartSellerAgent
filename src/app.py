# -------------------------- Imports --------------------------
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import tempfile
import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional

# Imports: Agents
from smolagents import ToolCallingAgent, OpenAIServerModel, DuckDuckGoSearchTool, LogLevel

# Imports: Config, API Keys
from src.config import TEXT_API_BASE, TEXT_API_KEY, TEXT_MODEL_ID, MODEL_EXTRA_BODY

# Imports: Tracing, Logging
from src.tracing import setup_tracing
import logging
logging.getLogger("opentelemetry.exporter.otlp").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)

# Imports: Tools
from src.tools.vision import analyze_product_image
from src.tools.pricing import calculate_margin
from src.tools import marketplace
from src.login_job import LoginJob
from src import user_profile

#-------------------------- Code --------------------------
# setup tracing
tracer_provider = setup_tracing()

# Absoluten Pfad relativ zu dieser Datei berechnen
_project_root = Path(__file__).parent.parent  # src/ -> Projektstamm
_image_path = _project_root / "test" / "images" / "Kallax4x4_leer.png"

# Load prompts from YAML file
_prompts_path = _project_root / "src" / "prompts.yaml"
with open(_prompts_path, encoding="utf-8") as f:
    _prompts = yaml.safe_load(f)

# TOOL: Web Search Tool
webSearch = DuckDuckGoSearchTool()

# TOOL: Vision Tool: Analyze the product image and extract relevant information (e.g., product name, condition, etc.)
vision_tool = analyze_product_image

# TOOL: Pricing Tool: Calculate the margin based on the extracted information and the web search results (mainly for debugging)
pricing_tool = calculate_margin

model = OpenAIServerModel(
    model_id=TEXT_MODEL_ID,
    api_base=TEXT_API_BASE,
    api_key=TEXT_API_KEY,
    # Nur setzen, wenn konfiguriert — sonst bleibt der lokale Ollama-Aufruf unverändert.
    **({"extra_body": MODEL_EXTRA_BODY} if MODEL_EXTRA_BODY else {}),
)
print(f"[config] text model: {TEXT_MODEL_ID} via {TEXT_API_BASE}")
if MODEL_EXTRA_BODY:
    print(f"[config] extra_body: {MODEL_EXTRA_BODY}")

# --- Subagent: analyzes product photos only ---
vision_agent = ToolCallingAgent(
    tools=[vision_tool],
    model=model,
    instructions=_prompts["vision_agent"]["instructions"],
    max_steps=4,
    # P2: DEBUG also logs "Output message of the LLM" — the Thought part of the
    # TAO cycle. At the default INFO level only Action and Observation appear.
    verbosity_level=LogLevel.DEBUG,
    name="vision_agent",
    description=(
        "Analyzes a product photo and reports back what the item is: "
        "product name/category, brand (if visible) and visible condition. "
        "Call it with a task that includes the local image file path, "
        "e.g. \"Analyze the product image at 'test/images/Kallax4x4.png'.\""
    ),
)

# --- Subagent: puts a finished listing on the marketplace ---
# Eigener Agent und nicht nur ein Tool am Orchestrator, weil hier echte Arbeit
# anfällt: aus Fließtext werden strukturierte Formularfelder mit eigenen Regeln
# (Titellänge, Kategorie-Stichwort, Preisart). Die Anmeldung prüft er selbst,
# bevor er etwas versucht.
publisher_agent = ToolCallingAgent(
    tools=[marketplace.publish_listing, marketplace.check_marketplace_session],
    model=model,
    instructions=_prompts["publisher_agent"]["instructions"],
    # Knapp gehalten: der Ablauf ist prüfen, einstellen, berichten. Mehr Schritte
    # hiessen, dass etwas schiefläuft — und jeder Schritt kostet eine Modellrunde.
    max_steps=4,
    verbosity_level=LogLevel.DEBUG,
    name="publisher_agent",
    description=(
        "Stellt eine fertige Anzeige bei kleinanzeigen.de ein. "
        "Erwartet Titel, Beschreibung, Preis, ein Stichwort für die Kategorie, "
        "ob Versand möglich ist, und den Pfad des Produktbildes. "
        "Prüft vorher selbst, ob eine gültige Anmeldung vorliegt."
    ),
)

# --- Orchestrator: owns the end-to-end resale evaluation workflow ---
orchestrator = ToolCallingAgent(
    tools=[webSearch, pricing_tool],
    model=model,
    managed_agents=[vision_agent, publisher_agent],
    instructions=_prompts["orchestrator"]["instructions"],
    max_steps=10,
    # P2: see vision_agent above — DEBUG makes the Thought visible in the logs.
    verbosity_level=LogLevel.DEBUG,
    name="orchestrator",
    description="Coordinates the end-to-end resale evaluation: image analysis, price research, margin calculation and recommendation.",
)


# -------------------------- FastAPI Setup --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Flush pending traces when the server shuts down.

    Spans are exported in batches from a background thread, so whatever is still
    queued when the process stops would be lost without this. shutdown() drains
    the queue and waits for the export to finish.
    """
    yield
    tracer_provider.shutdown()


api = FastAPI(title="SmartSeller Agent API", lifespan=lifespan)

# Erweitertes Request-Modell: Erlaubt optionale Übergabe von Bildpfad und Preis
class TaskRequest(BaseModel):
    task_name: str
    image_path: Optional[str] = str(_image_path)
    purchase_price: Optional[float] = 20.0
    # Freigabe für genau diesen Auftrag. Standard aus, und selbst ein True
    # reicht allein nicht — die Installation muss es zusätzlich erlauben
    # (KLEINANZEIGEN_ALLOW_PUBLISH). Das Sprachmodell sieht dieses Feld nicht.
    allow_publish: bool = False

@api.get("/health")
def health_check():
    return {"status": "ok", "message": "Der SmartSeller Agent läuft!"}

# Aufgaben, an deren Ende eine Anzeige stehen soll.
PUBLISHING_TASKS = {"create_and_publish_listing"}


def _publish_afterwards(listing_text: str, request: "TaskRequest") -> str:
    """Holt den Veröffentlichungsschritt nach, wenn er ausgefallen ist.

    Beobachtet: Der Orchestrator verfing sich in Websuchen, erreichte sein
    Schrittlimit und lieferte eine erzwungene Schlussantwort — in der er
    behauptete, die Anzeige sei eingestellt. Beauftragt hatte er niemanden.

    Ein Schritt, der zwingend passieren soll, darf nicht davon abhängen, dass
    ein Modell vorher mit seinem Budget haushaltet. Aufgerufen wird das nur bei
    leerem Protokoll — es kann also nichts doppelt entstehen.
    """
    return publisher_agent.run(
        "Stelle die folgende, bereits fertige Anzeige bei Kleinanzeigen ein. "
        "Übernimm Titel, Beschreibung und Preis unverändert; deine Aufgabe ist "
        "nur das Einstellen.\n"
        f"Das Produktbild liegt unter '{request.image_path}'.\n\n{listing_text}"
    )


@api.post("/run-task")
def run_agent_task(request: TaskRequest):
    # 1. Prompt dynamisch suchen (unterstützt deine neuen Tasks UND die vom Partner)
    task_prompt_template = None
    if "tasks" in _prompts and request.task_name in _prompts["tasks"]:
        task_prompt_template = _prompts["tasks"][request.task_name]
    elif "orchestrator" in _prompts and "tasks" in _prompts["orchestrator"] and request.task_name in _prompts["orchestrator"]["tasks"]:
        task_prompt_template = _prompts["orchestrator"]["tasks"][request.task_name]
        
    if not task_prompt_template:
        raise HTTPException(status_code=404, detail=f"Task '{request.task_name}' nicht gefunden.")
    
    # 2. Den gefundenen Prompt mit Variablen füllen (z.B. dem Bildpfad)
    try:
        final_task = task_prompt_template.format(
            image_path=request.image_path,
            purchase_price=request.purchase_price
        )
    except KeyError:
        # Falls der Prompt keine Platzhalter {} hat (wie z.B. dein create_listing)
        final_task = task_prompt_template 

    # Vor dem Lauf feststellen, ob eine Anzeige überhaupt entstehen kann.
    # Danach wäre die Auskunft weniger wert: Das Veröffentlichungs-Tool trägt
    # bei einem Fehlschlag selbst ein abgelehntes Urteil ein, und dann sähe
    # jeder Lauf so aus, als hätte von Anfang an die Anmeldung gefehlt.
    blocker = marketplace.publish_blocker()

    try:
        # 3. Das Multi-Agent-System (orchestrator) mit dem fertigen Task starten.
        #    Die Freigabe gilt nur für die Dauer dieses Aufrufs: smolagents ruft
        #    Tools synchron im selben Thread auf, deshalb sieht das
        #    Veröffentlichungs-Tool den Wert — und nur dieser Auftrag.
        with marketplace.publishing_allowed(request.allow_publish):
            result = orchestrator.run(final_task)
            # Innerhalb des Rahmens auslesen, danach ist das Protokoll wieder weg.
            attempts = marketplace.publish_records()

            # Nachholen nur, wenn es etwas nachzuholen gibt. Fehlt der Browser
            # oder die Anmeldung, kostete der zweite Anlauf bloß eine weitere
            # Modellrunde und endete am selben Hindernis.
            if request.task_name in PUBLISHING_TASKS and not attempts and not blocker:
                result = f"{result}\n\n{_publish_afterwards(result, request)}"
                attempts = marketplace.publish_records()
        return {
            "task": request.task_name,
            "result": result,
            # Was das Tool wirklich getan hat — mitgeschrieben vom Tool selbst,
            # nicht der Erzählung des Modells entnommen.
            "publish_attempts": attempts,
            # Stand vor dem Lauf: Wenn hier etwas steht, konnte am Ende nur der
            # Anzeigentext herauskommen. Die Oberfläche sagt das dazu, statt
            # den Anwender aus einer fehlenden Erfolgsmeldung schließen zu
            # lassen.
            "publish_blocker": blocker,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------- Marktplatz-Anmeldung --------------------------
# Die Anmeldung bei kleinanzeigen.de läuft bewusst von Hand ab: Captcha und
# Zwei-Faktor-Abfrage kann kein Skript lösen. Das Fenster dafür steht
# standardmäßig auf dem Rechner des Anwenders (scripts/host_browser.py); in der
# Rückfallvariante zeigt der Container seinen eigenen Browser über noVNC an.
# Zugangsdaten nimmt die Anwendung nie entgegen.
_login_job = LoginJob(marketplace.login_interactive)


def _session_payload() -> dict:
    status = marketplace.read_session_status()
    verdict = marketplace.last_session_verdict()
    return {
        "exists": status.exists,
        "usable": status.usable,
        "description": status.describe(),
        "saved_at": status.saved_at.isoformat() if status.saved_at else None,
        # Ergebnis der letzten echten Prüfung. Ohne das bliebe die Oberfläche
        # bei "sieht gut aus", obwohl der Anbieter die Sitzung eben abgelehnt hat.
        "verdict": verdict.status,
        "verdict_detail": verdict.detail,
        "verdict_at": verdict.at.isoformat() if verdict.at else None,
        # Damit die Oberfläche einen abgeschalteten Schalter erklären kann,
        # statt ihn wirkungslos anzubieten.
        "publishing_enabled": marketplace.publishing_enabled(),
        # Was einer Anzeige gerade im Weg steht, in einem Satz für den
        # Anwender — oder None. Damit die Oberfläche es schon vor dem Lauf
        # sagen kann und nicht erst hinterher.
        "publish_blocker": marketplace.publish_blocker(),
        # Wo der Browser läuft. Davon hängt ab, wohin die Oberfläche den
        # Anwender schickt: auf seinen eigenen Bildschirm oder in die
        # noVNC-Ansicht des Containers.
        "browser_on_host": bool(marketplace.BROWSER_CDP),
        # Läuft dieser Browser gerade? Der Container kann ihn nicht starten —
        # ein Programm auf dem Rechner des Anwenders zu starten ist genau das,
        # was ein Container nicht darf. Also muss die Oberfläche darum bitten.
        "browser_reachable": marketplace.browser_reachable(),
        # Wo die Anmeldung liegt: im Profil des Browsers oder in unserer Datei.
        # Davon hängt ab, was die Oberfläche überhaupt sinnvoll anzeigen kann.
        "session_in_browser": marketplace.session_lives_in_browser(),
    }


class ProfileRequest(BaseModel):
    """Was der Anwender einmal angibt und danach ändern kann."""

    zip_code: str


@api.get("/profile")
def get_profile():
    """Einstellungen des Anwenders.

    Liegt im selben Volume wie die Anmeldung, überlebt also einen Neustart
    der Container. ``complete`` sagt der Oberfläche, ob sie beim ersten
    Aufruf nach den Angaben fragen muss.
    """
    profile = user_profile.load_profile()
    return {
        "zip_code": profile.zip_code,
        "complete": profile.complete,
        "path": str(user_profile.profile_path()),
    }


@api.put("/profile")
def put_profile(request: ProfileRequest):
    try:
        profile = user_profile.save_profile(
            user_profile.Profile(zip_code=request.zip_code.strip())
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"zip_code": profile.zip_code, "complete": profile.complete}


@api.get("/marketplace/session")
def marketplace_session():
    """Stand der gespeicherten Anmeldung — liest nur die Datei, startet nichts."""
    return _session_payload()


@api.delete("/marketplace/session")
def marketplace_session_delete():
    """Verwirft die gespeicherte Anmeldung.

    Nur auf ausdrückliche Anweisung: eine fehlgeschlagene Prüfung allein ist
    kein hinreichender Grund — sie sieht bei einer gesperrten Adresse genauso
    aus wie bei einer wirklich ungültigen Sitzung.
    """
    marketplace.discard_session()
    return _session_payload()


@api.post("/marketplace/session/verify")
def marketplace_session_verify():
    """Ruft eine geschützte Seite auf und schaut, ob die Anmeldung noch trägt.

    Im Unterschied zu GET /marketplace/session startet das einen Browser und
    dauert einige Sekunden. Nur so lässt sich eine serverseitig verworfene
    Sitzung erkennen — die Ablaufzeiten in der Datei sehen dann noch gültig aus.
    """
    status = marketplace.read_session_status()
    # Trägt der Browser die Anmeldung selbst, sagt die Datei nichts aus.
    if not status.usable and not marketplace.session_lives_in_browser():
        raise HTTPException(status_code=409, detail=status.describe())

    try:
        messages = marketplace.verify_session_online()
    except marketplace.SessionExpiredError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {"messages": messages, "session": _session_payload()}


@api.post("/marketplace/login")
def marketplace_login_start():
    """Öffnet das Anmeldefenster in dem Browser, den die Anwendung steuert.

    Das ist der Browser auf dem Rechner des Anwenders, oder in der
    Rückfallvariante der des Containers. Kehrt sofort zurück; der Vorgang
    wartet danach minutenlang auf den Menschen vor dem Fenster.
    """
    # Vorab prüfen statt den Lauf erst im Thread scheitern zu lassen: ohne
    # sichtbaren Browser gibt es nichts zu bedienen, und der Aufrufer soll das
    # sofort erfahren.
    if marketplace.HEADLESS:
        raise HTTPException(
            status_code=409,
            detail=(
                "Kein sichtbarer Browser. Entweder den Browser auf dem eigenen "
                "Rechner starten (uv run python -m scripts.host_browser) oder "
                "für den Browser des Containers KLEINANZEIGEN_VNC=true und "
                "KLEINANZEIGEN_HEADLESS=false setzen."
            ),
        )
    return _login_job.start().as_dict()


@api.get("/marketplace/login")
def marketplace_login_status():
    """Fortschritt des laufenden Anmeldevorgangs."""
    return {**_login_job.snapshot().as_dict(), "session": _session_payload()}


@api.post("/marketplace/session/import")
def marketplace_session_import(file: UploadFile = File(...)):
    """Rückfall: eine anderswo erzeugte Anmeldung übernehmen.

    Gedacht für den Fall, dass die Anmeldung im Container am Anbieter
    scheitert. Die Datei wird erst geprüft und dann übernommen — eine
    unbrauchbare darf keine funktionierende Anmeldung verdrängen.
    """
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        staged = Path(tmp.name)

    try:
        marketplace.import_session(staged)
    except (marketplace.SessionMissingError, marketplace.SessionExpiredError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        staged.unlink(missing_ok=True)

    return _session_payload()


def main():
    """Console-script entry point (`uv run smartselleragent`) — serves the API.

    The container does not use this: it runs the uvicorn CLI directly and binds
    to 0.0.0.0 so the port can be published (see Dockerfile / docker-compose.yml).
    """
    import uvicorn

    uvicorn.run(api, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()