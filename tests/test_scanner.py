"""Tests for the Java Controller scanner."""

from perfscanner.scanner import JavaScanner, _join_path, _substitute_path_vars

BASE = "http://localhost:8080"


def test_join_path():
    assert _join_path("/api", "/users") == "/api/users"
    assert _join_path("/api", "") == "/api"
    assert _join_path("", "/users") == "/users"
    assert _join_path("", "") == "/"
    assert _join_path("/api/users", "/{id}") == "/api/users/{id}"


def test_substitute_path_vars():
    assert _substitute_path_vars("/users/{id}", {"id": "1"}) == "/users/1"
    assert _substitute_path_vars("/users/{id}/orders/{oid}", {"id": "5"}) == "/users/5/orders/1"
    assert _substitute_path_vars("/users/{name}", {}) == "/users/1"


def test_scan_extracts_endpoints(sample_java_project):
    endpoints = JavaScanner(BASE).scan(sample_java_project)

    # GET /api/users/{id}
    # POST /api/users
    # GET /api/users/search
    # DELETE /api/users/{id}/a
    # DELETE /api/users/{id}/b
    assert len(endpoints) == 5

    paths = {e.path for e in endpoints}
    assert "/api/users/{id}" in paths
    assert "/api/users" in paths
    assert "/api/users/search" in paths
    assert "/api/users/{id}/a" in paths
    assert "/api/users/{id}/b" in paths


def test_scan_path_variable_resolution(sample_java_project):
    endpoints = JavaScanner(BASE).scan(sample_java_project)
    get_user = next(e for e in endpoints if e.method_name == "getUser")
    assert get_user.path == "/api/users/{id}"
    assert get_user.resolved_path == "/api/users/1"
    assert get_user.full_url == "http://localhost:8080/api/users/1"
    assert get_user.http_method == "GET"


def test_scan_skips_non_controllers(sample_java_project):
    endpoints = JavaScanner(BASE).scan(sample_java_project)
    assert all("/should-not-scan" not in e.path for e in endpoints)


def test_scan_skips_unparseable_files(tmp_path):
    (tmp_path / "Modern.java").write_text(
        "public record Modern(int id) {}\n", encoding="utf-8"
    )
    endpoints = JavaScanner(BASE).scan(tmp_path)
    assert endpoints == []


def test_scan_http_methods(tmp_path):
    (tmp_path / "Methods.java").write_text(
        """\
@RestController
public class Methods {
    @GetMapping("/g") public void g() {}
    @PostMapping("/p") public void p() {}
    @PutMapping("/pu") public void pu() {}
    @DeleteMapping("/d") public void d() {}
    @PatchMapping("/pa") public void pa() {}
}
""",
        encoding="utf-8",
    )
    endpoints = JavaScanner(BASE).scan(tmp_path)
    methods = {e.http_method for e in endpoints}
    assert methods == {"GET", "POST", "PUT", "DELETE", "PATCH"}


def test_scan_string_path_variable_placeholder(tmp_path):
    (tmp_path / "Str.java").write_text(
        """\
@RestController
@RequestMapping("/names")
public class Str {
    @GetMapping("/{name}")
    public String get(@PathVariable("name") String name) { return name; }
}
""",
        encoding="utf-8",
    )
    endpoints = JavaScanner(BASE).scan(tmp_path)
    assert endpoints[0].resolved_path == "/names/test"
