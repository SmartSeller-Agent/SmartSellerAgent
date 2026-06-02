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

task = """
Analysiere zuerst das Bild unter dem Pfad 'testBilder/Kallax4x4_leer.png' mit deinem Vision-Tool, um herauszufinden, um welches Produkt es 
sich handelt.
Suche anschließend mit dem Suchwerkzeug nach dem aktuellen Gebrauchtpreis für dieses erkannte Produkt im Internet.
Gebe mir am Ende eine kurze Zusammenfassung, um welches Produkt es sich handelt und wie hoch der durchschnittliche Preis für 
dieses Produkt auf Kleinanzeigen ist. Bitte antworte auf deutsch und in Euro.
"""

if __name__ == "__main__":
    print("Agent startet die echte Web-Suche... Das kann einen Moment dauern.")
    result = agent.run(task)

    print("\n--- Ergebnis des Agenten ---")
    print(result)

# Ausgabe: Auf Kleinazeigen liegt der Preis so bei 80 € VB.
#--- Ergebnis des Agenten ---
# Der durchschnittliche Preis für einen gebrauchten IKEA Kallax Regal 4x4 beträgt etwa 86 €.