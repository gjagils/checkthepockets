# Samenwerken aan Checkthepockets

## Eén bron voor werk en voortgang

Lees bij iedere sessie dit document en [ACTIEPLAN.md](../ACTIEPLAN.md).
Deze afspraken gelden voor iedere bijdrager, waaronder Codex en Claude Code.
Het actieplan in Git is de centrale bron voor beschrijving, prioriteit, status,
acceptatiecriteria, besluiten en overdracht. Chatgeschiedenis, Linear, MCP,
plugins, persoonlijke skills en lokale agentinstellingen zijn niet vereist.
Bestaande Linear-issues zijn niet automatisch gemigreerd: neem relevante issues
alleen op na controle op overlap, met een verwijzing naar hun oorspronkelijke ID.
`BACKLOG.md` blijft een historisch archief en krijgt geen nieuwe acties.

Deze werkwijze vervangt de eerdere Linear-routine en agentgebonden ready-labels.
Ook als een oude lokale skill anders zegt, gebruik je voor dit verbeterprogramma
de repositorydocumenten. Een lijst geplande acties is geen opdracht om ze allemaal
uit te voeren. Een expliciete gebruikersopdracht bepaalt de vrijgegeven scope.

## Starten en een actie kiezen

1. Lees het actieplan, inclusief overdracht en besluitenlog.
2. Controleer `git status`, huidige branch, recente commits en eventuele open PRs.
   Bewaar wijzigingen van anderen; reset of stash ze niet zonder aanleiding.
3. Werk aan de expliciet gevraagde actie, of bij een vrijgegeven backlog-run aan
   de eerste `Gereed`-actie waarvan de afhankelijkheden `Afgerond` zijn.
   Sorteer op P1 vóór P2 vóór P3, daarna op actie-ID.
4. Controleer of iemand de actie al uitvoert. Neem geen tweede implementatie over
   dezelfde actie aan. Een andere agentnaam geeft geen extra bevoegdheden.
5. Zet de actie op `Bezig` en noteer uitvoerder, datum en branch in de overdracht.
   Begin vanaf bijgewerkte `main` in een schone checkout, of hervat de genoemde
   bestaande branch. Gebruik een afzonderlijke worktree bij ander lokaal werk.
6. Gebruik voor nieuwe branches standaard `codex/<actie-id>-<slug>` conform de
   repositoryconventie; de naam beperkt gebruik door Claude Code niet.

## Budgetcontrole vóór iedere actie

De gebruiker heeft op 2026-09-23 uitvoering vrijgegeven onder deze voorwaarden:

- Controleer vóór iedere nieuwe actie het actuele resterende gebruikstegoed via
  de beschikbare account-/usage-weergave van de gebruikte agent. Dit kan via UI
  of een beschikbare tool; geen specifieke connector is vereist.
- Noteer bron, datum en resterende limieten in de overdracht. Percentages zijn
  geen exacte tokenbudgetten en kunnen door andere sessies veranderen.
- Schat uitvoering, tests, mogelijke herstelronde, CI, merge en statusregistratie
  samen in. Reserveer minstens een derde van de beschikbare ruimte voor
  verificatie en afronding; dit is een werkafspraak, geen garantie op verbruik.
- Start alleen één afgebakende actie die naar redelijke inschatting past. Splits
  een te grote actie vóór de start in zelfstandig afrondbare subacties, met eigen
  acceptatiecriteria. Het bovenliggende werk blijft open tot alle criteria gelden.
- Bij onvoldoende of onbekend tegoed: start geen nieuwe implementatie. Laat de
  actie Gereed en leg vast waarom er gewacht wordt. Verbruik geen resetcredit
  en koop geen tegoed zonder expliciete toestemming.
- Controleer opnieuw vóór een volgende actie. Rond eerst de lopende actie af,
  inclusief geverifieerde merge en registratie als Afgerond. Bij een onverwachte
  blokkade leg je de werkelijkheid vast; nooit tests overslaan of werk ten
  onrechte afronden om binnen een limiet te blijven.

## Uitvoering en toetsing

- Houd één samenhangende actie per PR aan; splits omvangrijk werk in subacties
  met eigen criteria voordat je het implementeert.
- Lees eerst de betrokken code. Voeg passende regressietests toe voor fouten,
  gegevensintegriteit en beveiliging. Voor uitsluitend documentatie volstaan
  linkcontrole en `git diff --check`.
