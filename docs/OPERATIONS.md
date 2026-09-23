# Technische context en beheer

## Architectuur en bronnen

FastAPI/Jinja-app met SQLAlchemy en Alembic; PostgreSQL in productie.
GitHub → GitHub Actions → GHCR → Tailscale → Portainer → Docker op Synology.

- [Dependencies](../requirements.txt), [Dockerfile](../Dockerfile),
  [app-stack](../docker-compose.yml), [nginx-stack](../docker-compose.nginx.yml).
- [PR-CI](../.github/workflows/ci.yml): Python volgens `.python-version` (3.12), installatie van
  `requirements-dev.txt`, omgevingscontrole en `python -m pytest tests/ --tb=short`.
- [Deployment](../.github/workflows/deploy.yml): push naar main bouwt images en
  werkt Portainer bij. Markdown-wijzigingen zijn uitgesloten van de deploytrigger.
- Containerstart voert `alembic upgrade head` uit vóór Uvicorn.
- Huidige app-image: `ghcr.io/gjagils/checkthepockets:latest`; overgang naar
  specifieke releaseversies is gepland in ACT-14.

De echte workflowbestanden bepalen het gedrag; controleer die voordat je releaset.
Dit document legt bestaande infrastructuur vast, maar beweert niet dat de
productieconfiguratie of backups tijdens de analyse gecontroleerd zijn.

## Configuratie zonder geheimen in de repository

De deploymentworkflow gebruikt GitHub-secrets `TS_OAUTH_CLIENT_ID`,
`TS_OAUTH_SECRET`, `PORTAINER_URL`, `PORTAINER_API_TOKEN`, `PORTAINER_STACK_ID`
en voor nginx `PORTAINER_NGINX_STACK_ID`. De oude instructie met
`TAILSCALE_AUTHKEY` weerspiegelt de huidige workflow niet.

Runtimevariabelen staan beschreven in [app/config.py](../app/config.py),
[.env.example](../.env.example) en de composebestanden. Productiewaarden horen in
het daarvoor bestemde secrets-/deploymentbeheer, niet in documentatie of commits.
Een nieuwe bijdrager krijgt die toegang apart; geen coding-agentplugin is vereist.
`stack.env` wordt momenteel nog door Git gevolgd: ACT-08 behandelt onderzoek en
verwijdering uit tracking. Kopieer geen bestaande waarden naar voorbeelden.

## Verificatie en herstel

Gebruik een geïsoleerde testdatabase, nooit de productiedatabase, voor tests en
migratieproeven. De [ontwikkelhandleiding](DEVELOPMENT.md) beschrijft de reproduceerbare
Python-omgeving en locks. PostgreSQL-/migratiecontroles volgen in ACT-03.
Vermeld bij testresultaten altijd afwijkingen van de vastgelegde omgeving.

Controleer bij een release PR-CI, build/deploy-run, containerstatus, applicatielogs
en de relevante gebruikersroute. Meld welke controles niet uitgevoerd konden
worden. ACT-13 en ACT-14 automatiseren dit verder.

Bij herstel eerst beoordelen of het databaseschema compatibel is met de vorige
image. Een oude image terugzetten is niet vanzelf een veilige migratierollback.
De huidige [backupinstructie](../app/docs/admin/backup-restore.nl.md) is een
uitgangspunt. De [restoreproef](BACKUP-RESTORE-DRILL.md) beschrijft de vaste
controlepunten en het beheerlog; een proef moet door een bevoegde beheerder
worden uitgevoerd en geregistreerd.
