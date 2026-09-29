"""Tests for shared response behavior."""

from app.common.responses import success_response


def test_success_response_builds_meta_as_dict() -> None:
    payload = success_response({"id": "1"}, meta={"page": 1})

    assert payload.success is True
    assert payload.data == {"id": "1"}
    assert payload.meta == {"page": 1}
