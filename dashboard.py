"""
SAVE MY CUSTOMERS
Modern customer-retention intelligence dashboard.

Preserves:
- Existing SQLite database
- Existing Jev and OpenAI results
- Existing financial state history
- Existing retention strategy engine
- Exactly three strategies generated on explicit request
- No automatic AI calls on dashboard load
- No email sending
"""

import html
import json
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.database import get_database_path
from app.retention_engine import generate_retention_strategies


# ============================================================
# PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="Save My Customers",
    page_icon="💜",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = Path(get_database_path())

NAV_ITEMS = [
    "Overview",
    "Attention Center",
    "Customers",
    "Activity",
]


# ============================================================
# HTML RENDERING FIX
# ============================================================

def safe(value):
    """Escape user/database text before inserting into HTML."""
    return html.escape(str(value), quote=True)


def render_html(markup):
    """
    Render custom HTML without Markdown interpreting
    indented lines as code blocks.
    """
    cleaned = "\n".join(
        line.strip()
        for line in markup.splitlines()
        if line.strip()
    )

    st.markdown(
        cleaned,
        unsafe_allow_html=True,
    )


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_connection():
    uri = DB_PATH.resolve().as_uri() + "?mode=ro"

    conn = sqlite3.connect(
        uri,
        uri=True,
    )

    conn.row_factory = sqlite3.Row

    return conn


def table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def parse_json(value, default=None):
    if not value:
        return default

    if isinstance(value, (dict, list)):
        return value

    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def number(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def load_dashboard_data():
    result = {
        "replays": [],
        "events": [],
        "customers": pd.DataFrame(
            columns=[
                "customer_id",
                "customer_name",
            ]
        ),
        "snapshots": {},
        "error": None,
    }

    if not DB_PATH.is_file():
        result["error"] = (
            f"Database not found: {DB_PATH}"
        )
        return result

    try:
        with get_connection() as conn:

            # ----------------------------------------
            # Customer events
            # ----------------------------------------

            if table_exists(conn, "customer_events"):
                rows = conn.execute(
                    """
                    SELECT
                        event_id,
                        customer_id,
                        sim_day,
                        event_type,
                        description
                    FROM customer_events
                    ORDER BY sim_day, event_id
                    """
                ).fetchall()

                result["events"] = [
                    dict(row)
                    for row in rows
                ]

            events_by_id = {
                event["event_id"]: event
                for event in result["events"]
            }

            # ----------------------------------------
            # Saved Jev / OpenAI results
            # ----------------------------------------

            if table_exists(conn, "live_ai_replays"):
                rows = conn.execute(
                    """
                    SELECT *
                    FROM live_ai_replays
                    ORDER BY started_at, event_id
                    """
                ).fetchall()

                for row in rows:
                    record = dict(row)

                    record["jev"] = (
                        parse_json(
                            record.get("jev_result_json"),
                            {},
                        )
                        or {}
                    )

                    record["openai"] = (
                        parse_json(
                            record.get("openai_result_json"),
                            {},
                        )
                        or {}
                    )

                    matching_event = events_by_id.get(
                        record.get("event_id"),
                        {},
                    )

                    record["sim_day"] = (
                        matching_event.get("sim_day")
                    )

                    result["replays"].append(record)

            # ----------------------------------------
            # Customer directory
            # ----------------------------------------

            if table_exists(conn, "customers"):
                columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(customers)"
                    ).fetchall()
                }

                id_column = next(
                    (
                        col
                        for col in [
                            "customer_id",
                            "id",
                        ]
                        if col in columns
                    ),
                    None,
                )

                name_column = next(
                    (
                        col
                        for col in [
                            "customer_name",
                            "display_name",
                            "name",
                        ]
                        if col in columns
                    ),
                    None,
                )

                if id_column and name_column:
                    query = (
                        f'SELECT "{id_column}" '
                        f'AS customer_id, '
                        f'"{name_column}" '
                        f'AS customer_name '
                        f'FROM customers '
                        f'ORDER BY "{name_column}"'
                    )

                    result["customers"] = (
                        pd.read_sql_query(
                            query,
                            conn,
                        )
                    )

            # ----------------------------------------
            # Latest saved customer states
            # ----------------------------------------

            if table_exists(
                conn,
                "customer_state_history",
            ):
                rows = conn.execute(
                    """
                    SELECT
                        customer_id,
                        state_after_json
                    FROM customer_state_history
                    ORDER BY sim_day, rowid
                    """
                ).fetchall()

                for row in rows:
                    result["snapshots"][
                        row["customer_id"]
                    ] = (
                        parse_json(
                            row["state_after_json"],
                            {},
                        )
                        or {}
                    )

    except (
        sqlite3.Error,
        ValueError,
        TypeError,
    ) as exc:
        result["error"] = str(exc)

    return result


