# Advies per strategie m.b.t. mid-fallbacks

## Iron Condor
* `parity_true` wordt als volwaardige quote gezien. `parity_close`, `model` en `close` gelden als preview en worden in de teller meegenomen.
* Maximaal twee legs per vier mogen een fallback gebruiken (config `MID_FALLBACK_MAX_PER_4`). Zowel long als short legs tellen mee, maar short legs blijven toegestaan zolang het totaal binnen de limiet valt.
* Long wings mogen bij het zoeken naar strikes een tolerantie van ±5% gebruiken om illiquide ketens op te vangen.

## ATM Iron Butterfly
* `parity_true` blijft de voorkeur; gebruik van `parity_close`, `model` of `close` op de short legs is toegestaan maar wordt in de CLI/exports als previewkwaliteit gelabeld.
* Overweeg identieke tolerantie-uitbreiding voor de wings als dezelfde liquiditeitsproblemen ontstaan.

## Short Put/Call Spreads
* Sta hooguit één fallback toe (configlimiet). Short legs mogen een preview-bron gebruiken (`parity_close`, `model`, `close`), maar worden als zodanig in logging en exports gemarkeerd.
* Controleer of de long leg een voldoende nauwe strike-match heeft; verhoog de tolerantie alleen voor extreem illiquide expiries.

## Naked Put
* Eén fallback op de short leg is mogelijk zolang `MID_FALLBACK_MAX_PER_4` ≥ 1; de scorer logt expliciet welke bron (`parity_close`, `model`, `close`) gebruikt is.
* Indien `parity_true` beschikbaar is geeft dit de voorkeur boven andere bronnen.

## Calendar
* De short leg mag een preview-bron gebruiken mits binnen de fallbacklimiet, maar een model fallback op de long leg blijft geweigerd (vereist `parity_true`, `parity_close` of `close`).
* Houd de strike-tolerantie strikt om misprijzen tussen expiries te vermijden; overweeg parity-checks voor consistentie.

## Ratio en Backspreads
* Preview-bronnen op de short leg zijn toegestaan, maar tel mee in het fallbackquotum en communiceer naar gebruikers dat de credit gebaseerd is op lagere datakwaliteit.
* Documenteer welke legs fallback gebruiken voor risico-evaluatie en herzien de breedteberekening als strikes vaak ontbreken.

## Vragen / Onzekerheden
* Zijn er specifieke illiquide tickers (zoals AMT) waar additionele logging of uitzonderingen gewenst zijn?
