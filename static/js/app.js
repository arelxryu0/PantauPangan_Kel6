/* =========================================================
   Pantau Pangan Riau - skrip utama
   1. Pengaturan warna & format
   2. Pembuat grafik (dibaca dari <canvas data-jenis>)
   3. Pindah pilihan tanpa memuat ulang halaman
   4. Pencarian tabel, tombol proses, tab
   5. Pemantau status pelatihan AutoGluon
   ========================================================= */

const WARNA = { hijau: '#2E6B4E', abu: '#8A978F', kunyit: '#C98A12', cabai: '#B83227', biru: '#3D6F99' };
const WARNA_KOTA = { 'Pekanbaru': '#2E6B4E', 'Dumai': '#C98A12', 'Tembilahan': '#3D6F99' };

if (window.Chart) {
  Chart.defaults.font.family = '"Plus Jakarta Sans", system-ui, sans-serif';
  Chart.defaults.color = '#5F6E66';
}

function formatRp(v) {
  return 'Rp ' + Math.round(v).toLocaleString('id-ID');
}

function formatAngka(v, satuan) {
  return String(v).replace('.', ',') + (satuan || '');
}

function opsiGrafikHarga() {
  return {
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'top', align: 'end', labels: { boxWidth: 12, boxHeight: 12, filter: i => !i.text.startsWith('_') } },
      tooltip: {
        filter: i => !i.dataset.label.startsWith('_'),
        callbacks: { label: c => `${c.dataset.label}: ${c.raw == null ? '-' : formatRp(c.raw)}` }
      }
    },
    scales: {
      x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } },
      y: { ticks: { callback: v => formatRp(v) }, grid: { color: '#E6ECE7' } }
    }
  };
}

function garis(label, data, warna, ekstra = {}) {
  return Object.assign({ label, data, borderColor: warna, backgroundColor: warna, borderWidth: 2, pointRadius: 0, tension: .25, spanGaps: true }, ekstra);
}

/* ---------- 2. Pembuat grafik per jenis ---------- */
const PEMBUAT_GRAFIK = {
  'harga-kota': (c, d) => new Chart(c, {
    type: 'line',
    data: { labels: d.label, datasets: d.seri.map(s => garis(s.nama, s.data, WARNA_KOTA[s.nama])) },
    options: opsiGrafikHarga()
  }),

  'ramal': (c, d) => {
    const o = opsiGrafikHarga();
    o.plugins.tooltip.callbacks.label = ctx => {
      if (ctx.dataset.label === 'Rentang 10%–90%') {
        const bawah = ctx.chart.data.datasets[0].data[ctx.dataIndex];
        return ctx.raw == null ? null : `Rentang: ${formatRp(bawah)} – ${formatRp(ctx.raw)}`;
      }
      return `${ctx.dataset.label}: ${ctx.raw == null ? '-' : formatRp(ctx.raw)}`;
    };
    return new Chart(c, {
      type: 'line',
      data: {
        labels: d.label,
        datasets: [
          garis('_bawah', d.bawah, 'transparent', { spanGaps: false, borderWidth: 0 }),
          garis('Rentang 10%–90%', d.atas, 'transparent', { spanGaps: false, borderWidth: 0, fill: '-1', backgroundColor: 'rgba(184, 50, 39, .13)' }),
          garis('Harga aktual', d.aktual, WARNA.hijau, { spanGaps: false }),
          garis('Ramalan AutoGluon', d.prediksi, WARNA.cabai, { spanGaps: false, borderDash: [6, 4], pointRadius: 3 })
        ]
      },
      options: o
    });
  },

  'uji': (c, d) => {
    const o = opsiGrafikHarga();
    o.scales.x.ticks.maxTicksLimit = 4;
    return new Chart(c, {
      type: 'line',
      data: { labels: d.label, datasets: [garis('Harga asli', d.aktual, WARNA.hijau, { pointRadius: 3 }), garis('Ramalan model', d.prediksi, WARNA.kunyit, { pointRadius: 3 })] },
      options: o
    });
  },

  // Batang horizontal umum: { label: [...], data: [...], warna?: [...], satuan?: '%' }
  'batang-h': (c, d) => new Chart(c, {
    type: 'bar',
    data: {
      labels: d.label,
      datasets: [{ data: d.data, backgroundColor: d.warna || WARNA.hijau, borderRadius: 4, maxBarThickness: 22 }]
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: x => formatAngka(x.raw, d.satuan) } } },
      scales: {
        x: { beginAtZero: true, grid: { color: '#E6ECE7' }, ticks: { callback: v => formatAngka(v, d.satuan) } },
        y: { grid: { display: false }, ticks: { autoSkip: false, font: { size: 11 } } }
      }
    }
  }),

  'bulanan': (c, d) => new Chart(c, {
    type: 'bar',
    data: {
      labels: d.label,
      datasets: d.seri.map(s => ({ label: s.nama, data: s.data, backgroundColor: WARNA_KOTA[s.nama], borderRadius: 4, maxBarThickness: 26 }))
    },
    options: opsiGrafikHarga()
  }),

  'disparitas': (c, d) => {
    const o = opsiGrafikHarga();
    o.plugins.legend.display = false;
    o.plugins.tooltip.callbacks.label = x => `Selisih termahal–termurah: ${formatAngka(x.raw, '%')}`;
    o.scales.y.ticks.callback = v => v + '%';
    o.scales.y.beginAtZero = true;
    return new Chart(c, {
      type: 'line',
      data: { labels: d.label, datasets: [garis('Selisih', d.data, WARNA.biru, { fill: true, backgroundColor: 'rgba(61, 111, 153, .12)' })] },
      options: o
    });
  }
};

