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
            "prompt": "Du bist ein Experte, der Gegenstände erkennen kann. Auf dem Bild ist ein Gegenstand. Nenne mir nur den Namen des Gegenstands "
            "und die Marke (z. B. IKEA Kallax, Cube Fahrrad, IPhone 10, T-Shirt, etc.). Antworte extrem kurz und präzise.",
            "stream": False,
            "images": [base64_image]
        }
        
        response = requests.post("http://localhost:11434/api/generate", json=payload)
        response_json = response.json()
        
        # Rückgabe des erkannten Texts an die Agentin
        return response_json.get("response", "Das Produkt konnte leider nicht erkannt werden.")
        
    except Exception as e:
        return f"Fehler bei der Bildanalyse: {str(e)}"