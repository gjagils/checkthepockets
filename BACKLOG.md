# CheckThePockets — Product Backlog

Gebaseerd op vergelijking met Lunch Money (april 2026). Import beperkt tot CSV.
Sprints zijn gegroepeerd op gedeelde bestanden voor maximale efficiëntie per sessie.

> **Nieuwe sessie starten?** Zeg: *"Start Sprint X"* en Claude pakt de taken direct op.
> Elke sprint is zelfstandig uitvoerbaar zonder context uit vorige sessies.

---

## Sprint 19 — Dashboard grafiek & recurring koppeling ✅ (2026-04-08)

- [x] Klik-navigatie in grafiek via HTML links onder chart (Chart.js onClick was onbetrouwbaar)
- [x] Budget-achtergrond als plugin + gestapelde bars (gerealiseerd + verwacht)
- [x] Y-as schaal inclusief budget-waarden + label-uitlijning met chartArea
- [x] Niet-gecategoriseerd balk gevuld met eurobedrag in maandview
- [x] Maandview (level 2) en categorie-view (level 3) werkend met drill-down
- [x] Recurring koppelknop in transactie-panel met dropdown
- [x] Voorstel-banner na koppelen (zoekt vergelijkbare transacties, toont accept/negeer)
- [x] Auto-link na CSV import (`auto_link_recurring_after_import`)
- [x] Eerste-transactiedatum logica: geen projected transacties vóór eerste import, "gemist" gefilterd

---

## Sprint 17 — Slimme regelanalyse (Claude API) ✅ (2026-04-07)

- [x] `anthropic>=0.39.0` in `requirements.txt`
- [x] `app/ai_suggest.py` — `suggest_rule()`, `suggest_rules_bulk()`, `parse_description()`, `ai_available()`
- [x] Regex-parsers voor ABN AMRO BEA/GEA, SEPA, iDEAL, TRTP (ING/Rabobank)
- [x] `POST /rules/suggest` endpoint met AI + regex fallback
- [x] "✨ Analyseer" knop in regelformulier — pre-fill via JS
- [x] Fallback: knop verborgen als `ANTHROPIC_API_KEY` niet ingesteld
- [x] **Bonus:** Bulk regelanalyse (`POST /rules/analyze`) — groepeert ongecategoriseerde transacties, AI-suggesties in `RuleSuggestion` tabel
- [x] **Bonus:** Recurring detectie (`detect_recurring_patterns()` + `enrich_recurring_with_ai()`)
- [x] **Bonus:** Interactieve suggestie-UI met klikbare aantallen, inline bewerken, toevoegen/verwijderen

---

## Sprint 18 — Google login (OAuth2) ✅ (2026-04-07)

- [x] `authlib>=1.3.0` + `httpx>=0.27.0` in `requirements.txt`
- [x] `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` in `app/config.py`
- [x] `GET /auth/google` — redirect naar Google OAuth consent screen
- [x] `GET /auth/google/callback` — verwerk callback, zoek/maak user, zet sessie-cookie
- [x] "Inloggen met Google" knop op `auth/login.html` met Google SVG-icoon
- [x] Fallback: knop verborgen als Google credentials niet ingesteld
- [x] Automatische user-aanmaak bij eerste Google login (respecteert `REGISTRATION_OPEN`)
- [x] SessionMiddleware cookie hernoemd naar `oauth_state` om conflict te voorkomen

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
- [x] **Fase 3**: budget-prognose — "Verwacht nog €Y" per categorie + sync_projected op budgetpagina

---

## Sprint 12 — Database migratie naar Neon ✅ (2026-04-04)
*Eenmalige migratie. Onafhankelijk van andere sprints.*

**Context voor nieuwe sessie:**
- Huidige database: PostgreSQL in Docker container op Synology NAS
- Verbinding via `DATABASE_URL` in `stack.env`
- Neon account aanmaken op https://neon.tech (gratis tier, 512MB)

