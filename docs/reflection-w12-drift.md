# W12: Reflexion zu Data und Concept Drift

> Wahlpflichtanforderung W12 (VL 11): *Wie könnte sich Drift auf das System
> auswirken? Was würde man bemerken?*

## Zwei Arten von Drift

Data Drift und Concept Drift können ein System erheblich beeinflussen, weil sie
die Grundlage verändern, auf der es seine Entscheidungen trifft. Von Data Drift
spricht man, wenn sich die Datenverteilung im Lauf der Zeit verschiebt, also
andere Produkte, andere Fotos oder andere Nutzergruppen auftreten. Concept Drift
wiegt schwerer. Hier sehen die Daten nicht nur anders aus, sondern die Beziehung
zwischen Eingabe und richtigem Ergebnis hat sich verändert. Ein Zusammenhang, der
früher verlässlich war, gilt einfach nicht mehr. Für ein System, das
Gebrauchtpreise schätzt, bedeutet das, dass es weiter auf alten Annahmen
aufbaut, obwohl sich die Realität längst verschoben hat.

Der SmartSellerAgent trainiert selbst kein Modell. Daraus könnte man schließen,
dass ihn Drift nicht betrifft. Tatsächlich ist eher das Gegenteil der Fall. Weil
das System fast vollständig aus zugekauften Bausteinen besteht, nämlich einem
Sprachmodell, einem Vision-Modell, einer Websuche und einer fremden Website,
liegen sämtliche Driftquellen außerhalb des eigenen Codes. Sie lassen sich
deshalb auch nicht durch ein erneutes Training beheben.

## Wo Drift in diesem System eintritt

**Preise.** Der Wiederverkaufswert eines gebrauchten Kallax-Regals ist in zwei
Jahren ein anderer als heute. Die Websuche liefert zwar aktuelle Anzeigen, aber
das Preisgefühl des Sprachmodells ist auf dem Stand seines Trainings eingefroren.
Verschärft wird das durch eine bewusste Entscheidung im Projekt: Der
Orchestrator darf höchstens zwei Suchen pro Auftrag durchführen, weil er sich
sonst im Schrittbudget verliert. Damit haben wir Aktualität gegen
Zuverlässigkeit getauscht. Je weniger recherchiert wird, desto stärker wiegt das
veraltete Wissen des Modells.

**Produkte und Fotos.** Neue Geräte, neue Marken, eingestellte Serien. Was das
Vision-Modell mit einem Produkt macht, das es noch nie gesehen hat, ist nicht
vorhersagbar. Sicher ist nur, dass es antwortet, und zwar in demselben
souveränen Ton wie bei einem bekannten Produkt. Auch Kameraqualität,
Bildausschnitt und Lichtverhältnisse verändern sich über die Jahre.

**Die fremde Website.** Das ist im Rückblick der stillste und zugleich
gefährlichste Kanal. Kleinanzeigen.de bietet keine Schnittstelle an, deshalb
steuert das System das echte Formular über fest verdrahtete Selektoren wie
`#gdpr-banner-accept` oder `#ad-price-type`. Jede Änderung am Seitenaufbau bricht
das Werkzeug. Während der Entwicklung ist uns das mehrfach passiert. Der
Versandbereich existiert im DOM erst, nachdem eine Kategorie gewählt wurde, und
die Erkennung der Login-Seite prüfte zunächst nur auf `m-einloggen`, während der
tatsächliche Dienst unter `login.kleinanzeigen.de` läuft. Beides waren keine
Programmierfehler im engeren Sinn, sondern falsche Annahmen über eine Seite, die
uns nicht gehört.

**Das Verhalten des Anbieters.** Auch die Gegenseite verändert sich, und zwar
absichtlich. Im Verlauf der Entwicklung tauchte eine Sicherheitsabfrage auf,
verschwand nach einer Änderung der Browser-Startparameter wieder, und
schließlich sperrte der Anbieter den IP-Bereich des Containers für Anmeldungen.
Das ist Drift in einer Umgebung, die aktiv gegen Automatisierung arbeitet.

**Die Modelle selbst.** `qwen/qwen3-8b` kann bei OpenRouter unter demselben Namen
aktualisiert oder abgeschaltet werden. Das Verhalten ändert sich dann, ohne dass
im Repository eine einzige Zeile anders wäre.

