# Konfiguration für Ollama und die Modelle
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434/v1")
OLLAMA_API_KEY  = os.getenv("OLLAMA_API_KEY", "ollama")
TEXT_MODEL_ID   = os.getenv("TEXT_MODEL_ID", "qwen3:8b")
VISION_MODEL_ID = os.getenv("VISION_MODEL_ID", "llava")

# Configuration for langfuse and open telemetry
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST       = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")