import os

# Muss vor dem ersten Import von src.config stehen, denn dort wird .env
# gelesen. Tests dürfen nicht davon abhängen, was auf dem Rechner des
# Entwicklers gerade eingestellt ist — sonst laufen sie hier anders als in der
# CI, und ein grüner Lauf sagt nichts.
#
# load_dotenv() überschreibt bereits gesetzte Variablen nicht, ein leerer Wert
# hier gewinnt also gegen den Eintrag in der .env.

# Sonst würden die Tests einen echten Trace-Exporter gegen die Langfuse-Instanz
# aufsetzen, nur weil sie src.app importieren.
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""

# Sonst hielten die Tests einen Browser auf dem Host für vorhanden und
# übersprängen Prüfungen, die es ohne ihn geben muss.
os.environ["KLEINANZEIGEN_BROWSER_CDP"] = ""

# Die Freigabe zum Veröffentlichen setzen die Tests selbst, wo sie sie brauchen.
os.environ["KLEINANZEIGEN_ALLOW_PUBLISH"] = ""

# Zusätzliche Browser-Parameter sind ein Werkzeug für Versuche und haben in
# einem Testlauf nichts verloren.
os.environ["KLEINANZEIGEN_BROWSER_ARGS"] = ""
