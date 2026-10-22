"""Fungsi bantu kecil untuk membaca hasil AutoGluon."""
import ast
import logging
import re


class TangkapBobot(logging.Handler):
    """Menangkap baris log 'Ensemble weights: {...}' yang dicetak AutoGluon saat melatih."""

    def __init__(self):
        super().__init__(level=0)
        self.bobot = {}

    def emit(self, record):
        try:
            pesan = record.getMessage()
        except Exception:
            return
        if "ensemble weights" not in pesan.lower():
            return
        cocok = re.search(r"\{.*\}", pesan)
        if not cocok:
            return
        try:
            self.bobot = {str(k): float(v) for k, v in ast.literal_eval(cocok.group(0)).items()}
        except Exception:
            pass


class Penangkap:
    """with Penangkap() as t: ... ; t.bobot"""

    def __enter__(self):
        self.handler = TangkapBobot()
        logging.getLogger("autogluon").addHandler(self.handler)
        return self.handler

    def __exit__(self, *exc):
        logging.getLogger("autogluon").removeHandler(self.handler)
        return False


def rapikan_bobot(bobot):
    return {k: round(float(v), 3) for k, v in sorted(bobot.items(), key=lambda x: -x[1]) if float(v) > 0}
