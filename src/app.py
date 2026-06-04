import os
from pathlib import Path

from smolagents import ToolCallingAgent, OpenAIServerModel, tool, DuckDuckGoSearchTool

from src.config import OLLAMA_API_BASE, OLLAMA_API_KEY, TEXT_MODEL_ID
from src.tools.vision import analyze_product_image

# Absoluten Pfad relativ zu dieser Datei berechnen
_project_root = Path(__file__).parent.parent  # src/ -> Projektstamm
_image_path = _project_root / "test" / "images" / "Kallax4x4_leer.png"

webSearch = DuckDuckGoSearchTool()
vision_tool = analyze_product_image

model = OpenAIServerModel(
    model_id=TEXT_MODEL_ID,
    api_base=OLLAMA_API_BASE,
    api_key=OLLAMA_API_KEY
)

agent = ToolCallingAgent(
    tools=[webSearch, vision_tool],
    model=model
)

task = f"""
First, analyse the image located at the path '{_image_path}' using your vision tool to identify which product it 
is.
Then use the search tool to find the current second-hand price for this identified product on the internet.
Finally, give me a brief summary of which product it is and what the average price for 
this product is on classified ad sites. Please reply in German and in euros.
"""

def main():
    print("The agent is starting the actual web search... This may take a moment.")
    result = agent.run(task)
    print("\n--- Agent's result ---")
    print(result)

if __name__ == "__main__":
    main()

# Ausgabe: Auf Kleinazeigen liegt der Preis so bei 80 € VB.
#--- Ergebnis des Agenten ---
# Der durchschnittliche Preis für einen gebrauchten IKEA Kallax Regal 4x4 beträgt etwa 86 €.