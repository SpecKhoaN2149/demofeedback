"""Property 26: Invalid TimeWindow rejection.

For any TimeWindow pair where baseline start ≥ baseline end, current start ≥ current end,
or the two windows overlap, the API_Server SHALL return a validation error without invoking
the NLPProcessor.

**Validates: Requirements 15.4**
"""

import os
import tempfile

# Set up temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.database import get_connection, init_db
from app.main import app
from app.services.auth_service import AuthService

# Initialize DB once at module load
init_db()

_client = TestClient(app)


# --- Helpers ---


def _reset_db():
    """Clear all tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.execute("DELETE FROM submissions")
        conn.commit()


def _create_admin_token() -> str:
    """Create an admin user and return a valid session token."""
    auth = AuthService()
    auth.create_admin("testadmin", "testpassword123")
    session = auth.login("testadmin", "testpassword123")
    assert session is not None
    return session.token


# --- Strategies ---

# Generate datetimes within a reasonable range
reasonable_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)

# Positive durations (at least 1 second)
positive_durations = st.timedeltas(
    min_value=timedelta(seconds=1),
    max_value=timedelta(days=365),
)


# --- Property Tests ---


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    start=reasonable_datetimes,
    offset=positive_durations,
)
def test_baseline_start_gte_end_returns_422(start: datetime, offset: timedelta):
    """Property 26 case 1: Baseline window with start ≥ end returns 422.

    For any baseline window where start ≥ end, the API_Server SHALL return 422
    without invoking the NLPProcessor.

    Feature: sentiment-routed-frontend, Property 26: Invalid TimeWindow rejection
    **Validates: Requirements 15.4**
    """
    _reset_db()
    token = _create_admin_token()

    # baseline start >= end (start == end + offset, so start > end)
    baseline_end = start
    baseline_start = start + offset  # start > end

    # Current window is valid (non-overlapping, after baseline)
    current_start = baseline_start + timedelta(days=1)
    current_end = current_start + timedelta(days=7)

    payload = {
        "baseline_window": {
            "start": baseline_start.isoformat(),
            "end": baseline_end.isoformat(),
        },
        "current_window": {
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
        },
    }

    response = _client.post(
        "/api/admin/trends",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422, (
        f"Expected 422 for baseline start >= end, got {response.status_code}: {response.text}"
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    start=reasonable_datetimes,
    offset=positive_durations,
)
def test_current_start_gte_end_returns_422(start: datetime, offset: timedelta):
    """Property 26 case 2: Current window with start ≥ end returns 422.

    For any current window where start ≥ end, the API_Server SHALL return 422
    without invoking the NLPProcessor.

    Feature: sentiment-routed-frontend, Property 26: Invalid TimeWindow rejection
    **Validates: Requirements 15.4**
    """
    _reset_db()
    token = _create_admin_token()

    # Baseline window is valid
    baseline_start = start
    baseline_end = start + timedelta(days=7)

    # Current window: start >= end (start == end + offset, so start > end)
    current_end = baseline_end + timedelta(days=1)
    current_start = current_end + offset  # start > end

    payload = {
        "baseline_window": {
            "start": baseline_start.isoformat(),
            "end": baseline_end.isoformat(),
        },
        "current_window": {
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
        },
    }

    response = _client.post(
        "/api/admin/trends",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422, (
        f"Expected 422 for current start >= end, got {response.status_code}: {response.text}"
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    base_start=reasonable_datetimes,
    window_size=st.timedeltas(min_value=timedelta(hours=1), max_value=timedelta(days=30)),
    overlap_offset=st.timedeltas(min_value=timedelta(seconds=1), max_value=timedelta(days=29)),
)
def test_overlapping_windows_returns_422(
    base_start: datetime, window_size: timedelta, overlap_offset: timedelta
):
    """Property 26 case 3: Overlapping windows return 422.

    For any pair of windows that overlap in time, the API_Server SHALL return 422
    without invoking the NLPProcessor.

    Feature: sentiment-routed-frontend, Property 26: Invalid TimeWindow rejection
    **Validates: Requirements 15.4**
    """
    _reset_db()
    token = _create_admin_token()

    # Construct overlapping windows:
    # baseline: [base_start, base_start + window_size]
    # current starts before baseline ends (overlap_offset < window_size ensures overlap)
    baseline_start = base_start
    baseline_end = base_start + window_size

    # Current starts within the baseline window to guarantee overlap
    # Clamp overlap_offset to be less than window_size to ensure overlap
    actual_overlap = min(overlap_offset, window_size - timedelta(seconds=1))
    if actual_overlap <= timedelta(0):
        actual_overlap = timedelta(seconds=1)

    current_start = baseline_start + actual_overlap
    current_end = current_start + window_size

    # Both windows must individually be valid (start < end) for this to test overlap specifically
    assert baseline_start < baseline_end
    assert current_start < current_end

    # Verify they actually overlap
    overlaps = baseline_start < current_end and current_start < baseline_end
    assert overlaps, "Test setup error: windows should overlap"

    payload = {
        "baseline_window": {
            "start": baseline_start.isoformat(),
            "end": baseline_end.isoformat(),
        },
        "current_window": {
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
        },
    }

    response = _client.post(
        "/api/admin/trends",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422, (
        f"Expected 422 for overlapping windows, got {response.status_code}: {response.text}"
    )
