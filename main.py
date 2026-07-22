from smolagents import ToolCallingAgent, OpenAIServerModel, tool, DuckDuckGoSearchTool

from config import OLLAMA_API_BASE, OLLAMA_API_KEY, TEXT_MODEL_ID
from tools.vision import analyze_product_image

# pip install duckduckgo-search
# pip install ddgs
# ollama pull llava
# pip install requests

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

image_path = "test/images/Kallax4x4_leer.png"

task = f"""
Du bist ein professionelle*r Verkaufsassistent*in. Gehe zwingend Schritt für Schritt vor und rufe nicht mehrere Tools gleichzeitig auf!

Schritt 1: Nutze das Vision-Tool mit dem Dateipfad '{image_path}', um das Produkt zu erkennen.
Schritt 2: WARTE auf die Antwort des Vision-Tools. Nutze unter keinen Umständen den Dateinamen für deine Websuche!
Schritt 3: Bilde einen sinnvollen Suchbegriff aus dem erkannten Produkt (z. B. "IKEA Kallax 4x4 gebraucht Preis"). Suche damit im Internet nach aktuellen Preisen auf Kleinanzeigen.
Schritt 4: Erstelle eine kurze Zusammenfassung auf Deutsch. Nenne das Produkt und den durchschnittlichen Gebrauchtpreis in Euro.
"""

if __name__ == "__main__":
    print("Agent startet... Der TAO-Zyklus (Thought, Action, Observation) wird nun im Terminal mitgeloggt.")
    result = agent.run(task)

    print("\n--- Ergebnis des Agenten ---")
    print(result)

# Ausgabe: Auf Kleinazeigen liegt der Preis so bei 80 € VB.
#--- Ergebnis des Agenten ---
# Der durchschnittliche Preis für einen gebrauchten IKEA Kallax Regal 4x4 beträgt etwa 86 €.