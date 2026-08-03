import streamlit as st
import requests
from pathlib import Path

# --- Konfiguration ---
API_URL = "http://127.0.0.1:8000/run-task"

# Ordner für Datei-Uploads anlegen
UPLOAD_DIR = Path("test/images/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Benutzeroberfläche ---
st.set_page_config(page_title="SmartSeller Agent", page_icon="🛍️")
st.title("🛍️ SmartSeller")

st.write("Lade ein Bild deines Artikels hoch. Der Agent erkennt das Produkt, recherchiert Marktpreise und schreibt eine fertige Anzeige!")

# 1. Datei-Upload
uploaded_file = st.file_uploader("Produktbild hochladen (JPG/PNG)", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    # Bild anzeigen
    st.image(uploaded_file, caption="Dein Produkt", use_container_width=True)
    
    # 2. Button zum Starten
    if st.button("Verkaufsanzeige generieren"):
        with st.spinner("Agent arbeitet: Analysiert Bild und recherchiert Preise im Web..."):
            
            # Da unser FastAPI-Backend einen Dateipfad erwartet, speichern wir das Bild kurz ab
            file_path = UPLOAD_DIR / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # 3. Daten für die API vorbereiten
            payload = {
                "task_name": "create_listing", # Nutzt euren neuen Task aus der YAML
                "image_path": str(file_path.absolute()),
                "purchase_price": 0.0
            }
            
            # 4. Anfrage an das Backend senden
            try:
                response = requests.post(API_URL, json=payload)
                response.raise_for_status() # Prüft, ob es einen Fehler gab
                result_data = response.json()
                
                # 5. Ergebnis präsentieren
                st.success("Anzeige erfolgreich generiert!")
                st.markdown("### Dein Anzeigentext:")
                st.info(result_data.get("result", "Kein Text generiert."))
                
            except requests.exceptions.RequestException as e:
                st.error(f"Fehler bei der Kommunikation mit dem Backend: {e}")