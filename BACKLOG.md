# CheckThePockets — Product Backlog

Gebaseerd op vergelijking met Lunch Money (april 2026). Import beperkt tot CSV.
Sprints zijn gegroepeerd op gedeelde bestanden voor maximale efficiëntie per sessie.

> **Nieuwe sessie starten?** Zeg: *"Start Sprint X"* en Claude pakt de taken direct op.
> Elke sprint is zelfstandig uitvoerbaar zonder context uit vorige sessies.

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

## Sprint 7 — Terugkerende transacties uitbreiden
*Onafhankelijk van andere sprints.*

**Bestanden:** `app/routers/recurring.py`, `app/templates/recurring/list.html`, `app/models.py` (RecurringTransaction)

**Context voor nieuwe sessie:**
- RecurringTransaction model heeft: `name`, `amount_expected`, `frequency`, `category_id`, `counterparty`, `description_match`, `is_active`
- Matching-logica in recurring router
- Migratie 019 of 020 nodig voor nieuwe velden

**Taken:**
- [ ] **Actieve periode**: voeg `start_date` en `end_date` toe aan RecurringTransaction + migratie + UI datepickers — filter recurring items op actieve periode bij matching en dashboardweergave
- [ ] **Handmatig koppelen**: knop op transactiepagina of recurring-pagina om bestaande transactie te linken aan recurring item — sla op via `recurring_id` FK op Transaction model
- [ ] **Gemiste betalingen sectie**: op recurring-pagina, aparte sectie "Gemist" voor items die al hadden moeten betaald zijn maar geen overeenkomende transactie hebben — prominenter dan nu

---

## Sprint 8 — Categorieën & Tags opruimen
*Onafhankelijk van andere sprints.*

**Bestanden:** `app/routers/categories.py`, `app/routers/tags.py`, `app/templates/categories/list.html`, `app/templates/tags/list.html`, `app/models.py`

**Context voor nieuwe sessie:**
- Category model heeft `is_income`, `exclude_from_budget`, `exclude_from_totals`, `sort_order`, `parent_id`
- Archiveren = nieuw veld `is_archived` (0/1) + filter in lijstweergaven
- Mergen = alle transacties van categorie A overzetten naar categorie B, daarna A verwijderen

**Taken:**
- [ ] **Categorieën archiveren**: veld `is_archived` + migratie + toggle-knop + standaard verbergen in lijsten (toon toggle "toon gearchiveerd")
- [ ] **Categorieën samenvoegen**: form om twee categorieën te mergen — UPDATE transactions SET category_id=B WHERE category_id=A, daarna A verwijderen
- [ ] **Transfer-transacties**: twee transacties koppelen als "transfer" (debet op rekening A + credit op rekening B) — nieuw veld `transfer_id` op Transaction + UI om te koppelen + uitsluiten van totalen
- [ ] **Tag kleuren**: `color` veld op Tag model + migratie + kleurkiezer in tag-beheer + toon als gekleurde pill op transactiepagina
- [ ] **Tags archiveren**: veld `is_archived` op Tag + toggle + verbergen in dropdowns

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
