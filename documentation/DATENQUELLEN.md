# Datenquellen

**Stand:** 11.11.2026, beobachtete Quellen 16.11.2026 · öffentliche Fassung 0.1 · Definition der Quellen: `src/stockout_at/archive.py` `SOURCES`, dazu `eko.py` und `registers.py`

Das Projekt nutzt ausschließlich öffentlich abrufbare Daten. Es verarbeitet keine Apotheken-, Großhandels- oder Patientendaten. Dieses Dokument beschreibt jede Quelle, die die öffentliche Fassung abruft: was abgerufen wird, wie oft, in welchem Format, welches Modul sie liest und welche Nutzungshinweise im Code stehen. Was die Referenzinstanz zusätzlich nutzt, steht in [Abschnitt 4](#4-unterschiede-zur-referenzinstanz). Wie die Meldungen danach verknüpft und ausgewertet werden, steht in [MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md); die Zeitsteuerung in [BETRIEB.md](BETRIEB.md#zeitsteuerung-systemd).

**Lizenz der Rohdaten:** Die Daten der Quellen stehen nicht unter der Lizenz dieses Repositorys. Für sie gelten die Bedingungen der jeweiligen Quelle (Spalte „Nutzungshinweis“). Code steht unter Apache-2.0, eigene Texte und Auswertungen unter CC BY 4.0.

## 1. Überblick

`archive.SOURCES` enthält **23 Quellen**: 19 ausgewertete und 4 beobachtete, die nur roh archiviert werden ([Beobachtete Quellen](#beobachtete-quellen-nur-roh-archiviert)). Dazu kommen zwei Quellen mit eigenem Abrufweg: **`eko`** (RIS, Modul `eko`) und **`cima_reg`** (Einzelabfragen bei CIMA, `registers.sync_cima`). Jeder Name erscheint nach dem ersten Abruf als Ordner im Archiv; `stockout status` zeigt die 23 aus `SOURCES`, die beobachteten in einem eigenen Block.

**Rhythmus** (Details in Abschnitt 3):
- **jeder Lauf**: Quellen ohne `min_hours`, also bei jedem planmäßigen Lauf um 06:15 und 18:15 Uhr und im Nachholabruf um 12:15 Uhr, wenn ihr letzter Versuch scheiterte;
- **1×/Tag**: Quellen mit `min_hours = 20`; ein planmäßiger Lauf überspringt sie, solange ihr letzter Erfolg jünger als 20 Stunden ist.
- **beobachtet, 1×/Tag oder 1×/Woche**: `min_hours = 20` bzw. `160`; der Tageslauf holt die fälligen als letzten Schritt, nach dem Protokoll.

### Engpassregister

| Quelle | Herausgeber, Land | Inhalt | Format | Rhythmus | im Tagesarchiv seit | Parser | Verwendung | Nutzungshinweis laut Code |
|---|---|---|---|---|---|---|---|---|
| `basg` | BASG, AT | Vertriebseinschränkungen (amtliches Register, nur heutiger Stand) | XML | jeder Lauf | 17.10.2026 | `basg.parse` | Grundwahrheit: Schnappschüsse, Episoden, Website, Ergebnis aller Modelle | Quellenangabe „BASG“; amtliche Felder wörtlich; `Zulassungsinhaber_Tel` wird nie veröffentlicht |
| `bfarm` | BfArM, DE | Lieferengpassmeldungen | CSV | jeder Lauf | 17.10.2026 | `foreign.parse_bfarm` | nur intern: Archiv, `foreign_items`, Herausforderer `z3_v0_mit_de` | Auf der Website erst nach schriftlicher Zustimmung und ohne Kontaktspalten; bis dahin ausgeblendet (`site.HIDDEN_SOURCES`) |
| `ema` | EMA, EU | Medicine shortages (Output-Bericht) | XLSX | jeder Lauf | 17.10.2026 | `foreign.parse_ema` | Frühwarnung (Land „EU“) | Weiterverwendung mit Quellenangabe EMA |
| `aifa` | AIFA, IT | Elenco dei medicinali carenti | CSV | jeder Lauf | 18.10.2026 | `foreign.parse_aifa` | Frühwarnung | CC BY 4.0, Quelle AIFA |
| `sukl_cz` | SÚKL, CZ | Meldungen über Unterbrechung und Wiederaufnahme (Ereignisprotokoll seit 2008) | ZIP mit CSV | jeder Lauf | 18.10.2026 | `foreign.parse_sukl_cz` | Frühwarnung | Open-Data-Bedingungen SÚKL, Quelle SÚKL |
| `sukl_sk` | ŠÚKL, SK | Meldungen über Unterbrechungen (seit 2019) | CSV | jeder Lauf | 18.10.2026 | `foreign.parse_sukl_sk` | Frühwarnung | keine Bedingungen veröffentlicht |
| `ogyei` | OGYÉI, HU | Shortage-Liste | CSV | jeder Lauf | 18.10.2026 | `foreign.parse_ogyei` | Frühwarnung | keine Lizenz veröffentlicht |
| `jazmp` | JAZMP, SI | Liste der Unterbrechungen und Störungen (seit 2008) | XLSX | jeder Lauf | 18.10.2026 | `foreign.parse_jazmp` | Frühwarnung | Urheberrechtshinweis, keine offene Lizenz |
| `famhp` | FAMHP, BE | PharmaStatus-Export | XLSX | jeder Lauf | 18.10.2026 | `foreign.parse_famhp` | Frühwarnung | keine Lizenz veröffentlicht |
| `cima` | AEMPS, ES | Problemas de suministro (REST, seitenweise) | JSONL, eine Seite je Zeile | jeder Lauf, höchstens 50 Seiten | 18.10.2026 | `foreign.parse_cima` | Frühwarnung | keine Lizenz veröffentlicht |
| `fda` | FDA, US | openFDA Drug Shortages | ZIP mit JSON | jeder Lauf | 18.10.2026 | `foreign.parse_fda` | Frühwarnung (Land „US“) | CC0 |
| `ansm` | ANSM, FR | Verfügbarkeitsliste, Export der ganzen Liste | XLS (BIFF) | 1×/Tag | 19.10.2026 | `foreign.parse_ansm` | Frühwarnung | auf der Methodikseite „noch nicht geprüft“; robots.txt erlaubt alles (Code-Kommentar) |
| `pl_mz` | Gesundheitsministerium, PL | Liste der von Nichtverfügbarkeit bedrohten Arzneimittel (Amtsblatt, alle 6–8 Wochen) | PDF | 1×/Tag (neueste Ausgabe) | 19.10.2026; Ausgaben seit 2015 nachgeladen | `foreign.parse_pl_mz` | Frühwarnung | amtliches Dokument, nach Art. 4 des polnischen Urheberrechtsgesetzes nicht geschützt |

### Register und Zusatzsignale

| Quelle | Herausgeber | Inhalt | Format | Rhythmus | seit | gelesen von | Verwendung | Nutzungshinweis laut Code |
|---|---|---|---|---|---|---|---|---|
| `asp` | ELGA, FHIR-Terminologieserver | ASP-Liste: alle Humanarzneimittel-Packungen in AT mit „lieferbar“ | JSON (FHIR CodeSystem); Historie bis 06/2026 als SVS-XML aus TermGit | 1×/Tag; neue Fassung etwa monatlich | 19.10.2026 (82 ältere Fassungen importiert) | `asp.parse`, `build.load_asp`, `rueckblick.AspHistory` | Nenner, Gleichwertigkeit, Universum der Modelle, Marktaustritte (T8) | keine Angabe im Code; Website verlinkt die TermGit-Seite |
| `eudragmdp` | EMA, EudraGMDP | GMP-Nichtkonformitätsberichte | XLS | 1×/Tag | 19.10.2026 | `gmp.parse_ncr` | Schattenmerkmale, Test T7 | keine Angabe im Code |
| `sukl_dlp` | SÚKL, CZ | Arzneimitteldatenbank DLP (monatliches ZIP) | ZIP | 1×/Tag | 19.10.2026 | `registers.parse_sukl_dlp` | füllt Inhaber und ATC der tschechischen Meldungen | offene Daten (Docstring); robots.txt verlangt 10 s Abstand, wird eingehalten |
| `cima_reg` | AEMPS, ES | CIMA `medicamento?cn=` je nationalem Code einer Meldung | JSONL | nach jedem planmäßigen Lauf und bei `fetch --source cima`, nur neue Codes, höchstens 1.500 je Lauf, 1 Anfrage/s | 19.10.2026 | `registers.parse_cima_reg` (alle Dateien zusammen) | füllt ATC 5, Inhaber, Wirkstoffe der spanischen Meldungen | wie `cima` |
| `eko` | RIS, Amtliche Verlautbarungen der Sozialversicherung | monatliche „Änderung des Erstattungskodex“ (seit 2004) | HTML, ein Dokument je Datei | werktags 21:30 Uhr (+ bis 30 min) mit `fetch --eko`; am Wochenende in den planmäßigen Läufen | 29.10.2026 laufend; 268 Dokumente am 19./20.10.2026 nachgeladen | `eko.parse`, `rueckblick.eko_events` | Merkmal `eko_56`, Schattenspalte, Test T9 | RIS-Regeln: höchstens eine Anfrage je 2 s, keine parallelen Verbindungen, nur 20–5 Uhr oder am Wochenende |
| `erviss_ili` | ECDC ERVISS (GitHub) | ILI/ARI-Raten aller Länder, AT ab Woche 40/2022 | CSV | 1×/Tag | 19.10.2026 | `rueckblick.ili_series` | Test T4 | EUPL-1.2 (Code-Kommentar) |
| `sari_region` | Österreichische Sozialversicherung (Open Data) | SARI-Spitalsaufnahmen nach Virus und Region, wöchentlich ab Woche 19/2023 | CSV | 1×/Tag | 19.10.2026 | `rueckblick.sari_series` | Test T4 | keine Angabe im Code |
| `sari_patient` | wie `sari_region` | SARI nach Wohnregion und Altersgruppe | CSV | 1×/Tag | 19.10.2026 | – | **nur archiviert** | keine Angabe im Code |

### Beobachtete Quellen (nur roh archiviert)

Seit 16.11.2026. Ohne eigenes Archiv ginge ihr Verlauf verloren: Die Datei wird an Ort und Stelle überschrieben oder neu gefasst. Es gibt keinen Parser, keine Datenbanktabelle, kein Merkmal und keinen Eintrag auf der Website; `build` übergeht sie, weil es Quellen nur über ihren Namen liest. Je Lauf gibt es einen Versuch; ein Ausfall ist nur eine WARNUNG (Kennzeichen `watch`, [BETRIEB.md](BETRIEB.md#meldungen-alarme-und-status)). Die Referenzinstanz beobachtet weitere Quellen ([Abschnitt 4](#4-unterschiede-zur-referenzinstanz)).

| Quelle | Herausgeber, Land | Inhalt | Format, Abruf | Rhythmus | robots.txt (16.11.2026) | Nutzungshinweis | beobachtet in der Referenzinstanz (16.11.2026) |
|---|---|---|---|---|---|---|---|
| `ema_medicines` | EMA, EU | Arzneimitteltabelle (Medicines output) | XLSX, 60 s Pause vor der Anfrage | täglich | erlaubt | Weiterverwendung mit Quellenangabe EMA | 906.752 Bytes (im zweiten Anlauf, siehe Abschnitt 3) |
| `ema_dhpc` | EMA, EU | DHPC-Tabelle | XLSX, 60 s Pause | täglich | erlaubt | wie `ema_medicines` | 96.626 Bytes |
| `ema_union` | EMA, EU | Unionsliste kritischer Arzneimittel | XLSX, 60 s Pause | wöchentlich; Neufassung November/Dezember 2026 | erlaubt | wie `ema_medicines` | 219.112 Bytes (im zweiten Anlauf) |
| `abwasser_wien` | Stadt Wien (MA 15), AT | Abwassermonitoring (Virusfracht je Woche) | CSV, Kennung `Datum;Target` | wöchentlich; die Reihe endet vermutlich 2025-10 | `/downloads/` nicht gesperrt | CC BY 4.0, Stadt Wien | 18.774 Bytes |

Die Spalte „seit“ gibt den ersten Live-Abruf der Referenzinstanz laut Manifest an. Die Nutzungshinweise der Engpassregister stehen wortgleich in `site.FOREIGN_SOURCES` und erscheinen auf der Methodikseite der Website.

### Umfang am 10.11.2026 (beobachtet in der Referenzinstanz)

| Quelle | Dateien im Archiv | Meldungen in `foreign_items` | davon in der neuesten Datei | davon mit ATC 5 |
|---|---:|---:|---:|---:|
| `aifa` | 282 | 12.856 | 2.531 | 10.289 |
| `ansm` | 23 | 312 | 290 | 163 |
| `bfarm` | 44 | 2.093 | 531 | 2.093 |
| `cima` | 45 | 1.060 | 921 | 1.047 |
| `ema` | 51 | 89 | 85 | 63 |
| `famhp` | 60 | 1.663 | 1.474 | 1.621 |
| `fda` | 24 | 562 | 290 | 329 |
| `jazmp` | 5 | 8.967 | 8.967 | 4.335 |
| `ogyei` | 23 | 3.881 | 1.465 | 2.954 |
| `pl_mz` | 82 | 2.921 | 289 | 1.471 |
| `sukl_cz` | 21 | 39.890 | 39.890 | 37.996 |
| `sukl_sk` | 34 | 9.585 | 9.585 | 4.007 |

Weitere Dateien im Archiv: `basg` 53 (davon 25 live), `asp` 84, `eko` 270, `eudragmdp` 22, `cima_reg` 16, `sukl_dlp` 2, `erviss_ili` 4, `sari_region` 3, `sari_patient` 3. Bei `sukl_cz`, `sukl_sk` und `jazmp` wird nur die neueste Datei gelesen, weil jede Datei die ganze Meldehistorie enthält (`foreign.FULL_HISTORY`); deshalb zählt dort jede Meldung als „in der neuesten Datei“. Beendete Meldungen sind dort als Fälle mit Enddatum enthalten.

## 2. Gemeinsame Regeln beim Abruf

- **User-Agent** (`archive.user_agent()`): `LieferengpassRadar/0.1 (+https://github.com/benediktneumayer2-tech/lieferengpass-radar)`. Ist die Umgebungsvariable `STOCKOUT_CONTACT` gesetzt, etwa auf eine E-Mail-Adresse, steht zusätzlich `; Kontakt: <Wert>` vor der schließenden Klammer. Wer das Radar regelmäßig betreibt, sollte sie setzen, damit sich die Betreiber der Quellen melden können. Alle Abrufwege (`archive`, `eko`, `registers`, `legacy`) verwenden denselben User-Agent.
- **Wiederholung:** bis zu drei Versuche je Quelle, Pausen 15 s und 60 s (`archive.RETRY_DELAYS`), Zeitlimit 90 s je Anfrage. Beobachtete Quellen haben einen Versuch je Lauf. Eine Quelle kann eine Pause vor jeder Anfrage verlangen (`Source.pause`, EMA-Tabellen 60 s).
- **Formatprüfung** (`archive._check`), bevor eine Antwort als Erfolg zählt:

| Fall | Prüfung |
|---|---|
| leere Antwort | immer Fehler |
| `basg` | `Meta/@producedOn` muss lesbar sein |
| `asp` | FHIR-Datum vorhanden und Kennung `"asp-liste"` in den ersten 3.000 Bytes |
| XLSX, ZIP | beginnt mit `PK` |
| JSONL (`cima`) | beginnt mit `{` |
| PDF (`pl_mz`) | beginnt mit `%PDF` |
| XLS (`ansm`, `eudragmdp`) | OLE-Signatur |
| Quellen mit Kennung (`expect`) | `countryname` (ERVISS), `JAHR;KW` (SARI), `Datum;Target` (`abwasser_wien`) in den ersten 3.000 Bytes; bei HTML-Seiten (`ext = "html"`) irgendwo im Text |
| übrige CSV | Semikolon in den ersten 2.000 Bytes |

  Eine Antwort, die die Prüfung nicht besteht, wird wie ein Netzfehler wiederholt (bei beobachteten Quellen erst im nächsten Lauf). Bleibt sie falsch, wird sie zur Diagnose archiviert, aber mit `ok: false` vermerkt und nie ausgewertet.
- **Kontaktdaten:** Die Parser lesen keine Kontaktspalten (Telefon, E-Mail) in Auslandsmeldungen ein (`foreign`-Docstring; Test `test_bfarm_items_group_pzns_and_drop_contacts`). Die BASG-Spalte `Zulassungsinhaber_Tel` steht wörtlich in Archiv und Datenbank, wird aber nie auf der Website gezeigt.

## 3. Besonderheiten je Quelle

### BASG (Österreich, Grundwahrheit)

- Die Datei zeigt nur den heutigen Stand; beendete Meldungen verschwinden. Jede Fassung wird nach ihrem `producedOn` benannt. Die Datei entsteht laut Code gegen 02:00 Uhr; ab 06:00 Uhr Wiener Zeit erwartet `status` die Fassung des Tages (`status.BASG_READY_HOUR`).
- `stockout status` meldet jeden Kalendertag seit dem ersten Live-Abruf, für den keine Fassung mit diesem `producedOn`-Datum vorliegt. In der Referenzinstanz (erster Live-Abruf 17.10.2026) war das Archiv am 10.11.2026 lückenlos.
- **Vorgeschichte** (einmalig importiert): 27 Aufnahmen aus dem Internet Archive, ein lokal gesicherter BASG-Export vom 18.07.2026 und 82 ASP-Fassungen aus der öffentlichen TermGit-Historie. Internet-Archive-Aufnahmen holt `legacy.import_wayback`, auch unter der früheren URL `VertriebseinschraenkungenASP.xml`. Lokal gesicherte Dateien liest `stockout import-legacy` aus einem Ordner mit Manifesten ([BETRIEB.md](BETRIEB.md#import-legacy)). Manche Aufnahmen brechen nach etwa 1 MiB ab; sie gelten als unvollständig (`complete = 0`).
- Beobachtet am 10.11.2026: 1.130.304 Bytes je Datei, 844 gemeldete Packungen.

### BfArM (Deutschland, nur intern)

Wird zweimal täglich archiviert und in `foreign_items` übernommen. Auf der Website und in allen dort gezeigten Stufen und Trefferquoten bleibt sie ausgeblendet (`site.HIDDEN_SOURCES`), weil keine schriftliche Zustimmung zur Veröffentlichung vorliegt. Die Modelle `z3_v0`, `z3_v0_ohne_ausland` und `stufen_v0` lassen sie ebenfalls weg; nur der interne Herausforderer `z3_v0_mit_de` nutzt sie (siehe [MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md)).

### RIS und EKO (Zeitfenster)

- Das RIS bittet um Abfragen nur zwischen 20 und 5 Uhr Wiener Zeit oder am Wochenende, höchstens eine Anfrage je zwei Sekunden und ohne parallele Verbindungen (`eko`-Docstring mit Verweis auf die RIS-OGD-FAQ). `eko.allowed` prüft das Fenster; `eko.sync` ruft außerhalb nichts ab und bricht ab, wenn das Fenster während eines Laufs endet.
- Der laufende Abruf liest nur die erste Suchseite (100 Dokumente) und nimmt Dokumente der letzten 90 Tage (`RECENT_DAYS`). Bei Serverfehlern wiederholt er nach 60 s und 300 s.
- Das einmalige Nachladen aller Dokumente seit 2004 (`stockout import-legacy --backfill eko`) verteilt die Anfragen zufällig über die Nacht bis 04:30 Uhr (`eko.night_end`), damit keine geballte Last entsteht.
- Gelesen werden nur Streichungen ganzer Produkte aus dem Grünen, Gelben und Roten Bereich, mit ATC, Wirksamkeits- und Entscheidungsdatum, Verfahrensnummer und dem Grund aus den Fußnoten (`zulassung`, `nicht_lieferbar`, `antrag_zurueckgezogen`, `sonst`, `ohne_fussnote`). Streichungen einzelner Packungsgrößen werden nicht gelesen.
- **Grenze:** Ein EKO-Lauf ohne neues Dokument hinterlässt keinen Manifest-Eintrag, und `stockout status` zeigt EKO nicht. Ob der Abendlauf lief, zeigt nur das Journal (`journalctl --user -u stockout-eko.service`).

### Polen (PDF ohne Datum)

`archive._get_pl_mz` sucht im ELI-Verzeichnis des Amtsblatts des Gesundheitsministeriums die neueste Ausgabe der Liste (dieses oder voriges Jahr) und lädt deren PDF. Die Ausgaben seit 2015 kamen einmalig über `stockout import-legacy --backfill pl_mz` (81 Ausgaben, 12.07.2015 bis 01.09.2026). `foreign.pdf_blocks` ruft `pdftotext -bbox-layout` auf; `foreign.pl_rows` setzt die Tabellenzellen über ihre Koordinaten zu Zeilen zusammen, `foreign.latin_inn` wandelt die lateinischen Wirkstoffnamen um. Weil die Liste keine Daten enthält, macht `foreign.listings` aus aufeinanderfolgenden Ausgaben Listungen; das Signaldatum ist die erste Ausgabe einer ununterbrochenen Listung. Etwa die Hälfte der Einträge hat einen ATC-Code (`pl_mz` in der Umfangstabelle oben: 1.471 von 2.921).

### Tschechien (SÚKL)

- `sukl_cz` ist ein Ereignisprotokoll seit 2008 (Unterbrechung, Wiederaufnahme, Ende); `foreign._cases` macht daraus Fälle mit Beginn und Ende. Der Inhaber fehlt in den Meldungen und kommt aus der DLP-Datenbank (`sukl_dlp`). Das Register gibt den heutigen Inhaber, ältere Meldungen können deshalb einen späteren Inhaber zeigen.
- `archive._get_sukl_dlp` liest die Katalogseite, wählt die neueste `DLPJJJJMMTT.zip` und wartet vor dem Download 10 Sekunden.
- **Beobachtet:** SÚKL ist auf die Domain `opendata.sukl.gov.cz` umgezogen. Nach Fehlversuchen vom 21. bis 25.10.2026 wurden am 25.10.2026 beide URLs umgestellt; das Muster für die DLP-Datei lässt beide Domains zu.

### Spanien (CIMA)

`cima` ruft die Seiten `psuministro?pagina=1..n` ab, bis eine Seite keine Ergebnisse mehr hat (höchstens 50), und speichert alle Seiten als eine JSONL-Datei. Die Meldungen haben nur den nationalen Code; ATC 5, Inhaber und Wirkstoffe kommen aus `cima_reg`. Nicht gefundene Codes werden im nächsten Lauf erneut abgefragt.

### EudraGMDP (Sitzung)

`archive._get_eudragmdp` öffnet die Suchseite, sucht im Zeitraum 01.01.2000 bis heute in derselben Server-Sitzung (Cookie) und lädt danach die Ergebnisliste als XLS. Fehlt die Trefferzahl („x to y of z“), gilt der Abruf als gescheitert. Zurückgezogene Berichte verschwinden aus der Liste; die Geschichte entsteht nur im eigenen Archiv.

### ASP-Liste

Seit 19.10.2026 kommt die Liste täglich vom FHIR-Terminologieserver der ELGA; eine neue Fassung erscheint etwa monatlich, der Dateiname trägt ihr Datum. Die Historie bis Juni 2026 wurde aus TermGit importiert (`legacy.import_asp_package`, `origin: termgit_history`). Beide Formate tragen dieselben Eigenschaften und ergeben dieselben Zeilen (`asp.concept_row`, Test `test_asp_fhir_codesystem_gives_the_same_rows_as_svs`). Der Aufbau verwendet die neueste Fassung (am 10.11.2026: Version `2.54.0+20261022`); die Rückblicktests und die Modelle nutzen alle Fassungen.

### Beobachtete Quellen (EMA)

- **EMA** (`ema_medicines`, `ema_dhpc`, `ema_union`): Schnelle Folgeabrufe lösen eine Sperre aus (HTTP 429), die auch die ausgewertete Quelle `ema` träfe. Deshalb kommen die neuen EMA-Abrufe erst nach dem Protokoll, mit 60 s Pause vor jeder Anfrage und einem Versuch. **Beobachtet in der Referenzinstanz:** `ema` scheitert seit 09.11.2026 in den meisten Läufen mit HTTP 429. Beim Probeabruf am 16.11.2026 kam `ema_dhpc` durch; `ema_medicines` und `ema_union` bekamen trotz 60 s Abstand 429 und kamen 20 Minuten später im zweiten Anlauf durch. Bleibt die Sperre, werden die neuen EMA-Abrufe auf wöchentlich gestellt.
- **Hilfen für weitere beobachtete Quellen** (im Code, von der öffentlichen Fassung derzeit nicht genutzt): Link-Suche nach der neuesten verlinkten Datei (`Source.link`, `archive._get_linked`, Adresse im Manifest unter `file_url`), Seitenabruf bis zur ersten Seite ohne Ergebnis-Kennung (`Source.page_rows`), Kennung irgendwo im Text bei HTML-Seiten und Abruf nur über einen eigenen Timer statt in den Tagesläufen (`Source.timer`).

### Internet Archive (Vorgeschichte)

`stockout import-legacy --wayback-only <quelle>` holt alle verschiedenen Aufnahmen einer Export-URL, die noch nicht im Archiv sind (Vergleich über die CDX-Prüfsumme), mit 3 s Pause. Bei anderen Quellen als BASG muss der Parser mindestens eine Meldung lesen, sonst wird die Aufnahme als Fehler vermerkt. Die Referenzinstanz hat Internet-Archive-Historie unter anderem für `aifa`, `basg`, `bfarm`, `ema`, `fda`, `ogyei` und `sukl_sk`.

### Infektionsdaten

ERVISS-ILI und SARI dienen nur dem Rückblicktest T4. Die SARI-URLs enthalten eine Versionskennung (`v202602`); erscheint eine neue Fassung unter neuem Namen, muss die URL in `SOURCES` angepasst werden (Ableitung aus dem Code, nicht beobachtet). **Beobachtet:** SARI veröffentlicht mit Verzögerung; am 10.11.2026 war die neueste archivierte SARI-Fassung vom 05.11.2026.

## 4. Unterschiede zur Referenzinstanz

Die **Referenzinstanz** ist die Installation des Autors, die seit dem 17.10.2026 täglich läuft. Sie hat die eingefrorenen Modelle in `models/`, das Vorhersageprotokoll und die Bildschirmfotos dieser Dokumentation erzeugt; Angaben mit „beobachtet“ stammen von dort.

Zusätzlich zu den Quellen oben archiviert die Referenzinstanz:

- die finnische Engpassliste und das finnische Basisregister der Fimea (`fimea`, `fimea_reg`);
- die CEP-Datei der EDQM (`edqm`, Eignungszertifikate der Wirkstoffhersteller);
- vier Exporte aus „Medikamente Info Austria“ des BASG (`mia_asp`, `mia_abst`, `mia_verl`, `mia_ve`).
- seit 16.11.2026 als beobachtete Quellen, nur roh und ohne Parser: die kroatische Engpasstabelle der HALMED (`halmed`), die BASG-Seiten zu Vertriebseinschränkungen (MSC) und Sicherheitsinformationen (DHPC) (`basg_msc`, `basg_dhpc`), die norwegische Übersicht der DMP (`dmp_no`), den Erstattungskodex als PDF (`eko_pdf`), die portugiesische Liste der Exportverbote (`infarmed`), die rumänischen Marktaustrittsmeldungen der ANMDMR (`anm_ro`) und die lettische Verfügbarkeitsliste der ZVA (`zva_lv`); vorgesehen ist außerdem der Datenwürfel des Schweizer BWL (`bwl_ch`).

Die öffentliche Fassung lässt sie weg, bis die Nutzung mit den Betreibern geklärt ist. Ihre Parser bleiben im Code, damit bereits archivierte Dateien lesbar bleiben; finnische Meldungen blendet die Website aber aus (`site.SITE_HIDDEN_SOURCES`).

**Was sich dadurch ändert** (abgeleitet aus dem Code):

| Quelle | Wofür die Referenzinstanz sie nutzt | Folge in der öffentlichen Fassung |
|---|---|---|
| `fimea`, `fimea_reg` | Finnland zählt als Land: in den Ländermerkmalen der Modelle (`laender_*`, `inhaber_*`, `ausland_neu_28`), in den Stufen der Frühwarnliste und damit in `stufen_v0` und `mittel_v0`. Das Register liefert ATC, Produkt und Inhaber der finnischen Meldungen. | Finnland fehlt in Frühwarnliste und Ländermerkmalen. Im Merkmalsprotokoll der Referenzinstanz vom 11.11.2026 hatten 177 von 1.482 Wirkstoffen ohne aktive Meldung Finnland unter den meldenden Ländern; ohne Finnland hätten 108 eine andere Stufe gehabt, 27 davon B statt A. |
| `mia_verl` | Merkmal `inhaberwechsel_56` (Änderung beim Zulassungsinhaber in den letzten 56 Tagen) und der Registerhinweis „Änderung beim Zulassungsinhaber“ auf der Website | Merkmal immer 0; den Hinweis zeigt die Website nicht (`site.SITE_HOLDER_CHANGES`, auch in der Referenzinstanz ausgeblendet, bis das BASG die Nutzung erlaubt) |
| `mia_asp`, `edqm` | nur Schattenspalten im Merkmalsprotokoll (§ 21 AMG, CEP) | keine Wirkung auf Modelle, Vorhersagen oder Website |
| `mia_abst`, `mia_ve` | nur archiviert | keine |
| beobachtete Quellen der Referenzinstanz | nur roh archiviert | keine |

**Modelle und Prüfplan sind byte-gleich** mit der Referenzinstanz (`models/SHA256SUMS`, siehe [Vorab-Registrierung](MODELL_UND_BEWERTUNG.md#12-vorab-registrierung)). Die eingefrorenen Modelle speichern aber nur Gewichte; ihre Merkmale entstehen täglich aus den Daten. Die öffentliche Fassung liefert denselben Modellen deshalb andere Eingaben und erhält andere Vorhersagen. Für die prospektive Prüfung zählt das Vorhersageprotokoll der Referenzinstanz. Bis zum Go/No-Go am 30.04.2027 ändert sich deren Code nur in den Punkten, die der Prüfbericht unter „Änderungen nach dem Einfrieren“ nennt; danach werden beide Fassungen angeglichen.

## 5. Nicht umgesetzte Quellen

Ausgeschlossen oder zurückgestellt: drugshortage.ch (wird nicht gescrapt), Schweden und Zypern (robots.txt sperrt den Abruf), Litauen (Cloudflare), Produktregister für SK und SI (kein offener Export gefunden). Norwegen, Portugal und Kroatien archiviert die Referenzinstanz seit 16.11.2026 roh ([Abschnitt 4](#4-unterschiede-zur-referenzinstanz)).
