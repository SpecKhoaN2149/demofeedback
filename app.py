"""Streamlit UI for the NLP feedback processing pipeline with enhancements.

Run with:

    pip install streamlit
    streamlit run app.py

Features:
- Process feedback with Gemini-powered enrichment
- Persistence: batch results saved to SQLite, retrievable by ID
- Caching: repeated text skips Gemini calls (configurable TTL)
- Language detection: identifies input language, shows on insights
- Trend analysis: compare historical windows to spot spikes/shifts
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from nlp_processing.config import ConfigurationError
from nlp_processing.models import RawFeedback
from nlp_processing.models.enhancements import TimeWindow
from nlp_processing.models.types import SourceChannel
from nlp_processing.orchestrator import NLPProcessor
from nlp_processing.persistence_config import CacheConfig, PersistenceConfig

# The closed set of allowed source channels (Req 1.4).
CHANNELS = list(SourceChannel.__args__)  # type: ignore[attr-defined]

MODEL_OPTIONS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "Custom…",
]

st.set_page_config(page_title="NLP Feedback Processing", page_icon="🛰️", layout="wide")
st.title("🛰️ NLP Feedback Processing")
st.caption(
    "Process customer feedback with Gemini-powered enrichment, persistence, "
    "caching, language detection, and trend analysis."
)

# ──────────────────────────────────────────────────────────────────────────────
# Sidebar: Settings
# ──────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Settings")

    api_key = st.text_input(
        "Gemini API key",
        type="password",
        help="Held in memory only for this run; never logged.",
    )
    model_choice = st.selectbox("Model name", MODEL_OPTIONS, index=0)
    if model_choice == "Custom…":
        model_name = st.text_input("Custom model id", value="gemini-2.5-flash")
    else:
        model_name = model_choice

    similarity_threshold = st.slider(
        "Similarity threshold", min_value=0.0, max_value=1.0, value=0.75, step=0.05
    )
    review_threshold = st.slider(
        "Review threshold", min_value=0.0, max_value=1.0, value=0.70, step=0.05
    )

    st.divider()
    st.header("💾 Persistence & Cache")

    enable_persistence = st.toggle("Enable persistence", value=True)
    db_path = st.text_input(
        "Database path",
        value="nlp_pipeline.db",
        help="SQLite file path. The database is created automatically.",
        disabled=not enable_persistence,
    )

    enable_cache = st.toggle(
        "Enable enrichment cache",
        value=True,
        disabled=not enable_persistence,
        help="Cache requires persistence to be enabled.",
    )
    cache_ttl = st.slider(
        "Cache TTL (hours)",
        min_value=1,
        max_value=720,
        value=24,
        disabled=not (enable_persistence and enable_cache),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Build processor (cached per session to reuse persistence/cache state)
# ──────────────────────────────────────────────────────────────────────────────


@st.cache_resource
def _build_processor(
    _api_key: str,
    _model_name: str,
    _similarity: float,
    _review: float,
    _persist: bool,
    _db_path: str,
    _cache_enabled: bool,
    _cache_ttl: int,
) -> NLPProcessor:
    """Build and cache the processor so persistence state survives reruns."""
    persistence_config = None
    cache_config = None

    if _persist:
        persistence_config = PersistenceConfig(backend="sqlite", db_path=_db_path)
        if _cache_enabled:
            cache_config = CacheConfig(enabled=True, ttl_hours=_cache_ttl)

    return NLPProcessor.from_settings(
        api_key=_api_key,
        model_name=_model_name,
        similarity_threshold=_similarity,
        review_threshold=_review,
        persistence_config=persistence_config,
        cache_config=cache_config,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────────────────────────────────────

tab_process, tab_history, tab_trends = st.tabs(
    ["📝 Process Feedback", "📂 Batch History", "📈 Trend Analysis"]
)

# ──────────────────────────────────────────────────────────────────────────────
# Tab 1: Process Feedback
# ──────────────────────────────────────────────────────────────────────────────

with tab_process:
    source_channel = st.selectbox("Source channel", CHANNELS, index=0)
    text = st.text_area(
        "Feedback text",
        height=160,
        placeholder="e.g. My internet has been down for three days and support won't call me back.",
    )

    run = st.button("Process feedback", type="primary")

    if run:
        if not api_key.strip():
            st.error("Please enter a Gemini API key in the sidebar.")
            st.stop()
        if not text.strip():
            st.error("Please enter some feedback text.")
            st.stop()

        try:
            processor = _build_processor(
                api_key,
                model_name,
                similarity_threshold,
                review_threshold,
                enable_persistence,
                db_path,
                enable_cache,
                cache_ttl,
            )
        except ConfigurationError as exc:
            st.error(f"Configuration error: {exc}")
            st.stop()

        raw = RawFeedback(source_channel=source_channel, text=text)

        with st.spinner("Calling Gemini and enriching…"):
            try:
                output = processor.process_batch([raw])
            except Exception as exc:
                st.error(f"Processing failed: {type(exc).__name__}: {exc}")
                st.stop()

        # Show persistence result
        if enable_persistence and processor.last_save_result:
            sr = processor.last_save_result
            if sr.success:
                st.success(f"✅ Batch saved — ID: `{sr.batch_id}`")
            else:
                st.warning(f"⚠️ Save failed: {sr.error}")

        # Summary
        st.subheader("Summary")
        col1, col2, col3 = st.columns(3)
        col1.metric("Submitted", output.summary.submitted)
        col2.metric("Successful", output.summary.successful)
        col3.metric("Failures", output.summary.failures)

        # Insights with language metadata
        if output.insights:
            st.subheader("Insights")
            for insight in output.insights:
                with st.expander(
                    f"📋 {insight.feedback_id} — "
                    f"Sentiment: {insight.sentiment} | "
                    f"Severity: {insight.severity_score}/5"
                ):
                    # Language info
                    if insight.language_code:
                        lang_col1, lang_col2 = st.columns(2)
                        lang_col1.markdown(
                            f"**🌐 Language:** `{insight.language_code}`"
                        )
                        if insight.language_confidence is not None:
                            lang_col2.markdown(
                                f"**Confidence:** {insight.language_confidence:.2f}"
                            )

                    # Themes
                    st.markdown("**Themes:**")
                    for theme in insight.themes:
                        st.markdown(
                            f"- `{theme.theme}` (confidence: {theme.confidence:.2f})"
                        )

                    # Sentiment & Severity
                    st.markdown(
                        f"**Sentiment:** {insight.sentiment} "
                        f"(confidence: {insight.sentiment_confidence:.2f})"
                    )
                    st.markdown(f"**Severity:** {insight.severity_score}/5")
                    st.markdown("**Severity factors:**")
                    for factor in insight.severity_factors:
                        st.markdown(f"- {factor.description}")

                    if insight.review_flag:
                        st.warning("🔍 Flagged for human review")

                    if insight.notes:
                        st.markdown("**Notes:**")
                        for note in insight.notes:
                            st.caption(note)

        # Clusters
        if output.clusters:
            st.subheader("Clusters (ranked by priority)")
            for cluster in output.clusters:
                st.json(cluster.model_dump())

        # Failures
        if output.failures:
            st.subheader("⚠️ Failures")
            for failure in output.failures:
                st.json(failure.model_dump())

        if output.system_errors:
            st.subheader("🚨 System errors")
            for err in output.system_errors:
                st.json(err.model_dump())

        with st.expander("Full raw output (JSON)"):
            st.json(output.model_dump())

# ──────────────────────────────────────────────────────────────────────────────
# Tab 2: Batch History
# ──────────────────────────────────────────────────────────────────────────────

with tab_history:
    st.subheader("📂 Retrieve a Past Batch")

    if not enable_persistence:
        st.info("Enable persistence in the sidebar to use batch history.")
    else:
        batch_id_input = st.text_input(
            "Batch ID",
            placeholder="Enter a batch_id from a previous run",
        )
        retrieve_btn = st.button("Retrieve batch")

        if retrieve_btn and batch_id_input.strip():
            if not api_key.strip():
                st.error("Please enter a Gemini API key in the sidebar.")
            else:
                try:
                    processor = _build_processor(
                        api_key,
                        model_name,
                        similarity_threshold,
                        review_threshold,
                        enable_persistence,
                        db_path,
                        enable_cache,
                        cache_ttl,
                    )
                except ConfigurationError as exc:
                    st.error(f"Configuration error: {exc}")
                    st.stop()

                retrieved = processor.retrieve_batch(batch_id_input.strip())
                if retrieved is None:
                    st.warning("No batch found with that ID.")
                else:
                    st.success(
                        f"Found batch with {len(retrieved.insights)} insights"
                    )
                    st.json(retrieved.model_dump())

        st.divider()
        st.subheader("📋 List Recent Batches")
        st.caption("Shows batches saved in the last 30 days.")

        list_btn = st.button("List batches")
        if list_btn:
            if not api_key.strip():
                st.error("Please enter a Gemini API key in the sidebar.")
            else:
                try:
                    processor = _build_processor(
                        api_key,
                        model_name,
                        similarity_threshold,
                        review_threshold,
                        enable_persistence,
                        db_path,
                        enable_cache,
                        cache_ttl,
                    )
                except ConfigurationError as exc:
                    st.error(f"Configuration error: {exc}")
                    st.stop()

                from datetime import timedelta

                now = datetime.now(timezone.utc)
                start = now - timedelta(days=30)
                batches = processor._persistence_store.list_batches(start, now)

                if not batches:
                    st.info("No batches found in the last 30 days.")
                else:
                    st.write(f"Found **{len(batches)}** batch(es):")
                    for meta in batches:
                        st.markdown(
                            f"- **{meta.batch_id}** — "
                            f"{meta.timestamp} — "
                            f"{meta.record_count} records"
                        )

# ──────────────────────────────────────────────────────────────────────────────
# Tab 3: Trend Analysis
# ──────────────────────────────────────────────────────────────────────────────

with tab_trends:
    st.subheader("📈 Trend Analysis")
    st.caption(
        "Compare two time windows to detect theme spikes, sentiment shifts, "
        "and severity escalations. Requires at least 10 records in each window."
    )

    if not enable_persistence:
        st.info("Enable persistence in the sidebar to use trend analysis.")
    else:
        col_base, col_curr = st.columns(2)

        with col_base:
            st.markdown("**Baseline Window**")
            baseline_start = st.date_input(
                "Baseline start",
                value=datetime(2024, 1, 1),
                key="b_start",
            )
            baseline_end = st.date_input(
                "Baseline end",
                value=datetime(2024, 3, 1),
                key="b_end",
            )

        with col_curr:
            st.markdown("**Current Window**")
            current_start = st.date_input(
                "Current start",
                value=datetime(2024, 3, 1),
                key="c_start",
            )
            current_end = st.date_input(
                "Current end",
                value=datetime(2024, 6, 1),
                key="c_end",
            )

        run_trends = st.button("Detect trends", type="primary")

        if run_trends:
            if not api_key.strip():
                st.error("Please enter a Gemini API key in the sidebar.")
                st.stop()

            try:
                processor = _build_processor(
                    api_key,
                    model_name,
                    similarity_threshold,
                    review_threshold,
                    enable_persistence,
                    db_path,
                    enable_cache,
                    cache_ttl,
                )
            except ConfigurationError as exc:
                st.error(f"Configuration error: {exc}")
                st.stop()

            baseline = TimeWindow(
                start=datetime.combine(
                    baseline_start, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
                end=datetime.combine(
                    baseline_end, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
            )
            current = TimeWindow(
                start=datetime.combine(
                    current_start, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
                end=datetime.combine(
                    current_end, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
            )

            try:
                report = processor.detect_trends(baseline, current)
            except ValueError as exc:
                st.error(f"Invalid window configuration: {exc}")
                st.stop()
            except RuntimeError as exc:
                st.error(str(exc))
                st.stop()

            # Display results
            if report.notes:
                for note in report.notes:
                    st.info(f"ℹ️ {note}")

            # Theme spikes
            if report.theme_spikes:
                st.subheader("🔺 Theme Spikes")
                for spike in report.theme_spikes:
                    pct = (
                        "NEW"
                        if spike.percentage_increase == "new"
                        else f"+{spike.percentage_increase:.1f}%"
                    )
                    st.markdown(
                        f"- **{spike.theme}** — {pct} "
                        f"(baseline: {spike.baseline_frequency:.2%} → "
                        f"current: {spike.current_frequency:.2%})"
                    )
            else:
                st.caption("No theme spikes detected.")

            # Sentiment shifts
            if report.sentiment_shifts:
                st.subheader("😟 Sentiment Shifts")
                for shift in report.sentiment_shifts:
                    st.markdown(
                        f"- Negative proportion: "
                        f"{shift.baseline_negative_proportion:.1%} → "
                        f"{shift.current_negative_proportion:.1%} "
                        f"(**+{shift.difference_ppt:.1f} ppt**)"
                    )
            else:
                st.caption("No sentiment shifts detected.")

            # Severity escalations
            if report.severity_escalations:
                st.subheader("🚨 Severity Escalations")
                for esc in report.severity_escalations:
                    st.markdown(
                        f"- Mean severity: "
                        f"{esc.baseline_mean_severity:.2f} → "
                        f"{esc.current_mean_severity:.2f} "
                        f"(**+{esc.difference:.2f} points**)"
                    )
            else:
                st.caption("No severity escalations detected.")

            with st.expander("Full TrendReport (JSON)"):
                st.json(report.model_dump())
