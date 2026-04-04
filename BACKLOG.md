# CheckThePockets — Product Backlog

Gebaseerd op vergelijking met Lunch Money (april 2026). Import beperkt tot CSV.
Sprints zijn gegroepeerd op gedeelde bestanden voor maximale efficiëntie per sessie.

> **Nieuwe sessie starten?** Zeg: *"Start Sprint X"* en Claude pakt de taken direct op.
> Elke sprint is zelfstandig uitvoerbaar zonder context uit vorige sessies.

---

## Sprint Design 3 — Font & grootte pariteit tussen themes ✅ (2026-04-04)

- [x] Plus Jakarta Sans voor beide thema's — font-vars alleen in `:root`, niet overschreven in `[data-theme="light"]`
- [x] Logo layout: icon links, CHECK/THE/POCKETS rechts gestapeld (`flex-direction: row`)

---

## Sprint Design 2 — Layout redesign + dark/light thema-switcher ✅ (2026-04-04)

- [x] Logo: icon links + CHECK/THE/POCKETS gestapeld rechts, kleuren via CSS-variabelen
- [x] Gebruikersavatar: ronde initialen-cirkel rechts in nav (`nav-avatar`)
- [x] Nav active-indicators: border + subnav pill-stijl
- [x] Paginatitels: `var(--secondary)` kleur, font-weight 800
- [x] Tabelstructuur: border-bottom per rij, uppercase kolomkoppen
- [x] Filterbar: slim `.tx-toolbar` met period-nav + "Niet gecategoriseerd" quickfilter + "Meer filters" details
- [x] CSS thema-variabelen: dark = `:root`, light = `[data-theme="light"]` override
- [x] Font: Plus Jakarta Sans voor beide thema's (zie Sprint Design 3)
- [x] Toggle-knop: zon/maan knop in nav
- [x] Toggle JS + anti-flash in `<head>`, voorkeur in `localStorage`

---

## Sprint 1 — Database fundament ✅ (2026-04-03)
*Model-wijzigingen waar latere sprints op bouwen.*

- [x] `is_reviewed` veld op Transaction model + migratie (018)
- [x] `exclude_from_budget` veld op Category model + migratie (018)
- [x] `exclude_from_totals` veld op Category model + migratie (018)
- [x] UI: reviewed-vinkje per transactie (toggle inline op transactiepagina)
- [x] UI: exclude-flags instellen in categorie-beheer
- [x] Budgetpagina: `exclude_from_budget` categorieën niet tonen
- [x] Dashboard/analytics: `exclude_from_totals` categorieën uitsluiten van totalen

---

## Sprint Design — Editorial Finance redesign ✅ (2026-04-03)
*Volledige CSS-herschrijving van dark Catppuccin naar light navy/gold design system.*

- [x] Fonts: `Syne` (headings/nav/bedragen) + `DM Sans` (body) via Google Fonts
- [x] Kleurpalet: Primary Navy `#002752`, Gold `#F9A800`, licht grijs-blauw achtergrond
- [x] Navigatie: donker navy topbar, gold active-indicator, sub-nav in `#01356a`
- [x] Cards: wit met subtiele schaduw, geen harde borders
- [x] Tabellen: licht thema, navy kolomhoofd, subtiele hover
- [x] Knoppen: gold = primaire CTA, navy = accent, ghost = outline
- [x] Bedragen: Syne tabular-nums, groen/rood semantisch
- [x] Modals: navy backdrop blur, nette header/footer
- [x] Alle legacy `--ctp-` variabelen intact gehouden

---

## Sprint 2 — Transactie UX ✅ (2026-04-04)
*Bulk-acties, export en deduplicatie op de transactiepagina.*

- [x] **Bulk selectie + acties**: checkbox per rij + sticky bulk-balk onderaan — categorie, tag, reviewed, uitsluiten — POST `/transactions/bulk`
- [x] **CSV export**: knop in page-header — GET `/transactions/export` met zelfde filterparams — alle velden incl. tags en reviewed
- [x] **Deduplicatie tool**: `/transactions/duplicates` — groepeert op datum+bedrag+tegenpartij, eerste in groep bewaard, rest selecteerbaar voor uitsluiten
- [x] **Kolommen tonen/verbergen**: toggle-knoppen boven tabel voor Tegenpartij en Rekening, staat opgeslagen in `localStorage`
- [x] **Filterlogica gerefactored**: `_build_tx_query()` helper gedeeld tussen list, export en duplicates

