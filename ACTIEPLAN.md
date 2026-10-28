# Centraal actieplan

Dit document is de bron voor **alle hieronder beschreven verbeteracties**, hun
voortgang, besluiten en overdracht. Lees ook [de gedeelde workflow](docs/WORKFLOW.md).
Bijwerken gebeurt in Git; een externe tracker of chatgeschiedenis is niet nodig.

## Huidige stand — 2026-09-23

- De repository-inrichting is gemerged via PR #134 (a65a899).
- De gebruiker heeft alle verbeteracties vrijgegeven op 2026-09-23, onder de budgetvoorwaarde uit docs/WORKFLOW.md.
- ACT-01 t/m ACT-14, ACT-16 t/m ACT-24 en ACT-26 t/m ACT-28 zijn afgerond; ACT-08 zonder rotatie (gelekte geheimen niet meer in gebruik).
- Open: ACT-15 (restoreproef NAS, later), ACT-25b (bunq geeft de tweede spaarrekening niet door; wacht op test met alleen die rekening) en ACT-29 (verkoopfactor per bezit).
- 2026-10-14: codereview vóór het UI-redesign vastgelegd in [docs/CODE-REVIEW-2026-10-14.md](docs/CODE-REVIEW-2026-10-14.md); ACT-32 t/m ACT-52 toegevoegd als `Gepland` (vier fasen, zie [opschoning](#act-32)). Nog niet vrijgegeven; de gebruiker pakt dit in een volgende sessie op. Baseline in Python 3.12: 512 geslaagd, 3 overgeslagen.
- Bestaande Linear-issues zijn niet geïmporteerd of gecontroleerd op overlap.
- Testsuite in de vastgelegde Python 3.12-omgeving: 496 geslaagd, 2 bewust
  overgeslagen live-tests (controle 2026-09-23 na ACT-28). Productievalidatie na uitrol is per actie vermeld.

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
| ACT-08 | P1 | Afgerond | — | [Geheimen en Docker-buildcontext opschonen](#act-08) |
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
| ACT-25 | P2 | Bezig | — | [Meerdere bunq- en spaarrekeningen](#act-25) |
| ACT-25a | P2 | Afgerond | — | [Rekeningen zonder uid zichtbaar na koppelen](#act-25) |
| ACT-25b | P2 | Geblokkeerd | ACT-25a | [Beschikbaarheid bunq-rekeningen vaststellen en vervolg kiezen](#act-25) |
| ACT-26 | P1 | Afgerond | ACT-21 | [Importvoorbeeld zonder gegevens van andere gebruikers](#act-26) |
| ACT-27 | P2 | Afgerond | — | [Compacte spaarplanner](#act-27) |
| ACT-27a | P2 | Afgerond | — | [Eén regel per spaarregel, regel Beweging, compacte kop](#act-27) |
| ACT-27b | P2 | Afgerond | ACT-27a | [Toekomstige maanden direct bewerkbaar](#act-27) |
| ACT-28 | P2 | Afgerond | — | [Vermogensprognose per persoon](#act-28) |
| ACT-28a | P2 | Afgerond | — | [Rekenkern vermogen per persoon per maand](#act-28) |
| ACT-28b | P2 | Afgerond | ACT-28a | [Plan per 1/1 automatisch vastleggen](#act-28) |
| ACT-28c | P2 | Afgerond | ACT-28a, ACT-28b | [Pagina Vermogensprognose](#act-28) |
| ACT-28d | P2 | Afgerond | ACT-28c | [Losse boekingen per cel](#act-28) |
| ACT-29 | P2 | Gepland | ACT-28 | [Verkoopfactor per bezit in de vermogensprognose](#act-29) |
| ACT-30 | P2 | Review | — | [Rekeningen samenvoegen met preview](#act-30) |
| ACT-31 | P2 | Review | ACT-25 | [bunq API-koppeling met eigen sleutel](#act-31) |
| ACT-32 | P1 | Afgerond | — | [Encryptie-bugs: duplicaten, regelsuggesties, herversleutelen](#act-32) |
| ACT-33 | P1 | Afgerond | — | [Auth-fixes: uitnodiging, e-mailverificatie, rate limiting, proxy](#act-33) |
| ACT-34 | P1 | Afgerond | — | [Crash- en datafouten in routes](#act-34) |
| ACT-35 | P1 | Afgerond | — | [XSS in templates](#act-35) |
| ACT-36 | P2 | Afgerond | — | [Repo-hygiëne, configuratie en deploy-trigger](#act-36) |
| ACT-37 | P3 | Afgerond | — | [Tooling: ruff, pyproject, coverage, dependabot](#act-37) |
| ACT-38 | P2 | Afgerond | — | [Verouderde API's: TemplateResponse, lifespan, tijd](#act-38) |
| ACT-39 | P2 | Afgerond | — | [Testfundament met conftest](#act-39) |
| ACT-40 | P2 | Afgerond | ACT-38 | [Dependency-upgrade](#act-40) |
| ACT-41 | P2 | Afgerond | ACT-39 | [Schema-hygiëne en migratie](#act-41) |
| ACT-42 | P2 | Afgerond | ACT-39 | [Transactiegrenzen, banksync-service en scheduler-lock](#act-42) |
| ACT-43 | P3 | Afgerond | ACT-37 | [Gedeelde helpers en foutafhandelingsconventie](#act-43) |
| ACT-44 | P3 | Afgerond | ACT-39 | [Savings-service en N+1](#act-44) |
| ACT-45 | P3 | Afgerond | ACT-39 | [Recurring en transactions: batching en custom-CSV-parser](#act-45) |
| ACT-46 | P3 | Afgerond | ACT-39 | [Mortgage-formulieren en lange functies opknippen](#act-46) |
| ACT-47 | P2 | Review | — | [CSS-tokens en dode CSS](#act-47) |
| ACT-48 | P2 | Review | — | [Gedeeld JavaScript en gepinde Chart.js](#act-48) |
| ACT-49 | P2 | Review | ACT-48 | [Jinja-macro's en filters](#act-49) |
| ACT-50 | P3 | Review | ACT-47, ACT-49 | [Inline styles naar utility-classes](#act-50) |
| ACT-51 | P2 | Afgerond | ACT-39 | [HTTP-vangnet voor redesign-schermen en parsers](#act-51) |
| ACT-52 | P3 | Review | ACT-41 | [Model-typing: Boolean, enums, Mapped](#act-52) |
| ACT-53 | P2 | Review | ACT-31, ACT-28 | [Persoonspagina: verwachting betaalrekeningen en vermogen](#act-53) |
| ACT-54 | P2 | Review | — | [Regelvoorstellen leesbaar: volledige omschrijving en groepering](#act-54) |
| ACT-55 | P2 | Review | ACT-31 | [Rekeninggroepen, één categorieënset en budget per groep](#act-55) |
| ACT-58 | P2 | Afgerond | — | [Categoriesuggesties bij transacties met weinig AI-calls](#act-58) |
| ACT-59 | P2 | Afgerond | ACT-57 | [Vaste spaarstortingen automatisch categoriseren](#act-59) |
| ACT-60 | P2 | Review | ACT-58 | [Categoriseren per tegenpartij, met regel in één klik](#act-60) |

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
- **Afronding 2026-09-23:** De repository is openbaar, dus de oude stack.env was leesbaar via de Git-geschiedenis. Daarin stonden als geheimen `SECRET_KEY` en `POSTGRES_PASSWORD`; `ENABLE_BANKING_APP_ID` is een ID, de private key heeft nooit in Git gestaan. De gebruiker vergeleek SHA-256-vingerafdrukken (12 tekens, lokaal, zonder waarden te delen) van de gelekte waarden met de productieconfiguratie in Portainer: beide verschillen. Productie gebruikt een Neon-database; de `POSTGRES_*`-waarden hoorden bij een eerdere eigen database. Rotatie is daarmee niet nodig. De Git-geschiedenis is niet herschreven. `GOOGLE_CLIENT_SECRET`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY` en `FIELD_ENCRYPTION_KEY` hebben nooit in Git gestaan.

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
- **Waarneming 2026-09-23:** Bij een autorisatie van twee bunq-spaarrekeningen verscheen alleen de tweede; bij een nieuwe autorisatie van alleen de eerste bleef de lijst leeg. Volgens de gebruiker werkt die rekening normaal in bunq. Enable Banking laat `uid` weg als saldo en transacties niet op te halen zijn; de callback sloeg zulke rekeningen stil over.
- **ACT-25a:** Bewaar en toon alle rekeningen uit de sessie (IBAN, soort, status), ook zonder `uid`; geen succesmelding als niets op te halen is; log per rekening volgorde, soort en of er een `uid` was, zonder IBAN's of ID's. Klaar wanneer een rekening zonder `uid` zichtbaar is en niet in de synchronisatielijst staat.
- **Uitkomst ACT-25a in productie:** twee rekeningen aangevinkt, `POST /sessions` gaf er één terug (met uid, door bunq als `CARD` gelabeld); de tweede ontbrak volledig.
- **ACT-25b:** Vul rekeningen aan uit `GET /sessions/{id}` (`accounts`/`accounts_data`) en log aantallen en veldnamen. Na uitrol opnieuw koppelen en de log/resultaatpagina lezen. Ontbreekt de rekening helemaal of komt hij zonder `uid` terug, dan ligt de beperking bij bunq/Enable Banking (navragen bij Enable Banking, CSV-fallback vastleggen); komt hij met `uid` terug, dan verder zoeken in de app. Daarna eigen overboekingen en saldo zonder transacties.

<a id="act-26"></a>

### ACT-26 — Importvoorbeeld zonder gegevens van andere gebruikers

- **Aanleiding:** Gevonden tijdens ACT-21b (PR #175). `/import` en `/import/map` in app/routers/transactions.py markeren een voorbeeldrij als "al geïmporteerd" als de `import_hash` bij willekeurig welke gebruiker of rekening bestaat. Het voorbeeld toont dan ten onrechte duplicaten, en een gebruiker kan indirect afleiden dat een andere gebruiker een identieke transactie heeft. De opslag in `/import/confirm` controleert wel correct per rekening (ACT-09/ACT-21), dus er gaan geen gegevens verloren.
- **Acties:** Beperk de duplicaatcontrole in het voorbeeld tot de doelrekening van de ingelogde gebruiker, via dezelfde rekeningbepaling (bank + IBAN) als bij bevestigen. Heeft de gebruiker die rekening nog niet, dan is niets een duplicaat. Leg die gedeelde regel vast in app/import_service.py, zodat voorbeeld en opslag niet uit elkaar lopen.
- **Klaar wanneer:** Het voorbeeld toont alleen duplicaten van de eigen doelrekening; transacties van andere gebruikers of andere eigen rekeningen tellen niet mee; het getoonde aantal nieuw/dubbel komt overeen met het resultaat van bevestigen.
- **Validatie:** Routetests voor bekende bank en aangepaste CSV met: dezelfde hash bij een andere gebruiker, op een andere eigen rekening, op de doelrekening en een nog niet bestaande rekening. Controleer dat de aantallen in voorbeeld en bevestiging gelijk zijn.

<a id="act-27"></a>

### ACT-27 — Compacte spaarplanner

- **Aanleiding:** De gebruiker wil het overzicht van de eigen Excel-spaarsheet (alles op één scherm, makkelijk aanpassen) met de functionaliteit van de planner. Elke regel besloeg twee regelhoogtes en bewerken ging alleen via een uitklapformulier.
- **Besluiten gebruiker (2026-09-23):** actieknoppen per regel verschijnen bij hover (op aanraakschermen altijd); toekomstige maanden worden direct in de cel bewerkbaar, verleden maanden blijven de werkelijke transactiebedragen.
- **ACT-27a:** Eén regel per spaarregel (badge, naam, acties), kleinere celafstand en maandkolommen, compacte kop, regel "Beweging" (saldo min vorige maand) boven "Saldo". Klaar wanneer ±20 regels plus beweging en saldo op 1920×1080 zonder scrollen passen.
- **ACT-27b:** Klik op een toekomstige cel → bedrag typen, Enter/Tab slaat op en gaat naar de volgende cel; saldo en beweging werken direct bij. Een afwijkend maandbedrag maakt de regel 'onregelmatig' met behoud van de overige maanden. Alleen eigen plannen; verleden en lopende maand niet bewerkbaar. Klaar wanneer dit met route- en eigenaartests is afgedekt.

<a id="act-28"></a>

### ACT-28 — Vermogensprognose per persoon

- **Aanleiding:** De gebruiker volgt goud, zilver, beleggen en sparen per persoon in een spreadsheet (tabblad 2026, rij 46–67): per begin van de maand, bezit per persoon via aandeel × app-waarde × verkoopfactor 0,982, groei 0,8%/maand, beleggen (vorige + €150) × 1,01, spaar samen uit het spaarplan, kinderspaar + €60/maand met losse boekingen. Begin januari kopieert hij de waarden als "Plan per 1/1" om voor/achter te zien. Mockup besproken op 2026-09-23.
- **Besluiten gebruiker (2026-09-23):** weergave per persoon (Samen, Nelleke, Hannah, Suze), niet per soort bezit; rood/groen vergelijkt met plan 1/1 (niet met vorige maand); goud/zilver staan vermoedelijk al per persoon in de Portfolio (controleren bij ACT-28a).
- **Bestaande bouwstenen:** `PortfolioHolding` (bezit per persoon, inleg per maand), `PortfolioAsset` (koers, `monthly_growth_pct`, spread/verkoopkosten), `PortfolioPriceSnapshot` (koers per maand), `account_owners` (rekening ↔ persoon), spaarplanner (lopend saldo).
- **ACT-28a:** Service die per persoon en bezit de stand per begin van de maand (1/1 t/m eind dec) berekent: verleden uit koers-momentopnames en saldi, toekomst met groei, inleg en verkoopkosten; spaarrekeningen via eigenaar en spaarplan. Klaar wanneer een testgeval met de rekenregels van de sheet dezelfde bedragen oplevert en gebruikersscheiding getest is.
- **ACT-28b:** Bevroren plan per jaar (model + migratie), automatisch op 1 januari en handmatig vast te leggen; opnieuw vastleggen alleen na bevestiging. Klaar wanneer het plan niet meer meebeweegt met latere wijzigingen.
- **ACT-28c:** Pagina met weergaven Prognose / Plan 1/1 / Verschil, filter en inklappen per persoon, kleuren t.o.v. plan, tegels "nu vs plan" en "prognose eind jaar"; compact zoals ACT-27a, bruikbaar op mobiel. Klaar met route- en eigenaartests en een schermcontrole.
- **ACT-28d:** Losse bij-/afboekingen per persoon, bezit en maand direct in de cel (vervangt `+1000`/`−7500` in formules). Klaar met tests op herberekening en eigenaarschap.

- **Uitkomst en aannames (review 2026-09-23, Claude Code):** Gebouwd in app/wealth_forecast.py, app/wealth_plan_service.py, migraties 064/065 en /portfolio/wealth-forecast (menu Portfolio → Vermogensprognose); plan wordt op 1 januari 00:05 automatisch vastgelegd en vervangen alleen na bevestiging. Aannames in de code: (1) verkoopfactor 0,982 geldt voor alle portfoliobezit, ook beleggen, en negeert spread/verkoopkosten per bezit (afwijking van de sheet → ACT-29); (2) een rekening met meerdere eigenaren wordt gelijk over die eigenaren verdeeld — voor de groep "Samen" moet een persoon "Samen" eigenaar zijn; (3) ontbreekt een koers-momentopname voor een verstreken maand, dan telt de huidige koers. Codex valideerde lokaal op Python 3.14; herhaald in Python 3.12: 496 passed, 2 skipped. Deployments van #199, #201, #202 en #203 geslaagd. Een schermcontrole (desktop en mobiel) van ACT-28c is niet vastgelegd en staat open, net als controle met eigen gegevens.

<a id="act-29"></a>

### ACT-29 — Verkoopfactor per bezit in de vermogensprognose

- **Aanleiding:** Review van ACT-28: `SELL_FACTOR = 0,982` wordt op alle portfoliobezit toegepast. In de sheet geldt de factor alleen voor goud en zilver; beleggen telt volledig mee. De Portfolio kent al `spread_pct` en verkoopkosten per bezit.
- **Acties:** Gebruik per bezit de verkoopwaarde uit de eigen spread/verkoopkosten (goud/zilver 1,8% ≙ 0,982), beleggen zonder aftrek tenzij ingesteld; leg de keuze vast in de docstring.
- **Klaar wanneer:** Beleggen volgt `(vorige + inleg) × groei` zonder factor, goud/zilver houden 0,982 via hun instelling, en een bevroren plan wijzigt niet mee.
- **Validatie:** Regressietests per bezitsoort en een test dat bestaande plannen ongewijzigd blijven.

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
| Actie | ACT-28d — losse boekingen per cel |
| Status | Afgerond |
| Uitvoerder / datum | Codex / 2026-09-23 |
| Branch / PR | `codex/act-28d-adjustments`; [PR #203](https://github.com/gjagils/checkthepockets/pull/203) gemerged (`fde6ebb`) |
| Budget bij start | Codex usage-weergave, 2026-09-23 14:13: 67% resterend in vijf uur, 85% per week; afgebakend op mutatiemodel, migratie, eigenaarschap, celbewerking, tests, CI en merge. |
| Uitgevoerd | `WealthAdjustment` bewaart een losse euroboeking per gebruiker, bezit, persoon en maand. De prognose rekent deze direct door; de pagina toont per bezit/persoon twaalf bewerkbare cellen. Een lege cel verwijdert de boeking. De route accepteert alleen een eigen bezit met eigen persoon én bestaande holding. |
| Validatie | Lokale Python 3.14: 6 passed voor ACT-28a/b/d, inclusief bij-/afboeken, herberekening, wissen en eigenaarschap. PR #203: Python 3.12-test en PostgreSQL-migraties beide groen. |
| Openstaand | Productiecontrole met eigen vermogensgegevens; ACT-25b (beschikbaarheid van ontbrekende bunq-rekening) en ACT-15 (isolated restore) blijven los open. |
| Volgende stap | Gebruiker kan de pagina invullen via Portfolio → Vermogensprognose. |

Voor een actie-overdracht vervang je bovenstaande waarden door het concrete
actie-ID, branch/PR, veranderingen, testcommando’s en resultaten, open besluiten,
belemmeringen en één eerstvolgende stap. Bewaar de afgeronde samenvatting hieronder.

### ACT-30 — Rekeningen samenvoegen met preview

- **Probleem:** een CSV-rekening en een bankkoppeling van dezelfde rekening bestaan los naast elkaar en bevatten overlappende transacties met verschillende `import_hash`.
- **Gedrag:** `/accounts/{id}/merge` toont een preview (te verplaatsen en dubbele transacties); pas na bevestiging worden transacties verplaatst, dubbelen op datum + bedrag + tegenpartij of omschrijving één-op-één samengevoegd (categorie, controlestatus, uitsluiting, terugkerende post en koppelingen blijven behouden) en wordt de bronrekening verwijderd. Twijfelgevallen worden verplaatst, niet samengevoegd.
- **Onderdelen:** app/account_merge.py, routes in app/routers/accounts.py, accounts/merge.html, tests/test_account_merge.py. Geen migratie.
- **Validatie:** lokaal Python 3.14 zonder psycopg2: 502 passed, 3 skipped. PostgreSQL en Python 3.12 via CI.
- **Open:** productiecontrole met de echte ABN-rekeningen na uitrol.

### ACT-31 — bunq API-koppeling met eigen sleutel

- **Probleem:** bunq loopt via Enable Banking en geeft de tweede spaarrekening niet door (ACT-25b). De bunq-API geeft per gebruiker alle rekeningen.
- **ACT-31a (Review):** `/banking/bunq` (alleen beheerder, zoals de bankkoppeling): API-sleutel invoeren, versleuteld opslaan (`BunqConnection`, migratie 066; weigert opslaan zonder veldversleuteling), verbinden (installation → device-server → session-server, POST's ondertekend) en alle rekeningen met soort, IBAN, status en saldo tonen. Alleen lezen; geen transacties. Bij een geweigerde opgeslagen installatie (bv. IP gewijzigd) wordt het apparaat één keer opnieuw geregistreerd. `BUNQ_API_BASE` kan naar de sandbox wijzen.
- **Aannames/beperkingen:** het serverantwoord wordt niet op handtekening gecontroleerd (alleen TLS); paginering van rekeningen is `count=200` zonder doorbladeren; de sleutel is gebonden aan het uitgaande IP-adres van de server.
- **Validatie:** lokaal Python 3.14 zonder psycopg2, nagebootste bunq: 509 passed, 3 skipped. PostgreSQL-migratie en Python 3.12 via CI. Niet getest tegen echte bunq of sandbox.
- **Volgende stappen:** sleutel invoeren op de NAS en kijken of de tweede spaarrekening verschijnt (beslist ACT-31b: transactie-sync via `store_parsed_transactions`, koppeling aan bestaande rekeningen op IBAN, eigen overboekingen).

- **ACT-31b (Review):** rekeningen aanvinken om te importeren, soort (betaal/spaar; standaard uit bunq, `accounts.kind`) en doelrekening kiezen (bestaande rekening, IBAN-match of nieuw); voorbeeld zonder opslaan en daarna importeren; betalingen via de `payment`-endpoint met paginering en incrementele sync (`last_payment_id`); identiteit via het bunq-id (twee identieke betalingen blijven beide bestaan); betalingen die al via CSV op dezelfde rekening staan worden overgeslagen (datum + bedrag + tegenpartij/omschrijving, één-op-één, alleen tegen niet-bunq-boekingen); overboekingen tussen eigen rekeningen worden automatisch gekoppeld (`transfer_id`) bij tegenrekening-IBAN, omgekeerd bedrag, ≤3 dagen verschil en precies één kandidaat; geplande sync om 01:30 en 17:30 (`bunq_sync`). Op de rekeningenpagina zijn naam en soort (betaal/spaar) aanpasbaar (`POST /accounts/{id}/update`); IBAN en eigenaar(s) zijn zichtbaar, het IBAN is alleen-lezen. Migratie 067. Bunq kent geen endpoint voor aandelen (bunq Stocks) in de documentatie; die blijven handmatig in Portfolio.
- **Validatie ACT-31b:** lokaal Python 3.14 zonder psycopg2, nagebootste bunq: 519 passed, 3 skipped. PostgreSQL-migratie en Python 3.12 via CI. Niet getest tegen echte bunq-betalingen.

### ACT-53 — Persoonspagina: verwachting betaalrekeningen en vermogen

- **Doel (gebruiker, 2026-10-14):** een pagina per persoon met een overzicht van wat je verwacht op de betaalrekeningen en een vermogensdeel.
- **Basis die er al is:** eigenaren per rekening, soort rekening (ACT-31b), terugkerende posten en projecties, vermogensprognose per persoon (ACT-28).
- **Nog te beslissen vóór start:** welke periode de verwachting beslaat, hoe gedeelde rekeningen over personen verdeeld worden (zoals ACT-28: gelijk), en of spaarrekeningen in het vermogensdeel meetellen.

## Opschoning vóór het UI-redesign (ACT-32 t/m ACT-52)

Bron: [codereview van 2026-10-14](docs/CODE-REVIEW-2026-10-14.md). Daar staan
per actie de bevindingen met bestand en regelnummer (verwijzingen A1–A15, B1–B13,
C1–C14, D1–D10, E1–E8, F1–F9). Vier fasen: bugs en beveiliging (ACT-32–35),
hygiëne en tooling (ACT-36–40), backend-structuur (ACT-41–46), front-end-fundament
(ACT-47–52). Iedere actie is één PR. Regelnummers in de review gelden voor
commit `339a4d8`; controleer ze bij het oppakken.

<a id="act-32"></a>

### ACT-32 — Encryptie-bugs: duplicaten, regelsuggesties, herversleutelen

- **Aanleiding:** Review A1, A2, A3, B11. `duplicates_page` en `suggest_rules` groeperen in SQL op `counterparty`, een `EncryptedText`-kolom met random IV; in productie (sleutel verplicht) zijn beide altijd leeg. `encrypt_existing_transactions` leest de ontsleutelde waarde en schrijft niets. Lezen met een geconfigureerde maar ongeldige sleutel geeft ciphertext aan de UI.
- **Acties:** Duplicaten en regelsuggesties in Python groeperen na laden van de eigen transacties (lost ook de N+1 per groep op). Herversleutelen via ruwe kolomwaarden en `flag_modified` of directe `update()`. Read-path fail-closed in `app/crypto.py`.
- **Klaar wanneer:** Met `FIELD_ENCRYPTION_KEY` gezet toont de duplicatenpagina echte duplicaten en geeft `suggest_rules` suggesties; herversleutelen verandert de ruwe DB-waarde aantoonbaar; ongeldige sleutel geeft een fout, geen ciphertext.
- **Validatie:** Tests die met een testsleutel draaien en de ruwe kolomwaarde controleren; bestaande tests zonder sleutel blijven groen.
- **Uitkomst (Review, 2026-10-14, Claude Code):** alle vier bevestigd en opgelost. Duplicatenpagina selecteert eerst op de platte kolommen (datum, bedrag) en groepeert de tegenpartij in Python (niet-hoofdlettergevoelig); `suggest_rules` telt in Python; `encrypt_existing_transactions` leest de ruwe waarde met `type_coerce` en schrijft via een Core-UPDATE (de ORM gaf de ontsleutelde waarde terug, dus er werd nooit iets versleuteld); het leespad weigert nu ook als de sleutel geconfigureerd maar ongeldig is. Vier nieuwe tests met versleuteling aan, alle vier rood zonder de fix. Lokaal Python 3.14 zonder psycopg2: 529 passed, 3 skipped; Python 3.12 en PostgreSQL via CI.

<a id="act-33"></a>

### ACT-33 — Auth-fixes: uitnodiging, e-mailverificatie, rate limiting, proxy

- **Aanleiding:** Review A5, B1, B2, B3, B6, B7, B8, B10.
- **Acties:** Uitnodigingstoken pas consumeren in dezelfde commit als het aanmaken van de gebruiker. Google-callback weigert zonder `email_verified`. Rate limiting generaliseren naar `is_rate_limited(bucket, key)` en toepassen op register, forgot-password en reset; lege entries opruimen. Uvicorn starten met `--proxy-headers --forwarded-allow-ips` en `_client_ip` op `request.client.host`. Logout via POST. E-mail normaliseren en gebruikersnaam strippen/begrenzen bij registratie. `html.escape` in `email_service.py`. Route `/accounts/delete-all-transactions` en bijbehorend formulier verwijderen.
- **Klaar wanneer:** Een tikfout bij registreren verbrandt de uitnodiging niet; een ongeverifieerd Google-adres kan geen bestaand account overnemen; alle vier auth-formulieren zijn begrensd; `X-Forwarded-For` uit een niet-vertrouwde bron wordt genegeerd; `GET /logout` logt niet uit.
- **Validatie:** Regressietests per punt, inclusief oude-cookie- en XFF-gevallen; handmatige login/OAuth-smokecheck na uitrol.

<a id="act-34"></a>

### ACT-34 — Crash- en datafouten in routes

- **Aanleiding:** Review A4, A6–A15, B9.
- **Acties:** `delete_category` FK-veilig (transacties op NULL, budgets en preset-lines verwijderen, kinderen via ORM) en `PRAGMA foreign_keys=ON` in de SQLite-testengine. Onbereikbare `return` in `app/scheduler.py` naar `_run_weekly_digests`. Timeouts en één `requests.Session` in `app/enable_banking.py`; `coalesce`/`misfire_grace_time` op de jobs. Savings-helpers filteren op `is_excluded`/`is_projected`. `budget_from_average` via `category_spending_average`. `Rule.name[:100]`. URL-encoding in `link_recurring`. Transfer-partner loskoppelen en split-kinderen meeverhuizen. Categorie-naamconflict in de merge-preview. `app/forms.py` met `parse_amount`, `parse_percent`, `parse_int`, `parse_iso_date` op alle formulierparsing. `safe_redirect(target, fallback)` voor alle `redirect_to`. Handmatige scheduler-run via `modify_job` met logging.
- **Klaar wanneer:** Geen van de genoemde invoer geeft nog een 500; spaartotalen tellen verwachte en uitgesloten transacties niet mee; digest-summary is gevuld; een hangende bankverbinding blokkeert de scheduler niet langer dan de timeout.
- **Validatie:** Foutinjectietests per punt; bestaande suite groen op SQLite met FK's aan en in de PostgreSQL-CI-job.

<a id="act-35"></a>

### ACT-35 — XSS in templates

- **Aanleiding:** Review B4, B5. `savings/detail.html` zet tegenpartijnamen uit bankdata ongeëscaped in `innerHTML`; `dashboard/index.html` gebruikt `json.dumps` met `|safe`; Jinja-waarden staan direct in JS-literals (dashboard, budgets, wealth_forecast).
- **Acties:** `textContent`/`createElement` of gedeelde `escapeHtml`; `|tojson` i.p.v. `|safe`; JS-data via `tojson` of `data-*`-attributen.
- **Klaar wanneer:** Een tegenpartij of categorienaam met `<script>` of `&` wordt letterlijk getoond en breekt geen lookup.
- **Validatie:** Routetests met zulke namen die de HTML-uitvoer controleren.

<a id="act-36"></a>

### ACT-36 — Repo-hygiëne, configuratie en deploy-trigger

- **Aanleiding:** Review F3–F7, B13.
- **Acties:** `git rm --cached` voor `Wissellijst` (kapotte submodule-verwijzing), `.DS_Store`, `app/.DS_Store`. `deploy.sh`, `scripts/deploy-to-synology.sh` en `make init-env` verwijderen. `.gitignore` inkorten en `*.db`, `.DS_Store` toevoegen; `.dockerignore` aanvullen (`docs/`, `*.db`, `.DS_Store`, dubbele `stack.env` weg, comment bij `*.md`). `.env.example` volledig met alle twintig sleutels en markering "verplicht in productie"; `POSTGRES_*` eruit; compose aanvullen met `BUNQ_API_BASE`, `SESSION_MAX_AGE`, `CSRF_ENFORCE`, `LOG_LEVEL` en zonder `SECRET_KEY`-default. `deploy.yml`: `paths-ignore` naar `'*.md'`, `'docs/**'`, `'.claude/**'` zodat `app/docs` wél deployt; `concurrency: deploy-main`. `ci.yml`: ook op push naar `main`, `permissions`, `timeout-minutes`. Verouderde zinnen in OPERATIONS/DEVELOPMENT/WORKFLOW over ACT-01/03/08/14 corrigeren. `BACKLOG.md` naar `docs/archive/`.
- **Klaar wanneer:** `git submodule status` faalt niet meer; een wijziging aan alleen `app/docs` triggert een deployment; twee snelle pushes deployen na elkaar; `.env.example` en `app/config.py` noemen dezelfde sleutels. Daarna branch protection op `main` instellen met required checks `test` en `postgres-migrations` (handmatig in GitHub, door de gebruiker).
- **Validatie:** Linkcontrole, `git diff --check`, één deploy-verificatie na merge.

<a id="act-37"></a>

### ACT-37 — Tooling: ruff, pyproject, coverage, dependabot

- **Aanleiding:** Review F9, C14. Geen linter, formatter of coverage; 27 ongebruikte imports, 8 ongebruikte variabelen, dode condities en uitgecommentarieerde code.
- **Acties:** `pyproject.toml` met `[tool.ruff]` (`E,F,I,B,UP`, py312, line-length 120, `alembic/versions` uitgesloten, `per-file-ignores` voor `tests/*` E402 tot ACT-39) en `[tool.pytest.ini_options]`. `ruff` en `pytest-cov` in `requirements-dev.in`, locks regenereren volgens DEVELOPMENT.md. CI-stap `ruff check` en `ruff format --check`; tests met `--cov=app` zonder drempel. `Makefile` met `test/lint/fmt/check`. `.github/dependabot.yml` voor `github-actions` (pip-updates lopen via de lockprocedure). Eerste `ruff --fix` voor `F401/I/UP` en de dode code uit review C14 als aparte commit in dezelfde PR.
- **Klaar wanneer:** `make check` is groen en CI faalt op nieuwe lintfouten; geen gedragswijziging.
- **Validatie:** Volledige suite groen; diff van de fix-commit handmatig nagelopen.

<a id="act-38"></a>

### ACT-38 — Verouderde API's: TemplateResponse, lifespan, tijd

- **Aanleiding:** Review C1, C2, B12. 118× `TemplateResponse("naam", {...})` (verwijderd in Starlette 1.0, ~2.900 testwaarschuwingen); `@app.on_event`; 29× `utcnow()` en 41× `date.today()` in een UTC-container met Nederlandse gebruikers; inbox-middleware per request met eigen sessie zonder sessie-intrekkingscontrole.
- **Acties:** Alle aanroepen naar `TemplateResponse(request, "naam", ctx)`. `lifespan` i.p.v. `on_event`, inclusief scheduler-shutdown. `app/clock.py` met `now_utc()` en `today_nl()` (Europe/Amsterdam); alle `utcnow`/`today`-plekken omzetten; rekenfuncties krijgen `today` als parameter. Inbox-telling alleen na `get_current_user` en alleen voor HTML-routes.
- **Klaar wanneer:** De suite geeft geen `TemplateResponse`- of `utcnow`-waarschuwingen meer; een test met vaste datum rond middernacht NL-tijd geeft de juiste dag en maand; een ingetrokken cookie vult de inbox-badge niet.
- **Validatie:** Volledige suite; waarschuwingentelling in de overdracht.

<a id="act-39"></a>

### ACT-39 — Testfundament met conftest

- **Aanleiding:** Review F1. 41 testbestanden zetten elk `DATABASE_URL` op moduleniveau, maar de engine wordt één keer gemaakt; alle tests delen stil één SQLite-bestand. 23 varianten van `db_session` met handmatige delete-volgorde, 21× `_make_user`, 41 tempfiles zonder opruiming, geen `conftest.py`.
- **Acties:** `tests/conftest.py` die de omgeving vóór de app-import zet, één engine, per test een transactie met rollback, `PRAGMA foreign_keys=ON`, fixtures `db_session`, `user`, `admin`, `account`, `client`, `auth_client`, scheduler-start gemonkeypatcht. Module-headers en helpers mechanisch vervangen; dubbele testnamen uniek; `*.db` in `.gitignore`. Mag in twee stappen.
- **Klaar wanneer:** Dezelfde tests slagen zonder module-level env-toewijzingen; een los testbestand draait identiek aan de volledige run; geen tempfiles achter.
- **Validatie:** Volledige suite, zelfde aantal tests als vóór de wijziging; `pytest -p no:randomly` niet nodig maar een willekeurige volgorde van twee bestanden slaagt.

<a id="act-40"></a>

### ACT-40 — Dependency-upgrade

- **Aanleiding:** Review F8. Directe pins uit december 2024/januari 2025 (FastAPI 0.115, Starlette 0.41, SQLAlchemy 2.0.36, requests 2.32.3, Jinja2 3.1.5, cryptography 43, pdfminer-six 2023) naast transitieve packages van september 2026. Starlette 0.41 mist de multipart-fix uit 0.47.2. Starlette ≥1.0 vereist ACT-38.
- **Acties:** Eén geplande `uv pip compile --upgrade`-ronde volgens DEVELOPMENT.md voor beide locks; let op bcrypt 5 (fout bij wachtwoorden >72 bytes) en apscheduler 3.11.
- **Klaar wanneer:** Beide locks bijgewerkt, suite groen op 3.12, upload/login/PDF-import handmatig gecontroleerd, deployment geslaagd.
- **Validatie:** Volledige suite, PostgreSQL-CI, smokecheck na uitrol.

<a id="act-41"></a>

### ACT-41 — Schema-hygiëne en migratie

- **Aanleiding:** Review D1–D4, D6, D8. Migraties maken indexes die het model niet kent (autogenerate wil ze droppen); `transactions.recurring_id`, `transfer_id`, `import_hash` en `accounts/categories/persons.user_id` missen een index; `uq_user_account_category` staat dubbele globale categorienamen toe (NULL ≠ NULL); `Transaction.children` zonder cascade maakt splits tot wezen; downgrades met `try/except: pass`; ongebruikte `HouseholdFinance`-kolommen.
- **Acties:** `index=True` in het model; één migratie (eerstvolgende vrije nummer; 067 en 068 zijn bezet door bunq) met ontbrekende indexes, partiële unique `WHERE account_id IS NULL`, `ondelete` en `passive_deletes` op kind-relaties, `server_default=func.now()` gelijktrekken, dode kolommen droppen. `compare_type`/`compare_server_default` in `alembic/env.py`. Test die `compare_metadata` leeg eist. CI-stap `upgrade head && downgrade base && upgrade head` op PostgreSQL. Migraties expliciet PostgreSQL-only verklaren.
- **Klaar wanneer:** Autogenerate geeft een lege diff; up/down/up slaagt in CI; verwijderen van een gesplitste transactie verwijdert de kinderen.
- **Validatie:** PostgreSQL-CI-job en regressietests; geen productiegegevens.

<a id="act-42"></a>

### ACT-42 — Transactiegrenzen, banksync-service en scheduler-lock

- **Aanleiding:** Review C5–C7, D7. Scheduler en banking-router hebben twee banksync-implementaties (scheduler zonder `ImportBatch`, zonder statusvelden, zonder IBAN-normalisatie, één fout rolt alles terug); services committen zelf en worden uit GET-routes aangeroepen; `scheduler.py` importeert uit routers; geen lock bij meerdere workers.
- **Acties:** `app/bank_sync.py` met `sync_bank_connection(db, conn) -> SyncResult`, gebruikt door router en scheduler, per koppeling `begin_nested()` en status op de connection. Conventie "service flusht, caller commit"; projectie-sync weg uit GET-routes naar import, koppelen, recurring-wijziging en scheduler. `inbox_count` en `_map_eb_transactions` uit de routers. `SCHEDULER_ENABLED`-env en PostgreSQL advisory lock in `logged_job`; `coalesce`, `max_instances`, `misfire_grace_time`. Vastleggen in OPERATIONS.md.
- **Klaar wanneer:** Scheduler-sync maakt batches en zet statusvelden zoals de handmatige sync; één mislukte koppeling laat de andere intact; GET-routes schrijven niet; twee processen draaien een job één keer.
- **Validatie:** Integratietest voor het scheduler-pad met nagebootste Enable Banking; regressietests voor banking, dashboard, budgets en transactions. Dit is de actie met het meeste gedragsrisico; productievalidatie van de nachtelijke sync vastleggen.

<a id="act-43"></a>

### ACT-43 — Gedeelde helpers en foutafhandelingsconventie

- **Aanleiding:** Review C3, C4, C13. Superadmin-check 4×, maandnamen 9×, jaar-selector-query 4×, bedrag-parsing in drie varianten, vier stijlen foutafhandeling en statuscodes door elkaar, `/settings/*` verdeeld over twee routers, vier identieke AI-aanroepblokken met hardcoded modelnamen.
- **Acties:** `is_super_admin`, `require_admin`, `require_feature` in `app/auth.py`; `app/nl_format.py` (maandnamen, `format_euro`) als Jinja-globals; `transaction_years()`; `_clean_email` naar `app/validation.py`. Conventie in WORKFLOW.md: niet-gevonden → 404 via `get_owned_or_404`, validatiefout → redirect met `?error=code`, AJAX → JSON, 303 na POST; per router toepassen. `/settings/*` uit `auth.py` naar `settings.py` met `_settings_ctx`. `app/ai_client.py` met één client, `call_json()`, `AIUnavailable`, modelnamen in config. Personen-CRUD uit `portfolio.py`.
- **Klaar wanneer:** Elke helper bestaat één keer; alle routers volgen de conventie; de instellingenpagina toont het startpagina-blok ook na een import.
- **Validatie:** Routetests voor de conventie (404/redirect/JSON) en bestaande suite.

<a id="act-44"></a>

### ACT-44 — Savings-service en N+1

- **Aanleiding:** Review C9, C12. Lopend-saldo-lus 4× in de router; `_compute_december_balance` doet 12×N queries bij elke celupdate; tweede "legacy" statusmodel; dode route `accept_ai_suggestion`; categorie-aanmaak gedupliceerd met `categories.py`; drie keer dezelfde formulierblokken voor twaalf maandbedragen.
- **Acties:** `savings_calc.running_balances()` en `schedule_from_form()`; `_determine_entry_status` en `_has_transactions_in_month` verwijderen; dode route weg; `category_service.get_or_create_subcategory()` gedeeld; `_apply_transaction_totals()` voor de vier "vul vanuit transacties"-blokken; `plan_detail` schrijft niet meer op GET.
- **Klaar wanneer:** Spaarbedragen en kleurstatus blijven gelijk; een celupdate doet een begrensd aantal queries; `savings.py` bevat geen rekenlussen meer.
- **Validatie:** Bestaande savings-tests plus een querytelling-test voor de celupdate.

<a id="act-45"></a>

### ACT-45 — Recurring en transactions: batching en custom-CSV-parser

- **Aanleiding:** Review C10, C12. `_render_recurring_page` doet ~90 queries bij 30 items en ontsleutelt per item alle transacties; `apply_all_categories` en `apply_category_to_linked` zijn identiek; na-import-sequentie 2×; custom-CSV-parsing (datumformaten, EU/US-bedragen) in de router met een privé-attribuut op `ParsedTransaction`; `transaction_list` 258 regels met dubbele categoriequery; `exclude_duplicates` en `find_candidates_for_projected` per rij.
- **Acties:** Transacties per unieke periode één keer laden en in memory matchen; `recurring_service.resync_after_import()`, `classify_items()`, batchvariant voor kandidaten, `apply_item_categories()`; `app/parsers/custom_csv.py` en `import_service.build_preview()`; `_resolve_period()` en `categories_by_account()`; `tag_id`-parameter weg; `float()` in amount-filter naar Decimal.
- **Klaar wanneer:** `transaction_list` en `_render_recurring_page` zijn elk korter dan 100 regels; querytelling op de recurring-pagina is onafhankelijk van het aantal items; importvoorbeeld en bevestiging geven dezelfde aantallen.
- **Validatie:** Bestaande import-, recurring- en transactietests plus querytelling-tests.

<a id="act-46"></a>

### ACT-46 — Mortgage-formulieren en lange functies opknippen

- **Aanleiding:** Review C8, C11. 19 identieke `Form(...)`-parameters in create en edit; rates-context 5× uitgeschreven; `rates_bulk_import` herhaalt `compare_with_existing`; `scenarios_detail` bouwt 35 template-sleutels; `budget_overview` 400 regels, `import_confirm` 224, `sync_transactions` 221, `portfolio_overview` 180, `analytics_stats` 198.
- **Acties:** `ScenarioForm` als FastAPI-dependency; `_render_rates()`; `mortgage_calc.scenario_view_model()`; `budget_overview` naar `_expense_budget_rows`/`_income_budget_rows`/`_expected_income`; `import_confirm` per onderdeel; `sync_transactions` naar `_resolve_account_for_sync` en `_post_import_hooks` (of ACT-42); `portfolio_overview` naar `_portfolio_totals`/`_portfolio_chart`; `analytics_stats` naar `_top_merchants`/`_new_counterparties`. `date.today()` uit `mortgage_calc` als parameter.
- **Klaar wanneer:** Geen routefunctie langer dan 100 regels; templatecontext voor een representatief scenario en budgetoverzicht identiek (golden master).
- **Validatie:** Golden-master-tests op de context vóór en na; bestaande mortgage- en budgettests.

<a id="act-47"></a>

### ACT-47 — CSS-tokens en dode CSS

- **Aanleiding:** Review E1, E2, E6, E7. `--gold`, `--navy`, `--navy-mid`, `--muted-border`, `--card-bg` worden gebruikt maar zijn nergens gedefinieerd; `alert-danger`, `alert-info`, `btn-secondary` en andere klassen bestaan niet; twee tokenfamilies; 48 inline hex-kleuren die dark mode negeren; 42 dode selectors en 9 `!important` daarin; 8 breakpoints; landing/terms/privacy met gekopieerde nav-CSS.
- **Acties:** Ontbrekende tokens en klassen definiëren; één tokenfamilie kiezen en de andere tijdelijk aliassen; hex naar tokens; dode selectors en ongebruikte variabelen weg; `base_public.html` voor landing/terms/privacy; Google Fonts via `<link rel="preconnect">`; drie vaste breakpoints.
- **Klaar wanneer:** Geen `var(--x)` zonder definitie; geen klasse in templates zonder CSS-regel; light en dark mode zonder hardcoded kleuren in templates; terms en privacy zonder eigen `<style>`.
- **Validatie:** Grep-controle op tokens en klassen; schermcontrole desktop/mobiel in beide thema's.

<a id="act-48"></a>

### ACT-48 — Gedeeld JavaScript en gepinde Chart.js

- **Aanleiding:** Review E3. 29 inline scriptblokken (~2.100 regels), zes implementaties van bedragformattering, `toggleEdit` 3×, modal-sluiten 2×, tien `fetch()`-aanroepen met eigen foutafhandeling, Chart.js 4× met drie versies en zonder `integrity`, thema/drawer-script inline in `base.html`.
- **Acties:** `app/static/js/app.js` (thema, drawer, `formatEuro`, `escapeHtml`, `fetchJson` met uniforme foutmelding, modal, `toggleEdit`) geladen met `asset_version`; paginascripts alleen nog pagina-specifiek en in `{% block scripts %}`; Chart.js één gepinde URL met SRI in `{% block vendor %}`.
- **Klaar wanneer:** Geen gedupliceerde JS-functie over templates; één Chart.js-versie; `formatEuro` geeft dezelfde uitvoer als de Jinja-filter `euro`.
- **Validatie:** Bestaande `response.text`-asserts; handmatige check van celbewerking (spaarplanner, vermogensprognose), grafieken en modals.

<a id="act-49"></a>

### ACT-49 — Jinja-macro's en filters

- **Aanleiding:** Review E4, E8. Lege staat 18× uitgeschreven, flash-kaart met hex 23×, inline delete-form met `confirm()` 53×, sectiekop 11×, jaar/maand-select 14×, `"%.2f"|format|replace` 31× naast `|euro`; datums met 9 `strftime`-varianten; `&euro;` naast `€`; 0× `scope` op 295 `<th>`, ~19 inputs zonder label, modals zonder `role="dialog"`.
- **Acties:** `templates/_macros.html` met `empty_state`, `flash`, `inline_action_form`, `section_title`, `year_month_select`, `page_header`, `tx_table_head`; filters `date`, `datetime`, `euro_sign` in `template_config.py`; `_fmt_amount` in `savings.py` verwijderen; de herhaalde fragmenten vervangen; labels, `scope`, `<button>` i.p.v. `<a href="#">` en `role="dialog"` in de macro's.
- **Klaar wanneer:** Elk genoemd patroon bestaat op één plek; bedragen en datums overal via filters; kernformulieren met toetsenbord bedienbaar.
- **Validatie:** Bestaande routetests; handmatige toetsenbord- en schermcontrole op de aangepaste pagina's.

<a id="act-50"></a>

### ACT-50 — Inline styles naar utility-classes

- **Aanleiding:** Review E5. 1.149 inline `style=""`; top-20 declaraties dekken 60–70%; zwaarste templates mortgage/scenario_detail (99), rules/list (93), recurring/list (83), savings/detail (81), portfolio/index (80).
- **Acties:** ~15 utility-classes in `style.css`; per map omzetten (mortgage, rules, recurring, savings, portfolio, budgets, transactions), eventueel als sub-PR's ACT-50a t/m ACT-50g; de 27 dynamische styles als CSS custom properties laten staan; inline hex-kleuren naar tokens.
- **Klaar wanneer:** Per map minder dan tien resterende inline styles, allemaal dynamisch; geen visuele regressie in beide thema's.
- **Validatie:** Schermcontrole per map desktop/mobiel; bestaande routetests.

<a id="act-51"></a>

### ACT-51 — HTTP-vangnet voor redesign-schermen en parsers

- **Aanleiding:** Review F2. `rules_engine.py`, `ai_suggest.py`, `email_service.py`, `rate_limit.py`, `parsers/ing.py`, `parsers/rabobank.py`, `parsers/ics_pdf.py` hebben geen test; routers transactions (2 hits), analytics (0), rules (0), dashboard (1), budgets (2), categories (2) nauwelijks. Precies de schermen die een redesign raakt.
- **Acties:** Happy-path HTTP-tests (200, kernelementen in de HTML, eigenaarscheiding) voor `/transactions`, `/analytics`, `/rules`, `/budgets`, `/categories`, `/dashboard`; unit-tests voor `rules_engine`, `rate_limit`, parsers ING/Rabobank/ICS-PDF met synthetische bestanden.
- **Klaar wanneer:** Elke router heeft minstens één rendertest per hoofdpagina; de genoemde modules hebben unit-tests; coverage-rapport toont geen router onder de drempel die het team kiest.
- **Validatie:** Coverage-uitvoer in de overdracht; geen productiegegevens in fixtures.

<a id="act-52"></a>

### ACT-52 — Model-typing: Boolean, enums, Mapped

- **Aanleiding:** Review D5, D9, D10. 22 boolean-kolommen als `Integer` met `== 1` tot in de templates; vrije strings als enums (`bank`, `frequency`, `status`, `mortgage_type`); `accounts_json` als Text-blob; kommastrings voor maanden; volledig legacy SQLAlchemy-stijl; losse `os.getenv`-regels in `config.py`.
- **Acties:** Migratie naar `Boolean` met `NOT NULL DEFAULT false`; `StrEnum` met `CheckConstraint` (`native_enum=False`); `JSON`-kolom voor `accounts_json`; `active_months_set`/`skipped_months_set` als properties; `Mapped[]`/`mapped_column()` en `back_populates` i.p.v. `backref`; `pydantic-settings` voor configuratie. Mechanisch, zonder gedragswijziging; mag in subacties.
- **Klaar wanneer:** Templates vergelijken booleans niet meer met `1`; nieuwe code heeft typed modellen; autogenerate blijft leeg na de migratie.
- **Validatie:** Volledige suite, PostgreSQL-CI met up/down/up, productievalidatie na uitrol.

<a id="act-60"></a>

### ACT-60 — Categoriseren per tegenpartij, met regel in één klik

- **Aanleiding (gebruiker, 2026-10-28):** nog 642 ongecategoriseerde transacties. Van de voorgestelde versnellingen koos de gebruiker groeperen per tegenpartij (2) en na de keuze een regel aanbieden (3). Automatisch toepassen bij zekere historie (1) wil de gebruiker niet.
- **Gedrag:** `/transactions/groups` (knop "Per tegenpartij" op de transactiepagina, met maand en rekening als filter) toont de open transacties gegroepeerd op dezelfde genormaliseerde naam als ACT-58, grootste groep eerst. De suggestie uit historie of AI-cache staat voorgeselecteerd. "Toewijzen" zet de categorie op de hele groep; de server bepaalt de groep opnieuw. Transacties zonder herkenbare naam blijven op de transactiepagina.
- **Regel:** het vinkje "Maak er een regel van" (standaard aan vanaf 2 transacties) maakt een *bevat*-regel op tegenpartij of omschrijving. Die wordt alleen aangeboden als de tekst letterlijk in elke transactie van de groep staat en minstens 4 tekens lang is. De regel wordt meteen toegepast op andere open transacties, nooit op al gecategoriseerde.
- **Validatie:** `tests/test_category_suggest.py` (groeperen, regeltekst, toepassen inclusief regel, eigenaarschap, onbekende categorie). Productie: kwaliteit van de groepen op echte data door de gebruiker.

<a id="act-59"></a>

### ACT-59 — Vaste spaarstortingen automatisch categoriseren

- **Aanleiding (gebruiker, 2026-10-27):** gekoppelde overboekingen naar een spaarrekening kregen geen categorie. De gebruiker wil dat vaste stortingen dat wel krijgen, op alle boekingen (ook uit het verleden). Terugboekingen en incidentele grotere bedragen moeten ongemoeid blijven.
- **Analyse productie (2026-10-27, alleen lezen):** de meeste spaarhistorie heeft al een categorie uit de standaardset. Vaste bedragen veranderen in de tijd (250 → 350 → 400; 1.100 → 1.225), dus een vaste lijst bedragen werkt niet. Open zonder categorie onder meer 11× € 400 op Abn samen spaar en 3× € 500 op GJ Spaar (onregelmatig). Opvallend, buiten scope: 15× € 200 "SEPA Periodieke overb." op Abn samen spaar en 32× € 12 op Samen Spaar Bunq staan als *Rente*, en 22× € 280 van bunq als *Vakantiegeld en 13e maand*. Rekeninginstellingen: GJ – Spaar had geen eigenaar, Suze Kinderspaar stond als betaalrekening, er waren geen groepen; de gebruiker past dat zelf aan.
- **Gedrag:** een gekoppelde storting van betaal naar spaar krijgt aan beide kanten een categorie als hetzelfde bedrag tussen dezelfde twee rekeningen minstens 3 keer achter elkaar met 20–40 dagen ertussen voorkomt (over de hele historie): *Sparen › Storting Gerd-Jan/Nelleke* (afzender van één persoon), *Sparen › Storting samen* (gezamenlijke afzender, ook "Nelleke & Gerd-Jan" als één persoon) of *Kinderen › <naam>* (spaarrekening van een ander). Terugboekingen, spaar-naar-spaar, incidentele en niet-maandelijkse bedragen worden alleen gekoppeld. Een bestaande categorie wordt nooit overschreven.
- **Ook al gekoppelde paren:** `link_and_classify` vult nu lege kanten van al gekoppelde paren aan (alle soorten). Daardoor krijgen ook door de bunq-sync gekoppelde paren alsnog een categorie. De herstelpagina `/accounts/transfers` toont ze met "al gekoppeld" en past ze met één klik toe op de hele historie.
- **Niet gedaan:** Nellekes eenzijdige boekingen (haar rekeningen staan niet in de app) en kwartaal- of jaarstortingen; daarvoor zijn regels per rekening (`condition_account_id`) of de suggesties uit ACT-58 bedoeld.
- **Validatie:** `tests/test_transfer_service.py` (maandelijkse storting, samen, kind, terugboeking, incidenteel, halfjaarlijks, aanvullen gekoppelde paren, ritmecontrole). Productie: herstelpagina openen en de preview nalopen vóór toepassen.

<a id="act-58"></a>

### ACT-58 — Categoriesuggesties bij transacties met weinig AI-calls

- **Aanleiding (gebruiker, 2026-10-27):** categoriseren kost veel tijd; per transactie moet een voorbeeldcategorie zichtbaar zijn, met zo min mogelijk AI-calls. De gebruiker koos voor historie én AI-fallback in batch met cache.
- **Gedrag:** op de transactiepagina staat onder de keuzelijst een groene chip "✓ Categorie · n× eerder" (historie) of een blauwe "AI-suggestie"; één klik wijst toe. De knop "Neem n suggesties over" doet dat voor de hele pagina; de server berekent de suggesties dan opnieuw.
- **Historie (geen AI):** sleutels IBAN → tegenpartij → merchant uit de omschrijving (`parse_description`), genormaliseerd (hoofdletters, rechtsvormen, winkelnummers). Een sleutel telt pas bij ≥ 60 % voor één categorie, anders de volgende sleutel (betaaldienst-IBAN's). Alleen kiesbare subcategorieën: niet gearchiveerd, gedeeld of van dezelfde rekening. Splitsdelen en projecties tellen niet mee. Telling in Python vanwege versleutelde velden.
- **AI-fallback:** unieke tegenpartijen zonder historie gaan in één call (max. 40) naar Claude; het antwoord staat per tegenpartij in `merchant_category_suggestions` (migratie 072), met een HMAC van de naam (geen leesbare tegenpartij) en ook "weet niet" (NULL), zodat niets twee keer gevraagd wordt. Draait na een CSV-import (achtergrondtaak), na de geplande bank- en bunq-sync en via de knop "AI-suggesties voor n nieuwe tegenpartijen"; nooit bij het laden van een pagina. Een verwijderde categorie wist de cacheregel; samenvoegen vouwt hem mee.
- **Klaar wanneer:** ongecategoriseerde transacties met bekende tegenpartij tonen een suggestie zonder AI-call, de rest kost hooguit één call per nieuwe tegenpartij, en suggesties zijn per stuk of per pagina over te nemen.
- **Validatie:** `tests/test_category_suggest.py` (normalisatie, sleutelvolgorde, ambigue IBAN, archief, eigenaarschap, cache en één call, API-fout, pagina en bulkovername). Niet getest: de echte Anthropic-API, de PostgreSQL-migratie (CI) en de suggestiekwaliteit op productiedata. Bij een nieuwe `SECRET_KEY` vervalt de cache (er wordt dan opnieuw gevraagd).

<a id="act-55"></a>

### ACT-55 — Rekeninggroepen, één categorieënset en budget per groep

- **Aanleiding (gebruiker, 2026-10-15):** "GJ" (betaalrekening) en "On the go" (bunq) zijn functioneel één betaalrekening van één persoon; categorieën staan nu per rekening, waardoor dezelfde categorie dubbel bestaat en budgetten niet over beide rekeningen heen werken.
- **Besluiten gebruiker:** rekeningen die bij elkaar horen vormen een groep; het budget geldt per groep; alle rekeningen gebruiken één categorieënset; gelijke namen op hetzelfde niveau worden automatisch samengevoegd, bijna-gelijke namen kiest de gebruiker in de preview; lege categorieën worden gearchiveerd (blijven beschikbaar in oude overzichten).
- **Stappen (elk een PR):** (a) `AccountGroup` + `Account.group_id` met migratie (elke rekening start in een eigen groep) en groepsbeheer op de rekeningenpagina; (b) `Budget.group_id` en budgetpagina per groep; (c) categorieën consolideren met preview, samenvoegen en archiveren; (d) budget- en spaarpagina's op de gedeelde set.
- **Klaar wanneer:** GJ en On the go als groep één budget en één categorieënset delen, zonder dat transacties, regels, terugkerende posten of spaarregels verloren gaan; de preview toont vooraf elke wijziging.
- **Validatie:** tests op samenvoegen en groepsbudget, PostgreSQL-migratietest, productiecontrole door de gebruiker na elke stap.

### ACT-54 — Regelvoorstellen leesbaar: volledige omschrijving en groepering

- **Aanleiding (gebruiker, 2026-10-14):** in de tabel met regelvoorstellen (`/rules`) zijn "Herkenning" en "Tegenpartij" smalle invoervelden van één regel; lange bankomschrijvingen vallen weg en voorstellen die met dezelfde tekst beginnen zijn niet te onderscheiden.
- **Voorstel:** elk voorstel als kaartje met twee regels (Herkenning als meegroeiend tekstvak over de volle breedte; daaronder Tegenpartij, Rekening, Categorie); een grijs voorbeeld met de volledige omschrijving van één echte transactie; klikbare aantallen met een lijst die de hele omschrijving en datum toont; voorstellen met dezelfde zoekterm groeperen.
- **Klaar wanneer:** de volledige omschrijving is zichtbaar zonder af te kappen en de zes bijna-identieke "SEPA Periodieke overboeking"-rijen zijn te onderscheiden.


### Fase 1 (ACT-32 t/m ACT-35) — uitkomst, 2026-10-14, Claude Code

Alle vijf PR's gemerged en gedeployed (Build and Deploy geslaagd): ACT-32 [#215](https://github.com/gjagils/checkthepockets/pull/215), ACT-33 [#216](https://github.com/gjagils/checkthepockets/pull/216), ACT-34a [#217](https://github.com/gjagils/checkthepockets/pull/217), ACT-34b [#218](https://github.com/gjagils/checkthepockets/pull/218), ACT-35 [#219](https://github.com/gjagils/checkthepockets/pull/219). A12 was al opgelost in #211. ACT-34 is gesplitst in 34a (A4, A6–A11, A14) en 34b (A13, A15, B9). Gevonden bovenop de review: de instellingen-import was niet atomair (nu wel), en inline `confirm('…{{ naam }}…')` in elf templates was een stored-XSS-route (gebruikersnaam op `admin/users.html`); beide opgelost. Productievalidatie open: uitloggen via POST-knop, IP-gedrag van de inlogbegrenzing achter Cloudflare/nginx, de duplicatenpagina met echte versleutelde data, en de AI-modelnaam (`ANTHROPIC_MODEL`, standaard `claude-sonnet-5-5`, niet tegen de echte API getest).

### Fase 2 (ACT-36 t/m ACT-40) — uitkomst, 2026-10-14, Claude Code

Gemerged en gedeployed: ACT-36 [#221](https://github.com/gjagils/checkthepockets/pull/221), ACT-37 [#222](https://github.com/gjagils/checkthepockets/pull/222), ACT-38a [#223](https://github.com/gjagils/checkthepockets/pull/223), ACT-38b [#224](https://github.com/gjagils/checkthepockets/pull/224), ACT-40 [#225](https://github.com/gjagils/checkthepockets/pull/225), ACT-39 [#226](https://github.com/gjagils/checkthepockets/pull/226). Bijzonderheden: `app/clock.py` (`today_nl()` verandert gedrag tussen 00:00 en 02:00 NL-tijd); dependency-upgrade gevalideerd op een echte Python 3.12 uit het lock, met oude→nieuwe leesbaarheid van Fernet/bcrypt/sessiecookies; `apscheduler` 3.11 had `pytz` niet meer (nu `zoneinfo`); SQLAlchemy 2.1 en bcrypt 5 bewust niet meegenomen (eigen actie nodig); de testbasis dwingt nu foreign keys af en isoleert per test. Productievalidatie: pagina's laden (bevestigd door gebruiker); scheduler-pagina `/admin/scheduler` nog te bevestigen; bunq-voorbeeld en CSV-import door gebruiker later.

### Fase 3 (ACT-41 t/m ACT-46) en fase 4 (gedeeltelijk) — uitkomst, 2026-10-15, Claude Code

- **ACT-41** (migratie 069, modeluitlijning, drift-test op PostgreSQL), **ACT-42** (banksync-service, scheduler-lock, transactiegrenzen), **ACT-43** (gedeelde helpers; routeconventie alleen toegepast op de accounts-routes), **ACT-44** (savings-service; `_determine_entry_status` en GET-schrijfacties in plan_detail bewust ongemoeid), **ACT-45** (batching terugkerende posten, custom-CSV-parser; opsplitsen van `transaction_list` en `_render_recurring_page` niet gedaan), **ACT-46** (mortgage-formulieren; lange functies niet verder opgeknipt): afgerond met de genoemde beperkingen.
- **ACT-51** HTTP-vangnet: rooktest op alle parameterloze GET-routes, schrijf-flows en bank-CSV-parsers (PR 240). `/admin/imports` is uitgesloten omdat `date_trunc` PostgreSQL-only is.
- **ACT-47** CSS: ontbrekende tokens/klassen, 54 dode selectors weg, drie breakpoints, hex in hypotheek-/recurring-templates naar tokens, `base_public.html`. Visuele controle door de gebruiker open; de ~48 hex-kleuren in categoriekleuren-fallbacks (`#1F6FB2`) blijven bewust.
- **ACT-48** JavaScript: `app/static/js/app.js` (thema, drawer, `formatEuro`, `escapeHtml`, `toggleEdit`, `fetchJson`), Chart.js 4.4.1 met SRI. De 15 bestaande `fetch()`-aanroepen en de overige inline scriptblokken zijn nog niet omgezet naar `fetchJson`/aparte bestanden.
- **ACT-54** regelvoorstellen als kaartjes (PR 243).
- **Nog niet gedaan:** ACT-49, ACT-50, ACT-52, ACT-53 en de gedeelde categorieën met budget per rekening.

### Persoonspagina en rekeninggroepen (ACT-49, ACT-50, ACT-53, ACT-55) — uitkomst, 2026-10-15, Claude Code

- **ACT-49** (deel): filters `date`, `datetime`, `euro_sign`, `euro0_sign` (#245); macro's en a11y-werk nog niet gedaan. **ACT-50** (deel): 21 utility-klassen, ~350 inline styles vervangen (#246); samengestelde en variabele stijlen blijven.
- **ACT-53**: rekenkern (#247), pagina `/persons/{id}` met periodes 3/6/12 mnd en 2/3/5 jaar, grafiek, maandtabel en blok "Naar 18 jaar" (#248), menu-item Verwachting onder Portfolio (#251). Keuzes: gedeelde rekeningen gelijk verdeeld; spaaropdrachten als aparte regel "Naar sparen" in de verwachting; variabele uitgaven en budgetten zitten er nog niet in.
- **ACT-55**: rekeninggroepen (#250, migratie 070), budget per groep (#252, migratie 071), categorieën consolideren met preview, samenvoegen en archiveren (#253), pagina's op de gedeelde set (#254). Gebruiker moet de preview in productie doorlopen; er is geen automatische undo.
- **Bewust niet gedaan:** ACT-52 (Boolean-migratie raakt alle `== 0/1`-vergelijkingen in queries; apart en samen met de gebruiker). De oude route `POST /categories/merge` volgt nog niet de fold-logica.

### Model-typing (ACT-52, deel) — uitkomst, 2026-10-15, Claude Code

- **Gedaan:** type `Flag` (`app/db_types.py`): integer in de database, `bool` in Python, zonder migratie en zonder driftverschil. Toegepast op alle 16 vlagkolommen: `User` (#256), `Transaction` (#257), `Category` (#258) en de overige (#259). Queries met `== 0/1` en toewijzingen met `= 0/1` blijven werken; de back-up-export schrijft de vlaggen met `int()` zodat het bestandsformaat 0/1 blijft.
- **Bewust niet gedaan:** de echte PostgreSQL-`Boolean`-migratie (raakt elke `== 0/1` in SQL-filters en brengt productierisico zonder functionele winst); `StrEnum` met `CheckConstraint`, `JSON`-kolom voor `accounts_json`, `Mapped[]`/`mapped_column()` en `pydantic-settings`.
- **Besluit gebruiker (2026-10-15):** aanpak in stappen, eerst alleen het Python-type; de overige onderdelen alleen oppakken als er een concrete aanleiding is.

## Besluitenlog

| Datum | Besluit | Reden / gevolgen |
|---|---|---|
| 2026-09-23 | Git en Markdown zijn de centrale bron; Codex en Claude Code volgen dezelfde workflow | Wisselen zonder afhankelijkheid van Linear, MCP of agentspecifiek geheugen |
| 2026-09-23 | Beide agentingangen verwijzen naar één workflow | Voorkomt twee uiteenlopende versies van afspraken |
| 2026-09-23 | Alle verbeteracties vrijgegeven; budgetcontrole vóór iedere start verplicht | Alleen een actie starten die inclusief tests, CI en afronding naar redelijke inschatting past; anders wachten |
| 2026-09-23 | Oude Linear-items blijven extern totdat relevant werk bewust is overgenomen | Geen claim dat de volledige bestaande backlog al is gemigreerd |
| 2026-09-23 | Vermogensprognose per persoon, kleuren t.o.v. plan 1/1 (ACT-28) | Vervangt de handmatige kopie in de spreadsheet; bouwt voort op Portfolio en spaarplanner |
| 2026-09-23 | Gebruiker vraagt alle openstaande acties af te werken; ACT-22 en ACT-23 naar Gereed | Uitvoering blijft één actie tegelijk met budgetcontrole; ACT-08-rotatie, ACT-15-restoreproef en ACT-25-accountonderzoek vragen toegang of handelingen van de gebruiker |
| 2026-10-14 | Review-acties vrijgegeven: fase 1 (ACT-32 t/m 35) met doorlopende mergetoestemming zodra CI groen is; fase 2 (ACT-36 t/m 40) vrijgegeven | Fase 3 en 4 (structuur, front-end) per PR of per fase opnieuw vragen. Statusregistratie na merge gebundeld in een docs-PR per fase |

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
| 2026-09-23 | ACT-08 | Gelekte SECRET_KEY en POSTGRES_PASSWORD niet meer in gebruik (vingerafdrukken verschillen; productie op Neon) | Controle door gebruiker in Portainer; geen rotatie nodig |
| 2026-09-23 | ACT-25a | Rekeningen zonder uid zichtbaar na koppelen; logregel per koppeling | [PR #191](https://github.com/gjagils/checkthepockets/pull/191), beide checks groen; merge `8a58ab7`; deployment geslaagd |
| 2026-09-23 | ACT-27a | Compacte spaarplanner met regel Beweging | [PR #194](https://github.com/gjagils/checkthepockets/pull/194), beide checks groen; merge `34066d5`; deployment geslaagd |
| 2026-09-23 | ACT-27 | Compacte spaarplanner; toekomstige maanden direct bewerkbaar | [PR #194](https://github.com/gjagils/checkthepockets/pull/194) en [PR #197](https://github.com/gjagils/checkthepockets/pull/197), beide checks groen; merge `ccc26a2`; browsercontrole celbewerking open |
| 2026-09-23 | ACT-28a | Jaarrekenkern per persoon met koersmomentopnames, groei, inleg, verkoopfactor en gedeelde spaarrekeningen | [PR #199](https://github.com/gjagils/checkthepockets/pull/199), beide checks groen; merge `85caa2c` |
| 2026-09-23 | ACT-28 | Vermogensprognose, bevroren plan per 1/1, verschilweergave en losse maandboekingen per persoon/bezit | [PR #199](https://github.com/gjagils/checkthepockets/pull/199), [#201](https://github.com/gjagils/checkthepockets/pull/201), [#202](https://github.com/gjagils/checkthepockets/pull/202), [#203](https://github.com/gjagils/checkthepockets/pull/203); alle checks groen; merge `fde6ebb`; deployments geslaagd; schermcontrole open |
| 2026-09-23 | Review ACT-28 | Documentatie aangevuld (aannames, validatie op 3.12, open schermcontrole); ACT-29 toegevoegd; ACT-25b op Geblokkeerd | Claude Code; 496 passed, 2 skipped in Python 3.12 |
| 2026-10-14 | ACT-30 | Rekeningen samenvoegen met preview | Claude Code; 502 passed, 3 skipped (Python 3.14); PR-CI open |
| 2026-10-14 | ACT-30 fix | Samenvoegen gaf 500 (UniqueViolation op `uq_transaction_account_import_hash`): exacte hash-matches krijgen nu voorrang, ook bij verschoven zichtbare datum; fout toont melding en rollback | Claude Code; 505 passed, 3 skipped (Python 3.14); PR-CI open; productielog bevestigde de oorzaak |
| 2026-10-14 | ACT-31a | bunq-koppeling: sleutel invoeren en rekeningen tonen (alleen lezen) | Claude Code; 509 passed, 3 skipped (Python 3.14, nagebootste bunq); PR-CI open |
| 2026-10-14 | ACT-31b | bunq: rekeningen kiezen, betalingen importeren met dubbelcheck tegen CSV, overboekingen koppelen, geplande sync; knoppenrij op rekeningkaart breekt af | Claude Code; 519 passed, 3 skipped (Python 3.14, nagebootste bunq); PR-CI open |
| 2026-10-14 | ACT-30 fix (review A12) | Samenvoegen crasht niet meer op gelijknamige categorieën (`uq_user_account_category`): conflicterende bron-categorieën worden in die van de doelrekening gevouwen (transacties, budgetten, regels, spaarregels, suggesties, kinderen), de preview toont ze | Claude Code; 521 passed, 3 skipped (Python 3.14); PR-CI open |
| 2026-10-14 | ACT-31b fix | bunq-selectie gaf 500 (UniqueViolation `uq_user_account`) als de gekozen rekening geen IBAN had en het IBAN al op een andere eigen rekening stond: IBAN wordt dan niet overgenomen, melding om eerst samen te voegen, rollback bij fouten | Claude Code; 521 passed, 3 skipped (Python 3.14); productielog bevestigde de oorzaak; PR-CI open |
| 2026-10-14 | ACT-31b fix | bunq-sync gaf 500 (`integer out of range`): bunq-id's (bv. 2932017837) passen niet in 32 bits; `bunq_account_links.bunq_account_id` en `last_payment_id` zijn nu BIGINT (migratie 068). Productielog bevestigde de oorzaak; samenvoegen van de twee spaarrekeningen werkte (271 dubbel samengevoegd) | Claude Code; PR-CI (PostgreSQL) open |
| 2026-10-14 | AI-model | AI-regelsuggesties gaven 404 (`claude-sonnet-4-20250514` bestaat niet meer): model nu via `ANTHROPIC_MODEL` (standaard `claude-sonnet-5-5`), 4 plekken in ai_suggest.py; review C13 deels | Claude Code; 525 passed, 3 skipped (Python 3.14, nagebootste client); niet getest tegen de echte API |
| 2026-10-14 | Codereview | Volledige scan vóór het UI-redesign; ACT-32 t/m ACT-52 als Gepland toegevoegd | Claude Code; docs/CODE-REVIEW-2026-10-14.md; 512 passed, 3 skipped (Python 3.12 via uv); branch `claude/check-pockets-suite-review-fd0da6` |
| 2026-10-14 | ACT-32 | Encryptie-bugs uit de review (A1, A2, A3, B11) opgelost met tests die met versleuteling draaien | Claude Code; 529 passed, 3 skipped; PR-CI open |
| 2026-10-14 | ACT-32 t/m ACT-35 | Fase 1 van de codereview afgerond: encryptie-bugs, auth-hardening, crash- en datafouten (a en b), XSS | #215, #216, #217, #218, #219 gemerged; CI groen; productievalidatie deels open (zie fase 1 — uitkomst) |
| 2026-10-14 | ACT-36 t/m ACT-40 | Fase 2 van de codereview afgerond (hygiëne, tooling, verouderde API's, testbasis, dependency-upgrade) | #221–#226 gemerged; CI groen; 586 passed, 3 skipped op Python 3.12 |
| 2026-10-27 | ACT-58 | Categoriesuggesties uit historie plus AI-batch met cache op de transactiepagina; status Review | Claude Code; 708 passed, 10 skipped (lokaal Python 3.14, niet de 3.12-locks); branch `claude/transaction-categorization-examples-f9fe8b`; PR-CI open |
| 2026-10-27 | ACT-58 | Gemerged ([PR #270](https://github.com/gjagils/checkthepockets/pull/270), `391d4a1`), CI groen, deploy geslaagd; productiecontrole van suggesties en AI-knop door gebruiker open | Claude Code |
| 2026-10-27 | ACT-59 | Vaste spaarstortingen categoriseren en gekoppelde paren aanvullen; status Review | Claude Code; 713 passed, 10 skipped (lokaal Python 3.14); branch `claude/act-59-spaaroverboekingen`; PR-CI open |
| 2026-10-27 | ACT-59 | Gemerged ([PR #271](https://github.com/gjagils/checkthepockets/pull/271), `e86a5ef`), CI groen, deploy geslaagd; gebruiker heeft rekeninginstellingen aangepast en de herstelpagina toegepast. Ook in productie: regel #82 naar Storting samen (alleen Abn samen spaar, tegenpartij "Samen Betaal"), drie dubbele € 200-boekingen (feb–apr 2026) uitgesloten. Volgende sessie: nog 642 ongecategoriseerde transacties | Claude Code; bevestiging gebruiker |
| 2026-10-28 | ACT-60 | Categoriseren per tegenpartij met optionele regel; status Review | Claude Code; 716 passed, 10 skipped (lokaal Python 3.14); branch `claude/act-60-groepen`; PR-CI open |
| 2026-10-28 | ACT-60 | Gemerged ([PR #273](https://github.com/gjagils/checkthepockets/pull/273), `bb31a34`), CI groen, deploy geslaagd; productiecontrole van de groepenpagina door gebruiker open | Claude Code |
