"""
SNAPCHAT MULTI-PROFILE MONITOR & VIEWER v4
- Fix tri par récent (sort stable par ts_unix)
- Heure française (Europe/Paris) dans l'affichage
- Avatar auto-détecté depuis HTML (pattern _RS126,126)
- Viewer auto-refresh toutes les 15s sans recharger la page
- Historique avec preview + clic pour jouer
"""

import urllib.request
import urllib.error
import json
import re
import sys
import os
import time
import logging
import webbrowser
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
PROFILES = [
    "naslachiente",
    "lanalana570",
    "ibmusikofficiel",
    "nissou598",
    "gateyy_10",
    "mdm-78130",
    "chikaaanos",
    "brahimmd31",
    "samos-officiel",
    "h78amza",
    "reineminnesota",
    "leyna.latina",
]

PROFILE_CATEGORIES = {
    "naslachiente":    "Lifestyle",
    "lanalana570":     "Lifestyle",
    "ibmusikofficiel": "Music",
    "nissou598":       "Daily",
    "gateyy_10":       "Daily",
    "mdm-78130":       "Daily",
    "chikaaanos":      "Daily",
    "brahimmd31":      "Daily",
    "samos-officiel":  "Music",
    "h78amza":         "Daily",
    "reineminnesota":  "Daily",
    "leyna.latina":    "Lifestyle",
}

PROFILE_NAMES = {
    "naslachiente":    "Nasdas",
    "lanalana570":     "Henna",
    "ibmusikofficiel": "Imran",
    "nissou598":       "Anis",
    "gateyy_10":       "Gatey",
    "mdm-78130":       "Canette",
    "chikaaanos":      "Chikanos",
    "brahimmd31":      "Brahim",
    "samos-officiel":  "Samos",
    "h78amza":         "Hamza",
    "reineminnesota":  "Minnesota",
    "leyna.latina":    "Leyna",
}

REFRESH_INTERVAL = 30
BASE_URL         = "https://www.snapchat.com/@{}"
LOGS_DIR         = Path("logs")
OUTPUT_DIR       = Path("viewers")
STORE_DIR        = Path("store")
DATA_JSON        = Path("viewers") / "data.json"   # ← live data for auto-refresh

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "identity",
    "Cache-Control":   "no-cache",
}

MEDIA_TYPES = {0: "IMAGE", 1: "VIDEO"}

snap_logger   = None
global_logger = None


# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

def setup_logger(name: str, log_file: str) -> logging.Logger:
    LOGS_DIR.mkdir(exist_ok=True)
    lg = logging.getLogger(name)
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOGS_DIR / log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    lg.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    lg.addHandler(ch)
    return lg


# ─────────────────────────────────────────────
#  FETCH & PARSE
# ─────────────────────────────────────────────

def fetch_html(url: str) -> str | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return None


def _find_snap_lists(obj, results=None, depth=0):
    """Parcourt récursivement un dict/list JSON pour trouver toutes les snapList."""
    if results is None:
        results = []
    if depth > 12:
        return results
    if isinstance(obj, dict):
        if "snapList" in obj and isinstance(obj["snapList"], list) and obj["snapList"]:
            results.append(obj["snapList"])
        for v in obj.values():
            _find_snap_lists(v, results, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _find_snap_lists(item, results, depth + 1)
    return results


def extract_snap_data(html: str) -> list:
    # ── Méthode 1 : __NEXT_DATA__ JSON complet — chemin direct ──────────
    nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
    if nd:
        try:
            d = json.loads(nd.group(1))
            # Accès direct au chemin canonical: props.pageProps.story.snapList
            try:
                direct = d["props"]["pageProps"]["story"]["snapList"]
                if isinstance(direct, list) and direct:
                    return direct
            except (KeyError, TypeError):
                pass
            # Fallback: chercher toutes les snapList et prendre la plus longue
            all_lists = _find_snap_lists(d)
            if all_lists:
                best = max(all_lists, key=len)
                if best:
                    return best
        except Exception:
            pass

    # ── Méthode 2 : regex snapList dans le HTML brut ──────────────────────
    # Utilise un parser de brackets pour trouver le bon tableau JSON
    for start_pat in [
        r'"snapList"\s*:\s*\[',
        r'"snapList":\[',
    ]:
        m = re.search(start_pat, html)
        if not m:
            continue
        start = m.end() - 1  # position du '[' ouvrant
        depth = 0
        end = start
        for i in range(start, min(start + 2_000_000, len(html))):
            c = html[i]
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                return json.loads(html[start:end])
            except Exception:
                pass

    # ── Méthode 3 : bolt_web thumbnails (fallback CSR) ───────────────────
    import base64 as _b64
    import urllib.parse as _ul

    thumb_re = re.compile(
        r"https://[^\s\"']+sc-cdn\.net/aps/bolt_web/([A-Za-z0-9%+/=_-]+?)\._RS(\d+),(\d+)"
    )
    seen_ids = set()
    found    = []
    for tm in thumb_re.finditer(html):
        b64_raw = tm.group(1)
        try:
            b64_clean = _ul.unquote(b64_raw)
            pad       = b64_clean + "=" * (4 - len(b64_clean) % 4)
            media_url = _b64.urlsafe_b64decode(pad).decode("utf-8", errors="replace")
        except Exception:
            continue
        # Accepter /d/ (images/previews) ET /i/ (vidéos)
        id_m = re.search(r"/(?:d|i)/([A-Za-z0-9_-]{10,})", media_url)
        if not id_m:
            continue
        snap_id = id_m.group(1)
        if snap_id in seen_ids:
            continue
        seen_ids.add(snap_id)
        thumb_url = tm.group(0)
        # Détecter le type : /i/ = vidéo, /d/ = image
        media_type = 1 if "/i/" in media_url else 0
        found.append({
            "snapId":        {"value": snap_id},
            "snapIndex":     len(found),
            "snapMediaType": media_type,
            "snapUrls": {
                "mediaUrl":        media_url,
                "mediaPreviewUrl": {"value": thumb_url},
            },
            "timestampInSec": {"value": ""},
        })
    return found


def extract_avatar(html: str) -> str:
    """
    Extrait l'URL de la photo de profil depuis le HTML Snapchat.
    Cherche spécifiquement les URLs _RS126,126 qui sont les avatars de profil.
    """
    # Pattern ciblé : links preload avec _RS126,126 (avatar 126x126)
    patterns = [
        # preload image avec _RS126,126 exactement
        r'<link[^>]+rel=["\']preload["\'][^>]+as=["\']image["\'][^>]+href=["\']([^"\']+_RS126,126[^"\']*)["\']',
        r'<link[^>]+href=["\']([^"\']+_RS126,126[^"\']*)["\'][^>]+rel=["\']preload["\'][^>]+as=["\']image["\']',
        # fetchpriority="high" avec _RS126,126
        r'href=["\']([^"\']+_RS126,126[^"\']*FMwebp[^"\']*)["\'][^>]*fetchpriority',
        r'href=["\']([^"\']+_RS126,126[^"\']*)["\']',
        # og:image meta
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        # twitter:image
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        matches = re.findall(pat, html)
        for m in matches:
            if "_RS126,126" in m:
                return m
    # Fallback: toute preload image sc-cdn
    for pat in patterns[:2]:
        matches = re.findall(pat, html)
        if matches:
            return matches[0]
    return ""


def snap_ids(snaps: list) -> set:
    return {(s.get("snapId") or {}).get("value") for s in snaps} - {None}


def format_ts_fr(v) -> str:
    """Formate le timestamp en heure française (Europe/Paris, avec DST)."""
    try:
        ts = int(v) if isinstance(v, str) else int(v)
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        year = dt_utc.year
        dst_start = datetime(year, 3, 31, 2, 0, tzinfo=timezone.utc)
        dst_start -= timedelta(days=dst_start.weekday() + 1 if dst_start.weekday() != 6 else 0)
        dst_end = datetime(year, 10, 31, 1, 0, tzinfo=timezone.utc)
        dst_end -= timedelta(days=dst_end.weekday() + 1 if dst_end.weekday() != 6 else 0)
        offset = timedelta(hours=2) if dst_start <= dt_utc < dst_end else timedelta(hours=1)
        dt_fr = dt_utc + offset
        return dt_fr.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(v)


def format_ts_fr_short(v) -> str:
    """Version courte pour affichage dans la liste."""
    try:
        ts = int(v) if isinstance(v, str) else int(v)
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        year = dt_utc.year
        dst_start = datetime(year, 3, 31, 2, 0, tzinfo=timezone.utc)
        dst_start -= timedelta(days=dst_start.weekday() + 1 if dst_start.weekday() != 6 else 0)
        dst_end = datetime(year, 10, 31, 1, 0, tzinfo=timezone.utc)
        dst_end -= timedelta(days=dst_end.weekday() + 1 if dst_end.weekday() != 6 else 0)
        offset = timedelta(hours=2) if dst_start <= dt_utc < dst_end else timedelta(hours=1)
        dt_fr = dt_utc + offset
        return dt_fr.strftime("%d/%m %H:%M")
    except Exception:
        return str(v)


def build_snaps_json(snaps: list, profile: str = "") -> list:
    out = []
    for s in snaps:
        ts_raw = (s.get("timestampInSec") or {}).get("value", "")
        urls   = s.get("snapUrls") or {}
        ts_unix = int(ts_raw) if ts_raw else 0
        out.append({
            "profile": profile,
            "index":   s.get("snapIndex", 0),
            "type":    s.get("snapMediaType", 1),
            "ts":      format_ts_fr(ts_raw) if ts_raw else "",
            "ts_short": format_ts_fr_short(ts_raw) if ts_raw else "",
            "ts_unix": ts_unix,
            "url":     urls.get("mediaUrl", ""),
            "preview": (urls.get("mediaPreviewUrl") or {}).get("value", ""),
            "isnew":   False,
        })
    return out


# ─────────────────────────────────────────────
#  PERSISTENT STORAGE
# ─────────────────────────────────────────────

def store_path(profile: str) -> Path:
    STORE_DIR.mkdir(exist_ok=True)
    return STORE_DIR / f"{profile}.json"


def load_store(profile: str) -> dict:
    p = store_path(profile)
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            # Migration: fusionner les anciennes clés "profil_index_ts" → "profil_index"
            cleaned = {}
            for k, v in raw.items():
                if v.get("profile") and v.get("index") is not None:
                    new_key = f"{v['profile']}_{v['index']}"
                    if new_key not in cleaned or (
                        v.get("ts_unix", 0) > 0 and cleaned[new_key].get("ts_unix", 0) == 0
                    ):
                        cleaned[new_key] = v
                else:
                    cleaned[k] = v
            return cleaned
        except:
            pass
    return {}


def save_store(profile: str, data: dict) -> None:
    store_path(profile).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_snaps_to_store(profile: str, new_snaps_json: list) -> dict:
    store = load_store(profile)
    for s in new_snaps_json:
        # Clé basée sur l'index du snap — unique et stable
        # On préfère l'index Snapchat plutôt que ts_unix qui peut être 0
        key = f"{s['profile']}_{s['index']}"
        if key not in store:
            store[key] = s
        else:
            # Mettre à jour si on a maintenant un timestamp qu'on n'avait pas
            if s.get("ts_unix", 0) > 0 and store[key].get("ts_unix", 0) == 0:
                store[key] = s
    save_store(profile, store)
    return store


def get_all_stored_snaps(profile: str) -> list:
    store = load_store(profile)
    snaps = list(store.values())
    snaps.sort(key=lambda x: x.get("ts_unix", 0))
    return snaps


# ─────────────────────────────────────────────
#  PROFILE STATE
# ─────────────────────────────────────────────

class ProfileState:
    def __init__(self, profile: str):
        self.profile      = profile
        self.known_ids    = set()
        self.last_snaps   = []
        self.snap_json    = []
        self.all_snaps    = []
        self.check_count  = 0
        self.new_count    = 0
        self.last_check   = None
        self.new_log      = []
        self.avatar_url   = ""

        self.all_snaps = []  # sera rempli au premier check() avec les snaps Snapchat actuels

    def url(self): return BASE_URL.format(self.profile)

    def check(self) -> list:
        self.check_count += 1
        self.last_check   = datetime.now()
        html = fetch_html(self.url())
        if not html:
            return []

        # Toujours tenter d'extraire l'avatar (peut avoir expiré)
        new_avatar = extract_avatar(html)
        if new_avatar:
            self.avatar_url = new_avatar
            if global_logger:
                global_logger.info(f"Avatar trouvé pour @{self.profile}: {new_avatar[:60]}...")

        snaps = extract_snap_data(html)
        if not snaps:
            return []

        current_ids  = snap_ids(snaps)
        current_json = build_snaps_json(snaps, self.profile)

        if not self.known_ids:
            self.known_ids  = current_ids
            self.last_snaps = snaps
            self.snap_json  = current_json
            # Persister dans le store, mais afficher UNIQUEMENT les snaps actuels de Snapchat
            merge_snaps_to_store(self.profile, current_json)
            self.all_snaps  = sorted(current_json, key=lambda x: x.get("ts_unix", 0))
            v = sum(1 for s in snaps if s.get("snapMediaType") == 1)
            i = len(snaps) - v
            if snap_logger:
                snap_logger.info(f"INIT  @{self.profile:<20}  {len(snaps)} snaps  ({v} videos, {i} images)")
            return []

        new_ids   = current_ids - self.known_ids
        new_snaps = [s for s in snaps if (s.get("snapId") or {}).get("value") in new_ids]

        self.last_snaps = snaps
        self.snap_json  = current_json

        if new_snaps:
            self.new_count += len(new_snaps)
            self.known_ids  = current_ids
            new_json = build_snaps_json(new_snaps, self.profile)
            for s in new_json:
                s["isnew"] = True
            # Persister dans le store, afficher UNIQUEMENT les snaps actuels
            merge_snaps_to_store(self.profile, current_json)
            self.all_snaps = sorted(current_json, key=lambda x: x.get("ts_unix", 0))
            for s in new_snaps:
                ts_raw = (s.get("timestampInSec") or {}).get("value", "")
                ts_fmt = format_ts_fr(ts_raw) if ts_raw else "?"
                mtype  = MEDIA_TYPES.get(s.get("snapMediaType"), "?")
                idx    = s.get("snapIndex", "?")
                if snap_logger:
                    snap_logger.info(f"NEW   @{self.profile:<20}  #{idx}  {mtype:<5}  {ts_fmt}")
                self.new_log.append({
                    "ts":     datetime.now().strftime("%H:%M:%S"),
                    "idx":    idx,
                    "type":   mtype,
                    "ts_pub": ts_fmt,
                    "preview": (new_json[0].get("preview", "") if new_json else ""),
                    "url":    (new_json[0].get("url", "") if new_json else ""),
                })
        else:
            self.known_ids = current_ids
            # Persister dans le store, afficher UNIQUEMENT les snaps actuels
            merge_snaps_to_store(self.profile, current_json)
            self.all_snaps = sorted(current_json, key=lambda x: x.get("ts_unix", 0))

        return new_snaps


# ─────────────────────────────────────────────
#  DATE HELPERS
# ─────────────────────────────────────────────

def day_unix_bounds(d: date) -> tuple:
    # Dernier dimanche de mars = début heure été (UTC+2)
    # Dernier dimanche d'octobre = fin heure été (UTC+1)
    year = d.year
    # Dernier dimanche de mars
    last_sun_mar = date(year, 3, 31)
    while last_sun_mar.weekday() != 6:
        last_sun_mar -= timedelta(days=1)
    # Dernier dimanche d'octobre
    last_sun_oct = date(year, 10, 31)
    while last_sun_oct.weekday() != 6:
        last_sun_oct -= timedelta(days=1)
    # Offset Paris
    offset_h = 2 if last_sun_mar <= d < last_sun_oct else 1
    # minuit Paris = 00:00 locale = (24 - offset) UTC la veille
    start_utc = datetime(d.year, d.month, d.day, 0, 0, 0) - timedelta(hours=offset_h)
    start_utc = start_utc.replace(tzinfo=timezone.utc)
    end_utc   = start_utc + timedelta(days=1)
    return int(start_utc.timestamp()), int(end_utc.timestamp())


# ─────────────────────────────────────────────
#  LIVE DATA JSON (for auto-refresh)
# ─────────────────────────────────────────────

def write_live_data(states: list) -> None:
    """Écrit un JSON léger que le viewer recharge automatiquement."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    profiles_data = {}
    avatars_data  = {}
    new_logs_data = {}
    for st in states:
        new_idx = {s.get("index") for s in st.snap_json if s.get("isnew")}
        all_s = []
        for s in st.all_snaps:
            sc = dict(s)
            sc["isnew"] = sc.get("index") in new_idx
            all_s.append(sc)
        profiles_data[st.profile] = all_s
        avatars_data[st.profile]  = st.avatar_url
        new_logs_data[st.profile] = st.new_log

    leaderboard = sorted(states, key=lambda s: len(s.all_snaps), reverse=True)
    lb_rows = []
    for rank, st in enumerate(leaderboard, 1):
        v    = sum(1 for s in st.all_snaps if s.get("type") == 1)
        imgs = len(st.all_snaps) - v
        lb_rows.append([
            st.profile,
            PROFILE_NAMES.get(st.profile, st.profile),
            rank, len(st.all_snaps), v, imgs, st.new_count
        ])

    today     = date.today()
    yesterday = today - timedelta(days=1)
    payload = {
        "profiles":   profiles_data,
        "avatars":    avatars_data,
        "new_logs":   new_logs_data,
        "lb":         lb_rows,
        "today_str":  today.strftime("%d/%m/%Y"),
        "yest_str":   yesterday.strftime("%d/%m/%Y"),
        "today_b":    list(day_unix_bounds(today)),
        "yest_b":     list(day_unix_bounds(yesterday)),
        "updated_at": int(time.time()),
    }
    DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────
#  HTML GENERATOR
# ─────────────────────────────────────────────

def generate_html(states: list) -> str:
    profiles_data = {}
    avatars_data  = {}
    for st in states:
        new_idx = {s.get("index") for s in st.snap_json if s.get("isnew")}
        all_s = []
        for s in st.all_snaps:
            sc = dict(s)
            sc["isnew"] = sc.get("index") in new_idx
            all_s.append(sc)
        profiles_data[st.profile] = all_s
        avatars_data[st.profile]  = st.avatar_url

    new_logs_data = {st.profile: st.new_log for st in states}
    leaderboard   = sorted(states, key=lambda s: len(s.all_snaps), reverse=True)

    today     = date.today()
    yesterday = today - timedelta(days=1)

    profiles_js    = json.dumps(profiles_data,     ensure_ascii=False)
    profiles_list  = json.dumps(PROFILES,           ensure_ascii=False)
    avatars_js     = json.dumps(avatars_data,        ensure_ascii=False)
    categories_js  = json.dumps(PROFILE_CATEGORIES,  ensure_ascii=False)
    names_js       = json.dumps(PROFILE_NAMES,        ensure_ascii=False)
    new_logs_js    = json.dumps(new_logs_data,         ensure_ascii=False)
    today_str      = json.dumps(today.strftime("%d/%m/%Y"))
    yesterday_str  = json.dumps(yesterday.strftime("%d/%m/%Y"))
    today_b_js     = json.dumps(list(day_unix_bounds(today)))
    yest_b_js      = json.dumps(list(day_unix_bounds(yesterday)))

    lb_rows = []
    for rank, st in enumerate(leaderboard, 1):
        v    = sum(1 for s in st.all_snaps if s.get("type") == 1)
        imgs = len(st.all_snaps) - v
        lb_rows.append(json.dumps(
            [st.profile, PROFILE_NAMES.get(st.profile, st.profile),
             rank, len(st.all_snaps), v, imgs, st.new_count],
            ensure_ascii=False
        ))
    lb_js = "[" + ",".join(lb_rows) + "]"

    # ── CSS ──────────────────────────────────────────────────────────────
    css = """
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&family=Fira+Code:wght@300;400;500&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --ink:#07111f;
  --ink2:#0d1a2e;
  --ink3:#122338;
  --ink4:#1a2f48;
  --border:#1e3452;
  --border2:#2a4870;
  --fg:#e8f4ff;
  --fg2:#7eb8e8;
  --fg3:#3d6a99;
  --hi:#56cfff;
  --hi2:#8de0ff;
  --red:#ff5c7a;
  --green:#36e8a8;
  --side:300px;
}
html,body{height:100%;background:var(--ink);color:var(--fg);font-family:'Nunito',sans-serif;overflow:hidden;-webkit-font-smoothing:antialiased;font-size:14px}
::-webkit-scrollbar{width:3px;height:3px}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}

