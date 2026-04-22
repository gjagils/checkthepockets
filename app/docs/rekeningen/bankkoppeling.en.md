---
title: "Linking your bank"
summary: "Pull transactions automatically via a PSD2 bank connection."
order: 1
updated: "2026-04-22"
---

# Linking your bank

On top of CSV imports you can connect your bank directly via **PSD2** (the
European open-banking standard). Once linked, the app fetches the newest
transactions periodically.

## How does it work?

1. Go to **Accounts › Bank connection**.
2. Pick your bank from the list.
3. Log in at your bank and authorise read-only access to your accounts.
4. The app fetches the first batch; new transactions then appear in your
   **Inbox** ready to categorise.

## What's stored?

- Transaction details (date, amount, counterparty, description, IBAN).
- Account balance at sync time.
- **No** login credentials. The app works with a short-lived OAuth token that
  needs to be refreshed periodically (typically every 90 days).

## Token expired?

It happens. **Bank connection** will show a "re-authorise" banner — click it and
walk through the same flow. Historical data stays intact.

## Duplicates with CSV imports?

The app detects duplicates via `import_hash` (date + amount + counterparty +
description). So you can safely import a CSV while the bank connection is
active — duplicate records are skipped automatically.
