"""Display the TOMIC trading plan."""


TRADING_PLAN_TEXT = r"""
                            TOMIC Trading Plan

1. **Visie**

Mijn tradingaanpak is gebaseerd op het TOMIC-principe: handelen als een verzekeraar, waarbij systematisch premie wordt geïnd op overprijsde opties in ruil voor het overnemen van risico. De focus ligt op strategieën met een positieve verwachtingswaarde (EV), een hoge kans op succes (PoS), en een beheerste blootstelling aan portefeuillerisico's.

2. **Doelstellingen**

- Jaarlijks doelrendement: 10% op het beschikbare risicokapitaal.
- Drawdownlimiet: maximaal 6% op maandbasis.
- Maximale risicoblootstelling per positie: 2–3% van NetLiq.
- Aantal actieve posities: gemiddeld 4–8, gediversifieerd naar strategie en symbool.

3. **Strategieprofiel**

*Toegestane strategieën*
naked_put
  short_put_spread
  short_call_spread
  iron_condor
  atm_iron_butterfly
  calendar
  ratio_spread
  backspread_put

*Niet toegestane strategieën*
- Symbolen met lage liquiditeit of zeer brede spreads

4. **Trade selectieproces**

*Criteria*
- Symbolen met voldoende liquiditeit en open interest
- IV Rank > 40 voor vega-negatieve trades; IV Rank < 30 voor vega-positieve setups
- ATR, HV, skew en term structure worden meegewogen
- Geen dubbele posities per symbool of strategie

5. **Volatiliteit & Mean Reversion Inzichten**

Mean-reversion kansen bij stijging VIX t.o.v. vorige dag:

VIX-stijging      Kans op daling IV binnen 30 dagen  Betekenis
+1%               ~55%                              Ruis
+2%               ~60–65%                          Licht verhoogd risico
+3%               ~70%                              Signaalsterker dan ruis
+5%               ~80%                              Statistisch significant
+8%               ~90%                              Vaak nieuws/emotie-gedreven spike
+10%+             ~92–95%                          Mean-reversion zeer waarschijnlijk

NB: Deze cijfers gelden voor implied volatility (zoals VIX), niet voor aandelenprijzen zelf. De grootste correctie na spikes treedt vaak op binnen 10–15 dagen.

*Toepassing*
- Bij VIX-stijging >5% prioriteit op vega-negatieve strategieën.
- Bij +8–10% spikes: time-based setups voor mean-reversion.

6. **Risicomanagement**

- Max. 2–3% risk per individuele positie
- Maandelijkse stop bij >6% verlies
- Portfoliodiversificatie: max. 25% in één sector of onderliggend
- Exits gebaseerd op premieafbouw, DTE, en/of technische grens

7. **Entry- en Exitregels**

*Entry*
- Setup voldoet aan IV-/HV-analyse, skew, en TOMIC-score
- PoS > 70% en positieve EV

*Exit*
- Winstnemen bij 70–80% premieafbouw
- Stop-out bij max loss of bij breken van technische levels
- Tijdsexit: doorgaans 5–10 dagen voor expiratie

8. **Evaluatie en bijsturing**

- Wekelijkse journalevaluatie: performance en positiestructuur
- Maandelijkse analyse van winrate, EV, Greeks-gedrag
- Kwartaalreview: strategieprestaties en eventueel aanpassen tradingplan

9. **Infrastructurele randvoorwaarden**

- Broker met goede fills, margin-efficiëntie en real-time data
- Analysetools voor Greeks, IV-structuur, skew/term structure
- Back-upscenario’s bij platform- of internetproblemen

10. **Permanente ontwikkeling**

- Actieve studie van volarbitrage, synthetics, IV pricing
- Periodieke deelname aan TOMIC- of volatility-gebaseerde trainingsmodules
- Doel: beheersen van portfolio-Greeks en strategisch inzetten van skew en term structure voor edge

Laatste update: 29 mei 2025
"""


def main() -> None:
    """Print the trading plan."""
    print(TRADING_PLAN_TEXT)


if __name__ == "__main__":
    main()

