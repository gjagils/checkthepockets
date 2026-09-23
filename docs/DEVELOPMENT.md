# Ontwikkelen en testen

Deze opdrachten werken onafhankelijk van Codex, Claude Code, MCP of plugins.
Gebruik een terminal in de repositoryroot. Python **3.12** is de ondersteunde
minorversie, vastgelegd in `.python-version`. CI leest dat bestand; Docker gebruikt
`python:3.12-slim`. Patchupdates binnen 3.12 blijven toegestaan; dit is geen
bit-identieke OS-/containerlock. Python 3.14 is voor dit project niet de testbasis.

## Schone installatie

Installeer Python 3.12 met je gebruikelijke pakketbeheerder of Python-installatie.
Maak een nieuwe omgeving; hergebruik geen omgeving van een andere Python-versie.
De onderstaande `.venv` moet nieuw zijn. Bewaar een bestaande omgeving desgewenst
onder een andere naam of kies een andere directory; verwijder deze niet blind.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip check
python scripts/check_environment.py
python -m pytest tests/ --tb=short
```

Windows: gebruik `py -3.12 -m venv .venv` en activeer via
`.venv\Scripts\Activate.ps1` in PowerShell. De overige Python-opdrachten zijn gelijk.
De lockbestanden bevatten platformmarkers voor platformgebonden packages.
macOS en Linux worden gecontroleerd; Windows is hiermee niet afzonderlijk getest.

De huidige tests maken SQLite-testdatabases aan en simuleren externe diensten.
Gebruik een schone shell zonder productievariabelen of een productie-`.env`.
Voeg nooit echte banktokens of productie-dumps toe voor tests. PostgreSQL-integratie
met Alembic-migraties wordt apart behandeld in ACT-03; SQLite-tests bewijzen dat niet.

## Lokaal de applicatie draaien

Gebruik een afzonderlijke lokale PostgreSQL-database. Stel bijvoorbeeld in een
lokale, door Git genegeerde `.env` de volgende waarden in (vervang placeholders):

```dotenv
DATABASE_URL=postgresql://<lokale-user>:<lokaal-wachtwoord>@localhost:5432/checkthepockets_dev
SECRET_KEY=<een-lokaal-gegenereerde-willekeurige-sleutel>
APP_URL=http://localhost:8000
ENVIRONMENT=development
REGISTRATION_OPEN=true
```

Genereer een lokale sleutel met `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Laat bank-, mail-, OAuth- en AI-credentials leeg als je die integraties niet test.

```sh
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Deze opdrachten starten de app, inclusief de bestaande scheduler. Gebruik hiervoor
uitsluitend een ontwikkeldatabase met testgebruikers. De productiestack wordt beheerd
via Portainer; `docker-compose.yml` is geen complete lokale databaseomgeving.

## Dependencies wijzigen

- `requirements.in`: directe runtimewensen; bestaande exact gepinde versies blijven
  behouden. Open ondergrenzen worden bij lockgeneratie naar concrete versies opgelost.
- `requirements.txt`: gegenereerde, exact gepinde runtime-dependencies inclusief
  transitieve packages. Docker installeert dit bestand.
- `requirements-dev.in`: neemt de runtime-lock over en voegt pytest toe.
- `requirements-dev.txt`: gegenereerde testomgeving met dezelfde runtimeversies.

Wijzig `.in`-bestanden en genereer beide locks met onderstaande vastgelegde resolver.
`uv` is alleen nodig voor lockonderhoud, niet voor installatie, testen of agentgebruik.
Installeer het in een afzonderlijke tijdelijke omgeving om je app-omgeving niet te wijzigen.

```sh
python3.12 -m venv /tmp/ctp-lock-tools
/tmp/ctp-lock-tools/bin/python -m pip install uv==0.8.22
/tmp/ctp-lock-tools/bin/uv pip compile requirements.in --python-version 3.12 --universal --output-file requirements.txt
/tmp/ctp-lock-tools/bin/uv pip compile requirements-dev.in --python-version 3.12 --universal --output-file requirements-dev.txt
```

De resolver behoudt bestaande pins waar mogelijk. Voeg bij een bewuste update
`--upgrade-package <naam>` toe aan de runtimegeneratie, of `--upgrade` voor een
expliciet geplande brede update. Genereer daarna altijd de dev-lock opnieuw.
Controleer de diff en valideer in een verse omgeving met bovenstaande testopdrachten.
Commit de `.in`- en `.txt`-bestanden samen. Locks pinnen versies, geen artifacthashes.

## CI en Docker

PR-CI installeert de dev-lock, controleert packageconsistentie en draait de tests.
De omgevingscontrole ontdekt ontbrekende packages, verkeerde versies en een afwijkende
Python-minor. Extra lokaal geïnstalleerde tools zijn toegestaan; gebruik voor de
nulmeting altijd een verse omgeving.
Docker installeert uitsluitend de runtime-lock en controleert dependencies met pip.
Een volledige containerbuild vraagt een draaiende Docker-daemon:

```sh
docker build -t checkthepockets:local .
```

Neem lokale sleutels niet mee in een buildcontext. ACT-08 behandelt de bestaande
buildcontext-uitsluitingen. Een CI-build op een schone Git-checkout bevat geen lokale
niet-gevolgde sleutels. Productievalidatie en herstel staan in OPERATIONS.md.

Voor productie moet `ENVIRONMENT=production`, `APP_URL` een HTTPS-URL en
`COOKIE_SECURE=true` zijn. `SECRET_KEY` moet minstens 32 tekens zijn en mag geen
voorbeeldwaarde zijn. De applicatie stopt bij opstarten wanneer deze voorwaarden
niet gelden. In lokale ontwikkeling blijft HTTP toegestaan en worden Secure-cookies
uitgeschakeld zodat localhost-login werkt.
