"""
Pure (Streamlit-free) logic for the Brand Health Tracker dashboard.

Kept separate from app.py so it can be unit-tested without a Streamlit runtime,
and so the Streamlit view and any other consumer share ONE implementation of the
statistics (Share of Voice, MAD anomaly detection, Report-Horizon bucketing).

Design notes that mirror the interactive static dashboard (dashboard/index.html):
  * "Platform" terminology (these are consumer apps / platforms).
  * Store reviews only — Reddit rows are dropped on load.
  * Share of Voice replaces raw mention counts so switching the Report Horizon
    (Weekly / Monthly / Yearly) never makes totals spike.
  * Anomalies use Median Absolute Deviation (robust) instead of mean+1.5*std.
  * Unclassified complaints fall into an explicit "Others / Unclassified" theme.
"""
from __future__ import annotations

import datetime
import statistics

import pandas as pd

# Deterministic per-platform identity colors (unchanged hex badges).
PLATFORM_COLORS = {
    "Swiggy": "#F97316", "Zomato": "#E11D48", "Blinkit": "#CA8A04", "Zepto": "#7C3AED",
    "Amazon": "#F59E0B", "Flipkart": "#2874F0", "Meesho": "#EC4899",
}
OTHERS = "Others / Unclassified"

# The two competitive clusters (benchmark within-set only).
CLUSTERS = {
    "Food & quick commerce": ["Swiggy", "Zomato", "Blinkit", "Zepto"],
    "E-commerce": ["Amazon", "Flipkart", "Meesho"],
}
CLUSTER_OF = {b: c for c, bs in CLUSTERS.items() for b in bs}


