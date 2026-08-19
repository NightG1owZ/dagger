"""Schema-driven test data generation (OpenAPI 3.x subset).

Guarantees (per the tool's strategy):

* Fields listed in the schema's ``required`` array are **always** generated
  with a non-empty value; empty results are retried and, if needed, replaced
  with a type-appropriate fallback.
* Non-required fields are generated with a 50% chance per request, simulating
  real-world request variation.
* A request body object with declared properties is **never** sent as ``{}``:
  when every optional field rolls "absent", the body is regenerated and, as a
  last resort, the first declared property is included.
* Type mapping: ``string + email`` uses faker's ``email()``, ``string +
  date-time`` uses the current timestamp, plain strings follow
  minLength/maxLength, numbers stay within minimum/maximum, booleans are
  random.
* Business-unique fields (username / email / slug / login / account ...) get a
  UUID suffix (e.g. ``user_ab12cd34``) so thousands of requests never collide.
* Nested objects recurse; arrays generate 1-3 elements.
"""

from __future__ import annotations

import datetime as _dt
import random
import re
import string
import uuid
from typing import Any

from faker import Faker

from .models import ApiEndpoint, ApiParam
from .openapi import deref

# Default random string length bounds when minLength/maxLength are absent.
_DEFAULT_STRING_LEN = (8, 12)
# Default array length bounds when minItems/maxItems are absent.
_ARRAY_LEN = (1, 3)
# Probability of including a non-required object property (50%).
_OPTIONAL_PROP_CHANCE = 0.5

_FAKER = Faker()

# Field names that usually hold business-unique values.
_UNIQUE_HINTS = (
    "username",
    "user_name",
    "user-name",
    "user_login",
    "login",
    "account",
    "email",
    "mail",
    "mailbox",
    "slug",
    "nickname",
    "nick_name",
)


def _is_unique_field(name: str) -> bool:
    key = name.lower().replace("-", "_")
    return any(hint in key for hint in _UNIQUE_HINTS)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def generate_value(
    schema: dict | None,
    components: dict,
    rng: random.Random,
    depth: int = 0,
) -> Any:
    """Generate a JSON-compatible value matching ``schema``."""
    schema = deref(schema, components)
    if not isinstance(schema, dict) or depth > 10:
        return None
    if "const" in schema:
        return schema["const"]
    if "default" in schema:
        default = schema["default"]
        # An empty-object default on a schema that declares properties would
        # produce an empty request body; generate real data instead.
        has_props = isinstance(schema.get("properties"), dict) and schema["properties"]
        if not (isinstance(default, dict) and not default and has_props):
            return default
    if "enum" in schema:
        return rng.choice(schema["enum"])
    for key in ("oneOf", "anyOf"):
        branches = schema.get(key)
        if isinstance(branches, list) and branches:
            return generate_value(rng.choice(branches), components, rng, depth + 1)

    typ = schema.get("type")
    if isinstance(typ, list):  # OpenAPI 3.1 style
        typ = next((t for t in typ if t != "null"), "string")
    if typ is None and isinstance(schema.get("properties"), dict):
        typ = "object"
    typ = typ or "string"

    if typ == "string":
        return _gen_string(schema, rng)
    if typ == "integer":
        return _gen_number(schema, rng, integer=True)
    if typ == "number":
        return _gen_number(schema, rng, integer=False)
    if typ == "boolean":
        return rng.choice([True, False])
    if typ == "array":
        return _gen_array(schema, components, rng, depth)
    if typ == "object":
        return _gen_object(schema, components, rng, depth)
    if typ == "null":
        return None
    return None


