import base64
import requests
from smolagents import tool

@tool
def analyze_product_image(image_path: str) -> str:
    """
    Analysiert ein hochgeladenes Produktbild und erkennt, um welchen Verkaufsartikel es sich handelt.

    Args:
        image_path: Der lokale Dateipfad zu dem Bild, das analysiert werden soll.
    """
    try:
        # 1. Bild einlesen und in Base64 kodieren
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
        
        # 2. Anfrage an die lokale Ollama-API mit dem Vision-Modell 'llava'
        payload = {
            "model": "llava",
            "prompt": "Was für ein Produkt ist auf diesem Bild zu sehen? Nenne kurz den genauen Produktnamen und die Marke.",
            "stream": False,
            "images": [base64_image]
        }
        
        response = requests.post("http://localhost:11434/api/generate", json=payload)
        response_json = response.json()
        
        # Rückgabe des erkannten Texts an die Agentin
        return response_json.get("response", "Das Produkt konnte leider nicht erkannt werden.")
        
    except Exception as e:
        return f"Fehler bei der Bildanalyse: {str(e)}"