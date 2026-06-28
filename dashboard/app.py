"""
Streamlit dashboard for the Brand Health Tracker.

WHAT THIS DOES (and why it now matches the HTML exactly)
--------------------------------------------------------
Earlier this file *re-built* the dashboard out of native Streamlit widgets
(st.metric, st.altair_chart, st.dataframe, ...). Those widgets carry their own
built-in styling, so the result could never be pixel-identical to the bespoke
"Organic Modernism" design in dashboard/index.html — hence the persistent
"it looks different in Streamlit" problem.

This version instead *embeds the real dashboard/index.html* inside Streamlit via
streamlit.components.v1.html(). Because it is the exact same HTML/CSS/JS file,
what you see in Streamlit is identical to opening the HTML file directly.

LIVE DATA
---------
index.html normally fetches dashboard/web_data.json (written by
scripts/export_dashboard.py) and falls back to its built-in deterministic sample
when that file is absent. Inside an embedded iframe that relative fetch can't
resolve, so we build the same payload here (reusing export_dashboard.build_payload
— one source of truth) and inject it directly into the page. If the SQLite DB has
no scored rows yet, the page uses its own sample data, exactly as the static file
does. A small badge in the header marks live vs sample so the demo stays honest.

Run locally:
    streamlit run dashboard/app.py
"""
import os
import sys
import json

import streamlit as st
import streamlit.components.v1 as components

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

HTML_PATH = os.path.join(PROJECT_ROOT, "dashboard", "index.html")


# ── data ─────────────────────────────────────────────────────────────────────
def load_payload():
    """Return (payload_or_None, is_live).

    Live when the DB has scored rows; we reuse export_dashboard.build_payload so
    the embedded view and the static web_data.json export stay byte-for-byte
    consistent. Any failure (missing DB, missing deps) falls back to sample.
    """
    try:
        from scripts.database import get_connection, init_db
        from scripts.export_dashboard import build_payload
        conn = get_connection()
        init_db(conn)
        payload = build_payload(conn)
        conn.close()
        if payload and payload.get("mentions") and payload.get("weeks"):
            return payload, True
    except Exception:
        pass
    return None, False


# ── HTML assembly (pure function — no Streamlit calls, so it's unit-testable) ──
def build_embedded_html(raw_html: str, payload, is_live: bool) -> str:
    """Inject live data + a live/sample badge into index.html without touching
    its rendering logic.

    Trick: we override fetch("web_data.json") to resolve with the injected
    payload, so the page's own boot() picks it up exactly as it would from the
    static file. When there's no live payload we inject nothing data-wise and the
    page's built-in sample is used — identical to opening the file directly.
    """
    if is_live and payload:
        # Embedding JSON inside a <script> block: escape every "<" as its unicode
        # form so nothing in review text (e.g. "</script>", "<script>", "<!--")
        # can break out of or confuse the script element. json.dumps already
        # escapes non-ASCII (ensure_ascii=True), so "<" is the only HTML-unsafe
        # character left to handle. The value is unchanged once JS parses it.
        safe_json = json.dumps(payload).replace("<", "\\u003c")
        data_js = "window.__BHT_DATA__ = %s;" % safe_json
    else:
        data_js = ""
    live_flag = "true" if is_live else "false"

    shim = (
        "<script>\n"
        "  window.__BHT_LIVE__ = " + live_flag + ";\n"
        "  " + data_js + "\n"
        "  /* Serve injected data to the page's own fetch(\"web_data.json\") call. */\n"
        "  (function(){\n"
        "    var _fetch = window.fetch ? window.fetch.bind(window) : null;\n"
        "    window.fetch = function(url, opts){\n"
        "      try{\n"
        "        if (typeof url === 'string' && url.indexOf('web_data.json') !== -1 && window.__BHT_DATA__){\n"
        "          var body = JSON.stringify(window.__BHT_DATA__);\n"
        "          return Promise.resolve(new Response(body, {status:200, headers:{'Content-Type':'application/json'}}));\n"
        "        }\n"
        "      }catch(e){}\n"
        "      return _fetch ? _fetch(url, opts) : Promise.reject(new Error('no fetch'));\n"
        "    };\n"
        "  })();\n"
        "  /* Add a small live/sample chip into the header, matching the design tokens. */\n"
        "  (function(){\n"
        "    function addBadge(){\n"
        "      var tr = document.querySelector('.topbar-right'); if(!tr) return;\n"
        "      var chip = document.createElement('span');\n"
        "      chip.textContent = window.__BHT_LIVE__ ? '\\u25CF Live data' : '\\u25CF Sample data';\n"
        "      chip.style.cssText = 'font-size:12px;font-weight:700;padding:5px 11px;border-radius:999px;margin-right:10px;display:inline-flex;align-items:center;' +\n"
        "        (window.__BHT_LIVE__\n"
        "          ? 'background:#E8F4EE;color:#1C4A3C;border:1px solid #BFE3CF'\n"
        "          : 'background:#FFF7E6;color:#8A5A00;border:1px solid #F4D58A');\n"
        "      tr.insertBefore(chip, tr.firstChild);\n"
        "    }\n"
        "    if (document.readyState !== 'loading') addBadge();\n"
        "    else document.addEventListener('DOMContentLoaded', addBadge);\n"
        "  })();\n"
        "</script>\n"
    )

    # Insert the shim immediately after <head> so it runs before the page's boot().
    if "<head>" in raw_html:
        return raw_html.replace("<head>", "<head>\n" + shim, 1)
    return shim + raw_html


# ── Streamlit page ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Brand Health Tracker",
    layout="wide",
    page_icon="🌿",
    initial_sidebar_state="collapsed",  # the embedded dashboard has its own sidebar
)

# Strip Streamlit chrome/padding so the embedded dashboard sits flush, full-bleed.
st.markdown(
    """
    <style>
      header[data-testid="stHeader"]{display:none}
      .block-container{padding:0 !important;max-width:100% !important}
      [data-testid="stAppViewContainer"]{background:#F6F8F4}
      [data-testid="stSidebarCollapsedControl"]{display:none}
      footer{display:none}
    </style>
    """,
    unsafe_allow_html=True,
)


def render():
    if not os.path.exists(HTML_PATH):
        st.error(
            "dashboard/index.html was not found next to this app. "
            "It is the source of the design — keep it in the dashboard/ folder."
        )
        return

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        raw_html = f.read()

    payload, is_live = load_payload()
    html = build_embedded_html(raw_html, payload, is_live)

    # Tall fixed height + scrolling: the dashboard is a long, self-scrolling app.
    # (components.html can't auto-size a srcdoc iframe, so we give it generous room.)
    components.html(html, height=1500, scrolling=True)


render()
