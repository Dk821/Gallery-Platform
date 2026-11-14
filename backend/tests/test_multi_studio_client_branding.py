"""A client opening the gallery link sees THEIR studio's logo, name and contact details - and nothing of any other studio."""

from tests.ms_helpers import fresh, make_client_album, make_studio

# "slug" is the studio name in the gallery link itself, so it is as public as the link.
BRAND_KEYS = {"name", "slug", "logo_url", "brand_color", "contact_email", "contact_phone"}


def _studio(db, name, logo, email, phone):
    s = make_studio(db, name)
    s.logo_url, s.brand_color, s.contact_email, s.contact_phone = logo, "#112233", email, phone
    db.commit()
    return s


def test_gallery_link_shows_the_studio_that_shared_it(client, db_session):
    sam = _studio(db_session, "Studio Sam", "/api/studios/%d/logo?v=abc123", "hello@sam.dev", "+63 900 111")
    sam.logo_url = sam.logo_url % sam.id
    other = _studio(db_session, "Other Studio", None, "x@other.dev", None)
    db_session.commit()
    c_sam, _ = make_client_album(db_session, sam)
    c_other, _ = make_client_album(db_session, other)

    # before sign-in (public check)
    b = client.get(f"/api/client/gallery/access/{c_sam.client_uuid}").json()["data"]["studio"]
    assert set(b) == BRAND_KEYS  # exactly the public face - no quota, usage, status, ids
    assert b["name"] == "Studio Sam" and b["logo_url"] == f"/api/studios/{sam.id}/logo?v=abc123"
    assert b["contact_email"] == "hello@sam.dev" and b["contact_phone"] == "+63 900 111" and b["brand_color"] == "#112233"
    b2 = client.get(f"/api/client/gallery/access/{c_other.client_uuid}").json()["data"]["studio"]
    assert b2["name"] == "Other Studio" and b2["logo_url"] is None

    # after sign-in
    assert client.post("/api/auth/client/login", json={"gallery_id": c_sam.client_uuid, "password": "client-pass-1"}).status_code == 200
    g = client.get("/api/client/gallery").json()["data"]
    assert set(g["studio"]) == BRAND_KEYS and g["studio"]["name"] == "Studio Sam"
    assert "Other Studio" not in str(g)


def test_branding_follows_edits_and_survives_suspension(client, db_session):
    s = _studio(db_session, "Before", None, None, None)
    c, _ = make_client_album(db_session, s)
    s.name = "After Rename"
    s.status = "suspended"
    db_session.commit()
    data = client.get(f"/api/client/gallery/access/{c.client_uuid}").json()["data"]
    assert data["studio"]["name"] == "After Rename"  # live value, not a copy


def test_unmapped_legacy_client_has_no_studio_branding(client, db_session):
    s = make_studio(db_session, "Elsewhere")
    c, _ = make_client_album(db_session, s)
    c.studio_id = None
    db_session.commit()
    assert client.get(f"/api/client/gallery/access/{c.client_uuid}").json()["data"]["studio"] is None