---

## Sprint 3 — Budget verbeteringen ✅ (2026-04-04)
*Betere planning en inzicht op de budgetpagina. Bouwt op Sprint 1 (exclude_from_budget).*

- [x] **"Left to budget" balk**: progress bar bovenaan met groen/goud/rood kleur-coding
- [x] **Overbudgeted indicator**: alert banner als `total_budgeted > total_income`
- [x] **Budget kopiëren van vorige maand**: quick-copy knop in page header
- [x] **Budget presets**: `BudgetPreset` + `BudgetPresetLine` models, migratie 019, save/load/delete routes, UI met modal + dropdown

---

## Sprint Design 4 — Kolom-kiezer icoon in tabel ✅ (2026-04-04)

- [x] `div.col-toggle-bar` verwijderd
- [x] ⊞ icoon als laatste `<th>` in tabelheader met checkbox-dropdown
- [x] Sluit bij click buiten, `localStorage`-logica intact

---

## Sprint 9 — Actieknop per transactie (">" paneel) ✅ (2026-04-04)

- [x] `›` knop rechts in elke rij — toggled inline uitklapbare rij eronder
- [x] Paneel toont tegenpartij, datum, categorie
- [x] "Maak een regel" → `GET /rules?from_tx={id}` met pre-fill (counterparty, match-type, bedragrichting, categorie)
- [x] "Maak terugkerend" → `GET /recurring?from_tx={id}` met pre-fill (naam, bedrag, categorie, tegenpartij)
- [x] Beide formulieren scrollen automatisch naar het aanmaak-formulier + tonen alert-banner

---

## Sprint 10 — Projected Transactions ✅ (2026-04-04)

- [x] `is_projected` veld op Transaction + migratie 022
- [x] `sync_projected_transactions(user_id, year, month, db)` — genereert/ruimt placeholders op per maand
- [x] `cleanup_matched_projected()` — ruimt projected op na import
- [x] Transactielijst: projected rijen bovenaan bij maandweergave (gestreept, "Verwacht" badge)
- [x] `_build_tx_query` filtert altijd `is_projected == 0`
- [ ] **Fase 3 (nog te doen)**: budget-prognose — "Verwacht nog €Y" per categorie op budgetpagina

---

## Sprint 12 — Database migratie naar Neon ✅ (2026-04-04)
*Eenmalige migratie. Onafhankelijk van andere sprints.*

**Context voor nieuwe sessie:**
- Huidige database: PostgreSQL in Docker container op Synology NAS
- Verbinding via `DATABASE_URL` in `stack.env`
- Neon account aanmaken op https://neon.tech (gratis tier, 512MB)

**Taken:**
- [ ] Neon project + database aanmaken, connection string ophalen
- [ ] `pg_dump` van huidige database op NAS
- [ ] `pg_restore` naar Neon
- [ ] `DATABASE_URL` in `stack.env` op Portainer updaten naar Neon connection string
- [ ] Alembic migraties draaien op Neon om schema te verifiëren
- [ ] App herstarten + smoke test
- [ ] Oude PostgreSQL container + volume uit docker-compose.yml verwijderen

---

## Sprint 14 — Gebruikerstoegang & beveiliging
*Kort termijn. Vereist e-mailprovider (bijv. Resend.com — gratis tier 3000 mails/mnd).*

**Bestanden:** `app/routers/auth.py`, `app/models.py` (User), `app/templates/auth/`

**Taken:**
- [ ] **E-mail verificatie**: bij registratie een verificatielink sturen — `is_verified` veld op User, onverifieerde accounts kunnen niet inloggen
- [ ] **Wachtwoord reset**: "Vergeten wachtwoord" flow — e-mail met reset-link (token met TTL), nieuw wachtwoord instellen
- [ ] **Invite-only registratie**: `REGISTRATION_OPEN` config flag — als uit, alleen registreren via uitnodigingslink die jij genereert (`/admin/invite`)
- [ ] **Rate limiting op login**: max 5 pogingen per IP per minuut — bescherming tegen brute force

---