function gambarSparkline(akar = document) {
  akar.querySelectorAll('canvas[data-spark]').forEach(c => {
    const data = JSON.parse(c.dataset.spark || '[]');
    if (data.length < 2 || Chart.getChart(c)) return;
    const naik = data[data.length - 1] > data[0];
    new Chart(c, {
      type: 'line',
      data: { labels: data.map((_, i) => i), datasets: [{ data, borderColor: naik ? WARNA.cabai : WARNA.hijau, borderWidth: 1.5, pointRadius: 0, tension: .3 }] },
      options: {
        maintainAspectRatio: false, animation: false, events: [],
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false } }
      }
    });
  });
}

function gambarGrafik(akar = document) {
  if (!window.Chart) return;
  akar.querySelectorAll('canvas[data-jenis]').forEach(c => {
    const sumber = document.getElementById(c.dataset.sumber);
    const pembuat = PEMBUAT_GRAFIK[c.dataset.jenis];
    if (!sumber || !pembuat) return;
    const data = JSON.parse(sumber.textContent);
    if (!data) return;
    const lama = Chart.getChart(c);
    if (lama) lama.destroy();
    pembuat(c, data);
  });
  gambarSparkline(akar);
}

/* ---------- 3. Pindah pilihan tanpa memuat ulang halaman ----------
   Form dan link dengan atribut data-ajax hanya mengganti isi halaman,
   posisi scroll tetap di tempat. */
let permintaanTerakhir = 0;

async function muatIsi(url, gulirKe) {
  const main = document.querySelector('main.konten');
  const nomor = ++permintaanTerakhir;
  main.classList.add('memuat');
  try {
    const res = await fetch(url, { headers: { 'X-Diminta-Dengan': 'fetch' } });
    if (!res.ok) throw new Error(res.status);
    const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
    const baru = doc.querySelector('main.konten');
    if (!baru) throw new Error('isi tidak ditemukan');
    if (nomor !== permintaanTerakhir) return;   // ada pilihan yang lebih baru
    const y = window.scrollY;
    main.querySelectorAll('canvas').forEach(c => { const g = Chart.getChart(c); if (g) g.destroy(); });
    main.innerHTML = baru.innerHTML;
    document.title = doc.title;
    history.replaceState(null, '', url);
    gambarGrafik(main);
    aktifkanTab();
    const target = gulirKe && document.querySelector(gulirKe);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    else window.scrollTo({ top: y, behavior: 'instant' });
  } catch (e) {
    location.href = url;   // kalau gagal, pakai cara biasa
  } finally {
    if (nomor === permintaanTerakhir) main.classList.remove('memuat');
  }
}

