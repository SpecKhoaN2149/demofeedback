# NLP Feedback Processing

The enrichment layer of a telecom Customer Feedback and Support Intake system.
It accepts normalized customer feedback from four source channels (email, survey,
call transcript, social post) and produces structured, ranked insights using the
Google Gemini API.

## Requirements

- Python 3.11+

## Setup

Install the package with its test dependencies:

```bash
pip install -e ".[test]"
```

## Running tests

```bash
pytest
```

## Package layout

```
nlp_processing/
  models/          # pydantic data models and shared type literals
  transport/       # Gemini_Client + secret redaction
  enrichment/      # Classifier, Sentiment_Analyzer, Severity_Scorer
  aggregation/     # Clustering, Prioritization, output assembly
  serialization/   # Response_Parser, Response_Serializer
  config.py        # configuration loading + fail-fast validation
tests/             # unit + Hypothesis property tests (mirrors package layout)
  strategies.py    # shared Hypothesis strategies
```
