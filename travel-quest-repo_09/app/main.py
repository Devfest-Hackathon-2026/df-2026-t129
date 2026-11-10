"""TRAVEL QUEST server (Cloud Functions gen2, Python).

GET  /        -> index.html (config injected). Login page first: accounts (AUTH_USERS) or a single passcode (ACCESS_CODE).
POST /login   -> {username, password} form -> session cookie     POST /logout -> clears it
POST /ai      -> Claude: {task:"itinerary"|"vision", prompt, image?, lang} -> {result: ...}
POST /spots   -> shared map (Firestore): {action:"list"|"add"|"confirm"|"report"|"delete", ...}
POST /places  -> Google Places (New): {query, near, lang} -> {results:[{name,address,rating,ratingCount,distanceM,uri}]}
AI needs no API key: it uses the service account of this function (role roles/aiplatform.user).
Other keys come from environment variables / Secret Manager, never from the repo.
"""
import base64, hashlib, hmac, json, math, os, re, secrets, time
import functions_framework
import requests
import accounts

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]  # tried in order if a model is retired (404)
GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "global")
MAX_PROMPT = 12000
MAX_IMAGE_B64 = 6_000_000

_client = None
def client():
    global _client
    if _client is None:
        from google import genai
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            import google.auth
            _, project = google.auth.default()
        _client = genai.Client(vertexai=True, project=project, location=GEMINI_LOCATION)
    return _client


def _is_missing(e):
    t = repr(e)
    return "404" in t or "NOT_FOUND" in t or "was not found" in t


def _generate(prompt, image=None, max_tokens=6000):
    """Call Gemini on Vertex AI and return the text. image = (mime_type, raw_bytes) or None.
    If a model has been retired (404), the next model in FALLBACK_MODELS is tried."""
    from google.genai import types
    parts = []
    if image:
        parts.append(types.Part.from_bytes(data=image[1], mime_type=image[0]))
    parts.append(prompt)
    base = dict(max_output_tokens=max_tokens, temperature=0.7, response_mime_type="application/json")
    models = [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]
    last = None
    for model in models:
        try:
            try:   # keep thinking short for speed and cost; some models reject this setting
                cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"), **base)
                r = client().models.generate_content(model=model, contents=parts, config=cfg)
            except Exception as e:
                if _is_missing(e):
                    raise
                print("retry without thinking_config:", repr(e)[:200])
                r = client().models.generate_content(model=model, contents=parts,
                                                     config=types.GenerateContentConfig(**base))
            if model != MODEL:
                print("note: used fallback model", model, "- set GEMINI_MODEL to silence this")
            return r.text or ""
        except Exception as e:
            last = e
            if not _is_missing(e):
                raise
            print("model not available, trying next:", model)
    raise last


def _json_from_text(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _err(msg, code):
    return (json.dumps({"error": msg}), code, {"Content-Type": "application/json"})


def _ai(body):
    task = body.get("task")
    prompt = str(body.get("prompt", ""))[:MAX_PROMPT]
    if task not in ("itinerary", "vision") or not prompt:
        return _err("bad request", 400)
    image = None
    if task == "vision":
        img = str(body.get("image", ""))
        m = re.match(r"^data:(image/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/=]+)$", img)
        if not m or len(m.group(2)) > MAX_IMAGE_B64:
            return _err("bad image", 400)
        image = (m.group(1), base64.b64decode(m.group(2), validate=True))
    try:
        text = _generate(prompt + "\n\nReply with JSON only.", image, 4000 if task == "vision" else 8000)
        return (json.dumps({"result": _json_from_text(text)}), 200, {"Content-Type": "application/json"})
    except Exception as e:  # keep details in logs, not in the response
        print("ai error:", repr(e))
        return _err("ai failed", 502)


def _hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(x))


