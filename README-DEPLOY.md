# 🚀 Panduan Deploy Cuplik — Hosting Gratis

Panduan lengkap menghosting aplikasi ini secara **gratis**:
**Backend** → Hugging Face Spaces (Docker) · **Frontend** → Vercel.

Kenapa dipisah? Backend butuh `ffmpeg` + `yt-dlp` (harus Docker),
sedangkan frontend cuma file statis hasil `npm run build`.

---

## ✅ Sebelum mulai — pastikan bug sudah diperbaiki

Ada 1 bug fatal di `backend/main.py` yang bikin fitur unduh selalu error 500.
Kalau kamu pakai zip `cuplik_fixed.zip`, ini sudah beres. Kalau edit manual:

1. Ganti import:
   ```python
   # LAMA (salah):
   from fastapi.background import BackgroundTasks
   # BARU (benar):
   from starlette.background import BackgroundTask
   ```
2. Ganti pemakaiannya di endpoint `/api/process`:
   ```python
   # LAMA (salah):
   background=BackgroundTasks(_safe_remove, file_path),
   # BARU (benar):
   background=BackgroundTask(_safe_remove, file_path),
   ```

`BackgroundTask` **tanpa "s"** — kelas jamaknya tidak menerima
`(fungsi, argumen)` sehingga setiap unduhan langsung TypeError → 500.

---

## 🟡 Tahap 1 — Deploy Backend ke Hugging Face Spaces

Dockerfile di folder `backend/` memang sudah disiapkan untuk HF Spaces
(port 7860, folder `temp_media` writable, `$PORT` fleksibel untuk Render).

1. Daftar / login di <https://huggingface.co>
2. Klik foto profil → **New Space**
3. Isi:
   - **Space name**: misal `cuplik-backend`
   - **License**: bebas (mis. `mit`)
   - **Space SDK**: pilih **Docker** → template **Blank**
   - **Visibility**: Public
4. Klik **Create Space**
5. Buka tab **Files** → **Add file → Upload files**
6. Upload SEMUA isi folder `backend/`:
   - `Dockerfile`
   - `main.py`
   - `requirements.txt`
   - `.dockerignore`
   - folder `api/` (berisi `yt_dlp_service.py`, `douyin_service.py`, `ffmpeg_service.py`)

   > ⚠️ JANGAN upload folder `venv/`, `__pycache__/`, atau isi `temp_media/` —
   > itu file lokal, cuma bikin build lambat.
7. Commit → HF otomatis build image (~3–5 menit). Pantau di tab **Logs**.
8. Kalau status sudah **Running**, backend live di:
   ```
   https://<username>-cuplik-backend.hf.space
   ```
9. **Tes**: buka `https://<username>-cuplik-backend.hf.space/api/health`
   → harus muncul `{"status":"ok"}`. Kalau iya, lanjut Tahap 2. 🎉

---

## 🟢 Tahap 2 — Deploy Frontend ke Vercel

1. Push project ini ke repo GitHub (boleh satu repo, `frontend/` sebagai subfolder).
2. Daftar / login <https://vercel.com> pakai akun GitHub.
3. **Add New → Project** → pilih repo kamu → **Import**.
4. Pengaturan penting:
   - **Root Directory**: klik *Edit* → arahkan ke folder `frontend`
   - **Framework Preset**: otomatis terdeteksi *Create React App* (biarkan)
5. Buka bagian **Environment Variables**, tambahkan:

   | Name                | Value                                          |
   |---------------------|------------------------------------------------|
   | `REACT_APP_API_URL` | `https://<username>-cuplik-backend.hf.space`   |

   > ⚠️ Tanpa `/` di akhir URL. Variabel ini dibaca **saat build** —
   > kalau nanti diganti, wajib **Redeploy** biar kepakai.
6. Klik **Deploy** → selesai. Web live di `https://<nama-project>.vercel.app`.

---

## 🔵 Alternatif (kalau HF / Vercel tidak cocok)

**Backend → Render.com** (free tier):
1. <https://render.com> → **New → Web Service** → connect repo GitHub
2. **Root Directory**: `backend` · **Runtime**: Docker
3. Dockerfile sudah support `$PORT`-nya Render, tidak perlu diubah apa pun.
4. Catatan free tier: server *sleep* setelah 15 menit sepi; request pertama
   setelah tidur butuh ±1 menit untuk bangun.

**Frontend → Netlify**:
1. <https://netlify.com> → **Add new site → Import from Git**
2. **Base directory**: `frontend` · **Build command**: `npm run build`
   · **Publish directory**: `frontend/build`
3. Tambahkan env var `REACT_APP_API_URL` di *Site settings →
   Environment variables*, lalu redeploy.

---

## 🧪 Checklist tes setelah live

- [ ] `GET /api/health` di URL backend → `{"status":"ok"}`
- [ ] Buka web frontend → tempel link video → klik **Ambil** → preview muncul
- [ ] Geser rentang potong → klik **Unduh** → file benar-benar terunduh
- [ ] Coba format MP3 dan JPG juga

---

## ❗ Hal yang wajib kamu tahu

- **HF Spaces gratis akan sleep** kalau lama tidak dipakai (±48 jam idle).
  Request pertama setelah tidur butuh 1–2 menit untuk cold start.
- **YouTube sering memblokir IP server cloud** ("Sign in to confirm you're
  not a bot"). Ini perilaku YouTube ke datacenter, bukan bug kodemu.
  TikTok / Douyin / Instagram biasanya tetap jalan normal.
- **Douyin dengan cookie asli (opsional)**: kalau jalur share-page gagal,
  kamu bisa menaruh file `cookies_douyin.txt` (format Netscape) di folder
  backend, atau set env var `DOUYIN_COOKIES` berisi path file-nya.
- File hasil potong dihapus otomatis dari `temp_media/` setelah terkirim
  ke user (via `BackgroundTask`), jadi storage server tidak menumpuk.

---

## 💻 Menjalankan lokal (untuk development)

**Backend** (butuh Python 3.12+ dan ffmpeg terpasang):
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Frontend**:
```bash
cd frontend
npm install
npm start
```

Saat lokal, `REACT_APP_API_URL` boleh kosong — frontend otomatis pakai
`http://<host-halaman>:8000`, jadi tes dari HP di Wi-Fi yang sama pun bisa.
