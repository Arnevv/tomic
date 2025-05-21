import json
from datetime import date
from pathlib import Path

journal_file = Path("journal.json")

if not journal_file.exists():
    with open(journal_file, "w", encoding="utf-8") as f:
        json.dump([], f)

def float_prompt(prompt_tekst, default=None):
    while True:
        val = input(prompt_tekst).strip().replace(",", ".")
        if val == "" and default is not None:
            return default
        try:
            return float(val)
        except:
            print("❌ Ongeldige invoer, gebruik bijv. 14.7")

def get_next_trade_id(journal):
    existing_ids = [int(trade["TradeID"]) for trade in journal if str(trade["TradeID"]).isdigit()]
    return str(max(existing_ids + [0]) + 1)

def date_prompt(prompt_tekst):
    while True:
        val = input(prompt_tekst).strip()
        try:
            date.fromisoformat(val)
            return val
        except ValueError:
            print("❌ Ongeldige datum. Gebruik het formaat YYYY-MM-DD met streepjes.")

def interactieve_trade_invoer():
    print("\n🆕 Nieuwe Trade Invoeren (meerdere legs ondersteund)\nLaat een veld leeg om af te breken.\n")

    with open(journal_file, "r", encoding="utf-8") as f:
        journal = json.load(f)

    trade_id = get_next_trade_id(journal)
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

        legs.append({
            "strike": strike,
            "type": right,
            "action": action,
            "qty": qty
        })

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

    print("\n📊 Vul marktdata in (gebruik altijd dezelfde bronnen):")
    spot = float_prompt("  Spotprijs (https://marketchameleon.com/Overview/SPY/Summary): ")
    iv_entry = float_prompt("  IV30 (https://marketchameleon.com/Overview/SPY/Summary): ")
    iv_rank = float_prompt("  IV Rank (https://marketchameleon.com/Overview/SPY/Summary): ")
    hv_entry = float_prompt("  HV30 (https://www.alphaquery.com/stock/SPY/volatility-option-statistics/30-day/historical-volatility): ")
    vix = float_prompt("  VIX (https://www.barchart.com/stocks/quotes/$VIX/technical-analysis): ")
    atr14 = float_prompt("  ATR(14) (https://www.barchart.com/etfs-funds/quotes/SPY/technical-analysis): ")
    print("  Skew wordt berekend als: IV 25D call – IV 25D put (bijv. 12.8 – 17 = -4.2)")
    iv_call = float_prompt("    IV 25D CALL: ")
    iv_put = float_prompt("    IV 25D PUT: ")
    skew = round(iv_call - iv_put, 2)

    print("\n📐 Vul de NETTO Greeks in van de hele positie bij entry (optioneel):")
    print("ℹ️ Dit zijn GEAGGREGEERDE waarden van de gehele trade, NIET per leg of strike")
    delta = float_prompt("  Delta: ", default=None)
    theta = float_prompt("  Theta: ", default=None)
    gamma = float_prompt("  Gamma: ", default=None)
    vega = float_prompt("  Vega: ", default=None)

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
        "StopPct": stop_pct,
        "IV_Entry": iv_entry,
        "HV_Entry": hv_entry,
        "IV_Rank": iv_rank,
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
            "Theta": theta,
            "Gamma": gamma,
            "Vega": vega
        }
    }

    journal.append(nieuwe_trade)

    with open(journal_file, "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2)

    print(f"\n✅ Trade {trade_id} succesvol toegevoegd aan journal.json")

if __name__ == "__main__":
    interactieve_trade_invoer()