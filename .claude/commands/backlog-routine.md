---
name: backlog-routine
description: Werk de Linear-backlog af voor checkthepockets. Pakt alle issues met label 'claude-ready' + status 'Todo', implementeert, pusht, en merged autonoom na groene CI. Gebruik dit voor handmatige testruns of laat het automatisch draaien via de nachtelijke Remote Trigger.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, TodoWrite, AskUserQuestion, mcp__linear__list_issues, mcp__linear__get_issue, mcp__linear__save_issue, mcp__linear__save_comment, mcp__linear__list_comments, mcp__linear__list_issue_labels, mcp__linear__list_issue_statuses, mcp__linear__get_user, mcp__linear__list_projects
---

# Backlog-routine — Linear → Claude Code (checkthepockets)

Voer de backlog-routine uit zoals beschreven in `CLAUDE.md` (sectie "Backlog-routine"). Kern: pak Linear-issues met label `claude-ready` + status `Todo` uit project `checkthepockets`, en werk ze één voor één af.

## Vóór je begint

1. Verifieer dat we in de `main` branch zitten en up-to-date zijn:
   ```bash
   git status
   git checkout main && git pull
   ```
2. Noteer de **starttijd** in je eerste tekstoutput. Doe dit letterlijk: `⏱️ Start: <HH:MM:SS>` — zodat de eerste testrun getimed kan worden.
3. Check de Linear-queue via de Linear MCP:
   - Project: `checkthepockets` (workspace `gjagils`)
   - Filter: `state.type == "unstarted"` (Todo) EN label `claude-ready` EN (geen assignee OF assignee == gjagils)
   - Sorteer: `priority DESC, createdAt ASC`
4. Als de queue leeg is: meld dat, noteer de eindtijd, en stop.

## Per issue (herhaal tot queue leeg of run-afbreker)

### 1. Issue claimen
- Zet Linear-status op `In Progress`
- Assign aan `gjagils`
- Reageer onder de issue met: *"Claude Code pakt deze op. Branch: feat/LIN-<ID>-<slug>"*

### 2. Branch maken
```bash
git checkout main && git pull
git checkout -b feat/LIN-<ID>-<slug>
```
`<slug>` = kebab-case van de issue-titel, max 40 tekens.

### 3. Implementeren
- Lees de issue-beschrijving + acceptatiecriteria goed.
- Lees relevante bestaande code **voordat** je wijzigt.
- Volg de bestaande patronen in de codebase (FastAPI, Jinja, SQLAlchemy/Alembic).
- Voeg/update tests in `tests/` waar zinvol.
- **Stop-criteria** (zet issue op `In Review` en ga door naar volgende):
  - Acceptatiecriteria onduidelijk
  - Diff dreigt > 500 regels te worden
  - Issue raakt beschermde paths: `.github/workflows/`, `alembic/versions/`, `stack.env`, `deploy.sh`
  - Issue heeft label `needs-review` → implementeer wel, maar **NIET** auto-mergen
  - Issue heeft label `blocked` → skip, post comment met reden
  - Issue heeft label `spike` → alleen onderzoek + bevindingen in Linear-comment, geen code

### 4. Lokaal testen
```bash
# Zoek en draai relevante tests
source .venv/bin/activate 2>/dev/null || true
pytest tests/ -x --tb=short
```
Als pytest niet draait (missende dep/env): log dit, zet issue op `In Review`, ga naar volgende.

### 5. Commit + push
```bash
git add <specifieke-files>   # geen `git add -A`
git commit -m "<type>: <beschrijving> (LIN-<ID>)"
git push -u origin feat/LIN-<ID>-<slug>
```
Commit types: `feat`, `fix`, `docs`, `chore`, `refactor`, `style`.

### 6. PR openen
```bash
gh pr create --title "<type>: <beschrijving> (LIN-<ID>)" --body "$(cat <<'EOF'
Closes LIN-<ID>

## Samenvatting
<1-3 bullets>

## Gewijzigde bestanden
- <file1>
- <file2>

## Test plan
- [x] Unit tests groen lokaal
- [ ] CI groen
EOF
)"
```

### 7. Wacht op CI
```bash
gh pr checks --watch --timeout 1200    # 20 min max
```
- Groen + diff ≤ 500 regels + geen `needs-review` label → **stap 8** (merge)
- Rood → push één reparatiepoging (max 1). Daarna: **zet Linear op `In Review`**, PR open laten, Linear-comment met CI-log link, volgende issue.
- Timeout → idem: `In Review`, PR open.

### 8. Auto-merge
```bash
gh pr merge --squash --delete-branch
```
Valideer: `gh pr view --json state` → moet `MERGED` zijn.

### 9. Linear afronden
- Linear-status op `Done`
- Comment onder issue: `✅ Gemerged: <PR-link>. Deploy loopt via GitHub Actions → Portainer.`

### 10. Terug naar stap 1 (volgende issue)

## Na afloop

Log een compacte samenvatting:

```
⏱️ Start:  <HH:MM:SS>
⏱️ Einde:  <HH:MM:SS>
⏱️ Duur:   <M min S sec>

Verwerkt: <N> issues
  ✅ Gemerged: <lijst LIN-IDs>
  🔍 Needs review: <lijst LIN-IDs met reden>
  ⏭️  Skipped: <lijst LIN-IDs met reden>
```

Deze samenvatting is nodig om de nachtelijke cron-tijd in te kunnen schatten.

## Veiligheid

- **NOOIT** mergen zonder groene CI.
- **NOOIT** `git push --force` op main of shared branches.
- **NOOIT** `.github/workflows/`, `alembic/versions/`, `stack.env`, `deploy.sh` aanpassen zonder expliciet groen licht op de issue.
- Bij twijfel: zet issue op `In Review` en ga door.
