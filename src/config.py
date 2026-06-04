# Konfiguration für Ollama und die Modelle
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434/v1")
OLLAMA_API_KEY  = os.getenv("OLLAMA_API_KEY", "ollama")
TEXT_MODEL_ID   = os.getenv("TEXT_MODEL_ID", "qwen3:1.7b")
VISION_MODEL_ID = os.getenv("VISION_MODEL_ID", "llava")
