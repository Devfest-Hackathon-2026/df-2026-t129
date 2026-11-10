"""Run:  python3 tests/test_auth.py   (needs flask; functions_framework is stubbed)"""
import os, sys, types, importlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
ff = types.ModuleType("functions_framework"); ff.http = lambda f: f; sys.modules["functions_framework"] = ff
from flask import Flask, request
import accounts

os.environ["SPOTS_STORE"] = "memory"
demo_pw, user_pw = "DemoPass1234567", "UserPass7654321"
os.environ["AUTH_USERS"] = "~".join([
    "demo:%s:demo" % accounts.hash_password(demo_pw), "yamada:%s" % accounts.hash_password(user_pw), "broken-entry"])
os.environ["SESSION_SECRET"] = "s" * 40
import main; importlib.reload(main)

flask_app = Flask(__name__)
def _root(p=""): return main.app(request)
flask_app.add_url_rule("/", endpoint="root", defaults={"p": ""}, view_func=_root, methods=["GET", "POST"])
flask_app.add_url_rule("/<path:p>", endpoint="rest", view_func=_root, methods=["GET", "POST"])
fails = []
def check(name, cond):
    print(("OK   " if cond else "FAIL ") + name); cond or fails.append(name)
def new(): main._rate.clear(); return flask_app.test_client()
def login(c, u, p): return c.post("/login", data={"username": u, "password": p}, base_url="https://x.test")

c = new()
r = c.get("/"); check("anonymous GET / -> login page", r.status_code == 200 and b'name="username"' in r.data and b"TRAVEL_QUEST_CONFIG" not in r.data)
for path in ("/ai", "/places", "/spots"):
    check("anonymous POST %s -> 401" % path, c.post(path, json={}).status_code == 401)
check("wrong password -> 401", login(c, "demo", "nope").status_code == 401)
check("unknown user -> 401", login(c, "ghost", "x").status_code == 401)
check("empty fields -> 401", login(c, "", "").status_code == 401)
r = login(c, "Demo", demo_pw); check("login ok (case-insensitive name) -> 303", r.status_code == 303 and "tq_auth" in r.headers.get("Set-Cookie", ""))
check("cookie is HttpOnly+Secure", "HttpOnly" in r.headers["Set-Cookie"] and "Secure" in r.headers["Set-Cookie"])
r = c.get("/", base_url="https://x.test"); check("after login: app + demo flag", r.status_code == 200 and b'"demo": true' in r.data and b'"user": "demo"' in r.data)
check("password never in page", demo_pw.encode() not in r.data)
check("authed POST /spots reachable", c.post("/spots", json={"action": "list", "lat": 35.6, "lng": 139.7}, base_url="https://x.test").status_code == 200)
check("logout clears cookie", c.post("/logout", base_url="https://x.test").status_code == 303 and c.get("/", base_url="https://x.test").data.count(b'name="username"') == 1)

# forged / tampered cookies
c = new(); login(c, "yamada", user_pw); good = c.get_cookie("tq_auth", domain="x.test").value
c2 = new(); c2.set_cookie("tq_auth", good, domain="x.test")
check("positive control: a genuine cookie set by hand works", b'name="username"' not in c2.get("/", base_url="https://x.test").data)
c = new(); c.set_cookie("tq_auth", "a~yamada~9999999999~" + "0" * 64, domain="x.test")
check("forged signature rejected", b'name="username"' in c.get("/", base_url="https://x.test").data)
c = new(); login(c, "demo", demo_pw); v = c.get_cookie("tq_auth", domain="x.test").value.split("~"); v[1] = "yamada"
c.set_cookie("tq_auth", "~".join(v), domain="x.test")
check("cookie with swapped user name rejected", b'name="username"' in c.get("/", base_url="https://x.test").data)

# password change invalidates session
c = new(); login(c, "yamada", user_pw)
check("yamada logged in", c.post("/spots", json={"action": "list", "lat": 35.6, "lng": 139.7}, base_url="https://x.test").status_code == 200)
os.environ["AUTH_USERS"] = "yamada:%s" % accounts.hash_password("ChangedPass99999")
check("old session dies after password change", c.post("/spots", json={"action": "list", "lat": 35.6, "lng": 139.7}, base_url="https://x.test").status_code == 401)
os.environ["AUTH_USERS"] = "~".join(["demo:%s:demo" % accounts.hash_password(demo_pw), "yamada:%s" % accounts.hash_password(user_pw)])

# quotas: demo 30 AI calls/h, normal 100
main._ai = lambda body: ("{}", 200, {})
c = new(); login(c, "demo", demo_pw)
codes = [c.post("/ai", json={"task": "itinerary", "prompt": "x"}, base_url="https://x.test").status_code for _ in range(32)]
check("demo AI quota: 30 ok then 429", codes[:30] == [200] * 30 and codes[30] == 429)
c = new(); login(c, "yamada", user_pw)
codes = [c.post("/ai", json={"task": "itinerary", "prompt": "x"}, base_url="https://x.test").status_code for _ in range(32)]
check("normal user not limited at 30", set(codes) == {200})

# brute force: per-user limit even when IP changes
c = new(); res = []
for i in range(12):
    res.append(c.post("/login", data={"username": "demo", "password": "bad%d" % i}, headers={"X-Forwarded-For": "1.2.3.%d" % i}, base_url="https://x.test").status_code)
check("brute force on one account -> 429 after 10", res[:10] == [401] * 10 and res[10] == 429)

# modes
del os.environ["AUTH_USERS"]
c = new(); r = c.get("/"); check("no auth configured -> closed (503)", r.status_code == 503 and c.post("/ai", json={}).status_code == 401)
os.environ["AUTH_DISABLED"] = "true"; check("AUTH_DISABLED=true -> open", new().get("/").status_code == 200); del os.environ["AUTH_DISABLED"]
os.environ["ACCESS_CODE"] = "OldPasscode1234"; c = new()
check("legacy passcode page", b'name="code"' in c.get("/").data)
check("legacy passcode login", c.post("/login", data={"code": "OldPasscode1234"}, base_url="https://x.test").status_code == 303 and c.get("/", base_url="https://x.test").status_code == 200)
print("\nFAILED: %s" % fails if fails else "\nALL PASSED"); sys.exit(1 if fails else 0)
