"""TRAVEL QUEST server (Cloud Functions gen2, Python).

GET  /        -> index.html (config injected). If ACCESS_CODE is set, a passcode page comes first.
POST /ai      -> Claude: {task:"itinerary"|"vision", prompt, image?, lang} -> {result: ...}
POST /spots   -> shared map (Firestore): {action:"list"|"add"|"confirm"|"report"|"delete", ...}
POST /places  -> Google Places (New): {query, near, lang} -> {results:[{name,address,rating,ratingCount,distanceM,uri}]}
AI needs no API key: it uses the service account of this function (role roles/aiplatform.user).
Other keys come from environment variables / Secret Manager, never from the repo.
"""
import base64, hashlib, hmac, json, math, os, re, secrets, time
import functions_framework
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
# thinking level sent to Gemini ("LOW" keeps answers fast). Set GEMINI_THINKING=none to send nothing.
_THINK = {"level": (os.environ.get("GEMINI_THINKING", "LOW").upper() if os.environ.get("GEMINI_THINKING", "LOW").lower() != "none" else None)}
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
            r = None
            level = _THINK["level"]          # None = do not send a thinking setting
            if level:
                try:   # keep thinking short for speed and cost; if rejected, remember and stop sending it
                    cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=level), **base)
                    r = client().models.generate_content(model=model, contents=parts, config=cfg)
                except Exception as e:
                    if _is_missing(e):
                        raise
                    t = repr(e)
                    if "INVALID_ARGUMENT" in t or "400" in t:
                        print("thinking_level", level, "is not supported; continuing without it:", t[:160])
                        _THINK["level"] = None
                    else:
                        raise
            if r is None:
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


def _index_html():
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        html = f.read()
    cfg = {"aiUrl": "/ai", "placesUrl": "/places", "spotsUrl": "/spots"}
    if os.environ.get("MAPS_EMBED_KEY"):
        cfg["mapsKey"] = os.environ["MAPS_EMBED_KEY"]
    tag = "<script>window.TRAVEL_QUEST_CONFIG=%s;</script>" % json.dumps(cfg).replace("</", "<\\/")
    return html.replace("</head>", tag + "</head>", 1)


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


def _allow(request, kind, limit, per=3600):
    key = (kind, hashlib.sha256(_client_ip(request).encode()).hexdigest()[:16])
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


# ---------------------------------------------------------------- optional passcode
# Set the ACCESS_CODE environment variable to require a passcode (letters and numbers, 12+ chars recommended).
COOKIE = "tq_auth"
COOKIE_DAYS = 30


def _code():
    return os.environ.get("ACCESS_CODE", "")


def _sign(exp):
    return hmac.new(("tq1|" + _code()).encode(), str(exp).encode(), hashlib.sha256).hexdigest()


def _authed(request):
    if not _code():
        return True
    v = request.cookies.get(COOKIE, "")
    try:
        exp, sig = v.split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(sig, _sign(exp))
    except ValueError:
        return False


LOGIN_HTML = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>TRAVEL QUEST</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#E6F2F3;color:#10303A;font-family:system-ui,'Hiragino Sans','Noto Sans JP','PingFang SC',sans-serif}
@media (prefers-color-scheme:dark){body{background:#0A1418;color:#E4F3F5}form{background:#0F1E24!important;border-color:#27444D!important}input{background:#152A31!important;color:#E4F3F5!important;border-color:#27444D!important}button{background:#5FD0D4!important;color:#062226!important}}
form{width:min(92vw,360px);background:#fff;border:1px solid #D3E6E8;border-radius:16px;padding:22px}
h1{font-size:20px;margin:0 0 6px}p{margin:0 0 12px;font-size:14px;opacity:.85}
input{width:100%;box-sizing:border-box;min-height:46px;font-size:16px;padding:8px 12px;border:1.5px solid #D3E6E8;border-radius:10px;background:#fff;color:inherit}
button{margin-top:12px;width:100%;min-height:46px;font-size:16px;font-weight:700;border:0;border-radius:10px;background:#08686B;color:#fff}
.e{color:#B3261E;font-weight:700;margin:8px 0 0;font-size:14px}</style></head><body>
<form method="post" action="/login"><h1>TRAVEL QUEST</h1>
<p>合言葉を入力してください<br>Enter the passcode / 请输入口令</p>
<input type="password" name="code" autocomplete="current-password" autofocus required>
@@MSG@@<button type="submit">OK</button></form></body></html>"""


def _login_page(err=False, code=200):
    msg = '<div class="e" role="alert">合言葉が違います / Wrong passcode / 口令错误</div>' if err else ""
    return (LOGIN_HTML.replace("@@MSG@@", msg), code, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"})


def _login(request):
    from flask import make_response
    if not _allow(request, "login", 10, 600):
        return _err("rate limited", 429)
    given = request.form.get("code", "")[:200]
    if not _code() or not hmac.compare_digest(given.encode(), _code().encode()):
        return _login_page(True, 401)
    exp = int(time.time()) + COOKIE_DAYS * 86400
    r = make_response("", 303)
    r.headers["Location"] = "/"
    r.set_cookie(COOKIE, "%d.%s" % (exp, _sign(exp)), max_age=COOKIE_DAYS * 86400, httponly=True, secure=True, samesite="Lax")
    return r


@functions_framework.http
def app(request):
    path = request.path.rstrip("/") or "/"
    if path == "/robots.txt":
        return ("User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain"})
    if request.method == "POST" and path == "/login":
        return _login(request)
    if not _authed(request):
        if request.method == "GET" and path in ("/", "/index.html"):
            return _login_page()
        return _err("unauthorized", 401)
    if request.method == "GET" and path in ("/", "/index.html"):
        return (_index_html(), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache",
                                     "X-Robots-Tag": "noindex, nofollow"})
    if request.method == "POST" and path in ("/ai", "/places", "/spots"):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _err("bad request", 400)
        if path == "/spots":
            return _spots(request, body)
        return _ai(body) if path == "/ai" else _places(body)
    return _err("not found", 404)
