# -------------------------- Imports --------------------------
from contextlib import asynccontextmanager
from pathlib import Path
import yaml
from fastapi import FastAPI, HTTPException
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

# --- Orchestrator: owns the end-to-end resale evaluation workflow ---
orchestrator = ToolCallingAgent(
    tools=[webSearch, pricing_tool],
    model=model,
    managed_agents=[vision_agent],
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

@api.get("/health")
def health_check():
    return {"status": "ok", "message": "Der SmartSeller Agent läuft!"}

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

    try:
        # 3. Das Multi-Agent-System (orchestrator) mit dem fertigen Task starten
        result = orchestrator.run(final_task)
        return {"task": request.task_name, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Console-script entry point (`uv run smartselleragent`) — serves the API.

    The container does not use this: it runs the uvicorn CLI directly and binds
    to 0.0.0.0 so the port can be published (see Dockerfile / docker-compose.yml).
    """
    import uvicorn

    uvicorn.run(api, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()