"""
Nifty 500 Sector Intelligence - daily data updater
Downloads Yahoo Finance prices, calculates stock/sector metrics, writes all artifacts into Output,
then generates Output/index.html and Output/sector_dashboard.html.
"""
from pathlib import Path
from datetime import datetime
import json
import shutil
import time
import warnings
import webbrowser
import argparse
import urllib.request
from io import BytesIO
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
BASE = Path(__file__).resolve().parent
INPUT = BASE / "Input" / "nifty500_stocks.csv"
OUTPUT = BASE / "Output"
TEMPLATE = BASE / "dashboard_template.html"
PERIODS = {"1M":1,"3M":3,"6M":6,"1Y":12,"3Y":36,"5Y":60,"10Y":120,"Since Inception":None}

def log(message):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line=f"[{stamp}] {message}"
    print(line, flush=True)
    OUTPUT.mkdir(exist_ok=True)
    with (OUTPUT/"update.log").open("a", encoding="utf-8") as f:
        f.write(line+"\n")

def yahoo_symbol(value):
    s=str(value).strip().upper()
    if not s or s in {"NAN","NONE","NAT"}: return ""
    return s if s.endswith((".NS",".BO")) else s+".NS"

NIFTY500_CSV_URLS = [
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
]

def read_csv_with_browser_headers(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
            "Accept": "text/csv,text/plain,*/*",
            "Referer": "https://www.niftyindices.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return pd.read_csv(BytesIO(response.read()))

def load_universe():
    INPUT.parent.mkdir(parents=True, exist_ok=True)
    raw = None
    if INPUT.exists():
        raw = pd.read_csv(INPUT)
        if raw.empty:
            raise ValueError(f"Input CSV is empty: {INPUT}")

    # The ZIP originally contained a tiny example CSV. If it is missing or clearly
    # not the full index, attempt to refresh it from the official Nifty Indices CSV.
    if raw is None or len(raw) < 400:
        old_count = 0 if raw is None else len(raw)
        log(f"Input contains {old_count} rows; trying to obtain the full Nifty 500 constituent list.")
        fetched = None
        errors = []
        for url in NIFTY500_CSV_URLS:
            try:
                candidate = read_csv_with_browser_headers(url)
                cmap_try = {str(c).strip().lower(): c for c in candidate.columns}
                sym_try = next((cmap_try[k] for k in ["symbol", "ticker", "tradingsymbol", "nse symbol", "stock", "security id"] if k in cmap_try), None)
                if sym_try and len(candidate) >= 400:
                    fetched = candidate
                    log(f"Downloaded {len(candidate)} rows from official constituents source.")
                    break
                errors.append(f"{url}: unexpected columns/row count")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        if fetched is not None:
            raw = fetched
            # Save the actual full list so future runs use the same universe and sector mapping.
            raw.to_csv(INPUT, index=False)
            log(f"Saved full constituent list to {INPUT}.")
        elif raw is None or len(raw) < 400:
            raise RuntimeError(
                "The bundled/input CSV contains fewer than 400 rows and the full official Nifty 500 CSV "
                "could not be downloaded. Check internet access, then place the full ind_nifty500list.csv "
                f"at {INPUT}. Download attempts: {' | '.join(errors)}"
            )

    cmap = {str(c).strip().lower(): c for c in raw.columns}
    symcol = next((cmap[k] for k in ["symbol", "ticker", "tradingsymbol", "nse symbol", "stock", "security id"] if k in cmap), raw.columns[0])
    # NSE's official file uses the "Industry" column. Use it as the sector grouping.
    seccol = next((cmap[k] for k in ["sector", "industry", "sector name", "industry group", "macro economic sector"] if k in cmap), None)

    out = pd.DataFrame()
    out["DisplaySymbol"] = raw[symcol].astype(str).str.strip().str.upper().str.replace(".NS", "", regex=False)
    out["Symbol"] = raw[symcol].astype(str).str.strip().map(yahoo_symbol)
    out = out[out["Symbol"].ne("")].drop_duplicates("Symbol").reset_index(drop=True)

    if seccol:
        sector_map = dict(zip(raw[symcol].astype(str).str.strip().map(yahoo_symbol), raw[seccol].astype(str).str.strip()))
        out["Sector"] = out["Symbol"].map(sector_map).fillna("Unclassified")
        out.loc[out["Sector"].isin(["nan", "None", "", "N/A"]), "Sector"] = "Unclassified"
    else:
        out["Sector"] = "Unclassified"

    sector_count = out["Sector"].nunique()
    log(f"Universe ready: {len(out)} unique constituents across {sector_count} sector/industry groups.")
    if len(out) < 400:
        raise RuntimeError(f"Only {len(out)} constituents loaded; refusing to run a partial Nifty 500 scan.")
    if sector_count <= 3:
        raise RuntimeError(
            f"Only {sector_count} sector groups found in the input CSV. Use the official Nifty 500 CSV "
            "with its Industry column, not a symbol-only/sample file."
        )
    return out

def fetch_prices(symbols, period="max"):
    parts=[]
    for start in range(0,len(symbols),40):
        chunk=symbols[start:start+40]
        log(f"Downloading price history: symbols {start+1}-{min(start+len(chunk),len(symbols))} of {len(symbols)}")
        try:
            raw=yf.download(chunk,period=period,interval="1d",auto_adjust=True,group_by="ticker",progress=False,threads=True,timeout=30)
            if raw is None or raw.empty: continue
            if isinstance(raw.columns,pd.MultiIndex):
                lev0=raw.columns.get_level_values(0); lev1=raw.columns.get_level_values(1)
                for sym in chunk:
                    try:
                        if sym in lev0:
                            one=raw[sym]
                            if "Close" in one: parts.append(one["Close"].rename(sym))
                        elif sym in lev1:
                            one=raw.xs(sym,axis=1,level=1)
                            if "Close" in one: parts.append(one["Close"].rename(sym))
                    except Exception: pass
            elif len(chunk)==1 and "Close" in raw:
                parts.append(raw["Close"].rename(chunk[0]))
        except Exception as e:
            log(f"Download chunk failed ({chunk[0]}...): {e}")
    if not parts: return pd.DataFrame()
    result=pd.concat(parts,axis=1)
    result=result.loc[:,~result.columns.duplicated()].sort_index()
    return result.dropna(how="all")

def pct_return(series, months):
    s=series.dropna()
    if len(s)<2: return np.nan
    if months is None: base=float(s.iloc[0])
    else:
        cutoff=s.index[-1]-pd.DateOffset(months=months)
        old=s.loc[s.index<=cutoff]
        if old.empty: return np.nan
        base=float(old.iloc[-1])
    return (float(s.iloc[-1])/base-1)*100 if base else np.nan

def trend_label(price,e20,e50,e200):
    if all(pd.notna(x) for x in [price,e20,e50,e200]):
        if price>e50>e200 and e20>e50: return "Uptrend"
        if price<e50<e200: return "Downtrend"
    return "Flat / Transition"

def build_analysis(prices, universe):
    prices=prices.sort_index().ffill(limit=3)
    stock_rows=[]; sector_lines={}
    for _,row in universe.iterrows():
        sym=row["Symbol"]
        if sym not in prices: continue
        s=prices[sym].dropna()
        if len(s)<30: continue
        e20=s.ewm(span=20,adjust=False).mean(); e50=s.ewm(span=50,adjust=False).mean(); e200=s.ewm(span=200,adjust=False).mean()
        delta=s.diff(); avg_gain=delta.clip(lower=0).rolling(14).mean(); avg_loss=-delta.clip(upper=0).rolling(14).mean()
        rs=avg_gain/avg_loss.replace(0,np.nan); rsi=100-100/(1+rs)
        last=float(s.iloc[-1]); high3=float(s.tail(63).max())
        dd=(last/high3-1)*100 if high3 else np.nan
        last30=s.tail(30); base_range=((last30.max()-last30.min())/last30.mean()*100) if last30.mean() else np.nan
        slope=(e20.iloc[-1]/e20.iloc[-6]-1)*100 if len(e20)>=6 else np.nan
        rsi_now=float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else np.nan
        rsi_prior=float(rsi.iloc[-11]) if len(rsi)>11 and pd.notna(rsi.iloc[-11]) else np.nan
        early=bool(pd.notna(dd) and -18<=dd<=-2 and pd.notna(base_range) and base_range<=12 and last>e20.iloc[-1] and pd.notna(slope) and slope>0 and pd.notna(rsi_now) and rsi_now>=45 and (pd.isna(rsi_prior) or rsi_now>=rsi_prior))
        ret={f"{p} %":pct_return(s,m) for p,m in PERIODS.items()}
        valid=[ret[k] for k in ["1M %","3M %","6M %","1Y %"] if pd.notna(ret[k])]
        stock_rows.append({"Symbol":row["DisplaySymbol"],"YahooTicker":sym,"Sector":row["Sector"],"Price":last,**ret,
          "Trend":trend_label(last,e20.iloc[-1],e50.iloc[-1],e200.iloc[-1]),"RSI 14":rsi_now,
          "20 EMA":float(e20.iloc[-1]),"50 EMA":float(e50.iloc[-1]),"200 EMA":float(e200.iloc[-1]),
          "From 52W High %":(last/s.tail(252).max()-1)*100,"From 3M High %":dd,"Base Range 1M %":base_range,
          "20EMA Slope %":slope,"Early Reversal":early,"Strength Score":float(np.mean(valid)) if valid else np.nan})
    # Preserve every constituent in the screener, even if Yahoo Finance has no usable
    # price history for a symbol. Such rows are explicitly marked "No Data".
    priced_symbols = {r["YahooTicker"] for r in stock_rows}
    for _, row in universe.iterrows():
        sym = row["Symbol"]
        if sym in priced_symbols:
            continue
        missing_row = {"Symbol": row["DisplaySymbol"], "YahooTicker": sym, "Sector": row["Sector"],
            "Price": np.nan, **{f"{p} %": np.nan for p in PERIODS},
            "Trend": "No Data", "RSI 14": np.nan, "20 EMA": np.nan, "50 EMA": np.nan,
            "200 EMA": np.nan, "From 52W High %": np.nan, "From 3M High %": np.nan,
            "Base Range 1M %": np.nan, "20EMA Slope %": np.nan, "Early Reversal": False,
            "Strength Score": np.nan}
        stock_rows.append(missing_row)
    stocks=pd.DataFrame(stock_rows)
    if stocks.empty: return stocks,pd.DataFrame(),pd.DataFrame(),prices
    for sector in stocks["Sector"].fillna("Unclassified").unique():
        tickers=stocks.loc[stocks["Sector"]==sector,"YahooTicker"].tolist()
        tickers=[t for t in tickers if t in prices.columns]
        if not tickers: continue
        block=prices[tickers]
        normalized=block.divide(block.ffill().bfill().iloc[0]).multiply(100)
        sector_lines[sector]=normalized.mean(axis=1,skipna=True)
    sector_prices=pd.DataFrame(sector_lines)
    rows=[]
    all_sectors = sorted(set(universe["Sector"].fillna("Unclassified").astype(str)))
    for sector in all_sectors:
        count = int((universe["Sector"] == sector).sum())
        if sector not in sector_prices.columns or sector_prices[sector].dropna().shape[0] < 30:
            rows.append({"Sector": sector, "Index Level (base 100)": np.nan,
                **{f"{p} %": np.nan for p in PERIODS},
                "Trend": "No Data", "From 3M High %": np.nan, "Base Range 1M %": np.nan,
                "20EMA Slope %": np.nan, "Early Reversal Watch": False, "Stocks": count})
            continue
        s=sector_prices[sector].dropna()
        e20=s.ewm(span=20,adjust=False).mean();e50=s.ewm(span=50,adjust=False).mean();e200=s.ewm(span=200,adjust=False).mean()
        last=float(s.iloc[-1]);last30=s.tail(30)
        base_range=(last30.max()-last30.min())/last30.mean()*100 if last30.mean() else np.nan
        dd=(last/s.tail(63).max()-1)*100 if s.tail(63).max() else np.nan
        slope=(e20.iloc[-1]/e20.iloc[-6]-1)*100 if len(e20)>6 else np.nan
        early=bool(pd.notna(dd) and -18<=dd<=-2 and pd.notna(base_range) and base_range<=10 and last>e20.iloc[-1] and pd.notna(slope) and slope>0)
        rows.append({"Sector":sector,"Index Level (base 100)":last,**{f"{p} %":pct_return(s,m) for p,m in PERIODS.items()},
          "Trend":trend_label(last,e20.iloc[-1],e50.iloc[-1],e200.iloc[-1]),"From 3M High %":dd,
          "Base Range 1M %":base_range,"20EMA Slope %":slope,"Early Reversal Watch":early,
          "Stocks": count})
    return stocks,pd.DataFrame(rows),sector_prices,prices

def clean_records(df):
    # pandas JSON converts NaN to null and ensures JSON-compatible scalar values.
    return json.loads(df.replace({np.nan:None}).to_json(orient="records"))

def main(open_browser=True):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    log("Starting Nifty 500 data update.")
    universe=load_universe()
    log(f"Loaded {len(universe)} unique symbols.")
    prices=fetch_prices(universe["Symbol"].tolist(),"max")
    if prices.empty: raise RuntimeError("Yahoo Finance returned no usable price data. Check internet and ticker symbols.")
    stocks,sectors,sector_prices,prices=build_analysis(prices,universe)
    if stocks.empty or sectors.empty: raise RuntimeError("Not enough usable history to build the dashboard.")
    stocks=stocks.sort_values("Strength Score",ascending=False,na_position="last")
    sectors=sectors.sort_values("6M %",ascending=False,na_position="last")
    stocks.to_csv(OUTPUT/"nifty500_stock_performance.csv",index=False)
    universe.to_csv(OUTPUT/"nifty500_all_constituents.csv",index=False)
    sectors.to_csv(OUTPUT/"nifty500_sector_scorecard.csv",index=False)
    sector_prices.to_csv(OUTPUT/"nifty500_sector_history.csv",index_label="Date")
    prices.to_csv(OUTPUT/"nifty500_prices_history.csv",index_label="Date")
    asof=prices.dropna(how="all").index.max()
    # Use the first available sector composite history for true since-inception charts.
    history={}
    for sec in sector_prices.columns:
        ser=sector_prices[sec].dropna()
        history[sec]={"dates":[d.strftime("%Y-%m-%d") for d in ser.index],
                      "values":[round(float(v),5) for v in ser.values]}
    stock_history={}
    for _,r in stocks.iterrows():
        ticker=r["YahooTicker"]
        if ticker not in prices.columns: continue
        ser=prices[ticker].dropna()
        stock_history[ticker]={"dates":[d.strftime("%Y-%m-%d") for d in ser.index],
          "close":[round(float(v),4) for v in ser.values],
          "ema20":[round(float(v),4) for v in ser.ewm(span=20,adjust=False).mean().values],
          "ema50":[round(float(v),4) for v in ser.ewm(span=50,adjust=False).mean().values],
          "ema200":[round(float(v),4) for v in ser.ewm(span=200,adjust=False).mean().values]}
    payload={"sectors":clean_records(sectors),"stocks":clean_records(stocks),"history":history,
             "stockHistory":stock_history,"defaultTf":"6M","asOf":asof.strftime("%Y-%m-%d"),
             "updatedAt":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    template=TEMPLATE.read_text(encoding="utf-8")
    if "__DATA__" not in template: raise RuntimeError("Template missing __DATA__ placeholder.")
    dashboard=template.replace("__DATA__",json.dumps(payload,allow_nan=False,separators=(",",":")))
    (OUTPUT/"index.html").write_text(dashboard,encoding="utf-8")
    (OUTPUT/"sector_dashboard.html").write_text(dashboard,encoding="utf-8")
    # Small metadata file for health checks/logging.
    (OUTPUT/"last_update.json").write_text(json.dumps({"updatedAt":payload["updatedAt"],"asOf":payload["asOf"],
      "symbolsLoaded":len(universe),"stocksAnalysed":len(stocks),"sectors":len(sectors)},indent=2),encoding="utf-8")
    log(f"Update completed: {len(stocks)} stocks, {len(sectors)} sectors, prices through {asof:%Y-%m-%d}.")
    # Include PWA install/offline shell assets in the deployed Output directory.
    for asset in ("manifest.webmanifest", "service-worker.js"):
        src = ROOT / asset
        if src.exists(): shutil.copy2(src, OUTPUT / asset)
    src_icons = ROOT / "icons"
    if src_icons.exists():
        shutil.copytree(src_icons, OUTPUT / "icons", dirs_exist_ok=True)
    log("Outputs saved to Output/.")
    if open_browser:
        webbrowser.open((OUTPUT/"index.html").resolve().as_uri())
    return 0

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--no-open",action="store_true",help="Generate files without opening the browser")
    args=parser.parse_args()
    try:
        raise SystemExit(main(open_browser=not args.no_open))
    except Exception as exc:
        log(f"ERROR: {exc}")
        raise