# ============================================================
# DATA HELPERS
# ============================================================

def customer_name(customer_id, customers):
    if customers.empty:
        return (
            customer_id
            or "Unknown customer"
        )

    matches = customers[
        customers["customer_id"]
        == customer_id
    ]

    if matches.empty:
        return (
            customer_id
            or "Unknown customer"
        )

    return str(
        matches.iloc[0]["customer_name"]
    )


def get_customer_name(record, customers):
    jev = record.get("jev") or {}

    return (
        jev.get("customer_name")
        or customer_name(
            record.get("customer_id"),
            customers,
        )
    )


def get_notification(record):
    data = record.get("openai") or {}

    notification = (
        data.get("notification") or {}
    )

    if isinstance(notification, dict):
        return notification

    return {}


def go_to(page):
    st.session_state["pending_navigation"] = page
    st.rerun(scope="app")


# ============================================================
# GLOBAL CSS
# ============================================================

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
    --ink: #172443;
    --muted: #7D8AA4;
    --primary: #5365E9;
    --line: #E7ECF6;
    --background: #F7F9FE;
}

html, body, .stApp {
    font-family: 'DM Sans', sans-serif;
}

.stApp {
    background: var(--background);
    color: var(--ink);
}

.block-container {
    max-width: 1500px;
    padding-top: 1.7rem;
    padding-bottom: 4rem;
}

h1, h2, h3 {
    font-family: 'Manrope', sans-serif !important;
    letter-spacing: -0.035em;
    color: #172443;
}

[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid #E8EDF6;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 10px 12px;
    border-radius: 13px;
    margin-bottom: 5px;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: #F0F2FF;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
    background: #E9EDFF;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p {
    color: #4356D6;
    font-weight: 800;
}

div[data-testid="stMetric"] {
    background: white;
    border: 1px solid #E7ECF6;
    border-radius: 19px;
    padding: 19px 22px;
    box-shadow: 0 7px 24px rgba(30,50,100,.035);
}

div[data-testid="stMetricLabel"] p {
    color: #8290AA;
    font-size: 13px;
    font-weight: 600;
}

div[data-testid="stMetricValue"] {
    font-family: 'Manrope', sans-serif;
    color: #182648;
    font-weight: 800;
}

div[data-testid="stVerticalBlockBorderWrapper"] > div {
    border-radius: 21px !important;
    border-color: #E5EAF5 !important;
    box-shadow: 0 8px 24px rgba(32,50,100,.035);
}

div.stButton > button {
    border-radius: 12px;
    font-weight: 700;
    border: 1px solid #DDE4F2;
}

div.stButton > button[kind="primary"] {
    background: #5365E9;
    color: white;
    border-color: #5365E9;
}

div.stButton > button[kind="primary"]:hover {
    background: #4255D8;
    color: white;
}

/* BRAND */

.smc-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 8px 0 24px;
}

