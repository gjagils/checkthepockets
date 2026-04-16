# CLAUDE.md — CI/CD & Deployment Instructies

## Overzicht

Dit project gebruikt een geautomatiseerde CI/CD pipeline:

```
Claude Code → GitHub (push/merge) → GitHub Actions (build & push image) → Tailscale → Portainer API → Synology Docker update
```

## Architectuur

- **Code:** GitHub repository
- **Container Registry:** GitHub Container Registry (ghcr.io)
- **CI/CD:** GitHub Actions (build on merge to main)
- **Netwerk:** Tailscale (GitHub Actions runner joins tailnet om Synology te bereiken)
- **Orchestratie:** Portainer stacks op Synology NAS (Community Edition)
- **Runtime:** Docker op Synology

## Vereisten per repository

### 1. Dockerfile

Elke repository MOET een Dockerfile in de root hebben.

### 2. GitHub Actions workflow

Kopieer `.github/workflows/deploy.yml` naar elke nieuwe repository. De workflow:
1. Bouwt het Docker image
2. Pusht naar ghcr.io
3. Verbindt met Tailscale
4. Roept Portainer API aan om stack te redeployen met image pull

### 3. .dockerignore

Elke repository moet een `.dockerignore` hebben met minimaal:

```
node_modules
.git
.github
.env
stack.env
*.md
__pycache__
*.pyc
.pytest_cache
tests
.venv
```

### 4. Portainer stack (docker-compose.yml)

Per project een docker-compose.yml met `image: ghcr.io/gjagils/<REPO_NAME>:latest`.

## GitHub Secrets (per repository)

| Secret | Waarde | Herbruikbaar? |
|---|---|---|
| `TAILSCALE_AUTHKEY` | Tailscale auth key (reusable + ephemeral) | Ja, zelfde voor alle repos |
| `PORTAINER_API_TOKEN` | Portainer API access token | Ja, zelfde voor alle repos |
| `PORTAINER_URL` | `http://100.65.249.84:9000` (Tailscale IP) | Ja, zelfde voor alle repos |
| `PORTAINER_STACK_ID` | Stack ID uit Portainer URL | **Nee, uniek per project** |

### Secrets instellen via CLI

```bash
# Herbruikbare secrets (zelfde voor elk project)
gh secret set TAILSCALE_AUTHKEY --body "<KEY>" --repo gjagils/<REPO>
gh secret set PORTAINER_API_TOKEN --body "<TOKEN>" --repo gjagils/<REPO>
gh secret set PORTAINER_URL --body "http://100.65.249.84:9000" --repo gjagils/<REPO>

# Uniek per project (stack ID uit Portainer URL)
gh secret set PORTAINER_STACK_ID --body "<ID>" --repo gjagils/<REPO>
```

## Setup nieuw project (checklist)

1. [ ] Dockerfile in de root
2. [ ] `.github/workflows/deploy.yml` kopiëren
3. [ ] `.dockerignore` aanmaken
4. [ ] `docker-compose.yml` maken met `image: ghcr.io/gjagils/<REPO>:latest`
5. [ ] Eerste push naar main (triggert image build op ghcr.io)
6. [ ] GitHub Packages visibility instellen (public of juiste user toevoegen)
7. [ ] Portainer stack aanmaken (noteer het stack ID uit de URL)
8. [ ] GitHub secrets instellen (4 secrets, waarvan 3 herbruikbaar)

## Setup eenmalig (al gedaan)

### GitHub Container Registry op Synology

```bash
docker login ghcr.io -u gjagils -p <GITHUB_PAT_MET_READ_PACKAGES>
```

### Tailscale auth key

Aanmaken op https://login.tailscale.com/admin/settings/keys met **Reusable** + **Ephemeral** aan.

### Portainer API token

Aanmaken in Portainer → Account → Access tokens.

## Commit conventie

Gebruik Conventional Commits:

- `feat:` — nieuwe feature
- `fix:` — bugfix
- `docs:` — documentatie
- `chore:` — onderhoud, dependencies
- `refactor:` — code refactoring

