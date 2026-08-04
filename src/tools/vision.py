import base64
import mimetypes
import os
import requests
from smolagents import tool
from src.config import VISION_MODEL_ID, VISION_API_BASE, VISION_API_KEY

# (connect, read) in Sekunden. Ein gehosteter Provider antwortet in Sekunden,
# lokale CPU-Inferenz kann Minuten brauchen — der Lesetimeout ist deshalb
# großzügig. Er verhindert aber, dass ein Aufruf unbegrenzt hängen bleibt.
_TIMEOUT = (10, int(os.getenv("VISION_TIMEOUT_S", "600")))

@tool
def analyze_product_image(image_path: str) -> str:
    """
    Analysiert ein hochgeladenes Produktbild und erkennt, um welchen Verkaufsartikel es sich handelt.

    Args:
        image_path: Der lokale Dateipfad zu dem Bild, das analysiert werden soll.
    """
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")

        mime_type, _ = mimetypes.guess_type(image_path)
        mime_type = mime_type or "image/png"

        payload = {
            "model": VISION_MODEL_ID,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                        },
                        {
                            "type": "text",
                            "text": "Du bist ein Experte, der Gegenstände erkennen kann. Auf dem Bild ist ein Gegenstand. Nenne mir nur den Namen des Gegenstands "
                            "und die Marke (z. B. IKEA Kallax, Cube Fahrrad, IPhone 10, T-Shirt, etc.). Antworte extrem kurz und präzise.",
                        },
                    ],
                }
            ],
        }

        headers = {"Authorization": f"Bearer {VISION_API_KEY}"}
        if "openrouter.ai" in VISION_API_BASE:
            # Von OpenRouter empfohlen: ordnet die Nutzung im Dashboard dieser App zu.
            headers["HTTP-Referer"] = "https://github.com/SmartSeller-Agent/SmartSellerAgent"
            headers["X-Title"] = "SmartSellerAgent"

        response = requests.post(
            f"{VISION_API_BASE}/chat/completions",
            json=payload,
            headers=headers,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    except requests.HTTPError as e:
        # Antworttext mitgeben, sofern vorhanden — Provider erklären hier, was
        # falsch war (falsches Modell-Slug, kein Guthaben, ungültiger Key).
        body = getattr(getattr(e, "response", None), "text", "") or ""
        detail = f" — {body[:300]}" if body else ""
        return f"Fehler bei der Bildanalyse: {e}{detail}"
    except Exception as e:
        return f"Fehler bei der Bildanalyse: {str(e)}"
