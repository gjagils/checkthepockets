# Backup- en restoreproef

Deze proef maakt aantoonbaar dat een PostgreSQL-backup bruikbaar is zonder
productiegegevens in Git te zetten. Voer haar minimaal per kwartaal uit en na
een wijziging aan database, opslag of migraties.

1. Maak op de NAS een gecomprimeerde `pg_dump` met datum en versienummer.
2. Kopieer de dump naar een geïsoleerde PostgreSQL-container of tijdelijke
   database. Gebruik nooit de productiedatabase als restore-doel.
3. Restore de dump met `psql`, start de applicatie met dezelfde image-tag en
   voer `alembic upgrade head` uit.
4. Controleer `GET /healthz` en `GET /readyz`, plus aantallen voor gebruikers,
   rekeningen en transacties. Controleer ook dat een login en een leesroute
   werken.
5. Leg datum, dumpnaam, image-tag, schema-revisie, duur, controle-aantallen en
   resultaat vast in het beheerlog. Verwijder de tijdelijke omgeving en lokale
   kopieën na afloop.

Bewaar minimaal drie dagelijkse backups en vier wekelijkse backups, met ten
minste één kopie buiten de primaire NAS. Test ook dat een backupbestand niet
wereldwijd leesbaar is en dat toegang tot de restorekopie beperkt is tot
beheerders.

Een geslaagde dump zonder geslaagde restoreproef geldt niet als herstelbare
backup. Bij een mislukte proef blijft de laatste geslaagde backup leidend en
wordt de oorzaak als incident opgevolgd.
