# SmartSellerAgent

## Description
@TODO: Add a brief description of the project.

## Requirements
- Python (Version see `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) as a package and environment manager (see [Install `uv`](#install-uv))

### Install `uv`
If not already installed, you can install `uv` using the following commands:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Alternatively, via pip
pip install uv
```

## Installation
Clone the repository and install dependencies:

```bash
git clone <REPO-URL>
cd projectname
uv sync
```

## Configuration
### API Keys

Copy the `.env.example` file to `.env` and fill in your API keys:

​```bash
cp .env.example .env
​```

| Variable             | Mandatory  | Description                                       |
|----------------------|------------|---------------------------------------------------|
| `HF_TOKEN`           | ❌         | Token for the HF Inference API                    |
| `MODEL_ID`           | ❌         | Overrides the default model                         |
| `OPENAI_API_KEY`     | ❌         | Only needed when using LiteLLM models               |
| `LANGFUSE_PUBLIC_KEY`| ❌         | Tracing via Langfuse (W5: see [requirements.md](requirements.md))|
| `LANGFUSE_SECRET_KEY`| ❌         | Tracing via Langfuse (W5: see [requirements.md](requirements.md))|

## Architecture Overview
@TODO: Add a brief architecture overview.