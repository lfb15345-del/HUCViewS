# -*- coding: utf-8 -*-
"""大動脈サイジング: 画面の部品・共通（カード・ボタン・ページ切り替え・お知らせ）
AortaSizingWidget の一部（WidgetBaseMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class WidgetBaseMixin:
    # ---------------------------------------------------------------- 部品
    def _layWidgets(self, lay):
        out = []
        for i in range(lay.count()):
            it = lay.itemAt(i)
            if it.widget() is not None: out.append(it.widget())
            elif it.layout() is not None: out += self._layWidgets(it.layout())
        return out

    def _hideRow(self, wdg):
        """wdg を含む行（カード直下の横並び。ラベル・入れ子のボタンごと）を隠す"""
        par = wdg.parentWidget(); lay = par.layout() if par is not None else None
        if lay is None: return
        for i in range(lay.count()):
            sub = lay.itemAt(i).layout()
            if sub is None: continue
            ws = self._layWidgets(sub)
            if any(x == wdg for x in ws):
                for x in ws: x.setVisible(False)
                return

    def _card(self, parent_layout, title=None, sub=None):
        f = qt.QFrame(); f.setProperty("role", "card"); lay = qt.QVBoxLayout(f); lay.setContentsMargins(12, 10, 12, 12); lay.setSpacing(8)
        if title:
            h = qt.QHBoxLayout(); t = qt.QLabel(title); t.setProperty("role", "h"); h.addWidget(t); h.addStretch(1)
            if sub: s = qt.QLabel(sub); s.setProperty("role", "muted"); h.addWidget(s)
            lay.addLayout(h)
        parent_layout.addWidget(f); return f, lay

    def _btn(self, text, kind=None, tip=None, checkable=False):
        b = qt.QPushButton(text)
        if kind: b.setProperty("kind", kind)
        if tip: b.setToolTip(tip)
        b.setCheckable(checkable); b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor)); return b

    def _lab(self, text, role=None):
        l = qt.QLabel(text)
        if role: l.setProperty("role", role)
        if role == "muted" and len(text) > 24: l.setWordWrap(True)           # 長い説明は折り返す（パネルが狭くてもはみ出さない）
        return l

    def _seg(self, items, lay, exclusive=True):
        grp = qt.QButtonGroup(lay.parentWidget() if hasattr(lay, "parentWidget") else None); grp.setExclusive(exclusive)
        row = qt.QHBoxLayout(); row.setSpacing(4); out = []
        for txt in items:
            b = self._btn(txt, "seg", checkable=True); grp.addButton(b); row.addWidget(b); out.append(b)
        lay.addLayout(row); return grp, out

    def _tbl(self, t, h):
        t.setSelectionBehavior(qt.QAbstractItemView.SelectRows); t.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False); t.setMinimumHeight(h); t.setAlternatingRowColors(True); t.setShowGrid(False)
        t.horizontalHeader().setStretchLastSection(True); t.verticalHeader().setDefaultSectionSize(26)

    def cleanup(self):
        try:
            inter = slicer.app.applicationLogic().GetInteractionNode(); inter.RemoveObserver(self._interTag)
        except Exception: pass

    def enter(self):
        try:                                                                # Slicer のヘルプ欄はたたんで、画面を広く使う
            hb = slicer.util.mainWindow().findChild(ctk.ctkCollapsibleButton, "HelpCollapsibleButton")
            if hb is not None: hb.collapsed = True
        except Exception: pass
        try: self.logic.resume()
        except Exception: _err("enter")
        qt.QTimer.singleShot(300, self._autoStart)
        if self.stack.currentIndex in (2, 3): qt.QTimer.singleShot(500, lambda i=self.stack.currentIndex: self.showStep(i))   # TEVAR の画面に戻ってきた時も半透明の設定に

    def _autoStart(self):
        """開いたら、中心線がまだ無ければ自動で作って計測の画面にする（ボタンを探さなくてよい）"""
        L = self.logic
        try:
            if slicer.util.selectedModule() != "AortaSizing" or L.P is not None: return
        except Exception: return
        try: vol, seg = L._inputs()
        except Exception as e: self._say(str(e)); return
        if getattr(self, "_autoTried", None) == vol.GetID(): return
        self._autoTried = vol.GetID()
        self._say("中心線を自動で作っています（1 分ほど。開いた時に自動）…")
        self.onAuto()

    def exit(self):
        self.logic._tvMode = False
        try:
            if getattr(self, "_tvRen", None) is not None:
                ren = slicer.app.layoutManager().threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer()
                ren.SetUseDepthPeeling(self._tvRen[0]); ren.SetUseSSAO(self._tvRen[1]); self._tvRen = None
            vm = getattr(self.logic, "vesselModel", None)
            if vm is not None and slicer.mrmlScene.IsNodePresent(vm): vm.GetDisplayNode().SetOpacity(1.0)
        except Exception: pass
        try: self.logic.suspend()
        except Exception: _err("exit")

    def showStep(self, i):
        i = max(0, min(5 if getattr(self, "_research", False) else 4, i)); self.stack.setCurrentIndex(i); self.stepBtns[i].checked = True
        tv = i in (2, 3)                                                      # 計画・術後（TEVAR）
        if i != 0 and getattr(self, "fixButton", None) is not None and self.fixButton.checked: self.fixButton.checked = False
        if i == 1: self.refreshLists()
        self.logic._tvMode = tv
        for x in (getattr(self, "pinBtn", None), getattr(self, "baseBtn", None), getattr(self, "editContBtn", None), getattr(self, "wlBtn", None), getattr(self, "_hintTop", None)):
            if x is not None: x.setVisible(not tv)
        vw = getattr(self, "_valW", None)                                     # 計画・術後では径の表もしまう（断面の右上に出ている）
        if vw is None and hasattr(self, "vals"):
            w0 = self.vals[("outer", "dmax")]; lay = w0.parentWidget().layout(); vw = []
            for j in range(lay.count()):
                sub = lay.itemAt(j).layout()
                if sub is not None and any(x == w0 for x in self._layWidgets(sub)): vw = self._layWidgets(sub); break
            self._valW = vw
        for x in vw or []: x.setVisible(not tv)
        for btn, page in ((getattr(self, "tvPick", None), 2), (getattr(self, "tlFixBtn", None), 2), (getattr(self, "planEditBtn", None), 2), (getattr(self, "alignBtn", None), 3), (getattr(self, "tvRange", None), 2), (getattr(self, "entryBtn", None), 2)):
            if btn is not None and btn.checked and i != page: btn.checked = False
        if tv: self._tvEnter()
        try:                                                                  # TEVAR の時は血管を半透明にして、中のグラフトを見せる
            vm = getattr(self.logic, "vesselModel", None)
            if vm is not None and slicer.mrmlScene.IsNodePresent(vm): vm.GetDisplayNode().SetOpacity(0.3 if tv else 1.0)
            ren = slicer.app.layoutManager().threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer()
            if tv and getattr(self, "_tvRen", None) is None:               # 半透明（血管・グラフトの布）をきちんと描く（重ねた描画層では深さの剥離が効かない）
                self._tvRen = (ren.GetUseDepthPeeling(), ren.GetUseSSAO()); ren.SetUseDepthPeeling(False); ren.SetUseSSAO(False)
            elif not tv and getattr(self, "_tvRen", None) is not None:
                ren.SetUseDepthPeeling(self._tvRen[0]); ren.SetUseSSAO(self._tvRen[1]); self._tvRen = None
        except Exception: pass

    def _say(self, m):
        self.status.setText(m); print("[AortaSizing]", m); slicer.app.processEvents()

    def _busy(self, f, *a):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: return f(*a)
        except Exception as e:
            import traceback; traceback.print_exc(); self._say(f"エラー: {e}")
        finally: qt.QApplication.restoreOverrideCursor()

    def _syncPathButtons(self):
        cur = self.logic.path or ""; has = self.logic.curves
        for b, key in ((self.rightBtn, "大動脈→右腸骨"), (self.leftBtn, "大動脈→左腸骨"), (self.aortaBtn, "大動脈")):
            b.visible = key in has; b.checked = (cur == key)
        col = {"大動脈→右腸骨": ("#f39a33", "右"), "大動脈→左腸骨": ("#4cc8f0", "左"), "大動脈": ("#e6d54c", "大動脈")}.get(cur)
        self.pathChip.visible = col is not None
        if col: self.pathChip.setText(col[1]); self.pathChip.setStyleSheet(f"padding:2px 8px; border-radius:9px; font-size:11px; font-weight:bold; color:#15171c; background:{col[0]}")

    # ---------------------------------------------------------------- 3 出力
    def _done(self, d, what):
        self._lastDir = d; self.openBtn.enabled = True
        self.outLabel.setText(f"{what}: {d}"); self._say(f"{what}を保存しました。")
