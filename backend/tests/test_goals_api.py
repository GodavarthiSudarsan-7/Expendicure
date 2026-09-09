"""Phase 13 — CRUD + validation + ownership for /api/goals. DB stubbed."""

import pytest

GOAL = {
    "name": "Laptop",
    "target_amount": "50000.00",
    "current_amount": "30000.00",
    "monthly_contribution": "5000.00",
    "target_date": "2027-03-31",
}

_ROW = {
    "id": 1, "student_id": 1, "name": "Laptop", "target_amount": "50000.00",
    "current_amount": "30000.00", "monthly_contribution": "5000.00",
    "target_date": "2027-03-31", "status": "active",
    "created_at": None, "updated_at": None,
}


class FakeGoalsDB:
    def __init__(self):
        self._next_id = 1
        self.owned = True                 # does the row belong to the caller?
        self.owned_row = {"id": 1, "target_amount": "50000.00", "current_amount": "30000.00"}
        self.writes = []

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False,
                      commit=False, raise_on_error=False):
        s = " ".join(query.split()).lower()
        if s.startswith("select id, target_amount, current_amount from savings_goals where id = %s and student_id"):
            return dict(self.owned_row) if self.owned else None
        if s.startswith("insert into savings_goals"):
            self.writes.append(("insert", params))
            rid = self._next_id
            self._next_id += 1
            return rid
        if s.startswith("update savings_goals set"):
            self.writes.append(("update", params))
            return 1
        if s.startswith("delete from savings_goals"):
            self.writes.append(("delete", params))
            return 1
        if s.startswith("select id, student_id, name, target_amount"):
            if fetch_all:
                return [dict(_ROW)]
            return dict(_ROW)
        raise AssertionError(f"unexpected query: {s}")


@pytest.fixture
def gdb(monkeypatch):
    fake = FakeGoalsDB()
    monkeypatch.setattr("routes.goals.execute_query", fake.execute_query)
    return fake


# ------------------------------------------------------------------ create
def test_create_goal_ok(client, auth_headers, gdb):
    r = client.post("/api/goals", json=GOAL, headers=auth_headers)
    assert r.status_code == 201
    body = r.get_json()
    assert body["name"] == "Laptop" and body["target_amount"] == "50000.00"
    assert gdb.writes[0][0] == "insert"


def test_create_requires_auth(client, gdb):
    assert client.post("/api/goals", json=GOAL).status_code == 401


@pytest.mark.parametrize("patch", [
    {"name": ""},
    {"target_amount": "0"},
    {"target_amount": "-5"},
    {"target_amount": "abc"},
    {"current_amount": "-1"},
    {"monthly_contribution": "-10"},
    {"target_date": "31/03/2027"},
    {"target_date": "not-a-date"},
])
def test_create_validation_rejects_bad_fields(client, auth_headers, gdb, patch):
    payload = {**GOAL, **patch}
    r = client.post("/api/goals", json=payload, headers=auth_headers)
    assert r.status_code == 400


def test_create_rejects_overfunding(client, auth_headers, gdb):
    payload = {**GOAL, "current_amount": "60000.00"}  # > target 50000
    r = client.post("/api/goals", json=payload, headers=auth_headers)
    assert r.status_code == 400 and "exceed" in r.get_json()["error"]


def test_create_ignores_body_student_id(client, auth_headers, gdb):
    r = client.post("/api/goals", json={**GOAL, "student_id": 999}, headers=auth_headers)
    assert r.status_code == 201
    # the INSERT bound the authenticated id (1), not 999
    _, params = gdb.writes[0]
    assert params[0] == 1


# -------------------------------------------------------------------- read
def test_list_goals(client, auth_headers, gdb):
    r = client.get("/api/goals", headers=auth_headers)
    assert r.status_code == 200 and isinstance(r.get_json(), list)


def test_get_goal_ok(client, auth_headers, gdb):
    r = client.get("/api/goals/1", headers=auth_headers)
    assert r.status_code == 200 and r.get_json()["id"] == 1


def test_get_goal_not_owned_is_404(client, auth_headers, gdb):
    gdb.owned = False
    r = client.get("/api/goals/1", headers=auth_headers)
    assert r.status_code == 404


# ------------------------------------------------------------------ update
def test_update_goal_ok(client, auth_headers, gdb):
    r = client.put("/api/goals/1", json={"current_amount": "35000.00"}, headers=auth_headers)
    assert r.status_code == 200
    assert gdb.writes[-1][0] == "update"


def test_update_other_users_goal_is_404(client, auth_headers, gdb):
    gdb.owned = False
    r = client.put("/api/goals/1", json={"current_amount": "35000.00"}, headers=auth_headers)
    assert r.status_code == 404
    assert not gdb.writes                      # nothing was written


def test_update_rejects_overfunding_against_stored_target(client, auth_headers, gdb):
    r = client.put("/api/goals/1", json={"current_amount": "70000.00"}, headers=auth_headers)
    assert r.status_code == 400


def test_update_empty_body_is_400(client, auth_headers, gdb):
    r = client.put("/api/goals/1", json={}, headers=auth_headers)
    assert r.status_code == 400


# ------------------------------------------------------------------ delete
def test_delete_goal_ok(client, auth_headers, gdb):
    r = client.delete("/api/goals/1", headers=auth_headers)
    assert r.status_code == 200
    assert gdb.writes[-1][0] == "delete"


def test_archive_goal(client, auth_headers, gdb):
    r = client.delete("/api/goals/1?archive=1", headers=auth_headers)
    assert r.status_code == 200
    kind, params = gdb.writes[-1]
    assert kind == "update" and "archived" in params


def test_delete_other_users_goal_is_404(client, auth_headers, gdb):
    gdb.owned = False
    r = client.delete("/api/goals/1", headers=auth_headers)
    assert r.status_code == 404
    assert not gdb.writes
