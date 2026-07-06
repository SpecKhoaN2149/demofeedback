"""Property 30: PII removed from share templates.

**Validates: Requirements 17.2**

For any positive submission with social sharing enabled, the generated email template
SHALL NOT contain the customer name or contact information (email, phone).
"""

import os
import tempfile
import uuid

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.database import init_db, get_connection
from app.services.marketing_engine import MarketingEngine


@pytest.fixture(autouse=True)
def fresh_db():
    """Initialize a fresh database before each test."""
    init_db()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM submissions")
        conn.commit()


# --- Strategies ---

# Generate realistic customer names (first + last)
first_names = st.sampled_from([
    "Alice", "Bob", "Charlie", "Diana", "Edward", "Fiona",
    "George", "Hannah", "Ivan", "Julia", "Kevin", "Laura",
    "Michael", "Nancy", "Oscar", "Patricia", "Quincy", "Rachel",
])

last_names = st.sampled_from([
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
])

customer_names = st.builds(lambda f, l: f"{f} {l}", first_names, last_names)

# Generate realistic email addresses
email_strategy = st.builds(
    lambda user, domain, tld: f"{user}@{domain}.{tld}",
    user=st.from_regex(r"[a-z][a-z0-9._]{2,12}", fullmatch=True),
    domain=st.from_regex(r"[a-z]{3,8}", fullmatch=True),
    tld=st.sampled_from(["com", "org", "net", "io", "co"]),
)

# Generate realistic phone numbers
phone_strategy = st.one_of(
    # US format: +1-555-123-4567
    st.builds(
        lambda a, b, c: f"+1-{a}-{b}-{c}",
        st.from_regex(r"[2-9][0-9]{2}", fullmatch=True),
        st.from_regex(r"[0-9]{3}", fullmatch=True),
        st.from_regex(r"[0-9]{4}", fullmatch=True),
    ),
    # Plain digits: 5551234567
    st.from_regex(r"[2-9][0-9]{9}", fullmatch=True),
    # International format: +44 7911 123456
    st.builds(
        lambda cc, rest: f"+{cc} {rest}",
        st.from_regex(r"[1-9][0-9]{0,2}", fullmatch=True),
        st.from_regex(r"[0-9]{4} [0-9]{5,6}", fullmatch=True),
    ),
)

# Generate praise text that deliberately INCLUDES PII values
base_praise = st.sampled_from([
    "Your service was amazing",
    "I had a wonderful experience with Spectrum",
    "The technician was so helpful and kind",
    "Everything was resolved quickly and efficiently",
    "Best customer service I have ever received",
    "The support team went above and beyond",
])


@st.composite
def praise_with_pii(draw):
    """Generate praise text that includes the customer name, email, and phone."""
    name = draw(customer_names)
    email = draw(email_strategy)
    phone = draw(phone_strategy)
    praise = draw(base_praise)

    # Embed PII directly in the praise text
    text = f"My name is {name} and {praise}. Contact me at {email} or call {phone}. Thanks, {name}!"
    return name, email, phone, text


@settings(max_examples=100)
@given(data=praise_with_pii())
def test_pii_removed_from_share_templates(data):
    """Property 30: PII removed from share templates.

    Feature: sentiment-routed-frontend, Property 30
    **Validates: Requirements 17.2**
    """
    customer_name, email, phone, praise_text = data
    engine = MarketingEngine()
    submission_id = str(uuid.uuid4())

    # Insert a parent submission row so FK constraint is satisfied
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO submissions (id, created_at, customer_name, email, phone,
                                     core_request, sentiment, progress_state,
                                     praise_text, social_sharing)
            VALUES (?, datetime('now'), ?, ?, ?, 'Great service', 'positive', 100, ?, 1)
            """,
            (submission_id, customer_name, email, phone, praise_text),
        )
        conn.commit()

    # Log praise with social sharing enabled
    engine.log_praise(
        submission_id=submission_id,
        customer_name=customer_name,
        praise_text=praise_text,
        social_sharing=True,
    )

    # Generate share content
    share_result = engine.generate_share(submission_id)
    email_template = share_result.email_template

    # Assert: customer name is NOT in the email template
    assert customer_name.lower() not in email_template.lower(), (
        f"Email template contains customer name '{customer_name}': {email_template}"
    )

    # Assert: email address is NOT in the email template
    assert email.lower() not in email_template.lower(), (
        f"Email template contains email address '{email}': {email_template}"
    )

    # Assert: phone number is NOT in the email template
    assert phone not in email_template, (
        f"Email template contains phone number '{phone}': {email_template}"
    )

    # Cleanup for this test iteration
    with get_connection() as conn:
        conn.execute("DELETE FROM marketing_log WHERE submission_id = ?", (submission_id,))
        conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
        conn.commit()
