"""Unit tests for type-string normalisation + spec building."""

from chiron_validator.normalize import (build_response_contract, normalize_type,
                                         response_kind)


def test_scalar_aliases():
    assert normalize_type("int") == ("integer", False)
    assert normalize_type("str") == ("string", False)
    assert normalize_type("bool") == ("boolean", False)
    assert normalize_type("float") == ("number", False)
    assert normalize_type("dict") == ("object", False)


def test_nullable_from_pipe():
    assert normalize_type("int|null") == ("integer", True)
    assert normalize_type("string | null") == ("string", True)
    assert normalize_type("ConceptRelated|null")[1] is True


def test_string_subtypes():
    assert normalize_type("string(iso8601)") == ("string:iso8601", False)
    assert normalize_type("string(url)") == ("string:url", False)
    assert normalize_type("datetime") == ("string:iso8601", False)


def test_typed_array():
    assert normalize_type("array<int>") == ("array<integer>", False)
    # opaque element -> plain array (presence only)
    assert normalize_type("array<ConceptSerializer>") == ("array", False)
    assert normalize_type("list[str]") == ("array<string>", False)


def test_opaque_types_become_object_or_any():
    t, _ = normalize_type("ConceptSerializer")
    assert t in ("object", "any")
    assert normalize_type("dynamic object")[0] == "object" or normalize_type("dynamic object")[0] == "any"


def test_html_entities_unescaped():
    assert normalize_type("array&lt;int&gt;") == ("array<integer>", False)


def test_response_kind():
    assert response_kind("paginated") == "paginated"
    assert response_kind("array") == "array"
    assert response_kind("object") == "object"
    assert response_kind("csv") == "raw"
    assert response_kind("form-json") == "object"


def test_build_response_contract_drops_placeholder():
    ep = {"response_type": "object",
          "response_fields": [
              {"name": "<ConceptSerializer fields>", "type": "object", "nullable": False, "notes": ""},
              {"name": "statistics", "type": "object", "nullable": False,
               "notes": "Present only if include_statistics"}]}
    c = build_response_contract(ep)
    names = [f["name"] for f in c["fields"]]
    assert "<ConceptSerializer fields>" not in names
    assert "statistics" in names
    # placeholder present -> strict_extra disabled
    assert c["strict_extra"] is False
    # conditionally-present field marked optional
    stats = [f for f in c["fields"] if f["name"] == "statistics"][0]
    assert stats["required"] is False
