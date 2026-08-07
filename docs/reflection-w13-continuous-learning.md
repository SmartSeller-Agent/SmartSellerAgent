# W13: Continual Learning (Konzept)

> Wahlpflichtanforderung W13 (VL 12): *Wie könnte das System mithilfe neuer Daten
> verbessert werden?* Verlangt ist ein Konzept, keine Implementierung.

## Worum es geht

Continual Learning beschreibt die Fähigkeit eines Systems, sich über die Zeit an
neue Daten, neue Muster und veränderte Bedingungen anzupassen, ohne dafür
komplett neu aufgebaut werden zu müssen. Für den SmartSellerAgent ist das
naheliegend, weil Marktpreise, Produktangebote und das Verhalten der
Verkaufsplattform alles andere als statisch sind. Wie stark sich diese Dinge
verschieben, ist in [W12](reflection-w12-drift.md) beschrieben.

Eine Einschränkung vorweg, die für dieses Projekt entscheidend ist: Das System
trainiert kein eigenes Modell. Es benutzt zugekaufte Sprach- und Vision-Modelle
und steuert sie über Prompts und Werkzeuge. „Lernen" heißt hier deshalb in erster
Linie **besser instruieren und besser nachschlagen**, nicht Gewichte anpassen.
Alles andere wäre für ein Studienprojekt eine Behauptung, die weder die Hardware
noch die verfügbare Datenmenge decken würde.

## Welche Daten heute schon entstehen

Ein realistisches Konzept beginnt bei dem, was ohnehin anfällt:

- **Langfuse-Traces** (`src/tracing.py`): jeder Lauf mit Eingabe, allen
  Werkzeugaufrufen, Zwischenschritten und Endergebnis.
- **Die hochgeladenen Fotos** im `uploads`-Volume.
- **Die erzeugten Anzeigentexte** samt Preisvorschlag.
- **Der Screenshot des ausgefüllten Formulars** vor dem Absenden.
- **Das Veröffentlichungsprotokoll** (`publish_attempts`), also das, was das
  Werkzeug tatsächlich getan hat, unabhängig davon, was das Modell darüber
  erzählt.

Was vollständig fehlt, ist das **Ergebnis**. Wurde der Artikel verkauft? Zu
welchem Preis? Wie lange stand die Anzeige online? Genau dieses Signal wäre für
eine Preisempfehlung das wertvollste überhaupt, und der Marktplatz meldet es
nicht zurück. Diese Lücke ist der interessante Teil der Frage.

## Wo ein Rückkanal realistisch entstehen könnte

**Die stärkste Quelle liegt bereits im System, wird aber nicht erfasst.** Seit
einer der letzten Änderungen bleibt das ausgefüllte Formular im Browser stehen,
statt sofort abgeschickt zu werden. Der Mensch sieht die fertige Anzeige, kann
sie korrigieren und veröffentlicht selbst. Damit entsteht bei jedem Lauf ein
Vergleichspaar: der vom Agenten erzeugte Text und der Text, den ein Mensch
tatsächlich für gut genug hielt. Die Differenz zwischen beiden ist das
ehrlichste Lernsignal, das dieses System hat. Sie ist nicht erfragt, nicht durch
eine Bewertungsskala verzerrt und fällt ohne jeden Zusatzaufwand an. Erfassen
ließe sie sich mit überschaubarem Aufwand, indem das Formular vor dem Absenden
noch einmal ausgelesen und mit dem generierten Vorschlag verglichen wird.

Daneben wären zwei weitere Quellen denkbar:

- **Explizites Feedback** über einen Daumen hoch oder runter, oder ein
  Korrekturfeld für den Preis in der Streamlit-Oberfläche. Billig umzusetzen,
  aber Nutzer bewerten ungern, und wer bewertet, tut es selten repräsentativ.
- **Externes Feedback** in Form des tatsächlichen Verkaufspreises. Das wäre am
  wertvollsten und ist praktisch nicht zu bekommen, da die Plattform keine
  Schnittstelle anbietet.

## Welche Hebel es gibt

Die Möglichkeiten unterscheiden sich enorm im Aufwand, und das sollte man nicht
verwischen.

