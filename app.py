"""Streamlit UI for the Personal Finance Agent."""

from __future__ import annotations

import contextlib
import html
import os
import tempfile

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agent import (
    DB_PATH,
    SAMPLE_CSV,
    ask_finance_agent,
    ingest_csv,
    load_transactions_df,
    parse_pdf_to_dataframe,
)

load_dotenv()

st.set_page_config(page_title="Personal Finance Agent", layout="wide")

SAMPLE_QUESTIONS = [
    "How much did I spend on food last month?",
    "What's my biggest unnecessary expense?",
    "Break down my spending by category.",
    "Suggest a weekly budget plan based on my habits.",
]

PREVIEW_ROWS = 200

STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --paper:#FCFCFA; --panel:#F4F4EF; --bar:#EDF2E8; --rule:#DCE0D6;
  --ink:#1C221E; --dim:#5F6862; --faint:#949A92;
  --out:#9E3A2B; --in:#2E6B4A; --accent:#2E6B4A;
}

html, body, [class*="css"], .stApp { font-family:'IBM Plex Sans', system-ui, sans-serif; }
.stApp { background:var(--paper); color:var(--ink); }
#MainMenu, footer, header { visibility:hidden; }
.block-container { padding-top:2.6rem; max-width:900px; }
[data-testid="stSidebar"] { background:var(--panel); border-right:1px solid var(--rule); }
[data-testid="stSidebar"] * { color:var(--ink); }
[data-testid="stSidebar"] label { color:var(--dim) !important; font-size:13px !important; }
[data-testid="stSidebar"] hr { border-color:var(--rule); margin:16px 0; }

/* Masthead */
.mast h1 { font-size:31px; font-weight:600; letter-spacing:-0.015em; margin:0 0 7px; }
.mast p { color:var(--dim); font-size:15px; line-height:1.5; margin:0; max-width:60ch; }

/* Statement summary */
.sum { border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); padding:12px 0; margin:14px 0 4px; }
.sum .line { display:flex; justify-content:space-between; align-items:baseline; padding:3px 0; font-size:13px; }
.sum .line .k { color:var(--dim); }
.sum .line .v { font-family:'IBM Plex Mono', monospace; font-variant-numeric:tabular-nums; }
.sum .out { color:var(--out); }
.sum .in { color:var(--in); }
.sum .net { border-top:1px solid var(--rule); margin-top:6px; padding-top:8px; font-weight:500; }
.range { font-size:11.5px; color:var(--faint); font-family:'IBM Plex Mono', monospace; }

/* Category bars */
.cat { margin-top:4px; }
.cat .r { display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:2px; }
.cat .r .amt { font-family:'IBM Plex Mono', monospace; font-variant-numeric:tabular-nums; color:var(--dim); }
.cat .track { height:5px; background:var(--bar); margin-bottom:9px; }
.cat .fill { height:5px; background:var(--accent); }

/* Ledger */
.ledger { width:100%; border-collapse:collapse; font-size:13px; }
.ledger th { text-align:left; font-weight:500; font-size:11px; color:var(--faint);
  padding:0 10px 7px; border-bottom:1px solid var(--rule); }
