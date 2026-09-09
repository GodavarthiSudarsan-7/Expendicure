"""The students endpoints must not be reachable without a valid token."""


def test_list_students_requires_auth(client):
    resp = client.get("/api/students/")
    assert resp.status_code == 401


def test_get_student_requires_auth(client):
    resp = client.get("/api/students/1")
    assert resp.status_code == 401


def test_get_other_student_is_forbidden(client, auth_headers):
    # auth_headers resolves to student id 1; asking for id 2 must be 403.
    resp = client.get("/api/students/2", headers=auth_headers)
    assert resp.status_code == 403