function kirimFormAjax(form) {
  const p = new URLSearchParams(new FormData(form));
  [...p.keys()].forEach(k => { if (!p.get(k)) p.delete(k); });
  const tujuan = form.getAttribute('action') || location.pathname;
  muatIsi(tujuan + (p.toString() ? '?' + p : ''));
}

document.addEventListener('change', e => {
  const form = e.target.closest('form[data-ajax]');
  if (form && e.target.type !== 'search' && e.target.type !== 'date') kirimFormAjax(form);
});

document.addEventListener('submit', e => {
  const form = e.target.closest('form[data-ajax]');
  if (form) { e.preventDefault(); kirimFormAjax(form); return; }
  const teks = e.target.dataset && e.target.dataset.proses;
  if (teks) {
    const btn = e.target.querySelector('button[type=submit]');
    if (btn) { btn.textContent = teks; btn.disabled = true; }
  }
});

document.addEventListener('click', e => {
  const a = e.target.closest('a[data-ajax]');
  if (!a || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  muatIsi(a.href, a.dataset.gulir);
});

/* ---------- 4. Pencarian tabel: <input data-cari="#idTabel"> ---------- */
document.addEventListener('input', e => {
  const sel = e.target.dataset && e.target.dataset.cari;
  if (!sel) return;
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll(sel + ' tbody tr').forEach(tr => {
    tr.hidden = q && !tr.cells[0].textContent.toLowerCase().includes(q);
  });
});

/* Tab berdasarkan #hash. Tab pertama tampil kalau hash tidak cocok. */
function aktifkanTab() {
  const tautan = [...document.querySelectorAll('.tab-nav a')];
  const panel = [...document.querySelectorAll('.tab-panel')];
  if (!tautan.length) return;
  const awal = tautan[0].getAttribute('href').slice(1);
  function tampil() {
    const id = (location.hash || '#' + awal).slice(1);
    const ada = panel.some(p => p.id === id) ? id : awal;
    panel.forEach(p => p.classList.toggle('tampil', p.id === ada));
    tautan.forEach(a => a.classList.toggle('aktif', a.getAttribute('href') === '#' + ada));
    // grafik di tab tersembunyi digambar ulang supaya ukurannya benar
    document.querySelectorAll('#' + ada + ' canvas').forEach(c => { const g = Chart.getChart(c); if (g) g.resize(); });
  }
  tautan.forEach(a => {
    if (a.dataset.siap) return;
    a.dataset.siap = '1';
    a.addEventListener('click', e => {
      e.preventDefault();
      history.replaceState(null, '', a.getAttribute('href'));
      tampil();
    });
  });
  tampil();
}

/* ---------- 5. Pemantau status pelatihan AutoGluon ---------- */
function pantauLatih() {
  const kotak = document.getElementById('statusLatih');
  if (!kotak || kotak.dataset.status !== 'berjalan') return;
  const judul = { siap: 'Belum ada pelatihan', berjalan: 'Sedang melatih', selesai: 'Pelatihan selesai', sebagian: 'Selesai sebagian', gagal: 'Pelatihan gagal' };
  const isi = n => kotak.querySelector(`[data-isi="${n}"]`);
  async function cek() {
    try {
      const res = await fetch(kotak.dataset.url, { cache: 'no-store' });
      const s = await res.json();
      isi('judul').textContent = judul[s.status] || s.status;
      isi('tahap').textContent = s.tahap || '';
      if (s.detik != null) {
        const m = Math.floor(s.detik / 60), d = s.detik % 60;
        isi('waktu').textContent = `Berjalan ${m} menit ${d} detik`;
      }
      isi('log').textContent = (s.log || []).join('\n') || 'Belum ada catatan.';
      if (s.pesan) { isi('pesan').hidden = false; isi('pesan').textContent = s.pesan; }
      if (s.status !== 'berjalan') {
        kotak.className = kotak.className.replace(/status-\w+/, 'status-' + s.status);
        setTimeout(() => location.reload(), 1200);   // tampilkan hasil baru
        return;
      }
    } catch (e) { /* coba lagi */ }
    setTimeout(cek, 3000);
  }
  setTimeout(cek, 2000);
}

window.addEventListener('hashchange', aktifkanTab);

document.addEventListener('DOMContentLoaded', () => {
  gambarGrafik(document);
  aktifkanTab();
  pantauLatih();
});
