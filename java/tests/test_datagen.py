"""Tests for schema-driven test data generation."""

from __future__ import annotations

import random
import re
import uuid

from java.datagen import generate_value, prepare_request
from java.models import ApiEndpoint, ApiParam

# UUID suffix pattern appended to business-unique fields.
_UNIQUE_SUFFIX = re.compile(r"_[0-9a-f]{8}$")


def _gen(schema, components=None, rng=None, **kwargs):
    return generate_value(schema, components or {}, rng or random.Random(7), **kwargs)


def test_string_respects_length_bounds():
    rng = random.Random(1)
    for _ in range(50):
        value = _gen({"type": "string", "minLength": 5, "maxLength": 5}, rng=rng)
        assert isinstance(value, str)
        assert len(value) == 5


def test_string_enum_and_formats():
    rng = random.Random(1)
    assert _gen({"type": "string", "enum": ["a", "b"]}, rng=rng) in ("a", "b")
    uuid_value = _gen({"type": "string", "format": "uuid"}, rng=rng)
    assert uuid.UUID(uuid_value)  # must parse as a UUID
    assert "@" in _gen({"type": "string", "format": "email"}, rng=rng)
    assert "T" in _gen({"type": "string", "format": "date-time"}, rng=rng)


def test_integer_within_range():
    rng = random.Random(1)
    for _ in range(50):
        value = _gen(
            {"type": "integer", "minimum": 10, "maximum": 20},
            rng=rng,
        )
        assert isinstance(value, int)
        assert 10 <= value <= 20


def test_integer_default_range_and_exclusive():
    rng = random.Random(1)
    for _ in range(20):
        assert 1 <= _gen({"type": "integer"}, rng=rng) <= 100
    assert _gen(
        {"type": "integer", "minimum": 5, "exclusiveMinimum": True}, rng=rng
    ) > 5


def test_number_is_float():
    rng = random.Random(1)
    for _ in range(20):
        assert isinstance(_gen({"type": "number"}, rng=rng), float)


def test_boolean():
    rng = random.Random(1)
    assert isinstance(_gen({"type": "boolean"}, rng=rng), bool)


def test_array_length_one_to_three():
    rng = random.Random(1)
    for _ in range(30):
        value = _gen({"type": "array", "items": {"type": "integer"}}, rng=rng)
        assert 1 <= len(value) <= 3
        assert all(isinstance(i, int) for i in value)


def test_required_fields_always_present_and_non_empty():
    rng = random.Random(1)
    schema = {
        "type": "object",
        "required": ["name", "age", "tags"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }
    for _ in range(50):
        value = _gen(schema, rng=rng)
        assert "name" in value and isinstance(value["name"], str) and value["name"]
        assert "age" in value and isinstance(value["age"], int)
        assert "tags" in value and isinstance(value["tags"], list)


def test_optional_fields_generated_with_50_percent_chance():
    rng = random.Random(1)
    schema = {
        "type": "object",
        "properties": {"note": {"type": "string"}},
    }
    present = absent = 0
    for _ in range(200):
        value = _gen(schema, rng=rng)
        if "note" in value:
            present += 1
        else:
            absent += 1
    # Over 200 samples a 50% field must show both outcomes.
    assert present > 0 and absent > 0


def test_nested_object_recursion():
    rng = random.Random(1)
    schema = {
        "type": "object",
        "required": ["profile", "friends"],
        "properties": {
            "profile": {
                "type": "object",
                "required": ["nick"],
                "properties": {"nick": {"type": "string"}},
            },
            "friends": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "integer"}},
                },
            },
        },
    }
    for _ in range(20):
        value = _gen(schema, rng=rng)
        assert isinstance(value["profile"], dict) and value["profile"]["nick"]
        assert 1 <= len(value["friends"]) <= 3
        assert all(f["id"] for f in value["friends"])


def test_object_ref_resolution():
    components = {
        "schemas": {
            "User": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}},
            }
        }
    }
    value = _gen({"$ref": "#/components/schemas/User"}, components=components)
    assert isinstance(value, dict) and "id" in value