## Sprint 16 — Encryptie at-rest van gevoelige velden
*Middellang termijn. Onafhankelijk van andere sprints. Beschermt gebruikersdata als de database wordt gelekt.*

**Doel:** gevoelige financiële velden versleutelen in de applicatielaag. Een aanvaller die alleen toegang heeft tot de database (bijv. via een dump of SQL-injection) kan dan geen leesbare transactiedata inzien.

**Technische aanpak:**
- Symmetrische encryptie met `cryptography` library (`Fernet` — AES-128-CBC + HMAC)
- Encryptiesleutel (`FIELD_ENCRYPTION_KEY`) staat als omgevingsvariabele, **niet** in de database
- Encryptie/decryptie in de applicatielaag via een helper — SQLAlchemy `TypeDecorator` zodat encrypt/decrypt transparant werkt voor de rest van de code
- Velden worden versleuteld opgeslagen als base64-string; bestaande data wordt éénmalig gemigreerd

**Te versleutelen velden op Transaction:**
- `counterparty` (naam van de tegenpartij)
- `counterparty_iban` (IBAN van de tegenpartij)
- `description` (omschrijving)

**Bestanden:** `app/crypto.py` (nieuw), `app/models.py`, `app/database.py`, migratie 024, Dockerfile/Railway env vars

**Taken:**
- [ ] `pip install cryptography` toevoegen aan `requirements.txt`
- [ ] `app/crypto.py` — `EncryptedString` TypeDecorator: `process_bind_param` versleutelt, `process_result_value` ontsleutelt; sleutel via `os.environ["FIELD_ENCRYPTION_KEY"]`
- [ ] `FIELD_ENCRYPTION_KEY` genereren (`Fernet.generate_key()`) en instellen in Railway + Portainer stack env
- [ ] `counterparty`, `counterparty_iban`, `description` op Transaction omzetten naar `EncryptedString`
- [ ] Eénmalig migratiescript: bestaande rijen uitlezen, opnieuw versleuteld wegschrijven (batchgewijs, buiten Alembic om)
- [ ] Controleren dat alle queries die op deze velden filteren (ILIKE/contains) nog werken — encryptie maakt server-side LIKE onmogelijk; oplossing: zoekterm ook versleutelen en exacte vergelijking, of zoeken in Python na ophalen
- [ ] Testen: dump van database bevat geen leesbare tegenpartijnamen meer

**Aandachtspunt zoekfunctie:**
ILIKE-queries op versleutelde velden werken niet meer. Oplossingen:
- Optie A: zoeken in Python (alles ophalen, filteren in memory) — simpel maar langzamer
- Optie B: aparte `counterparty_search_hash` kolom (HMAC van lowercase waarde) voor exacte lookups
- Optie C: volledige tekstindex buiten de database (bijv. simpele Whoosh/in-memory index) — overkill voor persoonlijk gebruik
- **Aanbeveling:** Optie A voor nu (dataset is klein), Optie B als performance een probleem wordt

---

## Sprint 15 — Gebruikersbeheer (admin)
*Middellang termijn. Bouwt op Sprint 14.*

**Bestanden:** nieuw `app/routers/admin.py`, `app/templates/admin/`

**Taken:**
- [ ] **Admin flag op User**: `is_admin` veld + migratie — eerste geregistreerde gebruiker krijgt automatisch admin
- [ ] **Admin panel** `/admin/users`: lijst van alle gebruikers (naam, e-mail, registratiedatum, laatste login, verified/actief), activeren/deactiveren
- [ ] **Invite links genereren**: admin genereert uitnodigingslink met TTL (7 dagen) — ontvangt link per mail of kopiëren
- [ ] **Gebruikersstatistieken**: per gebruiker aantal transacties, rekeningen, laatste activiteit
- [ ] **Neon database schaling**: documentatie voor upgrade naar betaald plan bij groei (>512MB of >10 gebruikers)

---

## Sprint 13 — Setup export & import (configuratie-backup)
*Exporteer de volledige app-configuratie als JSON, importeer met één druk op de knop.*

**Bestanden:** nieuw `app/routers/settings.py`, `app/templates/settings/index.html`

