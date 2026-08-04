"""Synthetic test-data generation.

Two kinds of "test data" are involved and both are synthetic:

  * **Subject data** already loaded in Chiron's warehouse (the ``datasetN_stored``
    Postgres schemas) is Synthea-style synthetic patient data — no real PHI.
    The validator never fabricates or transmits patient records.
  * **Request payloads** the validator sends (cohort definitions, table
    definitions, query params) are synthetic *query structures* built from
    concept metadata discovered live via the public API. They describe how to
    query, not any person.

Everything here is deterministic (no randomness) so runs are reproducible.
"""

from __future__ import annotations

from typing import Any

# Provenance note surfaced in the report so a reviewer can confirm no real PHI.
DATA_PROVENANCE = (
    "Warehouse subject data is Synthea-style synthetic records (loaded into the "
    "datasetN_stored Postgres schemas by Chiron's ETL). Request payloads are "
    "synthetic query definitions derived from live concept metadata. No real "
    "patient data is used or generated."
)


def empty_cohort_def() -> dict:
    """A minimal, valid 'match everyone' cohort definition body."""
    return {"cohort_def": {"entries": [], "match_all": True}}


def minimal_table_def(concept_permanent_id: str | None) -> dict:
    """A minimal table definition selecting a single discovered concept."""
    fields = []
    if concept_permanent_id:
        fields.append({"concept": concept_permanent_id, "alias": concept_permanent_id})
    return {"table_def": {"fields": fields}}


def synthetic_query_params(concept: dict | None = None) -> dict:
    """Generic, safe query params for list/preview endpoints."""
    return {"page": 1, "page_size": 25}


def scalar_for_type(t: str) -> Any:
    """A synthetic value matching an expected request-field type (used when
    probing write endpoints under --include-writes)."""
    base = (t or "any").split(":")[0].split("<")[0]
    return {
        "string": "synthetic-validator-value",
        "integer": 1,
        "number": 1.0,
        "boolean": True,
        "array": [],
        "object": {},
        "null": None,
        "any": "synthetic-validator-value",
    }.get(base, "synthetic-validator-value")
