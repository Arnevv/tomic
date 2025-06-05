"""Interactively add new trades to the journal."""

from __future__ import annotations

from datetime import date

from tomic.api.market_utils import fetch_market_metrics
from tomic.api.margin_calc import calculate_trade_margin
from tomic.journal.service import add_trade, next_trade_id


def float_prompt(prompt_tekst, default=None):
    while True:
        val = input(prompt_tekst).strip().replace(",", ".")
        if val == "" and default is not None:
            return default
        try:
            return float(val)
        except ValueError:
            print("❌ Ongeldige invoer, gebruik bijv. 14.7")


def date_prompt(prompt_tekst):
    while True:
        val = input(prompt_tekst).strip()
        try:
            date.fromisoformat(val)
            return val
        except ValueError:
            print("❌ Ongeldige datum. Gebruik het formaat YYYY-MM-DD met streepjes.")


def interactieve_trade_invoer():
    print(
        "\n🆕 Nieuwe Trade Invoeren (meerdere legs ondersteund)\nLaat een veld leeg om af te breken.\n"
    )

    trade_id = next_trade_id()
    print(f"TradeID automatisch toegekend: {trade_id}")

    symbool = input("Symbool (bijv. SPY): ").strip()
    trade_type = input("Strategie type (bijv. Put Ratio Spread): ").strip()
    expiry = date_prompt("Expiry (YYYY-MM-DD): ")
    richting = input("Richting (Bullish / Bearish / Sideways): ").strip()

    legs = []
    print("\nVoer legs in. Typ ENTER bij strike om te stoppen.")
    while True:
        strike_input = input("  Strike: ").strip()
        if not strike_input:
            break
        try:
            strike = float(strike_input)
        except ValueError:
            print("❌ Ongeldige strike.")
            continue

        right = input("  Type (CALL of PUT): ").strip().upper()
        if right not in {"CALL", "PUT"}:
            print("❌ Alleen CALL of PUT toegestaan.")
            continue

        action = input("  Actie (BUY of SELL): ").strip().upper()
        if action not in {"BUY", "SELL"}:
            print("❌ Alleen BUY of SELL toegestaan.")
            continue

        qty_input = input("  Aantal contracts: ").strip()
        try:
            qty = int(qty_input)
        except ValueError:
            print("❌ Ongeldig aantal.")
            continue

        legs.append({"strike": strike, "type": right, "action": action, "qty": qty})

    if not legs:
        print("❌ Geen geldige legs ingevoerd.")
        return

    premium_input = input("\nNetto ontvangen/ingezette premium (bijv. 1.10): ").strip()
    try:
        premium = float(premium_input)
    except ValueError:
        print("❌ Ongeldige premium.")
        return

    while True:
        stop_pct_input = input("Stop-loss % (bijv. 20): ").strip()
        try:
            stop_pct = int(stop_pct_input)
            break
        except ValueError:
            print("❌ Ongeldige invoer. Vul een getal in.")

    print("\nVoer plan in (typ '.' op een lege regel om te stoppen):")
    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    plan = "\n".join(lijnen)

    print("\nVoer reden in (typ '.' op een lege regel om te stoppen):")
    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    reden = "\n".join(lijnen)

    print("\nVoer exitstrategie in (typ '.' op een lege regel om te stoppen):")
    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    exitstrategie = "\n".join(lijnen)

    print("\n📊 Marktdata wordt automatisch opgehaald...")
    try:
        metrics = fetch_market_metrics(symbool)
    except Exception as exc:
        print(f"⚠️ Marktdata ophalen mislukt: {exc}")
        metrics = {
            "spot_price": None,
            "hv30": None,
            "atr14": None,
            "vix": None,
            "skew": None,
            "iv_rank": None,
            "implied_volatility": None,
            "iv_percentile": None,
        }

    spot = metrics["spot_price"]
    iv_entry = metrics["implied_volatility"]
    iv_rank = metrics["iv_rank"]
    hv_entry = metrics["hv30"]
    vix = metrics["vix"]
    atr14 = metrics["atr14"]
    skew = metrics["skew"]
    iv_percentile = metrics["iv_percentile"]

    print("\n🧮 Benodigde margin wordt berekend...")
    try:
        init_margin = calculate_trade_margin(symbool, expiry, legs)
        print(f"✅ Init margin: {init_margin}")
    except Exception as exc:
        print(f"⚠️ Marginberekening mislukt: {exc}")
        init_margin = None

    print("\n📐 Vul de NETTO Greeks in van de hele positie bij entry (optioneel):")
    print(
        "ℹ️ Dit zijn GEAGGREGEERDE waarden van de gehele trade, NIET per leg of strike"
    )
    delta = float_prompt("  Delta: ", default=None)
    gamma = float_prompt("  Gamma: ", default=None)
    vega = float_prompt("  Vega: ", default=None)
    theta = float_prompt("  Theta: ", default=None)

    nieuwe_trade = {
        "TradeID": trade_id,
        "DatumIn": str(date.today()),
        "DatumUit": None,
        "Symbool": symbool,
        "Type": trade_type,
        "Expiry": expiry,
        "Richting": richting,
        "Status": "Open",
        "Premium": premium,
        "EntryPrice": premium,
        "ExitPrice": None,
        "ReturnOnMargin": None,
        "InitMargin": init_margin,
        "StopPct": stop_pct,
        "IV_Entry": iv_entry,
        "HV_Entry": hv_entry,
        "IV_Rank": iv_rank,
        "IV_Percentile": iv_percentile,
        "VIX": vix,
        "ATR_14": atr14,
        "Skew": skew,
        "Spot": spot,
        "DaysInTrade": None,
        "Plan": plan,
        "Reden": reden,
        "Exitstrategie": exitstrategie,
        "Evaluatie": None,
        "Resultaat": None,
        "Opmerkingen": "",
        "Legs": legs,
        "Greeks_Entry": {
            "Delta": delta,
            "Gamma": gamma,
            "Vega": vega,
            "Theta": theta,
        },
    }

    add_trade(nieuwe_trade)

    print(f"\n✅ Trade {trade_id} succesvol toegevoegd aan journal.json")


if __name__ == "__main__":
    interactieve_trade_invoer()