.smc-brand-mark {
    width: 52px;
    height: 52px;
    flex-shrink: 0;
    border-radius: 17px;
    background: linear-gradient(145deg,#5064EB,#A17BF5);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 8px 19px rgba(83,101,233,.18);
    font-size: 28px;
    color: white;
}

.smc-brand-name {
    font-family: 'Manrope', sans-serif;
    font-weight: 800;
    font-size: 20px;
    letter-spacing: -.06em;
    line-height: 1.1;
    color: #19264A;
}

.smc-brand-sub {
    font-size: 10px;
    letter-spacing: .11em;
    font-weight: 800;
    color: #96A2B9;
    margin-top: 5px;
}

.smc-sidebar-card {
    background: linear-gradient(145deg,#EDF1FF,#F4EFFF);
    border: 1px solid #E3E7FC;
    padding: 18px;
    border-radius: 18px;
    margin: 20px 0;
}

.smc-sidebar-title {
    color: #4657C7;
    font-size: 13px;
    font-weight: 800;
}

.smc-sidebar-copy {
    color: #73809C;
    font-size: 12px;
    line-height: 1.7;
    margin-top: 8px;
}

/* HERO */

.smc-hero {
    background: linear-gradient(
        112deg,
        #EAEAFF 0%,
        #F3EFFF 53%,
        #E8F3FF 100%
    );
    border: 1px solid #E3E6FA;
    border-radius: 28px;
    padding: 40px 43px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    min-height: 265px;
    margin-bottom: 25px;
    overflow: hidden;
}

.smc-hero-copy {
    max-width: 670px;
}

.smc-hero-label {
    display: inline-block;
    padding: 8px 13px;
    background: rgba(255,255,255,.8);
    color: #4B5DDA;
    border-radius: 100px;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .1em;
}

.smc-hero-title {
    font-family: 'Manrope', sans-serif;
    font-size: clamp(33px,3.5vw,51px);
    line-height: 1.15;
    letter-spacing: -.055em;
    font-weight: 800;
    color: #182653;
    margin: 17px 0 13px;
}

.smc-hero-title span {
    color: #5062DE;
}

.smc-hero-description {
    font-size: 15px;
    color: #6D7996;
    line-height: 1.75;
    max-width: 480px;
}

.smc-hero-art {
    position: relative;
    width: 260px;
    height: 215px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
}

.smc-art-circle {
    position: absolute;
    width: 205px;
    height: 205px;
    background: rgba(201,214,255,.5);
    border-radius: 50%;
}

.smc-art-person {
    position: relative;
    font-size: 100px;
    z-index: 2;
    filter: drop-shadow(0 12px 12px rgba(45,63,125,.12));
}

.smc-art-badge {
    position: absolute;
    z-index: 3;
    padding: 9px 13px;
    border-radius: 100px;
    font-size: 12px;
    font-weight: 800;
    box-shadow: 0 6px 15px rgba(50,70,125,.09);
    white-space: nowrap;
}

.smc-art-risk {
    top: 8px;
    right: 0;
    background: #FFE4EB;
    color: #D64D6C;
    transform: rotate(-7deg);
}

.smc-art-save {
    bottom: 11px;
    right: 0;
    background: #E0F8EB;
    color: #258E66;
    transform: rotate(5deg);
}

/* SECTION HEADINGS */

.smc-section {
    margin: 24px 0 13px;
}

.smc-section-title {
    font-family: 'Manrope', sans-serif;
    font-size: 21px;
    font-weight: 800;
    letter-spacing: -.035em;
    color: #1B294D;
}

.smc-section-description {
    font-size: 13px;
    color: #8B97B0;
    margin-top: 5px;
}

.smc-page-eyebrow {
    color: #5365E9;
    font-size: 11px;
    letter-spacing: .12em;
    font-weight: 800;
    margin-bottom: 9px;
}

.smc-page-title {
    font-family: 'Manrope', sans-serif;
    font-size: clamp(29px,3vw,40px);
    font-weight: 800;
    letter-spacing: -.055em;
    color: #172443;
}

.smc-page-description {
    font-size: 14px;
    color: #7F8BA5;
    margin: 8px 0 24px;
}

/* BADGES */

.smc-badge {
    display: inline-block;
    padding: 7px 11px;
    border-radius: 100px;
    font-size: 11px;
    font-weight: 800;
    white-space: nowrap;
}

.smc-badge-risk {
    background: #FFF0F2;
    color: #D94F6C;
}

.smc-badge-good {
    background: #E7F8EF;
    color: #228D66;
}

.smc-badge-neutral {
    background: #EDF0FF;
    color: #5666D7;
}

/* ALERT CARDS */

.smc-alert-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}

.smc-alert-name {
    font-family: 'Manrope', sans-serif;
    font-size: 19px;
    font-weight: 800;
    color: #1A284C;
}

.smc-alert-title {
    color: #DA5570;
    font-size: 14px;
    font-weight: 800;
    margin-bottom: 10px;
}

.smc-alert-description {
    color: #5F6E8B;
    font-size: 14px;
    line-height: 1.75;
}

.smc-recommendation {
    background: #F3F5FF;
    border: 1px solid #E5E9FC;
    border-radius: 14px;
    padding: 15px 17px;
    margin: 16px 0;
}

.smc-recommendation-label {
    font-size: 11px;
    font-weight: 800;
    color: #5365D8;
    letter-spacing: .07em;
    margin-bottom: 7px;
}

.smc-recommendation-text {
    color: #53617F;
    font-size: 13px;
    line-height: 1.7;
}

/* EVENT CARDS */

.smc-event {
    background: white;
    border: 1px solid #E7ECF6;
    border-radius: 18px;
    padding: 18px 21px;
    margin: 11px 0;
    box-shadow: 0 7px 22px rgba(33,52,100,.035);
}

.smc-event-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}

