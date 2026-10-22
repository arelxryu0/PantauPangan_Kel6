"""
Aturan status peringatan dini.

Status menggabungkan dua hasil AutoGluon:
1. Kenaikan harga hasil ramalan TimeSeriesPredictor dibanding harga terakhir.
2. Peluang naik tajam dari TabularPredictor.

Siaga   : ramalan naik >= 2 x ambang, ATAU peluang naik >= PELUANG_SIAGA
Waspada : ramalan naik >= ambang,     ATAU peluang naik >= PELUANG_WASPADA
Aman    : selain itu
"""
import config

STATUS = ["Aman", "Waspada", "Siaga"]


def status_peringatan(kenaikan, peluang, ambang,
                      p_waspada=config.PELUANG_WASPADA, p_siaga=config.PELUANG_SIAGA):
    level, alasan = 0, []
    if kenaikan is not None:
        if kenaikan >= 2 * ambang:
            level = 2
            alasan.append(f"ramalan naik {kenaikan:.1f}% (>= {2 * ambang:g}%)")
        elif kenaikan >= ambang:
            level = max(level, 1)
            alasan.append(f"ramalan naik {kenaikan:.1f}% (>= {ambang:g}%)")
    if peluang is not None:
        if peluang >= p_siaga:
            level = 2
            alasan.append(f"peluang naik {peluang:.0f}% (>= {p_siaga:g}%)")
        elif peluang >= p_waspada:
            level = max(level, 1)
            alasan.append(f"peluang naik {peluang:.0f}% (>= {p_waspada:g}%)")
    return STATUS[level], alasan


def kategori_peluang(peluang):
    if peluang is None:
        return None
    if peluang >= config.PELUANG_SIAGA:
        return "Tinggi"
    if peluang >= config.PELUANG_WASPADA:
        return "Sedang"
    return "Rendah"
