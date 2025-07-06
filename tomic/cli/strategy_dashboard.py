"""Portfolio dashboard that groups legs into strategies."""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import re

from tomic.config import get as cfg_get
from tomic.utils import today
from tomic.logutils import setup_logging, logger
from tomic.helpers.account import _fmt_money, print_account_overview
from tomic.analysis.strategy import group_strategies
from tomic.analysis.metrics import compute_term_structure, render_kpi_box
from tomic.journal.utils import load_journal, load_json, save_json
from .strategy_data import ALERT_PROFILE, get_strategy_description
from tomic.analysis.greeks import compute_portfolio_greeks

setup_logging()


def refresh_portfolio_data() -> None:
    """Fetch latest portfolio data via the IB API and update timestamp."""
    from tomic.api import getaccountinfo

    logger.info("🔄 Vernieuw portfolio data via getaccountinfo")
    try:
        getaccountinfo.main()
    except Exception as exc:  # pragma: no cover - network/IB errors
        logger.error(f"❌ Fout bij ophalen portfolio: {exc}")
        return

    meta_path = Path(cfg_get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
    try:
        meta_path.write_text(json.dumps({"last_update": datetime.now().isoformat()}))
    except OSError as exc:  # pragma: no cover - I/O errors
        logger.error(f"⚠️ Kan meta file niet schrijven: {exc}")


def maybe_refresh_portfolio(refresh: bool) -> None:
    """Refresh portfolio when requested or data files are missing."""

    positions_path = Path(cfg_get("POSITIONS_FILE", "positions.json"))
    account_path = Path(cfg_get("ACCOUNT_INFO_FILE", "account_info.json"))
    if refresh or not (positions_path.exists() and account_path.exists()):
        refresh_portfolio_data()


def load_positions(path: str):
    """Load positions JSON file and return list of open positions."""
    data = load_json(path)
    return [p for p in data if p.get("position")]


def load_account_info(path: str) -> dict:
    """Load account info JSON file and return as dict."""
    if not os.path.exists(path):
        return {}
    try:
        return load_json(path)
    except json.JSONDecodeError as e:
        print(f"⚠️ Kan accountinfo niet laden uit {path}: {e}")
        return {}


def print_account_summary(values: dict, portfolio: dict) -> None:
    """Print concise one-line account overview with icons."""
    net_liq = values.get("NetLiquidation")
    margin = values.get("InitMarginReq")
    used_pct = None
    try:
        used_pct = (float(margin) / float(net_liq)) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        used_pct = None
    delta = portfolio.get("Delta")
    vega = portfolio.get("Vega")
    parts = [
        f"💰 Netliq: {_fmt_money(net_liq)}",
        f"🏦 Margin used: {_fmt_money(margin)}",
    ]
    parts.append(f"📉 Δ: {delta:+.2f}" if delta is not None else "📉 Δ: n.v.t.")
    parts.append(f"📈 Vega: {vega:+.0f}" if vega is not None else "📈 Vega: n.v.t.")
    if used_pct is not None:
        parts.append(f"📦 Used: {used_pct:.0f}%")
    print("=== ACCOUNT ===")
    print(" | ".join(parts))


def extract_exit_rules(path: str):
    """Parse journal.json and return exit thresholds per trade."""
    journal = load_journal(path)
    rules = {}
    for trade in journal:
        sym = trade.get("Symbool")
        expiry = trade.get("Expiry")
        text = trade.get("Exitstrategie", "")
        if not sym or not expiry or not text:
            continue
        rule = {"premium_entry": trade.get("Premium")}
        txt = text.replace(",", ".")
        m = re.search(r"onder\s*~?([0-9]+(?:\.[0-9]+)?)", txt, re.I)
        if m:
            rule["spot_below"] = float(m.group(1))
        m = re.search(r"boven\s*~?([0-9]+(?:\.[0-9]+)?)", txt, re.I)
        if m:
            rule["spot_above"] = float(m.group(1))
        m = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", txt)
        if m:
            rule["premium_target"] = float(m.group(1))
            if (
                isinstance(rule.get("premium_entry"), (int, float))
                and rule["premium_entry"]
            ):
                rule["target_profit_pct"] = (
                    (rule["premium_entry"] - rule["premium_target"])
                    / rule["premium_entry"]
                ) * 100
        m = re.search(r"(\d+)\s*dagen", txt, re.I)
        if m:
            rule["days_before_expiry"] = int(m.group(1))
        rules[(sym, expiry)] = rule
    return rules


def sort_legs(legs):
    """Return legs sorted by option type and position."""
    type_order = {"P": 0, "C": 1}

    def key(leg):
        right = leg.get("right") or leg.get("type")
        pos = leg.get("position", 0)
        return (
            type_order.get(right, 2),
            0 if pos < 0 else 1,
            leg.get("strike", 0),
        )

    return sorted(legs, key=key)


def trade_id_key(value) -> float:
    """Return sortable numeric key for ``value`` used as trade id."""
    if value is None:
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


# Mapping of leg characteristics to emoji symbols

SYMBOL_MAP = {
    ("P", -1): "🔴",  # short put
    ("P", 1): "🔵",  # long put
    ("C", -1): "🟡",  # short call
    ("C", 1): "🟢",  # long call
}

# Severity scoring based on emoji markers
SEVERITY_MAP = {"🚨": 3, "⚠️": 2, "🔻": 2, "🟡": 1, "✅": 1, "🟢": 1}


def alert_category(alert: str) -> str:
    """Return rough category tag for an alert string."""
    lower = alert.lower()
    if "delta" in lower:
        return "delta"
    if "vega" in lower:
        return "vega"
    if "theta" in lower:
        return "theta"
    if "iv" in lower:
        return "iv"
    if "skew" in lower:
        return "skew"
    if "rom" in lower:
        return "rom"
    if "pnl" in lower or "winst" in lower or "verlies" in lower:
        return "pnl"
    if "dagen" in lower or "exp" in lower:
        return "dte"
    return "other"


def alert_severity(alert: str) -> int:
    """Return numeric severity for sorting."""
    for key, val in SEVERITY_MAP.items():
        if key in alert:
            return val
    return 0


def print_strategy_full(strategy, rule=None, *, details: bool = False):
    """Print a strategy with entry info, current status, KPI box and alerts."""
    pnl = strategy.get("unrealizedPnL")
    color = "🟩" if pnl is not None and pnl >= 0 else "🟥"
    header = f"{color} {strategy['symbol']} – {strategy['type']}"
    if strategy.get("trade_id") is not None:
        header += f" - TradeId {strategy['trade_id']}"
    print(header)
    desc = get_strategy_description(strategy.get("type"), strategy.get("delta"))
    if desc:
        print(f"ℹ️ {desc}")

    print("📌 ENTRY-INFORMATIE")
    entry_lines: list[str] = []
    spot_open = strategy.get("spot_open")
    if spot_open is not None:
        try:
            entry_lines.append(f"📍 Spot bij open: {float(spot_open):.2f}")
        except (TypeError, ValueError):
            entry_lines.append(f"📍 Spot bij open: {spot_open}")
    parts_main: list[str] = []
    parts_extra: list[str] = []
    iv = strategy.get("iv_entry")
    hv = strategy.get("hv_entry")
    ivr = strategy.get("ivrank_entry")
    ivp = strategy.get("ivpct_entry")
    vix = strategy.get("vix_entry")
    skew = strategy.get("skew_entry")
    term = strategy.get("term_slope")
    atr = strategy.get("atr_entry")
    if iv is not None:
        parts_main.append(f"IV {iv:.2f}%")
    if hv is not None:
        parts_main.append(f"HV {hv:.2f}%")
    if ivr is not None:
        parts_main.append(f"IV Rank: {ivr:.1f}")
    if ivp is not None:
        parts_main.append(f"IV Pctl: {ivp:.1f}")
    if vix is not None:
        parts_extra.append(f"VIX {vix:.2f}")
    if skew is not None:
        parts_extra.append(f"Skew {skew*100:.1f}bp")
    if term is not None:
        parts_extra.append(f"Term {term*100:.1f}bp")
    if atr is not None:
        parts_extra.append(f"ATR {atr:.2f}")
    if parts_main:
        entry_lines.append("📍 " + " | ".join(parts_main))
    if parts_extra:
        entry_lines.append("📍 " + " | ".join(parts_extra))
    delta_entry = strategy.get("delta_entry")
    gamma_entry = strategy.get("gamma_entry")
    vega_entry = strategy.get("vega_entry")
    theta_entry = strategy.get("theta_entry")
    delta = strategy.get("delta")
    gamma = strategy.get("gamma")
    vega = strategy.get("vega")
    theta = strategy.get("theta")
    if any(x is not None for x in (delta_entry, gamma_entry, vega_entry, theta_entry)):
        entry_lines.append(
            "📍 "
            f"Delta: {delta_entry:+.3f} | "
            f"Gamma: {gamma_entry:+.3f} | "
            f"Vega: {vega_entry:+.3f} | "
            f"Theta: {theta_entry:+.3f}"
        )
    elif any(x is not None for x in (delta, gamma, vega, theta)):
        entry_lines.append(
            "📍 "
            f"Delta: {delta:+.3f} | "
            f"Gamma: {gamma:+.3f} | "
            f"Vega: {vega:+.3f} | "
            f"Theta: {theta:+.3f}"
        )
    rom_entry = strategy.get("rom_entry")
    if rom_entry is not None:
        entry_lines.append(f"📍 ROM bij instap: {rom_entry:+.1f}%")
    max_p = strategy.get("max_profit")
    max_l = strategy.get("max_loss")
    rr = strategy.get("risk_reward")
    if max_p is not None and max_l is not None:
        rr_disp = f" (R/R {rr:.2f})" if rr is not None else ""
        entry_lines.append(
            f"📍 Max winst {_fmt_money(max_p)} | Max verlies {_fmt_money(max_l)}{rr_disp}"
        )
    dte_entry = strategy.get("dte_entry")
    if dte_entry is not None:
        entry_lines.append(f"📍 DTE bij opening: {dte_entry} dagen")
    for line in entry_lines:
        print(line)
    print()

    print("📈 HUIDIGE POSITIE")
    mgmt_lines: list[str] = []
    spot_now = strategy.get("spot_current") or strategy.get("spot")
    if spot_now is not None or spot_open is not None:
        parts = []
        if spot_now is not None:
            try:
                spot_now_float = float(spot_now)
                spot_now_str = f"{spot_now_float:.2f}"
            except (TypeError, ValueError):
                spot_now_str = str(spot_now)
            diff_pct = None
            if spot_open not in (None, 0, "0"):
                try:
                    diff_pct = (
                        (float(spot_now) - float(spot_open)) / float(spot_open)
                    ) * 100
                except (TypeError, ValueError, ZeroDivisionError):
                    diff_pct = None
            if diff_pct is not None:
                parts.append(f"Huidige spot: {spot_now_str} ({diff_pct:+.2f}%)")
            else:
                parts.append(f"Huidige spot: {spot_now_str}")
        if spot_open is not None:
            try:
                spot_open_str = f"{float(spot_open):.2f}"
            except (TypeError, ValueError):
                spot_open_str = str(spot_open)
            parts.append(f"Spot bij open: {spot_open_str}")
        mgmt_lines.append("📍 " + " | ".join(parts))
    delta_fmt = f"{delta:+.3f}" if delta is not None else "n.v.t."
    gamma_fmt = f"{gamma:+.3f}" if gamma is not None else "n.v.t."
    vega_fmt = f"{vega:+.3f}" if vega is not None else "n.v.t."
    theta_fmt = f"{theta:+.3f}" if theta is not None else "n.v.t."
    mgmt_lines.append(
        f"📍 Delta: {delta_fmt} "
        f"Gamma: {gamma_fmt} "
        f"Vega: {vega_fmt} "
        f"Theta: {theta_fmt}"
    )
    iv_avg = strategy.get("avg_iv")
    hv = strategy.get("HV30")
    ivhv = strategy.get("iv_hv_spread")
    skew = strategy.get("skew")
    term = strategy.get("term_slope")
    ivr = strategy.get("IV_Rank")
    ivp = strategy.get("IV_Percentile")
    parts = []
    if iv_avg is not None:
        parts.append(f"IV {iv_avg:.2%}")
    if hv is not None:
        parts.append(f"HV {hv:.2f}%")
    if ivr is not None:
        parts.append(f"IV Rank: {ivr:.1f}")
    if ivp is not None:
        parts.append(f"IV Pctl: {ivp:.1f}")
    if ivhv is not None:
        parts.append(f"IV-HV {ivhv:.2%}")
    if skew is not None:
        parts.append(f"Skew {skew*100:.1f}bp")
    if term is not None:
        parts.append(f"Term {term*100:.1f}bp")
    if parts:
        mgmt_lines.append("📍 " + " | ".join(parts))
    days_line: list[str] = []
    dte = strategy.get("days_to_expiry")
    dit = strategy.get("days_in_trade")
    if dte is not None:
        days_line.append(f"{dte}d tot exp")
    if dit is not None:
        days_line.append(f"{dit}d in trade")
    if days_line:
        mgmt_lines.append("📍 " + " | ".join(days_line))

    cost_basis = strategy.get("cost_basis")
    if cost_basis is not None:
        total_contracts = sum(
            abs(leg.get("position", 0)) * float(leg.get("multiplier") or 1)
            for leg in strategy.get("legs", [])
        )
        if total_contracts:
            avg_price = cost_basis / total_contracts
            mgmt_lines.append(f"📍 Gem. prijs: {avg_price:+.2f}")

    pnl_val = strategy.get("unrealizedPnL")
    if pnl_val is not None:
        margin_ref = strategy.get("init_margin") or strategy.get("margin_used") or 1000
        rom_now = (pnl_val / margin_ref) * 100
        mgmt_lines.append(f"📍 PnL: {pnl_val:+.2f} (ROM: {rom_now:+.1f}%)")
    spot = strategy.get("spot", 0)
    delta_dollar = strategy.get("delta_dollar")
    if delta is not None and spot and delta_dollar is not None:
        try:
            spot_fmt = f"{float(spot):.2f}"
        except (TypeError, ValueError):
            spot_fmt = str(spot)
        mgmt_lines.append(
            f"📍 Delta exposure ≈ ${delta_dollar:,.0f} bij spot {spot_fmt}"
        )
    margin = strategy.get("init_margin") or strategy.get("margin_used") or 1000
    if theta is not None and margin:
        theta_efficiency = abs(theta / margin) * 100
        if theta_efficiency < 0.5:
            rating = "⚠️ oninteressant"
        elif theta_efficiency < 1.5:
            rating = "🟡 acceptabel"
        elif theta_efficiency < 2.5:
            rating = "✅ goed"
        else:
            rating = "🟢 ideaal"
        mgmt_lines.append(
            f"📍 Theta-rendement: {theta_efficiency:.2f}% per $1.000 margin - {rating}"
        )
    for line in mgmt_lines:
        print(line)
    print()

    print("📊 KPI BOX")
    print(render_kpi_box(strategy))
    print()

    exit_text = strategy.get("exit_strategy")
    if exit_text:
        print("🚪 EXITCRITERIA")
        for line in str(exit_text).strip().splitlines():
            print(f"  {line}")

    alerts = list(strategy.get("entry_alerts", [])) + list(strategy.get("alerts", []))
    if rule:
        spot = strategy.get("spot")
        pnl_val = strategy.get("unrealizedPnL")
        if spot is not None:
            if rule.get("spot_below") is not None and spot < rule["spot_below"]:
                alerts.append(
                    f"🚨 Spot {spot:.2f} onder exitniveau {rule['spot_below']}"
                )
            if rule.get("spot_above") is not None and spot > rule["spot_above"]:
                alerts.append(
                    f"🚨 Spot {spot:.2f} boven exitniveau {rule['spot_above']}"
                )
        if (
            pnl_val is not None
            and rule.get("target_profit_pct") is not None
            and rule.get("premium_entry")
        ):
            profit_pct = (pnl_val / (rule["premium_entry"] * 100)) * 100
            if profit_pct >= rule["target_profit_pct"]:
                alerts.append(
                    f"🚨 PnL {profit_pct:.1f}% >= target {rule['target_profit_pct']:.1f}%"
                )

    profile = ALERT_PROFILE.get(strategy.get("type"))
    if profile is not None:
        alerts = [a for a in alerts if alert_category(a) in profile]
    alerts = list(dict.fromkeys(alerts))  # dedupe while preserving order
    alerts.sort(key=alert_severity, reverse=True)

    print("🚨 ALERTS")
    if alerts:
        for alert in alerts[:3]:
            print(f"- {alert}")
    else:
        print("- \u2139\ufe0f Geen directe aandachtspunten gedetecteerd")

    if details:
        print("📎 Leg-details:")
        for leg in sort_legs(strategy.get("legs", [])):
            side = "Long" if leg.get("position", 0) > 0 else "Short"
            right = leg.get("right") or leg.get("type")
            symbol = SYMBOL_MAP.get(
                (right, 1 if leg.get("position", 0) > 0 else -1), "▫️"
            )

            qty = abs(leg.get("position", 0))
            print(
                f"  {symbol} {right} {leg.get('strike')} ({side}) - {qty} contract{'s' if qty != 1 else ''}"
            )

            d = leg.get("delta")
            g = leg.get("gamma")
            v = leg.get("vega")
            t = leg.get("theta")
            d_disp = f"{d:.3f}" if d is not None else "–"
            g_disp = f"{g:.3f}" if g is not None else "–"
            v_disp = f"{v:.3f}" if v is not None else "–"
            t_disp = f"{t:.3f}" if t is not None else "–"
            print(f"    Delta: {d_disp} Gamma: {g_disp} Vega: {v_disp} Theta: {t_disp}")
        print()

    print()


def print_strategy_compact(strategy: dict) -> None:
    """Print one-line summary of a strategy."""
    symbol = strategy.get("symbol")
    typ = strategy.get("type")
    pnl = strategy.get("unrealizedPnL", 0)
    dte = strategy.get("days_to_expiry", "n.v.t.")
    rom = strategy.get("rom")
    delta_dollar = strategy.get("delta_dollar")
    alerts = strategy.get("alerts", [])
    alert_count = sum(alert_severity(a) > 0 for a in alerts)
    icon = "🟩" if pnl >= 0 else "🟥"
    rom_disp = f"{rom:+.1f}%" if rom is not None else "n.v.t."
    pnl_disp = f"{pnl:+.2f}" if pnl is not None else "n.v.t."
    dte_disp = f"{dte}d" if isinstance(dte, int) else str(dte)
    dd_disp = f"{delta_dollar:+.0f}" if delta_dollar is not None else "n.v.t."
    print(
        f"{icon} {symbol} | {typ} | ROM {rom_disp} | PnL {pnl_disp} | DTE {dte_disp} | Δ$ {dd_disp} | ⚠️ {alert_count} alerts"
    )


def print_strategy_alerts(strategy: dict) -> None:
    """Print alerts for a strategy if any have positive severity."""
    alerts = strategy.get("alerts", [])
    if not any(alert_severity(a) > 0 for a in alerts):
        return
    symbol = strategy.get("symbol")
    typ = strategy.get("type")
    trade_id = strategy.get("trade_id")
    header = f"🚨 {symbol} – {typ}"
    if trade_id:
        header += f" – TradeId {trade_id}"
    print(header)
    for alert in sorted(alerts, key=alert_severity, reverse=True)[:3]:
        print(f"- {alert}")
    print()


def print_strategy(strategy, rule=None, *, details: bool = False):
    """Deprecated wrapper for :func:`print_strategy_full`."""
    return print_strategy_full(strategy, rule=rule, details=details)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    json_output = None
    args = []
    details = False
    account_details = False
    refresh = False
    view_mode = "full"
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json-output":
            if i + 1 >= len(argv):
                print(
                    "Gebruik: python -m tomic.cli.strategy_dashboard positions.json [account_info.json] [--json-output PATH] [--refresh]"
                )
                return 1
            json_output = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--json-output="):
            json_output = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--details":
            details = True
            i += 1
            continue
        if arg == "--refresh":
            refresh = True
            i += 1
            continue
        if arg.startswith("--view="):
            view_mode = arg.split("=")[1]
            i += 1
            continue
        if arg == "--account":
            account_details = True
            i += 1
            continue
        args.append(arg)
        i += 1

    print(f"🧭 Weergavemodus geactiveerd: {view_mode}")

    if not args:
        print(
            "Gebruik: python -m tomic.cli.strategy_dashboard positions.json [account_info.json] [--json-output PATH] [--refresh]"
        )
        return 1

    positions_file = args[0]
    account_file = (
        args[1] if len(args) > 1 else cfg_get("ACCOUNT_INFO_FILE", "account_info.json")
    )
    journal_file = cfg_get("JOURNAL_FILE", "journal.json")

    maybe_refresh_portfolio(refresh)

    positions = load_positions(positions_file)
    account_info = load_account_info(account_file)
    journal = load_journal(journal_file)
    exit_rules = extract_exit_rules(journal_file)

    # totaal gerealiseerd resultaat uit TWS-posities
    realized_profit = 0.0
    for pos in positions:
        rpnl = pos.get("realizedPnL")
        if isinstance(rpnl, (int, float)) and abs(rpnl) < 1e307:
            realized_profit += rpnl

    if account_info is not None:
        account_info = dict(account_info)
        account_info["RealizedProfit"] = realized_profit

    portfolio = compute_portfolio_greeks(positions)
    if account_info:
        print_account_summary(account_info, portfolio)
        if account_details:
            print_account_overview(account_info)
    print()

    strategies = group_strategies(positions, journal)
    strategies.sort(key=lambda s: trade_id_key(s.get("trade_id")))
    compute_term_structure(strategies)
    type_counts = defaultdict(int)
    total_delta_dollar = 0.0
    total_vega = 0.0
    dtes = []
    total_pnl = 0.0
    total_margin = 0.0
    for s in strategies:
        type_counts[s.get("type")] += 1
        if s.get("delta_dollar") is not None:
            total_delta_dollar += s["delta_dollar"]
        if s.get("vega") is not None:
            total_vega += s["vega"]
        if s.get("days_to_expiry") is not None:
            dtes.append(s["days_to_expiry"])
        pnl_val = s.get("unrealizedPnL")
        margin_ref = s.get("init_margin") or s.get("margin_used") or 1000
        if pnl_val is not None:
            total_pnl += pnl_val
            total_margin += margin_ref

    avg_rom = (total_pnl / total_margin) * 100 if total_margin else 0.0

    print("=== Portfolio-overzicht ===")
    print(f"- Aantal strategieën: {len(strategies)}")
    print(f"- Gemiddeld ROM: {avg_rom:.1f}%")
    print(f"- Netto Δ$: ${total_delta_dollar:,.0f}")
    print(f"- Totale vega: {total_vega:+.2f}")
    if dtes:
        avg_dte = sum(dtes) / len(dtes)
        print(f"- Gemiddelde DTE: {avg_dte:.1f} dagen")
    print()

    global_alerts = []
    portfolio_vega = portfolio.get("Vega")
    if portfolio_vega is not None:
        abs_vega = abs(portfolio_vega)
        if abs_vega > 10000:
            global_alerts.append(
                "🚨 Totale Vega-exposure > 10.000 - gevoelig voor systematische vol-bewegingen"
            )
        elif abs_vega > 5000:
            global_alerts.append(
                "⚠️ Totale Vega-exposure > 5.000 - gevoelig voor systematische vol-bewegingen"
            )

    if strategies:
        total_strats = len(strategies)
        major_type, major_count = max(type_counts.items(), key=lambda x: x[1])
        pct = (major_count / total_strats) * 100
        if pct >= 80:
            global_alerts.append(
                f"⚠️ Strategieclustering: {major_count}x {major_type} van {total_strats} strategieën ({pct:.1f}%) - overweeg meer spreiding"
            )

    if global_alerts:
        global_alerts.sort(key=alert_severity, reverse=True)
        for alert in global_alerts[:3]:
            print(alert)
    
    print("=== Open posities ===")
    for s in strategies:
        rule = exit_rules.get((s["symbol"], s["expiry"]))
        if view_mode == "compact":
            print_strategy_compact(s)
        elif view_mode == "alerts":
            print_strategy_alerts(s)
        else:
            print_strategy_full(s, rule=rule, details=details)

    if json_output:
        strategies.sort(key=lambda s: (s["symbol"], s.get("expiry")))
        data = {
            "analysis_date": str(today()),
            "account_info": account_info,
            "portfolio_greeks": portfolio,
            "strategies": strategies,
            "global_alerts": global_alerts,
        }
        try:
            save_json(data, json_output)
        except OSError as e:
            print(f"❌ Kan niet schrijven naar {json_output}: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