def _places(body):
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        return _err("places not configured", 501)
    query = str(body.get("query", ""))[:120].strip()
    near = str(body.get("near", ""))[:120].strip()
    lang = {"ja": "ja", "zh": "zh-CN"}.get(body.get("lang"), "en")
    if not query:
        return _err("bad request", 400)
    url = "https://places.googleapis.com/v1/places:searchText"

    def search(q, mask, extra=None):
        payload = {"textQuery": q, "languageCode": lang, "regionCode": "JP", "pageSize": 10 if extra else 1}
        payload.update(extra or {})
        r = requests.post(url, json=payload, timeout=10, headers={
            "X-Goog-Api-Key": key, "X-Goog-FieldMask": mask})
        r.raise_for_status()
        return r.json().get("places", [])
    try:
        origin, extra = None, {}
        if near:
            a = search(near, "places.location")
            if a and "location" in a[0]:
                origin = (a[0]["location"]["latitude"], a[0]["location"]["longitude"])
                extra["locationBias"] = {"circle": {"center": {"latitude": origin[0], "longitude": origin[1]}, "radius": 3000.0}}
        mask = "places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.location,places.googleMapsUri"
        out = []
        for p in search(query, mask, extra):
            loc = p.get("location") or {}
            dist = _hav(origin[0], origin[1], loc["latitude"], loc["longitude"]) if origin and loc else None
            out.append({"name": (p.get("displayName") or {}).get("text", ""), "address": p.get("formattedAddress", ""),
                        "rating": p.get("rating"), "ratingCount": p.get("userRatingCount"),
                        "distanceM": dist, "uri": p.get("googleMapsUri", "")})
        out = [o for o in out if o["name"]]
        out.sort(key=lambda o: o["distanceM"] if o["distanceM"] is not None else 1e12)
        return (json.dumps({"results": out[:3]}), 200, {"Content-Type": "application/json"})
    except Exception as e:
        print("places error:", repr(e))
        return _err("places failed", 502)


# ---------------------------------------------------------------- shared map
SPOT_TYPES = ("toilet", "smoke", "atm", "store", "aed", "spot")
HIDE_AT_REPORTS = 3          # hidden after this many reports
_rate = {}                   # per-instance rate limiter (best effort; keep --max-instances small)


def _client_ip(request):
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() or request.remote_addr or "?")


def _allow(request, kind, limit, per=3600, who=None):
    key = (kind, hashlib.sha256((who or _client_ip(request)).encode()).hexdigest()[:16])
    now = time.time()
    hits = [t for t in _rate.get(key, []) if now - t < per]
    if len(hits) >= limit:
        _rate[key] = hits
        return False
    hits.append(now)
    _rate[key] = hits
    if len(_rate) > 5000:
        _rate.clear()
    return True


class MemoryStore:
    """Used for tests (SPOTS_STORE=memory)."""
    def __init__(self):
        self.d = {}
    def all_in_lat(self, lo, hi):
        return [dict(v, id=k) for k, v in self.d.items() if lo <= v["lat"] <= hi]
    def get(self, i):
        v = self.d.get(i)
        return dict(v, id=i) if v else None
    def add(self, rec):
        i = secrets.token_hex(8)
        self.d[i] = rec
        return i
    def inc(self, i, field):
        if i in self.d:
            self.d[i][field] = self.d[i].get(field, 0) + 1
    def delete(self, i):
        self.d.pop(i, None)


class FirestoreStore:
    def __init__(self):
        from google.cloud import firestore
        self.fs = firestore
        self.col = firestore.Client().collection("spots")
    def all_in_lat(self, lo, hi):
        q = self.col.where("lat", ">=", lo).where("lat", "<=", hi).limit(1000)
        return [dict(d.to_dict(), id=d.id) for d in q.stream()]
    def get(self, i):
        d = self.col.document(i).get()
        return dict(d.to_dict(), id=d.id) if d.exists else None
    def add(self, rec):
        ref = self.col.document()
        ref.set(rec)
        return ref.id
    def inc(self, i, field):
        self.col.document(i).update({field: self.fs.Increment(1)})
    def delete(self, i):
        self.col.document(i).delete()


_store = None
def store():
    global _store
    if _store is None:
        _store = MemoryStore() if os.environ.get("SPOTS_STORE") == "memory" else FirestoreStore()
    return _store


def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= v <= hi) or v != v:
        raise ValueError("range")
    return float(v)


def _note(v):
    v = re.sub(r"[\u0000-\u001f\u007f]", " ", str(v or "")).strip()[:60]
    if re.search(r"https?:|www\.|@\w|\.(com|net|jp|cn|org)\b", v, re.I):
        raise ValueError("links not allowed")
    return v


