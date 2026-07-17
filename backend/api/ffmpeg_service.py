import os
import uuid

import ffmpeg
import yt_dlp

from api import douyin_service

# --- PAGAR RESOLUSI (trik untuk hosting RAM kecil, mis. Render free 512 MB) ---
# Server tidak akan pernah mengunduh video lebih tinggi dari batas ini,
# berapa pun pilihan user. Ubah lewat env var MAX_HEIGHT di dashboard hosting
# (contoh: 480 kalau masih berat, 1080 kalau nanti pindah server besar).
# Isi 0 untuk mematikan pagar.
try:
    _MAX_HEIGHT = int(os.environ.get("MAX_HEIGHT", "720") or 0)
except ValueError:
    _MAX_HEIGHT = 720


def _resolution_format(resolution):
    """Bangun format-selector yt-dlp dari pilihan resolusi.

    Dua aturan penting (pelajaran dari file TikTok tanpa suara):
    1. Utamakan H.264 (avc1). TikTok/Douyin juga menyediakan H.265 (bytevc1)
       yang tidak bisa diputar banyak HP Android — dan varian itulah yang
       tadinya terpilih.
    2. Selalu minta video+audio (bv*+ba), dengan cadangan file muxed (b).
       Ini menjamin track audio ikut terunduh."""
    digits = "".join(c for c in str(resolution or "") if c.isdigit())
    h_val = int(digits) if digits else None
    # Terapkan pagar: pilihan user dipangkas ke MAX_HEIGHT bila melebihi,
    # dan "best" (tanpa angka) otomatis dibatasi MAX_HEIGHT.
    if _MAX_HEIGHT:
        h_val = min(h_val, _MAX_HEIGHT) if h_val else _MAX_HEIGHT
    h = f"[height<={h_val}]" if h_val else ""
    parts = [
        f"bv*[vcodec^=avc1]{h}+ba",
        f"bv*{h}+ba",
        f"b[vcodec^=avc1]{h}",
        f"b{h}",
        "b",
    ]
    seen, uniq = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return "/".join(uniq)


def process_media(original_url, start_time, end_time, output_format="mp4", resolution="best"):
    os.makedirs("temp_media", exist_ok=True)

    file_id = str(uuid.uuid4())
    temp_raw_file = f"temp_media/{file_id}_raw.mp4"
    output_filename = f"temp_media/{file_id}_final.{output_format}"

    try:
        if douyin_service.is_douyin(original_url):
            # Douyin: satu stream dari halaman share; resolusi tidak berlaku.
            _download_douyin(original_url, temp_raw_file)
        else:
            _download_with_ytdlp(original_url, temp_raw_file, resolution=resolution)

        if not os.path.exists(temp_raw_file):
            raise Exception("Gagal menyimpan video dari server asal.")

        _cut(temp_raw_file, output_filename, start_time, end_time, output_format)

        if os.path.exists(temp_raw_file):
            os.remove(temp_raw_file)

        return output_filename

    except Exception as e:
        if os.path.exists(temp_raw_file):
            os.remove(temp_raw_file)
        raise Exception(douyin_service.clean_error(str(e)))


def _cut(src, dst, start_time, end_time, output_format):
    """Potong media. Pakai fast-seek di input (-ss) lalu batasi DURASI di output
    (-t). Ini lebih benar daripada memasang -to di input (yang membuat panjang
    klip salah), dan tetap cepat karena stream-copy untuk video."""
    start = max(0, int(start_time))
    duration = max(1, int(end_time) - start)

    if output_format in ("jpg", "png"):
        (
            ffmpeg
            .input(src, ss=start)
            .output(dst, vframes=1)
            .run(overwrite_output=True, quiet=True)
        )
    elif output_format == "mp3":
        (
            ffmpeg
            .input(src, ss=start)
            .output(dst, t=duration, acodec="libmp3lame", **{"q:a": 2})
            .run(overwrite_output=True, quiet=True)
        )
    else:
        (
            ffmpeg
            .input(src, ss=start)
            .output(dst, t=duration, vcodec="copy", acodec="aac",
                    **{"avoid_negative_ts": "make_zero"})
            .run(overwrite_output=True, quiet=True)
        )


def _download_douyin(original_url, dest_path):
    canonical = douyin_service.resolve_douyin_url(original_url)
    video_id = douyin_service.extract_video_id(canonical)

    share_reason = None
    if video_id:
        try:
            info = douyin_service.share_page_info(video_id)
            douyin_service.download_direct(info["direct_url"], dest_path)
            return
        except Exception as e:
            share_reason = douyin_service.clean_error(str(e))
            if os.path.exists(dest_path):
                os.remove(dest_path)
    else:
        share_reason = "ID video tidak ditemukan di link."

    try:
        _download_with_ytdlp(canonical, dest_path, douyin=True)
    except Exception as e:
        raise Exception(
            "Douyin gagal lewat dua jalur. "
            f"Halaman share: {share_reason} | "
            f"yt-dlp: {douyin_service.clean_error(str(e))}"
        )


def _download_with_ytdlp(url, dest_path, douyin=False, resolution="best"):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "format": _resolution_format(resolution),
        "outtmpl": dest_path,
        "socket_timeout": 60,
        "retries": 10,
        "fragment_retries": 10,
        # Satu video saja meski tautan membawa parameter playlist.
        "noplaylist": True,
        # YouTube/Facebook mengirim video sebagai ratusan fragmen; mengunduh
        # 4 fragmen sekaligus mempercepat tanpa mengubah hasil akhirnya.
        "concurrent_fragment_downloads": 4,
        # Hasil gabungan video+audio selalu jadi .mp4 (bukan .mkv).
        "merge_output_format": "mp4",
        # Lapis pengaman kedua: saat kualitas setara, pilih H.264 + AAC
        # yang kompatibel dengan semua HP/browser.
        "format_sort": ["vcodec:h264", "acodec:aac"],
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
            ydl.download([url])
    finally:
        if temp_cookie and os.path.exists(temp_cookie):
            try:
                os.remove(temp_cookie)
            except OSError:
                pass