.smc-event-name {
    color: #1B294E;
    font-size: 14px;
    font-weight: 800;
}

.smc-event-meta {
    color: #8B97B0;
    font-size: 12px;
    margin-top: 7px;
}

.smc-event-description {
    color: #5F6D89;
    font-size: 13px;
    line-height: 1.7;
    margin-top: 12px;
}

@media(max-width:900px) {
    .smc-hero {
        padding: 27px;
    }

    .smc-hero-art {
        width: 170px;
    }

    .smc-art-person {
        font-size: 72px;
    }
}

@media(max-width:650px) {
    .smc-hero-art {
        display: none;
    }

    .smc-hero {
        padding: 25px;
    }
}
</style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# REUSABLE UI
# ============================================================

def section_heading(title, description=""):
    render_html(
        f"""
        <div class="smc-section">
            <div class="smc-section-title">
                {safe(title)}
            </div>
            <div class="smc-section-description">
                {safe(description)}
            </div>
        </div>
        """
    )


def page_heading(eyebrow, title, description):
    render_html(
        f"""
        <div class="smc-page-eyebrow">
            {safe(eyebrow.upper())}
        </div>
        <div class="smc-page-title">
            {safe(title)}
        </div>
        <div class="smc-page-description">
            {safe(description)}
        </div>
        """
    )


def status_badge(status):
    if status == "attention_needed":
        return (
            '<span class="smc-badge smc-badge-risk">'
            '● Needs attention'
            '</span>'
        )

    if status == "filtered":
        return (
            '<span class="smc-badge smc-badge-good">'
            '✓ Filtered'
            '</span>'
        )

    label = str(status).replace("_", " ").title()

    return (
        '<span class="smc-badge smc-badge-neutral">'
        f'{safe(label)}'
        '</span>'
    )


def risk_card(record, customers, show_action=True):
    alert = get_notification(record)
    jev = record.get("jev") or {}

    name = get_customer_name(
        record,
        customers,
    )

    title = alert.get(
        "alert_title",
        "Customer relationship alert",
    )

    summary = alert.get(
        "owner_summary",
        "This customer requires attention.",
    )

    recommended = alert.get(
        "recommended_action",
        "Review recent customer activity.",
    )

    with st.container(border=True):
        render_html(
            f"""
            <div class="smc-alert-header">
                <div class="smc-alert-name">
                    {safe(name)}
                </div>
                {status_badge("attention_needed")}
            </div>
            <div class="smc-alert-title">
                {safe(title)}
            </div>
            <div class="smc-alert-description">
                {safe(summary)}
            </div>
            <div class="smc-recommendation">
                <div class="smc-recommendation-label">
                    ✦ RECOMMENDED NEXT STEP
                </div>
                <div class="smc-recommendation-text">
                    {safe(recommended)}
                </div>
            </div>
            """
        )

        st.caption(
            "Jev change score: "
            f'{number(jev.get("meaningful_change_score")):.2f}'
            " · Escalation score: "
            f'{number(jev.get("needs_system_two_score")):.2f}'
        )

        if show_action:
            if st.button(
                "Review customer →",
                key=f"review_{record['event_id']}",
                type="primary",
                use_container_width=True,
            ):
                go_to("Attention Center")


