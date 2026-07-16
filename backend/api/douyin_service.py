"""
Logika Douyin, versi 3.

Pelajaran dari error terakhir: cookie SUDAH terkirim (yt-dlp menampilkan pesan
"report this issue" yang hanya muncul kalau s_v_web_id ada), tapi API detail
Douyin tetap menolak. Sebabnya: API itu kini menuntut tanda tangan permintaan
(a_bogus) yang dihitung JavaScript — dan yt-dlp memang tidak membuatnya
(ada TODO di kode yt-dlp sendiri). Menambah cookie tidak akan pernah cukup.

Jalan keluar yang dipakai downloader Douyin yang benar-benar jalan: baca
HALAMAN SHARE https://www.iesdouyin.com/share/video/<id>/ . Halaman itu
menanamkan JSON data video (judul, cover, durasi, dan link mp4) langsung di
HTML — tanpa signature, tanpa cookie. Modul ini menjadikannya jalur UTAMA;
yt-dlp hanya cadangan.
"""

import json
import os
import re
import time
import urllib.parse
import uuid

import requests

DOUYIN_HOME = "https://www.douyin.com/"

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Halaman share menyajikan data paling lengkap kalau diakses seperti HP.
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

_URL_RE = re.compile(r"https?://[^\s，,、。]+", re.IGNORECASE)
_ID_RE = re.compile(r"(?:/video/|modal_id=|/share/video/|aweme_id=)(\d{6,})")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_VALID_BROWSERS = {
    "brave", "chrome", "chromium", "edge",
    "firefox", "opera", "safari", "vivaldi", "whale",
}


def is_douyin(url):
    return "douyin.com" in (url or "")


def douyin_headers():
    return {"User-Agent": DESKTOP_UA, "Referer": DOUYIN_HOME}


def is_douyin_media_host(url):
    low = (url or "").lower()
    markers = (
        "douyin", "douyinvod", "iesdouyin", "amemv", "bytecdn", "ixigua",
        "zjcdn", "snssdk", "bytevod", "ibyteimg", "ibytedtos",
        "douyinpic", "douyinstatic",
    )
    return any(m in low for m in markers)


# --- Normalisasi URL -------------------------------------------------------

def _first_url(text):
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip("/") if m else (text or "").strip()


def extract_video_id(url):
    m = _ID_RE.search(url or "")
    return m.group(1) if m else None


def resolve_douyin_url(raw):
    """Ubah link pendek / teks share jadi https://www.douyin.com/video/<id>."""
    url = _first_url(raw)

    vid = extract_video_id(url)
    if vid:
        return f"https://www.douyin.com/video/{vid}"

    try:
        resp = requests.get(
            url, headers={"User-Agent": DESKTOP_UA}, allow_redirects=True, timeout=15,
        )
        vid = extract_video_id(resp.url)
        if vid:
            return f"https://www.douyin.com/video/{vid}"
        return resp.url
    except Exception:
        return url


# --- JALUR UTAMA: halaman share iesdouyin ----------------------------------

def _extract_embedded_json(html):
    """Ambil JSON yang ditanam di halaman share (dua format yang dikenal)."""
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(
        r'<script id="RENDER_DATA" type="application/json">([^<]+)</script>', html
    )
    if m:
        try:
            return json.loads(urllib.parse.unquote(m.group(1)))
        except json.JSONDecodeError:
            pass
    return None


