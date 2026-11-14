"""Client gallery links carry the studio name: /<studio slug>/gallery/<link id>."""

from app.models.studio import Studio
from app.services.studio_slug import RESERVED_SLUGS, build_studio_slug
from tests.ms_helpers import PASSWORD, login, make_admin, make_studio, make_super_admin


def _create_studio(client, name, email):
    r = client.post(
        "/api/super-admin/studios",
        json={"name": name, "admin_name": "Owner", "admin_email": email, "admin_password": PASSWORD},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


def test_slug_is_made_from_the_name_and_is_unique(client, db_session):
    make_super_admin(db_session)
    assert login(client, "root@platform.dev").status_code == 200
    a = _create_studio(client, "Acme Photo & Films!", "a1@x.dev")
    b = _create_studio(client, "Acme Photo & Films!", "a2@x.dev")
    slugs = {s.id: s.slug for s in db_session.query(Studio).all()}
    ids = [v for v in (a.get("id"), (a.get("studio") or {}).get("id")) if v]
    assert slugs[ids[0]] == "acme-photo-films"
    assert "acme-photo-films-2" in slugs.values()
    assert build_studio_slug(db_session, "") == "studio"
    for word in ("admin", "gallery", "api", "super-admin"):
        assert word in RESERVED_SLUGS
        assert build_studio_slug(db_session, word) == f"{word}-studio"


def test_renaming_keeps_the_slug_and_admin_links_use_it(client, db_session):
    studio = make_studio(db_session, "Blue Door")
    studio.slug = "blue-door"
    db_session.commit()
    make_admin(db_session, studio, "own@blue.dev")
    assert login(client, "own@blue.dev").status_code == 200
    created = client.post("/api/admin/clients", json={"client_name": "Mia & Leo"})
    assert created.status_code in (200, 201), created.text
    data = created.json()["data"]
    uuid = data["client_uuid"]
    assert data["gallery_url_path"] == f"/blue-door/gallery/{uuid}"
    # The public access check tells the page which slug is canonical.
    acc = client.get(f"/api/client/gallery/access/{uuid}").json()["data"]
    assert acc["studio"]["slug"] == "blue-door"
    listed = client.get("/api/admin/clients").json()["data"]["items"][0]
    assert listed["gallery_url_path"] == f"/blue-door/gallery/{uuid}"
    # A studio without a slug keeps the older link form.
    studio.slug = None
    db_session.commit()
    again = client.get("/api/admin/clients").json()["data"]["items"][0]
    assert again["gallery_url_path"] == f"/gallery/{uuid}"