def event_card(
    name,
    event_id,
    sim_day,
    event_type,
    description,
    status,
):
    day = (
        sim_day
        if sim_day is not None
        else "—"
    )

    event_type_label = (
        str(event_type)
        .replace("_", " ")
        .title()
    )

    render_html(
        f"""
        <div class="smc-event">
            <div class="smc-event-header">
                <div class="smc-event-name">
                    {safe(name)}
                </div>
                {status_badge(status)}
            </div>
            <div class="smc-event-meta">
                Day {safe(day)}
                · {safe(event_type_label)}
                · {safe(event_id)}
            </div>
            <div class="smc-event-description">
                {safe(description)}
            </div>
        </div>
        """
    )


def event_chart(evaluated):
    if not evaluated:
        st.info(
            "No saved Jev evaluations yet."
        )
        return

    labels = [
        record["event_id"].replace(
            "eb-stream-",
            "Event ",
        )
        for record in evaluated
    ]

    scores = [
        number(
            record["jev"].get(
                "needs_system_two_score"
            )
        )
        for record in evaluated
    ]

    colors = [
        "#E87991"
        if record.get("status") == "attention_needed"
        else "#77CEAD"
        for record in evaluated
    ]

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=scores,
            marker_color=colors,
            text=[
                f"{score:.2f}"
                for score in scores
            ],
            textposition="outside",
            hovertemplate=(
                "%{x}<br>"
                "Escalation score: %{y:.2f}"
                "<extra></extra>"
            ),
        )
    )

    fig.add_hline(
        y=0.5,
        line_dash="dot",
        line_color="#B6C1D7",
    )

    fig.update_layout(
        height=330,
        margin=dict(
            l=10,
            r=10,
            t=30,
            b=20,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        font=dict(
            color="#7B88A3",
        ),
        xaxis=dict(
            showgrid=False,
            tickangle=-35,
        ),
        yaxis=dict(
            range=[0, 1.1],
            gridcolor="#EEF1F8",
        ),
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False,
        },
    )


# ============================================================
# RETENTION STRATEGIES
# ============================================================

def show_retention_strategies(record):
    event_id = record["event_id"]
    customer_id = record.get("customer_id")
    sim_day = record.get("sim_day")

    strategy_key = (
        f"retention_strategies_{event_id}"
    )

    st.subheader("✦ AI retention strategies")

    st.caption(
        "Generate three customer-specific "
        "recommendations using saved accounting context."
    )

    if sim_day is None:
        st.error(
            "Cannot generate strategies: "
            "matching event simulation day is missing."
        )
        return

    if not customer_id:
        st.error(
            "Cannot generate strategies: "
            "customer ID is missing."
        )
        return

    if st.button(
    "Generate 3 retention strategies",
    key=f"generate_strategies_{event_id}",
    type="primary",
    use_container_width=True,
    disabled=strategy_key in st.session_state,
):
        try:
            with st.spinner(
                "Analyzing customer history..."
            ):
                result = generate_retention_strategies(
                    customer_id=customer_id,
                    as_of_sim_day=int(sim_day),
                )

            if not isinstance(result, dict):
                raise ValueError(
                    "Retention engine returned "
                    "an invalid response."
                )

            strategies = result.get(
                "strategies"
            )

            if (
                not isinstance(strategies, list)
                or len(strategies) != 3
            ):
                count = (
                    len(strategies)
                    if isinstance(strategies, list)
                    else 0
                )

                raise ValueError(
                    "Expected exactly 3 strategies, "
                    f"received {count}."
                )

            for strategy in strategies:
                if not isinstance(strategy, dict):
                    raise ValueError(
                        "Invalid strategy structure."
                    )

                required_fields = [
                    "title",
                    "action",
                    "why_it_fits",
                    "owner_check",
                ]

                missing = [
                    field
                    for field in required_fields
                    if not strategy.get(field)
                ]

                if missing:
                    raise ValueError(
                        "Missing strategy fields: "
                        + ", ".join(missing)
                    )

            st.session_state[
                strategy_key
            ] = result

        except Exception as exc:
            st.session_state.pop(
                strategy_key,
                None,
            )

            st.error(
                f"Could not generate strategies: {exc}"
            )

    saved_result = st.session_state.get(
        strategy_key
    )

    if not saved_result:
        return

    st.success(
        "3 retention strategies generated."
    )

    st.caption(
        "These are recommendations, not approved offers. "
        "Financial feasibility requires verified inputs."
    )

    for index, strategy in enumerate(
        saved_result["strategies"],
        start=1,
    ):
        with st.container(border=True):
            st.markdown(
                f"### {index:02d} · "
                f"{strategy['title']}"
            )

            st.write(
                strategy["action"]
            )

            st.markdown(
                "**Why this fits**"
            )

            st.write(
                strategy["why_it_fits"]
            )

            st.markdown(
                "**Owner should verify**"
            )

            st.write(
                strategy["owner_check"]
            )

            evaluation = (
                strategy.get(
                    "financial_evaluation"
                )
                or {}
            )

            status = evaluation.get(
                "status",
                "UNVERIFIED",
            )

            if status == "FINANCIALLY_FEASIBLE":
                st.success(
                    "Financial status: "
                    "FINANCIALLY FEASIBLE"
                )

            elif status == "REJECTED":
                st.error(
                    "Financial status: REJECTED"
                )

            else:
                st.warning(
                    "Financial status: UNVERIFIED"
                )

            st.caption(
                "Owner review required "
                "before taking action."
            )


