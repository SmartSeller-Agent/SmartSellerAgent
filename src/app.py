
# -------------------------- Imports --------------------------
from pathlib import Path
import yaml

# Imports: Agents
from smolagents import ToolCallingAgent, OpenAIServerModel, DuckDuckGoSearchTool

# Imports: Config, API Keys
from src.config import OLLAMA_API_BASE, OLLAMA_API_KEY, TEXT_MODEL_ID

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

# Calculate the absolute path relative to this file
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
    api_base=OLLAMA_API_BASE,
    api_key=OLLAMA_API_KEY
)

# --- Subagent: analyzes product photos only ---
vision_agent = ToolCallingAgent(
    tools=[vision_tool],
    model=model,
    instructions=_prompts["vision_agent"]["instructions"],
    max_steps=4,
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
    name="orchestrator",
    description="Coordinates the end-to-end resale evaluation: image analysis, price research, margin calculation and recommendation.",
)

# Build the task: full multi-agent workflow over the sample image
task = _prompts["orchestrator"]["tasks"]["full_evaluation"].format(
    image_path=_image_path,
    purchase_price=20,
)

def main():
    print("Smart Seller Agent is starting the evaluation... This may take a moment.")
    try:
        result = orchestrator.run(task)
        print("\n--- Agent's result ---")
        print(result)
    finally:
        tracer_provider.shutdown()  # flushes all buffered spans before exit

if __name__ == "__main__":
    main()

# Ausgabe: Auf Kleinazeigen liegt der Preis so bei 80 € VB.
#--- Ergebnis des Agenten ---
# Der durchschnittliche Preis für einen gebrauchten IKEA Kallax Regal 4x4 beträgt etwa 86 €.