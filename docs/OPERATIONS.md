# Technische context en beheer

## Architectuur en bronnen

FastAPI/Jinja-app met SQLAlchemy en Alembic; PostgreSQL in productie.
GitHub → GitHub Actions → GHCR → Tailscale → Portainer → Docker op Synology.

- [Dependencies](../requirements.txt), [Dockerfile](../Dockerfile),
  [app-stack](../docker-compose.yml), [nginx-stack](../docker-compose.nginx.yml).
- [PR-CI](../.github/workflows/ci.yml): Python volgens `.python-version` (3.12), installatie van
  `requirements-dev.txt`, omgevingscontrole en `python -m pytest tests/ --tb=short`.
- [Deployment](../.github/workflows/deploy.yml): push naar main bouwt images en
  werkt Portainer bij. Wijzigingen in alleen de Markdown in de repository-root, `docs/`
  of `.claude/` triggeren geen deployment; `app/docs/` (de kennisbank in het image) wel.
  Deployments lopen na elkaar (`concurrency: deploy-main`).
- Containerstart voert `alembic upgrade head` uit vóór Uvicorn.
- App-image: `ghcr.io/gjagils/checkthepockets:<commit-sha>` (ook `latest`); de deployment
  zet `IMAGE_TAG` op de commit, zodat een eerdere versie terug te zetten is (ACT-14).

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
`stack.env` wordt niet meer door Git gevolgd en staat in `.gitignore` en `.dockerignore`
(ACT-08). Kopieer geen bestaande waarden naar voorbeelden.

## Verificatie en herstel

Gebruik een geïsoleerde testdatabase, nooit de productiedatabase, voor tests en
migratieproeven. De [ontwikkelhandleiding](DEVELOPMENT.md) beschrijft de reproduceerbare
Python-omgeving en locks. De CI-job `postgres-migrations` controleert migraties en schema
op PostgreSQL 16 (ACT-03).
Vermeld bij testresultaten altijd afwijkingen van de vastgelegde omgeving.

Controleer bij een release PR-CI, build/deploy-run, containerstatus, applicatielogs
en de relevante gebruikersroute. Meld welke controles niet uitgevoerd konden
worden. De deployment faalt bij een fout van Portainer (ACT-13).
De regels voor foutafhandeling en loginhoud staan in
[ERROR-HANDLING.md](ERROR-HANDLING.md); logs bevatten geen tokens, bank-ID's of
transactie-inhoud.

Bij herstel eerst beoordelen of het databaseschema compatibel is met de vorige
image. Een oude image terugzetten is niet vanzelf een veilige migratierollback.
De huidige [backupinstructie](../app/docs/admin/backup-restore.nl.md) is een
uitgangspunt. De [restoreproef](BACKUP-RESTORE-DRILL.md) beschrijft de vaste
controlepunten en het beheerlog; een proef moet door een bevoegde beheerder
worden uitgevoerd en geregistreerd.

## Banksynchronisatie

De Enable Banking-sync staat op één plek: `app/bank_sync.py`. De handmatige pagina (`/banking/sync/…`)
en de geplande job (`bank_sync`, 01:00 en 17:00 Amsterdam) gebruiken dezelfde functies, dus hetzelfde
gedrag: rekeningen worden gevonden op `external_uid` en anders op het genormaliseerde IBAN, elke sync
maakt een `ImportBatch`, en de koppeling krijgt `last_synced_at`, `last_sync_status` (`success`/`error`)
en `last_sync_error`. Elke rekening draait in een eigen savepoint: een rekening die faalt laat de andere
rekeningen van dezelfde koppeling (en andere koppelingen) onaangetast; de koppeling krijgt dan status
`error` met de foutmelding (zonder account-id's). Controleer na een uitrol de scheduler-log
(`/admin/scheduler`, "Recente runs") en de status van de koppeling op `/banking/connect`.

## Scheduler: één proces, geen dubbele jobs

De achtergrondjobs (banksync, bunq-sync, digests, vermogensplan) draaien in het webproces. Draai je meer
dan één worker of container, dan heeft elk proces een eigen scheduler en zou elke job meerdere keren lopen.
- Zet `SCHEDULER_ENABLED=false` in alle processen behalve één. Dit is het hoofdmiddel en werkt overal.
- Optioneel: `SCHEDULER_LOCK=true` laat elke job een PostgreSQL advisory lock nemen, zodat hij ook zonder
  bovenstaande instelling nooit tegelijk draait. Gebruik dit **alleen met een directe databaseverbinding**: achter
  een transaction-pooler (een Neon-verbinding met `-pooler`) zijn sessie-locks onbetrouwbaar en kan een lock blijven
  hangen, waardoor een job wordt overgeslagen. Standaard staat het daarom uit.
- Jobs hebben `coalesce`, `max_instances=1` en `misfire_grace_time=3600`: na een herstart worden gemiste runs van
  het afgelopen uur één keer ingehaald, nooit parallel.
