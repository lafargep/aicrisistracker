#!/usr/bin/env python3
"""
Citrini 2028 Global Intelligence Crisis — Tracking Dashboard
=============================================================
A comprehensive, auto-refreshing dashboard that tracks every company,
metric, and trend predicted in the Citrini Research memo.

Usage:
    pip install flask yfinance requests
    python citrini_dashboard_server.py

Then open http://localhost:8050 in your browser.

The dashboard auto-refreshes data every 5 minutes.
"""

import json
import os
import threading
import time
import logging
from datetime import datetime, timedelta

from flask import Flask, jsonify, Response

# ---------------------------------------------------------------------------
# Lazy-import helpers so the server can still start even if a lib is missing
# ---------------------------------------------------------------------------
try:
    import yfinance as yf
except ImportError:
    yf = None
    print("WARNING: yfinance not installed. Run: pip install yfinance")

try:
    import requests as req
except ImportError:
    req = None
    print("WARNING: requests not installed. Run: pip install requests")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REFRESH_INTERVAL_SEC = 300          # 5 minutes
PORT = 8050
FRED_API_KEY = os.environ.get("FRED_API_KEY", "b3b8d972fefb2133e4acc1dacf2825b4")  # Uses env var on Railway, falls back to key
                                    # Get one free at https://fred.stlouisfed.org/docs/api/api_key.html

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Memo-derived tracking configuration
# ---------------------------------------------------------------------------
STOCK_GROUPS = {
    "market_indices": {
        "label": "Market Indices",
        "icon": "trending_up",
        "tickers": {
            "^GSPC":  {"name": "S&P 500",           "prediction": "Peaks ~8,000 by Oct 2026, then -38% drawdown to ~4,960 by June 2028"},
            "^IXIC":  {"name": "Nasdaq Composite",   "prediction": "Breaks above 30,000 before crash"},
            "^TNX":   {"name": "10-Yr Treasury Yield","prediction": "Descends from 4.3% to 3.2% as bond market prices in consumption hit"},
        },
    },
    "ai_infrastructure": {
        "label": "AI Infrastructure (Winners)",
        "icon": "memory",
        "tickers": {
            "NVDA": {"name": "NVIDIA",       "prediction": "Record revenues persist; AI infra complex keeps performing"},
            "TSM":  {"name": "Taiwan Semi",  "prediction": "95%+ utilization; supply-chain beneficiary"},
            "GEV":  {"name": "GE Vernova",   "prediction": "Turbine capacity sold out through 2040; power demand winner"},
        },
    },
    "saas_disruption": {
        "label": "SaaS & Software (Disruption Zone)",
        "icon": "cloud_off",
        "tickers": {
            "NOW":  {"name": "ServiceNow",  "prediction": "Net-new ACV growth decelerates 23% → 14%; 15% workforce cut; shares -18%"},
            "CRM":  {"name": "Salesforce",   "prediction": "Multiple rounds of layoffs; AI-threatened incumbent"},
            "MNDY": {"name": "Monday.com",   "prediction": "Long-tail SaaS severely disrupted"},
            "ASAN": {"name": "Asana",        "prediction": "Long-tail SaaS severely disrupted"},
            "ZM":   {"name": "Zoom",         "prediction": "Workflow SaaS under pricing pressure"},
        },
    },
    "payments_intermediation": {
        "label": "Payments & Intermediation (Friction → Zero)",
        "icon": "payment",
        "tickers": {
            "MA":   {"name": "Mastercard",       "prediction": "Rev +6% Y/Y but purchase volume slows to +3.4%; shares -9%"},
            "V":    {"name": "Visa",             "prediction": "Drops but pares losses on stablecoin positioning"},
            "AXP":  {"name": "American Express", "prediction": "Hit hardest — white-collar customer base gutted + interchange bypass"},
            "SYF":  {"name": "Synchrony",        "prediction": "Falls 10%+ as card-interchange model threatened"},
            "COF":  {"name": "Capital One",      "prediction": "Falls 10%+ on consumer credit + interchange headwinds"},
            "DASH": {"name": "DoorDash",         "prediction": "Margins compress to near zero; market fragments from agent-enabled competition"},
        },
    },
    "india_it_services": {
        "label": "Indian IT Services (Export Crisis)",
        "icon": "language",
        "tickers": {
            "INFY":    {"name": "Infosys",    "prediction": "Contract cancellations accelerate through 2027"},
            "WIT":     {"name": "Wipro",      "prediction": "Contract cancellations accelerate through 2027"},
            "TCS.NS":  {"name": "TCS",        "prediction": "Contract cancellations as AI coding agents collapse cost arbitrage"},
        },
    },
    "crypto_stablecoins": {
        "label": "Crypto & Stablecoins (New Payment Rails)",
        "icon": "currency_bitcoin",
        "tickers": {
            "SOL-USD": {"name": "Solana",   "prediction": "Becomes primary stablecoin settlement layer for agentic commerce"},
            "ETH-USD": {"name": "Ethereum", "prediction": "L2s used for stablecoin settlement alongside Solana"},
        },
    },
    "consumer_discretionary": {
        "label": "Consumer & Real Estate (Demand Destruction)",
        "icon": "shopping_cart",
        "tickers": {
            "XLY":  {"name": "Consumer Disc. ETF", "prediction": "Consumer discretionary collapses as white-collar spending evaporates"},
            "BKNG": {"name": "Booking Holdings",   "prediction": "Travel platforms disrupted by agentic itinerary assembly"},
            "RDFN": {"name": "Redfin",             "prediction": "Real estate commissions compress from 3% to under 1%"},
        },
    },
    "pc_bdc_sector": {
        "label": "BDC Sector (Private Credit Proxy)",
        "icon": "account_balance",
        "tickers": {
            "BIZD": {"name": "VanEck BDC Income ETF",       "prediction": "Key proxy for overall BDC sector health; sharp drawdowns signal private credit stress"},
            "ARCC": {"name": "Ares Capital",                 "prediction": "Largest BDC; watch for NAV discounts and PIK income trends"},
            "MAIN": {"name": "Main Street Capital",          "prediction": "Lower middle-market lender; early indicator of small-firm distress"},
            "FSK":  {"name": "FS KKR Capital",               "prediction": "Significant non-accrual risk; watch dividend coverage ratio"},
            "BXSL": {"name": "Blackstone Secured Lending",   "prediction": "Blackstone's public BDC; proxy for institutional private credit sentiment"},
            "OBDC": {"name": "Blue Owl Capital (BDC)",       "prediction": "Technology-heavy lending book; vulnerable to software sector disruption"},
            "GSBD": {"name": "Goldman Sachs BDC",            "prediction": "Bank-affiliated BDC; watch for correlation with bank stress"},
        },
    },
    "pc_alt_managers": {
        "label": "Alternative Asset Managers (GP Side)",
        "icon": "business",
        "tickers": {
            "BX":   {"name": "Blackstone",        "prediction": "Largest alt manager; fundraising pace and AUM growth signal industry health"},
            "APO":  {"name": "Apollo Global",      "prediction": "Major private credit originator; watch credit quality and deployment pace"},
            "ARES": {"name": "Ares Management",    "prediction": "Pure-play credit manager; most direct private credit exposure"},
            "KKR":  {"name": "KKR & Co",           "prediction": "Expanding aggressively into private credit; watch leverage and deal flow"},
            "OWL":  {"name": "Blue Owl Capital",   "prediction": "Direct lending specialist; fundraising and deployment trends matter"},
        },
    },
    "pc_bank_exposure": {
        "label": "Banks with NBFI Exposure",
        "icon": "account_balance_wallet",
        "tickers": {
            "JPM": {"name": "JPMorgan Chase",   "prediction": "Largest bank NBFI lender; warehouse lines and SRT exposure key"},
            "GS":  {"name": "Goldman Sachs",     "prediction": "Major SRT originator and private credit partner"},
            "MS":  {"name": "Morgan Stanley",    "prediction": "Growing private credit partnerships; wealth channel exposure"},
            "C":   {"name": "Citigroup",         "prediction": "Significant NBFI credit lines; watch tightening signals"},
        },
    },
    "pc_credit_etfs": {
        "label": "Credit Market & Volatility ETFs",
        "icon": "show_chart",
        "tickers": {
            "HYG":  {"name": "iShares HY Corp Bond ETF",    "prediction": "Liquid high-yield proxy; spread widening signals stress"},
            "JNK":  {"name": "SPDR Bloomberg HY Bond ETF",  "prediction": "Alternative HY proxy; watch for outflows"},
            "BKLN": {"name": "Invesco Senior Loan ETF",     "prediction": "Leveraged loan health; floating-rate stress indicator"},
            "LQD":  {"name": "iShares IG Corp Bond ETF",    "prediction": "Investment grade liquidity; flight-to-quality signal"},
            "^VIX": {"name": "CBOE Volatility Index",       "prediction": "Market fear gauge; spikes above 30 signal systemic stress risk"},
        },
    },
    "pc_sector_concentration": {
        "label": "Sector Concentration Risk",
        "icon": "warning",
        "tickers": {
            "IGV":  {"name": "iShares Software ETF",        "prediction": "Software = 21-40% of private credit exposure; disruption triggers correlated defaults"},
            "XLK":  {"name": "Technology Select SPDR",       "prediction": "Broader tech health; impacts private credit collateral values"},
            "WCLD": {"name": "WisdomTree Cloud Computing",   "prediction": "Cloud/SaaS most exposed to AI seat-count disruption and private credit losses"},
        },
    },
}

# FRED series for economic data
FRED_SERIES = {
    "UNRATE":   {"name": "Unemployment Rate (%)",       "prediction": "Rises to 10.2% by June 2028", "format": "percent"},
    "ICSA":     {"name": "Initial Jobless Claims",      "prediction": "Surges to 487,000 (highest since April 2020)", "format": "thousands"},
    "JTSJOL":   {"name": "JOLTS Job Openings (000s)",   "prediction": "Falls below 5,500 (-15% YoY)", "format": "thousands"},
    "PSAVERT":  {"name": "Personal Savings Rate (%)",   "prediction": "Ticks higher as employed professionals fear layoffs", "format": "percent"},
    "DPCERAM1M225NBEA": {"name": "Real PCE Growth (%)", "prediction": "Consumer economy (70% of GDP) contracts", "format": "percent"},
    "A191RL1Q225SBEA":  {"name": "Real GDP Growth (%)", "prediction": "Two consecutive quarters of negative growth by Q2 2027", "format": "percent"},
    "BAMLH0A0HYM2":     {"name": "HY Credit Spread (bps)", "prediction": "Widens as PE-backed software defaults cascade", "format": "bps"},
    "DEXINUS":  {"name": "USD/INR Exchange Rate",       "prediction": "Rupee falls 18% as IT services surplus evaporates", "format": "rate"},
    "BAMLH0A3HYC":      {"name": "CCC & Lower HY Spread (bps)", "prediction": "Distressed-tier spread; spike signals imminent default wave in weakest credits", "format": "bps"},
    "DRTSCILM":         {"name": "Loan Officer Survey: C&I Tightening (%)", "prediction": "Rising = banks pulling back lending to large/mid firms; liquidity squeeze for private credit borrowers", "format": "percent"},
    "DGS10":            {"name": "10-Year Treasury Yield (%)", "prediction": "Higher-for-longer compresses interest coverage for floating-rate borrowers", "format": "percent"},
    "FEDFUNDS":         {"name": "Fed Funds Rate (%)", "prediction": "Persistent elevation increases debt servicing burden across private credit portfolios", "format": "percent"},
    "RRPONTSYD":        {"name": "Overnight Reverse Repo ($B)", "prediction": "Declining = tightening liquidity conditions; less cash buffer in financial system", "format": "billions"},
    "WRESBAL":          {"name": "Reserve Balances at Fed ($B)", "prediction": "Shrinking reserves reduce system-wide liquidity cushion", "format": "billions"},
}

# ---------------------------------------------------------------------------
# Data Store
# ---------------------------------------------------------------------------
data_store = {
    "stocks": {},
    "economic": {},
    "last_updated": None,
    "errors": [],
}


def fetch_stock_data():
    """Fetch current stock data using yfinance."""
    if yf is None:
        return {}

    all_tickers = []
    for group in STOCK_GROUPS.values():
        all_tickers.extend(group["tickers"].keys())

    results = {}
    try:
        tickers_str = " ".join(all_tickers)
        log.info(f"Fetching stock data for {len(all_tickers)} tickers...")
        data = yf.download(tickers_str, period="6mo", interval="1d", group_by="ticker", progress=False, threads=True)

        for ticker in all_tickers:
            try:
                if len(all_tickers) == 1:
                    df = data
                else:
                    df = data[ticker] if ticker in data.columns.get_level_values(0) else None

                if df is not None and not df.empty:
                    df = df.dropna(subset=["Close"])
                    if len(df) == 0:
                        continue
                    current = float(df["Close"].iloc[-1])
                    prev_close = float(df["Close"].iloc[-2]) if len(df) > 1 else current

                    # Calculate various return periods
                    day_change = ((current - prev_close) / prev_close) * 100 if prev_close else 0

                    # 1 month return
                    mo1_idx = max(0, len(df) - 22)
                    mo1_price = float(df["Close"].iloc[mo1_idx])
                    mo1_return = ((current - mo1_price) / mo1_price) * 100 if mo1_price else 0

                    # 3 month return
                    mo3_idx = max(0, len(df) - 66)
                    mo3_price = float(df["Close"].iloc[mo3_idx])
                    mo3_return = ((current - mo3_price) / mo3_price) * 100 if mo3_price else 0

                    # 6 month return
                    mo6_price = float(df["Close"].iloc[0])
                    mo6_return = ((current - mo6_price) / mo6_price) * 100 if mo6_price else 0

                    # 52-week high/low from available data
                    high_52w = float(df["High"].max())
                    low_52w = float(df["Low"].min())

                    # Sparkline data (last 30 trading days)
                    sparkline = [round(float(x), 2) for x in df["Close"].tail(30).tolist()]

                    results[ticker] = {
                        "price": round(current, 2),
                        "day_change": round(day_change, 2),
                        "mo1_return": round(mo1_return, 2),
                        "mo3_return": round(mo3_return, 2),
                        "mo6_return": round(mo6_return, 2),
                        "high_6mo": round(high_52w, 2),
                        "low_6mo": round(low_52w, 2),
                        "sparkline": sparkline,
                    }
            except Exception as e:
                log.warning(f"  Error processing {ticker}: {e}")
                results[ticker] = {"error": str(e)}
    except Exception as e:
        log.error(f"Bulk download error: {e}")

    return results