**Context voor nieuwe sessie:**
- Exporteren: Rules, RecurringTransactions, Categories (incl. hiërarchie + kleuren), Budgets (per maand), Tags
- Geen transactie-data in de export — alleen de "setup"
- Import: JSON uploaden → preview wat er geladen wordt → bevestigen → upsert naar database

**Taken:**
- [ ] `GET /settings/export` — genereert JSON met alle configuratie-entiteiten voor de ingelogde gebruiker
- [ ] `POST /settings/import` — parseert JSON, toont preview (aantallen per type), bevestig-knop
- [ ] Conflict-strategie bij import: bestaande items overslaan of overschrijven (keuze via radio)
- [ ] Downloadknop in settings-pagina + upload-formulier
- [ ] Versienummer in export-JSON zodat toekomstige formaat-wijzigingen te detecteren zijn

---

## Sprint 4 — Analyse & Rapportage
*Nieuwe rapportage-pagina's. Onafhankelijk van andere sprints.*

**Bestanden:** `app/routers/analytics.py`, `app/templates/analytics/index.html`, nieuw: `app/templates/analytics/stats.html`

**Context voor nieuwe sessie:**
- Analytics router staat in `app/routers/analytics.py` — huidige functie: `analytics()` op `/analytics`
- Dashboard router (`app/routers/dashboard.py`) heeft al spaartarief-logica en recurring preview
- Recurring transacties model: `RecurringTransaction` met `frequency`, `amount_expected`, `is_active`

**Taken:**
- [ ] **Stats pagina** `/analytics/stats`: top merchants op totaalkosten + transactiefrequentie, nieuwe tegenpartijen deze maand (niet eerder gezien), top-10 categorieën — nieuwe route + template
- [ ] **Spaartarief op dashboard**: al berekend in dashboard router, alleen prominent tonen in de summary-kaarten boven de grafiek
- [ ] **Projectie op dashboard**: bereken voor huidige maand: verwacht nog te ontvangen/betalen via actieve recurring items die nog niet gematcht zijn — toon als "+€X verwacht" naast de totalen
- [ ] **Flexibele query-builder** `/analytics/query`: form met datumrange + groepeer-op (categorie/tag/merchant) + grafiektype (bar, pie, line) — render resultaat als chart + downloadbare CSV

---

## Sprint 5 — Regels uitbreiden
*Meer condities en acties in de rules engine. Onafhankelijk van andere sprints.*

**Bestanden:** `app/routers/rules.py`, `app/rules_engine.py`, `app/models.py` (Rule model), `app/templates/rules/list.html`

**Context voor nieuwe sessie:**
- Rule model heeft: `match_field` (counterparty/description/iban), `match_type` (contains/exact/starts_with), `match_value`, `action_category_id`, `action_tag_id`, `amount_min`, `amount_max`
- Rules engine in `app/rules_engine.py` — `apply_rules(transaction, rules, db)`
- Toevoegen van condities: voeg kolom toe aan Rule model + migratie + UI
- Toevoegen van acties: zelfde patroon als `action_category_id`

**Taken:**
- [ ] **Regelactie: counterparty hernoemen** — nieuw veld `action_rename_counterparty` op Rule model + migratie (019) + toepassen in rules engine + UI
- [ ] **Regelactie: markeer als reviewed** — nieuw veld `action_set_reviewed` (0/1) op Rule model + migratie + toepassen + UI
- [ ] **Regelconditie: account filter** — nieuw veld `condition_account_id` op Rule model + migratie + UI dropdown
- [ ] **Regelconditie: notes/omschrijving** — nieuw veld voor matching op `description` kolom (aparte van counterparty) — check of dit al bestaat en evt. uitbreiden
- [ ] **Suggestie bij categoriseren**: op de transactiepagina, na inline categorie-wijziging via AJAX, toon een kleine banner "Wil je een regel aanmaken voor [tegenpartij]?" — JS + endpoint

---

## Sprint 6 — CSV import verbeteringen
*Betere import-ervaring voor niet-standaard CSV's. Onafhankelijk.*

**Bestanden:** `app/routers/transactions.py` (import routes), `app/templates/transactions/import.html`, `app/parsers/`

**Context voor nieuwe sessie:**
- Import route: `GET/POST /import` in `app/routers/transactions.py`
- Huidige flow: upload → auto-detect bank format → parse → save
- Parsers in `app/parsers/` — base parser heeft `ParsedTransaction` dataclass
- Nieuwe flow moet zijn: upload → kolommapping UI → preview → bevestigen → save

