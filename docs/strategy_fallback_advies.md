# Advies per strategie m.b.t. mid-fallbacks

## Iron Condor
* Parity-mids tellen als "echte" mids; alleen model- of close-fallbacks worden beperkt.
* Maximaal twee long legs mogen een fallback gebruiken; short legs moeten een true of parity mid hebben.
* Long wings mogen bij het zoeken naar strikes een tolerantie van ±5% gebruiken om illiquide ketens op te vangen.

## ATM Iron Butterfly
* Houd parity als acceptabele vervanging voor ontbrekende mids, maar monitor of beide short legs een true mid hebben.
* Overweeg identieke tolerantie-uitbreiding voor de wings als dezelfde liquiditeitsproblemen ontstaan.

## Short Put/Call Spreads
* Sta hooguit één fallback toe en alleen op de long leg; short legs moeten een true/parity mid hebben om de credit te waarborgen.
* Controleer of de long leg een voldoende nauwe strike-match heeft; verhoog de tolerantie alleen voor extreem illiquide expiries.

## Naked Put
* Geen fallbacks toestaan op de enige leg; een fallback impliceert dat de prijs onvoldoende betrouwbaar is voor een naked positie.
* Indien parity beschikbaar is, kan dit dienen als sanity-check maar niet als vervanging voor echte quotes.

## Calendar
* Omdat expiries verschillen, kan een model fallback op de long leg acceptabel zijn zolang de short leg een true/parity mid heeft.
* Houd de strike-tolerantie strikt om misprijzen tussen expiries te vermijden; overweeg parity-checks voor consistentie.

## Ratio en Backspreads
* Beperk fallbacks tot de extra long legs; short legs moeten altijd op true/parity mids staan om een betrouwbare credit/debit te berekenen.
* Documenteer welke legs fallback gebruiken voor risico-evaluatie en herzien de breedteberekening als strikes vaak ontbreken.

## Vragen / Onzekerheden
* Moet de aangepaste fallback-logica ook voor ATM Iron Butterfly gelden, of blijft dat bij het oude beleid?
* Zijn er specifieke illiquide tickers (zoals AMT) waar additionele logging of uitzonderingen gewenst zijn?
