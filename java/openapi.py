"""Fetch and parse an OpenAPI (Swagger) 3.x document into endpoints."""

from __future__ import annotations

import logging

import aiohttp

from .models import ApiEndpoint, ApiParam

logger = logging.getLogger("java.openapi")

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


class OpenApiError(Exception):
    """Raised when the OpenAPI document is invalid or cannot be fetched."""


def _merge_all_of(resolved: dict, sub: dict) -> None:
    """Merge one allOf branch into the accumulated result.

    ``properties`` and ``required`` accumulate across branches instead of being
    overwritten (a plain dict-update would drop the first branch's fields).
    """
    for key, value in sub.items():
        if key in ("title", "description"):
            continue
        if key == "properties" and isinstance(value, dict) and isinstance(
            resolved.get("properties"), dict
        ):
            resolved["properties"] = {**resolved["properties"], **value}
        elif key == "required" and isinstance(value, list) and isinstance(
            resolved.get("required"), list
        ):
            resolved["required"] = list(dict.fromkeys(resolved["required"] + value))
        else:
            resolved[key] = value


def deref(schema: dict | None, components: dict, depth: int = 0) -> dict | None:
    """Resolve local ``$ref`` pointers against ``components``.

    Only local references (``#/components/...``) are supported. ``allOf``
    branches are merged; nested references inside properties are left intact
    and resolved lazily by the data generator (avoids infinite recursion on
    self-referential schemas).
    """
    if not isinstance(schema, dict) or depth > 20:
        return schema
    ref = schema.get("$ref")
    if not ref:
        merged = dict(schema)
        subs = merged.get("allOf")
        if isinstance(subs, list):
            resolved: dict = {}
            for sub in subs:
                _merge_all_of(resolved, deref(sub, components, depth + 1) or {})
            merged.update(resolved)
            merged.pop("allOf", None)
        return merged
    if not isinstance(ref, str) or not ref.startswith("#/components/"):
        raise OpenApiError(f"仅支持本地 $ref: {ref!r}")
    # ref = "#/components/schemas/User" -> parts ["schemas", "User"],
    # since `components` already IS the components section.
    parts = ref.split("/")[2:]
    target = components
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict) and part in target:
            target = target[part]
        else:
            raise OpenApiError(f"无法解析 $ref: {ref!r}")
    if isinstance(target, dict) and target.get("$ref"):
        return deref(target, components, depth + 1)
    return deref(target, components, depth + 1)


def _param_from_dict(pd: dict, components: dict) -> ApiParam | None:
    pd = deref(pd, components) or {}
    name = pd.get("name")
    location = pd.get("in")
    if not name or location not in ("query", "path", "header"):
        return None
    schema = deref(pd.get("schema"), components) if isinstance(pd.get("schema"), dict) else None
    return ApiParam(
        name=str(name),
        location=location,
        required=bool(pd.get("required", False)),
        schema=schema,
    )


def _body_schema(operation: dict, components: dict) -> dict | None:
    """Extract the application/json request body schema, if any."""
    rb = operation.get("requestBody")
    if not isinstance(rb, dict):
        return None
    rb = deref(rb, components) or {}
    content = rb.get("content")
    if not isinstance(content, dict):
        return None
    for ctype, media in content.items():
        if not isinstance(ctype, str):
            continue
        if ctype == "application/json" or ctype.endswith("+json"):
            if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                return deref(media["schema"], components)
            return None
    return None


def parse_spec(spec: dict, base_url: str | None = None) -> tuple[str, list[ApiEndpoint]]:
    """Parse a loaded OpenAPI document.

    Returns ``(base_url, endpoints)``. The base URL comes from ``--base-url``
    (when given) or the first entry of ``servers``.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise OpenApiError("无效的 OpenAPI 文档: 缺少 paths")

    if base_url is None:
        servers = spec.get("servers") or []
        base_url = servers[0].get("url") if servers and isinstance(servers[0], dict) else None
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        raise OpenApiError("无法确定 base URL: 文档缺少 servers 且未提供 --base-url")

    components = spec.get("components") or {}
    if not isinstance(components, dict):
        components = {}

    endpoints: list[ApiEndpoint] = []
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            params: list[ApiParam] = []
            for pd in op.get("parameters") or []:
                if isinstance(pd, dict):
                    param = _param_from_dict(pd, components)
                    if param is not None:
                        params.append(param)
            endpoints.append(
                ApiEndpoint(
                    method=method.upper(),
                    path=str(path),
                    params=params,
                    body_schema=_body_schema(op, components),
                    operation_id=str(op.get("operationId", "")),
                    summary=str(op.get("summary", "")),
                )
            )
    return base_url, endpoints


async def fetch_spec(url: str, timeout: float = 10.0) -> dict:
    """Download and decode the OpenAPI document from ``url``."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status >= 400:
                    raise OpenApiError(f"获取 OpenAPI 文档失败: HTTP {resp.status}")
                try:
                    return await resp.json()
                except ValueError as exc:
                    raise OpenApiError("OpenAPI 文档不是合法的 JSON") from exc
    except aiohttp.ClientError as exc:
        raise OpenApiError(f"无法访问 OpenAPI 文档: {type(exc).__name__}: {exc}") from exc
