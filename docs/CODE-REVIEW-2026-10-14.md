# Codereview Check The Pockets — 14 oktober 2026

Doel: de codebase netjes bijwerken vóór een UI-redesign. Dit document bevat de
bevindingen van een volledige scan (Python, templates, CSS/JS, tests, CI,
infra) met concrete voorstellen, gegroepeerd in PR's. Het is een voorstel;
niets hieruit is al uitgevoerd of in ACTIEPLAN.md opgenomen.

## Stand van zaken (gemeten)

| Onderdeel | Cijfer |
|---|---|
| Python in app/ | ~20.000 regels; 20 routers (3 van >1.400 regels), 30 services/modules |
| Templates | 65 bestanden, 11.779 regels; 1.149 inline `style=""`; 29 inline `<script>`-blokken (~2.100 regels JS); geen gedeeld JS-bestand |
| style.css | 2.170 regels; 42 dode selectors; 5 CSS-variabelen gebruikt maar nergens gedefinieerd |
| Tests (Python 3.12, schone uv-omgeving) | 512 geslaagd, 3 overgeslagen, 2.953 waarschuwingen |
| Tests (lokale `.venv`, Python 3.14 + Starlette 1.0) | 138 gefaald, 374 geslaagd (omgevingsprobleem, zie H1) |
| ruff `--select F` | 27 ongebruikte imports, 8 ongebruikte variabelen, 4 ongedefinieerde namen, 1 herdefinitie |
| ruff overig | 49 `except Exception` (blind), 29× `utcnow()`, 41× `date.today()`, 7 blokken uitgecommentarieerde code |
| Git | `Wissellijst` is een kapotte submodule-verwijzing (gitlink zonder `.gitmodules`); `.DS_Store` 2× getrackt; `main` zonder branch protection |

Alle 2.953 testwaarschuwingen komen uit twee bronnen: de verouderde
`TemplateResponse("naam", {...})`-aanroepstijl (118 plekken) en `datetime.utcnow()`.

---

## A. Fouten die nu al misgaan

Alle onderstaande punten zijn tegen de code gecontroleerd.

