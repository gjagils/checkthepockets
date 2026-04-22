---
title: "Backup en restore"
summary: "Hoe je een volledige database-backup maakt op de Synology en deze terugzet."
order: 1
updated: "2026-04-22"
---

# Backup en restore

De CSV-export op `/transactions` dekt alleen transacties. Voor een **volledige
backup** (incl. spaarplannen, portfolio, recurring, regels, hypotheek-scenario's,
personen) gebruik je een PostgreSQL dump.

## Backup maken

SSH naar de Synology en draai:

```bash
docker exec -t <postgres-container> \
  pg_dump -U <db-user> -d <db-name> --no-owner --clean \
  | gzip > ctp-backup-$(date +%F).sql.gz
```

Sla het bestand veilig op (NAS-volume met snapshot, externe schijf, of cloud).

## Restore

```bash
gunzip -c ctp-backup-2026-04-22.sql.gz \
  | docker exec -i <postgres-container> psql -U <db-user> -d <db-name>
```

## CSV-export voor transacties (subset)

`/transactions` → knop **CSV EXPORT** rechtsbovenin. Filters in de URL worden
meegenomen (bv. per rekening of per jaar). Kolommen: datum, bedrag, omschrijving,
tegenpartij, IBAN tegenpartij, categorie, rekening, gecontroleerd. Niet geschikt
als volledige backup — gebruik daarvoor `pg_dump`.

## CSV-import

`/import` → kies een rekening, upload het bestand, mapper-stap voor kolommen,
preview (toont duplicaten), bevestigen. Duplicaten worden herkend op
`import_hash` (datum + bedrag + tegenpartij + omschrijving) en overgeslagen.
