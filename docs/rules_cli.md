# Rules configuratie CLI

Deze CLI helpt bij het veilig aanpassen van `criteria.yaml`.

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
