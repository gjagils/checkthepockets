---
title: "Je bank koppelen"
summary: "Automatisch transacties binnenhalen via PSD2 bankkoppeling."
order: 1
updated: "2026-04-22"
---

# Je bank koppelen

Naast CSV-import kun je je bank direct koppelen via **PSD2** (de Europese
open-banking-standaard). Eenmaal gekoppeld haalt de app periodiek de nieuwste
transacties binnen.

## Hoe werkt het?

1. Ga naar **Rekeningen › Bankkoppeling**.
2. Kies je bank uit de lijst.
3. Log in bij je bank en autoriseer read-only toegang tot je rekeningen.
4. De app haalt de eerste batch binnen; nieuwe transacties komen vanzelf in je
   **Inbox** voor categoriseren.

## Wat wordt opgeslagen?

- Transactie-details (datum, bedrag, tegenpartij, omschrijving, IBAN).
- Rekening-saldo op het moment van synchroniseren.
- **Geen** inloggegevens van je bank. De app werkt met een kortlevend OAuth-
  token dat periodiek vernieuwd moet worden (meestal elke 90 dagen).

## Token verlopen?

Dat kan gebeuren. Je ziet dan op **Bankkoppeling** een melding "opnieuw
autoriseren". Klik erop en doorloop dezelfde flow — historische data blijft
behouden.

## Duplicaten met CSV-import?

De app detecteert duplicaten op `import_hash` (datum + bedrag + tegenpartij +
omschrijving). Je kunt dus zonder zorgen een CSV importeren terwijl de
bankkoppeling actief is — dubbele records worden automatisch overgeslagen.
