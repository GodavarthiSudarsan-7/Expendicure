"""Category scoping: GET returns global + own; writes only touch own rows."""

import pytest


class FakeCategoriesDB:
    def __init__(self):
        # id -> student_id (None => global)
        self.categories = {1: None, 2: None, 50: 1, 60: 2}
        self._next_id = 100
        self.name_clash = False
        self.in_use = False

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False,
                      commit=False, raise_on_error=False):
        s = " ".join(query.split()).lower()
        if s.startswith("select id, name, is_default, student_id, created_at from categories where student_id"):
            return [
                {"id": 1, "name": "Food", "is_default": 1, "student_id": None, "created_at": None},
                {"id": 50, "name": "Coffee", "is_default": 0, "student_id": 1, "created_at": None},
            ]
        if s.startswith("select id from categories where name = %s and (student_id"):
            return {"id": 999} if self.name_clash else None
        if s.startswith("select id from categories where name = %s and id != %s"):
            return {"id": 999} if self.name_clash else None
        if s.startswith("select id, student_id from categories where id = %s"):
            cid = params[0]
            if cid not in self.categories:
                return None
            return {"id": cid, "student_id": self.categories[cid]}
        if s.startswith("select id, student_id, is_default from categories where id = %s"):
            cid = params[0]
            if cid not in self.categories:
                return None
            return {"id": cid, "student_id": self.categories[cid], "is_default": 0}
        if s.startswith("insert into categories"):
            cid = self._next_id
            self._next_id += 1
            self.categories[cid] = params[2]
            return cid
        if s.startswith("update categories set name"):
            return 1
        if s.startswith("delete from categories"):
            return 1
        if s.startswith("select id, name, is_default, student_id, created_at from categories where id = %s"):
            cid = params[0]
            return {"id": cid, "name": "New", "is_default": 0,
                    "student_id": self.categories.get(cid), "created_at": None}
        if s.startswith("select count(*) as count from transactions"):
            return {"count": 1 if self.in_use else 0}
        if s.startswith("select count(*) as count from budgets"):
            return {"count": 0}
        raise AssertionError(f"unexpected query: {s}")


@pytest.fixture
def cdb(monkeypatch):
    fake = FakeCategoriesDB()
    monkeypatch.setattr("routes.categories.execute_query", fake.execute_query)
    return fake


def test_get_returns_global_and_own(client, auth_headers, cdb):
    resp = client.get("/api/categories/", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.get_json()
    assert any(r["student_id"] is None for r in rows)   # a global
    assert any(r["student_id"] == 1 for r in rows)      # own


def test_post_scopes_new_category_to_caller(client, auth_headers, cdb):
    resp = client.post("/api/categories/", json={"name": "Gym"}, headers=auth_headers)
    assert resp.status_code == 201
    # the INSERT recorded student_id = 1 (FAKE_STUDENT id)
    new_ids = [cid for cid, sid in cdb.categories.items() if cid >= 100]
    assert new_ids and cdb.categories[new_ids[0]] == 1


def test_post_duplicate_name_is_409(client, auth_headers, cdb):
    cdb.name_clash = True
    resp = client.post("/api/categories/", json={"name": "Food"}, headers=auth_headers)
    assert resp.status_code == 409


def test_cannot_edit_global_category(client, auth_headers, cdb):
    resp = client.put("/api/categories/1", json={"name": "Grub"}, headers=auth_headers)
    assert resp.status_code == 403


def test_cannot_edit_other_students_category(client, auth_headers, cdb):
    resp = client.put("/api/categories/60", json={"name": "Nope"}, headers=auth_headers)
    assert resp.status_code == 403


def test_can_edit_own_category(client, auth_headers, cdb):
    resp = client.put("/api/categories/50", json={"name": "Espresso"}, headers=auth_headers)
    assert resp.status_code == 200


def test_cannot_delete_global_category(client, auth_headers, cdb):
    resp = client.delete("/api/categories/1", headers=auth_headers)
    assert resp.status_code == 403


def test_can_delete_own_unused_category(client, auth_headers, cdb):
    resp = client.delete("/api/categories/50", headers=auth_headers)
    assert resp.status_code == 200


def test_delete_own_category_in_use_is_400(client, auth_headers, cdb):
    cdb.in_use = True
    resp = client.delete("/api/categories/50", headers=auth_headers)
    assert resp.status_code == 400
