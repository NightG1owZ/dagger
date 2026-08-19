"""Tests for OpenAPI parsing ($ref resolution, base URL, fetch)."""

from __future__ import annotations

import pytest

from java.models import ApiEndpoint
from java.openapi import OpenApiError, deref, fetch_spec, parse_spec


def test_parse_spec_extracts_endpoints(openapi_server):
    base, endpoints = parse_spec(openapi_server["spec"])
    assert base == openapi_server["base"]
    paths = {(e.method, e.path) for e in endpoints}
    assert ("GET", "/api/fast") in paths
    assert ("GET", "/api/users/{id}") in paths
    assert ("POST", "/api/users") in paths


def test_parse_spec_resolves_path_and_query_params(openapi_server):
    _, endpoints = parse_spec(openapi_server["spec"])
    user = next(e for e in endpoints if e.path == "/api/users/{id}")
    by_loc = {p.location: p for p in user.params}
    assert by_loc["path"].name == "id"
    assert by_loc["path"].required is True
    assert by_loc["path"].schema == {"type": "integer", "minimum": 1, "maximum": 100}
    assert by_loc["query"].name == "verbose"
    assert by_loc["query"].required is False
    assert by_loc["query"].schema == {"type": "boolean"}


def test_parse_spec_resolves_body_ref(openapi_server):
    _, endpoints = parse_spec(openapi_server["spec"])
    create = next(e for e in endpoints if e.path == "/api/users" and e.method == "POST")
    assert create.body_schema is not None
    assert create.body_schema["type"] == "object"
    assert "name" in create.body_schema["properties"]
    assert create.body_schema["required"] == ["name"]


def test_parse_spec_base_url_override(openapi_server):
    base, _ = parse_spec(openapi_server["spec"], base_url="http://example.com/api")
    assert base == "http://example.com/api"


def test_parse_spec_missing_servers_requires_base_url():
    spec = {"openapi": "3.0.0", "paths": {"/x": {"get": {}}}}
    with pytest.raises(OpenApiError, match="base URL"):
        parse_spec(spec)


def test_parse_spec_invalid_document():
    with pytest.raises(OpenApiError, match="paths"):
        parse_spec({"openapi": "3.0.0"})


def test_deref_nested_and_missing_refs():
    components = {
        "schemas": {
            "A": {"$ref": "#/components/schemas/B"},
            "B": {"type": "string", "minLength": 3},
        }
    }
    assert deref({"$ref": "#/components/schemas/A"}, components) == {
        "type": "string",
        "minLength": 3,
    }
    with pytest.raises(OpenApiError):
        deref({"$ref": "#/components/schemas/Nope"}, components)
    with pytest.raises(OpenApiError):
        deref({"$ref": "http://remote/other.json"}, components)


def test_deref_allof_merge():
    components = {
        "schemas": {
            "Base": {"type": "object", "properties": {"id": {"type": "integer"}}}
        }
    }
    merged = deref(
        {
            "allOf": [
                {"$ref": "#/components/schemas/Base"},
                {"required": ["name"], "properties": {"name": {"type": "string"}}},
            ]
        },
        components,
    )
    assert merged["type"] == "object"
    assert merged["required"] == ["name"]
    assert "id" in merged["properties"] and "name" in merged["properties"]


@pytest.mark.asyncio
async def test_fetch_spec_from_server(openapi_server):
    spec = await fetch_spec(openapi_server["spec_url"])
    assert spec["openapi"] == "3.0.1"
    assert "/api/fast" in spec["paths"]


@pytest.mark.asyncio
async def test_fetch_spec_http_error(openapi_server):
    with pytest.raises(OpenApiError, match="HTTP 404"):
        await fetch_spec(openapi_server["base"] + "/api/v3/not-found")
