# -*- coding: utf-8 -*-
"""大動脈サイジング: 5 出力 の画面の動き（CSV・PDF・PNG）
AortaSizingWidget の一部（OutputUIMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class OutputUIMixin:

    def onHelixCsv(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        if not L.tlValid(): self._busy(L.extractTL, self._say)
        if not L.tlValid(): self._say("真腔がたどれませんでした（3 計画の「真腔に沿わせる」を確認）。"); return
        self._say("逆向きにもたどって確かめています…"); self._busy(L.tlQC)
        r = self._busy(L.saveDissectionCSV)
        if not r: self._say("書き出せませんでした。"); return
        h = L.helixMetrics() or {}; qc = L.tl.get("qc")
        self._done(os.path.dirname(r[0]), "解離の形（断面ごとの表）")
        if h.get("dissected"):
            ks = np.arange(L._k(h["s0"]), L._k(h["s1"]) + 1); nq = int((qc[ks] < 0.7).sum() * STEP) if qc is not None else 0
            self._say(f"解離 {h['length']:.0f} mm・回転 正味 {h['net']:+.0f}°（{h['hand']}）・合計 {h['total']:.0f}°。"
                      + (f"要確認 {nq} mm（上下のたどりが食い違う所。3 計画の「真腔を直す」で確かめてから、もう一度押してください）" if nq else "上下のたどりは一致（要確認なし）。")
                      + f" {os.path.basename(r[1])} に 1 行追加。")
        else: self._say("解離は見つかりませんでした（一覧には「なし」で 1 行）。")

    def onSineCsv(self):
        r = self._busy(self.logic.saveSineCSV)
        if not r: self._say("SINE の目安がまだありません（3 計画で「真腔に沿わせる」→ 範囲を決める）。"); return
        self._done(os.path.dirname(r[1]), "SINE の目安（" + os.path.basename(r[1]) + " に 1 行追加）")

    def onPDF(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        keep = (L.curS, L.rot)
        pdf = self._busy(lambda: L.sizingSheet(self._tpl() if self._tpl() != "自由" else "EVAR", self._say))
        L.setRotation(keep[1]); L.setPosition(keep[0])
        if pdf:
            self._done(os.path.dirname(pdf), "サイジングシート")
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(pdf))

    def onPNG(self):
        L = self.logic
        if L.P is None: return
        r = self._busy(lambda: L.exportImages(None, self._say))
        if r: self._done(r[0], f"画像 {len(r[1])} 枚")

    def onSecPNG(self):
        L = self.logic
        if L.P is None: return
        def run():
            d = L.outDir(); q, _ = L.renderSection(title="断面"); fn = os.path.join(d, f"section_{L.rel(L.curS):+.0f}mm.png"); q.save(fn); return d
        d = self._busy(run)
        if d: self._done(d, "断面の画像")
