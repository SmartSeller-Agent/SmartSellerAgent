
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

# Absoluten Pfad relativ zu dieser Datei berechnen
_project_root = Path(__file__).parent.parent  # src/ -> Projektstamm
_image_path = _project_root / "test" / "images" / "Kallax4x4_leer.png"

# Load prompts from YAML file
_prompts_path = _project_root / "src" / "prompts.yaml"
with open(_prompts_path, encoding="utf-8") as f:
    _prompts = yaml.safe_load(f)
custom_instructions = _prompts["instructions"]
tasks = _prompts["tasks"]

webSearch = DuckDuckGoSearchTool()
vision_tool = analyze_product_image
pricing_tool = calculate_margin

model = OpenAIServerModel(
    model_id=TEXT_MODEL_ID,
    api_base=OLLAMA_API_BASE,
    api_key=OLLAMA_API_KEY
)

agent = ToolCallingAgent(
    tools=[webSearch, vision_tool, pricing_tool],
    model=model,
    max_steps=6,    # @TODO: adjust if bigger LLMs are used of increase if the task is more complex
    instructions=custom_instructions,
)

# Choose the task you want the agent to solve by selecting the corresponding prompt from the loaded YAML file
task = tasks["margin_check"]

def main():
    print("The agent is starting the actual web search... This may take a moment.")
    try:
        result = agent.run(task)
        print("\n--- Agent's result ---")
        print(result)
    finally:
        tracer_provider.shutdown()  # flushes all buffered spans before exit

if __name__ == "__main__":
    main()

# Ausgabe: Auf Kleinazeigen liegt der Preis so bei 80 € VB.
#--- Ergebnis des Agenten ---
# Der durchschnittliche Preis für einen gebrauchten IKEA Kallax Regal 4x4 beträgt etwa 86 €.