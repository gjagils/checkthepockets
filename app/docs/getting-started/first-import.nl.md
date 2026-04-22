---
title: "Je eerste CSV-import"
summary: "Van bankexport naar gecategoriseerde transacties in drie stappen."
order: 2
updated: "2026-04-22"
---

# Je eerste CSV-import

De meeste banken laten je transacties als CSV exporteren. Zo krijg je die in de app:

1. Ga naar **Rekeningen › Importeren**.
2. Kies de rekening en upload je CSV.
3. Controleer de kolommen (datum, bedrag, omschrijving, tegenpartij) en bevestig.

De preview-stap laat zien of er duplicaten zouden ontstaan — die worden automatisch
overgeslagen op basis van de `import_hash` (datum + bedrag + tegenpartij + omschrijving).

Nieuwe transacties komen vervolgens in de **Inbox** zolang ze nog geen categorie hebben.
