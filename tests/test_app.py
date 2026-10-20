"""Run: python tests/test_app.py   (uses a throwaway SQLite file)"""
import os, sys, tempfile
os.environ.pop("DATABASE_URL", None); os.environ.pop("POSTGRES_URL", None)
os.environ["SEGRO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app as A, manage as M

A.init_db()
db = A.DB()
keys = {c: M.add_org(db, c, c, t) for c, t in (("COL", "college"), ("PRV", "private"), ("GOV", "government"))}
for c in keys:
    M.add_bus(db, c, "12", 2); M.add_bus(db, c, "7", 5)
    M.add_user(db, c, "ADM", "Admin", "adminpass1", "admin")
    M.add_user(db, c, "STF", "Staff", "staffpass1", "staff")
    for i in (1, 2, 3):
        M.add_user(db, c, f"R{i}", f"Rider{i}", "riderpass1")
        M.card(db, c, f"R{i}", f"AA00{c}{i}")
M.assign(db, "COL", "R1", "12"); M.assign(db, "COL", "R2", "12"); M.assign(db, "COL", "R3", "7")
M.assign(db, "PRV", "R1", "12")
db.close()

n = 0
def check(name, cond):
    global n; n += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)

c = A.app.test_client()
H = lambda org: {"X-Device-Key": keys[org]}
scan = lambda org, uid, bus="12", **k: c.post("/api/scan", json={"uid": uid, "bus": bus, **k}, headers=H(org)).get_json()["result"]

check("health", c.get("/api/health").get_json()["ok"])
check("ping ok", c.get("/api/ping", headers=H("COL")).status_code == 200)
check("ping bad key", c.get("/api/ping", headers={"X-Device-Key": "x"}).status_code == 401)
check("scan bad key", c.post("/api/scan", json={"uid": "1", "bus": "12"}).status_code == 401)
check("college ok", scan("COL", "AA00COL1") == "OK")
check("college duplicate", scan("COL", "AA00COL1") == "DUPLICATE")
check("college wrong bus", scan("COL", "AA00COL3", "12") == "WRONG_BUS")
check("unknown bus", scan("COL", "AA00COL3", "99") == "UNKNOWN_BUS")
check("unknown card", scan("COL", "FFFF") == "INVALID_ID")
check("last seat taken", scan("COL", "AA00COL2") == "OK")
check("cross-org card rejected", scan("PRV", "AA00COL1") == "INVALID_ID")
check("private ok", scan("PRV", "AA00PRV1") == "OK")
check("private shift is separate trip", scan("PRV", "AA00PRV1", shift="NIGHT") == "OK")
check("bad shift rejected", c.post("/api/scan", json={"uid": "AA00PRV1", "bus": "12", "shift": "a b!"}, headers=H("PRV")).status_code == 400)
check("gov open ridership", scan("GOV", "AA00GOV1") == "OK")
check("gov second rider", scan("GOV", "AA00GOV2") == "OK")
check("gov bus full", scan("GOV", "AA00GOV3") == "FULL")
check("gov other bus ok", scan("GOV", "AA00GOV3", "7") == "OK")

s = A.app.test_client()
login = lambda cl, p, org, lid, pw: cl.post("/api/login", json={"portal": p, "org_code": org, "login_id": lid, "password": pw})
check("wrong portal rejected", login(s, "private", "COL", "ADM", "adminpass1").status_code == 401)
check("admin login", login(s, "college", "COL", "ADM", "adminpass1").status_code == 200)
d = s.get("/api/dashboard").get_json()
check("dashboard counts", {b["bus_number"]: b["boarded"] for b in d["buses"]}["12"] == 2 and d["scanner_last_seen"])
check("add bus", s.post("/api/admin/buses", json={"bus_number": "9", "capacity": 40}).status_code == 201)
check("bad capacity", s.post("/api/admin/buses", json={"bus_number": "9", "capacity": 0}).status_code == 400)
r = s.post("/api/admin/riders/import", json={"csv": "login_id,name,bus\nN1,New One,9\nN2,Bad,77\n"}).get_json()
check("import", len(r["created"]) == 1 and len(r["errors"]) == 1)
check("assign", s.post("/api/admin/riders/assign", json={"login_id": "N1", "bus": "7"}).status_code == 200)
check("enrol start", s.post("/api/admin/riders/enrol", json={"login_id": "N1"}).status_code == 200)
check("enrol via scan", scan("COL", "NEWCARD01") == "ENROLLED")
check("enrolled card boards", scan("COL", "NEWCARD01", "7") == "OK")
check("cross-org enrol not possible", scan("PRV", "NEWCARD01") == "INVALID_ID")
check("analytics aggregated", "login_id" not in str(s.get("/api/admin/analytics").get_json()))
check("riders list", any(x["login_id"] == "N1" and x["card_linked"] for x in s.get("/api/admin/riders").get_json()))

rd = A.app.test_client()
check("rider login", login(rd, "college", "COL", "R1", "riderpass1").status_code == 200)
me = rd.get("/api/me").get_json()
check("rider me", me["bus"]["boarded_this_trip"] and me["bus"]["seats_left"] == 0)
check("rider forbidden admin", rd.get("/api/admin/riders").status_code == 403)
check("rider forbidden dashboard", rd.get("/api/dashboard").status_code == 403)
check("anonymous blocked", A.app.test_client().get("/api/me").status_code == 401)
rd.post("/api/logout"); check("logout", rd.get("/api/me").status_code == 401)

check("signup", c.post("/api/register", json={"portal": "college", "org_code": "COL", "login_id": "S1", "name": "Sam", "password": "password1"}).status_code == 201)
check("signup duplicate", c.post("/api/register", json={"portal": "college", "org_code": "COL", "login_id": "S1", "name": "Sam", "password": "password1"}).status_code == 409)
check("signup short pw", c.post("/api/register", json={"portal": "college", "org_code": "COL", "login_id": "S2", "name": "Sam", "password": "short"}).status_code == 400)
check("gov signup closed", c.post("/api/register", json={"portal": "government", "org_code": "GOV", "login_id": "S1", "name": "Sam", "password": "password1"}).status_code == 403)

lk = A.app.test_client()
for _ in range(5): login(lk, "college", "COL", "R3", "wrong")
check("lockout after 5 failures", login(lk, "college", "COL", "R3", "riderpass1").status_code == 429)
os.environ["SETUP_TOKEN"] = "tok"
check("setup wrong token", c.post("/api/setup", json={}, headers={"X-Setup-Token": "no"}).status_code == 403)
r = c.post("/api/setup", json={"code": "new1", "name": "New Org", "org_type": "private", "admin_id": "boss", "admin_password": "bosspass12"}, headers={"X-Setup-Token": "tok"})
check("setup creates org", r.status_code == 201 and len(r.get_json()["device_key"]) == 32)
check("setup admin can log in", login(A.app.test_client(), "private", "NEW1", "boss", "bosspass12").status_code == 200)
check("home page served", c.get("/").status_code == 200)
print(f"\nALL {n} CHECKS PASSED")
