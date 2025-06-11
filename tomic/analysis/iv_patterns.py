"""Regular expression patterns for implied volatility scraping."""

IV_PATTERNS = {
    "iv_rank": [
        r"IV\s*&nbsp;?Rank:</span>\s*<span><strong>([0-9]+(?:\.[0-9]+)?)%",
        r"IV\s*Rank[^0-9]*([0-9]+(?:\.[0-9]+)?)",
    ],
    "implied_volatility": [
        r"Implied\s*&nbsp;?Volatility:</span>.*?<strong>([0-9]+(?:\.[0-9]+)?)%",
        r"Implied\s+Volatility[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
    ],
    "iv_percentile": [
        r"IV\s*&nbsp;?Percentile:</span>.*?<strong>([0-9]+(?:\.[0-9]+)?)%",
        r"IV\s*Pctl:</span>.*?<strong>([0-9]+(?:\.[0-9]+)?)%",
    ],
}

EXTRA_PATTERNS = {
    "spot_price": [
        r"\"lastPrice\":\s*([0-9]+(?:\.[0-9]+)?)",
        r"Last Price[^0-9]*([0-9]+(?:\.[0-9]+)?)",
    ],
    "hv30": [
        r"30[- ]Day Historical Volatility[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
        r"HV\s*30[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
        r"Historic\s*&nbsp;?Volatility[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
        r"HV:\s*</span>\s*</span>\s*<span><strong>([0-9]+(?:\.[0-9]+)?)%",
    ],
    "skew": [
        r"Skew[^%]*?(-?[0-9]+(?:\.[0-9]+)?)%",
    ],
    "atr14": [
        r"ATR\s*\(14\)[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        r"ATR\s*14[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        r"(?:Average\s*True\s*Range|ATR)\s*(?:\(14\)|14)[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        r"ATR(?:\s*\(14\))?:</span>\s*</span>\s*<span><strong>([0-9]+(?:\.[0-9]+)?)",
    ],
    "vix": [
        r"VIX[^0-9]*([0-9]+(?:\.[0-9]+)?)",
    ],
}
