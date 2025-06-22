from __future__ import annotations

"""Stealth scrape van MarketChameleon met undetected-chromedriver.."""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from tomic.logutils import logger, setup_logging
from tomic.config import get as cfg_get

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _extract(html: str, labels: List[str]) -> Optional[float]:
    for label in labels:
        pattern = rf"{re.escape(label)}[^0-9-]*(-?[0-9]+(?:\.[0-9]+)?)"
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None

def parse_iv_html(html: str) -> Dict[str, Optional[float]]:
    return {
        "spot_price": _extract(html, ["LastPrice", "Last Price"]),
        "iv30": _extract(html, ["30-Day IV", "IV30"]),
        "iv_rank": _extract(html, ["IV30 % Rank", "IV Rank"]),
        "hv_20": _extract(html, ["20-Day HV"]),
        "hv_252": _extract(html, ["1-Year HV"]),
    }

def parse_skew_html(html: str) -> Optional[float]:
    val = _extract(html, ["Skew"])
    if val is not None:
        return val
    match = re.search(r"skewData[^0-9-]*(-?[0-9]+(?:\.[0-9]+)?)", html, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

# ---------------------------------------------------------------------------
# Stealth Selenium helpers
# ---------------------------------------------------------------------------

def load_credentials(path: Path = Path(".env")) -> tuple[str, str]:
    env: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            env[key.strip()] = val.strip()
    user = os.getenv("MC_USERNAME", env.get("MC_USERNAME"))
    pwd = os.getenv("MC_PASSWORD", env.get("MC_PASSWORD"))
    if not user or not pwd:
        raise RuntimeError("MC_USERNAME and MC_PASSWORD required")
    return user, pwd

def create_driver():
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )

    driver = uc.Chrome(options=options)
    return driver

def login(driver, username: str, password: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    logger.info("Inloggen bij MarketChameleon")
    driver.get("https://marketchameleon.com/Account/Login")
    wait = WebDriverWait(driver, 15)
    email = wait.until(EC.presence_of_element_located((By.NAME, "Email or Username")))
    passwd = driver.find_element(By.NAME, "Password")
    email.clear()
    email.send_keys(username)
    passwd.clear()
    passwd.send_keys(password)
    passwd.send_keys(Keys.RETURN)
    wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'Logout')]")))
    logger.debug("✅ Login gelukt")

def fetch_symbol_metrics(driver, symbol: str) -> Dict[str, Optional[float]]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    logger.info(f"Verzamel data voor {symbol}")
    base = "https://marketchameleon.com/Overview"
    iv_url = f"{base}/{symbol}/IV"
    skew_url = f"{base}/{symbol}/VolatilitySkew/"
    wait = WebDriverWait(driver, 10)

    driver.get(iv_url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    iv_html = driver.page_source
    metrics = parse_iv_html(iv_html)

    driver.get(skew_url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    skew_html = driver.page_source
    metrics["skew"] = parse_skew_html(skew_html)

    return metrics

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: List[str] | None = None) -> None:
    if argv is None:
        argv = []
    setup_logging()
    logger.info("🚀 MarketChameleon scrape gestart")

    symbols = [s.upper() for s in cfg_get("SYMBOLS", [])] or [
        s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])
    ]
    out_path = Path("marketchameleon_metrics.json")

    try:
        username, password = load_credentials()
    except Exception as exc:
        logger.error(f"Geen inloggegevens: {exc}")
        return

    results: Dict[str, Dict[str, Optional[float]]] = {}
    driver = create_driver()
    try:
        try:
            login(driver, username, password)
        except Exception as exc:
            logger.error(f"❌ Login mislukt: {exc}")
            return

        for sym in symbols:
            try:
                results[sym] = fetch_symbol_metrics(driver, sym)
            except Exception as exc:
                logger.error(f"Fout bij ophalen van {sym}: {exc}")
    finally:
        driver.quit()

    out_path.write_text(json.dumps(results, indent=2))
    logger.success(f"✅ Gegevens opgeslagen in {out_path}")

if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
