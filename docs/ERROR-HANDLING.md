# Foutafhandeling en logging

Inventarisatie van brede `except`/`except Exception` in `app/` (ACT-24, stand
2026-09-23). Regelnummers zijn indicatief; zoek bij twijfel op bestand en context.
Controleer nieuwe code tegen dezelfde regels.

## Regels

- Een **operationele fout** (database, externe API, configuratie, ontsleuteling)
  wordt gelogd, ook als de gebruiker een terugvaloptie krijgt. Nooit stil `pass`.
- Een **verwachte gebruikersfout** (ongeldige invoer of een aangepaste
  formulierwaarde) vangt alleen de specifieke uitzondering af en geeft passende
  feedback of een veilige standaardwaarde.
- **Geen gevoelige inhoud** in logs of foutmeldingen: geen tokens, sessie- of
  rekening-ID's van Enable Banking, geen IBAN's of transactie-inhoud.
  Gebruik `enable_banking.safe_error_message(exc)` voor bankfouten; netwerkfouten
  van `requests` noemen anders het volledige requestpad. Log interne ID's
  (koppeling-, transactie-ID) als verwijzing.

## Inventarisatie

| Plaats | Soort | Afhandeling |
|---|---|---|
| crypto.py:53, :66; config.py:58; parsers/ics_pdf.py:112 | Omzetten naar domeinfout | Gooit een duidelijke fout verder; niets verdwijnt |
| crypto.py:30 | Operationeel | Gelogd; opslag weigert daarna (ACT-07) |
| scheduler.py:56 | Operationeel | Traceback in joblog, gelogd en opnieuw gegooid |
| scheduler.py:216 | Operationeel | Gelogd met `safe_error_message` en koppeling-ID; volgende rekening |
| admin.py:530 | Operationeel, al gelogd | `logged_job` legt de fout vast; de UI blijft werken |
| admin.py:466 | Operationeel | Gelogd; lege joblijst |
| admin.py:532 | Operationeel | Foutmelding in de UI |
| banking.py:68, :125, :151, :219, :347 | Operationeel (Enable Banking) | Gelogd en getoond via `safe_error_message`; synchronisatiefout opgeslagen zonder ID's |
| banking.py:255 | Operationeel | Gelogd; rekening zonder IBAN-verrijking |
| banking.py:619 | Operationeel | Gelogd zonder sessie-ID; lokale koppeling wordt toch ingetrokken |
| banking.py (rekeninglijst) | Beschadigde opgeslagen JSON | Alleen `ValueError`, gelogd met koppeling-ID |
| main.py:81 | Operationeel | Gelogd; badge toont 0, pagina blijft werken |
| main.py:93 | Operationeel | Gelogd; landingspagina als uitgelogd |
| auth.py:51 | Configuratie | Gelogd; Google-login uitgeschakeld |
| auth.py:684 | Gebruiker of extern | Alleen fouttype gelogd; melding om opnieuw te proberen |
| info_loader.py:104 | Beschadigd artikel | Gelogd; artikel niet getoond |
| savings.py:1618 | Onleesbare transactie | Gelogd met transactie-ID; overgeslagen in analyse |
| savings.py (suggesties) | Gebruikersinvoer (queryparameter) | Alleen `ValueError`; pagina zonder suggesties |
| settings.py:126, :171; transactions.py:1398, :1469 | Gebruikersinvoer (upload/formulier) | Foutmelding of terug naar het formulier |
| settings.py (datums) | Gebruikersinvoer (instellingenbestand) | Alleen `TypeError`/`ValueError`; standaarddatum |
| template_config.py:12, :43 | Weergave | Waarde ongewijzigd tonen; geen operationele fout |
| ai_suggest.py:169, :275, :474, :579; rules.py:200; mortgage_rate_ocr.py:122, :128 | Externe AI-API | Gelogd; functie meldt dat AI niet beschikbaar is |
| portfolio_prices.py:23, :74, :140 | Externe koersbron | Gelogd (warning/debug); geen koers |
| email_service.py:24 | Externe mailprovider | Gelogd met ontvangeradres; geeft `False` terug |

## Bekende beperkingen

- `email_service.py` logt het ontvangende e-mailadres. Dat is persoonsgegeven,
  geen geheim; laat het staan zolang het nodig is voor diagnose.
- Meldingen van externe AI- en koers-API's worden letterlijk gelogd. Die
  bevatten geen bankgegevens, maar controleer dit bij het toevoegen van een
  nieuwe provider.
