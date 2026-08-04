"""Unit tests for the type-checking engine (no live server needed)."""

from chiron_validator.typecheck import check_response, check_value, summarize


def _codes(issues):
    return sorted(i.code for i in issues)


def test_scalar_types_pass():
    c = {"kind": "object", "fields": [
        {"name": "id", "type": "integer", "required": True, "nullable": False},
        {"name": "name", "type": "string", "required": True, "nullable": False},
        {"name": "ok", "type": "boolean", "required": True, "nullable": False},
        {"name": "score", "type": "number", "required": True, "nullable": False},
    ]}
    body = {"id": 1, "name": "x", "ok": True, "score": 3.5}
    assert summarize(check_response(c, body))["passed"]


def test_integer_not_boolean():
    # booleans must not satisfy integer
    issues = check_value("integer", False, True, "flag")
    assert _codes(issues) == ["type_mismatch"]


def test_integer_accepts_int_number_field_accepts_int():
    assert check_value("number", False, 3, "n") == []
    assert check_value("integer", False, 3, "n") == []


def test_type_mismatch_detected():
    c = {"kind": "object", "fields": [
        {"name": "id", "type": "integer", "required": True, "nullable": False}]}
    issues = check_response(c, {"id": "not-an-int"})
    assert any(i.code == "type_mismatch" and i.path == "id" for i in issues)


def test_missing_required_field():
    c = {"kind": "object", "fields": [
        {"name": "id", "type": "integer", "required": True, "nullable": False}]}
    issues = check_response(c, {})
    assert any(i.code == "missing_field" for i in issues)


def test_optional_field_absent_ok():
    c = {"kind": "object", "fields": [
        {"name": "id", "type": "integer", "required": False, "nullable": False}]}
    assert summarize(check_response(c, {}))["passed"]


def test_unexpected_null():
    c = {"kind": "object", "fields": [
        {"name": "name", "type": "string", "required": True, "nullable": False}]}
    issues = check_response(c, {"name": None})
    assert any(i.code == "unexpected_null" for i in issues)


def test_nullable_allows_null():
    c = {"kind": "object", "fields": [
        {"name": "name", "type": "string", "required": True, "nullable": True}]}
    assert summarize(check_response(c, {"name": None}))["passed"]


def test_extra_field_is_info_only():
    c = {"kind": "object", "strict_extra": True, "fields": [
        {"name": "id", "type": "integer", "required": True, "nullable": False}]}
    s = summarize(check_response(c, {"id": 1, "surprise": "hi"}))
    assert s["passed"]  # extra field is info, not error
    assert s["by_code"].get("extra_field") == 1


def test_paginated_wrapper_and_items():
    c = {"kind": "paginated", "fields": [
        {"name": "permanent_id", "type": "string", "required": True, "nullable": False}]}
    good = {"count": 2, "next": None, "previous": None,
            "results": [{"permanent_id": "a"}, {"permanent_id": "b"}]}
    assert summarize(check_response(c, good))["passed"]
    # missing wrapper -> wrong_container
    issues = check_response(c, [{"permanent_id": "a"}])
    assert any(i.code == "wrong_container" for i in issues)


def test_paginated_item_type_error():
    c = {"kind": "paginated", "fields": [
        {"name": "pk", "type": "integer", "required": True, "nullable": False}]}
    body = {"count": 1, "next": None, "previous": None, "results": [{"pk": "oops"}]}
    issues = check_response(c, body)
    assert any(i.code == "type_mismatch" and i.path == "results[0].pk" for i in issues)


def test_enum_check():
    issues = check_value("enum:cohort|table", False, "analysis", "t")
    assert _codes(issues) == ["bad_enum"]
    assert check_value("enum:cohort|table", False, "cohort", "t") == []


def test_iso8601():
    assert check_value("string:iso8601", False, "2026-07-20T10:00:00Z", "d") == []
    assert check_value("string:iso8601", False, "07/15/2026", "d") == []
    bad = check_value("string:iso8601", False, "not a date", "d")
    assert _codes(bad) == ["type_mismatch"]


def test_nested_object_fields():
    c = {"kind": "object", "fields": [
        {"name": "user", "type": "object", "required": True, "nullable": True,
         "object_fields": [
             {"name": "id", "type": "integer", "required": True, "nullable": False}]}]}
    assert summarize(check_response(c, {"user": {"id": 1}}))["passed"]
    issues = check_response(c, {"user": {"id": "x"}})
    assert any(i.path == "user.id" and i.code == "type_mismatch" for i in issues)
    # nullable nested object allowed to be null
    assert summarize(check_response(c, {"user": None}))["passed"]


def test_nested_item_fields():
    c = {"kind": "object", "fields": [
        {"name": "datasets", "type": "array", "required": True, "nullable": False,
         "item_fields": [
             {"name": "id", "type": "integer", "required": True, "nullable": False},
             {"name": "selectable", "type": "boolean", "required": True, "nullable": False}]}]}
    good = {"datasets": [{"id": 1, "selectable": True}]}
    assert summarize(check_response(c, good))["passed"]
    bad = {"datasets": [{"id": 1, "selectable": "yes"}]}
    assert any(i.path == "datasets[0].selectable" for i in check_response(c, bad))


def test_raw_contract_skips():
    assert check_response({"kind": "raw", "fields": []}, "id,name\n1,x") == []