.ledger th.r, .ledger td.r { text-align:right; }
.ledger td { padding:6px 10px; border-bottom:1px solid #EFF1EC; }
.ledger tr:nth-child(even) td { background:var(--bar); }
.ledger td.amt { font-family:'IBM Plex Mono', monospace; font-variant-numeric:tabular-nums; }
.ledger td.neg { color:var(--out); }
.ledger td.pos { color:var(--in); }
.ledger td.cat { color:var(--dim); font-size:12px; }

/* Chat */
[data-testid="stChatMessage"] { background:transparent !important; border:0 !important;
  padding:0 !important; margin-bottom:18px !important; }
[data-testid="stChatMessageAvatar"], [data-testid="chatAvatarIcon-user"],
[data-testid="chatAvatarIcon-assistant"] { display:none !important; }
.askline { font-size:17px; font-weight:500; padding-left:12px; border-left:2px solid var(--accent);
  margin:26px 0 16px; }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { line-height:1.65; }
[data-testid="stChatInput"] textarea { background:#FFFFFF !important; border:1px solid var(--rule) !important;
  color:var(--ink) !important; border-radius:2px !important; }
[data-testid="stChatInput"] textarea:focus { border-color:var(--accent) !important; box-shadow:none !important; }

/* Buttons */
.stButton button { background:transparent !important; border:1px solid var(--rule) !important;
  color:var(--dim) !important; border-radius:2px !important; font-size:13px !important;
  font-weight:400 !important; }
.stButton button:hover { border-color:var(--accent) !important; color:var(--ink) !important; }
.stButton button:focus-visible { outline:2px solid var(--accent) !important; outline-offset:2px !important; }
[data-testid="stSidebar"] input, [data-testid="stSidebar"] [data-baseweb="select"] > div {
  background:#FFFFFF !important; border-color:var(--rule) !important; border-radius:2px !important; }
.hint { color:var(--dim); font-size:14px; line-height:1.55; max-width:56ch; }
.note { color:var(--faint); font-size:12px; margin-top:6px; }
</style>
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def temp_upload(uploaded, suffix):
    """Write an upload to disk, and delete it once the import is done."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(uploaded.getvalue())
        tmp.close()
        yield tmp.name
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)


def money(value: float) -> str:
    return f"${abs(value):,.2f}"


def summary_block(summary: dict, df: pd.DataFrame) -> str:
    income = float(df.loc[df["is_income"] == 1, "amount"].sum()) if not df.empty else 0.0
    out = float(summary.get("total_spending", 0.0))
    net = income - out
    net_cls = "in" if net >= 0 else "out"
    sign = "" if net >= 0 else "\u2212"
    return f"""
    <div class="sum">
      <div class="line"><span class="k">Money out</span><span class="v out">{money(out)}</span></div>
      <div class="line"><span class="k">Money in</span><span class="v in">{money(income)}</span></div>
      <div class="line net"><span class="k">Net</span>
        <span class="v {net_cls}">{sign}{money(net)}</span></div>
    </div>
    <p class="range">{html.escape(str(summary.get('date_range', '')))}</p>
    """


def category_bars(breakdown: dict) -> str:
    if not breakdown:
        return ""
    top = max(breakdown.values())
    rows = []
    for cat, val in breakdown.items():
        pct = 100 * val / top if top else 0
        rows.append(
            f'<div class="r"><span>{html.escape(cat)}</span>'
            f'<span class="amt">{money(val)}</span></div>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%"></div></div>'
        )
    return '<div class="cat">' + "".join(rows) + "</div>"


def ledger_table(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.head(PREVIEW_ROWS).iterrows():
        amount = float(r["amount"])
        cls = "pos" if amount > 0 else "neg"
        sign = "" if amount > 0 else "\u2212"
        rows.append(
            f'<tr><td class="amt">{html.escape(str(r["date"]))}</td>'
            f'<td>{html.escape(str(r["description"]))}</td>'
            f'<td class="cat">{html.escape(str(r["category"]))}</td>'
            f'<td class="amt r {cls}">{sign}{money(amount)}</td></tr>'
        )
    return (
        '<table class="ledger"><thead><tr><th>Date</th><th>Description</th>'
        '<th>Category</th><th class="r">Amount</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def rebuild_history(messages: list) -> list[tuple[str, str]]:
    """Pair up prior user/assistant turns for the agent's context."""
    pairs, idx = [], 0
    while idx < len(messages) - 1:
        if messages[idx]["role"] == "user" and messages[idx + 1]["role"] == "assistant":
            pairs.append((messages[idx]["content"], messages[idx + 1]["content"]))
            idx += 2
        else:
            idx += 1
    return pairs


# ── Sidebar ────────────────────────────────────────────────────────────────────

def render_sidebar(df: pd.DataFrame) -> None:
    with st.sidebar:
        st.markdown("**Statement**")

        uploaded = st.file_uploader(
            "Bank export",
            type=["csv", "pdf"],
            help="CSV with date, description and amount - or separate debit and credit "
                 "columns. Text-based PDF statements work too; scans do not.",
        )

        if uploaded is not None and st.button("Import file", use_container_width=True):
            suffix = ".pdf" if uploaded.name.lower().endswith(".pdf") else ".csv"
            try:
                with temp_upload(uploaded, suffix) as path:
                    if suffix == ".pdf":
                        with st.spinner("Reading the statement..."):
                            parsed = parse_pdf_to_dataframe(path)
                        fd, csv_path = tempfile.mkstemp(suffix=".csv")
                        os.close(fd)
                        try:
                            parsed.to_csv(csv_path, index=False)
                            summary = ingest_csv(csv_path, replace=True)
                        finally:
                            with contextlib.suppress(OSError):
                                os.unlink(csv_path)
                    else:
                        summary = ingest_csv(path, replace=True)
                st.session_state.import_summary = summary
                st.rerun()
            except Exception as exc:
                st.error(f"Couldn't read that file: {exc}")

        if st.button("Use the sample statement", use_container_width=True):
            st.session_state.import_summary = ingest_csv(SAMPLE_CSV, replace=True)
            st.rerun()

        summary = st.session_state.get("import_summary")
        if summary:
            st.markdown(summary_block(summary, df), unsafe_allow_html=True)
            st.markdown("**Where it went**")
            st.markdown(category_bars(summary.get("category_breakdown", {})),
                        unsafe_allow_html=True)

        st.divider()

        if st.session_state.get("messages"):
            export = "\n\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in st.session_state.messages
            )
            st.download_button("Save this conversation", export,
                               file_name="finance_chat.txt", mime="text/plain",
                               use_container_width=True)

        if st.button("Clear everything", use_container_width=True):
            if DB_PATH.exists():
                DB_PATH.unlink()
            st.session_state.clear()
            st.rerun()


# ── Page ───────────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown(STYLE, unsafe_allow_html=True)
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending", None)

    df = load_transactions_df()
    render_sidebar(df)

    st.markdown("""
    <div class="mast">
      <h1>Ask your bank statement a question</h1>
      <p>Import a CSV or PDF export. Every row is categorized and stored locally,
      then answered against with real figures rather than estimates.</p>
    </div>
    """, unsafe_allow_html=True)

    if df.empty:
        st.markdown(
            '<p class="hint">Nothing imported yet. Load the sample statement from the '
            'left to look around, or bring your own export.</p>',
            unsafe_allow_html=True,
        )
        st.stop()

    with st.expander(f"Ledger - {len(df)} transactions"):
        st.markdown(ledger_table(df), unsafe_allow_html=True)
        if len(df) > PREVIEW_ROWS:
            st.markdown(f'<p class="note">Showing the first {PREVIEW_ROWS} rows. '
                        f'The agent queries all {len(df)}.</p>', unsafe_allow_html=True)

    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f'<div class="askline">{html.escape(msg["content"])}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(msg["content"])

    if not st.session_state.messages:
        st.markdown('<p class="hint" style="margin-top:22px">Somewhere to start:</p>',
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for i, q in enumerate(SAMPLE_QUESTIONS):
            if cols[i % 2].button(q, key=f"s{i}", use_container_width=True):
                st.session_state.pending = q

    prompt = st.session_state.pending or st.chat_input("Ask about your spending...")
    st.session_state.pending = None

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.markdown(f'<div class="askline">{html.escape(prompt)}</div>',
                    unsafe_allow_html=True)

        with st.spinner("Working through the numbers..."):
            history = rebuild_history(st.session_state.messages[:-1])
            try:
                answer = ask_finance_agent(prompt, chat_history=history)
            except ValueError as exc:
                answer = f"Configuration problem: {exc}"
            except Exception as exc:
                answer = (
                    f"That question didn't complete: {exc}\n\n"
                    "Check that `ORQ_API_KEY` is set and that your Orq.ai router has "
                    "`deepseek-v4-flash` available."
                )
        st.markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