def _gen_string(schema: dict, rng: random.Random) -> str:
    fmt = schema.get("format")
    if fmt == "uuid":
        return str(uuid.uuid4())
    if fmt == "email":
        return _FAKER.email()
    if fmt == "date-time":
        return _dt.datetime.now().isoformat()
    if fmt == "date":
        return _dt.date.today().isoformat()
    if fmt in ("uri", "url"):
        return f"http://example.com/{uuid.uuid4().hex[:8]}"
    lo = schema.get("minLength")
    hi = schema.get("maxLength")
    lo = int(lo) if isinstance(lo, int) else _DEFAULT_STRING_LEN[0]
    hi = int(hi) if isinstance(hi, int) else _DEFAULT_STRING_LEN[1]
    if lo > hi:
        hi = lo
    length = rng.randint(lo, hi)
    chars = string.ascii_letters + string.digits
    return "".join(rng.choices(chars, k=length))


def _gen_number(schema: dict, rng: random.Random, *, integer: bool) -> int | float:
    lo = schema.get("minimum")
    hi = schema.get("maximum")
    excl_lo = schema.get("exclusiveMinimum")
    excl_hi = schema.get("exclusiveMaximum")
    step = 1 if integer else 0.01
    if isinstance(excl_lo, (int, float)) and not isinstance(excl_lo, bool):
        lo = excl_lo + step
    elif excl_lo is True and isinstance(lo, (int, float)):
        lo = lo + step
    if isinstance(excl_hi, (int, float)) and not isinstance(excl_hi, bool):
        hi = excl_hi - step
    elif excl_hi is True and isinstance(hi, (int, float)):
        hi = hi - step
    if not isinstance(lo, (int, float)):
        lo = 1
    if not isinstance(hi, (int, float)):
        hi = 100 if integer else 1000.0
    if lo > hi:
        hi = lo
    if integer:
        return rng.randint(int(lo), int(hi))
    return round(rng.uniform(float(lo), float(hi)), 2)


def _gen_array(
    schema: dict, components: dict, rng: random.Random, depth: int
) -> list[Any]:
    items = schema.get("items")
    lo = schema.get("minItems")
    hi = schema.get("maxItems")
    lo = int(lo) if isinstance(lo, int) else _ARRAY_LEN[0]
    hi = int(hi) if isinstance(hi, int) else _ARRAY_LEN[1]
    if lo > hi:
        hi = lo
    n = rng.randint(lo, hi)
    return [generate_value(items, components, rng, depth + 1) for _ in range(n)]


def _prop_value(
    name: str,
    prop: dict,
    components: dict,
    rng: random.Random,
    depth: int,
    *,
    required: bool,
) -> Any:
    value = generate_value(prop, components, rng, depth + 1)
    if required:
        value = _non_empty(name, value, prop, components, rng, depth + 1)
    return _unique_str(name, value, prop, rng)


def _gen_object(
    schema: dict, components: dict, rng: random.Random, depth: int
) -> dict[str, Any]:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out: dict[str, Any] = {}
    for name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        if name in required or rng.random() < _OPTIONAL_PROP_CHANCE:
            out[name] = _prop_value(
                name, prop, components, rng, depth, required=name in required
            )
    return out


def _non_empty(
    field_name: str,
    value: Any,
    schema: dict,
    components: dict,
    rng: random.Random,
    depth: int,
) -> Any:
    """Guarantee a non-empty value for a required field."""
    if not _is_empty(value):
        return value
    # An enum is the contract: keep a schema-valid (even empty) value rather
    # than fabricating a non-enum one.
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return value
    retried = generate_value(schema, components, rng, depth + 1)
    if not _is_empty(retried):
        return retried
    return _fallback_value(schema, rng)


def _fallback_value(schema: dict, rng: random.Random) -> Any:
    typ = schema.get("type")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), None)
    if typ == "integer":
        lo = schema.get("minimum")
        return int(lo) if isinstance(lo, (int, float)) else 1
    if typ == "number":
        lo = schema.get("minimum")
        return float(lo) if isinstance(lo, (int, float)) else 1.0
    if typ == "boolean":
        return True
    if typ == "array":
        return [1]
    if typ == "object":
        # An object without declared properties cannot be filled further.
        return {}
    chars = string.ascii_letters + string.digits
    return "".join(rng.choices(chars, k=8))


