# Check The Pockets - Product Backlog

Backlog gebaseerd op feature-analyse van [Lunch Money](https://lunchmoney.app/features), afgezet tegen de huidige staat van Check The Pockets.

---

## Huidige staat (al geïmplementeerd)

- Gebruikersregistratie en login (sessie-gebaseerd, bcrypt)
- Rekeningbeheer (aanmaken/verwijderen, IBAN, meerdere banken)
- CSV-import voor ABN AMRO, Bunq en ICS
- Duplicaatdetectie bij import (SHA256 hash)
- Transactie-overzicht met paginering en filtering per rekening
- Responsieve UI met eigen design system

---

## Epic 1: Categorieën & Transactiebeheer

> Fundament voor budgettering en analyse. Moet als eerste gebouwd worden.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 1.1 | Als gebruiker wil ik categorieën kunnen aanmaken, bewerken en verwijderen zodat ik mijn uitgaven kan ordenen | Must Have |
| 1.2 | Als gebruiker wil ik categorieën kunnen groeperen (bijv. "Vaste lasten" > "Huur", "Gas/Water/Licht") zodat ik overzicht houd | Must Have |
| 1.3 | Als gebruiker wil ik een transactie aan een categorie kunnen toewijzen | Must Have |
| 1.4 | Als gebruiker wil ik een transactie kunnen splitsen over meerdere categorieën (bijv. Albert Heijn: 80% boodschappen, 20% huishouden) | Should Have |
| 1.5 | Als gebruiker wil ik transacties kunnen taggen met vrije labels zodat ik ze flexibel kan groeperen | Should Have |
| 1.6 | Als gebruiker wil ik transacties handmatig kunnen invoeren voor contante uitgaven of correcties | Should Have |
| 1.7 | Als gebruiker wil ik transacties kunnen bewerken (omschrijving, categorie, tags) | Must Have |
| 1.8 | Als gebruiker wil ik transacties kunnen groeperen (bijv. losse Tikkie-betalingen samenvoegen) | Could Have |
| 1.9 | Als gebruiker wil ik transacties kunnen doorzoeken en filteren op datum, bedrag, categorie, tag en tegenrekening | Must Have |

---

## Epic 2: Budget

> Kernfunctionaliteit: budgetteren per categorie met flexibele periodes.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 2.1 | Als gebruiker wil ik een maandbudget kunnen instellen per categorie | Must Have |
| 2.2 | Als gebruiker wil ik mijn budget-periode kunnen kiezen (wekelijks, tweewekelijks, maandelijks, custom startdatum) | Should Have |
| 2.3 | Als gebruiker wil ik zien hoeveel ik per categorie heb uitgegeven vs. gebudgetteerd | Must Have |
| 2.4 | Als gebruiker wil ik een zero-based budget view waarin ik zie hoeveel inkomen nog niet is toegewezen | Should Have |
| 2.5 | Als gebruiker wil ik per categorie kunnen kiezen wat er met het restant gebeurt (rollover naar volgende maand of terug naar pot) | Should Have |
| 2.6 | Als gebruiker wil ik snel budgetten kunnen instellen op basis van vorige maand of gemiddelde van 3 maanden | Could Have |
| 2.7 | Als gebruiker wil ik historische budgetten kunnen terugkijken (plan vs. werkelijk) | Could Have |

---

## Epic 3: Dashboard & Overzicht

> Visueel inzicht in je financiële situatie.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 3.1 | Als gebruiker wil ik een dashboard zien met inkomsten, uitgaven en netto resultaat voor de huidige periode | Must Have |
| 3.2 | Als gebruiker wil ik een spaarquote zien ((Inkomen - Uitgaven) / Inkomen × 100%) | Should Have |
| 3.3 | Als gebruiker wil ik een spending breakdown per categorie zien met visuele balken | Must Have |
| 3.4 | Als gebruiker wil ik de periode kunnen kiezen (maand tot nu, jaar tot nu, custom datumbereik) | Must Have |
| 3.5 | Als gebruiker wil ik projecties zien van verwachte inkomsten en uitgaven op basis van terugkerende posten | Could Have |

---

## Epic 4: Terugkerende Transacties

> Vaste lasten en inkomsten bijhouden en projecteren.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 4.1 | Als gebruiker wil ik terugkerende posten kunnen aanmaken (huur, salaris, abonnementen) met frequentie (maandelijks/jaarlijks/wekelijks) | Must Have |
| 4.2 | Als gebruiker wil ik zien welke terugkerende posten deze periode al zijn afgeschreven en welke nog verwacht worden | Must Have |
| 4.3 | Als gebruiker wil ik dat inkomende transacties automatisch worden gekoppeld aan terugkerende posten | Should Have |
| 4.4 | Als gebruiker wil ik een overzicht van al mijn vaste lasten en vaste inkomsten | Must Have |

---

## Epic 5: Rules Engine (Automatisering)

> Transacties automatisch categoriseren en labelen.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 5.1 | Als gebruiker wil ik regels kunnen aanmaken die transacties automatisch categoriseren op basis van tegenpartij, omschrijving of bedrag | Must Have |
| 5.2 | Als gebruiker wil ik dat het systeem regels voorstelt op basis van mijn categoriseergedrag | Should Have |
| 5.3 | Als gebruiker wil ik regels kunnen beheren (aan/uit, bewerken, verwijderen) | Must Have |
| 5.4 | Als gebruiker wil ik dat regels ook tags en terugkerende posten kunnen toewijzen | Could Have |
| 5.5 | Als gebruiker wil ik dat regels worden toegepast bij import én achteraf op bestaande transacties | Should Have |

---

## Epic 6: Analytics & Inzichten

> Trends en patronen herkennen in je financiën.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 6.1 | Als gebruiker wil ik trends zien in mijn uitgaven per categorie over meerdere maanden | Should Have |
| 6.2 | Als gebruiker wil ik grafieken zien (staaf, lijn) van mijn inkomsten vs. uitgaven over tijd | Should Have |
| 6.3 | Als gebruiker wil ik een query-tool waarmee ik geavanceerde vragen kan stellen aan mijn transactiedata | Could Have |
| 6.4 | Als gebruiker wil ik inzichten krijgen in veranderingen in mijn bestedingspatroon t.o.v. vorige periodes | Could Have |

---

## Epic 7: Vermogenstracker (Net Worth)

> Lange-termijn financieel overzicht.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 7.1 | Als gebruiker wil ik assets kunnen toevoegen (spaargeld, beleggingen, vastgoed) met actuele waarde | Should Have |
| 7.2 | Als gebruiker wil ik schulden/leningen kunnen bijhouden | Should Have |
| 7.3 | Als gebruiker wil ik mijn netto vermogen over tijd in een grafiek zien | Should Have |
| 7.4 | Als gebruiker wil ik zien hoe mijn vermogen verandert als ik mijn uitgaven verlaag | Could Have |

---

## Epic 8: Multi-Valuta

> Relevant voor internationale gebruikers en beleggingen.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 8.1 | Als gebruiker wil ik transacties in andere valuta's kunnen importeren en bekijken | Could Have |
| 8.2 | Als gebruiker wil ik een thuisvaluta instellen en alles omgerekend zien | Could Have |
| 8.3 | Als gebruiker wil ik actuele wisselkoersen zien bij omrekening | Could Have |

---

## Epic 9: Samenwerking

> Gedeeld huishoudboekje.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 9.1 | Als gebruiker wil ik anderen kunnen uitnodigen om mijn budget mee te beheren | Could Have |
| 9.2 | Als medegebruiker wil ik transacties kunnen toevoegen en categoriseren | Could Have |

---

## Epic 10: Beveiliging & Account

> Extra beveiligingslagen.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 10.1 | Als gebruiker wil ik twee-factor authenticatie (TOTP) kunnen inschakelen | Should Have |
| 10.2 | Als gebruiker wil ik mijn wachtwoord kunnen wijzigen | Must Have |
| 10.3 | Als gebruiker wil ik mijn account en alle data kunnen verwijderen | Should Have |

---

## Epic 11: API & Integraties

> Voor power users en uitbreidbaarheid.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 11.1 | Als gebruiker wil ik een REST API om mijn transacties en budgetten programmatisch te benaderen | Could Have |
| 11.2 | Als ontwikkelaar wil ik API-documentatie zodat ik eigen tools kan bouwen | Could Have |
| 11.3 | Als gebruiker wil ik meer bankformaten kunnen importeren (Rabobank, ING, ASN, Knab) | Should Have |

---

## Epic 12: Kalender & Notificaties

> Financieel overzicht in de tijd.

| # | User Story | Prioriteit |
|---|-----------|------------|
| 12.1 | Als gebruiker wil ik een kalenderweergave van mijn transacties | Could Have |
| 12.2 | Als gebruiker wil ik notificaties als ik boven mijn budget dreig te komen | Could Have |

---

## Voorgestelde ontwikkelvolgorde

De epics zijn geordend op afhankelijkheid en waarde:

1. **Epic 1: Categorieën & Transactiebeheer** - Fundament voor alles
2. **Epic 5: Rules Engine** - Maakt categoriseren schalenbaar
3. **Epic 2: Budget** - Kernwaarde van de app
4. **Epic 4: Terugkerende Transacties** - Nodig voor projecties
5. **Epic 3: Dashboard & Overzicht** - Alles samengebracht
6. **Epic 10: Beveiliging & Account** - Basisbeveiliging
7. **Epic 6: Analytics & Inzichten** - Extra waarde
8. **Epic 7: Vermogenstracker** - Lange termijn
9. **Epic 11: API & Integraties** - Extra bankparsers
10. **Epic 8: Multi-Valuta** - Nice to have
11. **Epic 9: Samenwerking** - Nice to have
12. **Epic 12: Kalender & Notificaties** - Nice to have
