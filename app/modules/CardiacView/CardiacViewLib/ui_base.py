# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 画面の部品・共通（画像の上のツールバー・凡例・色合い・陰影・カード・ボタン・タブ・お知らせ・入る／出る）
CardiacViewWidget の一部（WidgetBaseMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *
from . import common          # 色合いで置き換わる名前は common.名前 で今の値を読む


class WidgetBaseMixin:
    # ---------------------------------------------------------------- 画像の上のツールバー（商用ビューアと同じく、よく使う操作は画像のすぐ上）
    def _buildToolbar(self):
        mw = slicer.util.mainWindow()
        for old in mw.findChildren(qt.QToolBar):
            if old.objectName == "HUCViewSToolBar":
                try: mw.removeToolBar(old); old.setParent(None); old.deleteLater()
                except Exception: pass
        tb = qt.QToolBar("HUCViewS"); tb.setObjectName("HUCViewSToolBar"); tb.setMovable(False); tb.setFloatable(False)
        tb.setIconSize(qt.QSize(22, 22)); tb.setStyleSheet(TB_STYLE); tb.setContextMenuPolicy(qt.Qt.PreventContextMenu)
        mw.addToolBarBreak(qt.Qt.TopToolBarArea); mw.addToolBar(qt.Qt.TopToolBarArea, tb); self.tb = tb; self.tbButtons = {}   # 1 段まるごと使う
        ic = _toolIcons()
        brand = qt.QLabel(getattr(slicer, "heartviewAppTitle", "HUCViewS")); brand.setObjectName("tbBrand"); tb.addWidget(brand)

        def add(key, text, tip, cb=None, checkable=False, group=None):
            b = qt.QToolButton(); b.setText(text); b.setToolTip(tip); b.setCheckable(checkable); b.setAutoRaise(True)
            if key in ic: b.setIcon(qt.QIcon(ic[key]))
            b.setToolButtonStyle(qt.Qt.ToolButtonTextUnderIcon); b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
            if group is not None: group.addButton(b)
            if cb is not None: b.connect("clicked()", cb)
            tb.addWidget(b); self.tbButtons[key] = b; return b

        g = qt.QButtonGroup(tb); g.setExclusive(True); self._tbModeGroup = g
        for key, (k, text, tip) in zip(("zoom", "window", "pan", "cut"),
                                       (("zoom", "拡大", "右ドラッグで拡大・縮小"), ("window", "ウィンドウ", "右ドラッグで濃さ（横=幅、縦=中心）。VR と断面"),
                                        ("pan", "移動", "右ドラッグで画面を動かす"), ("cut", "切る位置", "右ドラッグで切る面を前後に動かす"))):
            add("m_" + k, text, tip, lambda k=k: self._setMode(k), True, g).setIcon(qt.QIcon(ic.get(key, "")))
        tb.addSeparator()
        msgs = {"line": "始点と終点をクリック", "curve": "点をクリックで追加、終わったら右クリック",
                "area": "輪郭を囲むようにクリック、終わったら右クリック", "angle": "3 点クリック（2 点目が角の頂点）"}
        for k, text, tip in (("line", "直線", "2 点クリックで長さ"), ("curve", "カーブ", "曲線に沿った長さ（血管・弁輪など）"),
                             ("area", "面積", "囲んだ面積と周長"), ("angle", "角度", "3 点で角度")):
            add(k, text, tip, lambda k=k: (self.logic.startMeasure(k), self._status(msgs[k] + "（3D の面・VR の上、または断面）")))
        add("clear", "消去", "計測をすべて消す（1 つだけ消す時は、マウスを乗せて Delete）", lambda: self.logic.clearRulers())
        tb.addSeparator()
        lg = qt.QButtonGroup(tb); lg.setExclusive(True); self._tbLayoutGroup = lg
        for key, k, text, tip in (("one", "3d", "1画面", "3D だけを大きく"), ("two", "cut", "2画面", "左に 3D、右に今切っている面の断面"),
                                  ("four", "four", "4画面", "3D ＋ 軸位・矢状断・冠状断")):
            add("l_" + k, text, tip, lambda k=k: self._setLayoutTb(k), True, lg).setIcon(qt.QIcon(ic.get(key, "")))
        tb.addSeparator()
        add("fit", "全体表示", "見えているもの全体が画面に収まるように", lambda: (self.logic._fitParallel(recenter=True), self.logic._view().scheduleRender()))
        b = add("wl", "W/L", "断面のウィンドウをよく使う値に")
        m = qt.QMenu(b); m.setStyleSheet(TB_STYLE)
        for name, w, l in WL_PRESETS:
            a = m.addAction(f"{name}　　W {w} / L {l}")
            a.connect("triggered()", lambda w=w, l=l, name=name: (self.logic.applyWL(w, l), self._status(f"断面のウィンドウ: {name}（W {w} / L {l}）")))
        m.addSeparator(); a = m.addAction("最初の値に戻す"); a.connect("triggered()", self._wlReset)
        b.setMenu(m); b.setPopupMode(qt.QToolButton.InstantPopup)
        add("reset", "戻す", "VR と断面のウィンドウを最初の値に戻す", self._wlReset)
        sp = qt.QWidget(); sp.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred); tb.addWidget(sp)
        add("camera", "画像保存", "今の画面を PNG で保存", self._savePNG)
        add("help", "操作", "マウス・キーの操作の一覧", lambda: self._showHelp(self.tbButtons["help"]))
        tb.hide()

    def _setMode(self, k):
        self.logic.setRightMode(k)
        b = self.rmodeButtons.get(k)
        if b is not None: b.checked = True

    def _setLayoutTb(self, k):
        b = self.layoutButtons.get(k)
        if b is not None: b.checked = True
        self.logic.setLayout(k)

    def _wlReset(self):
        self.logic.resetWindow(); self._status("ウィンドウを最初の値に戻しました")

    def _savePNG(self):
        try:
            import HeartView
            p = HeartView.HeartViewLogic().savePNG(); self._status(f"画像を保存しました: {p}")
        except Exception as e:
            self._status(f"画像の保存に失敗しました: {e}")

    def _showHelp(self, anchor):
        self._popup(anchor, HELP_HTML)

    def _makeLegend(self):
        _sq = lambda cc: f"<span style='color:rgb({int(cc[0]*255)},{int(cc[1]*255)},{int(cc[2]*255)}); font-size:15px'>■</span>"
        _rows = lambda L: "".join(f"<tr><td>{_sq(cc)}</td><td style='padding-left:6px'>{n}</td></tr>" for n, cc in L)
        self._legendHtml = ("<div style='font-size:12px'><b style='color:#4cc8f0'>血液・血管の色</b><table>" + _rows(common.LEGEND) + "</table><br>"
                            "<b style='color:#4cc8f0'>断面（壁）の色</b><table>" + _rows(common.LEGEND_WALL) + "</table></div>")

    def onShade(self, i):
        lv = ("なし", "ふつう", "強め")[i]
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: msg = self.logic.setShading(lv)
        except Exception: import traceback; traceback.print_exc(); msg = ""
        finally: qt.QApplication.restoreOverrideCursor()
        if msg:
            self.shadeCombo.blockSignals(True); self.shadeCombo.currentIndex = ("なし", "ふつう", "強め").index(self.logic.shadeLevel); self.shadeCombo.blockSignals(False)
            try: self.statusLabel.setText(msg); paintStatus(self.statusLabel, msg)
            except Exception: print(msg)

    def onPalette(self, i):
        name = ("リアル", "赤と青", "落ち着いた")[max(0, min(2, int(i)))]
        try: qt.QSettings().setValue(PALETTE_KEY, name)
        except Exception: pass
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: self.logic.applyPalette(name)
        except Exception: import traceback; traceback.print_exc()
        finally: qt.QApplication.restoreOverrideCursor()
        self._makeLegend()

    def _popup(self, anchor, html):
        """ボタンの下に出す説明の小さな窓（「操作」「色の見方」）。外をクリックするか Esc で閉じる。
        版 25: 前は QLabel そのものを Popup にしていた。Popup は Slicer へのマウスとキーを全部受け取るが、QLabel はそれを捨てる
        （外をクリックした時に閉じる処理が QLabel には無い）ので、外をクリックしても Esc でも閉じず、Slicer 全体が動かなくなった。
        → 枠（QFrame）を Popup にして、中に QLabel を置く（外のクリック・Esc は枠が受けて閉じる）。画面の下にはみ出す時はボタンの上に出す"""
        old = getattr(self, "_helpPop", None)
        if old is not None:
            try: old.close()
            except Exception: pass
        f = qt.QFrame(); f.setWindowFlags(qt.Qt.Popup); f.setObjectName("cvPopup")
        f.setStyleSheet("QFrame#cvPopup{background:#1e2128; border:1px solid #343a46; border-radius:8px;} QLabel{color:#e6e8ec; background:transparent;}")
        lay = qt.QVBoxLayout(f); lay.setContentsMargins(14, 12, 14, 12)
        lb = qt.QLabel(html); lb.setTextFormat(qt.Qt.RichText); lay.addWidget(lb)
        f.adjustSize()
        g = anchor.mapToGlobal(qt.QPoint(anchor.width, anchor.height + 4)); x, y = g.x() - f.width, g.y()
        try:
            ag = qt.QApplication.desktop().availableGeometry(anchor)      # ボタンのある画面の使える範囲（タスクバーを除く）
            if y + f.height > ag.bottom() + 1: y = max(ag.top(), anchor.mapToGlobal(qt.QPoint(0, 0)).y() - f.height - 4)
            x = min(max(x, ag.left()), max(ag.left(), ag.right() + 1 - f.width))
        except Exception: x = max(0, x)
        f.move(x, y); f.show(); self._helpPop = f

    def _tbSync(self):
        """ツールバーの押された状態を、今のモード・画面割りに合わせる"""
        L = self.logic; tbb = getattr(self, "tbButtons", {})
        b = tbb.get("m_" + getattr(L, "rmode", "zoom"))
        if b is not None and not b.checked: b.checked = True
        b = tbb.get("l_" + getattr(L, "layoutKind", "3d"))
        if b is not None and not b.checked: b.checked = True

    def cleanup(self):
        """モジュールを読み直す時: タイマーを止め、ツールバーと画面上の表示を片づける"""
        for t in ("_uiTimer", "_t4D"):
            try: getattr(self, t).stop()
            except Exception: pass
        try: _hud().show(False)
        except Exception: pass
        try:
            mw = slicer.util.mainWindow(); mw.removeToolBar(self.tb); self.tb.setParent(None); self.tb.deleteLater()
        except Exception: pass

    def _uiTick(self):
        if getattr(self, "tb", None) is None: return
        try:
            if slicer.util.selectedModule() != "CardiacView": return
            self._tbSync(); self.logic._hudUpdate()
            L = self.logic; pn = L.layerModels.get("パッチ")                       # パッチの範囲を出している時は「推定したイメージ」と添える
            have = pn is not None and slicer.mrmlScene.IsNodePresent(pn) and pn.GetPolyData() is not None and pn.GetPolyData().GetNumberOfPoints() > 0
            on = bool(have and ((pn.GetDisplayNode() is not None and pn.GetDisplayNode().GetVisibility()) or getattr(L, "vrOn", False)))
            if getattr(self, "_patchNoteOn", None) != on:
                L._setUL("2_patch", "<span style='color:#f2f2ec'>白 = パッチの範囲</span>　<span style='color:#9aa7b4'>CT から推定した手術のイメージ（教育用・診断には使いません）</span>" if on else "")
                self._patchNoteOn = on
            sb = getattr(self, "_seqBar", None)
            if sb is None:
                sb = self._seqBar = next((t for t in slicer.util.mainWindow().findChildren(qt.QToolBar) if t.objectName == "SequenceBrowserToolBar"), False)
            if sb and sb.visible: sb.hide()
        except Exception as e:
            if "destroyed" in str(e): self._uiTimer.stop()                    # 古い画面（読み直し前）のタイマー
            else: print("ui tick:", e)

    def enter(self):
        try: self.logic._noDepthPeeling()                                    # 大動脈サイジングなどから戻った時も（剥離は AMD で固まる）
        except Exception: pass
        try: self._fillPreCombo()
        except Exception: pass
        try: self._sync4D()
        except Exception as e: print("4D sync:", e)
        try:
            if getattr(self, "tb", None) is not None: self.tb.show()
            _hud().show(True); self.logic._applyChrome()
            self._uiTimer.start(); self._uiTick()
        except Exception as e: print("ui enter:", e)

    def exit(self):
        try:                                                                  # ほかの画面（大動脈サイジングなど）へ行く時は 4D を終える（動く VR が残らない）
            if self.play4DButton.checked: self.play4DButton.checked = False
            if getattr(self.logic, "on4D", False): self.logic.show4D(False)
        except Exception: pass
        try:
            if getattr(self, "tb", None) is not None: self.tb.hide()
            self._uiTimer.stop(); _hud().show(False)
            if not getattr(slicer, "heartviewAppMode", False):                # Slicer の通常画面では 3D のバーを戻す
                slicer.app.layoutManager().threeDWidget(0).threeDController().setVisible(True)
        except Exception: pass

    # ---------------------------------------------------------------- UI 部品（AortaSizing と同じ見た目）
    def _card(self, parent_layout, title=None, sub=None):
        f = qt.QFrame(); f.setProperty("role", "card"); lay = qt.QVBoxLayout(f); lay.setContentsMargins(10, 8, 10, 10); lay.setSpacing(6)
        h = None
        if title:
            h = qt.QHBoxLayout(); h.setSpacing(4); t = qt.QLabel(title); t.setProperty("role", "h"); h.addWidget(t); h.addStretch(1)
            if sub: s = qt.QLabel(sub); s.setProperty("role", "muted"); h.addWidget(s)
            lay.addLayout(h)
        parent_layout.addWidget(f); return f, lay, h

    def _btn(self, text, kind=None, tip=None, checkable=False):
        b = qt.QPushButton(text)
        if kind: b.setProperty("kind", kind)
        if tip: b.setToolTip(tip)
        b.setCheckable(checkable); b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
        b.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Fixed); return b

    def _lab(self, text, role=None):
        l = qt.QLabel(text)
        if role: l.setProperty("role", role)
        return l

    def _showTab(self, i):
        for j, p in enumerate(self.pages): p.setVisible(j == i)              # 見えているページの高さだけ取る（空白を作らない）
        self.tabBtns[i].checked = True
        try: qt.QSettings().setValue("CardiacView/tab", int(i))
        except Exception: pass

    # ---------------------------------------------------------------- helpers
    def _addLayerRow(self, grid, r, name, lo, hi, col, sm, vis):
        visCb = qt.QCheckBox(); visCb.checked = vis; grid.addWidget(visCb, r, 0)
        nameEdit = qt.QLineEdit(name); nameEdit.setMinimumWidth(50); nameEdit.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Fixed); nameEdit.setToolTip(name); grid.addWidget(nameEdit, r, 1)
        loSpin = qt.QSpinBox(); loSpin.setRange(-1024, 3000); loSpin.value = lo; loSpin.setMaximumWidth(62); grid.addWidget(loSpin, r, 2)
        hiSpin = qt.QSpinBox(); hiSpin.setRange(-1024, 3000); hiSpin.value = hi; hiSpin.setMaximumWidth(62); grid.addWidget(hiSpin, r, 3)
        colBtn = ctk.ctkColorPickerButton(); colBtn.color = qt.QColor.fromRgbF(*col); colBtn.displayColorName = False; colBtn.setMaximumWidth(34); grid.addWidget(colBtn, r, 4)
        smCombo = qt.QComboBox(); smCombo.addItems(["なし", "弱", "強"]); smCombo.currentIndex = sm; smCombo.setMaximumWidth(64); grid.addWidget(smCombo, r, 5)
        self.layerRows.append(dict(vis=visCb, name=nameEdit, lo=loSpin, hi=hiSpin, col=colBtn, sm=smCombo))

    def _layerSpecs(self):
        specs = []
        for row in self.layerRows:
            c = row["col"].color
            specs.append(dict(name=row["name"].text, lo=row["lo"].value, hi=row["hi"].value,
                              color=(c.redF(), c.greenF(), c.blueF()), smooth=row["sm"].currentIndex, visible=row["vis"].checked))
        return specs

    def _status(self, msg):
        self.statusLabel.text = msg; paintStatus(self.statusLabel, msg); slicer.app.processEvents()