**Prompt-Verbesserung.** Der billigste Hebel, und der einzige, den wir in diesem
Projekt tatsächlich benutzt haben. Zwei Beispiele aus der Entwicklung: Der
Orchestrator verfing sich wiederholt in Websuchen und erreichte sein
Schrittlimit, bevor er zum eigentlichen Ziel kam. Daraufhin wurde eine
Obergrenze von zwei Suchen in `src/prompts.yaml` aufgenommen, versehen mit einer
Begründung statt einer bloßen Anordnung. Im zweiten Fall beschönigte er den
Status einer nicht erfolgten Veröffentlichung. Daraufhin verlangt die Vorlage nun
die wörtliche Übernahme der Werkzeugmeldung und bietet ausdrücklich die
Formulierung „Nicht eingestellt." an. Beides sind Fehlerfälle, die zu einer
dauerhaften Verbesserung geführt haben.

Wichtig ist dabei die ehrliche Einordnung: Gelernt hat nicht das System, sondern
der Entwickler. Der Kreis wurde von Hand geschlossen. Ein
Continual-Learning-Konzept für dieses Projekt bedeutet daher vor allem, **diesen
bereits gelebten Kreislauf zu systematisieren**, also Fehlerfälle gezielt aus den
Traces zu sammeln, statt sie zufällig beim Zuschauen zu bemerken.

**Few-Shot-Beispiele.** Erfolgreiche Anzeigen als Beispiele in den Prompt
aufnehmen. Mittlerer Aufwand, wirkt sofort, kostet aber Kontextfenster. Bei den
lokal betriebenen kleinen Modellen ist das ein knappes Gut.

**Retrieval beziehungsweise RAG.** Eine Wissensbasis aus vergangenen Bewertungen
aufbauen und den Agenten selbst darin nachschlagen lassen, etwa nach dem Muster
„für ein vergleichbares Regal wurden vor drei Wochen 45 € angesetzt". Das wäre
der fachlich sinnvollste Ausbau, weil er genau die Schwäche adressiert, die in
W12 beschrieben ist, nämlich das eingefrorene Preisgefühl des Modells. Nebenbei
würde er die derzeit nicht erfüllten Anforderungen W3 und W4 abdecken.

**Fine-Tuning.** Der teuerste Weg, mit dem größten Datenbedarf. Für ein
8B-Modell auf der hier verfügbaren Hardware ist er unrealistisch. Die Messungen
in [performance.md](performance.md) zeigen 3,6 Minuten pro Modellaufruf bei
reiner CPU-Inferenz. Das sollte man aussprechen, statt Fine-Tuning als Ausblick
zu behaupten.

## Risiken eines Rückkanals

Ein System darf neue Daten nicht blind übernehmen. Lernt es aus der eigenen
Ausgabe, verstärkt es seine eigenen Verzerrungen. Schlägt der Agent systematisch
zu niedrige Preise vor und die Nutzer akzeptieren sie, weil der Artikel dann
schnell weggeht, bestätigen die gesammelten Daten genau diese zu niedrigen
Preise. Ein schneller Verkauf ist eben kein Beleg für einen guten Preis, sondern
eher ein Hinweis auf einen zu niedrigen.

Dagegen hülfe, das Signal nicht ausschließlich aus dem eigenen Kreislauf zu
ziehen. Man könnte die akzeptierten Preise regelmäßig gegen unabhängig
recherchierte Marktpreise prüfen und einen Teil der Läufe bewusst ohne Beispiele
aus der eigenen Historie laufen lassen, um eine Vergleichsgröße zu behalten.

Ebenso wichtig ist die Balance zwischen Anpassungsfähigkeit und Stabilität. Neue
Erkenntnisse sollten aufgenommen werden, ohne dass frühere und weiterhin gültige
Muster verloren gehen. Ein schrittweiser, kontrollierter Prozess mit Validierung
gegen eine feste Prüfmenge wäre dafür der passende Rahmen. Es wäre dieselbe
Prüfmenge, die in W12 zur Drift-Erkennung vorgeschlagen wird.

## Fazit

Für dieses System ist Continual Learning kein Trainingsproblem, sondern ein
Erfassungsproblem. Die wertvollsten Signale entstehen bereits, nämlich die
Korrekturen des Menschen am fertigen Formular, und gehen ungenutzt verloren. Sie
aufzuzeichnen und daraus systematisch die Prompts und in einem zweiten Schritt
eine durchsuchbare Wissensbasis vergangener Bewertungen zu speisen, wäre der
realistische Weg, das System mit der Zeit besser zu machen.
