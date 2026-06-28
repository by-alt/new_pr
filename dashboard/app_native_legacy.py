"""
Streamlit dashboard for the Brand Health Tracker  —  "Organic Modernism" view.

Run locally:
    streamlit run dashboard/app.py

This is the interactive, decision-oriented view. It matches the static dashboard
(dashboard/index.html): Platform terminology, Share of Voice, MAD-based anomaly
alerts, multi-select platform overlay, a Weekly/Monthly/Yearly Report Horizon, an
"Others / Unclassified" theme, and store-reviews-only data (Reddit dropped).

Data source: reads data/brand_health.db when it has scored data; otherwise falls
back to clearly-labelled SAMPLE data so a fresh deploy still shows a full dashboard.
The sample data is never presented as real telemetry — a badge marks it.
"""
import os
import sys

import pandas as pd
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dashboard.voc_logic import (
    CLUSTERS, CLUSTER_OF, PLATFORM_COLORS, OTHERS,
    normalize, generate_sample_df, period_label, ordered_periods,
    net_sentiment, share_of_voice, sov_within_cluster, mad_anomalies,
)

st.set_page_config(page_title="Brand Health Tracker", layout="wide", page_icon="🌿")

# ── light "organic" polish on top of the theme in .streamlit/config.toml ──────
st.markdown(
    """
    <style>
      .block-container{padding-top:2.2rem;padding-left:2.4rem;padding-right:2.4rem;max-width:100%}
      div[data-testid="stMetric"]{background:#FFFFFF;border:1px solid #E3E9E0;border-radius:14px;
          padding:14px 18px;box-shadow:0 1px 3px rgba(16,36,28,.05)}
      div[data-testid="stMetricValue"]{font-weight:800;letter-spacing:-.02em}
      h1,h2,h3{letter-spacing:-.01em;color:#10241C}
      section[data-testid="stSidebar"]{background:#FFFFFF;border-right:1px solid #E3E9E0}
      .stButton>button{background:#13332A;color:#fff;border:0;border-radius:10px;font-weight:600}
      .stButton>button:hover{background:#1C4A3C;color:#fff}
      .demo-badge{display:inline-block;background:#FFF7E6;color:#8a5a00;border:1px solid #F4D58A;
          padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700}
      .live-badge{display:inline-block;background:#E8F4EE;color:#1C4A3C;border:1px solid #BFE3CF;
          padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700}
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Header ────────────────────────────────────────────────────────────────────
_t, _b = st.columns([5, 1])
with _t:
    st.title("🌿 Brand Health Tracker")
    st.caption("Voice-of-customer intelligence across consumer platforms — why sentiment moves, and the evidence behind it.")
with _b:
    st.write("")
    if st.button("🔄 Refresh", width='stretch',
                 help="Re-read the latest data. To collect NEW reviews, run scripts/run_all.py first."):
        st.rerun()

# ── Load data: real DB if populated, else labelled sample ─────────────────────
def load_data():
    """Return (dataframe, is_live). Live when the DB has scored rows, else sample."""
    try:
        from scripts.database import get_connection, init_db, count_by_brand
        conn = get_connection()
        init_db(conn)
        if count_by_brand(conn, "scored_mentions"):
            df = pd.read_sql_query(
                "SELECT brand, week, source, sentiment_label, is_complaint, themes, clean_text "
                "FROM scored_mentions", conn)
            latest = conn.execute("SELECT MAX(fetched_at) FROM mentions").fetchone()[0]
            conn.close()
            return normalize(df), True, latest
        conn.close()
    except Exception:
        pass
    return normalize(generate_sample_df()), False, None

df, is_live, latest = load_data()

if is_live:
    st.markdown(f'<span class="live-badge">● Live data</span>', unsafe_allow_html=True)
    if latest:
        st.caption(f"Most recent data collected: {latest}")
else:
    st.markdown('<span class="demo-badge">● Sample data — run scripts/run_all.py to load real reviews</span>',
                unsafe_allow_html=True)

# Only the known 7 platforms, in cluster order.
all_platforms = [b for b in CLUSTER_OF if b in set(df["brand"].unique())]

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.header("Filters")
st.sidebar.caption("Platforms are grouped into two competitive clusters.")
sel_platforms = st.sidebar.multiselect(
    "Platform focus", all_platforms, default=all_platforms,
    help="Select multiple to overlay them on the trend.")
if not sel_platforms:
    sel_platforms = all_platforms

themes_present = sorted({t for t in df["theme"].dropna().unique()})
if OTHERS not in themes_present:
    themes_present.append(OTHERS)
sel_theme = st.sidebar.selectbox("Complaint theme", ["All"] + themes_present)

horizon = st.sidebar.radio("Report horizon", ["Weekly", "Monthly", "Yearly"], horizontal=True)

# Derive period labels for the chosen horizon, then offer a range selector.
df = df.copy()
df["period"] = df["week"].map(lambda w: period_label(w, horizon))
periods = ordered_periods(df["week"].unique(), horizon)
if len(periods) >= 2:
    p_lo, p_hi = st.sidebar.select_slider("Timeframe", options=periods, value=(periods[0], periods[-1]))
    lo_i, hi_i = periods.index(p_lo), periods.index(p_hi)
    sel_periods = periods[lo_i:hi_i + 1]
else:
    sel_periods = periods

# Timeframe-scoped universe (all platforms) and the platform-filtered view.
df_tf = df[df["period"].isin(sel_periods)]
if sel_theme != "All":
    df_tf = df_tf[df_tf["theme"] == sel_theme]
view = df_tf[df_tf["brand"].isin(sel_platforms)]
st.sidebar.caption(f"{len(view):,} store reviews match these filters.")

# ── KPI cards ─────────────────────────────────────────────────────────────────
anoms = mad_anomalies(df_tf, sel_platforms, sel_periods)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Share of voice", f"{share_of_voice(view, df_tf)}%")
rate = (view["is_complaint"].mean() * 100) if len(view) else 0
k2.metric("Complaint rate", f"{rate:.0f}%")
if len(sel_platforms) == 1:
    k3.metric("Net sentiment", f"{net_sentiment(view):+.2f}")
else:
    k3.metric("Platforms active", f"{len(sel_platforms)}")
k4.metric("MAD alerts", f"{len(anoms)}")

# ── Why it's moving (period-over-period) ──────────────────────────────────────
st.header("Why it's moving")
st.caption("Period-over-period sentiment change and the complaint theme driving it.")
def _root_cause(brand):
    if len(sel_periods) < 2:
        return None
    last, prev = sel_periods[-1], sel_periods[-2]
    b = df_tf[df_tf["brand"] == brand]
    delta = round(net_sentiment(b[b["period"] == last]) - net_sentiment(b[b["period"] == prev]), 2)
    comp = b[b["is_complaint"] == 1]
    top, best = None, 0
    for th in comp["theme"].dropna().unique():
        d = int((comp[comp.period == last].theme == th).sum()) - int((comp[comp.period == prev].theme == th).sum())
        if d > best:
            best, top = d, th
    return {"brand": brand, "delta": delta, "period": last, "top": top, "inc": best}

causes = [c for c in (_root_cause(b) for b in sel_platforms) if c]
drops = sorted([c for c in causes if c["delta"] < 0], key=lambda c: c["delta"])[:3]
ups = [c for c in causes if c["delta"] >= 0][:2]
for c in drops:
    extra = f", led by a rise in '{c['top']}' complaints (+{c['inc']})." if c["top"] else "."
    st.error(f"📉 **{c['brand']}** net sentiment fell {abs(c['delta']):.2f} in {c['period']}{extra}")
for c in ups:
    st.success(f"📈 **{c['brand']}** held steady or rose in {c['period']}.")
if not drops and not ups:
    st.info(f"Not enough {horizon.lower()} history in this filter to attribute sentiment moves.")

# ── Share of Voice donuts (per cluster) ───────────────────────────────────────
st.header("Where the complaints concentrate")
st.caption("Each platform's share of complaints within its competitive cluster — normalized, so switching horizon never spikes the totals.")
try:
    import altair as alt
    cols = st.columns(2)
    for i, (cluster, brands) in enumerate(CLUSTERS.items()):
        comp = df_tf[(df_tf["is_complaint"] == 1) & (df_tf["brand"].isin(brands))]
        counts = comp.groupby("brand").size().reindex(brands, fill_value=0).reset_index(name="complaints")
        with cols[i]:
            st.subheader(cluster)
            if counts["complaints"].sum() == 0:
                st.info("No complaint data in this filter.")
                continue
            chart = alt.Chart(counts).mark_arc(innerRadius=55).encode(
                theta=alt.Theta("complaints:Q"),
                color=alt.Color("brand:N",
                                scale=alt.Scale(domain=brands, range=[PLATFORM_COLORS[b] for b in brands]),
                                legend=alt.Legend(title="Platform")),
                tooltip=["brand", "complaints"],
            ).properties(height=260)
            st.altair_chart(chart, width='stretch')
except Exception as e:
    st.caption(f"(donut unavailable: {e})")

# ── Competitive standing (within cluster, with SoV column) ────────────────────
st.header("Competitive standing")
st.caption("Ranked WITHIN each set — food/quick-commerce and e-commerce aren't comparable head-to-head.")
for cluster, brands in CLUSTERS.items():
    in_set = [b for b in brands if b in sel_platforms]
    if not in_set:
        continue
    rows = []
    for b in in_set:
        sub = view[view["brand"] == b]
        worst = (sub[sub.is_complaint == 1]["theme"].value_counts().idxmax()
                 if (sub["is_complaint"] == 1).any() else "—")
        rows.append({
            "Platform": b, "Reviews": len(sub),
            "SoV": f"{sov_within_cluster(df_tf, b)}%",
            "Net sentiment": round(net_sentiment(sub), 2),
            "Complaint rate": f"{(sub['is_complaint'].mean() * 100) if len(sub) else 0:.0f}%",
            "Worst theme": worst,
        })
    rows.sort(key=lambda r: r["Net sentiment"], reverse=True)
    st.subheader(cluster)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

# ── Sentiment trend (multi-platform overlay, MAD rings) ───────────────────────
st.header("Sentiment over time")
st.caption("Net sentiment per platform (−1 to +1). Select multiple platforms to overlay them. Red dots mark MAD-flagged spikes.")
series = (
    view.assign(pos=lambda d: (d.sentiment_label == "positive").astype(int),
                neg=lambda d: (d.sentiment_label == "negative").astype(int))
    .groupby(["period", "brand"])
    .apply(lambda g: (g.pos.sum() - g.neg.sum()) / len(g), include_groups=False)
    .reset_index(name="net"))
if not series.empty:
    try:
        import altair as alt
        order = {p: i for i, p in enumerate(sel_periods)}
        series = series[series["period"].isin(sel_periods)].copy()
        series["o"] = series["period"].map(order)
        dom = [b for b in all_platforms if b in sel_platforms]
        line = alt.Chart(series).mark_line(point=True, strokeWidth=3).encode(
            x=alt.X("period:N", sort=sel_periods, title=horizon),
            y=alt.Y("net:Q", title="Net sentiment", scale=alt.Scale(domain=[-1, 1])),
            color=alt.Color("brand:N", scale=alt.Scale(domain=dom, range=[PLATFORM_COLORS[b] for b in dom]),
                            title="Platform"),
            tooltip=["brand", "period", alt.Tooltip("net:Q", format="+.2f")],
        )
        layers = [line]
        adf = pd.DataFrame(anoms)
        if not adf.empty:
            marks = adf.merge(series, on=["brand", "period"], how="inner")
            if not marks.empty:
                layers.append(alt.Chart(marks).mark_point(size=130, color="#DC2626", filled=False, strokeWidth=3)
                              .encode(x=alt.X("period:N", sort=sel_periods), y="net:Q",
                                      tooltip=["brand", "theme", "period", "count"]))
        st.altair_chart(alt.layer(*layers).properties(height=340), width='stretch')
    except Exception:
        st.line_chart(series.pivot(index="period", columns="brand", values="net"))

# ── Complaint themes ──────────────────────────────────────────────────────────
st.header("Top sore points")
tview = view[view["is_complaint"] == 1].dropna(subset=["theme"])
if not tview.empty:
    pivot = tview.pivot_table(index="theme", columns="brand", values="is_complaint",
                              aggfunc="count", fill_value=0)
    st.bar_chart(pivot)
else:
    st.info("No themed complaints in the current filter.")

# ── Evidence ──────────────────────────────────────────────────────────────────
st.header("Read the actual complaints")
st.caption("The real text behind the charts — responds to your filters.")
ev = view[view["is_complaint"] == 1].sort_values("week", ascending=False).head(8)
if not ev.empty:
    for _, e in ev.iterrows():
        with st.expander(f"{e['brand']} · store review · {e['week']}  —  {e['theme'] or 'general'}"):
            st.write(e["clean_text"])
else:
    st.info("No matching complaints — widen the filters.")