def _find_item(obj, depth=0):
    """Cari item video pertama (dict yang punya item_list) di JSON bersarang."""
    if depth > 7:
        return None
    if isinstance(obj, dict):
        il = obj.get("item_list")
        if isinstance(il, list) and il and isinstance(il[0], dict):
            return il[0]
        for v in obj.values():
            r = _find_item(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_item(v, depth + 1)
            if r:
                return r
    return None


def share_page_info(video_id):
    """Ambil info video (judul, cover, durasi, link mp4) dari halaman share.

    Tidak butuh cookie maupun tanda tangan. Link 'playwm' (ber-watermark)
    diganti 'play' untuk mendapat versi tanpa watermark.
    """
    url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    resp = requests.get(
        url,
        headers={"User-Agent": MOBILE_UA, "Referer": DOUYIN_HOME},
        timeout=20,
    )
    data = _extract_embedded_json(resp.text)
    if not data:
        raise Exception(
            "Halaman share Douyin tidak berisi data video "
            "(video mungkin privat/dihapus, atau format halaman berubah)."
        )

    item = _find_item(data)
    if not item:
        raise Exception("Data video tidak ditemukan di halaman share Douyin.")

    video = item.get("video") or {}
    play_addr = video.get("play_addr") or {}
    url_list = play_addr.get("url_list") or []

    play_url = None
    if url_list:
        play_url = url_list[0].replace("playwm", "play")
    elif play_addr.get("uri"):
        play_url = (
            "https://www.iesdouyin.com/aweme/v1/play/"
            f"?video_id={play_addr['uri']}&ratio=1080p&line=0"
        )
    if not play_url:
        raise Exception(
            "Link video tidak ada di halaman share (kemungkinan ini post foto, "
            "bukan video)."
        )

    dur = video.get("duration") or item.get("duration") or 0
    duration = round(dur / 1000) if dur > 1000 else int(dur or 0)

    cover = (video.get("cover") or {}).get("url_list") or []

    return {
        "title": item.get("desc") or "Douyin Video",
        "thumbnail": cover[0] if cover else None,
        "duration": duration or 60,
        "direct_url": play_url,
    }


def download_direct(url, dest_path):
    """Unduh mp4 langsung dari CDN Douyin (mengikuti redirect otomatis)."""
    headers = {"User-Agent": MOBILE_UA, "Referer": DOUYIN_HOME, "Accept": "*/*"}
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1024:
        raise Exception("File video dari CDN Douyin kosong / terlalu kecil.")


# --- CADANGAN: yt-dlp dengan cookie (dipertahankan sebagai fallback) --------

def real_cookie_file():
    candidates = [
        os.environ.get("DOUYIN_COOKIES"),
        os.path.join(os.getcwd(), "cookies_douyin.txt"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "cookies_douyin.txt"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def browser_cookiespec():
    b = os.environ.get("DOUYIN_BROWSER", "").strip().lower()
    return (b,) if b in _VALID_BROWSERS else None


def fallback_cookiefile():
    os.makedirs("temp_media", exist_ok=True)
    cookie_path = os.path.join(os.getcwd(), "temp_media", f"cookie_{uuid.uuid4().hex}.txt")
    expires = int(time.time()) + 365 * 24 * 3600
    s_v_web_id = f"verify_{uuid.uuid4().hex}"
    ttwid = uuid.uuid4().hex
    domains = [
        ".douyin.com", "www.douyin.com", "v.douyin.com", "douyin.com",
        ".iesdouyin.com", "www.iesdouyin.com",
        ".tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    ]
    lines = ["# Netscape HTTP Cookie File", "# Generated. Do not edit.", ""]
    for d in domains:
        inc_sub = "TRUE" if d.startswith(".") else "FALSE"
        lines.append(f"{d}\t{inc_sub}\t/\tFALSE\t{expires}\ts_v_web_id\t{s_v_web_id}")
        lines.append(f"{d}\t{inc_sub}\t/\tFALSE\t{expires}\tttwid\t{ttwid}")
    with open(cookie_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return cookie_path


def apply_douyin_auth(ydl_opts):
    """Set header + cookie untuk jalur cadangan yt-dlp.
    Return path cookie sementara yang perlu dihapus, atau None."""
    ydl_opts["http_headers"] = douyin_headers()

    real = real_cookie_file()
    if real:
        ydl_opts["cookiefile"] = real
        return None

    spec = browser_cookiespec()
    if spec:
        ydl_opts["cookiesfrombrowser"] = spec
        return None

    fake = fallback_cookiefile()
    ydl_opts["cookiefile"] = fake
    return fake


def clean_error(msg):
    """Buang kode warna ANSI dan rapikan pesan supaya terbaca di layar."""
    return _ANSI_RE.sub("", msg or "").strip()