import React, { useState, useRef, useEffect, useMemo } from 'react';
import {
  Search, Scissors, Download, Loader2, AlertCircle, CheckCircle,
  Tv, Camera, Hash, Music, Globe, Image as ImageIcon,
  Sun, Moon, Clock, Volume2,
} from 'lucide-react';

// Alamat backend:
// - Saat hosting: isi REACT_APP_API_URL (lihat .env.example) dengan URL
//   backend online, mis. https://username-cuplik-backend.hf.space
// - Saat development: otomatis pakai host tempat halaman dibuka + port 8000.
//   Di PC -> localhost; di HP -> IP LAN PC-mu (kunci agar HP tidak
//   "Failed to fetch", karena 127.0.0.1 di HP menunjuk ke HP itu sendiri).
const API = (
  process.env.REACT_APP_API_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000`
).replace(/\/+$/, '');

/* ---- Pengenalan platform dari URL (7 platform) ---------------------------- */
const PLATFORMS = [
  { key: 'youtube',   name: 'YouTube',   Icon: Tv,        color: '#ef4444', match: (u) => /youtube\.com|youtu\.be/.test(u) },
  { key: 'tiktok',    name: 'TikTok',    Icon: Music,     color: '#2dd4bf', match: (u) => /tiktok\.com/.test(u) },
  { key: 'douyin',    name: 'Douyin',    Icon: Music,     color: '#fb7185', match: (u) => /douyin\.com/.test(u) },
  { key: 'instagram', name: 'Instagram', Icon: Camera,    color: '#ec4899', match: (u) => /instagram\.com/.test(u) },
  { key: 'facebook',  name: 'Facebook',  Icon: Globe,     color: '#3b82f6', match: (u) => /facebook\.com|fb\.watch/.test(u) },
  { key: 'x',         name: 'X',         Icon: Hash,      color: '#94a3b8', match: (u) => /twitter\.com|x\.com/.test(u) },
  { key: 'rednote',   name: 'Rednote',   Icon: ImageIcon, color: '#f43f5e', match: (u) => /xiaohongshu\.com|xhslink|rednote/.test(u) },
];

const platformOf = (url) => PLATFORMS.find((p) => p.match(url || '')) || null;

const fmt = (s) => {
  if (!Number.isFinite(s)) return '00:00';
  const m = Math.floor(s / 60).toString().padStart(2, '0');
  const sec = Math.floor(s % 60).toString().padStart(2, '0');
  return `${m}:${sec}`;
};

// Ukuran file otomatis: B / KB / MB / GB.
const humanBytes = (n) => {
  if (!Number.isFinite(n)) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let v = n, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
};

// Tema awal: ingat pilihan terakhir; kalau belum pernah memilih,
// ikuti preferensi sistem (gelap/terang) perangkat.
const initialTheme = () => {
  try {
    const saved = localStorage.getItem('cuplik-theme');
    if (saved === 'dark' || saved === 'light') return saved;
  } catch (_) {}
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
};

export default function App() {
  const [theme, setTheme] = useState(initialTheme);
  const [url, setUrl] = useState('');
  const [state, setState] = useState('idle'); // idle|parsing|preview|processing|downloading|error
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [prog, setProg] = useState(null); // {loaded, total}

  const [video, setVideo] = useState({ title: '', thumbnail: '', streamUrl: '', duration: 0, qualities: [] });
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(0);
  const [now, setNow] = useState(0);
  const [format, setFormat] = useState('mp4');
  const [resolution, setResolution] = useState('best');

  const videoRef = useRef(null);
  const trackRef = useRef(null);
  const dragRef = useRef(null);
  const dark = theme === 'dark';

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.background = dark ? '#0A0D16' : '#F6F4EF';
    try { localStorage.setItem('cuplik-theme', theme); } catch (_) {}
  }, [dark, theme]);

  // Cegah fitur "Terjemahkan halaman" (Google Translate dll) mengutak-atik DOM.
  // Penerjemah menukar node teks, lalu React gagal removeChild/insertBefore
  // -> crash. Menandai halaman "notranslate" menghentikannya untuk semua HP.
  useEffect(() => {
    const html = document.documentElement;
    html.setAttribute('translate', 'no');
    html.classList.add('notranslate');
    if (!document.querySelector('meta[name="google"]')) {
      const meta = document.createElement('meta');
      meta.name = 'google';
      meta.content = 'notranslate';
      document.head.appendChild(meta);
    }
  }, []);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(''), 3200);
    return () => clearTimeout(id);
  }, [toast]);

  // Preview memutar hanya di dalam rentang potong + lacak playhead.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || state !== 'preview') return;
    const onTime = () => {
      setNow(v.currentTime);
      if (v.currentTime >= end) v.currentTime = start;
      if (v.currentTime < start - 0.3) v.currentTime = start;
    };
    v.addEventListener('timeupdate', onTime);
    return () => v.removeEventListener('timeupdate', onTime);
  }, [start, end, state]);

  const active = platformOf(url);
  const busy = state === 'processing' || state === 'downloading';

  const resOptions = useMemo(() => {
    const opts = [{ label: 'Terbaik', value: 'best' }];
    (video.qualities || []).forEach((q) => opts.push({ label: q.label, value: String(q.height) }));
    return opts;
  }, [video.qualities]);

  // Jangan bangun URL stream kalau link videonya kosong (hindari
  // permintaan ?url=undefined ke server).
  const streamSrc = useMemo(
    () => (video.streamUrl ? `${API}/api/stream?url=${encodeURIComponent(video.streamUrl)}` : undefined),
    [video.streamUrl],
  );

  const seek = (t) => { if (videoRef.current) videoRef.current.currentTime = t; };

  /* ---- Timeline potong berbasis pointer (jalan di mouse & sentuh HP) ------ */
  const posToTime = (clientX) => {
    const el = trackRef.current;
    if (!el || !video.duration) return 0;
    const r = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    return ratio * video.duration;
  };
  const applyDrag = (t) => {
    if (dragRef.current === 'start') { const v = Math.max(0, Math.min(t, end - 1)); setStart(v); seek(v); }
    else if (dragRef.current === 'end') { const v = Math.min(video.duration, Math.max(t, start + 1)); setEnd(v); seek(v); }
  };
  const beginDrag = (e) => {
    if (busy || !video.duration) return;
    const t = posToTime(e.clientX);
    dragRef.current = Math.abs(t - start) <= Math.abs(t - end) ? 'start' : 'end';
    try { trackRef.current.setPointerCapture(e.pointerId); } catch (_) {}
    applyDrag(t);
  };
  const moveDrag = (e) => { if (dragRef.current) applyDrag(posToTime(e.clientX)); };
  const endDrag = (e) => {
    dragRef.current = null;
    try { trackRef.current.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  const nudge = (which, d) => {
    if (which === 'start') { const v = Math.max(0, Math.min(start + d, end - 1)); setStart(v); seek(v); }
    else { const v = Math.min(video.duration, Math.max(end + d, start + 1)); setEnd(v); seek(v); }
  };
  const markStart = () => setStart(Math.max(0, Math.min(Math.floor(now), end - 1)));
  const markEnd = () => setEnd(Math.min(video.duration, Math.max(Math.ceil(now), start + 1)));

  const fetchInfo = async () => {
    if (!url.trim()) return;
    setState('parsing'); setError('');
    try {
      const r = await fetch(`${API}/api/info`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || 'Tautan gagal dibaca.');
      const d = j.data;
      const dur = d.duration || 60;
      setVideo({ title: d.title, thumbnail: d.thumbnail, streamUrl: d.direct_url, duration: dur, qualities: d.qualities || [] });
      setStart(0); setEnd(dur); setNow(0); setResolution('best');
      setState('preview');
    } catch (e) {
      setError(mapNetErr(e)); setState('error');
    }
  };

  const download = async () => {
    setState('processing'); setError(''); setProg(null);
    try {
      const r = await fetch(`${API}/api/process`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          start_time: Math.floor(start),
          end_time: Math.floor(end),
          format,
          resolution: format === 'mp4' ? resolution : 'best',
        }),
      });
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || 'Server gagal memproses klip.'); }

      // Baca body sebagai aliran supaya bisa menampilkan progres transfer.
      let blob;
      if (r.body && r.body.getReader) {
        const total = Number(r.headers.get('Content-Length')) || 0;
        const reader = r.body.getReader();
        const chunks = [];
        let loaded = 0;
        setState('downloading'); setProg({ loaded: 0, total });
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value); loaded += value.length;
          setProg({ loaded, total });
        }
        blob = new Blob(chunks);
      } else {
        blob = await r.blob();
      }

      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = `Cuplik_${fmt(start).replace(':', '-')}-${fmt(end).replace(':', '-')}.${format}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(href);
      setState('preview'); setProg(null);
      setToast('Klip berhasil diunduh.');
    } catch (e) {
      setError(mapNetErr(e)); setState('error'); setProg(null);
    }
  };

  /* ---- token warna per tema ---------------------------------------------- */
  const c = {
    page: dark ? 'bg-[#0A0D16] text-[#EDEFF7]' : 'bg-[#F6F4EF] text-[#1C1F2A]',
    card: dark ? 'bg-white/[.04] border-white/10 backdrop-blur-md'
               : 'bg-white/90 border-black/[.07] backdrop-blur-md shadow-sm',
    sub: dark ? 'text-slate-400' : 'text-slate-500',
    field: dark ? 'bg-[#0D1120]/80 border-white/10 text-slate-100 placeholder-slate-500'
                : 'bg-white border-black/10 text-slate-900 placeholder-slate-400 shadow-sm',
    inset: dark ? 'bg-[#0D1120]/70 border-white/10 backdrop-blur-md'
                : 'bg-white/80 border-black/[.07] backdrop-blur-md shadow-sm',
    chip: dark ? 'bg-white/[.04] border-white/10 text-slate-300'
               : 'bg-white border-black/[.08] text-slate-600',
    chipOn: dark ? 'bg-amber-500/15 border-amber-500/50 text-amber-300'
                 : 'bg-amber-500/10 border-amber-500/60 text-amber-700',
    segWrap: dark ? 'border-white/10 bg-black/20' : 'border-black/[.08] bg-black/[.03]',
    segIdle: dark ? 'text-slate-300 hover:bg-white/5' : 'text-slate-600 hover:bg-black/5',
    track: dark ? 'bg-[#0A0E1A] border-white/10' : 'bg-[#E9E5DC] border-black/10',
    barBg: dark ? 'bg-white/10' : 'bg-black/10',
  };
  const cta = 'bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-slate-950';

  const clipLen = Math.max(0, Math.floor(end - start));
  const pct = (t) => (video.duration ? (t / video.duration) * 100 : 0);
  const resLabel = resOptions.find((o) => o.value === resolution)?.label || 'Terbaik';
  const progPct = prog && prog.total ? Math.round((prog.loaded / prog.total) * 100) : null;

  return (
    <div translate="no" className={`notranslate relative min-h-screen font-sans transition-colors duration-300 ${c.page}`}>
      <div className="hero-glow" aria-hidden="true" />

      <header className="relative z-10 max-w-4xl mx-auto px-5 pt-6 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="grid place-items-center w-9 h-9 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 text-slate-950 shadow-lg shadow-amber-500/25">
            <Scissors size={19} />
          </span>
          <span className="font-display text-xl font-extrabold tracking-tight">Cuplik</span>
          <span className={`hidden sm:inline text-[11px] font-mono uppercase tracking-[.2em] ${c.sub}`}>ruang potong</span>
        </div>
        <button onClick={() => setTheme(dark ? 'light' : 'dark')} aria-label="Ganti tema"
          className={`p-2.5 rounded-xl border transition-colors ${c.chip} hover:border-amber-500/60`}>
          {dark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </header>

      <main className="relative z-10 max-w-4xl mx-auto px-5 pb-16">
        <section className="pt-7 md:pt-12 pb-6 max-w-2xl">
          <h1 className="font-display text-3xl md:text-[2.6rem] font-extrabold tracking-tight leading-[1.12]">
            Ambil klipnya.{' '}
            <span className="bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">Potong pas.</span>
          </h1>
          <p className={`mt-2.5 text-base ${c.sub}`}>
            Tempel tautan, tandai bagian yang kamu mau, unduh sebagai video, audio, atau gambar.
          </p>

          <div className="mt-6 relative flex items-center">
            <span className="absolute left-4">
              {active ? <active.Icon size={18} style={{ color: active.color }} /> : <Search size={18} className={c.sub} />}
            </span>
            <input value={url} onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchInfo()}
              placeholder="Tempel tautan video…"
              className={`w-full border rounded-2xl pl-11 pr-28 py-4 outline-none focus:ring-2 focus:ring-amber-500/70 focus:border-amber-500/50 transition ${c.field}`} />
            <button onClick={fetchInfo} disabled={state === 'parsing' || !url.trim()}
              className={`absolute right-2 px-5 py-2.5 rounded-xl font-bold disabled:opacity-40 transition-colors shadow-md shadow-amber-500/20 ${cta}`}>
              {state === 'parsing' ? <Loader2 className="animate-spin" size={18} /> : 'Ambil'}
            </button>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {PLATFORMS.map((p) => {
              const on = active?.key === p.key;
              return (
                <span key={p.key}
                  className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-full border transition-all duration-200 ${on ? c.chipOn : c.chip}`}>
                  <p.Icon size={13} style={{ color: p.color }} /> {p.name}
                </span>
              );
            })}
          </div>
        </section>

        {state === 'error' && (
          <div className={`anim-fade-in mb-6 flex items-start gap-3 rounded-2xl border p-4 text-sm ${dark ? 'border-rose-500/40 bg-rose-500/10 text-rose-300' : 'border-rose-400/50 bg-rose-50 text-rose-700'}`}>
            <AlertCircle size={18} className="shrink-0 mt-0.5" />
            <p className="break-words">{error}</p>
          </div>
        )}

        {(state === 'preview' || busy) && (
          <section className="anim-fade-up grid lg:grid-cols-5 gap-5">
            <div className="lg:col-span-3">
              <div className={`rounded-2xl overflow-hidden border bg-black shadow-xl ${dark ? 'border-white/10 shadow-black/40' : 'border-black/10 shadow-black/10'}`}>
                <video ref={videoRef}
                  src={streamSrc}
                  poster={video.thumbnail} controls playsInline preload="metadata"
                  className="w-full max-h-[62vh] object-contain bg-black" />
              </div>
              <div className="mt-3 flex items-start gap-2">
                {active && <span className="mt-0.5 shrink-0"><active.Icon size={16} style={{ color: active.color }} /></span>}
                <div className="min-w-0">
                  <h2 className="font-semibold leading-snug break-words"
                    style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {video.title}
                  </h2>
                  <div className={`mt-1 flex gap-4 text-xs font-mono ${c.sub}`}>
                    <span className="inline-flex items-center gap-1"><Clock size={13} /> {fmt(video.duration)} total</span>
                    <span className="inline-flex items-center gap-1 text-amber-500"><Scissors size={13} /> {fmt(clipLen)} terpilih</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:col-span-2 space-y-5">
              {/* Timeline potong — elemen tanda tangan */}
              <div className={`rounded-2xl border p-4 ${c.inset}`}>
                <div className="flex items-center justify-between mb-3">
                  <span className={`text-[11px] font-mono uppercase tracking-[.18em] ${c.sub}`}>Rentang potong</span>
                  <span className="text-xs font-mono px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-500 border border-amber-500/30">{fmt(clipLen)}</span>
                </div>

                <div
                  ref={trackRef}
                  onPointerDown={beginDrag} onPointerMove={moveDrag}
                  onPointerUp={endDrag} onPointerCancel={endDrag}
                  className={`filmstrip relative h-[4.5rem] rounded-xl border overflow-hidden cursor-pointer ${c.track}`}
                  style={{ touchAction: 'none' }}
                >
                  {/* wilayah terpilih */}
                  <div className="absolute top-0 bottom-0 bg-amber-500/20 border-x-2 border-amber-500 pointer-events-none"
                    style={{ left: `${pct(start)}%`, right: `${100 - pct(end)}%` }} />
                  {/* playhead */}
                  <div className="absolute top-0 bottom-0 w-px bg-amber-300 pointer-events-none"
                    style={{ left: `${pct(now)}%`, boxShadow: '0 0 10px #fcd34d' }} />
                  {/* gagang mulai */}
                  <div role="slider" tabIndex={0} aria-label="Waktu mulai"
                    aria-valuemin={0} aria-valuemax={Math.floor(video.duration)} aria-valuenow={Math.floor(start)}
                    onKeyDown={(e) => { if (e.key === 'ArrowLeft') nudge('start', -1); if (e.key === 'ArrowRight') nudge('start', 1); }}
                    className="absolute top-0 bottom-0 w-8 -translate-x-1/2 flex items-center justify-center outline-none group"
                    style={{ left: `${pct(start)}%` }}>
                    <span className="w-2.5 h-11 rounded-full bg-gradient-to-b from-white to-amber-100 border-2 border-amber-500 shadow-md group-focus-visible:ring-4 group-focus-visible:ring-amber-500/40" />
                  </div>
                  {/* gagang selesai */}
                  <div role="slider" tabIndex={0} aria-label="Waktu selesai"
                    aria-valuemin={0} aria-valuemax={Math.floor(video.duration)} aria-valuenow={Math.floor(end)}
                    onKeyDown={(e) => { if (e.key === 'ArrowLeft') nudge('end', -1); if (e.key === 'ArrowRight') nudge('end', 1); }}
                    className="absolute top-0 bottom-0 w-8 -translate-x-1/2 flex items-center justify-center outline-none group"
                    style={{ left: `${pct(end)}%` }}>
                    <span className="w-2.5 h-11 rounded-full bg-gradient-to-b from-white to-amber-100 border-2 border-amber-500 shadow-md group-focus-visible:ring-4 group-focus-visible:ring-amber-500/40" />
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className={`rounded-xl border px-3 py-2 ${c.card}`}>
                    <div className={`text-[10px] font-mono uppercase tracking-[.15em] ${c.sub}`}>Mulai</div>
                    <div className="font-mono text-lg leading-none mt-1">{fmt(start)}</div>
                  </div>
                  <div className={`rounded-xl border px-3 py-2 ${c.card}`}>
                    <div className={`text-[10px] font-mono uppercase tracking-[.15em] ${c.sub}`}>Selesai</div>
                    <div className="font-mono text-lg leading-none mt-1">{fmt(end)}</div>
                  </div>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <button onClick={markStart} className={`text-xs font-medium rounded-xl border py-2 transition ${c.chip} hover:border-amber-500/70 hover:text-amber-500`}>Tandai mulai di sini</button>
                  <button onClick={markEnd} className={`text-xs font-medium rounded-xl border py-2 transition ${c.chip} hover:border-amber-500/70 hover:text-amber-500`}>Tandai selesai di sini</button>
                </div>
                <p className={`mt-2 text-[11px] ${c.sub}`}>Seret gagang, atau ketuk timeline. Bisa juga panah ←/→ setelah memilih gagang.</p>
              </div>

              {/* Format + resolusi */}
              <div className={`rounded-2xl border p-4 ${c.inset}`}>
                <span className={`block text-[11px] font-mono uppercase tracking-[.18em] mb-2 ${c.sub}`}>Format</span>
                <div className={`grid grid-cols-3 gap-1.5 p-1 rounded-2xl border ${c.segWrap}`}>
                  {[{ v: 'mp4', label: 'Video', Icon: Tv }, { v: 'mp3', label: 'Audio', Icon: Volume2 }, { v: 'jpg', label: 'Gambar', Icon: ImageIcon }].map((f) => (
                    <button key={f.v} onClick={() => setFormat(f.v)}
                      className={`flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-semibold transition ${format === f.v ? `${cta} shadow-md shadow-amber-500/20` : c.segIdle}`}>
                      <f.Icon size={15} /> {f.label}
                    </button>
                  ))}
                </div>

                <div className="mt-3.5">
                  <span className={`block text-[11px] font-mono uppercase tracking-[.18em] mb-1.5 ${c.sub}`}>Resolusi</span>
                  <select value={resolution} onChange={(e) => setResolution(e.target.value)} disabled={format !== 'mp4'}
                    className={`w-full rounded-xl border px-3 py-2.5 font-medium outline-none focus:ring-2 focus:ring-amber-500/70 transition ${c.field} disabled:opacity-50 disabled:cursor-not-allowed`}>
                    {resOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                  <p className={`mt-1 text-[11px] ${c.sub}`}>
                    {format !== 'mp4' ? 'Resolusi hanya berlaku untuk video MP4.'
                      : (video.qualities?.length ? 'Pilih tinggi maksimum video.' : 'Sumber ini menyediakan satu kualitas.')}
                  </p>
                </div>
              </div>

              {/* Progres unduh */}
              {busy && (
                <div className={`rounded-2xl border p-4 ${c.inset}`}>
                  {state === 'processing' ? (
                    <div className="flex items-center gap-2 text-sm">
                      <Loader2 className="animate-spin text-amber-500" size={16} />
                      <span>Memproses di server… (mengambil & memotong)</span>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center justify-between text-sm mb-2">
                        <span className="inline-flex items-center gap-2"><Download size={15} className="text-amber-500" /> Mengunduh hasil</span>
                        <span className="font-mono">{progPct !== null ? `${progPct}%` : humanBytes(prog?.loaded || 0)}</span>
                      </div>
                      <div className={`h-2 rounded-full overflow-hidden ${c.barBg}`}>
                        <div className="h-full bg-gradient-to-r from-amber-500 to-orange-500 transition-[width] duration-150"
                          style={{ width: progPct !== null ? `${progPct}%` : '100%' }} />
                      </div>
                      <div className={`mt-1.5 text-[11px] font-mono ${c.sub}`}>
                        {humanBytes(prog?.loaded || 0)}{prog?.total ? ` / ${humanBytes(prog.total)}` : ''}
                      </div>
                    </>
                  )}
                </div>
              )}

              <button onClick={download} disabled={busy}
                className={`w-full sticky bottom-3 lg:static z-10 flex items-center justify-center gap-2 rounded-2xl font-bold py-4 shadow-lg shadow-amber-500/30 transition-colors disabled:opacity-60 ${cta}`}>
                {busy
                  ? <><Loader2 className="animate-spin" size={18} /> {state === 'downloading' ? 'Mengunduh…' : 'Memproses…'}</>
                  : <><Download size={18} /> Unduh {format.toUpperCase()} · {format === 'mp4' ? resLabel : '—'} · {fmt(clipLen)}</>}
              </button>
            </div>
          </section>
        )}
      </main>

      {toast && (
        <div className="anim-fade-up fixed bottom-5 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 rounded-full bg-emerald-500 text-slate-950 font-semibold px-4 py-2.5 shadow-lg shadow-emerald-500/30">
          <CheckCircle size={18} /> {toast}
        </div>
      )}
    </div>
  );
}

// Pesan jaringan yang lebih membantu daripada "Failed to fetch" mentah.
function mapNetErr(e) {
  const m = (e && e.message) || String(e);
  if (/Failed to fetch|NetworkError|Load failed/i.test(m)) {
    return 'Tidak bisa menghubungi server. Pastikan backend jalan dengan --host 0.0.0.0 dan HP berada di Wi-Fi yang sama dengan PC (atau REACT_APP_API_URL sudah diisi jika web sudah di-hosting).';
  }
  return m;
}
