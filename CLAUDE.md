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
