from collections import OrderedDict
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.background import BackgroundTask
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from api import douyin_service
from api.ffmpeg_service import process_media
from api.yt_dlp_service import extract_video_info

import os
import traceback

import requests

os.makedirs("temp_media", exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class URLRequest(BaseModel):
    url: str


class ProcessRequest(BaseModel):
    url: str
    start_time: int
    end_time: int
    format: str
    # BUG LAMA: field ini tidak ada, jadi pilihan resolusi dari frontend
    # diam-diam dibuang dan video selalu diunduh kualitas "best".
    resolution: str = "best"


# ---------------------------------------------------------------------------
# "Kartu identitas" untuk tiap link video.
#
# INTI PERBAIKAN 403 TIKTOK: link CDN TikTok membawa parameter
# `tk=tt_chain_token`. Artinya CDN MEWAJIBKAN cookie `tt_chain_token`
# (yang lahir saat yt-dlp membaca halaman video) ikut dikirim, plus
# Referer https://www.tiktok.com/. Proxy lama hanya mengirim User-Agent
# polos -> TikTok menjawab 403 Forbidden -> preview tidak bisa diputar.
#
# Sekarang: saat /api/info, yt_dlp_service ikut menyerahkan header + cookie
# yang dipakainya. Kita simpan di sini (dibatasi 64 entri terakhir), lalu
# /api/stream memakainya lagi ketika browser meminta video.
# ---------------------------------------------------------------------------
_STREAM_HEADERS: "OrderedDict[str, dict]" = OrderedDict()
_STREAM_HEADERS_MAX = 64


def _remember_stream_headers(url: str, headers: dict):
    if not url or not headers:
        return
    _STREAM_HEADERS[url] = headers
    _STREAM_HEADERS.move_to_end(url)
    while len(_STREAM_HEADERS) > _STREAM_HEADERS_MAX:
        _STREAM_HEADERS.popitem(last=False)


def _fallback_headers_for(url: str) -> dict:
    """Kalau header hasil ekstraksi tidak ada (mis. server baru restart),
    tebak Referer yang paling mungkin diterima CDN masing-masing platform."""
    host = (urlsplit(url).hostname or "").lower()
    if douyin_service.is_douyin_media_host(url):
        return {"Referer": douyin_service.DOUYIN_HOME}
    if "tiktok" in host or "ttwstatic" in host or "byteoversea" in host:
        return {"Referer": "https://www.tiktok.com/"}
    if "xhscdn" in host or "xiaohongshu" in host:
        return {"Referer": "https://www.xiaohongshu.com/"}
    if "cdninstagram" in host or "fbcdn" in host:
        return {"Referer": "https://www.instagram.com/"}
    return {}


@app.get("/api/stream")
def stream_video(url: str, request: Request):
    """Proxy preview: browser minta video ke sini, server ini yang
    mengambilkannya dari CDN sosmed — bebas masalah CORS."""
    try:
        headers = {
            "User-Agent": douyin_service.DESKTOP_UA,
            "Accept": "*/*",
        }

        saved = _STREAM_HEADERS.get(url)
        if saved:
            headers.update(saved)          # cookie + referer asli dari ekstraksi
        else:
            headers.update(_fallback_headers_for(url))

        # Teruskan permintaan "seek" (Range) dari browser.
        range_header = request.headers.get("Range")
        if range_header:
            headers["Range"] = range_header

        client_req = requests.get(
            url, headers=headers, stream=True, timeout=(10, 60)
        )

        resp_headers = {}
        for key, value in client_req.headers.items():
            if key.lower() in ("content-type", "content-length",
                               "content-range", "accept-ranges"):
                resp_headers[key] = value

        def generate():
            try:
                for chunk in client_req.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        yield chunk
            finally:
                client_req.close()

        return StreamingResponse(
            generate(),
            status_code=client_req.status_code,
            headers=resp_headers,
        )
    except Exception:
        print("Error di Streaming Proxy:", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Gagal memutar preview")


@app.post("/api/info")
def get_info(request: URLRequest):
    try:
        info = extract_video_info(request.url)
        # Simpan "kartu identitas" untuk /api/stream, jangan bocorkan cookie
        # ke browser.
        stream_headers = info.pop("stream_headers", None)
        if info.get("direct_url") and stream_headers:
            _remember_stream_headers(info["direct_url"], stream_headers)
        return {"status": "success", "data": info}
    except Exception as e:
        print("ERROR DI BACKEND:", traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/process")
def process_and_download(req: ProcessRequest):
    try:
        file_path = process_media(
            req.url, req.start_time, req.end_time, req.format,
            resolution=req.resolution,
        )
        # BackgroundTask: file hasil dihapus SETELAH selesai terkirim,
        # supaya temp_media tidak menumpuk mp4 lama (bug penyimpanan penuh).
        return FileResponse(
            path=file_path,
            filename=f"download.{req.format}",
            media_type="application/octet-stream",
            background=BackgroundTask(_safe_remove, file_path),
        )
    except Exception as e:
        print("ERROR DI BACKEND:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


def _safe_remove(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@app.get("/api/health")
def health():
    """Dipakai layanan hosting (Render/HF Spaces) untuk cek server hidup."""
    return {"status": "ok"}