## Workflow voor Claude Code

### Nieuwe feature of bugfix

```bash
# 1. Maak een branch
git checkout -b feature/beschrijving

# 2. Maak wijzigingen en commit
git add .
git commit -m "feat: beschrijving van de wijziging"

# 3. Push en maak PR
git push -u origin feature/beschrijving
gh pr create --title "feat: beschrijving" --body "Beschrijving van de wijziging"

# 4. Merge de PR (triggert automatisch build + deploy)
gh pr merge --squash
```

## Backlog-routine (Linear → Claude Code)

Het product-backlog leeft in **Linear** (workspace `gjagils`, project `checkthepockets`). Claude Code pakt geschikte issues autonoom op — handmatig via `/backlog-routine` of automatisch via een nachtelijke Remote Trigger.

### Rollen

- **Linear** — single source of truth voor openstaande werkzaamheden.
- **`BACKLOG.md`** — historisch archief van afgeronde sprints. **Niet meer bijwerken met nieuwe items.** Blijft bestaan voor context/geschiedenis.
- **Claude Code** — implementeert, pusht, merget. Werkt alleen aan issues die jij expliciet vrijgeeft.

### Selectie-criteria

Claude pakt alleen issues op die aan **alle** onderstaande voorwaarden voldoen:

1. Project = `checkthepockets`
2. Status = `Todo`
3. Label = `claude-ready` aanwezig
4. Niet geassigneerd aan een ander persoon (geen assignee, of assignee = Claude/gjagils)

Selectie-volgorde binnen de kandidaten: **priority desc** → **createdAt asc** (oudste hoge-prio eerst). Er is **geen harde limiet** per run — Claude werkt door tot óf de kandidatenlijst leeg is, óf een run-afbreker optreedt (zie hieronder).

### Workflow per issue

```
1. Pak volgende kandidaat (Linear query)
2. Zet Linear-status op "In Progress", assignee = Claude/gjagils
3. git checkout main && git pull
4. git checkout -b feat/<LIN-ID>-<slug>
5. Implementeer + voeg/update tests waar zinvol
6. Lokaal: run tests (pytest) en smoke-check
7. git commit -m "<type>: <beschrijving> (LIN-<ID>)"
8. git push -u origin feat/<LIN-ID>-<slug>
9. gh pr create met body "Closes LIN-<ID>" + korte beschrijving
10. Wacht op CI (gh pr checks --watch, timeout 20 min)
11. Als CI groen → gh pr merge --squash --delete-branch
12. Verifieer merge → Linear-status "Done"
13. Terug naar stap 1
```

### Auto-merge regels

- **Alleen mergen als**: alle GitHub Actions checks groen, PR heeft geen review-requested labels, diff < 500 regels, niet op beschermde paths (`.github/workflows/`, `alembic/versions/`, `stack.env`, `deploy.sh`).
- **Squash-merge altijd**, branch wordt verwijderd.
- Bij groter of gevoeliger werk: zet zelf een `needs-review`-label op de Linear-issue vóór de run — dan maakt Claude wél een PR maar merged niet.

### Run-afbrekers (failure-modus)

Als één van deze gebeurt, stopt Claude en zet de issue op **"Needs review"** in Linear, met PR open:

- CI faalt na 2 pushes (geen derde retry)
- Tests kunnen lokaal niet draaien (missende dep, migratie-conflict)
- Diff overschrijdt 500 regels
- Claude komt issue tegen met onduidelijke acceptatiecriteria
- Merge-conflict met `main` die niet triviaal op te lossen is
- Issue raakt beschermde paths (zie boven)

Linear-comment bevat in dat geval: PR-link + link naar CI-logs + korte samenvatting. Andere issues in de queue worden **wél** daarna nog opgepakt (één falende issue blokkeert de rest niet).

### Handmatig triggeren

In een Claude Code sessie:

```
/backlog-routine
```

of vrije vorm:

> voer backlog routine uit