def _spots(request, body):
    action = body.get("action")
    try:
        st = store()
        if action == "list":
            lat, lng = _num(body.get("lat"), -90, 90), _num(body.get("lng"), -180, 180)
            rad = min(max(float(body.get("radiusKm") or 5), 0.5), 30.0)
            if not _allow(request, "list", 120, 600):
                return _err("rate limited", 429)
            dlat = rad / 111.0
            dlng = rad / (111.0 * max(math.cos(math.radians(lat)), 0.05))
            out = []
            for v in st.all_in_lat(lat - dlat, lat + dlat):
                if v.get("hidden") or v.get("rep", 0) >= HIDE_AT_REPORTS or abs(v["lng"] - lng) > dlng:
                    continue
                d = _hav(lat, lng, v["lat"], v["lng"])
                if d <= rad * 1000:
                    out.append({"id": v["id"], "type": v["type"], "lat": v["lat"], "lng": v["lng"],
                                "note": v.get("note", ""), "up": v.get("up", 0), "distanceM": round(d)})
            out.sort(key=lambda o: o["distanceM"])
            return (json.dumps({"spots": out[:200]}), 200, {"Content-Type": "application/json"})
        if action == "add":
            typ = body.get("type")
            if typ not in SPOT_TYPES:
                return _err("bad type", 400)
            lat, lng = round(_num(body.get("lat"), -90, 90), 5), round(_num(body.get("lng"), -180, 180), 5)
            note = _note(body.get("note"))
            if not _allow(request, "add", 20):
                return _err("rate limited", 429)
            for v in st.all_in_lat(lat - 0.0002, lat + 0.0002):   # ~20 m duplicate check
                if v["type"] == typ and not v.get("hidden") and _hav(lat, lng, v["lat"], v["lng"]) < 20:
                    st.inc(v["id"], "up")
                    return (json.dumps({"id": v["id"], "duplicate": True}), 200, {"Content-Type": "application/json"})
            token = secrets.token_urlsafe(24)
            i = st.add({"type": typ, "lat": lat, "lng": lng, "note": note, "up": 0, "rep": 0,
                        "th": hashlib.sha256(token.encode()).hexdigest(), "ts": int(time.time())})
            return (json.dumps({"id": i, "token": token}), 200, {"Content-Type": "application/json"})
        if action in ("confirm", "report"):
            i = str(body.get("id", ""))[:64]
            if not i or not _allow(request, action, 60):
                return _err("rate limited" if i else "bad request", 429 if i else 400)
            if st.get(i):
                st.inc(i, "up" if action == "confirm" else "rep")
            return (json.dumps({"ok": True}), 200, {"Content-Type": "application/json"})
        if action == "delete":
            i, token = str(body.get("id", ""))[:64], str(body.get("token", ""))
            v = st.get(i) if i else None
            if not v or not token or not secrets.compare_digest(v.get("th", ""), hashlib.sha256(token.encode()).hexdigest()):
                return _err("forbidden", 403)
            st.delete(i)
            return (json.dumps({"ok": True}), 200, {"Content-Type": "application/json"})
        return _err("bad request", 400)
    except ValueError:
        return _err("bad request", 400)
    except Exception as e:
        print("spots error:", repr(e))
        return _err("spots failed", 502)


# ---------------------------------------------------------------- login (accounts or passcode)
# Modes, decided by environment variables:
#   AUTH_USERS set        -> user name + password accounts (recommended; see tools/make_users.py)
#   ACCESS_CODE set       -> one shared passcode (old behaviour)
#   AUTH_DISABLED=true    -> no login (local development only)
#   none of the above     -> the site stays CLOSED (503) instead of being open to everyone
COOKIE = "tq_auth"
SESSION_DAYS = 7
DEMO_SESSION_DAYS = 1
PASSCODE_DAYS = 30
# AI / Places cost money: per-hour limits per signed-in user (demo accounts get less).
HOURLY_LIMIT = {"ai": {"demo": 30, "user": 100}, "places": {"demo": 60, "user": 300}}


def _users():
    return accounts.parse_users(os.environ.get("AUTH_USERS", ""))


def _code():
    return os.environ.get("ACCESS_CODE", "")


