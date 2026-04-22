---
title: "Backup and restore"
summary: "How to take a full database backup on the Synology and how to restore it."
order: 1
updated: "2026-04-22"
---

# Backup and restore

The CSV export on `/transactions` only covers transactions. For a **full backup**
(including savings plans, portfolio, recurring items, rules, mortgage scenarios
and persons) use a PostgreSQL dump.

## Taking a backup

SSH into the Synology and run:

```bash
docker exec -t <postgres-container> \
  pg_dump -U <db-user> -d <db-name> --no-owner --clean \
  | gzip > ctp-backup-$(date +%F).sql.gz
```

Store the resulting file somewhere safe (a NAS volume with snapshots, an
external disk, or cloud storage).

## Restoring

```bash
gunzip -c ctp-backup-2026-04-22.sql.gz \
  | docker exec -i <postgres-container> psql -U <db-user> -d <db-name>
```

## Transaction-only CSV export

`/transactions` has a **CSV EXPORT** button in the top-right corner. URL filters
(per account, per year, …) are honoured. Columns: date, amount, description,
counterparty, counterparty IBAN, category, account, reviewed. Not a full backup —
use `pg_dump` for that.

## CSV import

`/import` → pick an account, upload the file, walk through the column-mapper,
check the preview (it flags duplicates), confirm. Duplicates are detected via
`import_hash` (date + amount + counterparty + description) and skipped.
