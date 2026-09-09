"""CRUD + validation + global-rule protection for /api/categorization-rules."""

import pytest

VALID = {"match_type": "contains", "pattern": "netflix", "category_id": 6, "priority": 50}


class FakeRulesDB:
    def __init__(self):
        # id -> student_id (None => global)
        self.rules = {1: 1, 2: None}
        self._next_id = 3
        self.category_ok = True

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False,
                      commit=False, raise_on_error=False):
        s = " ".join(query.split()).lower()
        if s.startswith("select id from categories where id = %s and (student_id"):
            return {"id": params[0]} if self.category_ok else None
        if s.startswith("select id, student_id from categorization_rules where id = %s"):
            rid = params[0]
            if rid not in self.rules:
                return None
            return {"id": rid, "student_id": self.rules[rid]}
        if s.startswith("insert into categorization_rules"):
            rid = self._next_id
            self._next_id += 1
            self.rules[rid] = params[0]
            return rid
        if s.startswith("update categorization_rules set"):
            return 1
        if s.startswith("delete from categorization_rules"):
            return 1
        if s.startswith("select id, student_id, match_type, pattern, category_id, priority, created_at"):
            if fetch_all:
                return [{"id": 1, "student_id": 1, "match_type": "contains",
                         "pattern": "x", "category_id": 6, "priority": 50, "created_at": None},
                        {"id": 2, "student_id": None, "match_type": "equals",
                         "pattern": "y", "category_id": 6, "priority": 10, "created_at": None}]
            return {"id": params[0], "student_id": 1, "match_type": "contains",
                    "pattern": "netflix", "category_id": 6, "priority": 50, "created_at": None}
        raise AssertionError(f"unexpected query: {s}")


@pytest.fixture
def gdb(monkeypatch):
    fake = FakeRulesDB()
    monkeypatch.setattr("routes.categorization_rules.execute_query", fake.execute_query)
    return fake


def test_create_rule_ok(client, auth_headers, gdb):
    resp = client.post("/api/categorization-rules", json=VALID, headers=auth_headers)
    assert resp.status_code == 201


def test_create_rejects_bad_match_type(client, auth_headers, gdb):
    body = dict(VALID); body["match_type"] = "regex"
    assert client.post("/api/categorization-rules", json=body, headers=auth_headers).status_code == 400


def test_create_rejects_empty_pattern(client, auth_headers, gdb):
    body = dict(VALID); body["pattern"] = "   "
    assert client.post("/api/categorization-rules", json=body, headers=auth_headers).status_code == 400


def test_create_rejects_unknown_category(client, auth_headers, gdb):
    gdb.category_ok = False
    assert client.post("/api/categorization-rules", json=VALID, headers=auth_headers).status_code == 400


def test_list_returns_global_and_own(client, auth_headers, gdb):
    resp = client.get("/api/categorization-rules", headers=auth_headers)
    assert resp.status_code == 200
    assert {r["id"] for r in resp.get_json()} == {1, 2}


def test_cannot_update_global_rule(client, auth_headers, gdb):
    resp = client.put("/api/categorization-rules/2", json={"pattern": "z"}, headers=auth_headers)
    assert resp.status_code == 403


def test_cannot_delete_global_rule(client, auth_headers, gdb):
    resp = client.delete("/api/categorization-rules/2", headers=auth_headers)
    assert resp.status_code == 403


def test_update_own_rule_ok(client, auth_headers, gdb):
    resp = client.put("/api/categorization-rules/1", json={"priority": 5}, headers=auth_headers)
    assert resp.status_code == 200


def test_delete_own_rule_ok(client, auth_headers, gdb):
    resp = client.delete("/api/categorization-rules/1", headers=auth_headers)
    assert resp.status_code == 200


def test_update_missing_rule_is_404(client, auth_headers, gdb):
    resp = client.put("/api/categorization-rules/999", json={"priority": 5}, headers=auth_headers)
    assert resp.status_code == 404


def test_rules_require_auth(client):
    assert client.get("/api/categorization-rules").status_code == 401
