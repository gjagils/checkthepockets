# Centraal actieplan

Dit document is de bron voor **alle hieronder beschreven verbeteracties**, hun
voortgang, besluiten en overdracht. Lees ook [de gedeelde workflow](docs/WORKFLOW.md).
Bijwerken gebeurt in Git; een externe tracker of chatgeschiedenis is niet nodig.

## Huidige stand — 2026-09-23

- De repository-inrichting is gemerged via PR #134 (a65a899).
- De gebruiker heeft alle verbeteracties vrijgegeven op 2026-09-23, onder de budgetvoorwaarde uit docs/WORKFLOW.md.
- ACT-01 t/m ACT-07, ACT-09 t/m ACT-14, ACT-16 t/m ACT-24 en ACT-26 zijn afgerond.
- Open en afhankelijk van de gebruiker: ACT-08 (rotatie van blootgestelde geheimen),
  ACT-15 (restoreproef op een geïsoleerde NAS-omgeving) en ACT-25 (bunq-rekeningen
  controleren met een geautoriseerde Enable Banking-koppeling).
- Bestaande Linear-issues zijn niet geïmporteerd of gecontroleerd op overlap.
- Testsuite in de vastgelegde Python 3.12-omgeving: 476 geslaagd, 2 bewust
  overgeslagen live-tests. Productievalidatie na uitrol is per actie vermeld.

## Status en prioriteit

`Gepland` = beschreven, niet vrijgegeven. `Gereed` = gebruiker heeft uitvoering
vrijgegeven. `Bezig` = opgepakt op een genoemde branch. `Geblokkeerd` = concrete
belemmering met volgende stap. `Review` = implementatie klaar, controles/review of
merge nog open. `Afgerond` = criteria gehaald en merge geverifieerd.

P1 = betrouwbaarheid/beveiliging eerst; P2 = beheer en gebruik; P3 = onderhoud.
Afhankelijkheden zijn harde voorwaarden vóór implementatie; onderzoek mag eerder.
ACT-08 en ACT-15 kunnen onafhankelijk worden onderzocht. ACT-21 t/m ACT-24 mogen
meelopen met een verwante wijziging als scope en criteria expliciet worden gevolgd.
Een actie mag in subacties worden gesplitst, bijvoorbeeld ACT-09a, met eigen status,
criteria en overdracht. Neem nooit impliciet alle geplande acties in uitvoering.

## Overzicht