# ============================================================
# SIDEBAR
# ============================================================

if "pending_navigation" in st.session_state:
    st.session_state["navigation"] = (
        st.session_state.pop(
            "pending_navigation"
        )
    )

if "navigation" not in st.session_state:
    st.session_state["navigation"] = "Overview"

with st.sidebar:
    render_html(
        """
        <div class="smc-brand">
            <div class="smc-brand-mark">
                ♡
            </div>
            <div>
                <div class="smc-brand-name">
                    save my<br>customers.
                </div>
                <div class="smc-brand-sub">
                    CUSTOMER INTELLIGENCE
                </div>
            </div>
        </div>
        """
    )

    selected = st.radio(
        "Navigation",
        NAV_ITEMS,
        key="navigation",
        label_visibility="collapsed",
    )

    render_html(
        """
        <div class="smc-sidebar-card">
            <div class="smc-sidebar-title">
                ✦ Proactive retention
            </div>
            <div class="smc-sidebar-copy">
                Turn accounting events into
                customer intelligence.
                Spot the signs before
                relationships are lost.
            </div>
        </div>
        """
    )

    st.caption(
        "Jev screens events. OpenAI explains "
        "important changes. You decide."
    )

    st.caption(
        "● Synthetic accounting data"
    )

    st.caption(
        "● Saved AI evaluations"
    )

    if st.button(
        "↻ Refresh now",
        use_container_width=True,
    ):
        st.rerun()


# ============================================================
# LIVE DASHBOARD CONTENT
# ============================================================

@st.fragment(run_every="1s")
def render_live_overview():
    data = load_dashboard_data()

    replays = data["replays"]
    events = data["events"]
    customers = data["customers"]

    attention = [
        record
        for record in replays
        if record.get("status") == "attention_needed"
    ]

    filtered = [
        record
        for record in replays
        if record.get("status") == "filtered"
    ]

    evaluated = [
        record
        for record in replays
        if record.get("jev")
    ]

    # Live counters
    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total customers", len(customers))
    c2.metric("Events evaluated", len(evaluated))
    c3.metric("Risk alerts generated", len(attention))
    c4.metric("Events filtered", len(filtered))

    section_heading(
        "Recent intelligence",
        "Latest evaluated customer events",
    )

    events_by_id = {
        event["event_id"]: event
        for event in events
    }

    for record in reversed(replays[-5:]):
        event = events_by_id.get(record["event_id"], {})

        event_card(
            name=get_customer_name(record, customers),
            event_id=record["event_id"],
            sim_day=record.get("sim_day"),
            event_type=event.get(
                "event_type",
                "customer_event",
            ),
            description=event.get(
                "description",
                "Customer event evaluated by Jev.",
            ),
            status=record.get("status", "unknown"),
        )
