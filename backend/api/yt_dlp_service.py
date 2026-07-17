import os
import urllib.parse

import yt_dlp

from api import douyin_service


def extract_video_info(url: str):
    if douyin_service.is_douyin(url):
        return _extract_douyin_info(url)
    return _extract_with_ytdlp(url)


def _extract_douyin_info(url: str):
    canonical = douyin_service.resolve_douyin_url(url)
    video_id = douyin_service.extract_video_id(canonical)

    share_reason = None
    if video_id:
        try:
            info = douyin_service.share_page_info(video_id)
            info.setdefault("qualities", [])  # Douyin share: satu stream saja
            # Header yang sama dengan yang dipakai saat membaca halaman share,
            # supaya /api/stream tidak ditolak CDN Douyin.
            info["stream_headers"] = {
                "User-Agent": douyin_service.MOBILE_UA,
                "Referer": douyin_service.DOUYIN_HOME,
            }
            return info
        except Exception as e:
            share_reason = douyin_service.clean_error(str(e))
    else:
        share_reason = "ID video tidak ditemukan di link."

    try:
        return _extract_with_ytdlp(canonical, douyin=True)
    except Exception as e:
        raise Exception(
            "Douyin gagal lewat dua jalur. "
            f"Halaman share: {share_reason} | "
            f"yt-dlp: {douyin_service.clean_error(str(e))}"
        )


def _quality_ladder(formats):
    """Daftar tinggi resolusi unik yang punya jalur video, urut dari besar.

    Resolusi di atas pagar MAX_HEIGHT server tidak ditawarkan ke user,
    supaya pilihan di layar jujur dengan yang benar-benar bisa diunduh."""
    try:
        max_h = int(os.environ.get("MAX_HEIGHT", "720") or 0)
    except ValueError:
        max_h = 720
    heights = set()
    for f in formats or []:
        h = f.get("height")
        if h and f.get("vcodec") not in (None, "none"):
            h = int(h)
            if max_h and h > max_h:
                continue
            heights.add(h)
    return [{"label": f"{h}p", "height": h} for h in sorted(heights, reverse=True)]


def _cookie_header(cookiejar, stream_url):
    """Rangkai cookie yang berlaku untuk host stream_url jadi satu string.

    INTI PERBAIKAN PREVIEW TIKTOK: link CDN TikTok membawa `tk=tt_chain_token`,
    artinya CDN menuntut cookie `tt_chain_token` yang lahir saat yt-dlp membuka
    halaman video. Kalau cookie ini tidak ikut dikirim proxy -> 403 Forbidden.
    """
    try:
        host = (urllib.parse.urlsplit(stream_url).hostname or "").lower()
    except Exception:
        return ""
    if not host or cookiejar is None:
        return ""
    pairs = []
    for c in cookiejar:
        dom = (c.domain or "").lstrip(".").lower()
        if dom and (host == dom or host.endswith("." + dom)):
            pairs.append(f"{c.name}={c.value}")
    return "; ".join(pairs)


def _extract_with_ytdlp(url: str, douyin: bool = False):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        # Catatan: JANGAN set "format" di sini. Ini hanya ekstraksi metadata
        # (download=False); memaksa "best" bisa gagal di video yang tidak
        # punya format gabungan, padahal kita cuma butuh info + daftar format.
        # Tautan YouTube sering membawa &list=... — tanpa ini yt-dlp bisa
        # mencoba membaca SELURUH playlist, bukan satu video.
        "noplaylist": True,
    }

    temp_cookie = None
    if douyin:
        temp_cookie = douyin_service.apply_douyin_auth(ydl_opts)
    elif "tiktok.com" in url:
        temp_cookie = douyin_service.fallback_cookiefile()
        ydl_opts["cookiefile"] = temp_cookie
        ydl_opts["http_headers"] = {"User-Agent": douyin_service.DESKTOP_UA}
    elif any(s in url for s in ("instagram.com", "facebook.com", "twitter.com", "x.com")):
        ydl_opts["http_headers"] = {"User-Agent": douyin_service.DESKTOP_UA}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            formats = info.get("formats", [])

            def _playable(f, need_avc):
                return (
                    f.get("ext") == "mp4"
                    and f.get("vcodec") not in (None, "none")
                    and f.get("acodec") not in (None, "none")
                    and (not need_avc or str(f.get("vcodec", "")).startswith("avc"))
                )

            # Utamakan H.264+audio: H.265 (TikTok/Douyin) tidak bisa diputar
            # banyak browser HP, membuat preview diam. Ambil kandidat TERAKHIR
            # karena yt-dlp mengurutkan format dari terburuk ke terbaik.
            stream_url = None
            chosen = None
            for need_avc in (True, False):
                cands = [f for f in formats if _playable(f, need_avc)]
                if cands:
                    chosen = cands[-1]
                    stream_url = chosen.get("url")
                    break

            final_url = stream_url or info.get("url")

            # "Kartu identitas" untuk proxy preview: header yang yt-dlp
            # sendiri pakai untuk format ini + cookie sesi (tt_chain_token
            # dkk). Tanpa ini, CDN TikTok menjawab 403.
            stream_headers = {}
            if chosen and isinstance(chosen.get("http_headers"), dict):
                for k in ("User-Agent", "Referer", "Origin", "Accept"):
                    if chosen["http_headers"].get(k):
                        stream_headers[k] = chosen["http_headers"][k]
            cookie = _cookie_header(getattr(ydl, "cookiejar", None), final_url or "")
            if cookie:
                stream_headers["Cookie"] = cookie
            if "tiktok.com" in url and "Referer" not in stream_headers:
                stream_headers["Referer"] = "https://www.tiktok.com/"

            return {
                "title": info.get("title", "Unknown Video"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration", 60),
                "direct_url": final_url,
                "qualities": _quality_ladder(formats),
                "stream_headers": stream_headers,
            }
    except Exception as e:
        raise Exception(douyin_service.clean_error(str(e)))
    finally:
        if temp_cookie and os.path.exists(temp_cookie):
            try:
                os.remove(temp_cookie)
            except OSError:
                pass