| # | Ernst | Plek | Wat er misgaat | Voorstel |
|---|---|---|---|---|
| A1 | hoog | [transactions.py:1060](../app/routers/transactions.py#L1060) `duplicates_page` | Groepeert in SQL op `counterparty`, een `EncryptedText`-kolom met random IV. Met `FIELD_ENCRYPTION_KEY` (verplicht in productie) is elke ciphertext uniek, dus de duplicatenpagina is in productie altijd leeg. | Transacties laden en in Python groeperen op `(date, amount, counterparty.lower())`. Lost ook de N+1 (één query per groep) op. |
| A2 | hoog | [rules_engine.py:212](../app/rules_engine.py#L212) `suggest_rules` | Zelfde probleem: `group_by(Transaction.counterparty)` met `having(count >= 2)` matcht nooit onder encryptie. Regelsuggesties zijn in productie dood. | In Python groeperen; op termijn een deterministische HMAC-kolom voor matching in SQL. |
| A3 | hoog | [crypto.py:83](../app/crypto.py#L83) `encrypt_existing_transactions` | `getattr(tx, field)` geeft de al ontsleutelde waarde, dus de `gAAA`-check vergelijkt plaintext; `setattr` met dezelfde waarde geeft geen UPDATE. De admin-knop meldt een aantal maar versleutelt niets. | Ruwe kolomwaarden lezen via `Transaction.__table__`, `flag_modified()` of directe `update()`; test die de ruwe DB-waarde controleert. |
| A4 | hoog | [categories.py:423](../app/routers/categories.py#L423) `delete_category` | Kinderen via bulk `.delete()` (omzeilt ORM); `transactions.category_id` en `budgets.category_id` hebben geen `ondelete`, budgets zijn NOT NULL. Op PostgreSQL: IntegrityError → 500 zodra een subcategorie transacties of de categorie budgetten heeft. SQLite-tests zien dit niet (FK's uit). | Transacties expliciet op NULL zetten, budgets/preset-lines verwijderen, kinderen via ORM; `PRAGMA foreign_keys=ON` in de testengine. |
| A5 | hoog | [auth.py:226](../app/routers/auth.py#L226) `register` | Uitnodigingstoken wordt verbruikt vóór de validatie van gebruikersnaam/wachtwoord. Eén tikfout verbrandt de uitnodiging. | Read-only `_find_valid_token()` voor validatie; token pas consumeren in dezelfde commit als `db.add(user)`. |
| A6 | hoog | [scheduler.py:187](../app/scheduler.py#L187) | Onbereikbare `return` met vier ongedefinieerde namen na `try/finally` in `_capture_january_wealth_plans`. Hoort aan het eind van `_run_weekly_digests`, die nu `None` teruggeeft: de digest-summary in `scheduler_run_log` is altijd leeg. | Regels 187-190 verplaatsen; test op de summary. |
| A7 | hoog | [enable_banking.py:110-222](../app/enable_banking.py#L110) | Geen enkele `requests`-aanroep heeft een `timeout`. Eén hangende verbinding blokkeert de scheduler-thread onbeperkt. `bunq_client.py` doet het wél goed. | `TIMEOUT = (5, 30)` en één `requests.Session`; `coalesce=True, misfire_grace_time=3600` op de jobs. |
| A8 | hoog | [savings.py:115-146](../app/routers/savings.py#L115) | `_get_transaction_totals_by_month` en `_has_transactions_in_month` filteren niet op `is_excluded`/`is_projected`, terwijl de rest van savings dat wel doet. Verwachte (geprojecteerde) en uitgesloten transacties tellen mee in spaarcellen, eindsaldo en suggesties. | Eén `_real_tx_query(db, account_id, year)` als basis voor alle helpers. |
| A9 | middel | [transactions.py:703](../app/routers/transactions.py#L703) | `recurring_name={item.name}` ongecodeerd in de URL; `&`, `#`, `+` breken de query-string. `quote_plus` is geïmporteerd maar ongebruikt. | `urllib.parse.urlencode(...)`. |
| A10 | middel | [budgets.py:561](../app/routers/budgets.py#L561) `budget_from_average` | Filtert niet op `is_excluded`/`transfer_id`/`is_projected`; de knop "gemiddelde" zet andere bedragen dan de kolom "gem. 3 mnd". | `category_spending_average()` hergebruiken. |
| A11 | middel | [rules.py:296](../app/routers/rules.py#L296) | `Rule.name` is `String(100)`, naam wordt hier niet afgekapt (elders wel) → DataError bij lange tegenpartijnamen. | `[:100]`. |
| A12 | middel | [account_merge.py:145](../app/account_merge.py#L145) | Categorieën worden bulk naar het doelaccount gezet; gelijknamige categorieën op beide accounts botsen op `uq_user_account_category` met een kale IntegrityError (zelfde klasse fout als de ACT-30-fix). | Naamconflicten in `plan_merge` detecteren en in de preview tonen; bron-categorie samenvoegen. |
| A13 | middel | rules.py:272/417/490, budgets.py:445, settings.py:132 | `int()`/`Decimal()` op formulierwaarden zonder try → 500 bij `category_id=abc` of `1,2,3`. | `app/forms.py` met `parse_int`, `parse_amount`, `parse_percent`, `parse_iso_date` (zie C3). |
| A14 | middel | [admin.py:523](../app/routers/admin.py#L523) | Scheduler-job handmatig starten: `except Exception: pass` en de job draait synchroon in de request-thread. | `scheduler.modify_job(next_run_time=now)` en de except loggen. |
| A15 | middel | [transactions.py:1563](../app/routers/transactions.py#L1563) `link_transfer`, `move_transaction_to_account` | Bestaande transfer-partner blijft hangen met een dangling `transfer_id`; split-kinderen verhuizen niet mee. | Partners eerst loskoppelen; kinderen mee-updaten of verplaatsen van gesplitste ouder weigeren. |

## B. Beveiliging

| # | Ernst | Plek | Bevinding | Voorstel |
|---|---|---|---|---|
| B1 | hoog | [auth.py:693](../app/routers/auth.py#L693) Google-callback | Koppelt op e-mail aan een bestaand account zonder `email_verified` te controleren (komt nergens in app/ voor). Een Google-account met ongeverifieerd adres kan een lokaal account overnemen. | `if not userinfo.get("email_verified"): fout`. |
| B2 | hoog | [auth.py:78](../app/routers/auth.py#L78) `_client_ip` + Dockerfile | `X-Forwarded-For` wordt onvoorwaardelijk vertrouwd terwijl uvicorn zonder `--proxy-headers` draait. De login-rate-limit is te omzeilen door per request een andere header te sturen. | `--proxy-headers --forwarded-allow-ips=<proxy>` en alleen `request.client.host` gebruiken. |
| B3 | hoog | auth.py:211/307/344 | Alleen `/login` heeft rate limiting; register, forgot-password en reset niet → mail-flood via Resend, vrije accountaanmaak. | `rate_limit.is_rate_limited(bucket, key)` generaliseren en op alle vier toepassen; lege entries opruimen. |
| B4 | hoog | [savings/detail.html:814](../app/templates/savings/detail.html#L814) | `row.innerHTML = ... + tx.label + ...` zonder escaping. `tx.label` is tegenpartij/omschrijving uit bankdata van derden: opgeslagen XSS. | `textContent`/`createElement`, of de `escapeHtml` uit rules/list.html via gedeeld JS. |
| B5 | middel | [dashboard/index.html:171](../app/templates/dashboard/index.html#L171) + dashboard.py:241 | `{{ overview_json \| safe }}` met `json.dumps` (escapet `</script>` niet); labels zijn categorienamen. Zelfde patroon met Jinja-waarden in JS-literals op r. 213-217, budgets/overview.html:547, wealth_forecast.html:79. | Lijst doorgeven en `\| tojson` (portfolio/dashboard.html doet dit al goed). |
| B6 | middel | [email_service.py:88-137](../app/email_service.py#L88) | Gebruikersnaam, uitnodiger en rekeningnamen ongeëscaped in HTML-mails. | `html.escape()` of een Jinja-template voor mails. |
| B7 | middel | [auth.py:750](../app/routers/auth.py#L750) + base.html:68 | Logout via GET-link; `<img src="/logout">` op een vreemde site logt uit (CSRF-check dekt alleen POST). | POST + formulier. |
| B8 | middel | [accounts.py:191](../app/routers/accounts.py#L191) | `/accounts/delete-all-transactions` zonder wachtwoordbevestiging ("for testing"); `/settings/delete-transactions` doet hetzelfde mét wachtwoord. | Route en formulier verwijderen. |
| B9 | middel | transactions.py:544/574/607/641/666/719/758/1006, recurring.py:48/93 | `redirect_to` uit het formulier ongevalideerd in `RedirectResponse` (open redirect). Elders wordt wél op `startswith("/")` gecontroleerd. | `safe_redirect(target, fallback)` in één helper, overal gebruiken. |
| B10 | middel | [auth.py:236](../app/routers/auth.py#L236) | E-mail bij registratie niet genormaliseerd (elders wel via `_clean_email`): `A@x.nl` en `a@x.nl` worden twee accounts; username niet gestript/begrensd. | `_clean_email` ook hier; `username.strip()[:50]`. |
| B11 | middel | [crypto.py:56](../app/crypto.py#L56) | Schrijven is fail-closed, lezen niet: bij een geconfigureerde maar ongeldige sleutel komt ciphertext ongewijzigd in de UI. | Ook in `process_result_value` raisen als `_encryption_configured and _fernet is None`. |
| B12 | middel | [main.py:65](../app/main.py#L65) inbox-middleware | Draait per request (ook `/healthz`) een COUNT met eigen sessie, en gebruikt `get_session_user_id` zonder `session_version`/`is_active`-check: een ingetrokken cookie vult de badge nog. | Alleen na `get_current_user` en alleen voor HTML-routes. |
| B13 | laag | deploy.yml, GitHub | `main` heeft geen branch protection; deploy draait op elke push naar main zonder te wachten op CI. | Required checks `test` + `postgres-migrations`; `concurrency` op de deploy-job. |

## C. Structuur en duplicatie (backend)

Wat goed is: eigenaarscontrole (`user_id`) is vrijwel overal correct, mutaties lopen via POST, Decimal wordt consequent gebruikt voor geld, en ACT-21/22/23 zijn goed geland (import-, spaar- en hypotheekrekenwerk zit in services). De resterende schuld zit in de laag erboven.

| # | Thema | Bevinding | Voorstel |
|---|---|---|---|
| C1 | Verouderde API | 118× `TemplateResponse("naam", {"request": ...})`. Deprecated sinds Starlette 0.29, verwijderd in 1.0 (dat is waarom de lokale `.venv` 138 tests laat falen). Daarnaast `@app.on_event("startup")` (main.py:154). | Mechanisch omzetten naar `TemplateResponse(request, "naam", ctx)`; `lifespan` i.p.v. `on_event` (ook de plek voor scheduler-shutdown). Scheelt ~2.900 waarschuwingen. |
| C2 | Tijd | 29× `utcnow()` (deprecated) en 41× `date.today()`; container draait UTC, scheduler in Europe/Amsterdam. Tussen 00:00 en 02:00 NL-tijd valt "vandaag" in de vorige dag of maand: raakt `is_past` in de spaarplanner, de 409-vergrendeling, projectie-sync en maandgrenzen. | `app/clock.py` met `now_utc()` en `today_nl()`; rekenfuncties krijgen `today` als parameter (zoals `wealth_forecast` al doet). |
| C3 | Formulierparsing | Bedrag-parsing op ~28 plekken in drie varianten (`replace(",", ".")`, met duizendtalpunt, zonder); `int()` zonder try; maandnamen 9× gedefinieerd; jaar-selector-query 4× identiek. | `app/forms.py` (`parse_amount`, `parse_percent`, `parse_int`, `parse_iso_date`) en `app/nl_format.py` (maandnamen, `format_euro`) als Jinja-globals. |
| C4 | Foutafhandeling | Vier stijlen: stille redirect (transactions), `?error=code` (savings/recurring), `?flash=` naast `HTTPException` (mortgage), en 302 vs 303 vs 400 vs 404 door elkaar. | Eén conventie vastleggen in WORKFLOW.md: niet-gevonden → 404 via `get_owned_or_404`; validatie → `?error=code`; AJAX → JSON; 303 na POST. |
| C5 | Routers importeren routers | scheduler.py:85/218 (`inbox_count`, `_map_eb_transactions`), admin.py:117 (`_clean_email`). | Naar `app/transaction_queries.py`, `app/enable_banking.py`, `app/validation.py`. |
| C6 | Banksync 2× | [scheduler.py:206](../app/scheduler.py#L206) en banking.py:399 zijn twee implementaties: de scheduler matcht alleen op IBAN, maakt geen `ImportBatch`, zet geen `last_sync_status`, en één fout rolt alle koppelingen terug. | `app/bank_sync.py` met `sync_bank_connection(db, conn) -> SyncResult`, per koppeling `begin_nested()`. |
| C7 | Transactiegrenzen | Services committen zelf (recurring_service.py:240/324/368, rules_engine.py:122/202, wealth_plan_service.py:93) én worden vanuit GET-routes aangeroepen (dashboard.py:91, budgets.py:46, transactions.py:395, savings plan_detail). Elke refresh schrijft. | Conventie "service flusht, caller commit" (zoals `account_merge` al doet); projectie-sync naar schrijfmomenten en de scheduler. |
| C8 | Lange functies | 19 functies >80 regels; grootste: `budget_overview` 400, `transaction_list` 258, `build_capital_dashboard` 246, `_level1_yearly` 229, `quick_add_line` 227, `import_confirm` 224, `sync_transactions` 221, `_render_recurring_page` 205. | Per functie opknippen in query-, reken- en view-model-helpers (concrete splitsingen staan in de agentrapporten; hoofdlijn: `_resolve_period()`, `categories_by_account()`, `scenario_view_model()`, `_expense_budget_rows()`/`_income_budget_rows()`). |
| C9 | Savings | Lopend-saldo-lus 4× in de router (savings.py:41, 486, 727, 1305); `_compute_december_balance` doet 12×N queries en wordt bij elke AJAX-celupdate aangeroepen; `_determine_entry_status` is een tweede, "legacy" statusmodel naast `determine_color_status`; `accept_ai_suggestion` (r. 1349-1433) is dood. | `savings_calc.running_balances()`, `schedule_from_form()`; legacy status verwijderen; dode route weg. |
| C10 | Recurring/transactions | `_render_recurring_page` doet ~90 queries bij 30 items (`find_matching_transaction` laadt en ontsleutelt alle transacties per item); `apply_all_categories` en `apply_category_to_linked` zijn identiek; na-import-sequentie staat 2× (transactions.py:1343, recurring.py:675); custom-CSV-parsing (transactions.py:56-171) hoort in `app/parsers/`. | Transacties per periode één keer laden; `recurring_service.resync_after_import()`, `classify_items()`; `parsers/custom_csv.py`. |
| C11 | Mortgage | 19 identieke `Form(...)`-parameters in create én edit (mortgage.py:715, 1155); rates-context 5× uitgeschreven; `rates_bulk_import` herberekent wat `compare_with_existing` al doet; `scenarios_detail` bouwt nog 35 template-sleutels. | `ScenarioForm`-dependency, `_render_rates()`, `mortgage_calc.scenario_view_model()`. |
| C12 | N+1 | portfolio.py:312 en 723 (per asset × 12 maanden), settings.py:64-91 (export), budgets/networth upsert-loops, transactions.py:1107 `exclude_duplicates`, wealth_forecast.py:170, rules_engine.py:138 (preview zonder `joinedload`), import_service.py:40 `_already_imported` per rij. | Batch-laden in dicts, `joinedload`, `id.in_(...)`. |
| C13 | AI-aanroepen | ai_suggest.py en mortgage_rate_ocr.py: vier vrijwel identieke blokken, modelnamen hardcoded (3× `claude-sonnet-4-20250514`), `except Exception → None`, geen timeout. | `app/ai_client.py` met één client, `call_json()`, `AIUnavailable`; modelnamen in config. |
| C14 | Dode code | 27 ongebruikte imports, `has_filter or True` (analytics.py:386), `tag_id`-parameter (transactions.py:190), `_fmt_amount` (savings.py:1011, duplicaat van de euro-filter), dode `mortgage_calc`-functies (`to_finance`, `overwaarde`, `annuity_principal`, `ltv`, `net_monthly`), personen-CRUD dubbel in portfolio.py:397, 7 blokken uitgecommentarieerde code, dubbele `_landing_templates` zonder euro-filters (main.py:50). | `ruff --select F` in CI en opruimen. |

## D. Datalaag en migraties

| # | Ernst | Bevinding | Voorstel |
|---|---|---|---|
| D1 | middel | Model/migratie-drift: migraties maken `ix_transactions_date`, `_account_id`, `_category_id`, `_parent_id`, `ix_rules_user_id` enz., maar het model heeft geen `index=True`. Autogenerate stelt voor ze te droppen; SQLite-tests missen ze. | `index=True` in het model; test die `compare_metadata` leeg eist na `alembic upgrade head`. |
| D2 | middel | Ontbrekende indexes: `transactions.recurring_id`, `transfer_id`, `import_hash` alleen (unique begint met `account_id`), `accounts/categories/persons.user_id`. | Eén migratie (eerstvolgende vrije nummer). |
| D3 | middel | `uq_user_account_category(user_id, account_id, name)` met nullable `account_id`: NULL ≠ NULL, dus dubbele globale categorienamen zijn mogelijk terwijl de import ze als uniek behandelt. | Partiële unique index `WHERE account_id IS NULL`. |
| D4 | middel | Cascades: `Transaction.children` zonder cascade/`passive_deletes` zet `parent_id` op NULL vóór de DELETE (DB-cascade vuurt nooit, splits worden wezen); `Account.transactions` met `delete-orphan` laadt alles in geheugen. | `cascade="all, delete-orphan", passive_deletes=True` + DB-`ondelete`. |
| D5 | middel | 22 boolean-kolommen als `Integer` met `== 1`-vergelijkingen tot in de templates; vrije strings als enums (`bank`, `frequency`, `status`, `mortgage_type`); `accounts_json` als Text-blob; `active_months`/`skipped_months` als kommastrings. | `Boolean`, `StrEnum` met `CheckConstraint`, `JSON`-kolom; properties op het model. Dit maakt de templates straks typed en consistent. |
| D6 | middel | Migraties: downgrades met `try/except: pass`, `060`-downgrade die faalt na ACT-30-merges, idempotente inspector-checks die mislukte runs maskeren, inconsistent SQLite-beleid. | PostgreSQL-only verklaren; CI-stap `upgrade head && downgrade base && upgrade head`. |
| D7 | middel | Scheduler: in-process `BackgroundScheduler` zonder lock; bij `--workers N` of een tweede container draait elke job N keer. | `SCHEDULER_ENABLED`-env + PostgreSQL advisory lock in `logged_job`. |
| D8 | laag | `HouseholdFinance.purchase_costs_pct`, `selling_costs_pct`, `current_home_debt`, `existing_mortgage_pim_refund_rate` worden geschreven maar nergens gelezen; `SELL_FACTOR` (wealth_forecast) en `cashout_fee_pct` (capital_dashboard) zijn twee definities van nettowaarde (ACT-29 adresseert dit deels). | Kolommen droppen of documenteren; één `net_portfolio_value()`. |
| D9 | laag | SQLAlchemy 2.0.36 maar volledig legacy-stijl: `Column()`, 440× `db.query()`, 0× `select()`, `backref` i.p.v. `back_populates`. Geen fouten, wel geen typing. | Mechanische migratie naar `Mapped[]`/`mapped_column()` als laatste stap. |
| D10 | laag | `config.py`: losse `os.getenv`-regels, `int()` zonder vangnet, Fernet-sleutel alleen in productie gevalideerd, `BUNQ_API_BASE` ná de validatie. | `pydantic-settings` (pydantic 2 is al dependency). |

## E. Front-end: schuld die een redesign hindert

Belangrijkste conclusie: de 1.149 inline styles en 2.100 regels inline JS zijn
niet het grootste probleem op zich, maar wél dat er geen enkele gedeelde plek
is: geen `app.js`, geen `_macros.html`, geen datum-filter. Elk patroon bestaat
in 3-8 varianten. Een redesign moet daardoor 65 templates afzonderlijk aanraken.

| # | Bevinding | Cijfers | Voorstel |
|---|---|---|---|
| E1 | Kapotte tokens en klassen | `--gold` (11×), `--navy` (2), `--navy-mid` (4), `--muted-border` (7), `--card-bg` (2) worden gebruikt maar zijn nergens gedefinieerd (renderen als `initial`). `alert-danger` (9×), `alert-info` (6×), `btn-secondary` (9×), `data-table`, `card-header`, `text-center` e.a. bestaan niet in style.css. | Definiëren of hernoemen. Klein, direct zichtbaar effect. |
| E2 | Twee tokenfamilies | `--bg/--surface/--orange/...` (794 gebruiken) naast `--ctp-*` (89 gebruiken); 9 ongebruikte variabelen; 48 inline hex-kleuren die dark mode negeren; 31 hex-regels in CSS buiten de tokenblokken. | Eén familie kiezen, de andere tijdelijk aliassen; hex → tokens. |
| E3 | Geen gedeeld JS | 6 implementaties van bedragformattering (4 uitkomsten), `toggleEdit` 3×, startsaldo-bewerking 2×, modal-sluiten 2×, 10 `fetch()`-aanroepen met eigen foutafhandeling, Chart.js 4× geladen met 3 versie-aanduidingen (2× ongepind, 0× `integrity`). Theme/drawer-script inline in base.html. | `app/static/js/app.js` (thema, drawer, `formatEuro`, `escapeHtml`, `fetchJson`, modal, `toggleEdit`); Chart.js één gepinde URL met SRI in `{% block vendor %}`. |
| E4 | Geen macro's/filters | Lege staat 18× uitgeschreven, flash-kaart met hex-kleuren 23×, inline delete-form met `confirm()` 53×, sectiekop 11×, jaar/maand-select 14×, `"%.2f"\|format\|replace` 31× naast `\|euro` 186×; datums met 9 `strftime`-varianten; `&euro;` 141× naast `€` 95×. | `templates/_macros.html` (`empty_state`, `flash`, `inline_action_form`, `section_title`, `year_month_select`, `page_header`, `tx_table_head`); filters `\|date`, `\|datetime`, `\|euro_sign`. |
| E5 | Inline styles | Top: scenario_detail 99, rules/list 93, recurring/list 83, savings/detail 81, portfolio/index 80. Top-20 declaraties (`display:flex` 119, `margin-bottom:1rem` 84, `align-items:center` 66, ...) dekken ~60-70%. | ~15 utility-classes; per map omzetten; 27 dynamische styles als custom properties laten. |
| E6 | Structuur | `landing/terms/privacy` omzeilen base.html met gekopieerde nav-CSS en zonder cache-busting; terms en privacy hebben byte-identieke `<style>`-blokken; 12 templates zetten scripts in `content` i.p.v. `{% block scripts %}`; sub-navigatie 2× uitgeschreven in base.html (desktop + drawer). | `base_public.html`; één `{% block scripts %}`; nav-items als lijst in `template_config`. |
| E7 | Dode CSS | 42 van 288 selectors komen in geen template voor (`.inbox-card*` 17 selectors, `.period-*`, `.cell-*` met 7 `!important`, `.cat-*`); 13 `!important` waarvan 9 in dode selectors; 8 verschillende breakpoints (1100/960/768/680/560/520/480). | ~150-200 regels verwijderen; 3 vaste breakpoints. |
| E8 | Toegankelijkheid | 0× `scope` op 295 `<th>`, 11 tabellen zonder `<thead>`, ~19 inputs zonder label/`aria-label`, 2× `<a href="#" onclick>`, modals zonder `role="dialog"`/focus-trap, `outline:none` zonder vervanging op `.cell-input:focus`. Goed: globale `:focus-visible`, aria op drawer, alle `<img>` met `alt`. | Via de macro's (E4) in één keer goed; rest in het redesign. |

## F. Tests, CI en infra

| # | Ernst | Bevinding | Voorstel |
|---|---|---|---|
| F1 | hoog | Testfundament: 41 testbestanden zetten elk `DATABASE_URL` op moduleniveau vóór `import app`, maar de engine wordt één keer gemaakt bij de eerste import. In een volledige run wint alfabetisch het eerste bestand; alle 512 tests delen één SQLite-bestand. Werkt omdat elke module `drop_all` doet, maar is volgorde-afhankelijk. 23 varianten van `db_session` met handmatige delete-volgorde; 21× `_make_user`; 41 tempfiles die nooit worden opgeruimd. Geen `conftest.py`, geen `pyproject.toml`. | Eén `tests/conftest.py`: env vóór app-import, één engine, per test transactie + rollback, fixtures `user/admin/account/client/auth_client`, scheduler gemonkeypatcht, `PRAGMA foreign_keys=ON`. Mechanisch, gedragsneutraal. |
| F2 | hoog | Dekkingsgaten: `rules_engine.py`, `ai_suggest.py`, `email_service.py`, `rate_limit.py`, `parsers/ing.py`, `parsers/rabobank.py`, `parsers/ics_pdf.py` hebben geen test; routers `analytics`, `rules`, `transactions` (2 hits), `dashboard` (1), `auth` (alleen `/login`), `budgets` (2), `categories` (2) nauwelijks. Precies de schermen die een redesign raakt. | Happy-path HTTP-tests voor die routes vóór het redesign, als vangnet. |
| F3 | hoog | [deploy.yml:7](../.github/workflows/deploy.yml#L7): `paths-ignore: '**.md'` sluit ook `app/docs/**/*.md` uit, en dat zijn runtime-bestanden van de kennisbank (`info_loader.py:20`). Een wijziging aan alleen die docs wordt niet gedeployd. | `'*.md'`, `'docs/**'`, `'.claude/**'`. |
| F4 | middel | CI draait alleen op `pull_request`; deploy op elke push naar main zonder CI-gate, zonder `concurrency` (ACT-14 "voorkom overlappende deployments" is niet afgedwongen), geen `permissions`, geen `timeout-minutes`. | CI ook op `push: main`; `concurrency: deploy-main`; branch protection met required checks. |
| F5 | middel | `.env.example` mist 13 van 20 sleutels (waaronder de verplichte `DATABASE_URL` en `FIELD_ENCRYPTION_KEY`), bevat ongebruikte `POSTGRES_*`, `APP_PORT=8100` vs nginx-default 8368; compose mist `BUNQ_API_BASE`, `SESSION_MAX_AGE`, `CSRF_ENFORCE`, `LOG_LEVEL` (sandbox-omschakeling is in productie dus onmogelijk). | Herschrijven; vier compose-regels toevoegen; `SECRET_KEY`-default weghalen. |
| F6 | middel | Repo-hygiëne: `Wissellijst` is een gitlink (mode 160000) zonder `.gitmodules` sinds april (kapotte submodule); `.DS_Store` 2× getrackt; `deploy.sh`, `scripts/deploy-to-synology.sh` en `make init-env` beschrijven een flow (`compose up --build`, poort 8100, ssh+git pull) die niet meer bestaat; `.gitignore` is een 200-regelig generiek template met dode regels voor al getrackte logo's; `AGENTS.md` = `CLAUDE.md`. | `git rm --cached`; scripts verwijderen; `.gitignore` inkorten; `.dockerignore` aanvullen (`docs/`, `*.db`, `.DS_Store`). |
| F7 | middel | Docs verouderd: OPERATIONS.md zegt nog "stack.env wordt gevolgd (ACT-08)", "releaseversies gepland in ACT-14", "PostgreSQL-controles volgen in ACT-03"; allemaal afgerond. | Eén docs-PR. |
| F8 | middel | Dependencies: directe pins uit dec 2024/jan 2025 (`fastapi 0.115.6`, `starlette 0.41.3`, `sqlalchemy 2.0.36`, `requests 2.32.3`, `jinja2 3.1.5`, `cryptography 43.0.3`, `pdfminer-six 20231228`) terwijl transitieve packages op sept 2026 staan. Starlette 0.41 mist o.a. de multipart-DoS-fix (0.47.2); requests 2.32.4 fixte een netrc-lek. Niet offline geverifieerd tegen advisories. Let op: Starlette ≥1.0 vereist eerst C1. | Na C1 één geplande `uv pip compile --upgrade`-ronde met volledige suite en handmatige check van upload/login/PDF-import; daarna `dependabot.yml`. |
| F9 | laag | Geen linter/formatter, geen coverage, geen `pyproject.toml`. | `pyproject.toml` met `[tool.ruff]` (`E,F,I,B,UP`, py312, line-length 120, `alembic/versions` uitgesloten) en `[tool.pytest.ini_options]`; `ruff check` + `ruff format --check` als CI-stap; `pytest-cov` zonder drempel; `Makefile` met `test/lint/fmt/check`. Geen pre-commit, geen mypy (nu). |

## G. Voorgestelde volgorde

Elke regel is één PR met één samenhangend doel, conform WORKFLOW.md. Fase 1 en 2
zijn gedragsfixes en hygiëne; fase 3 is de structurele basis; fase 4 is het
front-end-fundament dat direct vóór het redesign moet liggen. Voorgestelde
actie-ID's sluiten aan op ACTIEPLAN.md (ACT-31 is de laatste).

**Fase 1 — bugs en beveiliging (klein, direct mergebaar)**

| PR | Inhoud | Bevindingen |
|---|---|---|
| ACT-32 | Encryptie-bugs: duplicatenpagina en regelsuggesties in Python groeperen, `encrypt_existing_transactions` repareren, read-path fail-closed; tests met sleutel aan. | A1, A2, A3, B11 |
| ACT-33 | Auth-fixes: invite pas na validatie consumeren, `email_verified`, rate limiting op register/forgot/reset, `--proxy-headers`, logout via POST, e-mailnormalisatie, `html.escape` in mails, `delete-all-transactions` weg. | A5, B1, B2, B3, B6, B7, B8, B10 |
| ACT-34 | Crash- en datafouten: `delete_category` FK-veilig, scheduler-return, timeouts in enable_banking, savings-filters op projected/excluded, `budget_from_average`, `Rule.name[:100]`, URL-encoding, transfer/split-randgevallen, merge-categorieconflict in preview, `app/forms.py` voor formulierparsing, `safe_redirect`. | A4, A6, A7, A8, A9, A10, A11, A12, A13, A14, A15, B9 |
| ACT-35 | XSS in templates: `tojson` i.p.v. `\|safe`, `textContent` in savings/detail, Jinja-waarden niet in JS-literals. | B4, B5 |

**Fase 2 — hygiëne en tooling (geen gedragswijziging)**

| PR | Inhoud | Bevindingen |
|---|---|---|
| ACT-36 | Repo-hygiëne: `Wissellijst`, `.DS_Store`, dode deploy-scripts, `.gitignore`/`.dockerignore`, verouderde docs-zinnen, `.env.example` volledig, compose-variabelen, `deploy.yml` paths-ignore + concurrency, CI op push naar main. Daarna branch protection (handmatig). | F3, F4, F5, F6, F7, B13 |
| ACT-37 | Tooling: `pyproject.toml` (ruff + pytest), `ruff`/`pytest-cov` in dev-lock, lint-stap in CI, `Makefile`, `dependabot.yml`; eerste `ruff --fix` voor `F401/I/UP` als aparte commit; dode code uit C14. | F9, C14 |
| ACT-38 | Verouderde API's: 118× `TemplateResponse(request, ...)`, `lifespan`, `app/clock.py` met `now_utc()`/`today_nl()` en alle `utcnow`/`today`-plekken, inbox-middleware beperken. Scheelt ~2.900 waarschuwingen en ontgrendelt de dependency-upgrade. | C1, C2, B12 |
| ACT-39 | Testfundament: `tests/conftest.py`, fixtures, rollback per test, `PRAGMA foreign_keys=ON`; de 41 module-headers en 23 `db_session`-varianten vervangen. Eventueel in twee stappen. | F1 |
| ACT-40 | Dependency-upgrade: `uv pip compile --upgrade`, volledige suite, handmatige check upload/login/PDF. Pas na ACT-38. | F8 |

**Fase 3 — structuur (backend)**

| PR | Inhoud | Bevindingen |
|---|---|---|
| ACT-41 | Schema-hygiëne, één migratie (eerstvolgende vrije nummer; 067/068 zijn bezet door bunq): indexes, partiële unique op categorieën, cascades/`passive_deletes`, `server_default`s, dode `HouseholdFinance`-kolommen; drift-test; CI-stap up/down/up. | D1, D2, D3, D4, D6, D8 |
| ACT-42 | Transactiegrenzen en banksync: `app/bank_sync.py` gedeeld door router en scheduler, "service flusht, caller commit", projectie-sync weg uit GET, router-imports uit scheduler, advisory lock + `SCHEDULER_ENABLED`, jobconfig. Meeste gedragsrisico; aparte integratietest. | C5, C6, C7, D7 |
| ACT-43 | Gedeelde helpers en conventies: `is_super_admin`/`require_admin`/`require_feature`, `app/nl_format.py`, `transaction_years()`, foutafhandelingsconventie in WORKFLOW.md en per router toepassen, `/settings/*` uit auth.py naar settings.py, `ai_client.py`. | C3, C4, C13 |
| ACT-44 | Savings-service en N+1: `running_balances`, `schedule_from_form`, legacy status weg, dode route weg, `get_or_create_subcategory` gedeeld met categories. | C9, C12 (deel) |
| ACT-45 | Recurring/transactions: periode-batching, `resync_after_import`, `classify_items`, `parsers/custom_csv.py`, overige N+1's; `transaction_list` en `_render_recurring_page` elk <100 regels. | C10, C12 |
| ACT-46 | Mortgage en lange functies: `ScenarioForm`, `_render_rates`, `scenario_view_model`, `budget_overview`/`import_confirm`/`portfolio_overview` opknippen. | C8, C11 |

**Fase 4 — front-end-fundament (direct vóór het redesign)**

| PR | Inhoud | Bevindingen |
|---|---|---|
| ACT-47 | Kapotte tokens/klassen definiëren; dode CSS en ongebruikte variabelen weg; één tokenfamilie; hex → tokens; `base_public.html`; Google Fonts via `<link>`; 3 breakpoints. | E1, E2, E6, E7 |
| ACT-48 | `app/static/js/app.js` + Chart.js gepind met SRI; inline blokken naar `{% block scripts %}`. | E3 |
| ACT-49 | `_macros.html` en filters `date`/`datetime`/`euro_sign`; de 18 lege staten, 23 flash-kaarten, 53 inline forms, 14 selectors en 31 handmatige bedragformats vervangen; toegankelijkheid (labels, `scope`, `<button>`, `role=dialog`) in de macro's. | E4, E8 |
| ACT-50 | Inline styles naar utility-classes, per map (mortgage, rules, recurring, savings, portfolio, budgets, transactions); eventueel in sub-PR's. | E5 |
| ACT-51 | Happy-path HTTP-tests voor transactions, analytics, rules, budgets, categories, dashboard en parsers ing/rabobank/ics_pdf, als vangnet voor template-werk. Kan parallel aan fase 3. | F2 |
| ACT-52 | Model-typing (laatste, mechanisch): `Boolean`-kolommen, enums met `CheckConstraint`, `JSON` voor `accounts_json`, `Mapped[]`/`mapped_column`, `pydantic-settings`. | D5, D9, D10 |

Fase 1 past in een dag of twee werk per PR; fase 2 is mechanisch; fase 3 en 4
zijn elk meerdere dagen. ACT-39 (testfundament) en ACT-51 (vangnet) zijn de
investeringen die alle latere PR's goedkoper en veiliger maken.

## Bijwerking na schrijven (14 oktober 2026)

- **A12 is opgelost** in PR #211 (samenvoegen vouwt gelijknamige categorieën samen); haal A12 uit ACT-34.
- **B13 is opgelost:** `main` vereist de checks `test` en `postgres-migrations` en auto-merge staat aan (nog zonder `concurrency` op de deploy-job, dat blijft in ACT-36).
- **Migratienummers:** 067 en 068 zijn bezet door de bunq-koppeling; de migratie van ACT-41 krijgt het eerstvolgende vrije nummer.
- **Actie-ID's:** de persoonspagina uit het gesprek is ACT-53 (niet ACT-32).
- **bunq-code** (app/bunq_*.py, app/transfer_linking.py, routers/bunq.py) is ná de review geschreven en is er niet in beoordeeld.

## H. Methode en beperkingen

- **H1 Lokale omgeving.** De `.venv` in de repo-root draait Python 3.14.3 met
  FastAPI 0.135 en Starlette 1.0 (niet de locks). Daarin falen 138 tests, allemaal
  op de `TemplateResponse`-signatuur (C1). ACTIEPLAN noemt lokale runs op 3.14 met
  groene uitslag; de venv is sindsdien kennelijk opgewaardeerd. Gebruik voor lokale
  runs een omgeving uit de locks, bijvoorbeeld `uv venv --python 3.12` en
  `uv pip install -r requirements-dev.txt`; daarmee: 512 geslaagd, 3 overgeslagen.
- **H2 Werkwijze.** Vijf parallelle deelreviews (grote routers; overige routers
  en auth; services, modellen en migraties; templates, CSS en JS; tests, CI en
  infra) plus eigen scans met ruff 0.17, vulture 2.16 en grep. Alle bevindingen
  met ernst hoog in A, B en F en de encryptie-, scheduler-, deploy- en
  testfundamentclaims zijn door mij opnieuw tegen de code gecontroleerd; de
  overige bevindingen zijn door de deelreviews aan de code geverifieerd en
  steekproefsgewijs door mij.
- **H3 Niet gecontroleerd.** Productieconfiguratie, Portainer, nginx-headers op
  de Synology, en dependency-advisories (offline). Regelnummers gelden voor commit
  `339a4d8`.
- **H4 Niet gedaan.** Geen code gewijzigd, geen ACTIEPLAN-items toegevoegd. De
  actie-ID's hierboven zijn voorstellen.