def _mode():
    if _users():
        return "accounts"
    if _code():
        return "passcode"
    if os.environ.get("AUTH_DISABLED", "").lower() == "true":
        return "open"
    return "closed"


def _secret():
    # SESSION_SECRET is best (random, 32+ chars). Without it, fall back to a value derived from the credentials.
    return (os.environ.get("SESSION_SECRET") or ("tq2|" + os.environ.get("AUTH_USERS", "") + "|" + _code())).encode()


def _sign(msg):
    return hmac.new(_secret(), msg.encode(), hashlib.sha256).hexdigest()


def _fp(u):
    return hashlib.sha256(u["hash"].encode()).hexdigest()[:16]   # changes when the password changes -> old sessions die


def _make_cookie(mode, name=None):
    if mode == "passcode":
        exp = int(time.time()) + PASSCODE_DAYS * 86400
        return "p~%d~%s" % (exp, _sign("p|%d" % exp)), PASSCODE_DAYS * 86400
    u = _users()[name]
    secs = (DEMO_SESSION_DAYS if u["demo"] else SESSION_DAYS) * 86400
    exp = int(time.time()) + secs
    return "a~%s~%d~%s" % (name, exp, _sign("a|%s|%d|%s" % (name, exp, _fp(u)))), secs


def _session(request):
    """-> {"user": str|None, "demo": bool} when allowed in, otherwise None."""
    mode = _mode()
    if mode == "open":
        return {"user": None, "demo": False}
    if mode == "closed":
        return None
    parts = request.cookies.get(COOKIE, "").split("~")
    try:
        if mode == "passcode" and len(parts) == 3 and parts[0] == "p":
            if int(parts[1]) > time.time() and hmac.compare_digest(parts[2], _sign("p|%s" % parts[1])):
                return {"user": "passcode", "demo": False}
        if mode == "accounts" and len(parts) == 4 and parts[0] == "a":
            u = _users().get(parts[1])
            if u and int(parts[2]) > time.time() and hmac.compare_digest(
                    parts[3], _sign("a|%s|%s|%s" % (parts[1], parts[2], _fp(u)))):
                return {"user": parts[1], "demo": u["demo"]}
    except ValueError:
        pass
    return None