**Taken:**
- [ ] **Kolommapping UI**: na upload, als bank-format niet herkend, toon tabel met CSV-headers en dropdowns om velden te mappen (datum, bedrag, omschrijving, tegenpartij, IBAN) — POST naar `/import/preview`
- [ ] **Opgeslagen importconfiguraties**: model `ImportConfig` (naam, kolomnamen-mapping als JSON) — sla op per gebruiker, laad via dropdown bij import
- [ ] **Import preview/review scherm**: toon parsed transacties vóór opslaan — checkbox per rij, samenvatting (nieuw/duplicaat/auto-gecategoriseerd) — bevestigen via POST
- [ ] **Tags/categorieën uit CSV**: als CSV kolom "category" of "tags" heeft, map naar CTP categorieën/tags tijdens import

---

## Sprint 11 — Terugkerende items verfijnen ✅ (2026-04-04)

- [x] `active_months` veld op RecurringTransaction (kommagescheiden maandnummers, NULL = alle)
- [x] Maand-checkbox picker in add/edit formulier, actieve maand-pills per item
- [x] `_is_in_active_period()` en `_is_active_in_month()` respecteren `active_months`

---

## Sprint 7 — Terugkerende transacties uitbreiden ✅ (2026-04-04)
*Onafhankelijk van andere sprints.*

- [x] **Actieve periode**: `start_date` + `end_date` op RecurringTransaction + migratie 020 + UI datepickers
- [x] **Handmatig koppelen**: `recurring_id` FK op Transaction + POST `/recurring/{id}/link` + unlink
- [x] **Gemiste betalingen sectie**: prominente rode sectie bovenaan voor items die ook vorige periode niet gematcht waren; pagina opgesplitst in Gemist / Verwacht / Ontvangen / Inactief

---

## Sprint 8 — Categorieën & Tags opruimen ✅ (2026-04-04)
*Onafhankelijk van andere sprints.*

- [x] **Categorieën archiveren**: `is_archived` + migratie 021 + 🗄 toggle-knop + show_archived filter + cascade naar children
- [x] **Categorieën samenvoegen**: POST `/categories/merge` — verplaatst transacties + herparents children + verwijdert bron
- [x] **Transfer-transacties**: `transfer_id` FK op Transaction + migratie + POST `/transactions/{id}/link-transfer` + unlink — bidirectioneel; ⇄ knop in transactielijst
- [x] **Tag kleuren**: `color` veld op Tag + migratie + kleurkiezer + gekleurde pill weergave
- [x] **Tags archiveren**: `is_archived` op Tag + toggle + show_archived filter

> **Nog te doen (follow-up):** transfers uitsluiten van dashboard/analytics-totalen (`Transaction.transfer_id.is_(None)` filter toevoegen in `dashboard.py` + `analytics.py`)

---

## Reeds geïmplementeerd (referentie)

- Gebruikersregistratie / login (sessie-gebaseerd, bcrypt)
- Rekeningbeheer (ABN, ING, Rabobank, Bunq, ICS)
- CSV-import met duplicaatdetectie en auto-format detectie
- ICS PDF transactiesplitsing (parent/child)
- Transacties: aanmaken, bewerken, uitsluiten (`is_excluded`), reviewed toggle (`is_reviewed`), paginering, filtering
- Categorieën: hiërarchie, kleuren, income-flag, exclude-flags, drag-and-drop volgorde
- Tags: many-to-many, gebruikscount
- Rules engine: counterparty/description/IBAN matching, category+tag acties, suggesties, preview
- Terugkerende transacties: frequenties, auto-detectie, dashboard-integratie
- Budgetten: maandelijks per categorie, rollover, exclude_from_budget filtering
- Dashboard: inkomen/uitgaven, categorie-breakdown, recurring-preview, spaartarief
- Analytics: maandtrend, top-10 categorieën, exclude_from_totals filtering
- Savings plans: jaarplanning met regels en statustracking
- Portfolio: crypto + metalen met live prijzen (CoinGecko + currency API)
- Net worth: activa/passiva met historische snapshots
- Design system: Editorial Finance (navy/gold, Syne + DM Sans, light theme)