def fetch_fred_data():
    """Fetch economic data from FRED."""
    if req is None or not FRED_API_KEY:
        # Return empty dict; dashboard will show "No FRED API key" message
        return {}

    results = {}
    for series_id, meta in FRED_SERIES.items():
        try:
            url = f"https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 60,  # ~5 years of monthly data or 1+ year of weekly
            }
            resp = req.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                obs = resp.json().get("observations", [])
                # Filter out missing values
                valid = [o for o in obs if o["value"] != "."]
                if valid:
                    current = float(valid[0]["value"])
                    current_date = valid[0]["date"]

                    # Get prior values for trend
                    values = []
                    for o in valid[:24]:
                        try:
                            values.append({"date": o["date"], "value": float(o["value"])})
                        except ValueError:
                            pass

                    prior = float(valid[1]["value"]) if len(valid) > 1 else current
                    change = current - prior

                    results[series_id] = {
                        "value": round(current, 2),
                        "date": current_date,
                        "change": round(change, 2),
                        "history": values[:12],  # Last 12 observations
                    }
        except Exception as e:
            log.warning(f"  FRED error for {series_id}: {e}")
            results[series_id] = {"error": str(e)}

    return results


def refresh_data():
    """Refresh all data sources."""
    log.info("=== Refreshing dashboard data ===")
    errors = []

    try:
        stocks = fetch_stock_data()
        data_store["stocks"] = stocks
        log.info(f"  Fetched {len(stocks)} stock tickers")
    except Exception as e:
        errors.append(f"Stock fetch error: {e}")
        log.error(f"  Stock fetch error: {e}")

    try:
        econ = fetch_fred_data()
        data_store["economic"] = econ
        log.info(f"  Fetched {len(econ)} FRED series")
    except Exception as e:
        errors.append(f"FRED fetch error: {e}")
        log.error(f"  FRED fetch error: {e}")

    data_store["last_updated"] = datetime.now().isoformat()
    data_store["errors"] = errors
    log.info("=== Refresh complete ===")


def background_refresh():
    """Background thread that refreshes data periodically."""
    while True:
        try:
            refresh_data()
        except Exception as e:
            log.error(f"Background refresh error: {e}")
        time.sleep(REFRESH_INTERVAL_SEC)


# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/api/data")
def api_data():
    """Return all dashboard data as JSON."""
    payload = {
        "stocks": data_store["stocks"],
        "economic": data_store["economic"],
        "stock_groups": {
            k: {
                "label": v["label"],
                "icon": v["icon"],
                "tickers": v["tickers"],
            }
            for k, v in STOCK_GROUPS.items()
        },
        "fred_series": FRED_SERIES,
        "last_updated": data_store["last_updated"],
        "errors": data_store["errors"],
        "has_fred_key": FRED_API_KEY is not None,
    }
    return jsonify(payload)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Force a data refresh."""
    refresh_data()
    return jsonify({"status": "ok", "last_updated": data_store["last_updated"]})


@app.route("/")
def index():
    return Response(DASHBOARD_HTML, mimetype="text/html")


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7605456088723739"
     crossorigin="anonymous"></script>
<title>AI Crisis Prediction Tracker</title>
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
    --sf-blue: #3b82f6;
    --sf-light-blue: #93c5fd;
    --sf-light-navy: #1e3a5f;
    --sf-dark-navy: #0f172a;
    --sf-green: #22c55e;
    --sf-dark-green: #16a34a;
    --sf-yellow: #facc15;
    --sf-warm-gray-1: #d4d4d4;
    --sf-warm-gray-2: #c4c4c4;
    --sf-warm-gray-3: #a3a3a3;
    --sf-warm-gray-4: #737373;
    --sf-cool-gray-1: #e2e8f0;
    --sf-cool-gray-2: #f1f5f9;
    --sf-purple: #8b5cf6;
    --sf-red: #ef4444;
    --sf-accent-green: #34d399;
    --bg: #f8fafc;
    --card-bg: #ffffff;
    --text-primary: #0f172a;
    --text-secondary: #64748b;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text-primary);
    line-height: 1.5;
}

/* ---- Top Bar ---- */
.topbar {
    background: linear-gradient(135deg, #0f172a, #1e3a5f);
    color: #fff;
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 12px rgba(0,0,0,0.15);
}
.topbar h1 {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.3px;
}
.topbar .subtitle {
    font-size: 12px;
    opacity: 0.85;
    font-weight: 400;
}
.topbar-right {
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 13px;
}
.topbar-right .status {
    display: flex;
    align-items: center;
    gap: 6px;
}
.pulse-dot {
    width: 8px; height: 8px;
    background: var(--sf-accent-green);
    border-radius: 50%;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
.refresh-btn {
    background: rgba(255,255,255,0.2);
    border: 1px solid rgba(255,255,255,0.3);
    color: #fff;
    padding: 6px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 500;
    transition: background 0.2s;
}
.refresh-btn:hover { background: rgba(255,255,255,0.35); }

/* ---- Memo Banner ---- */
.memo-banner {
    background: var(--sf-dark-navy);
    color: #fff;
    padding: 14px 32px;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.memo-banner .material-icons { font-size: 18px; color: var(--sf-yellow); }

/* ---- Navigation ---- */
.nav-tabs {
    background: #fff;
    padding: 0 32px;
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--sf-cool-gray-1);
    overflow-x: auto;
    position: sticky;
    top: 60px;
    z-index: 99;
}
.nav-tab {
    padding: 12px 20px;
    font-size: 13px;
    font-weight: 500;
    color: var(--sf-warm-gray-4);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    white-space: nowrap;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 6px;
}
.nav-tab:hover { color: var(--sf-blue); }
.nav-tab.active {
    color: var(--sf-blue);
    border-bottom-color: var(--sf-blue);
}
.nav-tab .material-icons { font-size: 16px; }

/* ---- Main Content ---- */
.main { padding: 24px 32px; max-width: 1600px; margin: 0 auto; }

/* ---- Section ---- */
.section {
    margin-bottom: 32px;
    display: none;
}
.section.active { display: block; }
.section-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 16px;
}
.section-header h2 {
    font-size: 18px;
    font-weight: 700;
    color: var(--sf-dark-navy);
}
.section-header .material-icons {
    font-size: 22px;
    color: var(--sf-blue);
}

/* ---- Stock Cards Grid ---- */
.cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 16px;
}
.card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    border: 1px solid var(--sf-cool-gray-1);
    transition: box-shadow 0.2s, transform 0.15s;
}
.card:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.1);
    transform: translateY(-1px);
}
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 12px;
}
.card-ticker {
    font-size: 13px;
    font-weight: 700;
    color: var(--sf-blue);
    background: rgba(41,98,255,0.08);
    padding: 2px 8px;
    border-radius: 4px;
}
.card-name {
    font-size: 15px;
    font-weight: 600;
    color: var(--sf-dark-navy);
    margin-bottom: 2px;
}
.card-price {
    font-size: 28px;
    font-weight: 800;
    color: var(--sf-dark-navy);
    letter-spacing: -1px;
}
.card-change {
    font-size: 14px;
    font-weight: 600;
    margin-left: 8px;
}
.positive { color: var(--sf-green); }
.negative { color: var(--sf-red); }

.card-returns {
    display: flex;
    gap: 12px;
    margin: 12px 0;
    font-size: 12px;
}
.return-pill {
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 600;
    background: var(--sf-cool-gray-2);
}
.return-pill.pos { background: rgba(32,201,159,0.12); color: var(--sf-dark-green); }
.return-pill.neg { background: rgba(231,76,60,0.1); color: var(--sf-red); }

/* Sparkline */
.sparkline-container {
    height: 40px;
    margin: 10px 0;
}
.sparkline-container svg {
    width: 100%;
    height: 100%;
}

.card-prediction {
    font-size: 12px;
    color: var(--sf-warm-gray-4);
    padding: 10px 12px;
    background: var(--sf-cool-gray-2);
    border-radius: 6px;
    border-left: 3px solid var(--sf-purple);
    margin-top: 10px;
    line-height: 1.5;
}
.card-prediction strong {
    color: var(--sf-light-navy);
    font-weight: 600;
}

/* ---- Economic Indicators ---- */
.econ-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
}
.econ-card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    border: 1px solid var(--sf-cool-gray-1);
}
.econ-card .label {
    font-size: 12px;
    font-weight: 600;
    color: var(--sf-warm-gray-4);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
}
.econ-card .value {
    font-size: 32px;
    font-weight: 800;
    color: var(--sf-dark-navy);
    letter-spacing: -1px;
}
.econ-card .change {
    font-size: 13px;
    font-weight: 600;
    margin-top: 4px;
}
.econ-card .date {
    font-size: 11px;
    color: var(--sf-warm-gray-3);
    margin-top: 6px;
}
.econ-card .prediction {
    font-size: 12px;
    color: var(--sf-warm-gray-4);
    padding: 8px 10px;
    background: var(--sf-cool-gray-2);
    border-radius: 6px;
    border-left: 3px solid var(--sf-red);
    margin-top: 12px;
}
.econ-card .mini-chart {
    height: 32px;
    margin-top: 10px;
}

/* ---- Timeline ---- */
.timeline {
    position: relative;
    padding-left: 28px;
}
.timeline::before {
    content: '';
    position: absolute;
    left: 8px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--sf-cool-gray-1);
}
.timeline-item {
    position: relative;
    margin-bottom: 24px;
    padding: 16px 20px;
    background: var(--card-bg);
    border-radius: 10px;
    border: 1px solid var(--sf-cool-gray-1);
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.timeline-item::before {
    content: '';
    position: absolute;
    left: -24px;
    top: 20px;
    width: 12px;
    height: 12px;
    background: var(--sf-blue);
    border-radius: 50%;
    border: 2px solid #fff;
    box-shadow: 0 0 0 2px var(--sf-blue);
}
.timeline-item.crisis::before { background: var(--sf-red); box-shadow: 0 0 0 2px var(--sf-red); }
.timeline-item.warning::before { background: var(--sf-yellow); box-shadow: 0 0 0 2px #ccc; }
.timeline-date {
    font-size: 12px;
    font-weight: 700;
    color: var(--sf-blue);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.timeline-title {
    font-size: 15px;
    font-weight: 700;
    color: var(--sf-dark-navy);
    margin: 4px 0;
}
.timeline-desc {
    font-size: 13px;
    color: var(--sf-warm-gray-4);
    line-height: 1.6;
}
.timeline-bets {
    margin-top: 12px;
    padding: 12px 14px;
    background: var(--sf-cool-gray-2);
    border-radius: 8px;
    border-left: 3px solid var(--sf-purple);
}
.timeline-bets-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--sf-purple);
    margin-bottom: 8px;
}
.timeline-bet {
    font-size: 12px;
    color: var(--text-primary);
    margin-bottom: 6px;
    line-height: 1.5;
    display: flex;
    align-items: flex-start;
    gap: 6px;
}
.timeline-bet::before {
    content: '\2192';
    color: var(--sf-purple);
    font-weight: 700;
    flex-shrink: 0;
    margin-top: 1px;
}
.timeline-indicators {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
}
.tl-indicator {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: #fff;
    border: 1px solid var(--sf-cool-gray-1);
    border-radius: 8px;
    font-size: 12px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.tl-indicator .tl-ticker {
    font-weight: 700;
    color: var(--sf-blue);
}
.tl-indicator .tl-price {
    font-weight: 700;
    color: var(--text-primary);
}
.tl-indicator .tl-change {
    font-weight: 600;
    font-size: 11px;
}
.tl-indicator .tl-label {
    font-size: 11px;
    color: var(--sf-warm-gray-4);
}
.tl-sparkline {
    width: 50px;
    height: 18px;
    display: inline-block;
    vertical-align: middle;
}

/* ---- No FRED Key Banner ---- */
.fred-banner {
    background: linear-gradient(135deg, #fef3c7, #d1fae5);
    color: var(--sf-dark-navy);
    padding: 14px 20px;
    border-radius: 10px;
    margin-bottom: 20px;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.fred-banner .material-icons { font-size: 20px; }
.fred-banner code {
    background: rgba(0,0,0,0.1);
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 12px;
}

/* ---- Loading ---- */
.loading {
    text-align: center;
    padding: 60px;
    color: var(--sf-warm-gray-3);
}
.loading .material-icons {
    font-size: 48px;
    animation: spin 1.5s linear infinite;
    color: var(--sf-blue);
}
@keyframes spin { 100% { transform: rotate(360deg); } }

/* ---- Overview Stats ---- */
.overview-stats {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
}
.stat-card {
    background: #fff;
    border-radius: 10px;
    padding: 16px;
    border: 1px solid var(--sf-cool-gray-1);
    text-align: center;
}
.stat-card .stat-value {
    font-size: 24px;
    font-weight: 800;
    color: var(--sf-dark-navy);
}
.stat-card .stat-label {
    font-size: 11px;
    color: var(--sf-warm-gray-4);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
}

/* ---- About Page ---- */
.about-container {
    max-width: 820px;
    margin: 0 auto;
}
.about-section {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 28px 32px;
    margin-bottom: 20px;
    border: 1px solid var(--sf-cool-gray-1);
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.about-section h3 {
    font-size: 16px;
    font-weight: 700;
    color: var(--sf-dark-navy);
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.about-section h3 .material-icons {
    font-size: 20px;
    color: var(--sf-blue);
}
.about-section p {
    font-size: 14px;
    color: var(--sf-warm-gray-4);
    line-height: 1.7;
    margin-bottom: 12px;
}
.about-section p:last-child {
    margin-bottom: 0;
}
.about-section a {
    color: var(--sf-blue);
    text-decoration: none;
    font-weight: 500;
}
.about-section a:hover {
    text-decoration: underline;
}
.about-table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 13px;
}
.about-table th {
    text-align: left;
    font-weight: 700;
    color: var(--sf-dark-navy);
    padding: 8px 12px;
    border-bottom: 2px solid var(--sf-cool-gray-1);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.about-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--sf-cool-gray-2);
    color: var(--sf-warm-gray-4);
    vertical-align: top;
}
.about-table td:first-child {
    font-weight: 600;
    color: var(--sf-dark-navy);
    white-space: nowrap;
}
.about-table tr:last-child td {
    border-bottom: none;
}
.about-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    margin-right: 4px;
    margin-bottom: 4px;
}
.about-tag.stock { background: rgba(59,130,246,0.1); color: var(--sf-blue); }
.about-tag.econ { background: rgba(139,92,246,0.1); color: var(--sf-purple); }
.about-tag.source { background: rgba(34,197,94,0.1); color: var(--sf-dark-green); }

/* ---- Rebuttal Page ---- */
.rebuttal-container {
    max-width: 860px;
    margin: 0 auto;
}
.rebuttal-intro {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 20px;
    border: 1px solid var(--sf-cool-gray-1);
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.rebuttal-intro p {
    font-size: 14px;
    color: var(--sf-warm-gray-4);
    line-height: 1.7;
    margin-bottom: 10px;
}
.rebuttal-intro p:last-child { margin-bottom: 0; }
.rebuttal-intro a {
    color: var(--sf-blue);
    text-decoration: none;
    font-weight: 500;
}
.rebuttal-intro a:hover { text-decoration: underline; }
.rebuttal-point {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 20px;
    border: 1px solid var(--sf-cool-gray-1);
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.rebuttal-point-header {
    display: flex;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 16px;
}
.rebuttal-vs {
    display: flex;
    gap: 0;
    flex: 1;
}
.rebuttal-claim, .rebuttal-counter {
    flex: 1;
    padding: 14px 16px;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.6;
}
.rebuttal-claim {
    background: rgba(239,68,68,0.06);
    border: 1px solid rgba(239,68,68,0.15);
    border-right: none;
    border-radius: 8px 0 0 8px;
}
.rebuttal-counter {
    background: rgba(34,197,94,0.06);
    border: 1px solid rgba(34,197,94,0.15);
    border-left: none;
    border-radius: 0 8px 8px 0;
}
.rebuttal-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 6px;
}
.rebuttal-claim .rebuttal-label { color: var(--sf-red); }
.rebuttal-counter .rebuttal-label { color: var(--sf-green); }
.rebuttal-claim p, .rebuttal-counter p {
    margin: 0;
    color: var(--text-primary);
    font-size: 13px;
}
.rebuttal-analysis {
    font-size: 13px;
    color: var(--sf-warm-gray-4);
    line-height: 1.7;
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid var(--sf-cool-gray-2);
}
.rebuttal-analysis p {
    margin-bottom: 10px;
}
.rebuttal-analysis p:last-child { margin-bottom: 0; }
.rebuttal-watchlist {
    margin-top: 14px;
    padding: 12px 14px;
    background: var(--sf-cool-gray-2);
    border-radius: 8px;
    font-size: 12px;
    color: var(--sf-warm-gray-4);
    line-height: 1.6;
}
.rebuttal-watchlist strong {
    color: var(--sf-dark-navy);
}
.rebuttal-verdict {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 20px;
    border: 1px solid var(--sf-cool-gray-1);
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.rebuttal-verdict h3 {
    font-size: 16px;
    font-weight: 700;
    color: var(--sf-dark-navy);
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.rebuttal-verdict h3 .material-icons {
    font-size: 20px;
    color: var(--sf-purple);
}
.rebuttal-verdict p {
    font-size: 14px;
    color: var(--sf-warm-gray-4);
    line-height: 1.7;
    margin-bottom: 10px;
}
.rebuttal-verdict p:last-child { margin-bottom: 0; }
.trigger-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 10px;
    margin: 14px 0;
}
.trigger-card {
    padding: 12px 14px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.5;
    text-align: center;
}
.trigger-card.bad {
    background: rgba(239,68,68,0.06);
    border: 1px solid rgba(239,68,68,0.15);
    color: var(--sf-red);
}
.trigger-card.good {
    background: rgba(34,197,94,0.06);
    border: 1px solid rgba(34,197,94,0.15);
    color: var(--sf-dark-green);
}
.trigger-card .trigger-icon {
    font-size: 22px;
    margin-bottom: 4px;
}
.trigger-card .trigger-label {
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ---- Responsive ---- */
@media (max-width: 768px) {
    .topbar { padding: 12px 16px; }
    .main { padding: 16px; }
    .cards-grid { grid-template-columns: 1fr; }
    .nav-tabs { padding: 0 12px; }
    .about-section { padding: 20px; }
    .rebuttal-vs { flex-direction: column; }
    .rebuttal-claim { border-radius: 8px 8px 0 0; border-right: 1px solid rgba(239,68,68,0.15); border-bottom: none; }
    .rebuttal-counter { border-radius: 0 0 8px 8px; border-left: 1px solid rgba(34,197,94,0.15); border-top: none; }
    .trigger-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="topbar">
    <div>
        <h1>AI Crisis Prediction Tracker</h1>
        <div class="subtitle">Tracking the predictions from <a href="https://www.citriniresearch.com/p/2028gic" target="_blank" style="color:inherit;text-decoration:underline;">"The 2028 Global Intelligence Crisis"</a> memo by Citrini Research</div>
    </div>
    <div class="topbar-right">
        <div class="status">
            <div class="pulse-dot"></div>
            <span id="last-updated">Loading...</span>
        </div>
        <button class="refresh-btn" onclick="forceRefresh()">
            <span class="material-icons" style="font-size:14px;vertical-align:middle">refresh</span> Refresh
        </button>
    </div>
</div>

<div class="memo-banner">
    <span class="material-icons">info</span>
    <span><strong>Note:</strong> This memo is a speculative scenario exercise by Citrini Research &amp; Alap Shah (Feb 22, 2026), not a prediction. This dashboard tracks real-time data against the scenario's thesis for monitoring purposes. It was not developed by Citrini Research, and is meant as an educational project to track publicly available data around predictions included in the report.</span>
</div>

<div class="nav-tabs" id="nav-tabs">
    <div class="nav-tab active" data-tab="overview">
        <span class="material-icons">dashboard</span> Overview
    </div>
    <div class="nav-tab" data-tab="market_indices">
        <span class="material-icons">trending_up</span> Markets
    </div>
    <div class="nav-tab" data-tab="ai_infrastructure">
        <span class="material-icons">memory</span> AI Infra
    </div>
    <div class="nav-tab" data-tab="saas_disruption">
        <span class="material-icons">cloud_off</span> SaaS
    </div>
    <div class="nav-tab" data-tab="payments_intermediation">
        <span class="material-icons">payment</span> Payments
    </div>
    <div class="nav-tab" data-tab="india_it_services">
        <span class="material-icons">language</span> India IT
    </div>
    <div class="nav-tab" data-tab="crypto_stablecoins">
        <span class="material-icons">currency_bitcoin</span> Crypto
    </div>
    <div class="nav-tab" data-tab="consumer_discretionary">
        <span class="material-icons">shopping_cart</span> Consumer
    </div>
    <div class="nav-tab" data-tab="economic">
        <span class="material-icons">bar_chart</span> Economic
    </div>
    <div class="nav-tab" data-tab="timeline">
        <span class="material-icons">schedule</span> Scenario Timeline
    </div>
    <div class="nav-tab" data-tab="private_credit">
        <span class="material-icons">account_balance</span> Private Credit
    </div>
    <div class="nav-tab" data-tab="rebuttal">
        <span class="material-icons">gavel</span> Rebuttal
    </div>
    <div class="nav-tab" data-tab="about">
        <span class="material-icons">help_outline</span> About
    </div>
</div>

<div class="main" id="main-content">
    <div class="loading" id="loading">
        <span class="material-icons">sync</span>
        <p style="margin-top:16px; font-size:15px;">Fetching live market data...</p>
    </div>
</div>

<script>
// ---- State ----
let dashData = null;
let activeTab = 'overview';
const AUTO_REFRESH_MS = 300000; // 5 min

// ---- Tab Navigation ----
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        activeTab = tab.dataset.tab;
        render();
    });
});

// ---- Data Fetching ----
async function fetchData() {
    try {
        const resp = await fetch('/api/data');
        dashData = await resp.json();
        document.getElementById('last-updated').textContent =
            dashData.last_updated ? 'Updated ' + new Date(dashData.last_updated).toLocaleTimeString() : 'Loading...';
        render();
    } catch (e) {
        console.error('Fetch error:', e);
    }
}

async function forceRefresh() {
    document.getElementById('last-updated').textContent = 'Refreshing...';
    try {
        await fetch('/api/refresh', { method: 'POST' });
        await fetchData();
    } catch (e) { console.error(e); }
}

// ---- Helpers ----
function fmt(n, decimals=2) {
    if (n === undefined || n === null || isNaN(n)) return '—';
    return Number(n).toLocaleString(undefined, {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
}
function changeClass(v) { return v >= 0 ? 'positive' : 'negative'; }
function changeSign(v) { return v >= 0 ? '+' : ''; }
function pillClass(v) { return v >= 0 ? 'pos' : 'neg'; }

function sparklineSVG(data, color) {
    if (!data || data.length < 2) return '';
    const w = 280, h = 36, pad = 2;
    const min = Math.min(...data), max = Math.max(...data);
    const range = max - min || 1;
    const points = data.map((v, i) => {
        const x = pad + (i / (data.length - 1)) * (w - 2*pad);
        const y = h - pad - ((v - min) / range) * (h - 2*pad);
        return `${x},${y}`;
    }).join(' ');
    const fillPoints = `${pad},${h-pad} ${points} ${w-pad},${h-pad}`;
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        <polygon points="${fillPoints}" fill="${color}22" />
        <polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5" />
    </svg>`;
}

// ---- Render ----
function render() {
    if (!dashData) return;
    const main = document.getElementById('main-content');
    const loadingEl = document.getElementById('loading');
    if (loadingEl) loadingEl.style.display = 'none';

    if (activeTab === 'overview') {
        main.innerHTML = renderOverview();
    } else if (activeTab === 'economic') {
        main.innerHTML = renderEconomic();
    } else if (activeTab === 'timeline') {
        main.innerHTML = renderTimeline();
    } else if (activeTab === 'private_credit') {
        main.innerHTML = renderPrivateCredit();
    } else if (activeTab === 'rebuttal') {
        main.innerHTML = renderRebuttal();
    } else if (activeTab === 'about') {
        main.innerHTML = renderAbout();
    } else {
        main.innerHTML = renderStockGroup(activeTab);
    }
}

function renderOverview() {
    const stocks = dashData.stocks;
    const groups = dashData.stock_groups;

    // Key metrics bar
    const sp = stocks['^GSPC'] || {};
    const ndx = stocks['^IXIC'] || {};
    const tny = stocks['^TNX'] || {};
    const nvda = stocks['NVDA'] || {};

    let html = `<div class="overview-stats">
        <div class="stat-card">
            <div class="stat-value">${sp.price ? fmt(sp.price, 0) : '—'}</div>
            <div class="stat-label">S&P 500</div>
            <div class="${changeClass(sp.day_change)}" style="font-size:13px;font-weight:600">${changeSign(sp.day_change)}${fmt(sp.day_change)}%</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${ndx.price ? fmt(ndx.price, 0) : '—'}</div>
            <div class="stat-label">Nasdaq</div>
            <div class="${changeClass(ndx.day_change)}" style="font-size:13px;font-weight:600">${changeSign(ndx.day_change)}${fmt(ndx.day_change)}%</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${tny.price ? fmt(tny.price) : '—'}%</div>
            <div class="stat-label">10-Yr Yield</div>
            <div class="${changeClass(tny.day_change)}" style="font-size:13px;font-weight:600">${changeSign(tny.day_change)}${fmt(tny.day_change)}%</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">$${nvda.price ? fmt(nvda.price, 0) : '—'}</div>
            <div class="stat-label">NVIDIA</div>
            <div class="${changeClass(nvda.day_change)}" style="font-size:13px;font-weight:600">${changeSign(nvda.day_change)}${fmt(nvda.day_change)}%</div>
        </div>
    </div>`;

    // Render a summary card grid of all groups
    for (const [groupKey, group] of Object.entries(groups)) {
        html += `<div style="margin-bottom:28px;">
            <div class="section-header">
                <span class="material-icons">${group.icon}</span>
                <h2>${group.label}</h2>
            </div>
            <div class="cards-grid">`;
        for (const [ticker, meta] of Object.entries(group.tickers)) {
            const s = stocks[ticker] || {};
            const hasData = s.price !== undefined;
            const color = (s.mo3_return >= 0) ? '#20c99f' : '#e74c3c';
            html += `<div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-name">${meta.name}</div>
                        <span class="card-ticker">${ticker}</span>
                    </div>
                    <div style="text-align:right">
                        <div class="card-price">${hasData ? (ticker === '^TNX' ? fmt(s.price) + '%' : '$' + fmt(s.price)) : '—'}</div>
                        ${hasData ? `<span class="card-change ${changeClass(s.day_change)}">${changeSign(s.day_change)}${fmt(s.day_change)}% today</span>` : ''}
                    </div>
                </div>
                ${hasData ? `<div class="card-returns">
                    <span class="return-pill ${pillClass(s.mo1_return)}">1M: ${changeSign(s.mo1_return)}${fmt(s.mo1_return)}%</span>
                    <span class="return-pill ${pillClass(s.mo3_return)}">3M: ${changeSign(s.mo3_return)}${fmt(s.mo3_return)}%</span>
                    <span class="return-pill ${pillClass(s.mo6_return)}">6M: ${changeSign(s.mo6_return)}${fmt(s.mo6_return)}%</span>
                </div>` : ''}
                ${hasData && s.sparkline ? `<div class="sparkline-container">${sparklineSVG(s.sparkline, color)}</div>` : ''}
                <div class="card-prediction"><strong>Memo scenario:</strong> ${meta.prediction}</div>
            </div>`;
        }
        html += `</div></div>`;
    }
    return html;
}

function renderStockGroup(groupKey) {
    const group = dashData.stock_groups[groupKey];
    const stocks = dashData.stocks;
    if (!group) return '<p>Group not found</p>';

    let html = `<div class="section-header">
        <span class="material-icons">${group.icon}</span>
        <h2>${group.label}</h2>
    </div>
    <div class="cards-grid">`;

    for (const [ticker, meta] of Object.entries(group.tickers)) {
        const s = stocks[ticker] || {};
        const hasData = s.price !== undefined;
        const color = (s.mo3_return >= 0) ? '#20c99f' : '#e74c3c';
        html += `<div class="card">
            <div class="card-header">
                <div>
                    <div class="card-name">${meta.name}</div>
                    <span class="card-ticker">${ticker}</span>
                </div>
                <div style="text-align:right">
                    <div class="card-price">${hasData ? (ticker === '^TNX' ? fmt(s.price) + '%' : '$' + fmt(s.price)) : '—'}</div>
                    ${hasData ? `<span class="card-change ${changeClass(s.day_change)}">${changeSign(s.day_change)}${fmt(s.day_change)}% today</span>` : ''}
                </div>
            </div>
            ${hasData ? `<div class="card-returns">
                <span class="return-pill ${pillClass(s.mo1_return)}">1M: ${changeSign(s.mo1_return)}${fmt(s.mo1_return)}%</span>
                <span class="return-pill ${pillClass(s.mo3_return)}">3M: ${changeSign(s.mo3_return)}${fmt(s.mo3_return)}%</span>
                <span class="return-pill ${pillClass(s.mo6_return)}">6M: ${changeSign(s.mo6_return)}${fmt(s.mo6_return)}%</span>
            </div>` : ''}
            ${hasData && s.sparkline ? `<div class="sparkline-container">${sparklineSVG(s.sparkline, color)}</div>` : ''}
            ${hasData ? `<div style="font-size:12px;color:var(--sf-warm-gray-3);margin:6px 0;">
                6mo Range: $${fmt(s.low_6mo)} — $${fmt(s.high_6mo)}
            </div>` : ''}
            <div class="card-prediction"><strong>Memo scenario:</strong> ${meta.prediction}</div>
        </div>`;
    }
    html += '</div>';
    return html;
}

function renderEconomic() {
    const econ = dashData.economic;
    const series = dashData.fred_series;
    const hasFred = dashData.has_fred_key;

    let html = `<div class="section-header">
        <span class="material-icons">bar_chart</span>
        <h2>Economic Indicators</h2>
    </div>`;

    if (!hasFred) {
        html += `<div class="fred-banner">
            <span class="material-icons">vpn_key</span>
            <div>
                <strong>FRED API key not configured.</strong> To enable live economic data, get a free key at
                <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank">fred.stlouisfed.org</a>
                and set <code>FRED_API_KEY</code> in the Python script. The memo predictions are still shown below.
            </div>
        </div>`;
    }

    html += '<div class="econ-grid">';
    for (const [sid, meta] of Object.entries(series)) {
        const d = econ[sid] || {};
        const hasData = d.value !== undefined;
        html += `<div class="econ-card">
            <div class="label">${meta.name}</div>
            <div class="value">${hasData ? fmt(d.value) : '—'}</div>
            ${hasData ? `<div class="change ${changeClass(d.change)}">${changeSign(d.change)}${fmt(d.change)} from prior</div>
            <div class="date">As of ${d.date}</div>` : '<div class="date" style="color:var(--sf-warm-gray-3)">No data — set FRED API key</div>'}
            <div class="prediction"><strong>Memo scenario:</strong> ${meta.prediction}</div>
        </div>`;
    }
    html += '</div>';
    return html;
}

function renderTimeline() {
    const stocks = dashData.stocks;
    const econ = dashData.economic;

    // Helper to render a small stock indicator chip
    function stockChip(ticker, label) {
        const s = stocks[ticker] || {};
        if (!s.price) return `<div class="tl-indicator"><span class="tl-ticker">${ticker}</span> <span class="tl-label">${label}</span> <span class="tl-price">—</span></div>`;
        const color = s.mo3_return >= 0 ? '#22c55e' : '#ef4444';
        const cls = s.mo3_return >= 0 ? 'positive' : 'negative';
        const miniSpark = s.sparkline ? `<span class="tl-sparkline">${sparklineSVG(s.sparkline, color)}</span>` : '';
        return `<div class="tl-indicator">
            <span class="tl-ticker">${ticker}</span>
            <span class="tl-price">$${fmt(s.price)}</span>
            <span class="tl-change ${cls}">${changeSign(s.mo3_return)}${fmt(s.mo3_return)}% 3mo</span>
            ${miniSpark}
            <span class="tl-label">${label}</span>
        </div>`;
    }

    // Helper for FRED indicator chip
    function fredChip(seriesId, label) {
        const d = econ[seriesId] || {};
        if (d.value === undefined) return `<div class="tl-indicator"><span class="tl-ticker">${seriesId}</span> <span class="tl-label">${label}</span> <span class="tl-price">—</span></div>`;
        const cls = d.change >= 0 ? 'positive' : 'negative';
        return `<div class="tl-indicator">
            <span class="tl-ticker">${seriesId}</span>
            <span class="tl-price">${fmt(d.value)}</span>
            <span class="tl-change ${cls}">${changeSign(d.change)}${fmt(d.change)}</span>
            <span class="tl-label">${label} (${d.date})</span>
        </div>`;
    }

    const events = [
        {
            date: "Late 2025", type: "warning",
            title: "Agentic Coding Step Function",
            desc: "Agentic coding tools (Claude Code, Codex) take a step-function jump. A competent developer can now replicate the core functionality of a mid-market SaaS product in weeks. CIOs reviewing $500k annual renewals start asking: 'what if we just built this ourselves?'",
            bets: [
                "SaaS contract renewals begin facing pricing pressure as in-house builds become viable",
                "Long-tail SaaS vendors (Monday.com, Zapier, Asana) most exposed — differentiation collapses when AI makes it easy to ship features",
                "Systems of record (ServiceNow, Salesforce) initially thought safe, but reflexivity emerges: their customers' headcount cuts reduce seat counts"
            ],
            indicators: () => stockChip('NOW', 'Systems of record') + stockChip('MNDY', 'Long-tail SaaS') + stockChip('ASAN', 'Long-tail SaaS') + stockChip('CRM', 'Enterprise SaaS')
        },
        {
            date: "Early 2026", type: "",
            title: "Initial Layoff Wave — The Euphoria Phase",
            desc: "First wave of white-collar layoffs due to AI obsolescence begins. But the market loves it: margins expand, earnings beat, stocks rally. Record corporate profits get funneled right back into AI compute. S&P 500 flirts with 8,000, Nasdaq breaks above 30k. Nominal GDP prints mid-to-high single-digit growth. The headline numbers look great.",
            bets: [
                "S&P 500 approaches ~8,000 and Nasdaq breaks 30,000 driven by margin expansion",
                "AI infrastructure stocks (NVDA, TSM) post record revenues as capex pours in",
                "Real wage growth starts collapsing even as productivity booms — the 'Ghost GDP' concept: output shows up in national accounts but never circulates through the real economy",
                "Consumer economy (70% of GDP) begins to weaken beneath strong headline numbers"
            ],
            indicators: () => stockChip('^GSPC', 'Target: ~8,000') + stockChip('^IXIC', 'Target: 30,000+') + stockChip('NVDA', 'AI infra winner') + stockChip('TSM', '95%+ utilization')
        },
        {
            date: "Mid 2026", type: "warning",
            title: "Enterprise Budget Reviews — The Cracks Form",
            desc: "Fiscal years mostly align with calendar years, so 2026 spend was set in Q4 2025 when 'agentic AI' was still a buzzword. The mid-year review is the first time procurement teams make decisions with visibility into what these systems can actually do. Some watch internal teams spin up prototypes replicating six-figure SaaS contracts in weeks. A Fortune 500 procurement manager tells a vendor expecting a 5% price increase that his engineers are already using AI tools to replace the vendor entirely. They renew at a 30% discount — and that's considered a good outcome.",
            bets: [
                "Enterprise SaaS renewal rates begin declining — 30% discounts become common for survivors",
                "Long-tail SaaS vendors see accelerating churn as in-house builds proliferate",
                "The companies most threatened by AI become AI's most aggressive adopters — a paradox that accelerates the displacement spiral"
            ],
            indicators: () => stockChip('NOW', 'ACV growth watch') + stockChip('ZM', 'Workflow SaaS') + stockChip('CRM', 'Enterprise renewal pressure')
        },
        {
            date: "Oct 2026", type: "crisis",
            title: "ServiceNow Q3 Report — The SaaS Crack",
            desc: "ServiceNow's Q3 2026 report reveals the mechanism of reflexivity. Net new ACV growth decelerates from 23% to 14%. A 15% workforce reduction and 'structural efficiency program' is announced. Shares fall 18%. When Fortune 500 clients cut 15% of their workforce, they cancel 15% of their ServiceNow licenses. The same AI-driven headcount reductions boosting margins at ServiceNow's customers are mechanically destroying its own revenue base. The long-tail SaaS companies — Monday.com, Zapier, Asana — have it much worse.",
            bets: [
                "ServiceNow ACV growth decelerates from 23% to 14% — watch quarterly earnings for this specific metric",
                "Per-seat SaaS models structurally break as customers' headcounts shrink",
                "SaaS multiples compress to 5-8x EBITDA as growth assumptions die",
                "Incumbents don't resist AI (like Kodak/Blockbuster) — they adopt it aggressively because they can't afford not to, accelerating their own disruption"
            ],
            indicators: () => stockChip('NOW', 'ACV: 23%→14%') + stockChip('MNDY', 'Long-tail collapse') + stockChip('ASAN', 'Long-tail collapse') + stockChip('ZM', 'Pricing pressure')
        },
        {
            date: "Oct 2026", type: "crisis",
            title: "JOLTS: Job Openings Collapse",
            desc: "The October 2026 JOLTS print provides the first definitive labor market data. Job openings fall below 5.5 million, a 15% decline YoY. The unemployed-to-opening ratio climbs to ~1.7, highest since August 2020. White-collar openings are collapsing while blue-collar openings (construction, healthcare, trades) remain relatively stable. Real wage growth has been negative for the majority of the year in both cohorts.",
            bets: [
                "JOLTS job openings fall below 5.5M — a 15% YoY decline",
                "Unemployed-to-opening ratio climbs to ~1.7 (highest since Aug 2020)",
                "White-collar vs blue-collar divergence: the churn is concentrated in jobs that write memos, approve budgets, and keep the middle layers of the economy lubricated",
                "10-year yield begins descent from 4.3% to 3.2% as bond market prices in the consumption hit"
            ],
            indicators: () => fredChip('JTSJOL', 'Target: <5,500') + fredChip('UNRATE', 'Rising') + stockChip('^TNX', 'Yield: 4.3%→3.2%')
        },
        {
            date: "Q4 2026", type: "warning",
            title: "Agentic Shopping Disrupts Intermediation",
            desc: "By Q4 2026, AI agents assemble complete travel itineraries (flights, hotels, ground transport, loyalty optimization) faster and cheaper than any platform. Insurance renewals are disrupted as agents re-shop coverage annually, dismantling the 15-20% premiums insurers earned from passive renewals. Real estate buy-side commissions compress from 3% to under 1%. Financial advice, tax prep, routine legal work — any category where the value proposition was 'I will navigate complexity that you find tedious' gets disrupted, because the agents find nothing tedious.",
            bets: [
                "Travel booking platforms (Booking, Expedia) face agent-driven disintermediation",
                "Insurance renewal premiums compress 15-20% as agents re-shop annually",
                "Real estate commissions compress from 3% to under 1% in major metros",
                "Customer lifetime value — the metric the subscription economy was built on — distinctly declines"
            ],
            indicators: () => stockChip('BKNG', 'Travel disruption') + stockChip('RDFN', 'Commission compression') + stockChip('XLY', 'Consumer discretionary')
        },
        {
            date: "Early 2027", type: "",
            title: "LLM Usage Goes Mainstream — 400K Tokens/Day",
            desc: "By early 2027, LLM usage is default. People use AI agents without even knowing what an AI agent is. Qwen's open-source agentic shopper catalyzes AI-handled consumer decisions. Every major assistant integrates agentic commerce. Distilled models run on phones and laptops. The median individual consumes 400,000 tokens per day — 10x since end of 2026. Commerce stops being a series of discrete human decisions and becomes continuous optimization running 24/7.",
            bets: [
                "DoorDash (DASH) poster child for 'habitual intermediation' destruction — agents check DoorDash, Uber Eats, restaurant sites, and twenty new alternatives to pick lowest fee every time",
                "Delivery app margins compress to near zero as barriers to entry collapse and agents eliminate app loyalty",
                "The 2-3% card interchange rate becomes an obvious target for agent-to-agent commerce — stablecoins via Solana/Ethereum L2s offer near-instant settlement at fractions of a penny"
            ],
            indicators: () => stockChip('DASH', 'Margin compression') + stockChip('SOL-USD', 'Stablecoin rails') + stockChip('ETH-USD', 'L2 settlement')
        },
        {
            date: "Q1 2027", type: "crisis",
            title: "Mastercard Q1 — The Interchange Reckoning",
            desc: "Mastercard's Q1 2027 report is the point of no return for agentic commerce. Net revenues +6% Y/Y but purchase volume growth slows to +3.4% from +5.9%. Management notes 'agent-led price optimization' and 'pressure in discretionary categories.' MA drops 9% the following day. Visa drops too but pares losses on stronger stablecoin infrastructure positioning. American Express hit hardest: a combined headwind from white-collar workforce reductions gutting its customer base AND agents routing around interchange. Synchrony, Capital One, and Discover all fall 10%+.",
            bets: [
                "Mastercard purchase volume growth decelerates to +3.4% (from +5.9%)",
                "American Express hit hardest among card networks — double headwind of white-collar customer losses + interchange bypass",
                "Stablecoin transaction volume on Solana/Ethereum L2s grows as machine-to-machine commerce routes around card rails",
                "Card-focused banks and mono-line issuers face existential threat to rewards programs funded by merchant subsidies"
            ],
            indicators: () => stockChip('MA', 'Vol growth: +3.4%') + stockChip('V', 'Stablecoin pivot') + stockChip('AXP', 'Double headwind') + stockChip('SYF', '-10%+') + stockChip('COF', '-10%+') + stockChip('SOL-USD', 'Settlement layer')
        },
        {
            date: "Q1-Q2 2027", type: "warning",
            title: "The Intelligence Displacement Spiral",
            desc: "White-collar workers don't sit idle — they downshift. A former Salesforce senior PM ($180K/yr) starts driving Uber ($45K/yr). Multiply this by hundreds of thousands of workers across every major metro. Overqualified labor flooding the service and gig economy pushes down wages for existing workers who were already struggling. The top 10% of earners account for 50%+ of all consumer spending; the top 20% account for ~65%. A 2% decline in white-collar employment translates to a 3-4% hit to discretionary consumer spending.",
            bets: [
                "Savings rates tick higher as still-employed professionals spend like they might be next",
                "Consumer discretionary spending contracts disproportionately to headline job losses",
                "White-collar job losses create a lagged but deeper consumption impact vs blue-collar losses (savings buffers delay the behavioral shift 2-3 quarters)",
                "Autonomous delivery and self-driving vehicles begin working through the gig economy that absorbed the first wave of displaced workers"
            ],
            indicators: () => fredChip('PSAVERT', 'Savings rate rising') + fredChip('DPCERAM1M225NBEA', 'PCE weakening') + stockChip('XLY', 'Discretionary demand') + fredChip('UNRATE', 'Unemployment climbing')
        },
        {
            date: "Q2 2027", type: "crisis",
            title: "Recession Confirmed — Two Quarters of Negative GDP",
            desc: "By Q2 2027, it's unambiguous: two consecutive quarters of negative real GDP growth. Initial claims surge to 487,000 — highest since April 2020. ADP and Equifax confirm the overwhelming majority of new filings are from white-collar professionals. The S&P drops 6% in a week. This cycle's cause is not cyclical — AI got better and cheaper, companies laid off workers and used savings to buy more AI capability, displaced workers spent less, consumer-facing companies weakened and invested more in AI to protect margins. A feedback loop with no natural brake.",
            bets: [
                "Real GDP turns negative for two consecutive quarters",
                "Initial jobless claims surge to 487,000",
                "S&P 500 drops 6% in a week as negative macro starts winning the tug of war",
                "Unlike a normal recession, the cause (AI improvement) does not self-correct — the engine that caused the disruption gets better every quarter"
            ],
            indicators: () => fredChip('A191RL1Q225SBEA', 'GDP: target negative') + fredChip('ICSA', 'Claims: target 487K') + stockChip('^GSPC', 'S&P 500 drawdown') + fredChip('UNRATE', 'Accelerating')
        },
        {
            date: "Apr 2027", type: "crisis",
            title: "Moody's Downgrades $18B of PE-Backed Software Debt",
            desc: "Private credit had grown from under $1 trillion (2015) to over $2.5 trillion by 2026. Much deployed into leveraged buyouts of SaaS companies at valuations assuming mid-teens revenue growth in perpetuity. As public SaaS companies trade at 5-8x EBITDA, PE-backed software companies sit on balance sheets at marks reflecting acquisition multiples of revenue that no longer exist. Moody's downgrades $18B across 14 issuers citing 'secular revenue headwinds from AI-driven competitive disruption' — the largest single-sector action since energy in 2015.",
            bets: [
                "PE-backed software companies face wave of defaults as ARR growth assumptions collapse",
                "Private credit marks lag reality by quarters — managers ease marks down gradually (100, 92, 85) while public comps say 50 cents",
                "HY credit spreads widen as contagion fears spread beyond software to the broader PE-backed portfolio",
                "The $13 trillion mortgage market faces reassessment as white-collar income — its bedrock — becomes structurally impaired"
            ],
            indicators: () => fredChip('BAMLH0A0HYM2', 'HY spreads widening') + stockChip('^GSPC', 'Broad market stress')
        },
        {
            date: "Through 2027", type: "crisis",
            title: "India IT Services Crisis — Rupee Falls 18%",
            desc: "India's IT services sector exports over $200 billion annually — the single largest contributor to India's current account surplus and the offset that financed its persistent goods trade deficit. The entire model was built on one value proposition: Indian developers cost a fraction of their American counterparts. But the marginal cost of an AI coding agent has collapsed to essentially the cost of electricity. TCS, Infosys, and Wipro see contract cancellations accelerate through 2027. The rupee falls 18% against the dollar in four months. By Q1 2028, the IMF has begun 'preliminary discussions' with New Delhi.",
            bets: [
                "TCS, Infosys, Wipro contract cancellations accelerate as AI coding agents destroy the cost-arbitrage value proposition",
                "Indian rupee falls 18% vs dollar as the IT services surplus that anchored India's external accounts evaporates",
                "IMF begins discussions with India by Q1 2028 — a sovereign-level economic impact",
                "Economies purely convex to AI infrastructure (Taiwan, Korea) outperform massively"
            ],
            indicators: () => stockChip('INFY', 'Contract cancellations') + stockChip('WIT', 'Contract cancellations') + stockChip('TCS.NS', 'Contract cancellations') + fredChip('DEXINUS', 'Rupee: target -18%') + stockChip('TSM', 'Taiwan outperformance')
        },
        {
            date: "Nov 2027", type: "crisis",
            title: "Market Crash — Feedback Loops Accelerate",
            desc: "The November 2027 crash accelerates all negative feedback loops already in place. The AI infrastructure complex keeps performing even as the economy it's disrupting deteriorates — NVDA posts record revenues, TSM runs at 95%+ utilization, hyperscalers still spend $150-200B per quarter on data center capex. But every company's AI budget grows while its overall spending shrinks. The intuitive expectation that falling aggregate demand would slow the AI buildout doesn't materialize — it's OpEx substitution, not CapEx. A company spending $100M on employees and $5M on AI now spends $70M on employees and $20M on AI.",
            bets: [
                "S&P 500 cumulative drawdown reaches -38% from October 2026 highs (~8,000 → ~4,960)",
                "AI infrastructure stocks (NVDA, TSM) paradoxically hold up better than broad market",
                "AI investment increases by multiples even as total operating costs decline — OpEx substitution, not CapEx bubble",
                "The crash accelerates layoffs as boards demand cost cuts, which funds more AI adoption, which enables more layoffs"
            ],
            indicators: () => stockChip('^GSPC', 'Target: ~4,960') + stockChip('NVDA', 'Resilient infra') + stockChip('TSM', 'Resilient infra') + stockChip('GEV', 'Power demand') + fredChip('BAMLH0A0HYM2', 'Credit stress')
        },
        {
            date: "June 2028", type: "crisis",
            title: "Unemployment Hits 10.2% — The New Normal",
            desc: "The memo's framing date. Unemployment prints 10.2%, a 0.3% upside surprise. The market sells off 2% on the number, bringing the cumulative S&P drawdown to -38% from October 2026 highs. Traders have grown numb — six months ago this print would have triggered a circuit breaker. The velocity of money has flatlined. The human-centric consumer economy, 70% of GDP, has withered. Policy response has always lagged economic reality, and lack of a comprehensive plan is now threatening to accelerate a deflationary spiral.",
            bets: [
                "Unemployment rate reaches 10.2% — track the monthly BLS prints for trajectory",
                "S&P 500 at roughly 4,960 — a -38% drawdown from the Oct 2026 peak",
                "Velocity of money flatlines as displaced workers can't circulate income",
                "Deflationary spiral risk emerges as policy response lags the structural (not cyclical) nature of the crisis",
                "The question shifts from 'will the AI bubble burst' to 'what happens to a consumer-credit economy when consumers are being replaced with machines'"
            ],
            indicators: () => fredChip('UNRATE', 'Target: 10.2%') + fredChip('ICSA', 'Target: 487K') + stockChip('^GSPC', 'Target: ~4,960') + fredChip('A191RL1Q225SBEA', 'GDP contracting') + fredChip('PSAVERT', 'Savings behavior')
        },
    ];

    let html = `<div class="section-header">
        <span class="material-icons">schedule</span>
        <h2>Scenario Timeline — Key Events to Watch</h2>
    </div>
    <p style="font-size:13px;color:var(--sf-warm-gray-4);margin-bottom:20px;">
        The memo traces a chain of predicted dominoes from late 2025 through June 2028. Each event below lists the specific bets embedded in that step, with live indicators so you can track whether the thesis is playing out. <span style="color:var(--sf-purple);font-weight:600;">Purple boxes</span> show the specific bets; <strong>indicator chips</strong> show where those metrics stand today.
    </p>
    <div class="timeline">`;

    for (const evt of events) {
        html += `<div class="timeline-item ${evt.type}">
            <div class="timeline-date">${evt.date}</div>
            <div class="timeline-title">${evt.title}</div>
            <div class="timeline-desc">${evt.desc}</div>
            <div class="timeline-bets">
                <div class="timeline-bets-title">Specific Bets in This Step</div>
                ${evt.bets.map(b => `<div class="timeline-bet"><span>${b}</span></div>`).join('')}
            </div>
            <div class="timeline-indicators">
                ${evt.indicators()}
            </div>
        </div>`;
    }
    html += '</div>';
    return html;
}

function renderPrivateCredit() {
    const stocks = dashData.stocks;
    const econ = dashData.economic;

    function pcStockChip(ticker, label) {
        const s = stocks[ticker];
        if (!s) return '<span style="display:inline-block;padding:2px 8px;background:#555;color:#fff;border-radius:10px;font-size:11px;margin:2px;">' + ticker + ': N/A</span>';
        const color = s.day_change >= 0 ? '#22c55e' : '#ef4444';
        const arrow = s.day_change >= 0 ? '\u25B2' : '\u25BC';
        return '<span style="display:inline-block;padding:2px 8px;background:' + color + '22;color:' + color + ';border:1px solid ' + color + '44;border-radius:10px;font-size:11px;margin:2px;font-weight:600;">' +
            ticker + ' $' + s.current.toFixed(2) + ' ' + arrow + s.day_change.toFixed(1) + '% <span style="color:#999;font-weight:400;">' + label + '</span></span>';
    }

    function pcFredChip(seriesId, label) {
        const e = econ[seriesId];
        if (!e) return '<span style="display:inline-block;padding:2px 8px;background:#555;color:#fff;border-radius:10px;font-size:11px;margin:2px;">' + seriesId + ': N/A</span>';
        return '<span style="display:inline-block;padding:2px 8px;background:#3b82f622;color:#3b82f6;border:1px solid #3b82f644;border-radius:10px;font-size:11px;margin:2px;font-weight:600;">' +
            e.name + ': ' + (typeof e.value === 'number' ? e.value.toFixed(2) : e.value) + ' <span style="color:#999;font-weight:400;">' + label + '</span></span>';
    }

    function stressLevel(value, thresholds) {
        // thresholds = {green: [min,max], yellow: [min,max], red: [min,max]}
        if (!value && value !== 0) return '<span style="color:#888;">N/A</span>';
        if (thresholds.red && value >= thresholds.red) return '<span style="background:#ef444422;color:#ef4444;padding:1px 8px;border-radius:8px;font-size:11px;font-weight:700;">ELEVATED</span>';
        if (thresholds.yellow && value >= thresholds.yellow) return '<span style="background:#f59e0b22;color:#f59e0b;padding:1px 8px;border-radius:8px;font-size:11px;font-weight:700;">WATCH</span>';
        return '<span style="background:#22c55e22;color:#22c55e;padding:1px 8px;border-radius:8px;font-size:11px;font-weight:700;">NORMAL</span>';
    }

    // Compute stress indicators
    const hySpread = econ['BAMLH0A0HYM2'] ? econ['BAMLH0A0HYM2'].value : null;
    const cccSpread = econ['BAMLH0A3HYC'] ? econ['BAMLH0A3HYC'].value : null;
    const fedFunds = econ['FEDFUNDS'] ? econ['FEDFUNDS'].value : null;
    const dgs10 = econ['DGS10'] ? econ['DGS10'].value : null;
    const rrp = econ['RRPONTSYD'] ? econ['RRPONTSYD'].value : null;
    const reserves = econ['WRESBAL'] ? econ['WRESBAL'].value : null;
    const loanTightening = econ['DRTSCILM'] ? econ['DRTSCILM'].value : null;
    const bizd = stocks['BIZD'] ? stocks['BIZD'] : null;
    const vix = stocks['^VIX'] ? stocks['^VIX'] : null;

    let html = '';

    // ---- Header ----
    html += '<div class="section-header" style="margin-bottom:12px;"><h2 style="display:flex;align-items:center;gap:8px;"><span class="material-icons">account_balance</span> Private Credit Systemic Risk Monitor</h2></div>';
    html += '<div style="background:linear-gradient(135deg,#1e293b,#0f172a);border-radius:12px;padding:20px 24px;margin-bottom:24px;border-left:4px solid #3b82f6;">';
    html += '<p style="color:#94a3b8;font-size:14px;line-height:1.7;margin:0;">Based on the <strong style="color:#e2e8f0;">June 2025 Moody\'s Analytics report "Private Credit & Systemic Risk"</strong>, this page monitors real-time indicators across four risk categories that track the depth of interconnection between private credit funds and the regulated financial system. Private credit assets have surged to over <strong style="color:#e2e8f0;">$2 trillion globally</strong>, with ~75% concentrated in the U.S., making it comparable in size to the high-yield bond and leveraged loan markets.</p>';
    html += '</div>';

    // ---- Key metrics bar ----
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:28px;">';

    // BDC ETF
    const bizdPrice = bizd ? '$' + bizd.current.toFixed(2) : 'N/A';
    const bizdChg = bizd ? bizd.day_change : null;
    const bizdColor = bizdChg >= 0 ? '#22c55e' : '#ef4444';
    html += '<div style="background:#1e293b;border-radius:10px;padding:14px;text-align:center;">';
    html += '<div style="font-size:11px;color:#64748b;margin-bottom:4px;">BIZD (BDC ETF)</div>';
    html += '<div style="font-size:22px;font-weight:700;color:' + (bizd ? bizdColor : '#888') + ';">' + bizdPrice + '</div>';
    html += bizd ? '<div style="font-size:12px;color:' + bizdColor + ';">' + (bizdChg >= 0 ? '+' : '') + bizdChg.toFixed(2) + '%</div>' : '';
    html += '</div>';

    // HY Spread
    html += '<div style="background:#1e293b;border-radius:10px;padding:14px;text-align:center;">';
    html += '<div style="font-size:11px;color:#64748b;margin-bottom:4px;">HY Credit Spread</div>';
    html += '<div style="font-size:22px;font-weight:700;color:#f59e0b;">' + (hySpread ? hySpread.toFixed(0) + ' bps' : 'N/A') + '</div>';
    html += '<div style="font-size:12px;">' + stressLevel(hySpread, {yellow: 400, red: 600}) + '</div>';
    html += '</div>';

    // CCC Spread
    html += '<div style="background:#1e293b;border-radius:10px;padding:14px;text-align:center;">';
    html += '<div style="font-size:11px;color:#64748b;margin-bottom:4px;">CCC & Lower Spread</div>';
    html += '<div style="font-size:22px;font-weight:700;color:#f59e0b;">' + (cccSpread ? cccSpread.toFixed(0) + ' bps' : 'N/A') + '</div>';
    html += '<div style="font-size:12px;">' + stressLevel(cccSpread, {yellow: 800, red: 1200}) + '</div>';
    html += '</div>';

    // Fed Funds Rate
    html += '<div style="background:#1e293b;border-radius:10px;padding:14px;text-align:center;">';
    html += '<div style="font-size:11px;color:#64748b;margin-bottom:4px;">Fed Funds Rate</div>';
    html += '<div style="font-size:22px;font-weight:700;color:#8b5cf6;">' + (fedFunds ? fedFunds.toFixed(2) + '%' : 'N/A') + '</div>';
    html += '<div style="font-size:12px;">' + stressLevel(fedFunds, {yellow: 4.5, red: 5.5}) + '</div>';
    html += '</div>';

    // 10Y Treasury
    html += '<div style="background:#1e293b;border-radius:10px;padding:14px;text-align:center;">';
    html += '<div style="font-size:11px;color:#64748b;margin-bottom:4px;">10-Year Treasury</div>';
    html += '<div style="font-size:22px;font-weight:700;color:#8b5cf6;">' + (dgs10 ? dgs10.toFixed(2) + '%' : 'N/A') + '</div>';
    html += '<div style="font-size:12px;">' + stressLevel(dgs10, {yellow: 4.5, red: 5.0}) + '</div>';
    html += '</div>';

    // Loan Tightening
    html += '<div style="background:#1e293b;border-radius:10px;padding:14px;text-align:center;">';
    html += '<div style="font-size:11px;color:#64748b;margin-bottom:4px;">C&I Loan Tightening</div>';
    html += '<div style="font-size:22px;font-weight:700;color:#06b6d4;">' + (loanTightening !== null ? loanTightening.toFixed(1) + '%' : 'N/A') + '</div>';
    html += '<div style="font-size:12px;">' + stressLevel(loanTightening, {yellow: 20, red: 40}) + '</div>';
    html += '</div>';

    html += '</div>';

    // ===========================================================================
    // CATEGORY 1: Interconnectedness & Contagion
    // ===========================================================================
    html += '<div style="background:#1e293b;border-radius:12px;padding:24px;margin-bottom:24px;border-left:4px solid #ef4444;">';
    html += '<h3 style="color:#f8fafc;margin:0 0 6px 0;display:flex;align-items:center;gap:8px;"><span class="material-icons" style="color:#ef4444;">hub</span> Category 1: Interconnectedness & Contagion</h3>';
    html += '<p style="color:#64748b;font-size:13px;margin:0 0 16px 0;">How tightly is private credit woven into the banking and insurance sectors?</p>';

    // BDC Spillover
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">BDC "Spillover" Pricing</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Because private credit funds are opaque, publicly traded BDCs serve as the best available stress signal. Sharp drawdowns indicate fundamental cracks. As of early 2026, BDCs were down ~16% YoY.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#ef4444;">Stress trigger:</strong> BIZD drawdown > 15% from 52-week high, or multiple BDCs trading below NAV</div>';
    html += '<div style="margin-top:8px;">' + pcStockChip('BIZD', 'BDC ETF') + pcStockChip('ARCC', 'Ares') + pcStockChip('MAIN', 'Main St') + pcStockChip('FSK', 'FS KKR') + pcStockChip('BXSL', 'Blackstone') + pcStockChip('OBDC', 'Blue Owl') + pcStockChip('GSBD', 'Goldman') + '</div>';
    html += '</div>';

    // Bank NBFI Exposure
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Bank Lending to Non-Bank Financial Institutions</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Banks provide credit lines and warehouse facilities to private credit funds — accounting for ~11.2% of bank loans in early 2026. Watch for pullbacks in these facilities, which would force funds to dump liquid assets.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#ef4444;">Stress trigger:</strong> Bank stocks declining while credit spreads widen simultaneously; Senior Loan Officer Survey showing tightening > 40%</div>';
    html += '<div style="margin-top:8px;">' + pcStockChip('JPM', 'Largest NBFI lender') + pcStockChip('GS', 'SRT originator') + pcStockChip('MS', 'Wealth channel') + pcStockChip('C', 'Credit lines') + pcFredChip('DRTSCILM', 'Tightening') + '</div>';
    html += '</div>';

    // Significant Risk Transfers
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Significant Risk Transfers (SRTs)</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Banks pay private credit investors to absorb "first loss" risk on loan portfolios. A freeze or spike in SRT pricing indicates banks can\'t offload risk. Monitor bank stock performance alongside credit spreads as a proxy.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#ef4444;">Stress trigger:</strong> Sudden widening of HY spreads + bank stock selloff = potential SRT market freeze</div>';
    html += '<div style="margin-top:8px;">' + pcFredChip('BAMLH0A0HYM2', 'HY spread') + pcFredChip('BAMLH0A3HYC', 'CCC spread') + pcStockChip('GS', 'SRT proxy') + '</div>';
    html += '</div>';

    // Alt Managers
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Alternative Asset Manager Health (GP Side)</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">These firms manage private credit funds. Their stock prices reflect fundraising momentum, deployment pace, and market confidence in the asset class. A drawdown here signals institutional investors pulling back.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#ef4444;">Stress trigger:</strong> Alt manager stocks falling > 20% while fund AUM growth stalls</div>';
    html += '<div style="margin-top:8px;">' + pcStockChip('BX', 'Blackstone') + pcStockChip('APO', 'Apollo') + pcStockChip('ARES', 'Ares') + pcStockChip('KKR', 'KKR') + pcStockChip('OWL', 'Blue Owl') + '</div>';
    html += '</div>';
    html += '</div>';

    // ===========================================================================
    // CATEGORY 2: Masked Stress Indicators
    // ===========================================================================
    html += '<div style="background:#1e293b;border-radius:12px;padding:24px;margin-bottom:24px;border-left:4px solid #f59e0b;">';
    html += '<h3 style="color:#f8fafc;margin:0 0 6px 0;display:flex;align-items:center;gap:8px;"><span class="material-icons" style="color:#f59e0b;">visibility_off</span> Category 2: "Masked" Stress Indicators</h3>';
    html += '<p style="color:#64748b;font-size:13px;margin:0 0 16px 0;">Are borrowers struggling to pay debts even as formal default rates remain low?</p>';

    // PIK Usage
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Payment-in-Kind (PIK) Usage</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">When borrowers can\'t pay cash interest, they add it to the loan principal (PIK). High PIK levels mask cash-flow stress. Currently averaging ~8% for public BDCs. This is not directly available via market data, but BDC stock performance and credit spreads serve as proxies.</p>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px;">';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Current Avg PIK</div><div style="font-size:18px;font-weight:700;color:#f59e0b;">~8%</div><div style="font-size:10px;color:#64748b;">of BDC income</div></div>';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Warning Level</div><div style="font-size:18px;font-weight:700;color:#f59e0b;">12%+</div><div style="font-size:10px;color:#64748b;">widespread stress</div></div>';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Crisis Level</div><div style="font-size:18px;font-weight:700;color:#ef4444;">18%+</div><div style="font-size:10px;color:#64748b;">systemic concern</div></div>';
    html += '</div>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#f59e0b;">Stress trigger:</strong> PIK income exceeding 12% of BDC earnings; rising non-accruals alongside high PIK</div>';
    html += '</div>';

    // True vs Headline Default
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">"True" vs. Headline Default Rates</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">The formal default rate (~2%) understates real stress. Including distressed exchanges and liability management restructurings, the "true" rate approaches ~5%. Distressed exchanges now make up over 60% of all defaults (per Moody\'s Chart 6). Watch credit spreads for real-time signals.</p>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px;">';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Headline Default</div><div style="font-size:18px;font-weight:700;color:#22c55e;">~2%</div><div style="font-size:10px;color:#64748b;">formal rate</div></div>';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">"True" Default</div><div style="font-size:18px;font-weight:700;color:#f59e0b;">~5%</div><div style="font-size:10px;color:#64748b;">incl. restructurings</div></div>';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Distressed Exchanges</div><div style="font-size:18px;font-weight:700;color:#ef4444;">60%+</div><div style="font-size:10px;color:#64748b;">of all defaults</div></div>';
    html += '</div>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#f59e0b;">Stress trigger:</strong> CCC spread > 1200bps; HY spread > 600bps = default wave imminent</div>';
    html += '<div style="margin-top:8px;">' + pcFredChip('BAMLH0A0HYM2', 'HY spread') + pcFredChip('BAMLH0A3HYC', 'CCC spread') + pcStockChip('HYG', 'HY bond ETF') + pcStockChip('JNK', 'HY alt') + '</div>';
    html += '</div>';

    // Interest Coverage
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Interest Coverage Ratios</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Higher-for-longer rates compress the ratio of borrower earnings (EBITDA) to interest expenses. Most private credit loans are floating-rate. The Fed Funds rate and 10-Year yield directly drive this pressure. When EBITA/interest expense drops below 1.5x, defaults accelerate.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#f59e0b;">Stress trigger:</strong> Fed Funds > 5% sustained; 10Y yield > 5%; leveraged loan ETF (BKLN) declining</div>';
    html += '<div style="margin-top:8px;">' + pcFredChip('FEDFUNDS', 'Rate pressure') + pcFredChip('DGS10', '10Y yield') + pcStockChip('BKLN', 'Senior loans') + '</div>';
    html += '</div>';
    html += '</div>';

    // ===========================================================================
    // CATEGORY 3: Structural & Liquidity Fragility
    // ===========================================================================
    html += '<div style="background:#1e293b;border-radius:12px;padding:24px;margin-bottom:24px;border-left:4px solid #8b5cf6;">';
    html += '<h3 style="color:#f8fafc;margin:0 0 6px 0;display:flex;align-items:center;gap:8px;"><span class="material-icons" style="color:#8b5cf6;">water_drop</span> Category 3: Structural & Liquidity Fragility</h3>';
    html += '<p style="color:#64748b;font-size:13px;margin:0 0 16px 0;">Could forced selling or liquidity freezes amplify stress into a systemic event?</p>';

    // Redemption Gates
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Redemption Gates & Liquidity Mismatches</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Semi-liquid "evergreen" and "interval" funds offer redemption windows despite holding illiquid assets. When redemption requests exceed liquidity buffers, funds impose gates — limiting withdrawals. This is a primary trigger for systemic fear, as it signals that asset values may be overstated. Watch credit ETF flows and VIX for early warnings.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#8b5cf6;">Stress trigger:</strong> News of fund gating + VIX spike above 30 + credit ETF outflows</div>';
    html += '<div style="margin-top:8px;">' + pcStockChip('LQD', 'IG liquidity') + pcStockChip('HYG', 'HY flows') + '</div>';
    html += '</div>';

    // Subscription Lines & System Liquidity
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">System Liquidity & Subscription Line Leverage</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Private credit funds use short-term bank loans (subscription lines) to bridge capital calls. A pullback in these lines forces funds to sell liquid assets, spreading stress to public markets. System-wide liquidity (Fed reserves, reverse repo) provides the backdrop — when liquidity tightens, subscription lines are among the first facilities banks pull.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#8b5cf6;">Stress trigger:</strong> Reserve balances declining rapidly; reverse repo near zero; bank stocks falling</div>';
    html += '<div style="margin-top:8px;">' + pcFredChip('RRPONTSYD', 'Reverse repo') + pcFredChip('WRESBAL', 'Fed reserves') + pcStockChip('JPM', 'Bank health') + '</div>';
    html += '</div>';

    // CLO & Structural Complexity
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Private Credit CLOs & Structural Complexity</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Over $100 billion of private credit CLOs now securitize middle-market direct loans. This adds leverage layers invisible to end investors and creates potential for contagion through the structured finance chain. The corporate debt-to-GVA ratio has risen significantly, indicating elevated leverage across the system.</p>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#8b5cf6;">Stress trigger:</strong> CLO tranche downgrades; widening of IG-to-HY spread differential; BKLN declining while loan issuance rises</div>';
    html += '<div style="margin-top:8px;">' + pcStockChip('BKLN', 'Loan market') + pcStockChip('LQD', 'IG credit') + pcFredChip('BAMLH0A0HYM2', 'HY spread') + '</div>';
    html += '</div>';
    html += '</div>';

    // ===========================================================================
    // CATEGORY 4: Sector Concentration Risks
    // ===========================================================================
    html += '<div style="background:#1e293b;border-radius:12px;padding:24px;margin-bottom:24px;border-left:4px solid #06b6d4;">';
    html += '<h3 style="color:#f8fafc;margin:0 0 6px 0;display:flex;align-items:center;gap:8px;"><span class="material-icons" style="color:#06b6d4;">pie_chart</span> Category 4: Sector Concentration Risk</h3>';
    html += '<p style="color:#64748b;font-size:13px;margin:0 0 16px 0;">Is private credit dangerously concentrated in sectors vulnerable to AI disruption?</p>';

    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;margin-bottom:12px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Software & Technology Exposure</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">Private credit has roughly 21% direct exposure to software (approaching 40% when including broader tech services). AI-driven disruption in these sectors could trigger correlated defaults across many funds simultaneously. This is the single largest concentration risk identified in the Moody\'s report.</p>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px;">';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Software Exposure</div><div style="font-size:18px;font-weight:700;color:#06b6d4;">~21%</div><div style="font-size:10px;color:#64748b;">direct allocation</div></div>';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Broad Tech Exposure</div><div style="font-size:18px;font-weight:700;color:#f59e0b;">~40%</div><div style="font-size:10px;color:#64748b;">incl. tech services</div></div>';
    html += '<div style="background:#1e293b;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:10px;color:#64748b;">Private Credit AUM</div><div style="font-size:18px;font-weight:700;color:#e2e8f0;">$2T+</div><div style="font-size:10px;color:#64748b;">global</div></div>';
    html += '</div>';
    html += '<div style="color:#94a3b8;font-size:12px;margin-bottom:6px;"><strong style="color:#06b6d4;">Stress trigger:</strong> IGV drawdown > 25%; cloud/SaaS revenue deceleration; AI agent adoption displacing per-seat software models</div>';
    html += '<div style="margin-top:8px;">' + pcStockChip('IGV', 'Software ETF') + pcStockChip('XLK', 'Tech sector') + pcStockChip('WCLD', 'Cloud/SaaS') + '</div>';
    html += '</div>';

    // Cross-reference with Citrini
    html += '<div style="background:#0f172a;border-radius:8px;padding:16px;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 8px 0;">Cross-Reference: Citrini Memo Overlap</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 10px 0;">The Citrini "2028 Global Intelligence Crisis" memo predicts severe SaaS disruption from AI agents — the same sector where private credit is most concentrated. If Citrini\'s thesis plays out, private credit losses could compound the broader economic shock through the interconnectedness channels tracked above.</p>';
    html += '<div style="margin-top:8px;">' + pcStockChip('NOW', 'ServiceNow') + pcStockChip('CRM', 'Salesforce') + pcStockChip('MNDY', 'Monday.com') + pcStockChip('ASAN', 'Asana') + '</div>';
    html += '</div>';
    html += '</div>';

    // ===========================================================================
    // Report Reference & Disclaimer
    // ===========================================================================
    html += '<div style="background:#0f172a;border-radius:12px;padding:20px 24px;margin-bottom:24px;border:1px solid #1e293b;">';
    html += '<h4 style="color:#e2e8f0;margin:0 0 10px 0;"><span class="material-icons" style="vertical-align:middle;margin-right:6px;font-size:18px;">menu_book</span>Source Report</h4>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 8px 0;"><strong style="color:#e2e8f0;">"Private Credit & Systemic Risk"</strong> — Moody\'s Analytics, June 2025</p>';
    html += '<p style="color:#94a3b8;font-size:13px;margin:0 0 8px 0;">Authors: Samim Ghamami (NYU), Damien Moore (Moody\'s), Antonio Weiss (Harvard Kennedy School), Martin Wurm (Moody\'s), Mark Zandi (Moody\'s Chief Economist)</p>';
    html += '<p style="color:#64748b;font-size:12px;margin:0;font-style:italic;">This dashboard is an independent educational project. It was not developed by Moody\'s Analytics and is not affiliated with or endorsed by Moody\'s. The metrics displayed are publicly available market data used to monitor conditions described in the report. This is not investment advice.</p>';
    html += '</div>';

    return html;
}

function renderRebuttal() {
    const stocks = dashData.stocks;
    const econ = dashData.economic;

    function stockChip(ticker, label) {
        const s = stocks[ticker] || {};
        if (!s.price) return `<div class="tl-indicator"><span class="tl-ticker">${ticker}</span> <span class="tl-label">${label}</span> <span class="tl-price">&mdash;</span></div>`;
        const cls = s.mo3_return >= 0 ? 'positive' : 'negative';
        return `<div class="tl-indicator">
            <span class="tl-ticker">${ticker}</span>
            <span class="tl-price">$${fmt(s.price)}</span>
            <span class="tl-change ${cls}">${changeSign(s.mo3_return)}${fmt(s.mo3_return)}% 3mo</span>
            <span class="tl-label">${label}</span>
        </div>`;
    }
    function fredChip(seriesId, label) {
        const d = econ[seriesId] || {};
        if (d.value === undefined) return `<div class="tl-indicator"><span class="tl-ticker">${seriesId}</span> <span class="tl-label">${label}</span> <span class="tl-price">&mdash;</span></div>`;
        const cls = d.change >= 0 ? 'positive' : 'negative';
        return `<div class="tl-indicator">
            <span class="tl-ticker">${seriesId}</span>
            <span class="tl-price">${fmt(d.value)}</span>
            <span class="tl-change ${cls}">${changeSign(d.change)}${fmt(d.change)}</span>
            <span class="tl-label">${label} (${d.date})</span>
        </div>`;
    }

    return `<div class="rebuttal-container">
        <div class="section-header">
            <span class="material-icons">gavel</span>
            <h2>Rebuttal &mdash; The Counter-Arguments</h2>
        </div>

        <div class="rebuttal-intro">
            <p>Shortly after the Citrini memo went viral, <strong>Ilan Poonjolai</strong> (product leader, ex-Airbnb / Amazon / Meta / Google) published a widely-read response arguing the memo is a valuable stress test but a poor baseline forecast. His core thesis: the memo treats AI deployment as frictionless and policy as asleep, when in reality both are major braking forces.</p>
            <p>Below is a point-by-point comparison of each major claim from the Citrini memo against the rebuttal's counter-argument, with live indicators so you can judge which side the data currently supports.</p>
            <p style="font-size:12px; color:var(--sf-warm-gray-3);">Source: <a href="https://medium.com/@ilanpoonjolai" target="_blank">"A Substack Post Didn't Predict 2028, It Revealed 2026"</a> by Ilan Poonjolai, Feb 2026</p>
        </div>

        <!-- Point 1: Unemployment -->
        <div class="rebuttal-point">
            <h3 style="font-size:15px; font-weight:700; color:var(--sf-dark-navy); margin-bottom:14px;">1. Unemployment &mdash; 10.2% by 2028?</h3>
            <div class="rebuttal-vs">
                <div class="rebuttal-claim">
                    <div class="rebuttal-label">Citrini Memo</div>
                    <p>AI creates a feedback loop with "no natural brake." Companies cut payroll, buy more AI, which gets better, enabling more cuts. White-collar workers are 50% of employment and drive 75% of discretionary spending. Unemployment reaches 10.2% by June 2028.</p>
                </div>
                <div class="rebuttal-counter">
                    <div class="rebuttal-label">Rebuttal</div>
                    <p>The real economy is full of brakes that the memo ignores: integration friction (legacy systems, bad data, security reviews), liability (who's accountable when the agent is wrong), regulation (especially in finance, healthcare, employment), and trust (high-stakes work demands audit trails). Jobs are bundles of tasks &mdash; AI deletes tasks, but employment adjusts slower as roles become "human plus tool," not "human replaced."</p>
                </div>
            </div>
            <div class="rebuttal-analysis">
                <p><strong>What to watch:</strong> The rebuttal says we'll see "higher churn, more role redesign, fewer stable career ladders" but not a clean jump to 10%. If unemployment stays below 5-6% through 2027 despite accelerating AI capabilities, the braking forces are real. If it crosses 6% and the composition is overwhelmingly white-collar, the memo's flywheel is engaging.</p>
            </div>
            <div class="timeline-indicators" style="margin-top:12px;">
                ${fredChip('UNRATE', 'Unemployment rate')}
                ${fredChip('ICSA', 'Jobless claims')}
                ${fredChip('JTSJOL', 'Job openings')}
            </div>
        </div>

        <!-- Point 2: Ghost GDP -->
        <div class="rebuttal-point">
            <h3 style="font-size:15px; font-weight:700; color:var(--sf-dark-navy); margin-bottom:14px;">2. "Ghost GDP" &mdash; Output That Never Circulates?</h3>
            <div class="rebuttal-vs">
                <div class="rebuttal-claim">
                    <div class="rebuttal-label">Citrini Memo</div>
                    <p>A single GPU cluster in North Dakota generating the output previously attributed to 10,000 white-collar workers in Manhattan is "more economic pandemic than panacea." The velocity of money flatlines. The human-centric consumer economy (70% of GDP) withers because machines spend zero on discretionary goods.</p>
                </div>
                <div class="rebuttal-counter">
                    <div class="rebuttal-label">Rebuttal</div>
                    <p>"Machines spend zero" is true but incomplete. If agents squeeze junk fees, negotiate subscriptions, and compress markups, that functions like a broad cost-of-living cut. Money doesn't vanish &mdash; it reallocates. The macro question is whether households capture enough of the surplus to keep demand alive. That's about ownership, bargaining power, and policy &mdash; not a law of nature. Ghost GDP is a risk, not a destiny.</p>
                </div>
            </div>
            <div class="rebuttal-analysis">
                <p><strong>What to watch:</strong> Real PCE (personal consumption expenditure) is the key indicator. If consumer spending holds up even as corporate productivity surges, the surplus is circulating. If PCE contracts while GDP prints positive on productivity alone, "Ghost GDP" is materializing. Also watch the personal savings rate &mdash; if it spikes, employed workers are hoarding out of fear rather than spending.</p>
            </div>
            <div class="timeline-indicators" style="margin-top:12px;">
                ${fredChip('DPCERAM1M225NBEA', 'Real PCE growth')}
                ${fredChip('A191RL1Q225SBEA', 'Real GDP growth')}
                ${fredChip('PSAVERT', 'Savings rate')}
            </div>
        </div>

        <!-- Point 3: Intermediation collapse -->
        <div class="rebuttal-point">
            <h3 style="font-size:15px; font-weight:700; color:var(--sf-dark-navy); margin-bottom:14px;">3. Intermediation Dies &mdash; Agents Destroy All Middlemen?</h3>
            <div class="rebuttal-vs">
                <div class="rebuttal-claim">
                    <div class="rebuttal-label">Citrini Memo</div>
                    <p>Agents remove all friction. Subscriptions that passively renewed get cancelled. Travel platforms, insurance renewals, real estate commissions, financial advice, tax prep &mdash; any category where the value prop was "I navigate complexity you find tedious" gets disrupted. DoorDash margins compress to zero. Card interchange (2-3%) gets routed around via stablecoins. The entire rent-extraction layer built on human limitations disintegrates.</p>
                </div>
                <div class="rebuttal-counter">
                    <div class="rebuttal-label">Rebuttal</div>
                    <p>Correct for <em>bad</em> intermediaries. But "friction" also includes refunds, fraud liability, warranties, dispute resolution, compliance, and making sure reality matches the promise. In a world of infinite cheap answers, the scarce commodity becomes <em>confidence</em>. Cloning an app is easy; building reliable network effects, logistics, liquidity, and service quality is the real moat. Intermediaries don't die &mdash; they mutate and reprice.</p>
                </div>
            </div>
            <div class="rebuttal-analysis">
                <p><strong>What to watch:</strong> DoorDash and Booking are the key bellwethers. If DASH maintains margins and BKNG maintains take rates despite agentic competition, the "trust moat" argument holds. If margins compress rapidly and new entrants grab share, the memo is right that habitual intermediation has no defense against agents. Also watch Mastercard and Visa purchase volume growth &mdash; slowing volume means agents are successfully routing around traditional rails.</p>
            </div>
            <div class="timeline-indicators" style="margin-top:12px;">
                ${stockChip('DASH', 'Margin watch')}
                ${stockChip('BKNG', 'Take rate watch')}
                ${stockChip('MA', 'Volume growth')}
                ${stockChip('V', 'Volume growth')}
                ${stockChip('RDFN', 'Commission compression')}
                ${stockChip('SOL-USD', 'Stablecoin rails')}
            </div>
        </div>

        <!-- Point 4: Credit contagion -->
        <div class="rebuttal-point">
            <h3 style="font-size:15px; font-weight:700; color:var(--sf-dark-navy); margin-bottom:14px;">4. Mortgage & Credit Contagion?</h3>
            <div class="rebuttal-vs">
                <div class="rebuttal-claim">
                    <div class="rebuttal-label">Citrini Memo</div>
                    <p>White-collar incomes are the bedrock of the $13 trillion mortgage market. PE-backed software companies default as ARR assumptions collapse &mdash; Moody's downgrades $18B across 14 issuers. Private credit ($2.5T) is bloated with software deals marked at multiples that no longer exist. The daisy chain of correlated bets unravels.</p>
                </div>
                <div class="rebuttal-counter">
                    <div class="rebuttal-label">Rebuttal</div>
                    <p>The memo assumes "policy coma." In reality, if displacement starts to threaten broad consumption, the incentives to deploy stabilizers become overwhelming &mdash; not optional. IMF leadership has explicitly argued for preemptive stabilizers (wage insurance, portability, stronger safety nets) to prevent ordinary slowdowns from becoming deep slumps. The tools exist; the question is political will.</p>
                </div>
            </div>
            <div class="rebuttal-analysis">
                <p><strong>What to watch:</strong> High-yield credit spreads are the canary. If HY spreads stay below 500bps, the credit market isn't pricing in contagion. If they blow out past 600-700bps, the PE-backed software defaults are cascading. Also watch for any government announcements around AI-specific unemployment insurance, wage insurance programs, or retraining initiatives &mdash; the rebuttal's thesis depends on policy responding in time.</p>
            </div>
            <div class="timeline-indicators" style="margin-top:12px;">
                ${fredChip('BAMLH0A0HYM2', 'HY credit spread')}
                ${stockChip('AXP', 'Consumer credit')}
                ${stockChip('COF', 'Consumer credit')}
                ${stockChip('SYF', 'Consumer credit')}
            </div>
        </div>

        <!-- Point 5: The counter-scenario -->
        <div class="rebuttal-point">
            <h3 style="font-size:15px; font-weight:700; color:var(--sf-dark-navy); margin-bottom:14px;">5. The Alternative &mdash; "Intelligence Dividend" (With Bruises)</h3>
            <div class="rebuttal-vs">
                <div class="rebuttal-claim">
                    <div class="rebuttal-label">Citrini Scenario</div>
                    <p>A self-reinforcing deflationary spiral. AI replaces workers, workers stop spending, companies invest more in AI, AI gets better, more workers replaced. No natural brake. S&P -38%. Unemployment 10.2%. The economy no longer resembles the one any of us grew up in.</p>
                </div>
                <div class="rebuttal-counter">
                    <div class="rebuttal-label">Counter-Scenario</div>
                    <p>Real productivity gains arrive unevenly. Bad fee stacks and lazy markups get crushed, functioning like a consumer-side dividend. Work reorganizes around "centaur" roles: humans doing judgment, relationships, accountability, with AI doing cognitive heavy lifting. Entrepreneurship accelerates as the cost to build, sell, and support collapses. The scary future isn't "AI replaces work" &mdash; it's "AI replaces wages." And that future is optional.</p>
                </div>
            </div>
        </div>

        <!-- Verdict: What would make each side right -->
        <div class="rebuttal-verdict">
            <h3><span class="material-icons">flag</span> What Would Make Each Side Right?</h3>
            <p>The rebuttal identifies three conditions that, if all present simultaneously, would validate the Citrini crisis scenario. Conversely, the opposite conditions would confirm the rebuttal's "intelligence dividend" thesis. Track these as the meta-indicators:</p>

            <div style="margin:20px 0 10px 0; font-size:12px; font-weight:700; color:var(--sf-red); text-transform:uppercase; letter-spacing:0.5px;">Citrini is right if we see all three:</div>
            <div class="trigger-grid">
                <div class="trigger-card bad">
                    <div class="trigger-icon">&#9888;</div>
                    <div class="trigger-label">Rapid Deployment</div>
                    <div style="margin-top:6px; font-size:11px; color:var(--text-primary);">AI deployed at scale without auditability, liability frameworks, or regulatory guardrails</div>
                </div>
                <div class="trigger-card bad">
                    <div class="trigger-icon">&#9888;</div>
                    <div class="trigger-label">Gains Don't Circulate</div>
                    <div style="margin-top:6px; font-size:11px; color:var(--text-primary);">Rising corporate profits alongside falling median incomes &mdash; the surplus pools at the top</div>
                </div>
                <div class="trigger-card bad">
                    <div class="trigger-icon">&#9888;</div>
                    <div class="trigger-label">Policy Paralysis</div>
                    <div style="margin-top:6px; font-size:11px; color:var(--text-primary);">No wage insurance, no portability, no meaningful fiscal response to displacement</div>
                </div>
            </div>

            <div style="margin:20px 0 10px 0; font-size:12px; font-weight:700; color:var(--sf-dark-green); text-transform:uppercase; letter-spacing:0.5px;">Rebuttal is right if we see the opposite:</div>
            <div class="trigger-grid">
                <div class="trigger-card good">
                    <div class="trigger-icon">&#10003;</div>
                    <div class="trigger-label">Adoption Brakes</div>
                    <div style="margin-top:6px; font-size:11px; color:var(--text-primary);">Integration friction, liability concerns, and regulation meaningfully slow the pace of workforce replacement</div>
                </div>
                <div class="trigger-card good">
                    <div class="trigger-icon">&#10003;</div>
                    <div class="trigger-label">Surplus Circulates</div>
                    <div style="margin-top:6px; font-size:11px; color:var(--text-primary);">AI-driven cost compression functions as a consumer dividend &mdash; PCE holds up, demand stays alive</div>
                </div>
                <div class="trigger-card good">
                    <div class="trigger-icon">&#10003;</div>
                    <div class="trigger-label">Policy Responds</div>
                    <div style="margin-top:6px; font-size:11px; color:var(--text-primary);">Governments deploy stabilizers: wage insurance, broadened unemployment coverage, retraining programs</div>
                </div>
            </div>

            <p style="margin-top:16px;">As the rebuttal puts it: "The canary is alive. Let's ventilate the mine before we start writing eulogies." This dashboard helps you watch the canary.</p>
        </div>

    </div>`;
}

function renderAbout() {
    return `<div class="about-container">
        <div class="section-header">
            <span class="material-icons">help_outline</span>
            <h2>About This Dashboard</h2>
        </div>

        <div class="about-section">
            <h3><span class="material-icons">description</span> What This Is</h3>
            <p>This dashboard was built to track the real-world data behind <strong>"The 2028 Global Intelligence Crisis"</strong>, a speculative macro scenario published by <a href="https://www.citriniresearch.com/p/2028gic" target="_blank">Citrini Research</a> and Alap Shah on February 22, 2026. The memo imagines writing from June 2028, looking back at a chain of economic dominoes triggered by rapid AI capability gains — from SaaS disruption and white-collar displacement to a consumer spending collapse and financial crisis.</p>
            <p>The memo is explicitly <strong>not a prediction</strong> — it is a scenario exercise designed to stress-test what happens if AI bullishness is right about capabilities but wrong about the economic consequences. This dashboard takes every specific company, metric, and economic indicator referenced in that scenario and tracks them against live data, so you can monitor in real time whether any of the predicted dominoes are actually falling.</p>
        </div>

        <div class="about-section">
            <h3><span class="material-icons">build</span> How It Was Built</h3>
            <p>This dashboard was built entirely using <a href="https://claude.ai" target="_blank">Claude</a>, Anthropic's AI assistant. The memo PDF was provided as input, and Claude extracted every trackable claim, organized them into thematic sections, wrote the Python backend for data fetching, designed the front-end UI, and wired up the auto-refresh logic — all in a single session.</p>
            <p>The stack is intentionally simple: a single Python file running a <strong>Flask</strong> web server that fetches data on a background thread and serves an embedded HTML dashboard. No build tools, no frameworks, no database — just run the script and open your browser.</p>
        </div>

        <div class="about-section">
            <h3><span class="material-icons">trending_up</span> Stock & Market Data</h3>
            <p>All stock and index data is fetched via <a href="https://pypi.org/project/yfinance/" target="_blank">yfinance</a>, which pulls from Yahoo Finance. The dashboard tracks <strong>25 tickers</strong> organized into 7 thematic groups based on the memo's thesis:</p>
            <table class="about-table">
                <tr><th>Section</th><th>Tickers</th><th>What the Memo Says</th></tr>
                <tr>
                    <td>Market Indices</td>
                    <td><span class="about-tag stock">^GSPC</span><span class="about-tag stock">^IXIC</span><span class="about-tag stock">^TNX</span></td>
                    <td>S&P peaks at ~8,000 (Oct 2026), then draws down -38%. Nasdaq breaks 30k before crash. 10-year yield falls from 4.3% to 3.2%.</td>
                </tr>
                <tr>
                    <td>AI Infrastructure</td>
                    <td><span class="about-tag stock">NVDA</span><span class="about-tag stock">TSM</span><span class="about-tag stock">GEV</span></td>
                    <td>The "winners" — record revenues, 95%+ utilization, sold-out capacity. AI infra keeps performing even as the economy deteriorates.</td>
                </tr>
                <tr>
                    <td>SaaS Disruption</td>
                    <td><span class="about-tag stock">NOW</span><span class="about-tag stock">CRM</span><span class="about-tag stock">MNDY</span><span class="about-tag stock">ASAN</span><span class="about-tag stock">ZM</span></td>
                    <td>ServiceNow ACV growth decelerates from 23% to 14%. Long-tail SaaS hit hardest. Per-seat models break as customers shrink headcount.</td>
                </tr>
                <tr>
                    <td>Payments</td>
                    <td><span class="about-tag stock">MA</span><span class="about-tag stock">V</span><span class="about-tag stock">AXP</span><span class="about-tag stock">SYF</span><span class="about-tag stock">COF</span><span class="about-tag stock">DASH</span></td>
                    <td>Agentic commerce routes around card interchange via stablecoins. Mastercard volume growth slows. AmEx hit hardest. DoorDash margins compress to near zero.</td>
                </tr>
                <tr>
                    <td>India IT Services</td>
                    <td><span class="about-tag stock">INFY</span><span class="about-tag stock">WIT</span><span class="about-tag stock">TCS.NS</span></td>
                    <td>AI coding agents destroy the cost-arbitrage model. Contract cancellations accelerate. Rupee falls 18%.</td>
                </tr>
                <tr>
                    <td>Crypto / Stablecoins</td>
                    <td><span class="about-tag stock">SOL-USD</span><span class="about-tag stock">ETH-USD</span></td>
                    <td>Solana and Ethereum L2s become primary settlement layer for machine-to-machine commerce, replacing card rails.</td>
                </tr>
                <tr>
                    <td>Consumer</td>
                    <td><span class="about-tag stock">XLY</span><span class="about-tag stock">BKNG</span><span class="about-tag stock">RDFN</span></td>
                    <td>Consumer discretionary collapses. Travel platforms disintermediated. Real estate commissions compress from 3% to under 1%.</td>
                </tr>
            </table>
            <p>For each ticker, the dashboard shows the current price, daily change, 1/3/6-month returns, a 30-day sparkline chart, and the 6-month high/low range. Data refreshes automatically every 5 minutes.</p>
        </div>

        <div class="about-section">
            <h3><span class="material-icons">bar_chart</span> Economic Indicators</h3>
            <p>Economic data is fetched from the <a href="https://fred.stlouisfed.org/" target="_blank">Federal Reserve Economic Data (FRED)</a> API, maintained by the Federal Reserve Bank of St. Louis. This requires a free API key (set <code>FRED_API_KEY</code> in the Python script). The dashboard tracks <strong>8 series</strong>:</p>
            <table class="about-table">
                <tr><th>FRED Series</th><th>Indicator</th><th>Memo Target</th></tr>
                <tr><td><span class="about-tag econ">UNRATE</span></td><td>Unemployment Rate</td><td>Rises to 10.2% by June 2028</td></tr>
                <tr><td><span class="about-tag econ">ICSA</span></td><td>Initial Jobless Claims</td><td>Surges to 487,000 (highest since April 2020)</td></tr>
                <tr><td><span class="about-tag econ">JTSJOL</span></td><td>JOLTS Job Openings</td><td>Falls below 5.5 million (-15% YoY)</td></tr>
                <tr><td><span class="about-tag econ">PSAVERT</span></td><td>Personal Savings Rate</td><td>Ticks higher as employed professionals fear layoffs</td></tr>
                <tr><td><span class="about-tag econ">DPCERAM1M225NBEA</span></td><td>Real PCE Growth</td><td>Consumer economy (70% of GDP) contracts</td></tr>
                <tr><td><span class="about-tag econ">A191RL1Q225SBEA</span></td><td>Real GDP Growth</td><td>Two consecutive negative quarters by Q2 2027</td></tr>
                <tr><td><span class="about-tag econ">BAMLH0A0HYM2</span></td><td>High-Yield Credit Spread</td><td>Widens as PE-backed software defaults cascade</td></tr>
                <tr><td><span class="about-tag econ">DEXINUS</span></td><td>USD/INR Exchange Rate</td><td>Rupee falls 18% as IT services surplus evaporates</td></tr>
            </table>
        </div>

        <div class="about-section">
            <h3><span class="material-icons">sync</span> Data Sources & Refresh</h3>
            <table class="about-table">
                <tr><th>Source</th><th>Data</th><th>Update Frequency</th></tr>
                <tr>
                    <td><span class="about-tag source">Yahoo Finance</span></td>
                    <td>Stock prices, index levels, crypto prices, daily/historical OHLCV</td>
                    <td>Every 5 minutes (market hours: real-time delayed ~15 min; after hours: last close)</td>
                </tr>
                <tr>
                    <td><span class="about-tag source">FRED API</span></td>
                    <td>Unemployment, jobless claims, JOLTS, savings rate, PCE, GDP, HY spreads, USD/INR</td>
                    <td>Every 5 minutes (underlying data updates monthly, weekly, or quarterly depending on series)</td>
                </tr>
            </table>
            <p>The dashboard runs a background thread that re-fetches all data every 5 minutes. The browser auto-refreshes on the same interval. You can also force a manual refresh using the button in the top-right corner. All data is fetched and processed locally — nothing is sent to any third-party service beyond the Yahoo Finance and FRED API calls.</p>
        </div>

        <div class="about-section">
            <h3><span class="material-icons">schedule</span> Dashboard Tabs</h3>
            <table class="about-table">
                <tr><th>Tab</th><th>What It Shows</th></tr>
                <tr><td>Overview</td><td>All 25 tickers at a glance with key market stats at the top, organized by the memo's thematic groups. Each card shows price, returns, sparkline, and the specific memo prediction.</td></tr>
                <tr><td>Markets</td><td>S&P 500, Nasdaq, and 10-Year Treasury — the top-level macro picture.</td></tr>
                <tr><td>AI Infra</td><td>NVIDIA, Taiwan Semi, GE Vernova — the memo's "winners" that keep performing even during the crisis.</td></tr>
                <tr><td>SaaS</td><td>ServiceNow, Salesforce, Monday.com, Asana, Zoom — the software disruption zone.</td></tr>
                <tr><td>Payments</td><td>Mastercard, Visa, AmEx, Synchrony, Capital One, DoorDash — interchange and intermediation under threat.</td></tr>
                <tr><td>India IT</td><td>Infosys, Wipro, TCS — the IT services export crisis.</td></tr>
                <tr><td>Crypto</td><td>Solana and Ethereum — new stablecoin payment rails replacing card networks.</td></tr>
                <tr><td>Consumer</td><td>Consumer discretionary ETF, Booking Holdings, Redfin — demand destruction and commission compression.</td></tr>
                <tr><td>Economic</td><td>All 8 FRED indicators with current values, trends, and memo targets.</td></tr>
                <tr><td>Timeline</td><td>Chronological sequence of every predicted domino from the memo, with the specific testable bets at each step and live indicator chips showing where those metrics stand today.</td></tr>
                <tr><td>Private Credit</td><td>Systemic risk monitor based on the June 2025 Moody's Analytics report. Tracks BDC health, bank NBFI exposure, credit spreads, interest rate pressure, system liquidity, and software sector concentration risk across 4 categories with live stress indicators.</td></tr>
            </table>
        </div>

        <div class="about-section">
            <h3><span class="material-icons">warning</span> Important Disclaimers</h3>
            <p>The underlying memo is explicitly a <strong>speculative scenario exercise</strong>, not a forecast. The authors describe it as modeling a "relatively underexplored" left-tail risk. This dashboard is a monitoring tool — it does not endorse, validate, or recommend any investment thesis.</p>
            <p>Nothing on this dashboard constitutes financial advice. Stock prices and economic data are provided for informational purposes only. Always do your own research and consult qualified professionals before making investment decisions.</p>
            <p>Data from Yahoo Finance may be delayed up to 15 minutes during market hours. FRED data updates on varying schedules (monthly for unemployment, weekly for jobless claims, quarterly for GDP). The dashboard shows the latest available observation for each series.</p>
        </div>

        <div class="about-section" style="text-align:center; color:var(--sf-warm-gray-3); font-size:12px; padding:16px;">
            Built with Claude by Anthropic &middot; Data from Yahoo Finance & FRED &middot; Memo by <a href="https://www.citriniresearch.com/p/2028gic" target="_blank">Citrini Research & Alap Shah</a> &middot; Private Credit analysis based on Moody's Analytics (June 2025)
        </div>
    </div>`;
}

// ---- Init ----
fetchData();
setInterval(fetchData, AUTO_REFRESH_MS);
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# Production startup: refresh data and start background thread immediately
# (needed for gunicorn, which doesn't run the if __name__ block)
# ---------------------------------------------------------------------------
refresh_data()
_bg = threading.Thread(target=background_refresh, daemon=True)
_bg.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