**Taken:**
- [x] Neon project + database aanmaken, connection string ophalen
- [x] `pg_dump` van huidige database op NAS
- [x] `pg_restore` naar Neon
- [x] `DATABASE_URL` in `stack.env` op Portainer updaten naar Neon connection string
- [x] Alembic migraties draaien op Neon om schema te verifiëren
- [x] App herstarten + smoke test
- [x] Oude PostgreSQL container + volume uit docker-compose.yml verwijderen

---

## Sprint 14 — Gebruikerstoegang & beveiliging ✅ (2026-04-04)

- [x] **E-mail verificatie**: `is_verified` veld, verificatielink via Resend, `REQUIRE_EMAIL_VERIFICATION` flag
- [x] **Wachtwoord reset**: "Wachtwoord vergeten" flow met token (TTL 1 uur)
- [x] **Invite-only registratie**: `REGISTRATION_OPEN` config flag + invite tokens (TTL 7 dagen)
- [x] **Rate limiting op login**: max 5 pogingen per IP per minuut (in-memory)

---

## Sprint 16 — Encryptie at-rest van gevoelige velden ✅ (2026-04-04)

- [x] `cryptography==43.0.3` in `requirements.txt`
- [x] `app/crypto.py` — `EncryptedText` TypeDecorator (Fernet AES-128-CBC + HMAC-SHA256)
- [x] `counterparty`, `counterparty_iban`, `description` op Transaction versleuteld
- [x] Admin endpoint om bestaande data te (her)versleutelen
- [x] Graceful fallback voor legacy plaintext data

---

## Sprint 15 — Gebruikersbeheer (admin) ✅ (2026-04-04)

- [x] `is_admin` veld op User — eerste geregistreerde gebruiker = admin
- [x] Admin panel `/admin/users`: gebruikerslijst, activeren/deactiveren, admin toggle, verwijderen
- [x] Invite links genereren (met optionele e-mail via Resend)
- [x] Gebruikersstatistieken: rekening- en transactieaantallen per gebruiker

---

## Sprint 13 — Setup export & import (configuratie-backup) ✅ (2026-04-07)

- [x] `GET /settings/export` — JSON met categorieën, tags, regels, recurring, budgetten (versie 1)
- [x] `POST /settings/import/preview` — upload JSON, toont preview met aantallen per type
- [x] `POST /settings/import/confirm` — importeert met conflict-strategie (overschrijven of overslaan)
- [x] Conflict-strategie via radio-knoppen op preview-pagina
- [x] Downloadknop + upload-formulier op settings-pagina
- [x] Versienummer in export-JSON (version: 1) met validatie bij import

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

## Sprint 5 — Regels uitbreiden ✅ (2026-04-04)

- [x] **Regelactie: counterparty hernoemen** — `action_rename_counterparty` veld + migratie + rules engine + UI
- [x] **Regelactie: markeer als reviewed** — `action_set_reviewed` veld + migratie + UI
- [x] **Regelconditie: account filter** — `condition_account_id` veld + migratie + UI dropdown
- [x] **Suggestie bij categoriseren** — dismissible banner na inline categorie-wijziging met link naar regelformulier

---

## Sprint 6 — CSV import verbeteringen ✅ (2026-04-04)

- [x] **Import preview**: toon nieuwe vs. duplicaat transacties vóór opslaan (voor alle bankformaten)
- [x] **Kolomtoewijzing UI**: aangepast CSV-formaat met dropdowns per veld
- [x] **Categorie uit CSV**: categorie-kolom matcht op naam met bestaande categorieën
- Opgeslagen importconfiguraties: bewust weggelaten (overkill voor persoonlijk gebruik)

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

> **Follow-up afgerond (2026-04-08):** transfers uitgesloten van dashboard, analytics en budgetten via `Transaction.transfer_id.is_(None)` filter

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
