"""Tests for the Streamlit dashboard's pure logic (dashboard/voc_logic.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import statistics
from dashboard import voc_logic as V

checks = 0


def ok(cond, msg):
    global checks
    assert cond, msg
    checks += 1


# sample data: deterministic, store-reviews-only, 7 platforms
df = V.generate_sample_df()
ok(len(df) > 200, "sample has rows")
ok(df["brand"].nunique() == 7, "seven platforms")
ok(set(df["source"].unique()) == {"google_play"}, "store reviews only (no reddit)")

# normalize drops reddit and maps unclassified complaints to OTHERS
import pandas as pd
raw = pd.DataFrame([
    {"brand": "Swiggy", "week": "2026-W20", "source": "reddit",
     "sentiment_label": "negative", "is_complaint": 1, "themes": "Delivery", "clean_text": "x"},
    {"brand": "Amazon", "week": "2026-W20", "source": "google_play",
     "sentiment_label": "negative", "is_complaint": 1, "themes": "", "clean_text": "y"},
])
n = V.normalize(raw)
ok((n["source"] == "reddit").sum() == 0, "reddit dropped on normalize")
ok((n["theme"] == V.OTHERS).any(), "untagged complaint -> Others / Unclassified")

# period bucketing
wk = [f"2026-W{w:02d}" for w in range(20, 26)]
ok(len(V.ordered_periods(wk, "Weekly")) == 6, "weekly buckets")
ok(len(V.ordered_periods(wk, "Yearly")) == 1, "yearly bucket")
ok(all("'" in p for p in V.ordered_periods(wk, "Monthly")), "monthly labels formatted")

# net sentiment guards empty
ok(V.net_sentiment(df.iloc[0:0]) == 0.0, "net of empty is 0")

# share of voice is a 0..100 share
sov = V.share_of_voice(df[df.brand == "Zepto"], df)
ok(0 <= sov <= 100, "SoV in range")

# MAD flags a real spike but not an organic bump
def mz(counts):
    med = statistics.median(counts)
    mad = statistics.median([abs(c - med) for c in counts])
    last = counts[-1]
    return (0.6745 * (last - med) / mad) if mad > 0 else (float("inf") if last > med else 0)

ok(mz([2, 1, 2, 3, 2, 1, 12]) > 3.5, "MAD flags real spike")
ok(not (mz([5, 6, 5, 7, 6, 5, 8]) > 3.5), "MAD ignores organic bump")

# mad_anomalies returns structured dicts, sparsity-safe on tiny input
df2 = V.normalize(df)
df2["period"] = df2["week"].map(lambda w: V.period_label(w, "Weekly"))
an = V.mad_anomalies(df2, list(V.CLUSTER_OF), V.ordered_periods(df2["week"].unique(), "Weekly"))
ok(isinstance(an, list), "anomalies is a list")
ok(V.mad_anomalies(df2.iloc[0:0], ["Swiggy"], ["2026-W20"]) == [], "empty frame -> no anomalies, no crash")


# invalid ISO week (e.g. W53 in a 52-week year) must NOT crash bucketing
ok(V.period_label("2021-W53", "Monthly") == "2021", "invalid week degrades to year (monthly)")
ok(V.period_label("2021-W53", "Yearly") == "2021", "invalid week degrades to year (yearly)")
ok(V.ordered_periods(["2026-W24", "2021-W53"], "Monthly"), "ordered_periods survives a bad week")

print(f"test_dashboard_logic: {checks} checks passed")