# ── data loading / normalization ─────────────────────────────────────────────
def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a raw scored_mentions frame into the dashboard's shape.

    Drops Reddit rows (store reviews only), reduces pipe-joined themes to the
    first tag, and routes unclassified complaints to 'Others / Unclassified'.
    """
    if df.empty:
        return df
    df = df.copy()
    if "source" in df.columns:
        df = df[df["source"] != "reddit"]
    # one theme per row (first tagged); unclassified complaints -> OTHERS
    if "themes" in df.columns:
        df["theme"] = df["themes"].fillna("").map(lambda s: s.split("|")[0] if s else None)
    elif "theme" not in df.columns:
        df["theme"] = None
    cmask = df["is_complaint"] == 1
    df.loc[cmask & df["theme"].isna(), "theme"] = OTHERS
    df.loc[cmask & (df["theme"] == ""), "theme"] = OTHERS
    return df.reset_index(drop=True)


def generate_sample_df(seed: int = 42) -> pd.DataFrame:
    """Deterministic demo data so a fresh deploy shows a full dashboard.

    Uses ISO-week labels (YYYY-Www) so the monthly/yearly horizons derive real
    calendar buckets — exactly like live pipeline output (analyze.py emits %G-W%V).
    Clearly labelled as sample data by the caller; never presented as real telemetry.
    """
    import random
    rng = random.Random(seed)
    year = datetime.date.today().isocalendar()[0]
    weeks = [f"{year}-W{w:02d}" for w in range(20, 26)]
    bias = {"Swiggy": .38, "Zomato": .44, "Blinkit": .52, "Zepto": .61,
            "Amazon": .41, "Flipkart": .49, "Meesho": .58}
    tt = {
        "Delivery": ["Order arrived over an hour late and stone cold.", "Driver never showed but it was marked delivered.", "Delivery keeps getting delayed every time."],
        "Refunds & payments": ["Refund stuck for days with no response.", "Got charged twice for one order.", "Payment failed but money was still deducted."],
        "Returns & replacement": ["Wrong size sent and the return pickup never came.", "Tried to return, the request keeps failing.", "Replacement still not processed after a week."],
        "Counterfeit / damaged": ["Product is clearly fake, nothing like the listing.", "Item arrived cracked and damaged.", "Looks nothing like the photos, feels counterfeit."],
        "App & tech": ["App crashes every time I reach checkout.", "Can't log in after the latest update.", "Cart randomly empties itself."],
        "Pricing": ["Prices jumped overnight for no reason.", "Surge pricing is out of control.", "Hidden charges appeared at checkout."],
        "Customer service": ["Support is useless, no reply for days.", "The bot just loops, can't reach a human.", "Got a rude reply from the agent."],
        "Product/food quality": ["Food was stale and barely edible.", "Half the items were missing.", "Quality has dropped a lot recently."],
        OTHERS: ["Honestly not sure what happened, just a bad experience.", "Something felt off about the whole order.", "Generally disappointed lately, hard to say why."],
    }
    themes = list(tt)
    pos = ["Fast and smooth, genuinely impressed.", "Great experience as always.",
           "Quick delivery, zero issues.", "Easy and reliable."]
    rows = []
    for brand in CLUSTER_OF:
        n = 60 + rng.randrange(30)
        for _ in range(n):
            wi = rng.randrange(len(weeks))
            drift = wi * 0.03 if brand in ("Zepto", "Meesho") else 0
            is_c = rng.random() < (bias[brand] + drift)
            if is_c:
                label = "negative" if rng.random() < 0.78 else "neutral"
                theme = rng.choice(themes)
                if wi == 5 and brand == "Zepto" and rng.random() < 0.6:
                    theme = "Refunds & payments"
                if wi == 5 and brand == "Meesho" and rng.random() < 0.6:
                    theme = "Counterfeit / damaged"
                text = rng.choice(tt[theme])
            else:
                label, theme, text = "positive", None, rng.choice(pos)
            rows.append({"brand": brand, "week": weeks[wi], "source": "google_play",
                         "sentiment_label": label, "is_complaint": 1 if is_c else 0,
                         "theme": theme, "clean_text": text})
    return pd.DataFrame(rows)


# ── Report Horizon: period bucketing ─────────────────────────────────────────
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _iso_week_monday(y: int, w: int) -> datetime.date:
    return datetime.date.fromisocalendar(y, w, 1)


def period_label(week: str, horizon: str) -> str:
    """Map an ISO week label to its Weekly / Monthly / Yearly bucket label."""
    import re
    m = re.match(r"(\d{4})-W(\d{2})", str(week))
    if horizon == "Yearly":
        return m.group(1) if m else "All time"
    if horizon == "Monthly":
        if m:
            try:
                d = _iso_week_monday(int(m.group(1)), int(m.group(2)))
                return f"{_MONTHS[d.month - 1]} '{str(d.year)[2:]}"
            except ValueError:
                # Malformed/invalid ISO week (e.g. W53 in a 52-week year):
                # degrade to the year so render never crashes.
                return m.group(1)
        return str(week)
    return str(week)  # Weekly


def ordered_periods(weeks, horizon: str):
    """Return period labels in chronological order (de-duplicated)."""
    seen, out = set(), []
    for w in sorted(weeks):
        lbl = period_label(w, horizon)
        if lbl not in seen:
            seen.add(lbl)
            out.append(lbl)
    return out


# ── statistics ───────────────────────────────────────────────────────────────
def net_sentiment(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    pos = (frame["sentiment_label"] == "positive").sum()
    neg = (frame["sentiment_label"] == "negative").sum()
    return (pos - neg) / len(frame)


def share_of_voice(view: pd.DataFrame, universe: pd.DataFrame) -> int:
    """Selected platforms' share of all complaint volume in the timeframe (%)."""
    total = int((universe["is_complaint"] == 1).sum())
    mine = int((view["is_complaint"] == 1).sum())
    return round(mine / total * 100) if total else 0


def sov_within_cluster(df_timeframe: pd.DataFrame, brand: str) -> int:
    cluster = CLUSTER_OF.get(brand, "")
    peers = CLUSTERS.get(cluster, [brand])
    comp = df_timeframe[df_timeframe["is_complaint"] == 1]
    cluster_comp = int(comp["brand"].isin(peers).sum())
    mine = int((comp["brand"] == brand).sum())
    return round(mine / cluster_comp * 100) if cluster_comp else 0


def mad_anomalies(df_timeframe: pd.DataFrame, platforms, periods):
    """Median Absolute Deviation anomaly detection (modified z-score).

    Robust to organic spikes; needs >=4 periods of history (sparsity guard) and a
    last bucket of >=4 to avoid alarming on tiny absolute numbers.
    """
    out = []
    comp = df_timeframe[df_timeframe["is_complaint"] == 1]
    for b in platforms:
        sub_b = comp[comp["brand"] == b]
        for th in sub_b["theme"].dropna().unique():
            sub = sub_b[sub_b["theme"] == th]
            counts = [int((sub["period"] == p).sum()) for p in periods]
            if len(counts) < 4:
                continue
            med = statistics.median(counts)
            mad = statistics.median([abs(c - med) for c in counts])
            last = counts[-1]
            if mad > 0:
                mz = 0.6745 * (last - med) / mad
            else:
                mz = float("inf") if last > med else 0.0
            if last >= 4 and mz > 3.5:
                out.append({"brand": b, "theme": th, "period": periods[-1],
                            "count": int(last), "baseline": round(med, 1)})
    return out