def render_dashboard():

    # Refresh database data inside the fragment.
    # This does not invoke Jev or OpenAI.

    data = load_dashboard_data()

    replays = data["replays"]
    events = data["events"]
    customers = data["customers"]
    snapshots = data["snapshots"]

    if data["error"]:
        st.warning(
            f"Database read issue: {data['error']}"
        )

    by_event = {
        record["event_id"]: record
        for record in replays
    }

    attention = [
        record
        for record in replays
        if record.get("status")
        == "attention_needed"
    ]

    filtered = [
        record
        for record in replays
        if record.get("status")
        == "filtered"
    ]

    evaluated = [
        record
        for record in replays
        if record.get("jev")
    ]

    # ========================================================
    # OVERVIEW
    # ========================================================

    if selected == "Overview":
        hero_path = Path(__file__).resolve().parent / "assets" / "hero_banner.png"

        if hero_path.exists():
            st.image(
                str(hero_path),
                use_container_width=True,
            )
        else:
            st.warning("Hero banner image not found.")
        render_live_overview()

        
        

        left, right = st.columns(
            [1.15, 1],
            gap="large",
        )

        with left:
            section_heading(
                "Your priority inbox",
                "Saved customer relationship alerts",
            )

            if attention:
                for record in reversed(attention):
                    risk_card(
                        record,
                        customers,
                    )
            else:
                st.success(
                    "No saved customer alerts."
                )

        with right:
            section_heading(
                "Intelligence at a glance",
                "Jev escalation scores",
            )

            with st.container(border=True):
                event_chart(evaluated)

                st.caption(
                    "Model scores are not "
                    "churn probabilities."
                )

        

       

    # ========================================================
    # ATTENTION CENTER
    # ========================================================

    elif selected == "Attention Center":

        page_heading(
            "YOUR PRIORITY INBOX",
            "Attention Center",
            "Understand customer warning signs, "
            "review evidence, and explore "
            "retention options.",
        )

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Historical alerts",
            len(attention),
        )

        c2.metric(
            "Events evaluated",
            len(evaluated),
        )

        c3.metric(
            "Events filtered",
            len(filtered),
        )

        if not attention:
            st.success(
                "No saved alerts."
            )

        for record in reversed(attention):

            alert = get_notification(
                record
            )

            jev = record.get("jev") or {}

            risk_card(
                record,
                customers,
                show_action=False,
            )

            with st.container(border=True):

                render_html(
                    """
                    <div class="smc-page-eyebrow">
                        ✦ INTELLIGENCE REPORT
                    </div>
                    """
                )

                st.subheader(
                    "Why this customer was flagged"
                )

                a, b, c = st.columns(3)

                a.metric(
                    "Jev change score",
                    (
                        f'{number(jev.get("meaningful_change_score")):.2f}'
                    ),
                )

                b.metric(
                    "Escalation score",
                    (
                        f'{number(jev.get("needs_system_two_score")):.2f}'
                    ),
                )

                c.metric(
                    "AI severity",
                    str(
                        alert.get(
                            "severity",
                            "Unknown",
                        )
                    ).title(),
                )

                st.markdown(
                    "**Supporting evidence**"
                )

                evidence = (
                    alert.get("evidence") or []
                )

                if (
                    isinstance(evidence, list)
                    and evidence
                ):
                    for item in evidence:
                        st.write(
                            f"• {item}"
                        )
                else:
                    st.info(
                        "No supporting evidence saved."
                    )

                st.caption(
                    "AI-generated explanations "
                    "should be verified against "
                    "accounting records."
                )

                st.divider()

                st.markdown(
                    "**Recommended action**"
                )

                st.write(
                    alert.get(
                        "recommended_action",
                        "No recommendation available.",
                    )
                )

            with st.container(border=True):
                show_retention_strategies(
                    record
                )

            st.write("")

    # ========================================================
    # CUSTOMERS
    # ========================================================

    elif selected == "Customers":

        page_heading(
            "CUSTOMER DIRECTORY",
            "Your customers",
            "Explore customer relationships "
            "and saved financial context.",
        )

        if customers.empty:
            st.info(
                "Customer directory unavailable."
            )

        else:
            st.metric(
                "Customers in database",
                len(customers),
            )

            search = st.text_input(
                "Search customers",
                placeholder=(
                    "Search by customer name..."
                ),
            )

            preview = customers

            if search:
                preview = customers[
                    customers["customer_name"]
                    .astype(str)
                    .str.contains(
                        search,
                        case=False,
                        na=False,
                        regex=False,
                    )
                ]

            section_heading(
                "Customer directory",
                (
                    f"{len(preview)} matching customers"
                ),
            )

            with st.container(border=True):
                st.dataframe(
                    preview,
                    use_container_width=True,
                    hide_index=True,
                )

            section_heading(
                "Customer details",
                "Select an account to review",
            )

            choices = {
                (
                    f"{row.customer_name} "
                    f"({row.customer_id})"
                ): row.customer_id
                for row in preview.itertuples(
                    index=False
                )
            }

            if choices:
                selected_customer = (
                    st.selectbox(
                        "Select customer",
                        list(choices),
                    )
                )

                customer_id = choices[
                    selected_customer
                ]

                state = (
                    snapshots.get(
                        customer_id
                    )
                    or {}
                )

                customer_replays = [
                    record
                    for record in replays
                    if record.get("customer_id")
                    == customer_id
                ]

                customer_alerts = sum(
                    record.get("status")
                    == "attention_needed"
                    for record in customer_replays
                )

                with st.container(border=True):

                    st.subheader(
                        customer_name(
                            customer_id,
                            customers,
                        )
                    )

                    if state:
                        a, b = st.columns(2)

                        a.metric(
                            "Outstanding AR",
                            (
                                f'${number(state.get("outstanding_ar")):,.2f}'
                            ),
                        )

                        b.metric(
                            "Overdue AR",
                            (
                                f'${number(state.get("overdue_ar")):,.2f}'
                            ),
                        )

                        st.caption(
                            "Balances from the latest "
                            "saved customer state."
                        )

                    else:
                        st.caption(
                            "No saved customer state."
                        )

                    a, b = st.columns(2)

                    a.metric(
                        "Saved Jev evaluations",
                        len(customer_replays),
                    )

                    b.metric(
                        "Historical alerts",
                        customer_alerts,
                    )

    # ========================================================
    # ACTIVITY
    # ========================================================

    elif selected == "Activity":

        page_heading(
            "INTELLIGENCE TIMELINE",
            "Activity history",
            "Follow customer events and "
            "saved AI decisions.",
        )

        a, b, c = st.columns(3)

        a.metric(
            "Total events",
            len(events),
        )

        b.metric(
            "Evaluated",
            len(evaluated),
        )

        c.metric(
            "Escalated",
            len(attention),
        )

        section_heading(
            "Event timeline",
            "Newest events first",
        )

        if not events:
            st.info(
                "No saved customer events."
            )

        for event in reversed(events):

            record = by_event.get(
                event["event_id"]
            )

            if record:
                name = get_customer_name(
                    record,
                    customers,
                )

                status = record.get(
                    "status",
                    "unknown",
                )

            else:
                name = customer_name(
                    event["customer_id"],
                    customers,
                )

                status = "Not evaluated"

            event_card(
                name=name,
                event_id=event["event_id"],
                sim_day=event["sim_day"],
                event_type=event["event_type"],
                description=event["description"],
                status=status,
            )

        section_heading(
            "How Save My Customers works",
            "From accounting activity "
            "to informed decisions",
        )

        steps = [
            (
                "01",
                "Observe",
                "Read customer events and "
                "reconstruct financial context.",
            ),
            (
                "02",
                "Filter with Jev",
                "Screen events using System One.",
            ),
            (
                "03",
                "Explain with OpenAI",
                "Investigate events that "
                "require deeper attention.",
            ),
            (
                "04",
                "Recommend",
                "Generate three customer-specific "
                "retention strategies.",
            ),
            (
                "05",
                "Owner decides",
                "Review recommendations "
                "before taking action.",
            ),
        ]

        for step_number, title, description in steps:
            render_html(
                f"""
                <div class="smc-event">
                    <div class="smc-page-eyebrow">
                        STEP {safe(step_number)}
                    </div>
                    <div class="smc-event-name">
                        {safe(title)}
                    </div>
                    <div class="smc-event-description">
                        {safe(description)}
                    </div>
                </div>
                """
            )

        st.caption(
            "Dashboard navigation reads "
            "saved SQLite results. "
            "No emails or offers are "
            "sent automatically."
        )


# ============================================================
# START DASHBOARD
# ============================================================

render_dashboard()