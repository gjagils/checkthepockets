# CLAUDE.md — CI/CD & Deployment Instructies

## Overzicht

Dit project gebruikt een geautomatiseerde CI/CD pipeline:

```
Claude Code → GitHub (push/merge) → GitHub Actions (build & push image) → Portainer webhook → Synology Docker update
```

## Architectuur

- **Code:** GitHub repository
- **Container Registry:** GitHub Container Registry (ghcr.io)
- **CI/CD:** GitHub Actions (build on merge to main)
- **Orchestratie:** Portainer stacks op Synology NAS
- **Runtime:** Docker op Synology

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
docker pull ghcr.io/gjagils/checkthepockets:latest
docker login ghcr.io
```

### GitHub Actions faalt

- Check of GITHUB_TOKEN permissions `packages: write` heeft (staat in de workflow)
- Check of de Dockerfile geldig is: `docker build -t test .`

### Portainer webhook werkt niet

- Check of de webhook URL correct is in GitHub secrets
- Test handmatig: `curl -X POST "<WEBHOOK_URL>"`
- Check Portainer logs

### Container start niet

```bash
docker logs checkthepockets
docker inspect ghcr.io/gjagils/checkthepockets:latest
```
