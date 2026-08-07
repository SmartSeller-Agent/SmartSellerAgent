# Mitarbeit / Entwicklungs-Setup

Interne Anleitung für unser Team. Wie du das Projekt lokal zum Laufen bringst,
neue Pakete hinzufügst und unseren Branch-Workflow einhältst.

## 1. Einmaliges Setup

`uv` installieren (falls noch nicht vorhanden):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Repo klonen und Umgebung aufbauen:

```bash
git clone <REPO-URL>
cd SmartSellerAgent
uv sync                # erstellt .venv und installiert ALLE Abhängigkeiten
cp .env.example .env   # danach echte Werte eintragen (siehe Kommentare dort)
```

> ⚠️ Die `.env` niemals committen – sie steht in der `.gitignore`.
> Das `.venv` ebenfalls nicht committen.

## 2. Projekt ausführen

Wir nutzen kein manuelles `activate` – alles läuft über `uv run`.

Für den reinen Betrieb ist Docker der richtige Weg (siehe [README.md](../README.md)).
Der Weg hier ist der Entwicklungspfad: Codeänderungen wirken sofort, statt jedes
Mal ein Image neu zu bauen. Es ist außerdem das Setup, das auch die CI benutzt
([ci.yml](../.github/workflows/ci.yml) fährt `uv sync` + `uv run pytest`, kein Docker).

```bash
uv run pytest                              # Tests
uv run ruff check src/                     # Linter
```

Backend und Frontend sind zwei Prozesse und brauchen zwei Terminals:

```bash
# Terminal 1 – API auf http://127.0.0.1:8000 (--reload startet bei Codeänderung neu)
uv run uvicorn src.app:api --reload

# Terminal 2 – UI auf http://localhost:8501
uv run streamlit run src/frontend.py
```

> Achtung auf die Reihenfolge im Modulpfad: Das Modul heißt `src.app`, die
> FastAPI-Instanz darin `api` – also `src.app:api`. Ein `src/api.py` gibt es nicht.

`uv run smartselleragent` startet die API ebenfalls (der Entry Point aus
[pyproject.toml](../pyproject.toml)), allerdings ohne `--reload`.

**Läuft das Backend?** http://127.0.0.1:8000/health im Browser öffnen – dort muss
`{"status":"ok", "message":"Der SmartSeller Agent läuft!"}` stehen. Die
interaktive API-Doku liegt unter http://127.0.0.1:8000/docs.

**Welche Modelle?** Das entscheidet die `.env`. Mit den `OPENROUTER_*`-Werten und
`TEXT_API_BASE=https://openrouter.ai/api/v1` brauchst du **kein lokales Ollama** –
das ist der schnellste Weg, am Code zu arbeiten. Zeigt `TEXT_API_BASE` dagegen auf
`http://localhost:11434/v1`, muss Ollama auf dem Rechner installiert sein und die
Modelle müssen bereits gezogen sein.

Das Frontend spricht standardmäßig mit `http://127.0.0.1:8000`; überschreibbar
über `API_BASE_URL` (genau das macht das Docker-Setup).

## 3. Neue Pakete hinzufügen

**Wichtig:** Pakete nicht mit `pip install` installieren, sondern immer mit `uv add`.
`uv add` macht alles in einem Schritt: Eintrag in `pyproject.toml`, Auflösung in
`uv.lock` **und** Installation ins `.venv`.

```bash
uv add fastapi               # normale Abhängigkeit
uv add "smolagents[toolkit]" # mit Extra
uv add --dev pytest          # nur fürs Entwickeln/Testen (Dev-Dependency)
```

Paket wieder entfernen:

```bash
uv remove paketname
```

Nach einem `uv add` **immer** die geänderten Dateien committen, damit alle dieselbe
Umgebung bekomme:

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add fastapi"
```

Wenn du etwas hinzugefügt habe und du es übernehmen willst, reicht:

```bash
git pull
uv sync   # zieht die neuen Pakete nach
```

## 4. Branch-Workflow

- Default-Branch ist **`develop`** – von hier abzweigen.
- Pro Aufgabe einen **Feature-Branch**, am besten direkt aus dem GitHub-Issue
  erstellt ("Development → Create a branch").

```bash
git switch develop
git pull
git switch -c feature/kurzer-name
# ... arbeiten, committen ...
git push -u origin feature/kurzer-name
```

- Dann **Pull Request nach `develop`**. Diesen darfst du selbst mergen
  (kein fremdes Approval nötig).
- Merges nach **`main`** laufen nur per PR von `develop` und brauchen die
  Freigabe der jeweils anderen Person. Bitte dort vorher kurz Bescheid geben.

## 5. Vor jedem Push kurz prüfen

```bash
uv run pytest        # laufen die Tests?
git status           # keine .env / keine .venv dabei?
```
