import os

# Muss vor dem ersten Import von src.config stehen: die Schlüssel aus einer
# lokalen .env würden sonst einen echten Trace-Exporter gegen die
# Langfuse-Instanz aufsetzen, nur weil die Tests src.app importieren.
# load_dotenv() überschreibt bereits gesetzte Variablen nicht.
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
