# Rules configuratie CLI

Deze CLI helpt bij het veilig aanpassen van `criteria.yaml`.

## Strategie & Criteria submenu

In het control panel vind je onder *Configuratie → Strategie & Criteria* een handig
submenustructuur om zowel optie-strategie parameters als de regels in `criteria.yaml`
te beheren:

```
=== Strategie & Criteria ===
1. Optie-strategie parameters
2. Criteria beheren
3. Terug
```

Het onderdeel **Criteria beheren** toont de volgende opties:

```
=== Criteria beheren ===
1. Toon criteria
2. Valideer criteria.yaml
3. Valideer & reload
4. Reload zonder validatie
5. Terug
```

Hier kun je optioneel een pad naar een alternatieve `criteria.yaml` invoeren voordat je
valideert of herlaadt.

## Configuratie tonen

```
tomic rules show
```

Geeft de samengevoegde configuratie weer in JSON-vorm.

## Configuratie valideren

```
tomic rules validate path/naar/criteria.yaml
```

Controleert of het YAML-bestand geldig is. Voeg `--reload` toe om na een
succesvolle validatie de draaiende services te herladen.

```
tomic rules validate criteria.yaml --reload
```

## Hot reload

Het `reload`-commando leest de configuratie opnieuw en ververst zowel de
app-config als de regels:

```
tomic rules reload
```

## Tips

- Maak altijd een back-up voordat je het bestand wijzigt.
- Gebruik `tomic rules validate` om fouten te voorkomen voordat je
  applicaties start.
