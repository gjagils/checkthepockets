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

## Sprint 10 — Projected Transactions (potlood-planning)

*Bouwt op Sprint 9 ("Maak terugkerend" vanuit transactie) en het bestaande RecurringTransaction model.*

**Bestanden:** `app/models.py`, `app/routers/transactions.py`, `app/routers/recurring.py`, `app/templates/transactions/list.html`, `app/templates/budgets/month.html`

**Context voor nieuwe sessie:**
- `RecurringTransaction` heeft: `name`, `amount_expected`, `frequency`, `counterparty`, `category_id`, `account_id`, `start_date`, `end_date`, `is_active`
- `Transaction.recurring_id` FK bestaat al (Sprint 7) — koppelt echte transactie aan recurring item
- Budgetpagina toont per categorie: budgetteerd, uitgegeven, resterend
- Import-flow: `POST /import/confirm` slaat transacties op en past rules toe

**Idee:** Terugkerende items genereren automatisch een *verwachte transactie* (`is_projected=True`) voor de lopende maand. Deze staat in de transactielijst, visueel onderscheiden. Bij import matcht de echte transactie de placeholder en vervangt die.

**Datamodel:**
```python
Transaction
  + is_projected: bool = False   # nieuw veld + migratie
  # is_projected=True entries tellen niet mee in export, CSV, bulk-acties
  # wel mee in budget-prognose berekeningen
```

**Taken:**

### Fase 1 — Genereren & tonen
- [ ] **Migratie**: `is_projected INTEGER DEFAULT 0` op `transactions`
- [ ] **Generator-functie** in `recurring.py`: `generate_projected_for_month(user, year, month, db)` — maakt voor elk actief recurring item een `Transaction(is_projected=True)` aan als die er nog niet is voor die periode
- [ ] **Aanroep**: generator draaien bij laden van transactiepagina (lazy) en bij aanmaken/bewerken recurring item
- [ ] **Transactielijst**: projected entries bovenaan, visueel anders — stippelborder of grijze rij, label "Verwacht", bedrag in `var(--muted)` i.p.v. rood/groen
- [ ] **Filteren**: projected entries standaard zichtbaar, maar weglaatbaar via toggle "Toon verwacht"

### Fase 2 — Matching bij import
- [ ] **Match-logica**: bij `POST /import/confirm`, na opslaan echte transactie, zoek passende projected entry (zelfde recurring_id, zelfde maand) → verwijder de placeholder of markeer als gematcht
- [ ] **Handmatige match**: als er geen automatische match is, kan gebruiker via "›" paneel de projected entry koppelen aan een echte transactie

### Fase 3 — Budget-prognose
- [ ] **Budgetpagina**: naast "Uitgegeven €X" ook "Verwacht nog €Y" (som van projected entries in die categorie die nog niet gematcht zijn)
- [ ] **Resterende ruimte**: `budget - uitgegeven - verwacht` → "Vrij te besteden: €Z"

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

## Sprint 11 — Terugkerende items verfijnen

*Uitbreiding op het bestaande RecurringTransaction model (Sprint 7).*

**Bestanden:** `app/models.py`, `app/routers/recurring.py`, `app/templates/recurring/list.html`, `app/templates/recurring/_edit_form.html`

**Context voor nieuwe sessie:**
- `RecurringTransaction` heeft al: `name`, `amount_expected`, `frequency`, `counterparty`, `category_id`, `account_id`, `start_date`, `end_date`, `is_active`
- Recurring items zijn nu altijd "elke maand" actief binnen de start/end periode
- Sprint 10 (projected transactions) bouwt hierop — maandfilter bepaalt of er een placeholder gegenereerd wordt

**Taken:**

### Maandfilter per recurring item
- [ ] **Datamodel**: nieuw veld `active_months: str` op `RecurringTransaction` — kommagescheiden lijst van maandnummers bijv. `"3,4,5,6,7,8,9,10,11,12"`. Leeg = alle maanden. Migratie toevoegen.
- [ ] **UI in formulier**: 12 checkboxes (Jan t/m Dec), standaard allemaal aangevinkt. Groepeer per kwartaal voor overzicht.
- [ ] **Generator-logica** (Sprint 10 aansluiting): `generate_projected_for_month()` controleert of de huidige maand in `active_months` valt voordat een placeholder aangemaakt wordt
- [ ] **Weergave in lijst**: toon de actieve maanden als pill-rij onder de naam, bijv. `Mrt Apr Mei ... Dec` (gekleurde pills, inactieve maanden grijs)

### Handmatig aanmaken recurring items
- [ ] **"Nieuw terugkerend item" knop** op de recurring pagina — opent hetzelfde formulier als "Maak terugkerend" vanuit een transactie (Sprint 9), maar zonder pre-fill
- [ ] **Formuliervelden**: naam, verwacht bedrag, richting (uitgave/inkomst), tegenpartij, categorie, rekening, frequentie, start/einddatum, actieve maanden
- [ ] Dit bestaat deels al via `POST /recurring/new` — controleer of dat formulier compleet is en voeg ontbrekende velden toe

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
