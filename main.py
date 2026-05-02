from smolagents import ToolCallingAgent, OpenAIServerModel, tool, DuckDuckGoSearchTool

# pip install duckduckgo-search
# pip install ddgs

webSearch = DuckDuckGoSearchTool()

model = OpenAIServerModel(
    model_id="qwen3:1.7b",
    api_base="http://localhost:11434/v1",
    api_key="ollama"
)

agent = ToolCallingAgent(
    tools=[webSearch],
    model=model
)

task = """
Bitte suche im Internet nach dem aktuellen Preis für einen gebrauchten 'Ikea Kallax Regal 4x4' auf Kleinanzeigen oder generell.
Nutze dein Suchwerkzeug, um echte Daten zu finden und fasse den durchschnittlichen Preis in einem kurzen Satz zusammen.
"""

print("Agent startet die echte Web-Suche... Das kann einen Moment dauern.")
result = agent.run(task)

print("\n--- Ergebnis des Agenten ---")
print(result)

# Ausgabe: Auf Kleinazeigen liegt der Preis so bei 80 € VB.
#--- Ergebnis des Agenten ---
# Der durchschnittliche Preis für einen gebrauchten IKEA Kallax Regal 4x4 beträgt etwa 86 €.