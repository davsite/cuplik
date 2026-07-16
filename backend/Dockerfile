# Backend Cuplik — siap untuk Hugging Face Spaces / Render (Docker)
FROM python:3.12-slim

# ffmpeg wajib ada untuk memotong video/audio/gambar
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HF Spaces butuh folder yang bisa ditulis oleh user non-root
RUN mkdir -p /app/temp_media && chmod 777 /app/temp_media

# HF Spaces memakai port 7860; Render mengisi $PORT sendiri.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
