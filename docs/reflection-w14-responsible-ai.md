# W14: Responsible AI (Reflexion)

> Wahlpflichtanforderung W14 (VL 14): *Welche Risiken, Verzerrungen und
> Missbrauchspotenziale hat das System?*

## Einordnung

Responsible AI beschreibt die Verantwortung, mit der ein KI-System entwickelt,
eingesetzt und überwacht wird. Ein System wie der SmartSellerAgent nimmt seinen
Nutzern Arbeit ab, gleichzeitig entstehen Risiken, die nicht ignoriert werden
dürfen. KI-Systeme sind nicht neutral, sondern spiegeln die Daten und Regeln
wider, auf denen sie beruhen.

Diese Reflexion versucht bewusst, weniger über KI im Allgemeinen und mehr über
*dieses* System zu sagen. Vor allem geht es um die Stelle, an der es sich während
der Entwicklung tatsächlich falsch verhalten hat.

## Der konkreteste Vorfall: ein System, das gelogen hat

Bei einem Testlauf meldete der Agent, die Anzeige sei erfolgreich bei
Kleinanzeigen eingestellt worden. Tatsächlich war nichts geschehen, es war nicht
einmal jemand angemeldet. Die Ursache war weder Bosheit noch eine Halluzination
im engeren Sinn. Der Orchestrator hatte sein Schrittbudget in Websuchen
verbraucht, wurde zu einer Schlussantwort gezwungen und füllte die vom
Antwortformat geforderte Statuszeile mit der wahrscheinlichsten Formulierung. Das
Ergebnis war ein flüssiger, vollständig plausibler und komplett falscher Bericht
über eine Handlung in der echten Welt.

Das ist aus zwei Gründen der wichtigste Punkt dieser Reflexion. Erstens ist die
betroffene Handlung **nicht rückholbar**. Eine veröffentlichte Anzeige lässt sich
nicht automatisch zurücknehmen, und im umgekehrten Fall hätte sich ein Nutzer
darauf verlassen, dass sein Artikel online steht. Zweitens zeigt der Vorfall die
allgemeine Gefahr sprachfähiger Systeme. Sie klingen bei falschen Aussagen
genauso überzeugend wie bei richtigen.

Die Konsequenzen im Code beschreiben wir hier, weil sie das eigentliche Ergebnis
dieser Reflexion sind:

- **Das Werkzeug protokolliert selbst**, was es getan hat. Die Oberfläche zeigt
  dieses Protokoll (`publish_attempts`) und nicht die Zusammenfassung des
  Modells. Wurde das Werkzeug nie aufgerufen, steht dort ausdrücklich, dass keine
  Anzeige eingestellt wurde, auch wenn der Text daneben etwas anderes behauptet.
- **Zwei getrennte Schalter** müssen gesetzt sein, damit überhaupt veröffentlicht
  wird: eine Umgebungsvariable des Betreibers und eine Ankreuzbox für genau
  diesen einen Lauf. Standardmäßig ist beides aus.
- **Keiner dieser Schalter ist für das Sprachmodell sichtbar.** Das
  Veröffentlichungswerkzeug hat kein entsprechendes Feld, das Modell kann seine
  eigene Freigabe also gar nicht erst argumentieren.

Der Grundsatz dahinter lässt sich verallgemeinern: Eine unumkehrbare Handlung
darf nicht davon abhängen, dass ein Sprachmodell sich korrekt verhält.

## Datenschutz

Das System läuft in zwei Betriebsarten. Lokal verlassen die Fotos die Maschine
nicht. Im Betrieb über OpenRouter wird dagegen **jedes Produktfoto und jeder
Prompt an einen Dritten übertragen**. Das wiegt hier schwerer, als es zunächst
klingt, denn Produktfotos entstehen in Wohnungen. Sie zeigen nicht nur den
Artikel, sondern auch Räume, weitere Besitztümer und gelegentlich Personen. Wer
ein gebrauchtes Regal fotografiert, denkt selten daran, dass der Hintergrund
mitreist.

Ehrlich benannt: Die Betriebsart steht in der Konfiguration und im README, aber
**die Oberfläche sagt es dem Nutzer nicht.** Wer die Anwendung nur benutzt,
erfährt nicht, wohin sein Bild geht. Das ist die Lücke, die wir als erste
schließen würden, denn ein Hinweis in der Seitenleiste wäre wenige Zeilen Arbeit.
So lange das System aber nur in der aktuellen Version als Prototyp läuft, ist es nicht entscheidend, weil die Nutzer ohnehin die README lesen müssen, um es überhaupt zum Laufen zu bringen.

Ein zweiter Punkt betrifft die Anmeldung. Die Anwendung nimmt bewusst nie ein
Passwort entgegen. Angemeldet wird von Hand, gespeichert wird nur die Sitzung.
Diese Sitzungsdaten sind allerdings faktisch ein angemeldetes Konto, und sie
liegen im Volume `marketplace-state`. Hinzu kommt die noVNC-Ansicht des
Container-Browsers, die ohne Passwort läuft. Aus diesem Grund ist der Port in
`docker-compose.yml` ausdrücklich nur an `127.0.0.1` gebunden. Wer ihn erreicht,
steuert einen angemeldeten Browser. Die Einschränkung ist im Compose-File
kommentiert, damit sie nicht versehentlich aufgehoben wird.

