# CheckThePockets — Product Backlog

Gebaseerd op vergelijking met Lunch Money (april 2026). Import beperkt tot CSV.
Sprints zijn gegroepeerd op gedeelde bestanden voor maximale efficiëntie per sessie.

> **Nieuwe sessie starten?** Zeg: *"Start Sprint X"* en Claude pakt de taken direct op.
> Elke sprint is zelfstandig uitvoerbaar zonder context uit vorige sessies.

---

## Sprint Design 2 — Layout redesign + dark/light thema-switcher

*Tweefasige aanpak:*
*Fase A — Layout: HTML-structuur van alle pagina's aanpassen naar de Banani-mockup (geldt voor beide thema's)*
*Fase B — Thema's: huidige navy/gold stijl als "dark" bewaren + nieuw oranje/licht als "light" toevoegen + toggle*

**Referentie:** twee screenshots gedeeld door gebruiker (april 2026):
1. Transactiepagina mockup (exacte UI-layout)
2. Design system sheet (exacte kleur- en font-tokens)

**Bestanden:** `app/static/css/style.css`, `app/templates/base.html`, `app/templates/transactions/list.html`

**Context voor nieuwe sessie:**
- Huidig thema: Editorial Finance — navy `#002752`, gold `#F9A800`, fonts: Syne + DM Sans
- CSS custom properties staan bovenin `style.css` — thema-switching via `[data-theme]` op `<html>`
- `--ctp-*` legacy aliassen moeten intact blijven
- Google Fonts import in `base.html` `<head>`
- Themavoorkeur opslaan in `localStorage`, instellen via `data-theme="light"|"dark"` op `<html>`

**Design system light thema (exacte tokens uit mockup):**
```
--primary:     #234C75   /* navy */
--secondary:   #F28C28   /* oranje — primaire CTA-kleur */
--tertiary:    #5DADE2   /* lichtblauw accent */
--bg:          #F8F9FA   /* pagina-achtergrond */
--card:        #ffffff
--text:        #1a1a2e
--muted:       #6b7280
--border:      #e5e7eb

Font: Plus Jakarta Sans 400/500/600/700/800
→ https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap
```

---

### FASE A — Layout (thema-onafhankelijk, 1 sprint)

**Bestanden:** `base.html`, `transactions/list.html`, `style.css` (structurele CSS)

- [ ] **Logo restructuur** (`base.html`): wallet-icoontje behouden + tekst gestapeld naast het icoontje:
  `CHECK` / `THE` / `POCKETS` in drie regels, CHECK+THE in accentkleur (`var(--secondary)`), POCKETS in primaire kleur (`var(--primary)`). Gebruik CSS-variabelen zodat dit in beide thema's werkt.

- [ ] **Gebruikersavatar** (`base.html`): ronde initialen-cirkel rechts in de primaire nav:
  `{{ user.username[:2].upper() }}` in een `div.user-avatar` — stijl via CSS-variabelen. Vervangt huidige tekst-only gebruikersnaam.

- [ ] **Primaire nav active-indicator** (`style.css`): van huidige goud-streep → `border-bottom: 3px solid var(--primary)` onder actief item.

- [ ] **Sub-nav active-indicator** (`style.css`): actief item krijgt pill-stijl:
  `background: var(--subnav-pill-bg); border-radius: 999px; padding: 0.3rem 1rem`
  (variabele `--subnav-pill-bg` verschilt per thema: licht = `#F5F0E8`, donker = `rgba(255,255,255,0.1)`)

- [ ] **Paginatitels** (`style.css`): `h1` in `.page-header` → `color: var(--secondary); font-weight: 800; font-size: 2rem`.
  Teller "(N)" → `color: var(--muted); font-weight: 400; font-size: 1.1rem` (via `<span class="page-count">`)

- [ ] **Tabelstructuur** (`style.css` + `transactions/list.html`): tabel zonder card-wrapper (zit direct op achtergrond), rijen gescheiden door `border-bottom: 1px solid var(--border)`. Kolomkoppen: `text-transform: uppercase; letter-spacing: 0.07em; font-size: 0.7rem; font-weight: 600; color: var(--muted)`.

- [ ] **Filterbar** (`transactions/list.html`):
  - Veldlabels boven de inputs als uppercase captions: `font-size:0.68rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted)`
  - Zoekicoontje als inline SVG in het zoekveld (absolute positioning, `padding-left:2.5rem` op input)
  - "Meer filters" → oranje/accent link met `›` chevron, geen knop

- [ ] **Knoppen transactiepagina** (`transactions/list.html`):
  - "Handmatig toevoegen" → `.btn-accent` (primary/navy filled, uppercase)
  - "CSV importeren" → `.btn-primary` (secondary/oranje filled, met document-icoon `📄` of SVG)
  - BEWERKEN → `.btn-sm` outlined grijs
  - UITSLUITEN → `.btn-sm` outlined met accentkleur tekst (geen gevulde achtergrond)

---

### FASE B — Thema-switcher (aparte sprint na Fase A)

**Bestanden:** `style.css`, `base.html`

- [ ] **CSS thema-variabelen**: twee variabelenblokken in `style.css`:
  ```css
  :root, [data-theme="light"] { --primary:#234C75; --secondary:#F28C28; --bg:#F8F9FA; ... }
  [data-theme="dark"]          { --primary:#002752; --secondary:#F9A800; --bg:#1e1e2e; ... }
  ```
  Alle bestaande kleurwaarden in dark-blok zetten, light-blok is het nieuwe Banani-palet.

- [ ] **Font-switcher** (`style.css`): font-stacks per thema of één gedeeld font (Plus Jakarta Sans voor beide, of Syne/DM Sans behouden voor dark). Keuze: **Plus Jakarta Sans voor beide** (eenvoudiger).

- [ ] **Toggle-knop** (`base.html`): zon/maan icoon-knop in de nav naast de avatar:
  ```html
  <button class="theme-toggle" onclick="toggleTheme()" title="Wissel thema">🌙</button>
  ```

- [ ] **Toggle JS** (`base.html` of `static/js/theme.js`):
  ```js
  function toggleTheme() {
    const html = document.documentElement;
    const next = html.dataset.theme === 'dark' ? 'light' : 'dark';
    html.dataset.theme = next;
    localStorage.setItem('theme', next);
  }
  // On load:
  document.documentElement.dataset.theme = localStorage.getItem('theme') || 'light';
  ```

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
