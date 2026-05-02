from smolagents import ToolCallingAgent, OpenAIServerModel, tool

@tool
def get_market_price(product_name: str) -> str:
    """
    Sucht den aktuellen Marktpreis für ein Second-Hand-Produkt.

    Args:
        product_name: Der Name des Produkts, für das der Preis gesucht wird.
    """
    return f"Der Marktpreis für '{product_name}' liegt aktuell bei 45 Euro."

model = OpenAIServerModel(
    model_id="qwen3:1.7b",
    api_base="http://localhost:11434/v1",
    api_key="ollama"
)

agent = ToolCallingAgent(
    tools=[get_market_price],
    model=model
)

# P2 ist 3 vollständige TAO-Schritte
task = """
Ich löse mein Homeoffice auf. Bitte finde nacheinander die Marktpreise für folgende drei Dinge heraus:
1. Schreibtisch
2. Bürostuhl
3. Tischlampe

Nutze für jeden Gegenstand einzeln dein Werkzeug und fasse die Ergebnisse am Ende in einer kurzen Anzeige zusammen.
"""

result = agent.run(task)
print("\n--- Ergebnis des Agenten ---")
print(result)