## Verzerrungen

Bias entsteht, wenn ein System bestimmte Gruppen oder Merkmale systematisch
bevorzugt oder benachteiligt, weil die zugrunde liegenden Daten diese Verzerrung
enthalten. Im SmartSellerAgent sind drei Stellen betroffen:

- **Preisschätzung.** Die Websuche spiegelt die Plattformen und Regionen wider,
  die sie indexiert. Preise für den deutschen Gebrauchtmarkt sind nicht überall
  Preise. Durch die Begrenzung auf zwei Suchen pro Lauf stützt sich die Schätzung
  zudem auf eine sehr schmale Stichprobe.
- **Produkterkennung.** Vision-Modelle erkennen bekannte westliche Marken
  zuverlässiger als regionale oder Nischenprodukte. Wer etwas verkauft, das das
  Modell nicht kennt, bekommt keine Fehlermeldung, sondern eine selbstbewusste
  Fehleinschätzung und darauf aufbauend einen falschen Preis.
- **Sprache.** Die erzeugten Anzeigen sind deutsch, ein Teil der Anweisungen ist
  englisch. Wessen Produkte dabei gut beschrieben werden, ist keine neutrale
  Frage.

## Missbrauchspotenzial

Aufschlussreich ist die Frage, was das System *leicht* macht, das vorher mühsam
war.

Der schärfste Punkt betrifft die Kernfunktion. Das System ist darauf optimiert,
aus einem Foto eine ansprechende Verkaufsbeschreibung zu erzeugen. Das
Vision-Modell sieht dabei ausschließlich das Bild, das der Verkäufer ausgewählt
hat, und kann nicht wissen, was dieses Bild verbirgt. Ein Defekt außerhalb des
Ausschnitts wird nicht erwähnt, weil er nicht bekannt ist, und der erzeugte Text
klingt trotzdem überzeugend. Damit lässt sich mangelhafte Ware attraktiv
darstellen, ohne dass irgendjemand aktiv lügen müsste.

Hinzu kommt die Massenerzeugung. Was als Hilfe für Privatpersonen gedacht ist,
eignet sich ebenso gut für gewerbliche Wiederverkäufer, die damit den Aufwand für
hunderte Anzeigen auf ein Vielfaches ihrer bisherigen Kapazität skalieren können.

## Verlässlichkeit und menschliche Kontrolle

Der Agent liefert eine **Preisempfehlung und kein Wertgutachten**. Kleine Modelle
halluzinieren, und eine selbstbewusst falsche Produkterkennung führt zu einem
selbstbewusst falschen Preis. Verkauft jemand deutlich unter Wert, weil er der
Empfehlung gefolgt ist, entsteht ihm ein realer Schaden.

Das Projekt hat darauf mit einem Menschen im Ablauf reagiert, und zwar an genau
der Stelle, an der es darauf ankommt. Die Anmeldung erfolgt von Hand, das
ausgefüllte Formular bleibt im Browser stehen, und die Veröffentlichung löst der
Mensch selbst aus. Was zunächst eine technische Notlösung war, weil die Plattform
den automatischen Login verhindert, hat sich als die inhaltlich richtige
Gestaltung erwiesen. Die unumkehrbare Entscheidung liegt beim Menschen, der das
Ergebnis vorher sieht.

## Was gebaut ist und was fehlt

Vorhanden sind die zwei Freigabeschalter mit sicherem Standardwert, das
werkzeuggeführte Protokoll anstelle der Selbstauskunft des Modells, der lokale
Betrieb als datenschutzfreundliche Variante, die vollständige
Nachvollziehbarkeit über Langfuse-Traces, die Vorschau vor dem Absenden und die
Bindung der noVNC-Ansicht an die lokale Schnittstelle.

Nicht vorhanden sind eine Authentifizierung an Frontend und API, eine
Ratenbegrenzung, eine Inhaltsmoderation der erzeugten Texte, eine Aufzeichnung
darüber, wer was hochgeladen hat, ein Passwortschutz für die noVNC-Ansicht und
ein sichtbarer Hinweis auf die gewählte Betriebsart. Die Anwendung ist für den
Einsatz durch eine einzelne Person auf dem eigenen Rechner gebaut. Ein
mehrbenutzerfähiger Betrieb wäre in dieser Form nicht verantwortbar.

## Fazit

Responsible AI ist bei diesem Projekt weniger eine ethische Grundsatzfrage als
eine Frage der Architektur. Die konkreteste Lehre stammt nicht aus der Vorlesung,
sondern aus einem Testlauf: Ein Sprachmodell hat eine Handlung berichtet, die nie
stattgefunden hat. Die Antwort darauf war nicht, das Modell besser zu
instruieren, denn das allein hätte nicht genügt. Stattdessen wurde die
unumkehrbare Handlung strukturell aus seinem Zugriff genommen und ihre
tatsächliche Ausführung unabhängig protokolliert. Verantwortungsvoll ist ein
solches System dann, wenn seine gefährlichsten Fähigkeiten nicht davon abhängen,
dass es sich gut benimmt.