LOGIN_HTML = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>TRAVEL QUEST</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#E6F2F3;color:#10303A;font-family:system-ui,'Hiragino Sans','Noto Sans JP','PingFang SC',sans-serif}
@media (prefers-color-scheme:dark){body{background:#0A1418;color:#E4F3F5}form{background:#0F1E24!important;border-color:#27444D!important}input{background:#152A31!important;color:#E4F3F5!important;border-color:#27444D!important}button{background:#5FD0D4!important;color:#062226!important}}
form{width:min(92vw,360px);background:#fff;border:1px solid #D3E6E8;border-radius:16px;padding:22px}
h1{font-size:20px;margin:0 0 6px}p{margin:0 0 12px;font-size:14px;opacity:.85}
label{display:block;font-size:13px;font-weight:700;margin:10px 0 4px}
input{width:100%;box-sizing:border-box;min-height:46px;font-size:16px;padding:8px 12px;border:1.5px solid #D3E6E8;border-radius:10px;background:#fff;color:inherit}
button{margin-top:14px;width:100%;min-height:46px;font-size:16px;font-weight:700;border:0;border-radius:10px;background:#08686B;color:#fff}
.e{color:#B3261E;font-weight:700;margin:8px 0 0;font-size:14px}</style></head><body>
<form method="post" action="/login"><h1>TRAVEL QUEST</h1>
<p>@@LEAD@@</p>
@@FIELDS@@@@MSG@@<button type="submit">OK</button></form></body></html>"""

_FIELDS_ACCOUNTS = ('<label for="u">ID / User / 用户名</label><input id="u" type="text" name="username" autocomplete="username" '
                    'autocapitalize="none" spellcheck="false" autofocus required maxlength="64">'
                    '<label for="p">パスワード / Password / 密码</label><input id="p" type="password" name="password" '
                    'autocomplete="current-password" required maxlength="200">')
_FIELDS_PASSCODE = '<input type="password" name="code" autocomplete="current-password" autofocus required>'


def _page(html, code=200):
    return (html, code, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


def _login_page(err=False, code=200):
    if _mode() == "closed":
        return _page("<!doctype html><meta charset=utf-8><meta name=robots content=noindex>"
                     "<p style='font:16px system-ui;padding:24px'>ログインが未設定のため、公開を停止しています。管理者は SETUP.md の「ログインとデモアカウント」を確認してください。<br>"
                     "Login is not configured, so this site is closed.</p>", 503)
    acc = _mode() == "accounts"
    lead = "IDとパスワードを入力してください<br>Sign in / 请登录" if acc else "パスワードを入力してください<br>Enter the password / 请输入密码"
    wrong = ("IDまたはパスワードが違います / Wrong ID or password / 用户名或密码错误" if acc
             else "パスワードが違います / Wrong password / 密码错误")
    msg = '<div class="e" role="alert">%s</div>' % wrong if err else ""
    return _page(LOGIN_HTML.replace("@@LEAD@@", lead).replace("@@FIELDS@@", _FIELDS_ACCOUNTS if acc else _FIELDS_PASSCODE)
                 .replace("@@MSG@@", msg), code)


def _login(request):
    from flask import make_response
    mode = _mode()
    if mode in ("closed", "open"):
        return _login_page()
    if not _allow(request, "login", 10, 600):
        return _err("rate limited", 429)
    if mode == "accounts":
        name_in = request.form.get("username", "")[:64].strip().lower()
        # also limit per user name, so guessing one account's password cannot be sped up by changing IPs
        if not _allow(request, "login-user", 10, 600, who="u:" + name_in):
            return _err("rate limited", 429)
        name = accounts.check_login(_users(), name_in, request.form.get("password", "")[:200])
        if not name:
            return _login_page(True, 401)
        value, secs = _make_cookie("accounts", name)
    else:
        given = request.form.get("code", "")[:200]
        if not hmac.compare_digest(given.encode(), _code().encode()):
            return _login_page(True, 401)
        value, secs = _make_cookie("passcode")
    r = make_response("", 303)
    r.headers["Location"] = "/"
    r.headers["Cache-Control"] = "no-store"
    r.set_cookie(COOKIE, value, max_age=secs, httponly=True, secure=True, samesite="Lax")
    return r


def _logout():
    from flask import make_response
    r = make_response("", 303)
    r.headers["Location"] = "/"
    r.headers["Cache-Control"] = "no-store"
    r.set_cookie(COOKIE, "", max_age=0, httponly=True, secure=True, samesite="Lax")
    return r


def _index_html(sess=None):
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        html = f.read()
    cfg = {"aiUrl": "/ai", "placesUrl": "/places", "spotsUrl": "/spots"}
    if os.environ.get("MAPS_EMBED_KEY"):
        cfg["mapsKey"] = os.environ["MAPS_EMBED_KEY"]
    if sess and sess.get("user") and _mode() == "accounts":
        cfg["user"] = sess["user"]
        cfg["demo"] = bool(sess["demo"])
        cfg["logoutUrl"] = "/logout"
    tag = "<script>window.TRAVEL_QUEST_CONFIG=%s;</script>" % json.dumps(cfg).replace("</", "<\\/")
    return html.replace("</head>", tag + "</head>", 1)


@functions_framework.http
def app(request):
    path = request.path.rstrip("/") or "/"
    if path == "/robots.txt":
        return ("User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain"})
    if request.method == "POST" and path == "/login":
        return _login(request)
    if request.method == "POST" and path == "/logout":
        return _logout()
    sess = _session(request)
    if sess is None:
        if request.method == "GET" and path in ("/", "/index.html"):
            return _login_page()
        return _err("unauthorized", 401)
    if request.method == "GET" and path in ("/", "/index.html"):
        return (_index_html(sess), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                                         "X-Robots-Tag": "noindex, nofollow"})
    if request.method == "POST" and path in ("/ai", "/places", "/spots"):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _err("bad request", 400)
        if path == "/spots":
            return _spots(request, body)
        lim = HOURLY_LIMIT[path[1:]]["demo" if sess["demo"] else "user"]
        if not _allow(request, "quota" + path, lim, 3600, who=sess["user"] and "q:" + sess["user"]):
            return _err("rate limited", 429)
        return _ai(body) if path == "/ai" else _places(body)
    return _err("not found", 404)
