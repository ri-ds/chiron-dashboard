"""chiron-validator — a database of type validations for Chiron's public API.

Derives expected request/response field types from Chiron's own DRF serializers
and Django models (captured in specs/inventory.json), stores them in a queryable
SQLite DB, then calls the *live* API with synthetic data and checks every
response field-by-field against those expectations. Black-box: HTTP only.
"""

__version__ = "0.1.0"