## Was auffallen würde und was nicht

Die unangenehme Frage ist, welche dieser Verschiebungen man tatsächlich *sähe*.

Laute Fehler melden sich von selbst. Ein Selektor greift nicht, das Formular
läuft in einen Timeout, die Anmeldung wird abgelehnt, die Schnittstelle
antwortet mit HTTP 500. Genau diese Klasse ist uns im Projekt regelmäßig
begegnet, und sie ist vergleichsweise harmlos, weil sie den Lauf abbricht statt
ihn zu verfälschen.

Das eigentliche Problem sind die leisen Fehler. Liegt der geschätzte Preis
30 Prozent daneben, klingt die Anzeige veraltet oder erkennt das Vision-Modell
ein neues Produkt selbstbewusst falsch, dann bemerkt das im aktuellen System
schlicht **niemand**. Es gibt keine Grundwahrheit, gegen die verglichen werden
könnte, und das Ergebnis sieht in jedem Fall plausibel aus.

Ein Vorfall aus der Entwicklung zeigt das exemplarisch, auch wenn seine Ursache
keine Drift war. Der Orchestrator verbrauchte sein Schrittbudget in Websuchen,
musste eine Schlussantwort liefern und behauptete darin, die Anzeige sei
veröffentlicht worden. Tatsächlich war nichts geschehen. Die Antwort war
formvollendet und vollständig falsch. Daraus haben wir eine allgemeine Lehre
gezogen, die auch für Drift gilt: **Man darf nicht der Erzählung des Systems
glauben, sondern muss messen, was wirklich passiert ist.** Seither führt das
Veröffentlichungswerkzeug ein eigenes Protokoll (`publish_attempts`), und die
Oberfläche zeigt dieses Protokoll statt der Zusammenfassung des Modells.

## Was sich mit dem Vorhandenen beobachten ließe

Die Langfuse-Traces zeichnen bereits jeden Lauf mit Eingaben, Werkzeugaufrufen,
Schrittzahl und Endergebnis auf. Daraus ließen sich ohne neue Infrastruktur zwei
Frühwarnzeichen ableiten. Eine steigende durchschnittliche Schrittzahl bedeutet,
dass das System schwerer zum Ziel kommt. Eine steigende Fehlerquote der
Marktplatz-Werkzeuge deutet darauf hin, dass sich die Website verändert hat. Was
noch fehlt, ist der Schritt vom Trace zum Alarm.

## Was wir tun würden

Für ein Studienprojekt erscheinen uns drei Maßnahmen verhältnismäßig:

1. **Eine kleine feste Prüfmenge** aus einigen Fotos mit bekannten
   Referenzpreisen, die in regelmäßigen Abständen neu bewertet wird. Weicht die
   Schätzung deutlich ab, ist etwas gedriftet. Das ist der einzige Weg, leise
   Fehler überhaupt sichtbar zu machen.
2. **Ein Selektortest gegen einen gespeicherten Seitenschnappschuss.** Das
   Werkzeug `scripts/inspect_offer_form.py` liest die Formularstruktur ohnehin
   schon aus. Ein regelmäßiger Abgleich würde eine Umgestaltung der Website
   melden, bevor ein Nutzer davon betroffen ist.
3. **Modellversionen festnageln** statt gleitender Namen zu verwenden, damit ein
   Anbieterwechsel nicht unbemerkt das Verhalten verändert.

Nicht verhältnismäßig wäre für dieses Projekt eine Überwachung der
Preisabweichung gegen tatsächliche Verkaufserlöse, denn die dafür nötigen Daten
existieren schlicht nicht. Warum das so ist, steht in
[W13](reflection-w13-continuous-learning.md).

## Schluss

Drift ist nicht nur ein technisches, sondern auch ein organisatorisches Problem.
Wird sie nicht früh erkannt, trifft das System über längere Zeit falsche
Entscheidungen, ohne dass die Ursache sichtbar wird. Beim SmartSellerAgent kommt
hinzu, dass er auf fremden Bausteinen aufsetzt, die sich unabhängig von uns
verändern. Die Fähigkeit, eine Veränderung überhaupt zu *bemerken*, ist deshalb
wichtiger als die Fähigkeit, sie zu beheben.
