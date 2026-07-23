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
cd projektname
uv sync          # erstellt .venv und installiert ALLE Abhängigkeiten
cp .env.example .env   # danach echte Werte (HF_TOKEN etc.) eintragen
```

> ⚠️ Die `.env` niemals committen – sie steht in der `.gitignore`.
> Das `.venv` ebenfalls nicht committen.

## 2. Projekt ausführen

Wir nutzen kein manuelles `activate` – alles läuft über `uv run`:

```bash
uv run uvicorn src.api:app --reload   # API starten
uv run python -m src.app              # Agent direkt per CLI
uv run smartselleragent               # Agent per CLI (smolagents-Toolkit)
uv run pytest                         # Tests (not implemented yet)
```

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