- Gebruik de Python-versie uit `.github/workflows/ci.yml` (bij opstellen: 3.12)
  en de dependencies uit de repository. Leg afwijkende omgevingen vast.
- De bestaande testopdracht is `python -m pytest tests/ --tb=short`.
  Dit is nog geen garantie van reproduceerbaarheid: daarvoor bestaat ACT-01.
- Leg testopdrachten, uitslag en beperkingen in de overdracht vast. Presenteer
  een lokale fout met afwijkende dependencies niet als bewezen productiefout.
- Houd geheimen, bankgegevens en productie-dumps buiten Git, PRs en logs.
- Werk status, relevante besluiten en overdracht in dezelfde branch bij.
  Stage alleen bestanden die bij de actie horen, niet blind `git add .`.
- Commit volgens Conventional Commits, bijvoorbeeld
  `fix: begrens importherkenning per rekening (ACT-09)`.
- Een PR noemt actie-ID, probleem, resulterend gedrag, gewijzigde onderdelen,
  validatie en eventuele migratie- of herstelstappen. Gebruik geen `Closes ACT-09`:
  actie-ID's zijn documentreferenties, geen GitHub-issuenummers.

## Review en afronden

Voor vrijgegeven implementatiewerk blijft squash-merge na groene PR-CI toegestaan,
behalve bij `needs-review` of een expliciet verzoek om eerst te reviewen.
Verwijder na merge de werkbranch, behalve als die nog voor overdracht nodig is.
Zonder PR-CI mag uitsluitend een triviale veilige wijziging van maximaal 50 regels
in Markdown of statische assets automatisch worden gemerged; nooit runtimecode,
migraties, workflows, composebestanden of geheimen. Anders: `Review`.
Een deployment wordt afzonderlijk geverifieerd; groene tests bewijzen geen gezonde
productieomgeving. Zie [OPERATIONS.md](OPERATIONS.md).

Stop de betreffende implementatie bij onduidelijke criteria, niet-uitvoerbare
vereiste tests, niet-triviale mergeconflicten of twee mislukte CI-pushes. Leg oorzaak,
PR/CI-link en de eerstvolgende stap vast als `Geblokkeerd` of `Review`.
Een grote diff is reden om werk op te splitsen, geen bewijs van onveiligheid.
Ga uitsluitend verder met andere acties als ook die zijn vrijgegeven.

Markeer pas `Afgerond` nadat de criteria aantoonbaar gehaald en de PR gemerged zijn.
Zet de actie vóór merge op `Review`; werk de centrale status na de geverifieerde
merge bij in een opvolgende documentatiecommit/PR. Noteer bij runtimewijzigingen
ook deploymentbewijs of expliciet dat productievalidatie nog openstaat.

## Wisselen tussen agents of machines

Een overdracht bevat minimaal actie-ID, status, uitvoerder, datum, branch, PR-link
(indien beschikbaar), uitgevoerde stappen, testresultaten, open vragen en één
concrete volgende stap. Leg alleen informatie vast die de opvolger nodig heeft.
Commit en push de werkbranch met de overdracht voordat je op een andere machine
verdergaat. Als push niet kan, meld expliciet dat het werk alleen lokaal staat.
Een WIP-commit mag onvolledig werk bevatten mits tests en beperkingen zijn vermeld.

De opvolger haalt de remote branch op en vervolgt daarop; hij begint niet opnieuw
vanaf `main`. Controleer eerst dat de vorige uitvoerder gestopt is. Draai twee
agents niet gelijktijdig op dezelfde actie of checkout. Onafhankelijke acties
kunnen in aparte branches, maar statusconflicten moeten bewust worden opgelost.

Dezelfde startopdracht werkt in iedere coding-agent:

> Lees AGENTS.md, docs/WORKFLOW.md en ACTIEPLAN.md. Hervat de actie uit de
> overdracht. Als er geen actieve actie is, voer alleen de eerste vrijgegeven
> Gereed-actie uit. Werk het actieplan en de overdracht bij met testresultaten.

Git en Markdown zijn voldoende voor planning en overdracht. Voor codewerk blijven
Python/dependencies nodig; voor publicatie zijn GitHub-toegang en voor deployment
de bestaande infrastructuur vereist. De GitHub CLI is optioneel: dezelfde PR- en
CI-handelingen kunnen via de GitHub-webinterface.
