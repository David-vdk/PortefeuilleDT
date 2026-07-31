#!/usr/bin/env python3
"""
Haalt dagkoersen op bij Yahoo Finance voor de fondsen in de portefeuille-tracker.
Gebruikt enkel de Python-standaardbibliotheek (geen pip install nodig).

Schrijft:
  - prices.json   : laatste koers per fonds (voor de "huidige waarde"-weergave)
  - history.json  : volledige koersreeks per fonds (voor de waardeverloop-grafiek)

Belangrijk:
  - Controleert de munt van elk fonds. Als Yahoo een andere munt teruggeeft dan
    verwacht (EUR), wordt de koers NIET opgeslagen -- beter geen koers dan een foute.
  - Bij een mislukte ophaling voor een fonds valt het script terug op de laatst
    bekende koers uit het bestaande prices.json, zodat een storing niet één fonds
    op nul zet.
  - Slaat dagen zonder slotkoers over (feestdagen geven null bij Yahoo).
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ISIN -> (Yahoo-ticker, verwachte munt)
FONDSEN = {
    "IE00BF4RFH31": {"ticker": "IUSN.DE", "munt": "EUR", "naam": "iShares MSCI World Small Cap"},
    "IE00BKM4GZ66": {"ticker": "EMIM.AS", "munt": "EUR", "naam": "iShares Core MSCI EM IMI"},
    "IE00BSPLC298": {"ticker": "ZPRX.DE", "munt": "EUR", "naam": "SPDR MSCI Europe Small Cap Value"},
    "IE00BSPLC413": {"ticker": "ZPRV.DE", "munt": "EUR", "naam": "SPDR MSCI USA Small Cap Value"},
    "IE00B48X4842": {"ticker": "SPYX.DE", "munt": "EUR", "naam": "SPDR MSCI EM Small Cap"},
    "IE00BL25JP72": {"ticker": "XDEM.DE", "munt": "EUR", "naam": "Xtrackers MSCI World Momentum"},
    "IE00BL25JM42": {"ticker": "XDEV.DE", "munt": "EUR", "naam": "Xtrackers MSCI World Value"},
    # Referte-index -- geen echte positie, enkel voor vergelijking op de Groei-grafiek
    "IE00B4L5Y983": {"ticker": "IWDA.AS", "munt": "EUR", "naam": "iShares Core MSCI World (referentie)"},
}

PRICES_PATH = "prices.json"
HISTORY_PATH = "history.json"
USER_AGENT = "Mozilla/5.0 (compatible; portefeuille-tracker/1.0)"


def haal_yahoo_data(ticker, range_str):
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?range={range_str}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"Geen data teruggekregen voor {ticker}")
    return result[0]


def verwerk_resultaat(result, verwachte_munt):
    meta = result.get("meta", {})
    munt = meta.get("currency")
    if munt != verwachte_munt:
        raise ValueError(f"Munt komt niet overeen: verwacht {verwachte_munt}, kreeg {munt}")

    timestamps = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])

    reeks = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue  # feestdag / geen handel die dag
        datum = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        reeks.append({"datum": datum, "koers": round(close, 4)})

    # Ontdubbel op datum (Yahoo geeft soms de huidige dag dubbel als de markt nog open is)
    per_datum = {r["datum"]: r["koers"] for r in reeks}
    reeks = [{"datum": d, "koers": per_datum[d]} for d in sorted(per_datum.keys())]
    return reeks


def main():
    eerste_run = not os.path.exists(HISTORY_PATH)
    range_str = "10y" if eerste_run else "5d"

    bestaande_prices = {}
    bestaande_history = {}
    if os.path.exists(PRICES_PATH):
        with open(PRICES_PATH, "r", encoding="utf-8") as f:
            bestaande_prices = json.load(f)
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            bestaande_history = json.load(f)

    nieuwe_prices = dict(bestaande_prices)
    nieuwe_history = dict(bestaande_history)

    for isin, info in FONDSEN.items():
        ticker = info["ticker"]
        try:
            result = haal_yahoo_data(ticker, range_str)
            reeks = verwerk_resultaat(result, info["munt"])
            if not reeks:
                raise ValueError("Lege koersreeks ontvangen")

            if eerste_run or isin not in nieuwe_history:
                nieuwe_history[isin] = reeks
            else:
                # Voeg enkel nieuwe datums toe aan de bestaande reeks
                bekende_datums = {r["datum"] for r in nieuwe_history[isin]}
                for r in reeks:
                    if r["datum"] not in bekende_datums:
                        nieuwe_history[isin].append(r)
                nieuwe_history[isin].sort(key=lambda r: r["datum"])

            nieuwe_prices[isin] = {
                "ticker": ticker,
                "naam": info["naam"],
                "koers": reeks[-1]["koers"],
                "datum": reeks[-1]["datum"],
            }
            print(f"OK  {isin} ({ticker}): {reeks[-1]['koers']} EUR op {reeks[-1]['datum']}")

        except (urllib.error.URLError, ValueError, KeyError, IndexError) as e:
            # Val terug op de laatst bekende koers -- liever een oude koers dan een storing
            # die het hele fonds op nul zet.
            if isin in bestaande_prices:
                nieuwe_prices[isin] = bestaande_prices[isin]
                print(f"WAARSCHUWING {isin} ({ticker}): ophalen mislukt ({e}). "
                      f"Val terug op laatst bekende koers van {bestaande_prices[isin].get('datum')}.")
            else:
                print(f"FOUT {isin} ({ticker}): ophalen mislukt ({e}), en geen eerdere koers bekend.")

    nieuwe_prices["_bijgewerkt_op"] = datetime.now(timezone.utc).isoformat()

    with open(PRICES_PATH, "w", encoding="utf-8") as f:
        json.dump(nieuwe_prices, f, ensure_ascii=False, indent=2)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(nieuwe_history, f, ensure_ascii=False, indent=2)

    print(f"\nKlaar. {PRICES_PATH} en {HISTORY_PATH} bijgewerkt.")


if __name__ == "__main__":
    main()
