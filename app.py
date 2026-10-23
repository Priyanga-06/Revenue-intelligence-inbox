"""
app.py — Revenue Intelligence Inbox

A professional sales-operations dashboard for managing, routing, and
analyzing sales conversations.  Built with Streamlit, SQLite, and Plotly.

Run locally:
    streamlit run app.py
"""

import sys
import io
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from database import init_db, get_all_conversations, count_conversations, \
    update_routing_override, get_import_history, APP_VERSION
from imports import import_csv_data, generate_sample_data, save_sample_csv, \
    run_duplicate_update_demo, REQUIRED_FIELDS
from routing import route_conversation, route_to_dict, CATEGORIES
from analytics import calculate_metrics, filter_conversations, generate_findings, \
    get_rejected_decision
from exports import create_export_zip, EXPORT_DIR
from audit import log_action, get_audit_log

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Revenue Intelligence Inbox",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for a premium look
st.markdown("""
<style>
    .main-header {
        font-size: 1.75rem;
        font-weight: 700;
        color: #1a1a2e;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #e63946;
    }
    .metric-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        border-left: 4px solid #e63946;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a2e;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #6c757d;
        margin-top: 0.25rem;
    }
    .routing-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .stAlert {
        border-radius: 8px;
    }
    .dataframe td, .dataframe th {
        font-size: 0.85rem;
    }
    .sidebar .sidebar-content {
        background: #1a1a2e;
    }
    div[data-testid="stSidebar"] {
        background: #1a1a2e;
    }
    div[data-testid="stSidebar"] * {
        color: #e0e0e0;
    }
    .nav-active {
        background: rgba(230, 57, 70, 0.15);
        border-left: 3px solid #e63946;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

@st.cache_resource
def ensure_db():
    """Initialize the database and load sample data if empty."""
    init_db()
    if count_conversations() == 0:
        df = generate_sample_data()
        import_csv_data(df, "sample_data.csv")
    return True


def safe_init():
    """Always init the DB (not cached) — safe to call on every page."""
    init_db()


def get_conversations_cached():
    """Fetch all conversations (re-run each time for freshness)."""
    return get_all_conversations()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar():
    """Render the sidebar navigation."""
    st.sidebar.markdown("## Revenue Intelligence")
    st.sidebar.markdown(f"**v{APP_VERSION}**")
    st.sidebar.markdown("---")

    pages = [
        "📊 Executive Dashboard",
        "💬 Conversation Inbox",
        "📥 Import & Data Quality",
        "🔀 Routing Review",
        "📄 Reports & Exports",
        "📋 Audit Log",
    ]

    if "current_page" not in st.session_state:
        st.session_state["current_page"] = pages[0]

    selected = st.sidebar.radio("Navigation", pages, label_visibility="collapsed")

    st.session_state["current_page"] = selected

    st.sidebar.markdown("---")
    total = count_conversations()
    st.sidebar.metric("Total Records", total)
    st.sidebar.markdown("---")

    if st.sidebar.button("🔄 Reload Sample Data", use_container_width=True):
        from database import reset_database
        reset_database()
        df = generate_sample_data()
        import_csv_data(df, "sample_data.csv")
        log_action("reload_sample_data")
        st.sidebar.success("Sample data reloaded.")
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "⚠️ Data is **synthetic** for demonstration.\n"
        "Import your own CSV for real analysis."
    )

    return selected


# ---------------------------------------------------------------------------
# Filter widget (shared)
# ---------------------------------------------------------------------------

def render_filters(conversations):
    """Render filter controls and return the filter dict."""
    with st.expander("🔎 Filters", expanded=False):
        col1, col2, col3, col4, col5 = st.columns(5)

        owners = ["All"] + sorted(set(c.get("owner", "") for c in conversations))
        priorities = ["All", "high", "medium", "low"]
        sentiments = ["All", "positive", "neutral", "negative"]
        routing_cats = ["All"] + sorted(set(
            c.get("routing_category", "") for c in conversations if c.get("routing_category")
        ))

        with col1:
            date_from = st.date_input("From", value=None, key="filter_date_from")
        with col2:
            date_to = st.date_input("To", value=None, key="filter_date_to")
        with col3:
            owner = st.selectbox("Owner", owners, key="filter_owner")
        with col4:
            priority = st.selectbox("Priority", priorities, key="filter_priority")
        with col5:
            sentiment = st.selectbox("Sentiment", sentiments, key="filter_sentiment")

        col6, col7 = st.columns(2)
        with col6:
            routing_cat = st.selectbox(
                "Routing Category", routing_cats, key="filter_routing"
            )
        with col7:
            st.write("")  # spacer

        filters = {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
            "owner": owner,
            "priority": priority,
            "sentiment": sentiment,
            "routing_category": routing_cat,
        }
        return filters


# ---------------------------------------------------------------------------
# Page: Executive Dashboard
# ---------------------------------------------------------------------------

def page_dashboard(conversations):
    st.markdown('<p class="main-header">Executive Dashboard</p>', unsafe_allow_html=True)
    st.markdown("Overview of all sales conversations with live, filterable metrics.")

    if not conversations:
        st.warning("No conversations loaded. Use Import & Data Quality to add data.")
        return

    filters = render_filters(conversations)
    filtered = filter_conversations(conversations, filters)
    metrics = calculate_metrics(filtered)

    st.markdown(f"**Showing {len(filtered)} of {len(conversations)} conversations**")

    # ---- KPI cards ---------------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Conversations", metrics["total_conversations"])
    with col2:
        calls_meetings = f"{metrics['calls']} calls · {metrics['meetings']} meetings"
        st.metric("Calls vs Meetings", calls_meetings)
    with col3:
        st.metric("High Priority", metrics["high_priority"])
    with col4:
        st.metric("Needs Attention", metrics["needs_attention"])

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("Open Follow-ups", metrics["open_followups"])
    with col6:
        st.metric("Pipeline Value", f"${metrics['pipeline_value']:,.0f}")
    with col7:
        positive = metrics["sentiment_distribution"].get("positive", 0)
        st.metric("Positive Sentiment", positive)
    with col8:
        negative = metrics["sentiment_distribution"].get("negative", 0)
        st.metric("Negative Sentiment", negative)

    st.markdown("---")

    # ---- Charts row 1: Sentiment + Routing --------------------------------
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("Sentiment Distribution")
        sent_data = metrics["sentiment_distribution"]
        if sent_data:
            fig = px.pie(
                values=list(sent_data.values()),
                names=list(sent_data.keys()),
                color_discrete_map={
                    "positive": "#2ecc71",
                    "neutral": "#f39c12",
                    "negative": "#e74c3c",
                },
            )
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sentiment data available.")

    with chart_col2:
        st.subheader("Routing Category Distribution")
        routing_data = metrics["routing_category_distribution"]
        if routing_data:
            fig = px.bar(
                x=list(routing_data.values()),
                y=list(routing_data.keys()),
                orientation="h",
                color=list(routing_data.values()),
                color_continuous_scale="Reds",
            )
            fig.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                yaxis_title="",
                xaxis_title="Count",
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No routing data available.")

    # ---- Charts row 2: Activity trend + Owner volume ----------------------
    chart_col3, chart_col4 = st.columns(2)

    with chart_col3:
        st.subheader("Activity Trend by Day")
        trend = metrics["activity_trend"]
        if trend:
            df_trend = pd.DataFrame(trend)
            df_trend["date"] = pd.to_datetime(df_trend["date"])
            fig = px.line(
                df_trend, x="date", y="count",
                markers=True,
                color_discrete_sequence=["#e63946"],
            )
            fig.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                xaxis_title="Date",
                yaxis_title="Conversations",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No activity trend data available.")

    with chart_col4:
        st.subheader("Conversation Volume by Owner")
        owner_data = metrics["owner_distribution"]
        if owner_data:
            fig = px.bar(
                x=list(owner_data.keys()),
                y=list(owner_data.values()),
                color=list(owner_data.values()),
                color_continuous_scale="Blues",
            )
            fig.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                xaxis_title="Owner",
                yaxis_title="Conversations",
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No owner data available.")


# ---------------------------------------------------------------------------
# Page: Conversation Inbox
# ---------------------------------------------------------------------------

def page_inbox(conversations):
    st.markdown('<p class="main-header">Conversation Inbox</p>', unsafe_allow_html=True)
    st.markdown("Browse, search, and inspect individual conversation records.")

    if not conversations:
        st.warning("No conversations loaded.")
        return

    filters = render_filters(conversations)
    filtered = filter_conversations(conversations, filters)

    st.markdown(f"**{len(filtered)} conversations**")

    # Search box
    search = st.text_input("🔍 Search by account, contact, or transcript keyword:",
                           key="inbox_search")
    if search:
        s_lower = search.lower()
        filtered = [
            c for c in filtered
            if s_lower in (c.get("account_name") or "").lower()
            or s_lower in (c.get("contact_name") or "").lower()
            or s_lower in (c.get("transcript") or "").lower()
            or s_lower in (c.get("outcome") or "").lower()
        ]
        st.markdown(f"*{len(filtered)} results after search*")

    # Table view
    if filtered:
        display_cols = [
            "conversation_id", "account_name", "contact_name", "owner",
            "conversation_date", "conversation_type", "outcome",
            "deal_value", "sentiment", "buying_intent", "priority",
            "routing_category", "status",
        ]
        df_display = pd.DataFrame(filtered)
        existing_cols = [c for c in display_cols if c in df_display.columns]
        st.table(df_display[existing_cols].reset_index(drop=True))

        # Detail view
        st.markdown("---")
        st.subheader("Conversation Detail")
        conv_ids = [c["conversation_id"] for c in filtered]
        selected_id = st.selectbox("Select a conversation:", conv_ids,
                                   key="detail_select")
        selected_conv = next(c for c in filtered if c["conversation_id"] == selected_id)

        if selected_conv:
            _render_conversation_detail(selected_conv)
    else:
        st.info("No conversations match the current filters.")


def _render_conversation_detail(conv):
    """Render a detailed view of a single conversation."""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"**Account:** {conv.get('account_name') or ''}")
        st.markdown(f"**Contact:** {conv.get('contact_name') or ''}")
        st.markdown(f"**Owner:** {conv.get('owner') or ''}")
    with col2:
        st.markdown(f"**Date:** {conv.get('conversation_date') or ''}")
        st.markdown(f"**Type:** {(conv.get('conversation_type') or '').title()}")
        st.markdown(f"**Duration:** {conv.get('duration_minutes') or 0} min")
    with col3:
        st.markdown(f"**Deal Value:** ${float(conv.get('deal_value') or 0):,.0f}")
        st.markdown(f"**Sentiment:** {(conv.get('sentiment') or '').title()}")
        st.markdown(f"**Buying Intent:** {(conv.get('buying_intent') or '').title()}")

    st.markdown("---")

    # Transcript
    st.subheader("Transcript")
    st.text_area("", value=conv.get("transcript") or "", height=200,
                 key=f"transcript_{conv['conversation_id']}")

    # Routing information
    st.subheader("Routing Analysis")
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown(f"**Category:** {conv.get('routing_category') or 'N/A'}")
        st.markdown(f"**Priority:** {(conv.get('priority') or 'N/A').title()}")
        st.markdown(f"**Next Action:** {conv.get('next_action') or 'N/A'}")
        st.markdown(f"**Status:** {(conv.get('status') or 'N/A').title()}")
    with col_r2:
        st.markdown(f"**Reason:** {conv.get('routing_reason') or 'N/A'}")
        st.markdown(f"**Evidence:**")
        st.info(conv.get("evidence_excerpt") or "No evidence excerpt available.")

    # Show automated vs manual routing
    if conv.get("manual_override_applied"):
        st.warning(
            "⚠️ **Manual override applied.** "
            f"Original automated category: {conv.get('auto_routing_category') or 'N/A'}"
        )


# ---------------------------------------------------------------------------
# Page: Import & Data Quality
# ---------------------------------------------------------------------------

def page_import():
    st.markdown('<p class="main-header">Import & Data Quality</p>', unsafe_allow_html=True)
    st.markdown("Import CSV data with duplicate detection, validation, and update tracking.")

    # ---- File upload -------------------------------------------------------
    st.subheader("Upload CSV")
    uploaded = st.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        key="csv_upload",
    )

    if uploaded is not None:
        try:
            df = pd.read_csv(uploaded)
            df.columns = [c.strip().lower() for c in df.columns]
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
            return

        # Preview
        st.markdown("**Preview (first 10 rows):**")
        st.table(df.head(10).reset_index(drop=True))

        # Check required columns
        missing = [f for f in REQUIRED_FIELDS if f not in df.columns]
        if missing:
            st.error(f"❌ Missing required columns: {', '.join(missing)}")
            st.markdown(f"Required columns: {', '.join(REQUIRED_FIELDS)}")
        else:
            if st.button("✅ Import Data", type="primary", key="do_import"):
                with st.spinner("Importing..."):
                    result = import_csv_data(df, uploaded.name)
                _show_import_result(result)
                log_action("file_import", details={"file": uploaded.name, "result": result})
                st.rerun()

    st.markdown("---")

    # ---- Download sample CSV ----------------------------------------------
    st.subheader("Download Sample CSV")
    st.markdown("Get the synthetic dataset CSV for reference or as a template.")
    if st.button("📥 Generate & Download Sample CSV", key="dl_sample"):
        csv_path = save_sample_csv()
        with open(csv_path, "rb") as f:
            st.download_button(
                "⬇️ Download sample_data.csv",
                f,
                file_name="sample_data.csv",
                mime="text/csv",
            )
        st.success(f"Sample CSV saved to {csv_path}")

    st.markdown("---")

    # ---- Duplicate / Update Demo ------------------------------------------
    st.subheader("Duplicate / Update Demo")
    st.markdown("""
    This demo executes a genuine end-to-end test of the import logic:
    1. Import a single record → **inserted**
    2. Import the same record again → **unchanged**
    3. Import a modified version → **updated**
    4. Verify record count never increases
    """)
    if st.button("🏃 Run Duplicate/Update Demo", type="primary", key="run_demo"):
        with st.spinner("Running duplicate/update test..."):
            results = run_duplicate_update_demo()
        st.success("Demo complete!")

        for step, data in results.items():
            if step == "verification":
                st.markdown("### Verification")
                v = data
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Records after Step 1", v["count_after_step1"])
                with col2:
                    st.metric("Records after Step 2", v["count_after_step2"])
                with col3:
                    st.metric("Records after Step 3", v["count_after_step3"])
                with col4:
                    ok = "✅ Yes" if v["count_stayed_same"] else "❌ No"
                    st.metric("Count Stayed Same?", ok)

                checks = [
                    ("Step 1 inserted 1 record", v["step1_inserted"]),
                    ("Step 2 unchanged (no duplicate)", v["step2_unchanged"]),
                    ("Step 3 updated existing record", v["step3_updated"]),
                    ("Record count never increased", v["count_stayed_same"]),
                ]
                all_pass = True
                for label, passed in checks:
                    icon = "✅" if passed else "❌"
                    st.markdown(f"{icon} {label}")
                    if not passed:
                        all_pass = False

                if all_pass:
                    st.success("All duplicate/update checks passed!")
                else:
                    st.error("Some checks failed — see details above.")
            else:
                st.markdown(f"### {step.replace('_', ' ').title()}")
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric("Total", data["total"])
                with col2:
                    st.metric("Inserted", data["inserted"])
                with col3:
                    st.metric("Updated", data["updated"])
                with col4:
                    st.metric("Unchanged", data["unchanged"])
                with col5:
                    st.metric("Rejected", data["rejected"])
                st.markdown(f"**Final record count:** {data['final_count']}")

    st.markdown("---")

    # ---- Import history ----------------------------------------------------
    st.subheader("Import History")
    history = get_import_history()
    if history:
        hist_df = pd.DataFrame(history)
        hist_df = hist_df.drop(columns=["rejected_details"], errors="ignore")
        st.table(hist_df.reset_index(drop=True))
    else:
        st.info("No import history yet.")


def _show_import_result(result):
    """Display import results with clear metrics."""
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Rows", result["total"])
    with col2:
        st.metric("Inserted", result["inserted"])
    with col3:
        st.metric("Updated", result["updated"])
    with col4:
        st.metric("Unchanged", result["unchanged"])
    with col5:
        st.metric("Rejected", result["rejected"])

    st.markdown(f"**Final record count in database:** {result['final_count']}")

    if result["rejected_details"]:
        with st.expander(f"⚠️ {len(result['rejected_details'])} rejection(s)"):
            for detail in result["rejected_details"]:
                st.markdown(f"- {detail}")


# ---------------------------------------------------------------------------
# Page: Routing Review
# ---------------------------------------------------------------------------

def page_routing(conversations):
    st.markdown('<p class="main-header">Routing Review</p>', unsafe_allow_html=True)
    st.markdown("Review automated routing decisions and apply manual overrides.")

    if not conversations:
        st.warning("No conversations loaded.")
        return

    # ---- Needs review section ----------------------------------------------
    needs_review = [c for c in conversations if c.get("needs_review") == 1]
    if needs_review:
        st.warning(f"⚠️ {len(needs_review)} conversation(s) require human review.")
        with st.expander("View conversations needing review", expanded=True):
            for c in needs_review:
                st.markdown(f"**{c['conversation_id']}** — {c.get('account_name', '')}: "
                           f"{c.get('routing_category', '')}")

    # ---- Manual override ---------------------------------------------------
    st.markdown("---")
    st.subheader("Manual Override")
    conv_ids = [c["conversation_id"] for c in conversations]
    selected_id = st.selectbox("Select conversation to review:", conv_ids,
                               key="routing_select")
    conv = next(c for c in conversations if c["conversation_id"] == selected_id)

    if conv:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Automated Routing")
            st.markdown(f"**Category:** {conv.get('auto_routing_category', 'N/A')}")
            st.markdown(f"**Priority:** {(conv.get('auto_priority') or 'N/A').title()}")
            st.markdown(f"**Confidence:** {conv.get('auto_confidence') or 'N/A'}")
            st.markdown(f"**Reason:** {conv.get('auto_routing_reason') or 'N/A'}")
            st.markdown(f"**Evidence:**")
            st.info(conv.get("auto_evidence_excerpt") or "N/A")
            st.markdown(f"**Next Action:** {conv.get('auto_next_action') or 'N/A'}")

        with col2:
            st.markdown("#### Current Applied Routing")
            if conv.get("manual_override_applied"):
                st.success("✅ Manual override active")
            else:
                st.info("Using automated routing")
            st.markdown(f"**Category:** {conv.get('routing_category') or 'N/A'}")
            st.markdown(f"**Priority:** {(conv.get('priority') or 'N/A').title()}")
            st.markdown(f"**Reason:** {conv.get('routing_reason') or 'N/A'}")
            st.markdown(f"**Evidence:**")
            st.info(conv.get("evidence_excerpt") or "N/A")
            st.markdown(f"**Next Action:** {conv.get('next_action') or 'N/A'}")
            st.markdown(f"**Status:** {(conv.get('status') or 'N/A').title()}")

        # Override form
        st.markdown("---")
        st.markdown("#### Apply Manual Override")
        with st.form("override_form"):
            override_col1, override_col2 = st.columns(2)
            with override_col1:
                new_category = st.selectbox(
                    "Override Category",
                    list(CATEGORIES.values()),
                    index=list(CATEGORIES.values()).index(
                        conv.get("routing_category") or list(CATEGORIES.values())[0]
                    ) if conv.get("routing_category") in CATEGORIES.values() else 0,
                    key="override_cat",
                )
                _pri = (conv.get("priority") or "medium").lower()
                new_priority = st.selectbox(
                    "Override Priority",
                    ["high", "medium", "low"],
                    index=["high", "medium", "low"].index(_pri) if _pri in ["high", "medium", "low"] else 1,
                    key="override_pri",
                )
            with override_col2:
                new_reason = st.text_area(
                    "Override Reason",
                    value=conv.get("routing_reason", ""),
                    key="override_reason",
                )
                new_action = st.text_area(
                    "Override Next Action",
                    value=conv.get("next_action", ""),
                    key="override_action",
                )

            _st = (conv.get("status") or "open").lower()
            new_status = st.selectbox(
                "Status",
                ["open", "closed"],
                index=["open", "closed"].index(_st) if _st in ["open", "closed"] else 0,
                key="override_status",
            )

            col_btn1, col_btn2, col_btn3 = st.columns(3)
            with col_btn1:
                submitted = st.form_submit_button("✅ Approve / Apply Override", type="primary")
            with col_btn2:
                rejected = st.form_submit_button("❌ Reject Routing")
            with col_btn3:
                reset = st.form_submit_button("🔄 Reset to Automated")

            if submitted:
                update_routing_override(
                    selected_id, new_category, new_priority, new_reason,
                    new_action, new_status, user="manager",
                )
                log_action(
                    "routing_override",
                    entity_id=selected_id,
                    details={
                        "category": new_category,
                        "priority": new_priority,
                        "reason": new_reason,
                    },
                )
                st.success(f"Override applied to {selected_id}.")
                st.rerun()

            if rejected:
                update_routing_override(
                    selected_id, "Needs human review", "high",
                    f"Manager rejected automated routing: {conv.get('auto_routing_reason', '')}",
                    "Manager to manually review and reassign.", "open",
                    user="manager",
                )
                log_action(
                    "routing_rejected",
                    entity_id=selected_id,
                    details={"original_category": conv.get("auto_routing_category", "")},
                )
                st.warning(f"Routing rejected for {selected_id}. Flagged for manual review.")
                st.rerun()

            if reset:
                from database import get_connection
                conn = get_connection()
                conn.execute(
                    "UPDATE conversations SET "
                    "routing_category = auto_routing_category, "
                    "routing_reason = auto_routing_reason, "
                    "priority = auto_priority, "
                    "evidence_excerpt = auto_evidence_excerpt, "
                    "next_action = auto_next_action, "
                    "manual_override_applied = 0 "
                    "WHERE conversation_id = ?",
                    (selected_id,),
                )
                conn.commit()
                conn.close()
                log_action(
                    "routing_reset",
                    entity_id=selected_id,
                    details={"reset_to": conv.get("auto_routing_category", "")},
                )
                st.info(f"Reset {selected_id} to automated routing.")
                st.rerun()


# ---------------------------------------------------------------------------
# Page: Reports & Exports
# ---------------------------------------------------------------------------

def page_reports(conversations):
    st.markdown('<p class="main-header">Reports & Exports</p>', unsafe_allow_html=True)
    st.markdown("Generate downloadable exports with manifest and checksums.")

    if not conversations:
        st.warning("No conversations to export.")
        return

    filters = render_filters(conversations)
    filtered = filter_conversations(conversations, filters)
    st.markdown(f"**Exporting {len(filtered)} of {len(conversations)} conversations** "
                f"(based on current filters)")

    # Determine dataset type
    source_files = set(c.get("source_file", "") for c in filtered)
    dataset_type = (
        "synthetic"
        if source_files.issubset({"", "sample_data.csv", "generate_sample_data"})
        else "user-provided"
    )
    st.markdown(f"**Dataset type:** {dataset_type}")

    st.markdown("---")

    # ---- Export files ------------------------------------------------------
    st.subheader("Export Files")
    st.markdown("The following files will be generated and bundled into a ZIP:")
    st.markdown("""
    - **conversations.csv** — Full conversation data in CSV format
    - **conversations.json** — Full conversation data in JSON format
    - **routing_review.csv** — Routing decisions and override status
    - **findings.json** — Three evidence-linked findings
    - **manifest.json** — Metadata, checksums, and record counts
    """)

    if st.button("📦 Generate & Download ZIP", type="primary", key="gen_zip"):
        with st.spinner("Generating exports..."):
            zip_path = create_export_zip(filtered, filters, dataset_type)

        st.success(f"ZIP generated: {zip_path.name}")

        with open(zip_path, "rb") as f:
            st.download_button(
                "⬇️ Download ZIP",
                f,
                file_name=zip_path.name,
                mime="application/zip",
            )

        # Show manifest preview
        manifest_path = EXPORT_DIR / "manifest.json"
        if manifest_path.exists():
            import json
            with open(manifest_path) as mf:
                manifest = json.load(mf)
            st.markdown("---")
            st.subheader("Manifest Preview")
            st.json(manifest)

    st.markdown("---")

    # ---- Findings ----------------------------------------------------------
    st.subheader("Evidence-Linked Findings")
    st.markdown("Three findings generated from the currently filtered data.")

    findings = generate_findings(filtered)

    for i, finding in enumerate(findings, 1):
        st.markdown(f"### Finding {i}")
        st.markdown(f"**{finding['finding_statement']}**")

        with st.expander("Details", expanded=True):
            st.markdown(f"**Supporting Metric:** {finding['supporting_metric']}")
            st.markdown(f"**Data Source:** {finding['data_source']}")

            if finding["conversation_ids"]:
                st.markdown(f"**Conversation IDs:** {', '.join(finding['conversation_ids'])}")
                st.markdown("**Evidence Excerpts:**")
                for j, excerpt in enumerate(finding["evidence_excerpts"], 1):
                    st.markdown(f"> {excerpt}")
            else:
                st.info("No supporting conversations found for this finding.")

            st.markdown(f"**Business Impact:** {finding['business_impact']}")
            st.markdown(f"**Recommended Action:** {finding['recommended_action']}")

    # ---- Rejected decision -------------------------------------------------
    st.markdown("---")
    st.subheader("Rejected Decision Log")
    decision = get_rejected_decision()
    st.markdown(f"**Decision:** {decision['decision']}")
    st.markdown(f"**Considered Approach:** {decision['considered_approach']}")
    st.markdown(f"**Reason for Rejection:** {decision['reason_for_rejection']}")
    st.markdown(f"**Chosen Alternative:** {decision['chosen_alternative']}")
    st.markdown(f"**Trade-off:** {decision['trade_off']}")
    st.markdown(f"**Expected Benefit:** {decision['expected_benefit']}")


# ---------------------------------------------------------------------------
# Page: Audit Log
# ---------------------------------------------------------------------------

def page_audit():
    st.markdown('<p class="main-header">Audit Log</p>', unsafe_allow_html=True)
    st.markdown("Complete record of all system and user actions.")

    log = get_audit_log(limit=500)

    if not log:
        st.info("No audit entries yet.")
        return

    log_df = pd.DataFrame(log)

    # Parse details JSON for display
    log_df["details"] = log_df["details"].apply(
        lambda x: x if isinstance(x, str) else str(x)
    )

    # Use st.table instead of st.dataframe to avoid PyArrow/NumPy version conflict
    st.table(log_df)

    st.markdown("---")
    st.markdown(f"**Total entries shown:** {len(log)}")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main():
    init_db()  # always ensure tables exist
    ensure_db()
    conversations = get_conversations_cached()

    page = render_sidebar()

    if "Dashboard" in page:
        page_dashboard(conversations)
    elif "Inbox" in page:
        page_inbox(conversations)
    elif "Import" in page:
        page_import()
    elif "Routing" in page:
        page_routing(conversations)
    elif "Reports" in page:
        page_reports(conversations)
    elif "Audit" in page:
        page_audit()


if __name__ == "__main__":
    main()