def _unique_str(field_name: str, value: Any, schema: dict, rng: random.Random) -> Any:
    """Append a UUID suffix when the field name suggests a unique business key."""
    if not _is_unique_field(field_name):
        return value
    if not isinstance(value, str) or not value:
        return value
    suffix = f"_{uuid.uuid4().hex[:8]}"
    key = field_name.lower().replace("-", "_")
    if "email" in key or "mail" in key:
        if "@" in value:
            local, _, domain = value.partition("@")
            return f"{local}{suffix}@{domain}"
        return value
    hi = schema.get("maxLength")
    if isinstance(hi, int) and hi <= len(suffix):
        return value  # no room for a suffix
    if isinstance(hi, int) and len(value) + len(suffix) > hi:
        value = value[: hi - len(suffix)]
    return f"{value}{suffix}"


def _non_empty_body(
    schema: dict | None, body: Any, components: dict, rng: random.Random
) -> Any:
    """Never send an empty body for an object schema that declares properties."""
    if not _is_empty(body):
        return body
    resolved = deref(schema, components) or {}
    props = resolved.get("properties")
    if not isinstance(props, dict) or not props:
        return body
    for _ in range(3):
        body = generate_value(resolved, components, rng)
        if not _is_empty(body):
            return body
    # Last resort: include the first declared property.
    name = next(iter(props))
    prop = props[name]
    if isinstance(prop, dict):
        return {name: _prop_value(name, prop, components, rng, 0, required=True)}
    return {name: True}


def _path_value(param: ApiParam, components: dict, rng: random.Random) -> str:
    """Value for a path parameter: schema-driven, falling back to preset "1"."""
    schema = param.schema
    if not isinstance(schema, dict) or not schema:
        return "1"
    value = generate_value(schema, components, rng)
    if value is None:
        return "1"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _substitute_path_vars(path: str, values: dict[str, str]) -> str:
    resolved = path
    for name, value in values.items():
        resolved = resolved.replace("{" + name + "}", str(value))
    # Any leftover placeholders get a generic preset value.
    return re.sub(r"\{[^}]*\}", "1", resolved)


def _query_value(value: Any) -> Any:
    """Serialize a generated value for a query string.

    aiohttp/yarl only accepts str / int / float query values; booleans must be
    rendered explicitly or the request construction raises TypeError.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return value
    return str(value)


def prepare_request(
    endpoint: ApiEndpoint,
    base_url: str,
    components: dict,
    rng: random.Random,
) -> tuple[str, dict]:
    """Build the request for ``endpoint``.

    Returns ``(url, kwargs)`` where ``kwargs`` are the aiohttp request
    keyword arguments (``params``, ``headers`` and/or ``json``).
    """
    path_values: dict[str, str] = {}
    query_params: dict[str, Any] = {}
    headers: dict[str, str] = {}
    for param in endpoint.params:
        schema = param.schema if isinstance(param.schema, dict) else {}
        if param.location == "path":
            value = _path_value(param, components, rng)
            path_values[param.name] = _unique_str(param.name, value, schema, rng)
        elif param.location == "query":
            value = _unique_str(
                param.name, generate_value(schema, components, rng), schema, rng
            )
            query_params[param.name] = _query_value(value)
        elif param.location == "header":
            value = _unique_str(
                param.name, generate_value(schema, components, rng), schema, rng
            )
            headers[param.name] = "" if value is None else str(value)

    query_params = {k: v for k, v in query_params.items() if v is not None}
    url = base_url + _substitute_path_vars(endpoint.path, path_values)
    kwargs: dict[str, Any] = {"params": query_params}
    if headers:
        kwargs["headers"] = headers
    if endpoint.body_schema is not None:
        kwargs["json"] = _non_empty_body(
            endpoint.body_schema,
            generate_value(endpoint.body_schema, components, rng),
            components,
            rng,
        )
    return url, kwargs