.shell{display:flex;height:100%;overflow:hidden}

/* ── PANEL ── */
.panel{width:var(--side);flex-shrink:0;background:var(--ink2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.brand{padding:16px 18px 13px;border-bottom:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:space-between}
.brand-wordmark{font-size:1.1rem;font-weight:900;letter-spacing:-.01em;color:var(--fg)}
.brand-wordmark b{color:var(--hi);font-weight:800}

.tabs{display:flex;border-bottom:1px solid var(--border);flex-shrink:0}
.tab{flex:1;padding:10px 0;text-align:center;font-size:.6rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--fg3);cursor:pointer;transition:color .13s;border-bottom:2px solid transparent}
.tab:hover{color:var(--fg2)}
.tab.on{color:var(--fg);border-bottom-color:var(--hi)}

.pane{display:none;flex-direction:column;flex:1;overflow:hidden;min-height:0}
.pane.on{display:flex}

.today-row{padding:10px 14px;border-bottom:1px solid var(--border);flex-shrink:0}
.today-chip{display:flex;align-items:center;justify-content:space-between;background:rgba(86,207,255,.08);border:1px solid rgba(86,207,255,.2);border-radius:12px;padding:9px 11px;cursor:pointer;transition:all .15s}
.today-chip:hover{background:rgba(86,207,255,.13);border-color:rgba(86,207,255,.35)}
.today-chip.on{background:rgba(86,207,255,.16);border-color:var(--hi)}
.today-label{font-size:.75rem;font-weight:700;color:var(--fg)}
.today-chip.on .today-label{color:var(--hi)}
.today-cnt{font-family:'Fira Code',monospace;font-size:.6rem;font-weight:500;color:var(--hi);background:rgba(86,207,255,.1);padding:2px 7px;border-radius:4px;border:1px solid rgba(86,207,255,.15)}

.cat-bar{padding:7px 10px;border-bottom:1px solid var(--border);display:flex;gap:4px;flex-wrap:wrap;flex-shrink:0}
.cp{padding:3px 9px;border-radius:5px;font-size:.57rem;font-weight:700;letter-spacing:.04em;cursor:pointer;border:1px solid var(--border2);color:var(--fg3);background:transparent;transition:all .12s}
.cp:hover{border-color:var(--fg3);color:var(--fg2)}
.cp.on{background:rgba(86,207,255,.1);color:var(--hi);border-color:rgba(86,207,255,.3)}

.prof-list{overflow-y:auto;flex:1}
.pi{display:flex;align-items:center;gap:11px;padding:9px 14px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.03);border-left:3px solid transparent;transition:background .1s,border-color .1s}
.pi:hover{background:var(--ink3)}
.pi.on{background:rgba(86,207,255,.05);border-left-color:var(--hi)}
.pi.cat-off{display:none}
.av{width:36px;height:36px;border-radius:50%;border:1px solid var(--border);flex-shrink:0;overflow:hidden;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:.82rem;color:var(--fg3);background:var(--ink4)}
.av img{width:100%;height:100%;object-fit:cover}
.pi.on .av{border-color:rgba(86,207,255,.4)}
.pi-text{flex:1;min-width:0}
.pi-name{font-size:.8rem;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pi.on .pi-name{color:var(--hi)}
.pi-sub{display:flex;align-items:center;gap:6px;margin-top:2px}
.pi-n{font-size:.57rem;color:var(--fg3);font-family:'Fira Code',monospace}
.pi-cat{font-size:.5rem;padding:1px 5px;border-radius:3px;background:var(--ink4);color:var(--fg3);font-weight:700;text-transform:uppercase;letter-spacing:.05em;border:1px solid var(--border)}
.pi-badge{min-width:16px;height:16px;border-radius:4px;background:var(--red);color:#fff;font-size:.54rem;font-weight:800;display:none;align-items:center;justify-content:center;padding:0 4px;font-family:'Fira Code',monospace}

/* ── LEADERBOARD ── */
.lb-list{overflow-y:auto;flex:1;padding:6px 0}
.lb-item{margin:3px 10px;padding:9px 11px;background:var(--ink3);border:1px solid var(--border);border-radius:12px;cursor:pointer;transition:all .12s}
.lb-item:hover{background:var(--ink4);border-color:var(--border2)}
.lb-top{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.lb-pos{font-family:'Fira Code',monospace;font-size:.72rem;font-weight:700;color:var(--fg3);width:22px;flex-shrink:0}
.lb-av{width:24px;height:24px;border-radius:50%;overflow:hidden;flex-shrink:0;background:var(--ink4);display:flex;align-items:center;justify-content:center;font-size:.6rem;font-weight:800;color:var(--fg3);border:1px solid var(--border)}
.lb-av img{width:100%;height:100%;object-fit:cover}
.lb-name{font-size:.76rem;font-weight:700;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lb-new{font-size:.54rem;color:var(--green);font-weight:700;font-family:'Fira Code',monospace;background:rgba(54,232,168,.08);padding:1px 5px;border-radius:3px}
.lb-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}
.lb-cell{background:var(--ink);border-radius:4px;padding:4px;text-align:center;border:1px solid var(--border)}
.lb-val{font-family:'Fira Code',monospace;font-size:.7rem;font-weight:700;display:block}
.lb-lbl{font-size:.47rem;color:var(--fg3);text-transform:uppercase;letter-spacing:.06em;display:block;margin-top:1px}
.lb-bar{height:1px;background:var(--border);overflow:hidden;margin-top:7px}
.lb-fill{height:100%;background:var(--hi);width:0%;transition:width .65s cubic-bezier(.4,0,.2,1)}

/* ── HISTORIQUE ── */
.hist-list{overflow-y:auto;flex:1;padding:4px 0}
.hist-item{
  display:flex;gap:8px;align-items:flex-start;
  padding:8px 10px;
  border-bottom:1px solid rgba(255,255,255,.025);
  cursor:pointer;
  transition:background .1s;
}
.hist-item:hover{background:var(--ink3)}
.hist-dot{width:5px;height:5px;border-radius:50%;background:var(--green);flex-shrink:0;margin-top:6px}
.hist-body{flex:1;min-width:0}
.hist-who{font-size:.7rem;font-weight:700}
.hist-detail{font-size:.57rem;color:var(--fg3);margin-top:1px;font-family:'Fira Code',monospace}
.hist-ts{font-size:.54rem;color:var(--fg3);flex-shrink:0;margin-top:4px;font-family:'Fira Code',monospace}
.hist-prev{
  width:34px;height:48px;border-radius:4px;
  background:var(--ink4);border:1px solid var(--border);
  flex-shrink:0;overflow:hidden;
  display:flex;align-items:center;justify-content:center;
  font-size:.65rem;color:var(--fg3);
  position:relative;
}
.hist-prev img{width:100%;height:100%;object-fit:cover}
.hist-prev-play{
  position:absolute;inset:0;
  display:flex;align-items:center;justify-content:center;
  background:rgba(0,0,0,.4);
  font-size:.75rem;
  opacity:0;transition:opacity .15s;
}
.hist-item:hover .hist-prev-play{opacity:1}
.hist-empty{padding:28px 14px;text-align:center;font-size:.62rem;color:var(--fg3)}
.clear-btn{background:none;border:1px solid var(--border2);color:var(--fg3);border-radius:4px;padding:2px 7px;font-size:.54rem;cursor:pointer;font-family:'Nunito',sans-serif;transition:all .12s}
.clear-btn:hover{color:var(--fg2);border-color:var(--fg3)}

/* ── SNAP COL ── */
.snap-col{width:260px;flex-shrink:0;background:var(--ink2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.sc-head{padding:10px 12px;border-bottom:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:space-between}
.sc-title{font-size:.8rem;font-weight:700;letter-spacing:-.01em}
.sc-cnt{font-size:.57rem;color:var(--fg3);font-family:'Fira Code',monospace}
.sc-filters{padding:5px 7px;border-bottom:1px solid var(--border);display:flex;gap:3px;flex-wrap:wrap;flex-shrink:0}
.sf{padding:3px 8px;border-radius:4px;font-size:.57rem;font-weight:700;cursor:pointer;border:1px solid var(--border2);color:var(--fg3);background:transparent;transition:all .12s;font-family:'Nunito',sans-serif}
.sf:hover{color:var(--fg2);border-color:var(--fg3)}
.sf.on{background:rgba(86,207,255,.1);color:var(--hi);border-color:rgba(86,207,255,.25)}
.sort-row{padding:4px 7px;border-bottom:1px solid var(--border);display:flex;gap:3px;align-items:center;flex-shrink:0}
.sort-lbl{font-size:.52rem;color:var(--fg3);text-transform:uppercase;letter-spacing:.07em}
.sb{padding:2px 7px;border-radius:4px;font-size:.55rem;font-weight:700;cursor:pointer;border:1px solid var(--border2);color:var(--fg3);background:transparent;transition:all .12s;font-family:'Nunito',sans-serif}
.sb.on{background:rgba(86,207,255,.08);color:var(--hi);border-color:rgba(86,207,255,.2)}
.snap-scroll{overflow-y:auto;flex:1}
.si{display:flex;align-items:center;gap:7px;padding:6px 9px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.025);transition:background .1s;border-left:3px solid transparent}
.si:hover{background:var(--ink3)}
.si.cur{background:rgba(86,207,255,.07);border-left-color:var(--hi)}
.si.cur .si-num{color:var(--hi)}
.si.isnew{border-left-color:var(--red)}
.si.off{display:none}
.si.playing .si-num::before{content:'▶ ';font-size:.46rem;color:var(--hi);animation:b2 .85s infinite}
@keyframes b2{0%,100%{opacity:1}50%{opacity:.1}}
.si-img{width:37px;height:52px;border-radius:4px;object-fit:cover;background:var(--ink4);border:1px solid var(--border);flex-shrink:0}
.si-ph{width:37px;height:52px;border-radius:4px;background:var(--ink4);border:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.62rem;color:var(--fg3)}
.si-info{flex:1;min-width:0}
.si-num{font-size:.68rem;font-weight:700;margin-bottom:2px;display:flex;align-items:center;gap:4px;font-family:'Fira Code',monospace}
.si-newtag{font-size:.42rem;background:var(--red);color:#fff;padding:1px 4px;border-radius:3px;font-weight:800}
.si-who{font-size:.57rem;color:var(--fg3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.si-type{font-size:.5rem;letter-spacing:.06em;text-transform:uppercase;font-weight:700;margin-top:1px}
.si-type.v{color:var(--hi)}
.si-type.i{color:var(--fg2)}
.si-ts{font-size:.49rem;color:var(--fg3);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:'Fira Code',monospace}

/* ── VIEWER ── */
.viewer{flex:1;position:relative;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden}
.viewer-blur{position:absolute;inset:0;background-size:cover;background-position:center;filter:blur(28px) brightness(.35) saturate(1.3);transform:scale(1.08);transition:background-image .3s ease;pointer-events:none}
.snap-stage{position:relative;height:100%;aspect-ratio:9/16;max-width:100%;background:#000;overflow:hidden;border-radius:16px}
#mv{width:100%;height:100%;object-fit:cover;display:block}
#mi{width:100%;height:100%;object-fit:cover;display:none}
.snap-prog{position:absolute;top:0;left:0;right:0;height:3px;background:rgba(255,255,255,.18);z-index:20}
.snap-prog-fill{height:100%;background:#fff;width:0%;transition:width .08s linear}
.snap-top{position:absolute;top:0;left:0;right:0;z-index:15;padding:14px 14px 10px;background:linear-gradient(180deg,rgba(0,0,0,.6) 0%,transparent 100%);display:flex;align-items:center;gap:9px}
.snap-av{width:34px;height:34px;border-radius:50%;overflow:hidden;border:2px solid rgba(255,255,255,.6);flex-shrink:0;background:var(--ink4);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:.78rem;color:rgba(255,255,255,.5)}
.snap-av img{width:100%;height:100%;object-fit:cover}
.snap-info{flex:1;min-width:0}
.snap-name{font-size:.82rem;font-weight:700;color:#fff;line-height:1}
.snap-time{font-size:.58rem;color:rgba(255,255,255,.6);margin-top:2px;font-family:'Fira Code',monospace}
.snap-type-badge{font-size:.56rem;font-weight:700;letter-spacing:.05em;font-family:'Fira Code',monospace;padding:3px 8px;border-radius:4px}
.snap-type-badge.v{background:rgba(86,207,255,.15);color:var(--hi);border:1px solid rgba(86,207,255,.2)}
.snap-type-badge.i{background:rgba(255,255,255,.1);color:rgba(255,255,255,.6);border:1px solid rgba(255,255,255,.1)}
.snap-bot{position:absolute;bottom:0;left:0;right:0;z-index:15;padding:10px 14px 14px;background:linear-gradient(0deg,rgba(0,0,0,.65) 0%,transparent 100%);display:flex;align-items:center;gap:8px;opacity:0;transition:opacity .18s}
.snap-stage:hover .snap-bot{opacity:1}
.s-btn{background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.15);color:rgba(255,255,255,.85);border-radius:7px;width:30px;height:30px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:.72rem;transition:all .12s;flex-shrink:0;backdrop-filter:blur(8px)}
.s-btn:hover{background:rgba(0,0,0,.65);color:#fff;border-color:rgba(255,255,255,.3)}
.vol-grp{display:flex;align-items:center;gap:5px;flex:1}
.vol-ic{font-size:.65rem;cursor:pointer;color:rgba(255,255,255,.55);transition:color .1s}
.vol-ic:hover{color:rgba(255,255,255,.9)}
input.vol-r{-webkit-appearance:none;appearance:none;flex:1;max-width:90px;height:2px;background:rgba(255,255,255,.18);border-radius:99px;outline:none;cursor:pointer}
input.vol-r::-webkit-slider-thumb{-webkit-appearance:none;width:9px;height:9px;border-radius:50%;background:#fff;cursor:pointer}
input.vol-r::-moz-range-thumb{width:9px;height:9px;border-radius:50%;background:#fff;cursor:pointer;border:none}
.counter{display:none}
.arr{position:absolute;top:50%;transform:translateY(-50%);z-index:30;width:44px;height:44px;border-radius:50%;cursor:pointer;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);color:rgba(255,255,255,.7);display:flex;align-items:center;justify-content:center;font-size:1.3rem;backdrop-filter:blur(12px);transition:all .15s;opacity:0}
.viewer:hover .arr{opacity:1}
.arr:hover{background:rgba(255,255,255,.16);color:#fff;transform:translateY(-50%) scale(1.06)}
#arr-prev{left:20px}
#arr-next{right:20px}
.tap-zone{display:none}
@media(max-width:768px){
  .tap-zone{display:block;position:absolute;top:0;bottom:0;width:38%;z-index:10;cursor:pointer;background:transparent}
  #tap-prev{left:0}
  #tap-next{right:0}
}
.tap-center{position:absolute;top:15%;bottom:15%;left:22%;right:22%;z-index:11;cursor:pointer;background:transparent}
.snap-idx{display:none}
.autoplay-tog{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);z-index:20;display:flex;align-items:center;gap:6px;font-size:.6rem;color:rgba(255,255,255,.4);cursor:pointer;user-select:none;opacity:0;transition:opacity .18s}
.viewer:hover .autoplay-tog{opacity:1}
.tgl{width:28px;height:15px;background:rgba(255,255,255,.15);border-radius:99px;position:relative;transition:background .17s}
.tgl.on{background:var(--hi)}
.tgl-k{position:absolute;top:2px;left:2px;width:11px;height:11px;background:#fff;border-radius:50%;transition:left .16s;box-shadow:0 1px 3px rgba(0,0,0,.4)}
.tgl.on .tgl-k{left:15px}
.viewer-empty{position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:rgba(255,255,255,.2);pointer-events:none}
.viewer-empty-icon{display:none}
.viewer-empty-txt{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;font-weight:600}
.snap-stage:fullscreen,
.snap-stage:-webkit-full-screen{width:100vw;height:100vh;aspect-ratio:unset;max-width:none}
.snap-stage:fullscreen #mv,
.snap-stage:-webkit-full-screen #mv{width:100%;height:100%;object-fit:contain}
.snap-stage:fullscreen #mi,
.snap-stage:-webkit-full-screen #mi{width:100%;height:100%;object-fit:contain}
.snap-stage:fullscreen .snap-bot,
.snap-stage:-webkit-full-screen .snap-bot{opacity:1}
#mv{-webkit-media-controls-enclosure:none}
#mv::-webkit-media-controls{display:none!important}

/* Toasts */
#toasts{position:fixed;top:14px;right:14px;z-index:9999;display:flex;flex-direction:column;gap:6px;pointer-events:none}
.toast{background:var(--ink4);border:1px solid var(--border2);border-top:2px solid var(--green);border-radius:14px;padding:9px 12px;display:flex;gap:10px;align-items:center;min-width:190px;max-width:260px;animation:tIn .22s cubic-bezier(.4,0,.2,1) forwards;pointer-events:auto;box-shadow:0 8px 24px rgba(0,0,0,.55)}
.toast.out{animation:tOut .18s ease forwards}
@keyframes tIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
@keyframes tOut{from{opacity:1}to{opacity:0;transform:translateY(-4px)}}
.t-av{width:28px;height:28px;border-radius:50%;overflow:hidden;flex-shrink:0;background:var(--ink3);display:flex;align-items:center;justify-content:center;font-size:.62rem;font-weight:800;color:var(--fg3)}
.t-av img{width:100%;height:100%;object-fit:cover}
.t-body{flex:1;min-width:0}
.t-name{font-size:.7rem;font-weight:700}
.t-msg{font-size:.57rem;color:var(--fg3);margin-top:1px;font-family:'Fira Code',monospace}

/* refresh indicator */

/* ── WELCOME BACK MODAL ── */
.wb-overlay{
  position:fixed;inset:0;z-index:10000;
  background:rgba(0,0,0,.72);backdrop-filter:blur(6px);
  display:flex;align-items:center;justify-content:center;
  animation:tIn .22s cubic-bezier(.4,0,.2,1);
}
.wb-overlay.hide{animation:tOut .18s ease forwards}
.wb-card{
  background:var(--ink2);border:1px solid var(--border2);
  border-top:2px solid var(--hi);border-radius:18px;
  padding:22px 24px;min-width:300px;max-width:380px;
  box-shadow:0 24px 64px rgba(0,0,0,.7);
}
.wb-title{font-size:.95rem;font-weight:800;color:var(--fg);margin-bottom:4px}
.wb-title b{color:var(--hi)}
.wb-sub{font-size:.68rem;color:var(--fg2);margin-bottom:14px;line-height:1.5}
.wb-news{margin-bottom:16px;display:flex;flex-direction:column;gap:5px}
.wb-news-item{
  display:flex;align-items:center;gap:8px;
  background:rgba(86,207,255,.06);border:1px solid rgba(86,207,255,.12);
  border-radius:6px;padding:6px 10px;
}
.wb-news-av{width:22px;height:22px;border-radius:50%;overflow:hidden;flex-shrink:0;background:var(--ink4);display:flex;align-items:center;justify-content:center;font-size:.6rem;font-weight:800;color:var(--fg3);border:1px solid var(--border)}
.wb-news-av img{width:100%;height:100%;object-fit:cover}
.wb-news-txt{font-size:.67rem;color:var(--fg);flex:1}
.wb-news-txt b{color:var(--hi);font-weight:700}
.wb-news-cnt{font-size:.6rem;font-family:'Fira Code',monospace;color:var(--green);background:rgba(54,232,168,.1);padding:1px 6px;border-radius:3px;flex-shrink:0}
.wb-resume{
  background:var(--ink3);border:1px solid var(--border);
  border-radius:7px;padding:9px 11px;margin-bottom:14px;
  display:flex;align-items:center;gap:10px;
}
.wb-resume-prev{width:32px;height:44px;border-radius:4px;overflow:hidden;flex-shrink:0;background:var(--ink4);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:.7rem;color:var(--fg3)}
.wb-resume-prev img{width:100%;height:100%;object-fit:cover}
.wb-resume-info{flex:1;min-width:0}
.wb-resume-name{font-size:.72rem;font-weight:700;color:var(--fg)}
.wb-resume-detail{font-size:.58rem;color:var(--fg3);font-family:'Fira Code',monospace;margin-top:2px}
.wb-btns{display:flex;gap:8px}
.wb-btn{
  flex:1;padding:9px 0;border-radius:7px;font-size:.72rem;font-weight:700;
  cursor:pointer;border:none;transition:all .14s;font-family:'Nunito',sans-serif;
}
.wb-btn.yes{background:var(--hi);color:var(--ink);letter-spacing:-.01em}
.wb-btn.yes:hover{background:var(--hi2)}
.wb-btn.no{background:var(--ink4);color:var(--fg2);border:1px solid var(--border2)}
.wb-btn.no:hover{background:var(--ink3);color:var(--fg)}
.wb-no-news{font-size:.63rem;color:var(--fg3);text-align:center;padding:6px 0 2px}

/* ── TODAY EXCLUSION PANEL ── */
.today-excl-toggle{font-size:.52rem;color:var(--fg3);cursor:pointer;padding:2px 6px;border-radius:4px;border:1px solid var(--border);background:transparent;transition:all .12s;font-family:"Plus Jakarta Sans",sans-serif;white-space:nowrap}
.today-excl-toggle:hover{color:var(--fg2);border-color:var(--border2)}
.today-excl-panel{padding:6px 8px;border-bottom:1px solid var(--border);background:var(--ink3);display:none;flex-direction:column;gap:3px;flex-shrink:0;max-height:220px;overflow-y:auto}
.today-excl-panel.open{display:flex}
.te-row{display:flex;align-items:center;gap:7px;padding:4px 4px;border-radius:5px;transition:background .1s}
.te-row.excluded{opacity:.45}
.te-av{width:22px;height:22px;border-radius:50%;overflow:hidden;flex-shrink:0;background:var(--ink4);display:flex;align-items:center;justify-content:center;font-size:.55rem;font-weight:800;color:var(--fg3);border:1px solid var(--border)}
.te-av img{width:100%;height:100%;object-fit:cover}
.te-name{flex:1;font-size:.68rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.te-tog{width:26px;height:14px;border-radius:99px;background:rgba(255,255,255,.12);position:relative;cursor:pointer;flex-shrink:0;transition:background .15s}
.te-tog.on{background:var(--green)}
.te-tog::after{content:"";position:absolute;top:2px;left:2px;width:10px;height:10px;border-radius:50%;background:#fff;transition:left .14s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.te-tog.on::after{left:14px}
/* ── RESUME MODAL checkbox ── */
.wb-no-show-row{margin-bottom:12px}
.wb-chk-label{display:flex;align-items:center;gap:7px;font-size:.63rem;color:var(--fg3);cursor:pointer;user-select:none}
.wb-chk-label input[type=checkbox]{accent-color:var(--hi);width:13px;height:13px;cursor:pointer}

/* ═══════════════════════════════════
   MOBILE
   ═══════════════════════════════════ */

.mob-nav{display:none}
.mob-drawer,.mob-snap-drawer{display:none}

@media(max-width:768px){
  @media(orientation:landscape){
    .mob-orientation-lock{
      display:flex!important;
      position:fixed;inset:0;z-index:99999;
      background:var(--ink);
      flex-direction:column;
      align-items:center;justify-content:center;
      gap:16px;color:var(--fg2);font-size:.9rem;font-weight:700;
    }
    .mob-orientation-icon{font-size:2.5rem;animation:rotateHint 1.5s ease infinite}
    @keyframes rotateHint{0%,100%{transform:rotate(0deg)}50%{transform:rotate(-90deg)}}
    .shell,.mob-nav,.mob-drawer,.mob-snap-drawer{display:none!important}
  }
  .panel{display:none!important}
  .snap-col{display:none!important}
  .arr{display:none!important}
  .autoplay-tog{display:none!important}

  /* body/html fixé */
  html,body{overflow:hidden;position:fixed;width:100%;height:100%}

  /* Shell = colonne verticale plein écran */
  .shell{
    display:flex!important;
    flex-direction:column!important;
    width:100vw;
    height:100%;
    overflow:hidden;
    position:relative;
  }

  /* Viewer = flex:1 pour prendre tout l'espace */
  .viewer{
    flex:1!important;
    min-height:0!important;
    width:100%;
    position:relative;
    background:#000;
    display:flex;
    align-items:stretch;
  }
  .snap-stage{
    width:100%!important;
    height:100%!important;
    aspect-ratio:unset!important;
    max-width:none!important;
    border-radius:0!important;
  }
  #mv,#mi{width:100%;height:100%;object-fit:cover}

  /* Barre nav en bas, dans le shell */
  .mob-nav{
    display:flex!important;
    flex-shrink:0;
    height:58px;
    width:100%;
    background:var(--ink2);
    border-top:1px solid var(--border);
    z-index:100;
  }
  .mob-tab{
    flex:1;
    display:flex;flex-direction:column;
    align-items:center;justify-content:center;
    gap:3px;
    cursor:pointer;
    color:var(--fg3);
    font-size:.48rem;font-weight:800;
    text-transform:uppercase;letter-spacing:.04em;
    border:none;background:none;
    padding:6px 0;
    position:relative;
    -webkit-tap-highlight-color:transparent;
    transition:color .12s;
  }
  .mob-tab.on{color:var(--hi)}
  .mob-tab svg{width:20px;height:20px;display:block;transition:transform .15s}
  .mob-tab.on svg{transform:scale(1.15)}
  .mob-badge{
    position:absolute;top:4px;right:calc(50% - 20px);
    min-width:16px;height:16px;border-radius:99px;
    background:var(--red);color:#fff;
    font-size:.46rem;font-weight:900;
    display:none;align-items:center;justify-content:center;
    padding:0 4px;
  }

  /* tap zones cachées — on gere via click direct sur le stage */
  .tap-zone{display:none!important}
  .tap-center{display:none!important}

  /* today-chip visible dans le drawer profils mobile */
  #today-chip{display:flex}

  /* contrôles vidéo */
  .snap-bot{display:none!important}
  .snap-top{padding:10px 12px 8px}
  #snap-badge{display:none!important}

  /* Drawers = position:fixed, z-index élevé + animation */
  @keyframes drawerIn{from{transform:translateY(100%);opacity:0}to{transform:translateY(0);opacity:1}}
  @keyframes drawerOut{from{transform:translateY(0);opacity:1}to{transform:translateY(100%);opacity:0}}
  @keyframes mobFadeIn{from{opacity:0}to{opacity:1}}
  @keyframes snapFlash{0%{opacity:.6}100%{opacity:1}}
  @keyframes tabPop{0%{transform:scale(1)}50%{transform:scale(1.25)}100%{transform:scale(1)}}

  .mob-drawer,.mob-snap-drawer{
    display:none;
    position:fixed;inset:0;
    z-index:9000;
    background:rgba(0,0,0,.55);
    backdrop-filter:blur(8px);
    align-items:flex-end;
    animation:mobFadeIn .18s ease;
  }
  .mob-drawer.open,.mob-snap-drawer.open{display:flex!important}

  .mob-sheet,.mob-snap-sheet{
    width:100%;max-height:85vh;
    background:var(--ink2);
    border-radius:22px 22px 0 0;
    border-top:2px solid var(--border2);
    display:flex;flex-direction:column;
    overflow:hidden;
    animation:drawerIn .28s cubic-bezier(.34,1.3,.64,1);
  }
  .mob-sheet-handle{
    width:38px;height:4px;border-radius:99px;
    background:var(--border2);
    margin:10px auto 4px;flex-shrink:0;
  }
  .mob-sheet-title{
    font-size:.88rem;font-weight:900;
    padding:6px 18px 12px;
    flex-shrink:0;
    border-bottom:1px solid var(--border);
    display:flex;align-items:center;justify-content:space-between;
  }
  .mob-sheet-close{
    width:28px;height:28px;border-radius:50%;
    background:var(--ink4);border:1px solid var(--border);
    color:var(--fg2);cursor:pointer;
    display:flex;align-items:center;justify-content:center;
  }
  .mob-sheet-close svg{width:14px;height:14px}
  .mob-sheet-body{overflow-y:auto;flex:1;padding:4px 0 20px}
  .mob-snaps-scroll{overflow-y:auto;flex:1}
  #mob-hist-list{display:flex;flex-direction:column;overflow:hidden}
  #mob-hist-list > div:last-child{overflow-y:auto;flex:1}

  /* Profils drawer items */
  .mob-pi{
    display:flex;align-items:center;gap:14px;
    padding:12px 18px;
    border-bottom:1px solid rgba(255,255,255,.04);
    cursor:pointer;
    -webkit-tap-highlight-color:transparent;
  }
  .mob-pi.on{background:rgba(86,207,255,.07)}
  .mob-pi .av{width:44px;height:44px;font-size:.95rem;flex-shrink:0}
  .mob-pi-info{flex:1;min-width:0}
  .mob-pi-name{font-size:.92rem;font-weight:800}
  .mob-pi.on .mob-pi-name{color:var(--hi)}
  .mob-pi-sub{font-size:.62rem;color:var(--fg3);margin-top:2px}
  .mob-pi-badge{
    min-width:20px;height:20px;border-radius:99px;
    background:var(--red);color:#fff;
    font-size:.52rem;font-weight:900;
    display:none;align-items:center;justify-content:center;
    padding:0 5px;
  }

  /* Snaps drawer filtres */
  .mob-filters{
    display:flex;gap:6px;padding:8px 14px;
    border-bottom:1px solid var(--border);
    flex-shrink:0;overflow-x:auto;
  }
  .mob-filters::-webkit-scrollbar{display:none}
  .mob-sort-row{
    display:flex;gap:6px;padding:5px 14px 7px;
    border-bottom:1px solid var(--border);
    flex-shrink:0;align-items:center;
  }
  .mob-sort-lbl{font-size:.52rem;color:var(--fg3);text-transform:uppercase;letter-spacing:.07em}

  /* Snap items plus grands + animation */
  .si{padding:8px 14px;animation:mobFadeIn .2s ease both}
  .si-img{width:40px;height:56px}
  .si-ph{width:40px;height:56px}
  .si-num{font-size:.75rem}
  /* Tab pop animation quand nouveau snap */
  .mob-tab.new-ping svg{animation:tabPop .4s ease}
  /* Toast animé */
  .toast{animation:drawerIn .22s cubic-bezier(.34,1.2,.64,1)}
  /* Profil item animation */
  .mob-pi{transition:background .12s,transform .1s}
  .mob-pi:active{transform:scale(.97);background:var(--ink3)}
  /* Hist sous-onglets */
  .mob-hist-tabs{display:flex;border-bottom:1px solid var(--border);flex-shrink:0}
  .mob-hist-tab{flex:1;padding:10px 0;text-align:center;font-size:.65rem;font-weight:800;
    color:var(--fg3);cursor:pointer;border-bottom:2px solid transparent;transition:all .13s}
  .mob-hist-tab.on{color:var(--hi);border-bottom-color:var(--hi)}
  /* Filtre notifs dans profils */
  .mob-notif-row{display:flex;align-items:center;justify-content:space-between;
    padding:8px 18px;border-bottom:1px solid rgba(255,255,255,.04)}
  .mob-notif-lbl{font-size:.75rem;font-weight:700}
  .mob-notif-sub{font-size:.58rem;color:var(--fg3);margin-top:1px}
  .mob-notif-tgl{width:36px;height:20px;border-radius:99px;background:rgba(255,255,255,.12);
    position:relative;cursor:pointer;flex-shrink:0;transition:background .15s}
  .mob-notif-tgl.on{background:var(--green)}
  .mob-notif-tgl::after{content:"";position:absolute;top:3px;left:3px;width:14px;height:14px;
    border-radius:50%;background:#fff;transition:left .14s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
  .mob-notif-tgl.on::after{left:19px}
  /* Reprendre items */
  .mob-resume-item{display:flex;align-items:center;gap:10px;padding:10px 16px;
    border-bottom:1px solid rgba(255,255,255,.04);cursor:pointer;transition:background .1s}
  .mob-resume-item:active{background:var(--ink3)}
  .mob-resume-thumb{width:40px;height:56px;border-radius:8px;object-fit:cover;
    border:1px solid var(--border);flex-shrink:0}
  .mob-resume-ph{width:40px;height:56px;border-radius:8px;background:var(--ink4);
    border:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;
    justify-content:center;font-size:.9rem}
  .mob-resume-info{flex:1;min-width:0}
  .mob-resume-name{font-size:.82rem;font-weight:800}
  .mob-resume-detail{font-size:.6rem;color:var(--fg3);margin-top:2px;font-family:Fira Code,monospace}
  /* Filtre profils pour today/hier */
  .mob-day-filter{display:flex;gap:5px;padding:6px 14px;border-bottom:1px solid var(--border);
    flex-shrink:0;overflow-x:auto}
  .mob-day-filter::-webkit-scrollbar{display:none}
  .mob-df-btn{padding:4px 10px;border-radius:99px;font-size:.6rem;font-weight:800;
    border:1px solid var(--border2);color:var(--fg3);background:transparent;cursor:pointer;
    white-space:nowrap;transition:all .12s;-webkit-tap-highlight-color:transparent}
  .mob-df-btn.on{background:rgba(86,207,255,.12);color:var(--hi);border-color:rgba(86,207,255,.3)}

  /* Toasts */
  #toasts{top:auto;bottom:66px;left:10px;right:10px;align-items:stretch}
  .toast{width:100%;max-width:100%;min-width:0}
}
"""

    # ── JS ───────────────────────────────────────────────────────────────
    js = r"""
var ALL     = __ALL_DATA__;
var PROFS   = __PROFILES__;
var AVATARS = __AVATARS__;
var CATS    = __CATEGORIES__;
var NAMES   = __NAMES__;
var NLOGS   = __NEW_LOGS__;
var LB      = __LB_ROWS__;
var TODAY_S = __TODAY_STR__;
var YEST_S  = __YEST_STR__;
var TODAY_B = __TODAY_BOUNDS__;
var YEST_B  = __YEST_BOUNDS__;
// Recalcul TODAY_B/YEST_B en heure Paris cote client (plus precis que serveur)
(function() {
  try {
    function parisMidnightUnix(daysOffset) {
      var now = new Date();
      var target = new Date(now.getTime() + (daysOffset||0)*86400000);
      // Formatter en heure Paris pour extraire la date locale
      var fmt = new Intl.DateTimeFormat('en-CA', {timeZone:'Europe/Paris'});
      var dateStr = fmt.format(target); // YYYY-MM-DD
      // Minuit Paris = dateStr T 00:00:00 dans la TZ Paris -> convertir en UTC
      var parisMidnight = new Date(dateStr + 'T00:00:00');
      // Calculer l offset Paris reel pour ce jour
      var utcMs = parisMidnight.getTime();
      var parisMs = new Date(parisMidnight.toLocaleString('en-US', {timeZone:'Europe/Paris'})).getTime();
      var localMs = parisMidnight.getTime();
      var offset = parisMs - utcMs;
      return Math.floor((utcMs - offset) / 1000);
    }
    var t0 = parisMidnightUnix(0);
    TODAY_B = [t0, t0 + 86400];
    var y0 = parisMidnightUnix(-1);
    YEST_B  = [y0, y0 + 86400];
  } catch(e) {}
})();

/* ── state ── */
var curProf = null;
var queue   = [];
var qMode   = 'profile';
var qi      = -1;
var autoP   = true;
var filt    = 'all';
var srt     = 'chrono';
var newCnts = {};
var logs    = [];
var imgT    = null;
var idxT    = null;
var lastUpdated = 0;

/* ── DOM ── */
var mv      = document.getElementById('mv');
var mi      = document.getElementById('mi');
var sl      = document.getElementById('snap-list');
var pf      = document.getElementById('pbar-fill');
var pbar    = document.getElementById('pbar');
var bPause  = document.getElementById('btn-pause');
var bFS     = document.getElementById('btn-fs');
var volR    = document.getElementById('vol');
var volI    = document.getElementById('vol-ico');
var scTitle = document.getElementById('sc-title');
var scCnt   = document.getElementById('sc-cnt');
var sName   = document.getElementById('snap-name');
var sTime   = document.getElementById('snap-time');
var sAvEl   = document.getElementById('snap-av');
var sBadge  = document.getElementById('snap-badge');
var sCounter= document.getElementById('snap-counter');
var blurBg  = document.getElementById('viewer-blur');
var emptyEl = document.getElementById('viewer-empty');
var idxEl   = document.getElementById('snap-idx');
var tglEl   = document.getElementById('tgl');

/* ── tabs ── */
function switchTab(t) {
  document.querySelectorAll('.pane').forEach(function(el){ el.classList.remove('on'); });
  document.querySelectorAll('.tab').forEach(function(el){ el.classList.remove('on'); });
  document.getElementById('pane-' + t).classList.add('on');
  document.getElementById('tab-' + t).classList.add('on');
  if (t === 'hist') buildHist();
}

/* ── categories ── */
var catVals = [];
Object.values(CATS).forEach(function(c){ if (catVals.indexOf(c) < 0) catVals.push(c); });
var catBar = document.getElementById('cat-bar');
function mkCp(label, cat) {
  var b = document.createElement('button');
  b.className = 'cp' + (cat === 'all' ? ' on' : '');
  b.textContent = label;
  b.onclick = function() {
    document.querySelectorAll('.cp').forEach(function(x){ x.classList.remove('on'); });
    b.classList.add('on');
    document.querySelectorAll('.pi').forEach(function(el) {
      el.classList.toggle('cat-off', cat !== 'all' && CATS[el.dataset.p] !== cat);
    });
  };
  return b;
}
catBar.appendChild(mkCp('Tous', 'all'));
catVals.forEach(function(c){ catBar.appendChild(mkCp(c, c)); });

/* ── avatar helper ── */
function avHtml(p, size) {
  var src = AVATARS[p] || '';
  var name = NAMES[p] || p;
  var ini = name[0] || '?';
  if (src) return '<img src="' + src + '" alt="" loading="lazy" onerror="this.parentElement.textContent=' + "'" + ini + "'" + '">';
  return ini;
}

/* ── profiles ── */
function buildProfiles() {
  var cont = document.getElementById('prof-list');
  cont.innerHTML = '';
  PROFS.forEach(function(p) {
    var snaps = ALL[p] || [];
    var el = document.createElement('div');
    el.className = 'pi' + (p === curProf ? ' on' : '');
    el.id = 'pi-' + p; el.dataset.p = p;
    el.innerHTML =
      '<div class="av">' + avHtml(p) + '</div>' +
      '<div class="pi-text">' +
        '<div class="pi-name">' + (NAMES[p] || p) + '</div>' +
        '<div class="pi-sub">' +
          '<span class="pi-n">' + snaps.length + '</span>' +
          '<span class="pi-cat">' + (CATS[p] || '') + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="pi-badge" id="pib-' + p + '">' + (newCnts[p] || 0) + '</div>';
    el.onclick = function(){ selProf(p); };
    cont.appendChild(el);
  });
}

/* ── leaderboard ── */
function buildLB() {
  var max = LB.reduce(function(m,r){ return Math.max(m,r[3]); }, 1);
  var cont = document.getElementById('lb-cont');
  cont.innerHTML = '';
  LB.forEach(function(r) {
    var p=r[0],name=r[1],rank=r[2],tot=r[3],vids=r[4],imgs=r[5],nw=r[6];
    var pct = Math.round(tot/max*100);
    var el = document.createElement('div');
    el.className = 'lb-item';
    el.innerHTML =
      '<div class="lb-top">' +
        '<div class="lb-pos">#'+rank+'</div>' +
        '<div class="lb-av">' + avHtml(p) + '</div>' +
        '<div class="lb-name">' + name + '</div>' +
        (nw>0 ? '<div class="lb-new">+'+nw+'</div>' : '') +
      '</div>' +
      '<div class="lb-grid">' +
        '<div class="lb-cell"><span class="lb-val">'+tot+'</span><span class="lb-lbl">snaps</span></div>' +
        '<div class="lb-cell"><span class="lb-val" style="color:var(--hi)">'+vids+'</span><span class="lb-lbl">vidéos</span></div>' +
        '<div class="lb-cell"><span class="lb-val" style="color:var(--fg2)">'+imgs+'</span><span class="lb-lbl">images</span></div>' +
      '</div>' +
      '<div class="lb-bar"><div class="lb-fill" data-p="'+pct+'" style="width:0%"></div></div>';
    el.onclick = function(){ selProf(p); switchTab('profiles'); };
    cont.appendChild(el);
  });
  setTimeout(function(){
    document.querySelectorAll('.lb-fill').forEach(function(el){ el.style.width = el.dataset.p + '%'; });
  }, 120);
}

/* ── historique ── */
function buildHist() {
  var cont = document.getElementById('hist-cont');
  if (!logs.length) { cont.innerHTML = '<div class="hist-empty">Aucun nouveau snap</div>'; return; }
  cont.innerHTML = '';
  logs.slice().reverse().forEach(function(e) {
    var el = document.createElement('div');
    el.className = 'hist-item';
    var prevH = '';
    if (e.preview) {
      prevH = '<div class="hist-prev"><img src="' + e.preview + '" alt="" loading="lazy"><div class="hist-prev-play">▶</div></div>';
    } else {
      prevH = '<div class="hist-prev"><span>' + (e.type === 'VIDEO' ? '🎬' : '🖼') + '</span></div>';
    }
    el.innerHTML =
      '<div class="hist-dot"></div>' +
      '<div class="hist-body">' +
        '<div class="hist-who">' + (NAMES[e.profile] || e.profile) + '</div>' +
        '<div class="hist-detail">#' + e.idx + ' · ' + e.type + ' · ' + e.ts_pub + '</div>' +
      '</div>' +
      '<div class="hist-ts">' + e.ts + '</div>' +
      prevH;
    el.onclick = function() {
      selProf(e.profile);
      switchTab('profiles');
      // Trouver et jouer le snap correspondant
      setTimeout(function() {
        var idx = findSnapInQueue(e.profile, e.idx);
        if (idx >= 0) playAt(idx);
      }, 100);
    };
    cont.appendChild(el);
  });
}

function findSnapInQueue(profile, snapIdx) {
  for (var i = 0; i < queue.length; i++) {
    if (queue[i].profile === profile && queue[i].index === snapIdx) return i;
  }
  return -1;
}

function clearHist() { logs = []; buildHist(); }

/* ── today ── */
function inBounds(s, b) { return s.ts_unix >= b[0] && s.ts_unix < b[1]; }
function todayMode() {
  qMode = 'today'; qi = -1;
  document.querySelectorAll('.pi').forEach(function(el){ el.classList.remove('on'); });
  document.getElementById('today-chip').classList.add('on');
  var snaps = getToday();
  queue = snaps;
  filt = 'all'; srt = 'chrono';
  resetFilterBtns();
  buildSnapList(snaps, true);
  scTitle.textContent = "Aujourd'hui";
  scCnt.textContent   = snaps.length + ' snaps';
}
document.getElementById('today-chip').onclick = todayMode;

/* ── select profile ── */
function selProf(p) {
  curProf = p; qi = -1; qMode = 'profile';
  document.querySelectorAll('.pi').forEach(function(el){ el.classList.remove('on'); });
  var pi = document.getElementById('pi-' + p);
  if (pi) pi.classList.add('on');
  document.getElementById('today-chip').classList.remove('on');
  newCnts[p] = 0;
  var b = document.getElementById('pib-' + p);
  if (b) b.style.display = 'none';
  updBadge();
  var snaps = ALL[p] || [];
  queue = snaps.slice();
  filt = 'all'; srt = 'chrono';
  resetFilterBtns();
  buildSnapList(snaps, false);
  scTitle.textContent = NAMES[p] || p;
  scCnt.textContent   = snaps.length + ' snaps';
}

function resetFilterBtns() {
  document.querySelectorAll('.sf').forEach(function(b,i){ b.classList.toggle('on', i===0); });
  document.querySelectorAll('.sb').forEach(function(b){ b.classList.remove('on'); });
  var asc = document.getElementById('sort-asc'); if(asc) asc.classList.add('on');
}

/* ── snap list ── */
function buildSnapList(snaps, showWho) {
  sl.innerHTML = '';
  // ── FIX TRI: sort stable numérique sur ts_unix ──
  var sorted;
  if (srt === 'recent') {
    sorted = snaps.slice().sort(function(a, b) {
      var ta = a.ts_unix || 0;
      var tb = b.ts_unix || 0;
      if (tb !== ta) return tb - ta;
      return b.index - a.index;
    });
  } else {
    sorted = snaps.slice().sort(function(a, b) {
      var ta = a.ts_unix || 0;
      var tb = b.ts_unix || 0;
      if (ta !== tb) return ta - tb;
      return a.index - b.index;
    });
  }
  queue = sorted;
  sorted.forEach(function(s, i) {
    var el = document.createElement('div');
    el.className = 'si' + (s.isnew ? ' isnew' : '');
    el.id = 'si-' + i;
    el.dataset.t   = s.type===1 ? 'v' : 'i';
    el.dataset.new = s.isnew ? '1' : '0';
    var isv = s.type === 1;
    var thH = s.preview
      ? '<img class="si-img" src="' + s.preview + '" loading="lazy" alt="">'
      : '<div class="si-ph">' + (isv ? '🎬' : '🖼') + '</div>';
    var whoH = showWho ? '<div class="si-who">' + (NAMES[s.profile]||s.profile||'') + '</div>' : '';
    var tsDisplay = s.ts_short || s.ts || '';
    el.innerHTML = thH +
      '<div class="si-info">' +
        '<div class="si-num">#' + s.index + (s.isnew ? '<span class="si-newtag">NEW</span>' : '') + '</div>' +
        whoH +
        '<div class="si-type ' + (isv?'v':'i') + '">' + (isv?'VIDEO':'IMAGE') + '</div>' +
        '<div class="si-ts">' + tsDisplay + '</div>' +
      '</div>';
    el.onclick = function(){ playAt(i); };
    sl.appendChild(el);
  });
  applyFilt();
}

function setFilt(f, btn) {
  filt = f;
  document.querySelectorAll('.sf').forEach(function(b){ b.classList.remove('on'); });
  btn.classList.add('on');
  applyFilt();
}
function applyFilt() {
  var cnt = 0;
  document.querySelectorAll('.si').forEach(function(el) {
    var h = (filt==='v' && el.dataset.t!=='v') || (filt==='i' && el.dataset.t!=='i') || (filt==='new' && el.dataset.new!=='1');
    el.classList.toggle('off', h);
    if (!h) cnt++;
  });
  scCnt.textContent = cnt + ' snaps';
}
function setSort(s, btn) {
  srt = s;
  document.querySelectorAll('.sb').forEach(function(b){ b.classList.remove('on'); });
  btn.classList.add('on');
  var currentSnap = (qi >= 0 && queue[qi]) ? queue[qi] : null;
  var base = qMode==='today' ? getToday() : (ALL[curProf]||[]);
  buildSnapList(base, qMode!=='profile');
  if (currentSnap) {
    for (var i = 0; i < queue.length; i++) {
      if (queue[i].profile === currentSnap.profile && queue[i].index === currentSnap.index) {
        qi = i;
        document.querySelectorAll('.si').forEach(function(el){ el.classList.remove('cur','playing'); });
        var el = document.getElementById('si-' + i);
        if (el) {
          el.classList.add('cur');
          el.scrollIntoView({block:'nearest', behavior:'smooth'});
        }
        sCounter.textContent = (i+1) + ' / ' + queue.length;
        break;
      }
    }
  }
}

/* ── play ── */
function playAt(i) {
  if (i < 0 || i >= queue.length) return;
  clearTimeout(imgT);
  if (qi >= 0) { var o = document.getElementById('si-' + qi); if(o) o.classList.remove('cur','playing'); }
  qi = i;
  var s = queue[i], isv = s.type===1;
  var el = document.getElementById('si-' + i);
  if (el) { el.classList.add('cur','playing'); el.scrollIntoView({block:'nearest',behavior:'smooth'}); }

  pf.style.transition = 'none'; pf.style.width = '0%';
  bPause.textContent = 'II';
  // counter supprimé

  var pname = NAMES[s.profile] || s.profile || '';
  sName.textContent = pname;
  sTime.textContent = s.ts || '';
  sBadge.textContent = isv ? 'VIDEO' : 'IMAGE';
  sBadge.className = 'snap-type-badge ' + (isv ? 'v' : 'i');

  var avSrc = AVATARS[s.profile] || '';
  if (avSrc) {
    sAvEl.innerHTML = '<img src="' + avSrc + '" alt="">';
  } else {
    sAvEl.innerHTML = pname[0] || '?';
  }

  var previewSrc = s.preview || s.url || '';
  if (previewSrc) blurBg.style.backgroundImage = 'url(' + previewSrc + ')';
  emptyEl.style.display = 'none';

  // snap-idx supprimé

  saveSession();

  if (isv) {
    mv.oncanplay = null;
    mv.volume = volR.value / 100;
    mi.style.display = 'none';
    mv.style.display = 'block';
    mv.src = s.url;
    mv.play().catch(function(){});
  } else {
    mv.pause(); mv.src=''; mv.style.display='none';
    mi.style.display='block';
    mi.src = s.url || s.preview;
    setTimeout(function(){
      pf.style.transition='width 3s linear'; pf.style.width='100%';
    }, 50);
    if (autoP) imgT = setTimeout(function(){ if(qi===i) navNext(); }, 3100);
  }
}

/* ── video events ── */
mv.addEventListener('timeupdate', function(){
  if (mv.duration) pf.style.width = (mv.currentTime/mv.duration*100) + '%';
});
mv.addEventListener('ended', function(){
  var o = document.getElementById('si-'+qi); if(o) o.classList.remove('playing');
  if (autoP) {
    pf.style.transition = 'none'; pf.style.width = '0%';
    navNext();
  }
});
mv.addEventListener('play', function(){
  var el = document.getElementById('si-'+qi); if(el) el.classList.add('playing');
  bPause.textContent = 'II';
});
mv.addEventListener('pause', function(){ bPause.textContent = '>'; });

pbar.onclick = function(e){
  if (queue[qi]&&queue[qi].type===1&&mv.duration) {
    var r=pbar.getBoundingClientRect();
    mv.currentTime=((e.clientX-r.left)/r.width)*mv.duration;
  }
};

bPause.onclick = function(){
  if (mv.style.display!=='none') { mv.paused?mv.play().catch(function(){}):mv.pause(); }
};

/* ── fullscreen ── */
function isFS(){ return !!(document.fullscreenElement||document.webkitFullscreenElement); }
function updFS(){
  bFS.textContent = isFS() ? 'X' : '[]';
  bFS.title = isFS() ? 'Quitter' : 'Plein ecran';
}
document.addEventListener('fullscreenchange', updFS);
document.addEventListener('webkitfullscreenchange', updFS);
bFS.onclick = function(){
  var el = document.getElementById('snap-stage');
  if (isFS()) {
    (document.exitFullscreen||document.webkitExitFullscreen||document.mozCancelFullScreen||function(){}).call(document);
  } else {
    var req = el.requestFullscreen||el.webkitRequestFullscreen||el.mozRequestFullScreen;
    if (req) req.call(el);
  }
};

/* ── volume ── */
volR.oninput = function(){
  var v=volR.value/100; mv.volume=v; mv.muted=v===0;
  volI.textContent = v===0?'🔇':v<0.4?'🔉':'🔊';
};
volI.onclick = function(){
  mv.muted=!mv.muted;
  volI.textContent=mv.muted?'🔇':'🔊';
  if(!mv.muted) volR.value=Math.max(mv.volume*100,20);
};

/* ── arrows ── */
function navPrev(){ playAt(srt==='recent' ? qi+1 : qi-1); }
function navNext(){ playAt(srt==='recent' ? qi-1 : qi+1); }
document.getElementById('arr-prev').onclick = navPrev;
document.getElementById('arr-next').onclick = navNext;
document.getElementById('tap-prev').onclick  = navPrev;
document.getElementById('tap-next').onclick  = navNext;
document.getElementById('tap-center').onclick = function(){
  if (mv.style.display !== 'none') {
    mv.paused ? mv.play().catch(function(){}) : mv.pause();
  }
};

/* ── keyboard ── */
document.addEventListener('keydown', function(e){
  if (['INPUT','TEXTAREA'].indexOf(document.activeElement.tagName)>=0) return;
  if (e.key==='ArrowRight'||e.key==='ArrowDown'){e.preventDefault();navNext();}
  if (e.key==='ArrowLeft' ||e.key==='ArrowUp')  {e.preventDefault();navPrev();}
  if (e.key===' '){e.preventDefault();bPause.click();}
  if (e.key==='f'||e.key==='F') bFS.click();
  if (e.key==='m'||e.key==='M') volI.click();
});

/* ── autoplay ── */
document.getElementById('auto-tog').onclick = function(){
  autoP=!autoP; tglEl.classList.toggle('on',autoP);
};

/* ── toast ── */
function showToast(profile, idx, type) {
  // Sur mobile : afficher seulement si notifs activées pour ce profil
  if ('ontouchstart' in window && !mobNotifEnabled[profile]) return;
  var wrap=document.getElementById('toasts');
  var el=document.createElement('div');
  el.className='toast';
  el.style.animation='drawerIn .22s cubic-bezier(.34,1.2,.64,1)';
  el.innerHTML='<div class="t-av">'+avHtml(profile)+'</div><div class="t-body"><div class="t-name">'+(NAMES[profile]||profile)+'</div><div class="t-msg">#'+idx+' · '+type+'</div></div>';
  wrap.appendChild(el);
  el.onclick=function(){selProf(profile);if('ontouchstart' in window)mobTabSnaps();else switchTab('profiles');};
  // Tab ping animation sur mobile
  if ('ontouchstart' in window) {
    var tab = document.getElementById('mob-tab-profs');
    if (tab) { tab.classList.add('new-ping'); setTimeout(function(){ tab.classList.remove('new-ping'); }, 500); }
  }
  setTimeout(function(){el.classList.add('out');setTimeout(function(){el.remove();},180);},4500);
}

/* ── badge ── */
function updBadge(){
  var t=Object.values(newCnts).reduce(function(a,b){return a+b;},0);
}

/* ── today count ── */
function updTodayCnt(){
  var el=document.getElementById('today-cnt');
  if(el) el.textContent=getToday().length;
}

/* ── init logs ── */
function initLogs(){
  Object.keys(NLOGS).forEach(function(p){
    (NLOGS[p]||[]).forEach(function(l){
      logs.push({ts:l.ts,profile:p,idx:l.idx,type:l.type,ts_pub:l.ts_pub,preview:l.preview||'',url:l.url||''});
    });
  });
  logs.sort(function(a,b){return a.ts.localeCompare(b.ts);});
}

/* ══════════════════════════════════════════════
   AUTO-REFRESH : recharge data.json toutes les 15s
   sans recharger la page
   ══════════════════════════════════════════════ */
var REFRESH_MS = 15000;
var refreshBar = null;
var refreshStart = Date.now();

function animRefreshBar() {
  var elapsed = Date.now() - refreshStart;
  var pct = Math.min((elapsed / REFRESH_MS) * 100, 100);
  if (refreshBar) refreshBar.style.width = pct + '%';
  if (pct < 100) requestAnimationFrame(animRefreshBar);
}

function applyNewData(data) {
  if (!data || data.updated_at <= lastUpdated) return;
  lastUpdated = data.updated_at;

  var hadNew = false;

  if (data.avatars) {
    Object.keys(data.avatars).forEach(function(p) {
      if (data.avatars[p]) AVATARS[p] = data.avatars[p];
    });
  }

  if (data.profiles) {
    Object.keys(data.profiles).forEach(function(p) {
      var oldLen = (ALL[p] || []).length;
      var newSnaps = data.profiles[p] || [];
      if (newSnaps.length > oldLen) {
        var diff = newSnaps.length - oldLen;
        newCnts[p] = (newCnts[p] || 0) + diff;
        hadNew = true;
        var newest = newSnaps.filter(function(s){ return s.isnew; });
        newest.forEach(function(s) {
          showToast(p, s.index, s.type===1?'VIDEO':'IMAGE');
        });
        var b = document.getElementById('pib-' + p);
        if (b) { b.textContent = newCnts[p]; b.style.display = 'flex'; }
      }
      ALL[p] = newSnaps;
    });
  }

  if (data.new_logs) {
    var allNewLogs = [];
    Object.keys(data.new_logs).forEach(function(p) {
      (data.new_logs[p] || []).forEach(function(l) {
        allNewLogs.push({ts:l.ts,profile:p,idx:l.idx,type:l.type,ts_pub:l.ts_pub,preview:l.preview||'',url:l.url||''});
      });
    });
    allNewLogs.sort(function(a,b){ return a.ts.localeCompare(b.ts); });
    if (allNewLogs.length > logs.length) {
      logs = allNewLogs;
      var histPane = document.getElementById('pane-hist');
      if (histPane && histPane.classList.contains('on')) buildHist();
    }
  }

  if (data.lb) {
    LB.length = 0;
    data.lb.forEach(function(r){ LB.push(r); });
    var lbPane = document.getElementById('pane-lb');
    if (lbPane && lbPane.classList.contains('on')) buildLB();
  }

  buildProfiles();
  var pi = document.getElementById('pi-' + curProf);
  if (pi) pi.classList.add('on');

  if (ALL[curProf]) {
    var base = qMode === 'today' ? getToday() : (ALL[curProf]||[]);
    var prevSnap = queue[qi];
    buildSnapList(base, qMode !== 'profile');
    if (prevSnap) {
      for (var i = 0; i < queue.length; i++) {
        if (queue[i].profile === prevSnap.profile && queue[i].index === prevSnap.index) {
          qi = i;
          var el = document.getElementById('si-' + i);
          if (el) el.classList.add('cur');
          break;
        }
      }
    }
  }

  updTodayCnt();
  updBadge();
}

function fetchLiveData() {
  refreshStart = Date.now();
  animRefreshBar();

  fetch('data.json?t=' + Date.now())
    .then(function(r){ return r.json(); })
    .then(function(data){ applyNewData(data); })
    .catch(function(e){ console.warn('Auto-refresh err:', e); });

  setTimeout(fetchLiveData, REFRESH_MS);
}

/* ══════════════════════════════════════════════
   TODAY EXCLUSIONS
   ══════════════════════════════════════════════ */
var todayExcluded = {};  // { profile: true/false }
try {
  var _te = localStorage.getItem('snapmon_today_excl');
  if (_te) todayExcluded = JSON.parse(_te);
} catch(e) {}

function saveTodayExcluded() {
  try { localStorage.setItem('snapmon_today_excl', JSON.stringify(todayExcluded)); } catch(e) {}
}

function getToday() {
  var all = [];
  PROFS.forEach(function(p){
    if (todayExcluded[p]) return;
    (ALL[p]||[]).forEach(function(s){ if(inBounds(s,TODAY_B)) all.push(s); });
  });
  all.sort(function(a,b){ return a.ts_unix-b.ts_unix; });
  return all;
}

function toggleTodayExclPanel() {
  var panel = document.getElementById('today-excl-panel');
  var btn   = document.getElementById('today-excl-btn');
  if (!panel) return;
  panel.classList.toggle('open');
  btn.style.color = panel.classList.contains('open') ? 'var(--hi)' : '';
  btn.style.borderColor = panel.classList.contains('open') ? 'rgba(86,207,255,.3)' : '';
  if (panel.classList.contains('open')) buildTodayExclPanel();
}

function buildTodayExclPanel() {
  var el = document.getElementById('today-excl-panel');
  if (!el) return;
  el.innerHTML = '';
  PROFS.forEach(function(p) {
    var isExcl = !!todayExcluded[p];
    var row = document.createElement('div');
    row.className = 'te-row' + (isExcl ? ' excluded' : '');
    row.innerHTML =
      '<div class="te-av">' + avHtml(p) + '</div>' +
      '<span class="te-name">' + (NAMES[p]||p) + '</span>' +
      '<div class="te-tog' + (isExcl ? '' : ' on') + '" data-p="' + p + '"></div>';
    row.querySelector('.te-tog').onclick = function() {
      var pp = this.dataset.p;
      todayExcluded[pp] = !todayExcluded[pp];
      saveTodayExcluded();
      buildTodayExclPanel();
      updTodayCnt();
      if (qMode === 'today') {
        var snaps = getToday();
        buildSnapList(snaps, true);
        scCnt.textContent = snaps.length + ' snaps';
      }
    };
    el.appendChild(row);
  });
}

/* ══════════════════════════════════════════════
   SESSION SAVE / RESTORE
   - Sauvegarde par profil le dernier snap regardé
   - Modal "Reprendre ?" uniquement au clic sur le profil
   - Checkbox "ne plus afficher" par profil
   ══════════════════════════════════════════════ */
var SESSION_KEY    = 'snapmon_session';
var NO_RESUME_KEY  = 'snapmon_no_resume';  // global boolean

function saveSession() {
  if (qi < 0 || !queue[qi]) return;
  var s = queue[qi];
  try {
    var snap_counts = {};
    PROFS.forEach(function(p){ snap_counts[p] = (ALL[p]||[]).length; });
    // Charger sessions existantes et mettre à jour uniquement le profil en cours
    var existing = {};
    try { existing = JSON.parse(localStorage.getItem(SESSION_KEY) || '{}'); } catch(e2){}
    existing[s.profile] = {
      snap_index: s.index,
      snap_ts:    s.ts_unix,
      preview:    s.preview || '',
      ts_name:    s.ts || '',
      saved_at:   Date.now()
    };
    existing['__counts__'] = snap_counts;
    localStorage.setItem(SESSION_KEY, JSON.stringify(existing));
  } catch(e) {}
}

function loadSessionForProfile(profile) {
  try {
    var raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    var data = JSON.parse(raw);
    return data[profile] || null;
  } catch(e) { return null; }
}

function clearSessionForProfile(profile) {
  try {
    var raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return;
    var data = JSON.parse(raw);
    delete data[profile];
    localStorage.setItem(SESSION_KEY, JSON.stringify(data));
  } catch(e) {}
}

function isNoResume(profile) {
  try {
    return localStorage.getItem(NO_RESUME_KEY) === 'true';
  } catch(e) { return false; }
}

function setNoResume(profile, val) {
  try {
    localStorage.setItem(NO_RESUME_KEY, val ? 'true' : 'false');
  } catch(e) {}
}

/* Override selProf - pas de modal resume */
var _origSelProf = selProf;
selProf = function(p) {
  _origSelProf(p);
};

/* Welcome back : afficher uniquement si nouveaux snaps depuis dernière visite */
function checkWelcomeBack() {
  try {
    var raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return;
    var data = JSON.parse(raw);
    var oldCounts = data['__counts__'] || {};
    var news = [];
    PROFS.forEach(function(p) {
      var oldCount = oldCounts[p] || 0;
      var newCount = (ALL[p] || []).length;
      if (newCount > oldCount) news.push({profile:p, diff:newCount-oldCount});
    });
    if (!news.length) return; // Pas de nouveaux snaps = rien afficher
    showWelcomeBackMobile(news);
  } catch(e) {}
}

function showWelcomeBackMobile(news) {
  if (isNoResume('__welcome__')) return;
  var overlay = document.createElement('div');
  overlay.className = 'wb-overlay';
  var newsHtml = news.map(function(n) {
    return "<div class=\"wb-news-item\">" +
      "<div class=\"wb-news-av\">" + avHtml(n.profile) + "</div>" +
      "<div class=\"wb-news-txt\"><b>" + (NAMES[n.profile]||n.profile) + "</b> a posté</div>" +
      "<div class=\"wb-news-cnt\">+" + n.diff + "</div></div>";
  }).join('');
  overlay.innerHTML =
    "<div class=\"wb-card\">" +
      "<div class=\"wb-title\">Nouveaux snaps</div>" +
      "<div class=\"wb-sub\">Pendant ton absence :</div>" +
      "<div class=\"wb-news\">" + newsHtml + "</div>" +
      "<div class=\"wb-no-show-row\"><label class=\"wb-chk-label\"><input type=\"checkbox\" id=\"wb-welcome-chk\"> Ne plus afficher</label></div>" +
      "<div class=\"wb-btns\"><button class=\"wb-btn yes\" id=\"wb-ok\">OK</button></div>" +
    "</div>";
  document.body.appendChild(overlay);
  document.getElementById('wb-ok').onclick = function() {
    var chk = document.getElementById('wb-welcome-chk');
    if (chk && chk.checked) setNoResume('__welcome__', true);
    overlay.classList.add('hide');
    setTimeout(function(){ if(overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 200);
  };
  overlay.onclick = function(e){ if(e.target===overlay) document.getElementById('wb-ok').click(); };
}

window.addEventListener('beforeunload', saveSession);
window.addEventListener('pagehide',     saveSession);

/* ── boot ── */
initLogs();
buildProfiles();
buildLB();
buildHist();
updTodayCnt();
buildTodayExclPanel();

// Aucun profil sélectionné au démarrage

setTimeout(fetchLiveData, 5000);

// Welcome back uniquement si nouveaux snaps
if ('ontouchstart' in window) {
  setTimeout(checkWelcomeBack, 800);
}

// Bloquer l'orientation paysage sur mobile
if ('ontouchstart' in window && screen.orientation && screen.orientation.lock) {
  screen.orientation.lock('portrait').catch(function(){});
}

/* ══════════════════════════════════════════════
   MOBILE NAV
   ══════════════════════════════════════════════ */
var isMobile = function(){ return window.innerWidth <= 768; };

/* Snap list mobile = miroir de #snap-list */
var slOrig = document.getElementById('snap-list');
var slMob  = document.getElementById('mob-snap-list');

/* Override buildSnapList pour alimenter aussi la liste mobile */
var _origBuildSnapList = buildSnapList;
buildSnapList = function(snaps, showWho) {
  _origBuildSnapList(snaps, showWho);
  if (slMob) {
    slMob.innerHTML = slOrig.innerHTML;
    // Rebind les clics sur les items mobiles
    slMob.querySelectorAll('.si').forEach(function(el, i) {
      el.onclick = function() {
        playAt(i);
        mobCloseSnaps();
      };
    });
  }
};

/* Override playAt pour sync le highlight mobile */
var _origPlayAt2 = playAt;
playAt = function(i) {
  _origPlayAt2(i);
  // Sync highlight dans la liste mobile
  if (slMob) {
    slMob.querySelectorAll('.si').forEach(function(el){ el.classList.remove('cur','playing'); });
    var el = slMob.querySelector('#si-' + i);
    if (el) { el.classList.add('cur'); el.scrollIntoView({block:'nearest',behavior:'smooth'}); }
  }
  // Sur mobile, ne pas forcer retour viewer (l'user gère via la nav)
};

// Filtre jour actif: 'today', 'hier', ou null (profils normaux)
var mobDayMode = null;
var mobDayFilterProfs = {};
// Filtre catégorie mobile
var mobCatFilter = 'all';
// Bounds du jour actif pour filtre influenceur
var mobActiveBounds = null;
var mobActiveLabel = '';

function mobBuildProfs() {
  var cont = document.getElementById('mob-prof-list');
  if (!cont) return;
  cont.innerHTML = '';

  // ── Aujourd'hui / Hier (accès rapide, affiche tous les snaps du jour) ──
  var dayRow = document.createElement('div');
  dayRow.style.cssText = 'display:flex;gap:8px;padding:10px 16px 8px';
  [["Aujourd'hui", TODAY_B], ["Hier", YEST_B]].forEach(function(pair) {
    var label = pair[0], bounds = pair[1];
    var cnt = 0;
    PROFS.forEach(function(p){ (ALL[p]||[]).forEach(function(s){ if(inBounds(s,bounds)) cnt++; }); });
    var btn = document.createElement('button');
    btn.style.cssText = 'flex:1;padding:10px 6px;border-radius:12px;background:var(--ink3);border:1px solid var(--border);color:var(--fg);font-size:.78rem;font-weight:800;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:3px;-webkit-tap-highlight-color:transparent';
    btn.innerHTML = '<span>' + label + '</span><span style="font-size:.6rem;color:var(--hi);font-family:Fira Code,monospace">' + cnt + ' snaps</span>';
    btn.onclick = function() {
      qMode='today'; qi=-1;
      var snaps=[];
      // Inclure TOUS les profils sans filtre todayExcluded
      PROFS.forEach(function(p){ (ALL[p]||[]).forEach(function(s){ if(inBounds(s,bounds)) snaps.push(s); }); });
      snaps.sort(function(a,b){ return a.ts_unix-b.ts_unix; });
      queue=snaps; filt='all'; srt='chrono'; resetFilterBtns();
      buildSnapList(snaps,true);
      scTitle.textContent=label; scCnt.textContent=snaps.length+' snaps';
      // Stocker les bounds actives pour le filtre influenceur
      mobActiveBounds = bounds;
      mobActiveLabel = label;
      mobCloseProfs();
      setTimeout(function(){ mobTabSnaps(); },80);
    };
    dayRow.appendChild(btn);
  });
  cont.appendChild(dayRow);

  // ── Filtre catégorie (comme PC) ──
  var catRow = document.createElement('div');
  catRow.style.cssText = 'display:flex;gap:5px;padding:0 16px 8px;overflow-x:auto';
  catRow.style.cssText += ';scrollbar-width:none';
  var allCats = ['all'];
  Object.values(CATS).forEach(function(c){ if(allCats.indexOf(c)<0) allCats.push(c); });
  allCats.forEach(function(cat) {
    var chip = document.createElement('button');
    chip.className = 'mob-df-btn' + (mobCatFilter===cat?' on':'');
    chip.textContent = cat==='all'?'Tous':cat;
    chip.onclick = function() {
      mobCatFilter = cat;
      mobBuildProfs();
    };
    catRow.appendChild(chip);
  });
  cont.appendChild(catRow);

  // Séparateur
  var sep = document.createElement('div');
  sep.style.cssText = 'height:1px;background:var(--border);margin-bottom:4px';
  cont.appendChild(sep);

  // ── Liste profils (filtrée par catégorie) ──
  PROFS.forEach(function(p) {
    if (mobCatFilter !== 'all' && CATS[p] !== mobCatFilter) return;
    var snaps = ALL[p] || [];
    var el = document.createElement('div');
    el.className = 'mob-pi' + (p===curProf?' on':'');
    el.innerHTML =
      '<div class="av">'+avHtml(p)+'</div>'+
      '<div class="mob-pi-info">'+
        '<div class="mob-pi-name">'+(NAMES[p]||p)+'</div>'+
        '<div class="mob-pi-sub">'+snaps.length+' snaps · '+(CATS[p]||'')+'</div>'+
      '</div>'+
      '<div class="mob-pi-badge" id="mob-pib-'+p+'" style="display:'+(newCnts[p]>0?'flex':'none')+'">'+
        (newCnts[p]||0)+'</div>';
    el.onclick = function() {
      selProf(p); mobCloseProfs();
      setTimeout(function(){ mobTabSnaps(); },120);
    };
    cont.appendChild(el);
  });
}

function mobUpdateBadge() {
  var total = Object.values(newCnts).reduce(function(a,b){return a+b;},0);
  var b = document.getElementById('mob-badge-profs');
  if (b) {
    b.textContent = total > 0 ? total : '';
    b.style.display = total > 0 ? 'flex' : 'none';
  }
  // Mettre à jour les badges dans la liste profils si ouverte
  PROFS.forEach(function(p) {
    var badge = document.getElementById('mob-pib-' + p);
    var cnt = newCnts[p] || 0;
    if (badge) {
      badge.textContent = cnt;
      badge.style.display = cnt > 0 ? 'flex' : 'none';
    }
  });
}

function mobSetActiveTab(id) {
  document.querySelectorAll('.mob-tab').forEach(function(t){ t.classList.remove('on'); });
  var el = document.getElementById(id);
  if (el) el.classList.add('on');
}

function mobTabHome() {
  mobSetActiveTab('mob-tab-home');
  ['mob-drawer-profs','mob-drawer-snaps','mob-drawer-lb','mob-drawer-hist'].forEach(function(id){
    var el = document.getElementById(id); if(el) el.classList.remove('open');
  });
}

function mobTabProfs() {
  mobSetActiveTab('mob-tab-profs');
  mobBuildProfs();
  document.getElementById('mob-drawer-snaps').classList.remove('open');
  document.getElementById('mob-drawer-profs').classList.add('open');
}

function mobTabSnaps() {
  if (!curProf && qMode !== 'today') { mobTabProfs(); return; }
  mobSetActiveTab('mob-tab-snaps');
  // Sync titre
  var t = document.getElementById('mob-snaps-title');
  var titleTxt = qMode==='today' ? (mobActiveLabel||"Aujourd'hui") : ((NAMES[curProf]||curProf) + ' — ' + (ALL[curProf]||[]).length + ' snaps');
  if (t) t.textContent = titleTxt;
  // Construire le filtre influenceur si mode today/hier
  buildMobDayFilter();
  // Sync liste
  if (slMob) {
    slMob.innerHTML = slOrig.innerHTML;
    slMob.querySelectorAll('.si').forEach(function(el, i) {
      el.onclick = function() { playAt(i); mobCloseSnaps(); };
    });
  }
  document.getElementById('mob-drawer-profs').classList.remove('open');
  document.getElementById('mob-drawer-snaps').classList.add('open');
}

// Filtre influenceur pour mode today/hier
var mobDayProfFilter = {}; // { profile: false } = désactivé

function buildMobDayFilter() {
  var wrap = document.getElementById('mob-day-filter-wrap');
  if (!wrap) return;
  if (qMode !== 'today') { wrap.style.display = 'none'; return; }
  wrap.style.display = 'block';
  wrap.innerHTML = '';
  var row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:6px;padding:8px 12px;overflow-x:auto;scrollbar-width:none';

  // Chip "Tous"
  var allChip = document.createElement('button');
  allChip.className = 'mob-df-btn' + (Object.keys(mobDayProfFilter).length===0?' on':'');
  allChip.textContent = 'Tous';
  allChip.onclick = function() { mobDayProfFilter={}; applyMobDayFilter(); buildMobDayFilter(); };
  row.appendChild(allChip);

  PROFS.forEach(function(p) {
    // N'afficher que les profils qui ont des snaps dans le jour actif
    if (mobActiveBounds) {
      var hasBound = (ALL[p]||[]).some(function(s){ return inBounds(s, mobActiveBounds); });
      if (!hasBound) return;
    }
    var on = !mobDayProfFilter[p];
    var chip = document.createElement('button');
    chip.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:5px 10px;border-radius:99px;font-size:.62rem;font-weight:800;border:1px solid;cursor:pointer;white-space:nowrap;flex-shrink:0;-webkit-tap-highlight-color:transparent;transition:all .12s;' + (on?'background:rgba(86,207,255,.12);color:var(--hi);border-color:rgba(86,207,255,.3)':'background:transparent;color:var(--fg3);border-color:var(--border2)');
    var avSrc = AVATARS[p] || '';
    var ini = (NAMES[p]||p)[0];
    var avDiv = document.createElement('div');
    avDiv.style.cssText = 'width:18px;height:18px;border-radius:50%;overflow:hidden;flex-shrink:0;background:var(--ink4);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:.55rem;font-weight:900';
    if (avSrc) { var img=document.createElement('img'); img.src=avSrc; img.style.cssText='width:100%;height:100%;object-fit:cover'; avDiv.appendChild(img); } else { avDiv.textContent=ini; }
    chip.appendChild(avDiv);
    chip.appendChild(document.createTextNode(NAMES[p]||p));
    chip.onclick = function() {
      mobDayProfFilter[p] = on; // toggle
      applyMobDayFilter();
      buildMobDayFilter();
    };
    row.appendChild(chip);
  });
  wrap.appendChild(row);
}

function applyMobDayFilter() {
  if (qMode !== 'today' || !mobActiveBounds) return;
  var snaps = [];
  PROFS.forEach(function(p) {
    if (mobDayProfFilter[p]) return;
    (ALL[p]||[]).forEach(function(s){ if(inBounds(s, mobActiveBounds)) snaps.push(s); });
  });
  snaps.sort(function(a,b){ return a.ts_unix-b.ts_unix; });
  queue = snaps; resetFilterBtns();
  buildSnapList(snaps, true);
  var t = document.getElementById('mob-snaps-title');
  if(t) t.textContent = (mobActiveLabel||'') + ' — ' + snaps.length + ' snaps';
  if (slMob) {
    slMob.innerHTML = slOrig.innerHTML;
    slMob.querySelectorAll('.si').forEach(function(el, i) {
      el.onclick = function() { playAt(i); mobCloseSnaps(); };
    });
  }
}

function mobTabLB() {
  mobSetActiveTab('mob-tab-lb');
  document.getElementById('mob-drawer-profs').classList.remove('open');
  document.getElementById('mob-drawer-snaps').classList.remove('open');
  mobBuildLB();
  document.getElementById('mob-drawer-lb').classList.add('open');
}

function mobBuildLB() {
  var cont = document.getElementById('mob-lb-list');
  if (!cont) return;
  cont.innerHTML = '';
  var max = LB.reduce(function(m,r){ return Math.max(m,r[3]); }, 1);
  LB.forEach(function(r) {
    var p=r[0],name=r[1],rank=r[2],tot=r[3],vids=r[4],imgs=r[5],nw=r[6];
    var pct = Math.round(tot/max*100);
    var el = document.createElement('div');
    el.className = 'lb-item';
    el.style.margin = '4px 12px';
    el.innerHTML =
      '<div class="lb-top">' +
        '<div class="lb-pos">#'+rank+'</div>' +
        '<div class="lb-av">'+avHtml(p)+'</div>' +
        '<div class="lb-name">'+name+'</div>' +
        (nw>0?'<div class="lb-new">+'+nw+'</div>':'') +
      '</div>' +
      '<div class="lb-grid">' +
        '<div class="lb-cell"><span class="lb-val">'+tot+'</span><span class="lb-lbl">snaps</span></div>' +
        '<div class="lb-cell"><span class="lb-val" style="color:var(--hi)">'+vids+'</span><span class="lb-lbl">videos</span></div>' +
        '<div class="lb-cell"><span class="lb-val" style="color:var(--fg2)">'+imgs+'</span><span class="lb-lbl">images</span></div>' +
      '</div>' +
      '<div class="lb-bar"><div class="lb-fill" style="width:'+pct+'%"></div></div>';
    el.onclick = function(){ selProf(p); document.getElementById('mob-drawer-lb').classList.remove('open'); mobSetActiveTab('mob-tab-home'); };
    cont.appendChild(el);
  });
}

function mobCloseLB() {
  document.getElementById('mob-drawer-lb').classList.remove('open');
  mobSetActiveTab('mob-tab-home');
}

function mobTabHist() {
  mobSetActiveTab('mob-tab-hist');
  ['mob-drawer-profs','mob-drawer-snaps','mob-drawer-lb'].forEach(function(id){
    var el = document.getElementById(id); if(el) el.classList.remove('open');
  });
  mobBuildHist();
  document.getElementById('mob-drawer-hist').classList.add('open');
}

// Onglet historique actif
var mobHistTab = 'snaps'; // 'snaps' ou 'reprendre'
// Notifs activées par profil
var mobNotifEnabled = {};
try { mobNotifEnabled = JSON.parse(localStorage.getItem('snapmon_notifs')||'{}'); } catch(e){}
function saveMobNotif() { try{ localStorage.setItem('snapmon_notifs', JSON.stringify(mobNotifEnabled)); }catch(e){} }

// Sessions de reprendre : {profile: {snap_index, preview, ts_name, saved_at}}
function getAllResumeSessions() {
  try {
    var raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return [];
    var data = JSON.parse(raw);
    var list = [];
    PROFS.forEach(function(p) {
      if (data[p] && data[p].snap_index !== undefined) {
        var age = Date.now() - (data[p].saved_at||0);
        if (age < 7*86400000) list.push({profile:p, sess:data[p]});
      }
    });
    return list;
  } catch(e) { return []; }
}

function mobBuildHist() {
  var cont = document.getElementById('mob-hist-list');
  if (!cont) return;
  cont.innerHTML = '';

  // Onglets
  var tabs = document.createElement('div');
  tabs.className = 'mob-hist-tabs';
  ['Snaps','Reprendre'].forEach(function(label) {
    var tab = document.createElement('div');
    tab.className = 'mob-hist-tab' + (mobHistTab===label.toLowerCase()?' on':'');
    tab.textContent = label;
    tab.onclick = function() { mobHistTab=label.toLowerCase(); mobBuildHist(); };
    tabs.appendChild(tab);
  });
  cont.appendChild(tabs);

  var body = document.createElement('div');
  body.style.cssText = 'overflow-y:auto;flex:1';

  if (mobHistTab === 'snaps') {
    // ── Onglet Snaps : historique des nouveaux snaps + filtre notifs ──
    var notifTitle = document.createElement('div');
    notifTitle.style.cssText = 'padding:10px 18px 6px;font-size:.65rem;font-weight:800;color:var(--fg3);text-transform:uppercase;letter-spacing:.06em';
    notifTitle.textContent = 'Notifications par profil';
    body.appendChild(notifTitle);

    PROFS.forEach(function(p) {
      var on = !!mobNotifEnabled[p];
      var row = document.createElement('div');
      row.className = 'mob-notif-row';
      row.innerHTML =
        '<div style="display:flex;align-items:center;gap:10px;flex:1">' +
          '<div class="av" style="width:32px;height:32px;font-size:.75rem">'+avHtml(p)+'</div>'+
          '<div>'+
            '<div class="mob-notif-lbl">'+(NAMES[p]||p)+'</div>'+
            '<div class="mob-notif-sub">'+(on?'Notif active':'Notif inactive')+'</div>'+
          '</div>'+
        '</div>'+
        '<div class="mob-notif-tgl'+(on?' on':'')+'" id="mob-ntgl-'+p+'" data-p="'+p+'"></div>';
      row.querySelector('.mob-notif-tgl').onclick = function() {
        var pp = this.dataset.p;
        mobNotifEnabled[pp] = !mobNotifEnabled[pp];
        saveMobNotif();
        mobBuildHist();
      };
      body.appendChild(row);
    });

    // Historique des snaps notifiés
    if (logs.length) {
      var histTitle = document.createElement('div');
      histTitle.style.cssText = 'padding:12px 18px 6px;font-size:.65rem;font-weight:800;color:var(--fg3);text-transform:uppercase;letter-spacing:.06em;border-top:1px solid var(--border);margin-top:6px';
      histTitle.textContent = 'Derniers nouveaux snaps';
      body.appendChild(histTitle);
      logs.slice().reverse().slice(0,20).forEach(function(e) {
        var el = document.createElement('div');
        el.className = 'mob-pi';
        el.style.cssText = 'align-items:center;gap:10px;padding:8px 16px';
        var prevH = e.preview
          ? '<img src="'+e.preview+'" style="width:32px;height:44px;object-fit:cover;border-radius:6px;flex-shrink:0;border:1px solid var(--border)" loading="lazy">'
          : '<div style="width:32px;height:44px;border-radius:6px;background:var(--ink4);border:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.75rem;color:var(--green)">N</div>';
        el.innerHTML = prevH +
          '<div style="flex:1;min-width:0">'+
            '<div style="font-size:.78rem;font-weight:800">'+(NAMES[e.profile]||e.profile)+'</div>'+
            '<div style="font-size:.58rem;color:var(--fg3);font-family:Fira Code,monospace">#'+e.idx+' · '+e.type+'</div>'+
          '</div>'+
          '<div style="font-size:.52rem;color:var(--fg3);font-family:Fira Code,monospace">'+e.ts+'</div>';
        (function(prof, snapIdx) {
          el.onclick = function() {
            mobCloseHist();
            // Charger les snaps du profil puis jouer
            selProf(prof);
            setTimeout(function() {
              var idx = findSnapInQueue(prof, snapIdx);
              if (idx >= 0) { playAt(idx); mobTabHome(); }
            }, 100);
          };
        })(e.profile, e.idx);
        body.appendChild(el);
      });
    } else {
      var empty = document.createElement('div');
      empty.style.cssText = 'padding:20px;text-align:center;font-size:.72rem;color:var(--fg3)';
      empty.textContent = 'Aucun snap reçu pour le moment';
      body.appendChild(empty);
    }

  } else {
    // ── Onglet Reprendre ──
    var sessions = getAllResumeSessions();
    if (!sessions.length) {
      var empty2 = document.createElement('div');
      empty2.style.cssText = 'padding:36px 20px;text-align:center;font-size:.75rem;color:var(--fg3);line-height:1.6';
      empty2.innerHTML = 'Aucun snap à reprendre<br><span style="font-size:.65rem">Les snaps que tu quittes en cours apparaissent ici</span>';
      body.appendChild(empty2);
    } else {
      sessions.forEach(function(item) {
        var p = item.profile; var sess = item.sess;
        var el = document.createElement('div');
        el.className = 'mob-resume-item';
        var thumbH = sess.preview
          ? '<img src="'+sess.preview+'" class="mob-resume-thumb">'
          : '<div class="mob-resume-ph">&#9654;</div>';
        var delBtn = document.createElement('button');
        delBtn.style.cssText = 'width:28px;height:28px;border-radius:50%;background:var(--ink4);border:1px solid var(--border);color:var(--fg3);flex-shrink:0;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:.7rem';
        delBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="width:12px;height:12px"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        (function(pp) {
          delBtn.onclick = function(e) {
            e.stopPropagation();
            clearSessionForProfile(pp);
            mobBuildHist();
          };
        })(p);
        el.innerHTML =
          thumbH +
          '<div class="mob-resume-info">'+
            '<div class="mob-resume-name">'+(NAMES[p]||p)+'</div>'+
            '<div class="mob-resume-detail">Snap #'+sess.snap_index+(sess.ts_name?' · '+sess.ts_name:'')+'</div>'+
          '</div>'+
          '<div style="font-size:.7rem;font-weight:900;color:var(--hi);padding-left:6px;flex-shrink:0">&#8250;</div>';
        el.appendChild(delBtn);
        (function(pp, ss) {
          el.onclick = function() {
            mobCloseHist();
            selProf(pp);
            setTimeout(function() {
              var idx = findSnapInQueue(pp, ss.snap_index);
              if (idx >= 0) { playAt(idx); mobTabHome(); }
            }, 100);
          };
        })(p, sess);
        body.appendChild(el);
      });
    }
  }
  cont.appendChild(body);
}

function mobCloseHist() {
  document.getElementById('mob-drawer-hist').classList.remove('open');
  mobSetActiveTab('mob-tab-home');
}

function mobCloseProfs() {
  document.getElementById('mob-drawer-profs').classList.remove('open');
  mobSetActiveTab('mob-tab-home');
}

function mobCloseSnaps() {
  document.getElementById('mob-drawer-snaps').classList.remove('open');
  mobSetActiveTab('mob-tab-home');
}

function mobCloseDrawer(e, el) {
  if (e.target === el) {
    el.classList.remove('open');
    mobSetActiveTab('mob-tab-home');
  }
}

/* Patch buildProfiles pour aussi rebuild la version mobile */
var _origBuildProfiles = buildProfiles;
buildProfiles = function() {
  _origBuildProfiles();
  mobUpdateBadge();
  // Si le drawer est ouvert on le rebuild
  if (document.getElementById('mob-drawer-profs').classList.contains('open')) {
    mobBuildProfs();
  }
};

/* ── MOBILE : tap gauche/milieu/droite ── */
(function(){
  if (!('ontouchstart' in window)) return;
  var stage = document.getElementById('snap-stage');
  if (!stage) return;
  stage.addEventListener('click', function(e){
    var w = stage.offsetWidth;
    var x = e.clientX - stage.getBoundingClientRect().left;
    var pct = x / w;
    if (pct < 0.33) {
      navPrev();
    } else if (pct > 0.67) {
      navNext();
    } else {
      // Milieu : pause/play video ou pause/reprendre image
      if (mv.style.display !== 'none') {
        mv.paused ? mv.play().catch(function(){}) : mv.pause();
      } else if (mi.style.display !== 'none') {
        // Image : toggle pause
        if (imgT) { clearTimeout(imgT); imgT = null; }
        else { imgT = setTimeout(function(){ navNext(); }, 2000); }
      }
    }
  });
})();
"""

    js_final = (js
        .replace("__ALL_DATA__",     profiles_js)
        .replace("__PROFILES__",     profiles_list)
        .replace("__AVATARS__",      avatars_js)
        .replace("__CATEGORIES__",   categories_js)
        .replace("__NAMES__",        names_js)
        .replace("__NEW_LOGS__",     new_logs_js)
        .replace("__LB_ROWS__",      lb_js)
        .replace("__TODAY_STR__",    today_str)
        .replace("__YEST_STR__",     yesterday_str)
        .replace("__TODAY_BOUNDS__", today_b_js)
        .replace("__YEST_BOUNDS__",  yest_b_js)
    )

    # ── HTML ─────────────────────────────────────────────────────────────
    html = (
        "<!DOCTYPE html>\n<html lang='fr'>\n<head>\n"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name='screen-orientation' content='portrait'>"
        "<title>Team Nasdas Life</title>"
        "<style>" + css + "</style>"
        "</head>\n<body>\n"

        # ── SHELL (desktop) ──
        "<div class='shell'>\n"

        # ── LEFT PANEL ──
        "<aside class='panel'>\n"
        "<div class='brand'>"
        "<div class='brand-wordmark'>Team <b>Nasdas</b> Life</div>"
        "</div>\n"
        "<div class='tabs'>"
        "<div class='tab on' id='tab-profiles' onclick=\"switchTab('profiles')\">Profils</div>"
        "<div class='tab' id='tab-lb'       onclick=\"switchTab('lb')\">Classement</div>"
        "<div class='tab' id='tab-hist'     onclick=\"switchTab('hist')\">Historique</div>"
        "</div>\n"
        "<div class='pane on' id='pane-profiles'>"
        "<div class='today-row' style='padding-bottom:8px'>"
        "<div style='display:flex;align-items:center;gap:6px'>"
        "<div class='today-chip' id='today-chip' style='flex:1'>"
        "<span class='today-label'>Today</span>"
        "<span class='today-cnt' id='today-cnt'>0</span>"
        "</div>"
        "<button class='today-excl-toggle' id='today-excl-btn' onclick='toggleTodayExclPanel()'>Filtrer</button>"
        "</div></div>"
        "<div class='today-excl-panel' id='today-excl-panel'></div>"
        "<div class='cat-bar' id='cat-bar'></div>"
        "<div class='prof-list' id='prof-list'></div>"
        "</div>\n"
        "<div class='pane' id='pane-lb'>"
        "<div class='lb-list' id='lb-cont'></div>"
        "</div>\n"
        "<div class='pane' id='pane-hist'>"
        "<div style='padding:9px 13px;border-bottom:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:space-between'>"
        "<span style='font-size:.68rem;font-weight:700;color:var(--fg2)'>Historique</span>"
        "<button class='clear-btn' onclick='clearHist()'>Effacer</button>"
        "</div>"
        "<div class='hist-list' id='hist-cont'></div>"
        "</div>\n"
        "</aside>\n"

        # ── SNAP COL ──
        "<div class='snap-col'>"
        "<div class='sc-head'>"
        "<span class='sc-title' id='sc-title'>&mdash;</span>"
        "<span class='sc-cnt' id='sc-cnt'></span>"
        "</div>"
        "<div class='sc-filters'>"
        "<button class='sf on' onclick='setFilt(\"all\",this)'>Tous</button>"
        "<button class='sf' onclick='setFilt(\"v\",this)'>Vidéos</button>"
        "<button class='sf' onclick='setFilt(\"i\",this)'>Images</button>"
        "<button class='sf' onclick='setFilt(\"new\",this)'>Nouveaux</button>"
        "</div>"
        "<div class='sort-row'>"
        "<span class='sort-lbl'>Ordre</span>"
        "<button class='sb on' id='sort-asc' onclick='setSort(\"chrono\",this)'>&#8593; Ancien</button>"
        "<button class='sb' id='sort-desc' onclick='setSort(\"recent\",this)'>&#8595; Récent</button>"
        "</div>"
        "<div class='snap-scroll' id='snap-list'></div>"
        "</div>\n"

        # ── VIEWER ──
        "<div class='viewer' id='viewer'>"
        "<div class='viewer-blur' id='viewer-blur'></div>"
        "<div class='snap-stage' id='snap-stage'>"
        "<div class='snap-prog' id='pbar'><div class='snap-prog-fill' id='pbar-fill'></div></div>"
        "<div class='snap-top'>"
        "<div class='snap-av' id='snap-av'></div>"
        "<div class='snap-info'>"
        "<div class='snap-name' id='snap-name'>Sélectionner un snap</div>"
        "<div class='snap-time' id='snap-time'></div>"
        "</div>"
        "<span class='snap-type-badge v' id='snap-badge'>VIDEO</span>"
        "</div>"
        "<video id='mv' playsinline></video>"
        "<img id='mi' alt=''>"
        "<div class='tap-zone' id='tap-prev'></div>"
        "<div class='tap-zone' id='tap-next'></div>"
        "<div class='tap-center' id='tap-center'></div>"
        ""
        "<div class='snap-bot'>"
        "<button class='s-btn' id='btn-pause'>II</button>"
        "<button class='s-btn' id='btn-fs'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><polyline points='15 3 21 3 21 9'/><polyline points='9 21 3 21 3 15'/><line x1='21' y1='3' x2='14' y2='10'/><line x1='3' y1='21' x2='10' y2='14'/></svg></button>"
        "<div class='vol-grp'>"
        "<span class='vol-ic' id='vol-ico'>&#128266;</span>"
        "<input type='range' class='vol-r' id='vol' min='0' max='100' value='80'>"
        "</div>"
        ""
        "</div>"
        "</div>\n"
        "<button class='arr' id='arr-prev'>&#8249;</button>"
        "<button class='arr' id='arr-next'>&#8250;</button>"
        "<div class='viewer-empty' id='viewer-empty'>"
        "<div class='viewer-empty-txt'>Choisir un snap</div>"
        "</div>"
        "<div class='autoplay-tog' id='auto-tog'>"
        "<div class='tgl on' id='tgl'><div class='tgl-k'></div></div>"
        "Autoplay"
        "</div>"
        "</div>\n"

        # ── MOBILE NAV (dans le shell, après viewer) ──
        "<nav class='mob-nav' id='mob-nav'>"
        "<button class='mob-tab on' id='mob-tab-home' onclick='mobTabHome()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polygon points='23 7 16 12 23 17 23 7'/><rect x='1' y='5' width='15' height='14' rx='2'/></svg><span>Viewer</span></button>"
        "<button class='mob-tab' id='mob-tab-profs' onclick='mobTabProfs()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/><path d='M23 21v-2a4 4 0 0 0-3-3.87'/><path d='M16 3.13a4 4 0 0 1 0 7.75'/></svg><span class='mob-badge' id='mob-badge-profs'></span><span>Profils</span></button>"
        ""
        "<button class='mob-tab' id='mob-tab-lb' onclick='mobTabLB()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><line x1='18' y1='20' x2='18' y2='10'/><line x1='12' y1='20' x2='12' y2='4'/><line x1='6' y1='20' x2='6' y2='14'/></svg><span>Classement</span></button><button class='mob-tab' id='mob-tab-hist' onclick='mobTabHist()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><polyline points='12 6 12 12 16 14'/></svg><span>Historique</span></button>"
        "</nav>"

        "</div>\n"

        # ── TOASTS ──
        "<div id='toasts'></div>"

        # ── MOBILE DRAWERS (hors shell, position:fixed) ──
        "<div class='mob-drawer' id='mob-drawer-profs' onclick='mobCloseDrawer(event,this)'>"
        "<div class='mob-sheet'>"
        "<div class='mob-sheet-handle'></div>"
        "<div class='mob-sheet-title'>"
        "<span>Profils</span>"
        "<button class='mob-sheet-close' onclick='mobCloseProfs()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round'><line x1='18' y1='6' x2='6' y2='18'/><line x1='6' y1='6' x2='18' y2='18'/></svg></button>"
        "</div>"
        "<div class='mob-sheet-body' id='mob-prof-list'></div>"
        "</div></div>"
        "<div class='mob-snap-drawer' id='mob-drawer-snaps' onclick='mobCloseDrawer(event,this)'>"
        "<div class='mob-snap-sheet'>"
        "<div class='mob-sheet-handle'></div>"
        "<div class='mob-sheet-title'>"
        "<span id='mob-snaps-title'>Snaps</span>"
        "<button class='mob-sheet-close' onclick='mobCloseSnaps()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round'><line x1='18' y1='6' x2='6' y2='18'/><line x1='6' y1='6' x2='18' y2='18'/></svg></button>"
        "</div>"
        "<div id='mob-day-filter-wrap' style='display:none;border-bottom:1px solid var(--border);flex-shrink:0'></div>"
        "<div class='mob-day-filter' id='mob-snap-prof-filter' style='display:none'></div>"
        "<div class='mob-filters'>"
        "<button class='sf on' onclick='setFilt(&quot;all&quot;,this)'>Tous</button>"
        "<button class='sf' onclick='setFilt(&quot;v&quot;,this)'>Vidéos</button>"
        "<button class='sf' onclick='setFilt(&quot;i&quot;,this)'>Images</button>"
        "<button class='sf' onclick='setFilt(&quot;new&quot;,this)'>Nouveaux</button>"
        "</div>"
        "<div class='mob-sort-row'>"
        "<span class='mob-sort-lbl'>Ordre</span>"
        "<button class='sb on' id='mob-sort-asc' onclick='setSort(&quot;chrono&quot;,this)'>&#8593; Ancien</button>"
        "<button class='sb' id='mob-sort-desc' onclick='setSort(&quot;recent&quot;,this)'>&#8595; Récent</button>"
        "</div>"
        "<div class='mob-snaps-scroll' id='mob-snap-list'></div>"
        "</div></div>"

        # ── MOBILE LB DRAWER ──
        "<div class='mob-snap-drawer' id='mob-drawer-lb' onclick='mobCloseDrawer(event,this)'>"
        "<div class='mob-snap-sheet'>"
        "<div class='mob-sheet-handle'></div>"
        "<div class='mob-sheet-title'>"
        "<span>Classement</span>"
        "<button class='mob-sheet-close' onclick='mobCloseLB()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round'><line x1='18' y1='6' x2='6' y2='18'/><line x1='6' y1='6' x2='18' y2='18'/></svg></button>"
        "</div>"
        "<div class='mob-snaps-scroll' id='mob-lb-list'></div>"
        "</div></div>"

        # ── MOBILE HIST DRAWER ──
        "<div class='mob-snap-drawer' id='mob-drawer-hist' onclick='mobCloseDrawer(event,this)'>"
        "<div class='mob-snap-sheet'>"
        "<div class='mob-sheet-handle'></div>"
        "<div class='mob-sheet-title'>"
        "<span>Historique</span>"
        "<button class='mob-sheet-close' onclick='mobCloseHist()'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round'><line x1='18' y1='6' x2='6' y2='18'/><line x1='6' y1='6' x2='18' y2='18'/></svg></button>"
        "</div>"
        "<div class='mob-snaps-scroll' id='mob-hist-list'></div>"
        "</div></div>"
        "<script>\n" + js_final + "\n</script>"
        "\n</body>\n</html>"
    )
    return html


# ─────────────────────────────────────────────
#  MONITOR LOOP
# ─────────────────────────────────────────────

def monitor_loop(states: list, once: bool = False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    viewer_path = OUTPUT_DIR / "viewer.html"
    browser_opened = False
    n   = len(states)
    idx = 0

    global_logger.info("Init : chargement de tous les profils...")
    for st in states:
        st.check()

    html_content = generate_html(states)
    with open(viewer_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    write_live_data(states)

    global_logger.info(
        "Init terminee. Rotation : 1 profil / " + str(REFRESH_INTERVAL) +
        "s | Cycle complet : " + str(REFRESH_INTERVAL * n) + "s"
    )

    if not browser_opened:
        try:
            webbrowser.open(viewer_path.resolve().as_uri())
        except Exception:
            pass
        browser_opened = True

    if once:
        global_logger.info("Mode --once : terminé.")
        return

    while True:
        time.sleep(REFRESH_INTERVAL)

        st = states[idx]
        name = PROFILE_NAMES.get(st.profile, st.profile)
        global_logger.info(
            "Rotation [" + str(idx + 1) + "/" + str(n) + "] " +
            name + " (@" + st.profile + ")"
        )

        new_snaps = st.check()

        if new_snaps:
            global_logger.info(
                "  => " + str(len(new_snaps)) +
                " nouveau(x) snap(s) pour " + name
            )

        write_live_data(states)

        with open(viewer_path, "w", encoding="utf-8") as f:
            f.write(generate_html(states))

        idx = (idx + 1) % n


# ─────────────────────────────────────────────
#  HTTP SERVER (Railway / production)
# ─────────────────────────────────────────────

def start_http_server():
    import http.server
    import threading

    port = int(os.environ.get("PORT", 8080))

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(Path(".").resolve()), **kwargs)

        def do_GET(self):
            if self.path in ("/", ""):
                self.send_response(302)
                self.send_header("Location", "/viewers/viewer.html")
                self.end_headers()
            else:
                super().do_GET()

        def log_message(self, format, *args):
            pass  # silence les logs HTTP

    def run():
        with http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler) as httpd:
            print(f"Serveur HTTP démarré sur le port {port}", flush=True)
            httpd.serve_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    global snap_logger, global_logger
    snap_logger   = setup_logger("snaps",  "new_snaps.log")
    global_logger = setup_logger("global", "monitor.log")

    once = "--once" in sys.argv

    start_http_server()

    global_logger.info("SNAPCHAT MONITOR v4 — rotation 1 profil / " + str(REFRESH_INTERVAL) + "s")
    global_logger.info("Profils : " + ", ".join(PROFILES))
    global_logger.info("Cycle complet : " + str(REFRESH_INTERVAL * len(PROFILES)) + "s | Viewer : " + str(OUTPUT_DIR) + "/viewer.html")

    states = [ProfileState(p) for p in PROFILES]

    try:
        monitor_loop(states, once=once)
    except KeyboardInterrupt:
        global_logger.info("Arret - rapport final :")
        for st in states:
            global_logger.info("  @" + st.profile + "  all=" + str(len(st.all_snaps)) + "  new=" + str(st.new_count) + "  checks=" + str(st.check_count))


if __name__ == "__main__":
    main()