Claude doorloopt dan exact hetzelfde proces als de nachtelijke run, maar laat je wel per PR bevestigen of auto-merge gewenst is.

### Fase-plan voor activering

De routine gaat in drie fases live. Bewust gescheiden zodat je eerst bewijst dat de logica klopt vóórdat de nachtelijke automatisering aan gaat.

**Fase 1 — Handmatige CLI-test**
- Start een Claude Code sessie in deze repo
- Run: `/backlog-routine`
- Claude logt starttijd + eindtijd + verwerkte issues
- Valideer: PR(s) correct gemerged, Linear-statussen juist, geen ongewenste wijzigingen in beschermde paths
- **Resultaat:** bevestiging dat de logica werkt

**Fase 2 — Routine-test op zelfgekozen tijd**
- Maak een Remote Trigger aan met de `/backlog-routine`-prompt (kan later, als fase 1 slaagt)
- Plan 'm eenmalig op een tijdstip overdag dat je kunt monitoren (bv. 15 min in de toekomst)
- Bevestig dat cloud-run precies hetzelfde resultaat geeft als lokale run
- **Resultaat:** bevestiging dat cloud-infra werkt (Linear-auth, GitHub-push, CI-wait, merge)

**Fase 3 — Structurele nachtelijke run**
- Pas de cron-expressie van dezelfde Remote Trigger aan naar het gewenste nachttijdstip
- Richtlijn: **starttijd = later dan je laatste laptop-activiteit + lang genoeg zodat alle PRs voor ochtend klaar zijn**
- Suggestie: `37 2 * * *` (02:37 lokaal) — vermijdt het :00 kwartier waar iedereen op draait
- **Resultaat:** onbemande nachtrun, PRs zijn 's ochtends al gemerged en gedeployed

### Remote Trigger beheren

- Lijst bekijken: tijdens Claude Code sessie via de ingebouwde Remote Trigger-tooling
- Tijdelijk pauzeren: zet de trigger op disabled via claude.ai
- Schedule wijzigen: pas de cron-expressie aan in de trigger
- Let op: cron-tijd is in **UTC** op claude.ai, dus reken je lokale tijd om (CET = UTC+1, CEST = UTC+2)

### Linear label-conventies

| Label | Betekenis |
|---|---|
| `claude-ready` | Vrijgegeven voor autonome implementatie |
| `needs-review` | Claude mag PR aanmaken maar **niet** mergen |
| `blocked` | Claude slaat deze over (ook met `claude-ready`) |
| `spike` | Onderzoekstaak — Claude schrijft alleen een bevindingen-comment, geen code |

### Commit- & PR-conventie voor autonome runs

- Commit message: `<type>: <beschrijving> (LIN-<ID>)` — bv. `feat: export transacties als OFX (LIN-142)`
- PR-titel: identiek aan commit message
- PR-body bevat minimaal: `Closes LIN-<ID>`, korte samenvatting, checklist van gewijzigde files
- Type volgt bestaande conventie (`feat`, `fix`, `docs`, `chore`, `refactor`, `style`)

## Troubleshooting

### Image wordt niet gepulld op Synology

```bash
docker pull ghcr.io/gjagils/<REPO>:latest
docker login ghcr.io
```

### GitHub Actions faalt

- Check of GITHUB_TOKEN permissions `packages: write` heeft (staat in de workflow)
- Check of de Dockerfile geldig is: `docker build -t test .`

### Tailscale connect faalt

- Check of de auth key nog geldig is op https://login.tailscale.com/admin/settings/keys
- Maak eventueel een nieuwe reusable + ephemeral key aan

### Portainer API redeploy faalt

- Check of het stack ID klopt (kijk in de Portainer URL)
- Test handmatig: `curl -s -H "X-API-Key: <TOKEN>" http://100.65.249.84:9000/api/stacks/<ID>`
- Check Portainer logs

### Container start niet

```bash
docker logs <CONTAINER_NAME>
docker inspect ghcr.io/gjagils/<REPO>:latest
```
