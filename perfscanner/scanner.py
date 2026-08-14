"""Static analysis: scan a Java project and extract Controller endpoints."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import javalang

from .models import Endpoint

# Numeric-ish Java types whose @PathVariable placeholders become "1".
_NUMERIC_TYPES = {
    "int", "Integer", "long", "Long", "short", "Short", "byte", "Byte",
    "float", "Float", "double", "Double", "BigDecimal", "BigInteger",
}

# Method-level mapping annotations -> HTTP method.
_MAPPING_ANNOTATIONS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

_CONTROLLER_ANNOTATIONS = {"RestController", "Controller", "RequestMapping"}


def _annotation_name(annotation) -> str:
    return getattr(annotation, "name", "")


def _literal_value(value) -> str | None:
    if isinstance(value, javalang.tree.Literal):
        raw = value.value
        if isinstance(raw, str) and len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
            return raw[1:-1]
        return raw
    return None


def _extract_paths(annotation) -> list[str]:
    """Extract path string(s) from a Spring mapping annotation."""
    element = annotation.element
    paths: list[str] = []

    if element is None:
        return paths

    # Shorthand single value: @GetMapping("/x")
    value = _literal_value(element)
    if value is not None:
        paths.append(value)
        return paths

    # Shorthand array value: @DeleteMapping({"/a", "/b"})
    if isinstance(element, javalang.tree.ElementArrayValue):
        for v in element.values:
            vv = _literal_value(v)
            if vv is not None:
                paths.append(vv)
        return paths

    # Key/value pairs: @RequestMapping(value = "/x", method = ...)
    if isinstance(element, list):
        for pair in element:
            if not isinstance(pair, javalang.tree.ElementValuePair):
                continue
            if pair.name not in ("value", "path"):
                continue
            v = _literal_value(pair.value)
            if v is not None:
                paths.append(v)
            elif isinstance(pair.value, javalang.tree.ElementArrayValue):
                for item in pair.value.values:
                    vv = _literal_value(item)
                    if vv is not None:
                        paths.append(vv)

    return paths


def _http_method(annotation) -> str | None:
    name = _annotation_name(annotation)
    if name in _MAPPING_ANNOTATIONS:
        return _MAPPING_ANNOTATIONS[name]
    if name == "RequestMapping":
        element = annotation.element
        if isinstance(element, list):
            for pair in element:
                if (
                    isinstance(pair, javalang.tree.ElementValuePair)
                    and pair.name == "method"
                ):
                    if isinstance(pair.value, javalang.tree.MemberReference):
                        return pair.value.member.upper()
                    v = _literal_value(pair.value)
                    if v is not None:
                        return v.upper()
        return "GET"  # @RequestMapping defaults to GET
    return None


def _path_variable_name(param) -> str | None:
    """Return the @PathVariable name for a parameter, if any."""
    for annotation in param.annotations or []:
        if _annotation_name(annotation) == "PathVariable":
            v = _literal_value(annotation.element)
            return v if v is not None else param.name
    return None


def _placeholder_for(type_name: str) -> str:
    return "1" if type_name in _NUMERIC_TYPES else "test"


def _join_path(base: str, path: str) -> str:
    base = (base or "").strip("/")
    path = (path or "").strip("/")
    if base and path:
        return f"/{base}/{path}"
    if base:
        return f"/{base}"
    if path:
        return f"/{path}"
    return "/"


def _substitute_path_vars(path: str, var_names: dict[str, str]) -> str:
    """Replace {name} placeholders in a path template with sample values."""
    resolved = path
    for name, placeholder in var_names.items():
        resolved = resolved.replace("{" + name + "}", placeholder)
    # Any remaining unresolved placeholders get a generic value.
    resolved = re.sub(r"\{[^}]*\}", "1", resolved)
    return resolved


def _is_controller(node) -> bool:
    return any(_annotation_name(a) in _CONTROLLER_ANNOTATIONS for a in node.annotations or [])


class JavaScanner:
    """Scans Java source files and returns a list of :class:`Endpoint`."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def scan(self, project_path: str | Path, git_diff: str | None = None) -> list:
        """Scan a project directory (optionally restricted to a git diff)."""
        root = Path(project_path)
        java_files = list(root.rglob("*.java"))

        if git_diff:
            java_files = self._filter_by_git_diff(root, java_files, git_diff)

        endpoints: list = []
        for java_file in sorted(java_files):
            try:
                endpoints.extend(self._scan_file(root, java_file))
            except Exception:
                # Constraint: skip files that fail to parse (e.g. Java 17+ Records).
                continue
        return endpoints

    def _filter_by_git_diff(self, root: Path, java_files: list, diff_spec: str) -> list:
        """Restrict scanned files to those changed in the given git range."""
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=ACMR", diff_spec],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                return java_files  # fall back to full scan on git errors
            changed = {Path(line.strip()) for line in proc.stdout.splitlines() if line.strip()}
            return [f for f in java_files if f.relative_to(root) in changed]
        except (OSError, subprocess.SubprocessError):
            return java_files

    def _scan_file(self, root: Path, java_file: Path) -> list:
        source = java_file.read_text(encoding="utf-8", errors="replace")
        tree = javalang.parse.parse(source)

        endpoints: list = []
        rel_path = str(java_file.relative_to(root))

        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            if not _is_controller(node):
                continue

            class_paths = self._class_paths(node)

            for method in node.methods:
                endpoints.extend(
                    self._method_endpoints(node, method, class_paths, rel_path)
                )
        return endpoints

    def _class_paths(self, node) -> list[str]:
        """Class-level @RequestMapping path prefixes (empty string if none)."""
        paths: list[str] = []
        for annotation in node.annotations or []:
            if _annotation_name(annotation) == "RequestMapping":
                paths.extend(_extract_paths(annotation))
        if not paths:
            paths.append("")
        return paths

    def _method_endpoints(self, node, method, class_paths, rel_path) -> list:
        endpoints: list = []
        var_names: dict[str, str] = {}

        for param in method.parameters:
            name = _path_variable_name(param)
            if name:
                var_names[name] = _placeholder_for(param.type.name)

        params_list = [p.name for p in method.parameters]

        for annotation in method.annotations or []:
            http_method = _http_method(annotation)
            if http_method is None:
                continue

            method_paths = _extract_paths(annotation)
            if not method_paths:
                method_paths = [""]

            for class_path in class_paths:
                for method_path in method_paths:
                    full_path = _join_path(class_path, method_path)
                    resolved_path = _substitute_path_vars(full_path, var_names)
                    endpoints.append(
                        Endpoint(
                            http_method=http_method,
                            path=full_path,
                            resolved_path=resolved_path,
                            full_url=self.base_url + resolved_path,
                            class_name=node.name,
                            method_name=method.name,
                            source_file=rel_path,
                            source_line=getattr(getattr(method, "position", None), "line", 0) or 0,
                            params=list(params_list),
                        )
                    )
        return endpoints