| ID | Prioriteit | Status | Afhankelijk van | Actie |
|---|---|---|---|---|
| ACT-01 | P1 | Afgerond | — | [Reproduceerbare ontwikkel- en testomgeving](#act-01) |
| ACT-02 | P1 | Afgerond | ACT-01 | [Testfouten onderzoeken en herstellen](#act-02) |
| ACT-03 | P1 | Afgerond | ACT-01 | [PostgreSQL en migraties toetsen](#act-03) |
| ACT-04 | P1 | Afgerond | ACT-01 | [Accountstatus en sessie-intrekking](#act-04) |
| ACT-05 | P1 | Afgerond | ACT-01 | [Veilige configuratie en cookies](#act-05) |
| ACT-06 | P1 | Afgerond | ACT-01 | [CSRF-bescherming controleren en aanvullen](#act-06) |
| ACT-07 | P1 | Afgerond | ACT-01, ACT-03 | [Encryptie zonder stille terugval](#act-07) |
| ACT-08 | P1 | Review | — | [Geheimen en Docker-buildcontext opschonen](#act-08) |
| ACT-09 | P1 | Afgerond | ACT-02, ACT-03 | [Rekeninggebonden importherkenning](#act-09) |
| ACT-10 | P2 | Afgerond | ACT-09 | [Importbatches en resultaatrapport](#act-10) |
| ACT-11 | P2 | Afgerond | ACT-10 | [Import veilig terugdraaien](#act-11) |
| ACT-12 | P2 | Afgerond | ACT-01 | [Bankstatus en synchronisatiefouten zichtbaar](#act-12) |
| ACT-13 | P1 | Afgerond | ACT-01 | [Deploymentfouten en healthchecks](#act-13) |
| ACT-14 | P2 | Afgerond | ACT-13, ACT-03 | [Vaste releaseversies en herstelprocedure](#act-14) |
| ACT-15 | P1 | Review | — | [Backups en herstel aantoonbaar maken](#act-15) |
| ACT-16 | P2 | Afgerond | ACT-02 | [Gebruikersroutes en navigatie ontwerpen](#act-16) |
| ACT-17 | P2 | Afgerond | ACT-12, ACT-16 | [Centraal actieoverzicht](#act-17) |
| ACT-18 | P2 | Afgerond | ACT-16 | [Herkomst en actualiteit van bedragen](#act-18) |
| ACT-19 | P2 | Afgerond | ACT-16 | [Navigatie, foutmeldingen en lege schermen](#act-19) |
| ACT-20 | P2 | Afgerond | ACT-17, ACT-18, ACT-19 | [Toegankelijkheid en mobiele eindcontrole](#act-20) |
| ACT-21 | P3 | Afgerond | ACT-02 | [Importlogica afzonderlijk testbaar maken](#act-21) |
| ACT-22 | P3 | Afgerond | ACT-02 | [Spaar- en terugkerende logica opsplitsen](#act-22) |
| ACT-22a | P3 | Afgerond | ACT-02 | [Pure plannings- en spaarregels in eigen modules](#act-22) |
| ACT-22b | P3 | Afgerond | ACT-22a | [Projecties en koppelingen naar een service](#act-22) |
| ACT-23 | P3 | Afgerond | ACT-02 | [Hypotheeklogica opsplitsen](#act-23) |
| ACT-23a | P3 | Afgerond | ACT-02 | [Leningdeel- en variantberekening naar mortgage_calc](#act-23) |
| ACT-23b | P3 | Afgerond | ACT-23a | [Scenariovergelijking uit de detailroute](#act-23) |
| ACT-24 | P2 | Afgerond | ACT-02 | [Gerichte foutafhandeling en logging](#act-24) |
| ACT-24a | P2 | Afgerond | ACT-02 | [Twee stille fouten loggen (PR #174)](#act-24) |
| ACT-24b | P2 | Afgerond | ACT-24a | [Inventarisatie, overige excepts en foutinjectie](#act-24) |
| ACT-25 | P2 | Gepland | — | [Meerdere bunq- en spaarrekeningen](#act-25) |
| ACT-26 | P1 | Afgerond | ACT-21 | [Importvoorbeeld zonder gegevens van andere gebruikers](#act-26) |

## Beschrijving en acceptatiecriteria

<a id="act-01"></a>

### ACT-01 — Reproduceerbare ontwikkel- en testomgeving

- **Acties:** Leg Python 3.12 en directe/transitieve dependencies reproduceerbaar vast. Documenteer installatie, configuratie en testcommando’s; sluit aan op CI en Docker.
- **Klaar wanneer:** Een schone checkout kan met gedocumenteerde opdrachten installeren en testen; lokale omgeving, CI en Docker gebruiken dezelfde afgesproken versies.
- **Validatie:** Schone installatie en volledige pytest-run; noteer versies en uitslag.

<a id="act-02"></a>

### ACT-02 — Testfouten onderzoeken en herstellen

- **Acties:** De nulmeting is opnieuw uitgevoerd in de vastgelegde Python 3.12-omgeving. De eerdere 121 fouten kwamen uit de afwijkende lokale Python 3.14/FastAPI/Starlette-omgeving. De drie Enable Banking-fouten in de eerste schone run waren enerzijds te vroege config-inlezing en anderzijds live netwerktests zonder toegang; beide zijn opgelost door runtime-configuratie en opt-in live tests.
- **Klaar wanneer:** Alle tests slagen of iedere uitzondering heeft een concrete oorzaak, opvolgactie en expliciete acceptatie; geen stilzwijgend overslaan van falende tests.
- **Validatie:** `pip check`, `scripts/check_environment.py` en `python -m pytest tests/ --tb=short`: **405 passed, 2 skipped, 2703 warnings in 47.48s**. De twee skips zijn expliciet bedoelde live Enable Banking-tests (`ENABLE_BANKING_LIVE_TESTS=true`); de overige suite is offline en groen. De waarschuwingen zijn hoofdzakelijk Python 3.12-deprecations en zijn geen testfouten; opvolging valt onder ACT-24.

<a id="act-03"></a>

### ACT-03 — PostgreSQL en migraties toetsen

- **Acties:** Voeg een geïsoleerde PostgreSQL CI-service toe, test Alembic vanaf een lege database en inspecteer de gemigreerde tabellen, transactievelden en import-identiteitsconstraint met synthetische schema-informatie. Een bestaande-databaseproef volgt als aparte subactie wanneer een representatieve synthetische dump beschikbaar is.
- **Klaar wanneer:** Constraints en gebruikersscheiding worden op PostgreSQL getest; upgrades behouden bestaande gegevens; CI voert controles uit.
- **Validatie:** Migratieproeven en integratietests, zonder productiegegevens.

<a id="act-04"></a>

### ACT-04 — Accountstatus en sessie-intrekking

- **Acties:** Controleer `is_active` bij ieder beschermd verzoek. Voeg een versieveld toe aan gebruikerssessies en verhoog dit bij deactivering, wachtwoordreset en wachtwoordwijziging, zodat oude cookies ongeldig worden. Voeg regressietests toe.
- **Klaar wanneer:** Oude cookies geven na intrekking geen toegang; actieve accounts kunnen opnieuw inloggen; oude sessies worden bij invoering bewust afgehandeld.
- **Validatie:** Tests met oude cookie vóór/na iedere intrekkingsactie, inclusief OAuth-gebruiker.

<a id="act-05"></a>

### ACT-05 — Veilige configuratie en cookies

- **Acties:** Valideer productieconfiguratie en blokkeer ontbrekende/standaard sessiesleutels. Configureer Secure, HttpOnly en SameSite voor login en OAuth met expliciete lokale ontwikkelmodus. Gebruik HTTPS afgedwongen cookies in productie.
- **Klaar wanneer:** Onveilige productieconfiguratie start niet; HTTPS-login en OAuth blijven werken; localhost-ontwikkeling is gedocumenteerd.
- **Validatie:** Configuratie- en cookiechecks plus login/OAuth-smokecheck.

<a id="act-06"></a>

### ACT-06 — CSRF-bescherming controleren en aanvullen

- **Acties:** Inventariseer alle muterende routes en voeg passende CSRF-bescherming toe voor formulieren en JavaScript-verzoeken. Controleer mutaties via GET.
- **Klaar wanneer:** Ontbrekende of ongeldige bescherming wordt afgewezen; normale formulieren en callbacks blijven functioneren; uitzonderingen zijn gemotiveerd.
- **Validatie:** Positieve en negatieve tests voor gewone formulieren, JS en relevante callbacks.

<a id="act-07"></a>

### ACT-07 — Encryptie zonder stille terugval

- **Acties:** Stop opslag bij sleutel-/encryptiefouten. Onderscheid legacy platte tekst van beschadigde ciphertext. Controleer en herstel omzetting van bestaande gegevens, inclusief herhaalbaarheid en sleutelbeheer.
- **Klaar wanneer:** Foute sleutel of encryptiefout schrijft geen platte tekst; bestaande gegevens blijven controleerbaar leesbaar; omzetting is aantoonbaar volledig en veilig herhaalbaar.
- **Validatie:** Databasecontroles op ruwe opslag met geldige, ontbrekende en verkeerde sleutel; migratieproef op synthetische legacydata.

<a id="act-08"></a>

### ACT-08 — Geheimen en Docker-buildcontext opschonen

- **Acties:** Onderzoek stack.env en Git-historie zonder waarden te publiceren. Verwijder tracking en maak veilige voorbeelden. Sluit private keys en lokale agentconfiguratie uit van builds. Roteer blootgestelde geheimen via bevoegd beheer.
- **Klaar wanneer:** Geen geheimen in nieuwe commits/images; eventuele blootstelling heeft gedocumenteerde opvolging; rotatie wordt alleen voltooid genoemd na verificatie.
- **Validatie:** Controle van tracking en buildcontext; geredigeerde bevindingen. Herschrijf gedeelde Git-historie niet zonder expliciete opdracht.

<a id="act-09"></a>

### ACT-09 — Rekeninggebonden importherkenning

- **Acties:** Maak de database-identiteit uniek per rekening via `(account_id, import_hash)`. Gebruik bestaande stabiele bank-ID/hashwaarden; beperk opslagcontroles in handmatige, scheduler- en Enable Banking-imports tot de doelrekening. Behoud echte identieke betalingen op verschillende rekeningen en migreer de globale constraint.
- **Klaar wanneer:** Twee gebruikers/rekeningen kunnen dezelfde betaling importeren; herhaalde import dupliceert niet; twee echte identieke betalingen blijven behouden; bestaande imports blijven herkenbaar.
- **Validatie:** Regressietests voor alle genoemde gevallen en PostgreSQL-migratieproef; leg fallbackregels expliciet vast.

<a id="act-10"></a>

### ACT-10 — Importbatches en resultaatrapport

- **Acties:** Registreer importbron, batch, aantallen en redenen van overslaan/afkeuren. Toon een controleerbaar resultaat met verwijzing naar betrokken transacties.
- **Klaar wanneer:** Iedere import is herleidbaar; toegevoegd + overgeslagen + afgekeurd sluit aan op verwerkte invoer; alleen de eigenaar ziet resultaten.
- **Validatie:** Importtests met geldige, dubbele en ongeldige rijen en gebruikersscheiding.

<a id="act-11"></a>

### ACT-11 — Import veilig terugdraaien

- **Acties:** Ontwerp batch-terugdraaien met voorbeeld van impact en behandeling van daarna gewijzigde, gesplitste of gekoppelde transacties.
- **Klaar wanneer:** Een import is terug te draaien zonder stille verwijdering van latere wijzigingen of gedeelde gegevens; herhaalde actie is veilig; conflicten worden uitgelegd.
- **Validatie:** Tests voor ongewijzigde batch, gewijzigde transacties, koppelingen, mislukking/rollback en onbevoegde gebruiker.

<a id="act-12"></a>

### ACT-12 — Bankstatus en synchronisatiefouten zichtbaar

- **Acties:** Maak mislukte synchronisatie, laatste succesvolle update en verlopen/toekomstig verlopende toestemming zichtbaar voor eigenaar en beheer. Controleer retrygedrag en foutafhandeling.
- **Klaar wanneer:** Een fout wordt niet als succes weergegeven; melding bevat concrete vervolgstap; tokens en bankgegevens komen niet in foutmeldingen/logs.
- **Validatie:** Gesimuleerde timeout, API-fout, verlopen toestemming en succesvolle herhaling.

<a id="act-13"></a>

### ACT-13 — Deploymentfouten en healthchecks

- **Acties:** Laat Portainer HTTP- en inhoudelijke fouten de workflow stoppen. Voeg liveness/readiness toe, met databasecontrole waar nodig, en controle na uitrol.
- **Klaar wanneer:** API-fout of ongezonde app geeft mislukte deployment; gezonde app slaagt; controle heeft begrensde wachttijd en bruikbare diagnose.
- **Validatie:** Gesimuleerde HTTP/API-fouten en database-uitval plus geslaagde deploymentcontrole.

<a id="act-14"></a>

### ACT-14 — Vaste releaseversies en herstelprocedure

- **Acties:** Deploy een specifieke imageversie, voorkom overlappende deployments, toon/verifieer draaiende versie en documenteer rollback met schema-compatibiliteit.
- **Klaar wanneer:** Uitrol is aan commit/image te koppelen; twee releases verstoren elkaar niet; herstelpad houdt rekening met Alembic-migraties.
- **Validatie:** Uitrol- en herstelproef in geschikte testomgeving; bewijs van draaiende versie.

<a id="act-15"></a>

### ACT-15 — Backups en herstel aantoonbaar maken

- **Acties:** Inventariseer bestaande externe backups, bewaartermijnen en sleutelbeheer. Vul ontbrekende automatisering aan. Voer herstel uit naar een geïsoleerde omgeving.
- **Klaar wanneer:** Herstelde database en versleutelde velden zijn bruikbaar; herstelduur en gegevensverliesvenster zijn vastgelegd; ontbrekende toegang blijft expliciet open.
- **Validatie:** Gedocumenteerde restoreproef met aantallen/integriteitscontroles, zonder gegevens of geheimen in Git.

<a id="act-16"></a>

### ACT-16 — Gebruikersroutes en navigatie ontwerpen

- **Acties:** Loop dagelijkse taken door op desktop en mobiel. Ontwerp logische plaats voor analyse/statistieken en heldere namen voor dashboards. Leg bevindingen en voorgestelde indeling hier vast.
- **Klaar wanneer:** Taken en navigatieproblemen zijn concreet beschreven; gekozen indeling en belangrijkste routes zijn vastgelegd voor implementatie.
- **Validatie:** Taakgerichte inspectie van importeren, categoriseren, budget volgen, vermogen bekijken en hypotheekscenario gebruiken.
- **Besluit:** Zie [dagelijkse routes en navigatie](docs/INFORMATION-ARCHITECTURE.md). ACT-19 implementeert eventuele lege-staat- en foutmeldingaanpassingen; ACT-20 toetst de toegankelijkheid en mobiele eindcontrole.

<a id="act-17"></a>

### ACT-17 — Centraal actieoverzicht

- **Acties:** Combineer te categoriseren transacties, budgetoverschrijdingen, synchronisatieproblemen en herautorisatie met directe vervolglinks.
- **Klaar wanneer:** Gebruiker ziet alleen eigen actuele acties; aantallen kloppen; lege staat is duidelijk; ontbrekende bankkoppeling is geen fout.
- **Validatie:** Tests op tellingen, gebruikersscheiding en lege/foutstatussen plus desktop/mobiele controle.

<a id="act-18"></a>

### ACT-18 — Herkomst en actualiteit van bedragen

- **Acties:** Toon peildatum, gebruikte rekeningen en werkelijk/verwacht/geschat. Voeg doorklik naar transacties of rekenaannames toe bij relevante totalen.
- **Klaar wanneer:** Een gebruiker kan totaal en herkomst vergelijken met dezelfde filters; verouderde koersen/synchronisaties worden begrijpelijk aangeduid.
- **Validatie:** Reconciliatie van totalen en bronregels; filters, lege gegevens en oude koersen testen.

<a id="act-19"></a>

### ACT-19 — Navigatie, foutmeldingen en lege schermen

- **Acties:** Implementeer gekozen navigatie, consistente dashboardnamen en concrete vervolgstappen bij lege schermen en fouten. Behoud of redirect bestaande routes waar nodig.
- **Klaar wanneer:** Kernroutes blijven bereikbaar; actieve navigatie klopt; fouten en lege schermen geven een bruikbare vervolgstap.
- **Validatie:** Routetests en taakgerichte browsercontrole op desktop en mobiel.

<a id="act-20"></a>

### ACT-20 — Toegankelijkheid en mobiele eindcontrole

- **Acties:** Controleer toetsenbord, focus, labels, contrast, tabellen en foutfeedback in aangepaste gebruikersroutes. Verhelp gevonden blokkades.
- **Klaar wanneer:** Kernhandelingen zijn zonder muis en op een smal scherm uitvoerbaar; controles en resterende beperkingen zijn beschreven.
- **Validatie:** Handmatige toetsenbord/mobiele controle plus geschikte geautomatiseerde checks.

<a id="act-21"></a>

### ACT-21 — Importlogica afzonderlijk testbaar maken

- **Acties:** Haal importbusinesslogica uit routes naar gedeelde services voor bestandsimport, handmatige sync en scheduler. Stem af met ACT-09/10 om dubbel werk te voorkomen.
- **Klaar wanneer:** Routes verzorgen HTTP-afhandeling; gedeelde importregels staan op één plek; bestaande uitkomsten blijven gelijk behalve expliciete fixes.
- **Validatie:** Regressietests voor beide importpaden en scheduler; geen gelijktijdige refactor op dezelfde code.

<a id="act-22"></a>

### ACT-22 — Spaar- en terugkerende logica opsplitsen

- **Acties:** Scheid berekeningen, gegevensmutaties en rendering; centraliseer gedeelde regels voor projecties en koppelingen.
- **Klaar wanneer:** Berekeningen zijn zelfstandig testbaar; routegedrag en bestaande bedragen blijven gelijk.
- **Validatie:** Regressietests voor spaarplannen, overnames, koppelingen en projecties.
- **ACT-22a:** Pure regels zonder database verhuizen letterlijk naar app/recurring_schedule.py (perioden, actieve/overgeslagen maanden, projectiehash) en app/savings_calc.py (frequentiemaanden, eigen maandbedragen, kleurstatus). transactions.py en budgets.py importeren die niet meer uit de recurring-router. Klaar wanneer de functies inhoudelijk identiek zijn en unit-tests de bestaande uitkomsten vastleggen.
- **ACT-22b:** Verplaats de databasegebonden logica voor projecties en koppelingen (`sync_projected_transactions`, `cleanup_matched_projected`, `find_candidates_for_projected`, `link_transaction_to_recurring`, `_find_matching_transaction`, `auto_link_recurring_after_import`) naar een service, zodat banking, scheduler, budgets, dashboard en transactions niet meer uit routers importeren. Klaar wanneer bestaande routes gelijk werken en er regressietests voor projectie en koppeling zijn.

<a id="act-23"></a>

### ACT-23 — Hypotheeklogica opsplitsen

- **Acties:** Scheid scenarioberekeningen, databasewerk en schermweergave. Leg aannames bij berekeningen vast zonder ongemerkt financiële regels te wijzigen.
- **Klaar wanneer:** Scenario-uitkomsten blijven gelijk bij de refactor; gedeelde berekeningen staan op één plek en zijn zelfstandig testbaar.
- **Validatie:** Bestaande rekentests en routechecks; afwijkingen alleen met expliciete bugfix en regressietest.
- **ACT-23a:** Verplaats `_em_rate_for_date`, `_existing_mortgage_yearly_gross`, `_existing_mortgage_yearly_interest` en `_variant_stats` letterlijk van routers/mortgage.py naar app/mortgage_calc.py. Klaar wanneer uitkomsten identiek zijn aan de oude implementatie (golden master met vaste datum) en regressietests ze vastleggen.
- **ACT-23b:** Haal de scenariovergelijking uit `scenarios_detail` (overbruggingskosten, eerste-5-jaarsrente/-teruggaaf, kosten/inkomsten/resultaat, overschot per jaar, spaarsaldo, grafiekreeksen) naar functies in app/mortgage_calc.py; de route haalt gegevens op en rendert. Klaar wanneer de templatecontext voor een representatief scenario identiek blijft en de rekenstappen afzonderlijk getest zijn.
- **Aannames (vastgelegd in docstrings):** annuïtaire bestaande leningdelen gebruiken de rente van 1 januari (rentesprong midden in het jaar genegeerd); aflossingsvrij wordt pro rata per maand rond de wijzigingsdatum berekend; de getoonde teruggaaf is het gemiddelde over de rentevaste periode.

<a id="act-24"></a>

### ACT-24 — Gerichte foutafhandeling en logging

- **Acties:** Inventariseer brede excepts en stil ingeslikte fouten. Onderscheid verwachte gebruikersfouten van operationele fouten en voeg bruikbare logging toe zonder gevoelige inhoud.
- **Klaar wanneer:** Operationele fouten verdwijnen niet stil; gebruikers krijgen passende feedback; logs onthullen geen geheimen of transactiedetails.
- **Validatie:** Foutinjectie voor kritieke paden en controle van foutrespons/loginhoud.
- **Stand 2026-09-23:** ACT-24a ([PR #174](https://github.com/gjagils/checkthepockets/pull/174), merge `f5639e1`) logt twee stil ingeslikte fouten: de inbox-telling in app/main.py en het intrekken van een Enable Banking-sessie in app/routers/banking.py. Dit is een eerste deel; de actie is daarmee niet klaar. Er zijn geen tests toegevoegd.
- **ACT-24b — resterend:** (1) Leg de inventarisatie vast: 44 brede `except`/`except Exception` in app/, waarvan er 5 direct `pass`/`continue` doen (settings.py:295 en :300, auth.py:49, admin.py:527, savings.py:630). Per geval: verwachte gebruikersfout, operationele fout of bewust genegeerd, met reden. (2) Voeg logging of gebruikersfeedback toe waar een operationele fout nu verdwijnt. (3) Voorkom gevoelige inhoud in logs: `EnableBankingError` neemt de request-URL op in de melding, dus `exc_info=True` bij het intrekken van de sessie (ACT-24a) logt de sessie-ID; bij andere Enable Banking-aanroepen kunnen account-ID's zo in de logs komen. Redigeer de URL of log alleen status en foutcode. (4) Foutinjectietests voor de kritieke paden die loginhoud en foutrespons controleren, inclusief ACT-24a.

<a id="act-25"></a>

### ACT-25 — Meerdere bunq- en spaarrekeningen

- **Acties:** Onderzoek met een geautoriseerde koppeling welke bunq-betaal- en spaarrekeningen Enable Banking daadwerkelijk teruggeeft. Ondersteuning per spaarproduct is nog niet bevestigd. Controleer rekeningselectie, herautorisatie, namen, rekeningtype en ophalen van saldo onafhankelijk van transacties. Ontwerp herkenning van eigen overboekingen zodat ze niet als inkomsten/uitgaven dubbeltellen. Leg een handmatige/CSV-fallback vast voor niet-beschikbare rekeningen.
- **Klaar wanneer:** Beschikbaarheid is per rekeningtype bevestigd of als beperking vastgelegd; beschikbare rekeningen zijn afzonderlijk herkenbaar, ook zonder recente transacties; herautorisatie dupliceert niet; eigen overboekingen verstoren totalen niet. Splits onderzoek en eventuele implementatie in subacties voordat codewerk start; importwijzigingen hangen af van ACT-09.
- **Validatie:** Eerst echte accountlijst controleren met toestemming zonder IBANs/tokens in Git; daarna synthetische tests met meerdere spaarrekeningen, ontbrekende transacties, actuele saldi en eigen overboekingen. Een IBAN alleen bewijst geen API-ondersteuning.
- **Bronnen (geraadpleegd 2026-09-23):** [Enable Banking FAQ](https://enablebanking.com/docs/faq/), [API](https://enablebanking.com/docs/api/reference/), [bunq meerdere rekeningen](https://www.bunq.com/personal/features/bank-accounts); bestaande verwerking in app/routers/banking.py en app/scheduler.py.

<a id="act-26"></a>

### ACT-26 — Importvoorbeeld zonder gegevens van andere gebruikers

- **Aanleiding:** Gevonden tijdens ACT-21b (PR #175). `/import` en `/import/map` in app/routers/transactions.py markeren een voorbeeldrij als "al geïmporteerd" als de `import_hash` bij willekeurig welke gebruiker of rekening bestaat. Het voorbeeld toont dan ten onrechte duplicaten, en een gebruiker kan indirect afleiden dat een andere gebruiker een identieke transactie heeft. De opslag in `/import/confirm` controleert wel correct per rekening (ACT-09/ACT-21), dus er gaan geen gegevens verloren.
- **Acties:** Beperk de duplicaatcontrole in het voorbeeld tot de doelrekening van de ingelogde gebruiker, via dezelfde rekeningbepaling (bank + IBAN) als bij bevestigen. Heeft de gebruiker die rekening nog niet, dan is niets een duplicaat. Leg die gedeelde regel vast in app/import_service.py, zodat voorbeeld en opslag niet uit elkaar lopen.
- **Klaar wanneer:** Het voorbeeld toont alleen duplicaten van de eigen doelrekening; transacties van andere gebruikers of andere eigen rekeningen tellen niet mee; het getoonde aantal nieuw/dubbel komt overeen met het resultaat van bevestigen.
- **Validatie:** Routetests voor bekende bank en aangepaste CSV met: dezelfde hash bij een andere gebruiker, op een andere eigen rekening, op de doelrekening en een nog niet bestaande rekening. Controleer dat de aantallen in voorbeeld en bevestiging gelijk zijn.

## Onderbouwing van de eerste analyse

- Importidentiteit: [parser](app/parsers/base.py), [globale constraint](app/models.py)
  en [importafhandeling](app/routers/transactions.py).
- Sessies en configuratie: [auth](app/auth.py), [config](app/config.py),
  [adminacties](app/routers/admin.py).
- Encryptie: [crypto](app/crypto.py).
- Deployment: [workflow](.github/workflows/deploy.yml), [compose](docker-compose.yml).
- Navigatie: [basistemplate](app/templates/base.html).
- Onderhoud: grote routebestanden in app/routers; gerichte refactor, geen totale rewrite.
- Git-tracking van stack.env vastgesteld; inhoud en eventuele blootstelling moeten
  in ACT-08 worden beoordeeld zonder geheimen naar dit document te kopiëren.

## Actieve overdracht

Werk dit blok bij vóór iedere overdracht, ook wanneer tests of toegang blokkeren.
De branchversie beschrijft lopend werk; na merge wordt de centrale stand bijgewerkt.

| Veld | Waarde |
|---|---|
| Actie | ACT-23b — scenariovergelijking uit de detailroute |
| Status | Afgerond |
| Uitvoerder / datum | Claude Code / 2026-09-23 |
| Branch / PR | `codex/act-23b-scenario-comparison`; [PR #188](https://github.com/gjagils/checkthepockets/pull/188) gemerged (`d149d9a`) |
| Budget bij start | Claude Code usage-weergave (get_usage), 2026-09-23 13:47: 5-uurslimiet 29% gebruikt, week 43% gebruikt; extra usage uit. |
| Uitgevoerd | Nieuwe functies in app/mortgage_calc.py: `bridge_cost_summary`, `default_variant_summary`, `mortgage_budget_sum`, `scenario_monthly_total`, `variant_leftovers`, `add_variant_comparison`, `variant_chart_series`. `scenarios_detail` haalt alleen nog gegevens op, roept deze functies aan en rendert (rekenblok 316 → 104 regels). Een dode tussentoewijzing van `first_5y_refund` is vervallen. |
| Validatie | Golden master van de volledige templatecontext (96 KB: 4 varianten waarvan één zonder rente, overbrugging, bestaande leningdelen, budget met hypotheekcategorie, bijdragen) en van het terugvalpad zonder rentetabel: byte-identiek op main en branch. `python -m pytest tests/ --tb=short`: 476 passed, 2 skipped (live Enable Banking), 2820 warnings. Nieuw: tests/test_mortgage_scenario_comparison.py. |
| Openstaand | ACT-08 (rotatie van geheimen), ACT-15 (restoreproef op NAS) en ACT-25 (bunq-accountlijst met geautoriseerde koppeling) vragen handelingen of toegang van de gebruiker. |
| Volgende stap | Gebruiker: ACT-08-rotatie, ACT-15-restoreproef of ACT-25-accountlijst aanleveren; daarna kan de uitvoering verder. |

Voor een actie-overdracht vervang je bovenstaande waarden door het concrete
actie-ID, branch/PR, veranderingen, testcommando’s en resultaten, open besluiten,
belemmeringen en één eerstvolgende stap. Bewaar de afgeronde samenvatting hieronder.

## Besluitenlog

| Datum | Besluit | Reden / gevolgen |
|---|---|---|
| 2026-09-23 | Git en Markdown zijn de centrale bron; Codex en Claude Code volgen dezelfde workflow | Wisselen zonder afhankelijkheid van Linear, MCP of agentspecifiek geheugen |
| 2026-09-23 | Beide agentingangen verwijzen naar één workflow | Voorkomt twee uiteenlopende versies van afspraken |
| 2026-09-23 | Alle verbeteracties vrijgegeven; budgetcontrole vóór iedere start verplicht | Alleen een actie starten die inclusief tests, CI en afronding naar redelijke inschatting past; anders wachten |
| 2026-09-23 | Oude Linear-items blijven extern totdat relevant werk bewust is overgenomen | Geen claim dat de volledige bestaande backlog al is gemigreerd |
| 2026-09-23 | Gebruiker vraagt alle openstaande acties af te werken; ACT-22 en ACT-23 naar Gereed | Uitvoering blijft één actie tegelijk met budgetcontrole; ACT-08-rotatie, ACT-15-restoreproef en ACT-25-accountonderzoek vragen toegang of handelingen van de gebruiker |

## Uitvoeringslog

Voeg per afgeronde actie of overdracht een regel toe. Git bevat de volledige historie.

| Datum | Actie | Resultaat | Validatie / PR |
|---|---|---|---|
| 2026-09-23 | Inrichting | Actieplan en gedeelde repositorywerkwijze opgesteld | Zie actieve overdracht |

| 2026-09-23 | Inrichting afgerond | PR #134 gemerged (a65a899) | Groene GitHub CI |
| 2026-09-23 | ACT-01 | Python 3.12-omgeving, locks en deterministische offline tests ingevoerd | [PR #135](https://github.com/gjagils/checkthepockets/pull/135), CI groen; merge `0032f6d` |
| 2026-09-23 | ACT-02 | Testresultaten gereproduceerd en eerdere fouten geclassificeerd | Deze PR; 405 passed, 2 skipped, 2703 warnings |
| 2026-09-23 | ACT-03 | PostgreSQL 16-migratie en schema gecontroleerd in CI | [PR #138](https://github.com/gjagils/checkthepockets/pull/138), beide checks groen; merge `bb2fa44` |
| 2026-09-23 | ACT-04 | Accountstatus en sessie-intrekking toegevoegd | [PR #140](https://github.com/gjagils/checkthepockets/pull/140), beide checks groen; merge `f313593` |
| 2026-09-23 | ACT-05 | Productieconfiguratie en HTTPS-cookies veilig afgedwongen | [PR #142](https://github.com/gjagils/checkthepockets/pull/142), beide checks groen; merge `8ef7401` |
| 2026-09-23 | ACT-06 | Cross-origin mutaties geblokkeerd in productie | [PR #144](https://github.com/gjagils/checkthepockets/pull/144), beide checks groen; merge `d2292f0` |
| 2026-09-23 | ACT-07 | Encryptie faalt gesloten bij sleutel-, encryptie- en decryptiefouten | [PR #146](https://github.com/gjagils/checkthepockets/pull/146), beide checks groen; merge `a2bc34c` |
| 2026-09-23 | ACT-08 | stack.env uit tracking en gevoelige bestanden uit Dockercontext | [PR #148](https://github.com/gjagils/checkthepockets/pull/148), beide checks groen; merge `5d0b678`; secret-rotatie open |
| 2026-09-23 | ACT-21 | CSV-bevestiging, bank-sync en scheduler gebruiken één importservice | [PR #171](https://github.com/gjagils/checkthepockets/pull/171) en [PR #175](https://github.com/gjagils/checkthepockets/pull/175), beide checks groen; merge `df98838`; productievalidatie open |
| 2026-09-23 | ACT-24a | Twee stille fouten worden gelogd; ACT-24 gesplitst, ACT-24b open | [PR #174](https://github.com/gjagils/checkthepockets/pull/174), merge `f5639e1`; geen tests, sessie-ID kan in de logmelding staan |
| 2026-09-23 | ACT-26 | Importvoorbeeld telt alleen duplicaten op de eigen doelrekening | [PR #178](https://github.com/gjagils/checkthepockets/pull/178), beide checks groen; merge `f104c13`; productievalidatie open |
| 2026-09-23 | ACT-24 | Operationele fouten gelogd zonder bank-ID's; inventarisatie in docs/ERROR-HANDLING.md | [PR #174](https://github.com/gjagils/checkthepockets/pull/174) en [PR #180](https://github.com/gjagils/checkthepockets/pull/180), beide checks groen; merge `6acc298`; productievalidatie loginhoud open |
| 2026-09-23 | ACT-22a | Plannings- en spaarregels in app/recurring_schedule.py en app/savings_calc.py | [PR #182](https://github.com/gjagils/checkthepockets/pull/182), beide checks groen; merge `dc39afa` |
| 2026-09-23 | ACT-22 | Planningsregels, spaarberekeningen, projecties en koppelingen buiten de routers | [PR #182](https://github.com/gjagils/checkthepockets/pull/182) en [PR #184](https://github.com/gjagils/checkthepockets/pull/184), beide checks groen; merge `90e6b88` |
| 2026-09-23 | ACT-23a | Leningdeel- en variantberekening in app/mortgage_calc.py, uitkomsten identiek | [PR #186](https://github.com/gjagils/checkthepockets/pull/186), beide checks groen; merge `d16d38c` |
| 2026-09-23 | ACT-23 | Leningdeel-, variant- en scenariovergelijking in app/mortgage_calc.py; routes renderen alleen | [PR #186](https://github.com/gjagils/checkthepockets/pull/186) en [PR #188](https://github.com/gjagils/checkthepockets/pull/188), beide checks groen; merge `d149d9a` |
