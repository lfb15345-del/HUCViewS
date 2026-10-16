# -*- coding: utf-8 -*-
"""大動脈サイジング: 6 研究（隠しタブ）。Ctrl+Shift+R で出す / 隠す（設定に覚える）。
ふだんの画面を使いやすいままにするため、解析用の機能はここにまとめる。AortaSizingWidget の一部（ResearchUIMixin）。"""
from .common import *


class ResearchUIMixin:
    RESEARCH_KEY = "HUCViewS/researchMode"

    def _buildResearch(self):
        L = self.logic
        self.resStepBtn = self._btn("6 研究", "step", True); self.stepGrp.addButton(self.resStepBtn, 5); self.stepBtns.append(self.resStepBtn)
        sb = getattr(self, "_stepBar", None)
        if sb is not None: sb.addWidget(self.resStepBtn)
        self.resStepBtn.connect("clicked()", lambda: self.showStep(5))
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10)
        sc = qt.QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(qt.QFrame.NoFrame); sc.setWidget(pg); sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{background:transparent} QScrollArea > QWidget > QWidget{background:transparent}"); self.stack.addWidget(sc)
        card, c = self._card(pl, "プラーク・壁在血栓（shaggy）", "研究用")
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("範囲", "muted"))
        self.plqRangeGrp, self.plqRangeBtns = self._seg(["左鎖骨下〜腹腔", "基部〜分岐", "計画の範囲"], r); self.plqRangeBtns[0].checked = True
        self.plqRangeBtns[0].setToolTip("Hosaka の shagginess と同じ範囲（腹腔動脈の印が無ければ 最下位腎動脈まで）")
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("拾う厚み", "muted"))
        self.plqThrGrp, self.plqThrBtns = self._seg(["3 mm", "4 mm", "5 mm"], r); self.plqThrBtns[0].checked = True
        self.plqBtn = self._btn("プラークを拾う（3D に壁の厚みの色）", "primary", "断面ごと（1 mm）に 内腔と外周の輪郭から壁の厚み（72 方向）と壁の中の CT 値を出し、"
                                "拾う厚み以上のつながった所を 1 個ずつ番号をつける。3D: 青 = 薄い 〜 赤 = 厚い（0〜8 mm）"); c.addWidget(self.plqBtn)
        self.plqLab = qt.QLabel("—"); self.plqLab.setTextFormat(qt.Qt.RichText); self.plqLab.setWordWrap(True); self.plqLab.setStyleSheet("font-size:12px; color:#dfe6ee")
        self.plqLab.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred); self.plqLab.setMinimumWidth(10); c.addWidget(self.plqLab)
        self.plqTable = qt.QTableWidget(0, 6); self.plqTable.setHorizontalHeaderLabels(["番号", "位置", "長さ", "最大厚", "体積", "特徴"])
        self._tbl(self.plqTable, 170); c.addWidget(self.plqTable)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.plqShow = self._btn("3D の色", None, "壁の厚みの色とプラークの番号を 3D に出す / 隠す", True); self.plqShow.checked = True; r.addWidget(self.plqShow)
        self.plqCsvBtn = self._btn("CSV に保存", None, "プラーク 1 個 1 行・断面ごとの表を 研究_プラーク\\<シリーズ>_<日時> に。要約 1 行を プラーク_一覧.csv に追記（版・設定・画素間隔も）"); r.addWidget(self.plqCsvBtn, 1)
        self.plqMaskBtn = self._btn("マスクを保存", None, "ラジオミクス用: 伸ばした画像（範囲）とプラークの番号のラベルを NRRD で（同じフォルダ）"); r.addWidget(self.plqMaskBtn, 1)
        self.plqNote = self._lab("", "muted"); self.plqNote.setWordWrap(True); c.addWidget(self.plqNote)
        card, c = self._card(pl, "解析用の CSV")
        for b in (getattr(self, "helixCsvBtn", None), getattr(self, "sineCsvBtn", None)):
            if b is not None: c.addWidget(b)
        c.addWidget(self._lab("この「6 研究」は Ctrl+Shift+R で出す / 隠す。解析用の数値で、診療の判断には使いません。", "muted"))
        pl.addStretch(1)
        self.plqBtn.connect("clicked()", self.onPlaque); self.plqShow.connect("toggled(bool)", lambda on: self.logic.drawPlaque(on))
        self.plqCsvBtn.connect("clicked()", self.onPlaqueCsv); self.plqMaskBtn.connect("clicked()", self.onPlaqueMask)
        self.plqTable.connect("cellClicked(int,int)", self._onPlqRow)
        mw = slicer.util.mainWindow()                                         # 隠しタブの出し入れ（Ctrl+Shift+R）。読み直しても 1 つだけ
        try:
            for old in mw.findChildren(qt.QShortcut):
                if old.objectName == "hucvsResearchShortcut": old.setEnabled(False); old.setParent(None)
        except Exception: pass
        self._resShortcut = qt.QShortcut(qt.QKeySequence("Ctrl+Shift+R"), mw); self._resShortcut.setObjectName("hucvsResearchShortcut")
        self._resShortcut.setContext(qt.Qt.ApplicationShortcut); self._resShortcut.connect("activated()", self._toggleResearch)
        on = str(qt.QSettings().value(self.RESEARCH_KEY) or "").lower() in ("true", "1")
        self._setResearch(on, save=False)

    def _setResearch(self, on, save=True):
        self._research = bool(on); self.resStepBtn.setVisible(self._research)
        if save:
            qt.QSettings().setValue(self.RESEARCH_KEY, "true" if self._research else "false")
        if not self._research:
            if self.stack.currentIndex == 5: self.showStep(0)
            try: self.logic.drawPlaque(False)
            except Exception: pass

    def _toggleResearch(self):
        try:
            if slicer.util.selectedModule() != "AortaSizing": return
        except Exception: return
        self._setResearch(not getattr(self, "_research", False))
        self._say("「6 研究」を出しました（Ctrl+Shift+R で隠す）。" if self._research else "「6 研究」を隠しました（Ctrl+Shift+R で出す）。")
        if self._research: self.showStep(5)

    # ---------------------------------------------------------------- プラーク
    def onPlaque(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        which = ("lsca-celiac", "aorta", "plan")[[b.checked for b in self.plqRangeBtns].index(True)]
        thr = (3.0, 4.0, 5.0)[[b.checked for b in self.plqThrBtns].index(True)]
        q = self._busy(lambda: L.plaqueAnalyze(which, thr, self._say))
        if not q: self._say("プラークを拾えませんでした（範囲に断面がない）。"); return
        if self.plqShow.checked: L.drawPlaque(True)
        self._plqRefresh()

    def _plqRefresh(self):
        L = self.logic
        if not L.plaqueValid(): self.plqLab.setText("—"); self.plqTable.setRowCount(0); return
        q = L.plaque; s = q["summ"]; g = "color:#9aa7b4; font-size:11px"
        self.plqLab.setText(
            f"<b>{s['range']}</b>（{L.rel(s['s0']):.0f}〜{L.rel(s['s1']):.0f} mm・{s['nsec']} 断面）<br>"
            f"プラーク <b>{s['n']}</b> 個・体積 {s['vol']:.0f} mm³・最大の厚み <b>{s['tMax']:.1f} mm</b>・5 mm 以上 {s['len5']:.0f} mm<br>"
            f"Hosaka（内腔のギザギザ）<b>{s['hosaka']:.2f}</b>・全周の 2/3 超 {'あり' if s['circ23'] else 'なし'}・くぼみ候補 {s['ulcer']} 点<br>"
            f"<span style='{g}'>shaggy の 3 項目（厚み 5 mm 超・全周 2/3 超・くぼみ候補）: {s['shaggyItems']} / 3</span>")
        sp = s["spacing"]; warn = sp[2] > 1.25 if np.isfinite(sp[2]) else False
        self.plqNote.setText((f"<span style='color:#ffcc33'>元の CT のスライス間隔 {sp[2]:.1f} mm: 厚い。厚み・ギザギザ・きめは粗く・ならされます（研究では 1.25 mm 以下を推奨）。</span>" if warn
                              else f"元の CT の画素間隔 {sp[0]:.2f}×{sp[1]:.2f}×{sp[2]:.2f} mm。") + "　くぼみ（潰瘍様）は候補だけ。目で確かめてください。"
                             + self._plqDissectNote(s))
        self.plqNote.setTextFormat(qt.Qt.RichText)
        ps = q["plaques"]; self.plqTable.setRowCount(len(ps))
        for i, p in enumerate(ps):
            feat = "・".join(x for x in (p["zone"], p["side"], f"低CT {p['low'] * 100:.0f}%" if np.isfinite(p["low"]) else "", f"石灰 {p['ca'] * 100:.0f}%" if np.isfinite(p["ca"]) else "",
                                        "くぼみ" if p["ulcer"] else "", p["branch"]) if x)
            for j, t in enumerate((f"P{p['id']}", f"{L.rel(p['s0']):.0f}〜{L.rel(p['s1']):.0f}", f"{p['length']:.0f}", f"{p['tMax']:.1f}", f"{p['vol']:.0f}", feat)):
                it = qt.QTableWidgetItem(t); it.setToolTip(t); self.plqTable.setItem(i, j, it)

    def _plqDissectNote(self, s):
        """解離の区間は、偽腔（造影されていても）が「壁」として数えられる → 注意を出す"""
        L = self.logic
        try:
            h = L.helixMetrics() if L.tlValid() else None
        except Exception: h = None
        if not h or not h.get("dissected"): return ""
        a, b = max(h["s0"], s["s0"]), min(h["s1"], s["s1"])
        if b - a < 5: return ""
        return (f"<br><span style='color:#ff6b6b'>解離の区間（{L.rel(a):.0f}〜{L.rel(b):.0f} mm）は、偽腔が壁の厚みとして数えられています。"
                "プラークの解析には解離のない症例・区間を使ってください。</span>")

    def _onPlqRow(self, r, c):
        L = self.logic
        if L.plaqueValid() and 0 <= r < len(L.plaque["plaques"]): L.setPosition(L.plaque["plaques"][r]["sMax"])

    def onPlaqueCsv(self):
        L = self.logic
        if not L.plaqueValid(): self._say("先に「プラークを拾う」を押してください。"); return
        r = self._busy(L.savePlaqueCSV)
        if r: self._done(r[0], "プラークの表（" + os.path.basename(r[1]) + " に 1 行追加）")

    def onPlaqueMask(self):
        L = self.logic
        if not L.plaqueValid(): self._say("先に「プラークを拾う」を押してください。"); return
        if not getattr(L, "_plqLastDir", None): self._busy(L.savePlaqueCSV)
        out = self._busy(L.savePlaqueMasks)
        if out: self._done(os.path.dirname(out[0]), "ラジオミクス用のマスク（NRRD）")