def test_default_used_when_present():
    assert _gen({"type": "string", "default": "fixed"}) == "fixed"
    assert _gen({"type": "integer", "default": 42}) == 42


def test_const():
    assert _gen({"type": "string", "const": "locked"}) == "locked"


def test_unique_username_gets_uuid_suffix():
    rng = random.Random(1)
    schema = {
        "type": "object",
        "required": ["username"],
        "properties": {"username": {"type": "string", "minLength": 4}},
    }
    seen = set()
    for _ in range(30):
        value = _gen(schema, rng=rng)["username"]
        assert _UNIQUE_SUFFIX.search(value), value
        seen.add(value)
    assert len(seen) == 30  # all unique


def test_unique_email_gets_uuid_suffix_in_local_part():
    rng = random.Random(1)
    schema = {
        "type": "object",
        "required": ["email"],
        "properties": {"email": {"type": "string", "format": "email"}},
    }
    seen = set()
    for _ in range(30):
        value = _gen(schema, rng=rng)["email"]
        local, _, domain = value.partition("@")
        assert _UNIQUE_SUFFIX.search(local), value
        assert domain
        seen.add(value)
    assert len(seen) == 30


def test_unique_field_respects_max_length():
    rng = random.Random(1)
    schema = {
        "type": "object",
        "required": ["username"],
        "properties": {"username": {"type": "string", "maxLength": 12}},
    }
    for _ in range(20):
        value = _gen(schema, rng=rng)["username"]
        assert len(value) <= 12
        assert _UNIQUE_SUFFIX.search(value)


def test_body_never_empty_when_properties_declared():
    components = {
        "schemas": {
            "Dto": {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "integer"},
                    "c": {"type": "boolean"},
                },
            }
        }
    }
    endpoint = ApiEndpoint(
        method="POST",
        path="/api/dto",
        body_schema={"$ref": "#/components/schemas/Dto"},
    )
    for _ in range(100):
        _, kwargs = prepare_request(endpoint, "http://x", components, random.Random(5))
        assert kwargs["json"], "request body must never be empty"


def test_empty_object_default_is_ignored_when_properties_exist():
    schema = {
        "type": "object",
        "default": {},
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    for _ in range(10):
        value = _gen(schema)
        assert value and value["name"]


def test_prepare_request_builds_url_params_and_body():
    components = {
        "schemas": {
            "User": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            }
        }
    }
    endpoint = ApiEndpoint(
        method="POST",
        path="/api/users/{id}",
        params=[
            ApiParam("id", "path", True, {"type": "integer", "minimum": 1, "maximum": 1}),
            ApiParam("verbose", "query", False, {"type": "boolean"}),
            ApiParam("X-Trace", "header", False, {"type": "string"}),
        ],
        body_schema={"$ref": "#/components/schemas/User"},
    )
    url, kwargs = prepare_request(endpoint, "http://x", components, random.Random(3))
    assert url == "http://x/api/users/1"
    assert "verbose" in kwargs["params"]
    assert kwargs["headers"]["X-Trace"]
    assert isinstance(kwargs["json"], dict)
    assert "name" in kwargs["json"]


def test_prepare_request_unique_params():
    endpoint = ApiEndpoint(
        method="GET",
        path="/api/users/{username}",
        params=[
            ApiParam("username", "path", True, {"type": "string"}),
            ApiParam("email", "query", False, {"type": "string", "format": "email"}),
        ],
    )
    url, kwargs = prepare_request(endpoint, "http://x", {}, random.Random(3))
    username = url.rsplit("/", 1)[-1]
    assert _UNIQUE_SUFFIX.search(username), username
    assert _UNIQUE_SUFFIX.search(kwargs["params"]["email"].split("@")[0])


def test_prepare_request_presets_unresolved_path_vars():
    endpoint = ApiEndpoint(method="GET", path="/api/users/{id}/orders/{oid}")
    url, kwargs = prepare_request(endpoint, "http://x", {}, random.Random(3))
    assert url == "http://x/api/users/1/orders/1"
