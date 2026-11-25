# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 画面を組み立てる（setup）
CardiacViewWidget の一部（WidgetBuildMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *
from . import common          # 色合いで置き換わる名前は common.名前 で今の値を読む


class WidgetBuildMixin:
    def setup(self):
        """画面を組み立てる。中身は下の _build…（上から順に作る。順番を変えない: 部品を作る順・つなぐ順が、そのまま画面の並び・動きの順になる）"""
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = CardiacViewLogic()
        qt.QTimer.singleShot(0, lambda: self.logic._noDepthPeeling())          # 起動直後から深さの剥離を OFF に保つ（AMD で固まる）
        self.layerRows = []
        app = getattr(slicer, "heartviewAppMode", False)
        v, root = self._buildRoot()
        self._buildHeader(v, app)
        self._buildCaseCard(v, app)
        self._buildSceneCard(v)
        self._build4DCard(v)
        self._buildRightDragCard(v)
        pages = self._buildTabs(v, root)
        self._buildViewPage(pages)
        self._buildCutPage(pages)
        self._buildSlicePage(pages)
        self._buildMeasurePage(pages)
        self._buildSettingsPage(pages)
        self._arrangeParts(v, pages)
        self._connectSignals()

    def _buildRoot(self):
        """画面の土台（スクロールする入れ物と、縦の並び）"""
        root = qt.QWidget(); root.setObjectName("cvRoot"); root.setStyleSheet(CV_STYLE + _iconCSS()); root.setAttribute(qt.Qt.WA_StyledBackground, True)
        _sc = qt.QScrollArea(); _sc.setWidgetResizable(True); _sc.setFrameShape(qt.QFrame.NoFrame); _sc.setWidget(root)
        _sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)                      # 横スクロールなし（はみ出さない配置にする）
        _sc.setStyleSheet(SC_STYLE)
        self.layout.addWidget(_sc); self.layout.setContentsMargins(0, 0, 0, 0)
        v = qt.QVBoxLayout(root); v.setContentsMargins(10, 8, 10, 10); v.setSpacing(8); self.root = root
        return v, root

    def _buildHeader(self, v, app):
        """ヘッダー"""
        B, Lb = self._btn, self._lab
        h = qt.QHBoxLayout(); h.setSpacing(4); v.addLayout(h)
        if app:
            back = B("‹ 入口", "ghost", "症例の読み込み（入口）へ戻る"); h.addWidget(back)
            back.connect("clicked()", lambda: slicer.util.selectModule("HeartView"))
        h.addWidget(Lb("CardiacView", "title")); h.addStretch(1)
        self.helpButton = B("？ 操作", "ghost", HELP_TEXT); h.addWidget(self.helpButton)
        self.helpButton.connect("clicked()", lambda: self._showHelp(self.helpButton)); self.helpButton.hide()      # 操作の一覧は上のバーへ
        if app:
            png = B("画像保存", "ghost", "今の画面を PNG で保存"); h.addWidget(png); png.hide()
            def _png():
                import HeartView
                p = HeartView.HeartViewLogic().savePNG(); self._status(f"画像を保存しました: {p}")
            png.connect("clicked()", _png)

    def _buildCaseCard(self, v, app):
        """症例（CT・作成・状態）"""
        B, Lb = self._btn, self._lab
        card, c, _ = self._card(v)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r)
        r.addWidget(Lb("CT", "muted"))
        self.volumeSelector = slicer.qMRMLNodeComboBox()
        self.volumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.volumeSelector.addEnabled = False; self.volumeSelector.removeEnabled = False
        self.volumeSelector.noneEnabled = False; self.volumeSelector.showHidden = False
        self.volumeSelector.showChildNodeTypes = False                        # ラベル・VR 用の画像（別の種類の画像）は CT の欄に出さない
        self.volumeSelector.setMRMLScene(slicer.mrmlScene)
        self.volumeSelector.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Fixed); self.volumeSelector.setMinimumWidth(80)
        r.addWidget(self.volumeSelector, 1)
        self.loadButton = B("開く", None, "ファイルを開く（.nrrd / .nii / .mrb など）"); r.addWidget(self.loadButton)
        self.dicomButton = B("DICOM", None, "1シリーズ分の DICOM フォルダを選ぶ（院内 PC 内で読み込むだけ。外部送信なし）"); r.addWidget(self.dicomButton)
        self.quickButton = B("3D を自動で作る", "primary", "AI で心臓・血管を分けて 3D を作ります。初回 約5〜8分・2回目から約1分"); c.addWidget(self.quickButton)
        self.statusLabel = Lb("CT を選んで「3D を自動で作る」を押してください。", "muted"); self.statusLabel.setWordWrap(True); c.addWidget(self.statusLabel)
        if app:
            for b in (self.loadButton, self.dicomButton): b.hide()
            self.quickButton.setText("3D を作り直す（同じ CT）")

    def _buildSceneCard(self, v):
        """見たいもの（ワンクリック。最後に選んだものが次の症例の最初の表示）"""
        B = self._btn
        card, c, _ = self._card(v, "見たいもの", "次の症例もこの表示から"); self._sceneLay = c
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.sceneButtons = {}
        for key, text, tip in (("heart", "心臓", "四腔断面で心臓の中を見る"),
                               ("aorta", "大動脈", "大動脈（弓部分枝〜腸骨動脈、撮影範囲の分）を切らずに全体で。人工物・石灰化も表示"),
                               ("vessels", "全血管", "動脈・静脈・肺血管をすべて切らずに見る"),
                               ("body", "骨＋血管", "骨と血管を一緒に（位置関係・術前のオリエンテーション）")):
            b = B(text, "seg", tip, checkable=True); b.setMinimumHeight(30); r.addWidget(b, 1); self.sceneButtons[key] = b

    def _build4DCard(self, v):
        """4D（同じ撮影の位相が 2 つ以上ある時だけ出る）"""
        B, Lb = self._btn, self._lab
        self.box4D, c, hd = self._card(v, "4D", None)
        self.phaseLabel = Lb("", "accent"); hd.addWidget(self.phaseLabel)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r)
        self.play4DButton = B("▶ 再生", "play", "位相を順に表示（VR と断面が動く）。もう一度押すと止まる。切る・回す・4画面はそのまま使える", checkable=True)
        self.play4DButton.setMinimumWidth(78); r.addWidget(self.play4DButton)
        self.phaseSlider = ctk.ctkSliderWidget(); self.phaseSlider.decimals = 0; self.phaseSlider.singleStep = 1; self.phaseSlider.minimum = 0; self.phaseSlider.maximum = 1
        try: self.phaseSlider.spinBoxVisible = False
        except Exception: pass
        self.phaseSlider.setToolTip("位相を 1 つずつ見る"); r.addWidget(self.phaseSlider, 1)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.mode4DButtons = {}; mg4 = qt.QButtonGroup(self.box4D); mg4.setExclusive(True)
        for key, lab, tip in (("blood", "造影", "造影された血液を明るく。心臓の外形や、切った時の内腔の大きさの変化を見る"),
                              ("tissue", "心内構造", "造影された血液を透明にして、弁・乳頭筋・壁の動きを見る。切って使うと見やすい")):
            b = B(lab, "vr", tip, checkable=True); mg4.addButton(b); r.addWidget(b); self.mode4DButtons[key] = b
        self.mode4DButtons["blood"].checked = True; self._mode4DGroup = mg4
        r.addStretch(1)
        self.fpsSpin = qt.QDoubleSpinBox(); self.fpsSpin.setRange(0.5, 30.0); self.fpsSpin.setSingleStep(1.0); self.fpsSpin.setDecimals(1); self.fpsSpin.setSuffix(" /秒")
        self.fpsSpin.setToolTip("再生の速さ（1 秒あたりの位相数）")
        try: self.fpsSpin.setValue(float(qt.QSettings().value("CardiacView/fps4D", 8.0)))
        except Exception: self.fpsSpin.setValue(8.0)
        r.addWidget(self.fpsSpin)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.wl4DButton = B("ウィンドウを戻す", None, "4D の VR と断面のウィンドウ（濃さ・コントラスト）を最初の値に戻す"); r.addWidget(self.wl4DButton); self.wl4DButton.hide()
        r.addStretch(1)
        self.end4DButton = B("4D を終了", None, "4D をやめて、AI で作った面・色分け VR の表示に戻る"); r.addWidget(self.end4DButton)
        self.box4D.hide()

    def _buildRightDragCard(self, v):
        """右ドラッグ（マウスの機能）"""
        B = self._btn
        card, c, hd = self._card(v, "右ドラッグ", None)
        self.wlResetButton = B("ウィンドウを戻す", "ghost", "VR と断面のウィンドウ（濃さ・コントラスト）を最初の値に戻す"); hd.addWidget(self.wlResetButton)
        self.wlResetButton.connect("clicked()", lambda: self.logic.resetWindow())
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.rmodeButtons = {}; rg = qt.QButtonGroup(card); rg.setExclusive(True)
        rtips = {"zoom": "右ドラッグで拡大・縮小", "window": "右ドラッグでウィンドウ（横=幅、縦=中心）", "pan": "右ドラッグで画面を移動", "cut": "右ドラッグで切る位置を動かす"}
        for key, lab in CardiacViewLogic.RMODES:
            b = B(lab, "seg", rtips.get(key), checkable=True); rg.addButton(b); r.addWidget(b, 1); self.rmodeButtons[key] = b
        self.rmodeButtons["zoom"].checked = True; self._rmodeGroup = rg
        card.hide()                                                           # 右ドラッグの切り替えは画像の上のバーへ

    def _buildTabs(self, v, root):
        """タブ"""
        B = self._btn
        tb = qt.QHBoxLayout(); tb.setSpacing(0); v.addLayout(tb)
        self.stack = qt.QWidget(); _stl = qt.QVBoxLayout(self.stack); _stl.setContentsMargins(0, 0, 0, 0); _stl.setSpacing(0); v.addWidget(self.stack)
        self.tabBtns = []; self.pages = []; tg = qt.QButtonGroup(root); tg.setExclusive(True); self._tabGroup = tg
        pages = {}
        self._hidden = qt.QWidget(); self._hidden.hide(); pages["計測"] = qt.QVBoxLayout(self._hidden)   # 計測は画像の上のバーへ（ここは使わない部品の置き場）
        for i, name in enumerate(("表示", "切る", "断面", "設定")):
            b = B(name, "step", None, checkable=True); tg.addButton(b, i); tb.addWidget(b, 1); self.tabBtns.append(b)
            b.connect("clicked()", lambda i=i: self._showTab(i))
            p = qt.QWidget(); pl = qt.QVBoxLayout(p); pl.setContentsMargins(0, 4, 0, 0); pl.setSpacing(8)
            _stl.addWidget(p); self.pages.append(p); p.hide(); pages[name] = pl
        return pages

    def _buildViewPage(self, pages):
        """表示"""
        B, Lb = self._btn, self._lab
        P = pages["表示"]
        card, c, _ = self._card(P, "視点")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.viewButtons = {}
        vtips = {"A": "正面から", "L": "左から", "R": "右から", "S": "頭側から", "P": "背側から", "SURG": "術者の視点（胸骨正中切開）"}
        for lab, key in [("前", "A"), ("左", "L"), ("右", "R"), ("上", "S"), ("後", "P"), ("術者", "SURG")]:
            b = B(lab, "tool", vtips[key]); r.addWidget(b, 1); self.viewButtons[key] = b

        card, c, _ = self._card(P, "描画")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.heartOnlyButton = B("色分け面", None, "心臓・血管を AI の面で表示（血液を部位ごとに色分け）"); r.addWidget(self.heartOnlyButton, 1)
        self.vrTissueButton = B("VR 心内", "vr", "元の CT をそのまま立体に（ボリュームレンダリング）。弁・乳頭筋・肉柱・中隔が見える。\n左右ボタン同時ドラッグでウィンドウを調整", checkable=True)
        self.vrBloodButton = B("VR 造影", "vr", "造影された血液を立体に（ボリュームレンダリング）", checkable=True)
        r.addWidget(self.vrTissueButton, 1); r.addWidget(self.vrBloodButton, 1)

        card, c, hdL = self._card(P, "レイヤー"); self._layerLay = c
        g = qt.QGridLayout(); g.setHorizontalSpacing(10); g.setVerticalSpacing(4); c.addLayout(g)
        self.layerChecks = {}
        for k, name in enumerate(("心臓壁", "心筋", "血液・血管", "軟部組織", "骨", "人工物・石灰化", "パッチ")):
            cb = qt.QCheckBox("心筋（AI）" if name == "心筋" else name); cb.checked = True; g.addWidget(cb, k // 2, k % 2); self.layerChecks[name] = cb
            if name == "心筋": cb.setToolTip("心筋は AI（TotalSegmentator）のラベルから作っています。欠損を塗りつぶすことがあるので、外すと CT 値だけの壁が見えます")
            if name == "人工物・石灰化": cb.setToolTip("金属（人工弁のリング・ステント・クリップ・胸骨ワイヤー）= 銀、石灰化 = 黄白")
            if name == "パッチ": cb.setToolTip("術後の CT から自動で出したパッチの範囲（緑）。左室と右室の血液を 2 mm 以下の薄い仕切りだけで隔てている所（術前の CT があれば、術前の穴・術前から同じ所も区別）")
        _it = lambda n, cc: f'<span style="white-space:nowrap"><span style="color:rgb({int(cc[0]*255)},{int(cc[1]*255)},{int(cc[2]*255)})">■</span>{n}</span>'
        leg = " &nbsp;".join(_it(n, cc) for n, cc in common.LEGEND)
        leg2 = " &nbsp;".join(_it(n, cc) for n, cc in common.LEGEND_WALL)
        self.legend = Lb("血液: " + leg + "<br>断面: " + leg2, "muted"); self.legend.setWordWrap(True); c.addWidget(self.legend); self.legend.hide()
        self._makeLegend()
        lgb = B("色の見方", "ghost", "色分けの意味"); hdL.addWidget(lgb); lgb.connect("clicked()", lambda: self._popup(lgb, self._legendHtml))

        card, c, _ = self._card(P, "心筋・壁")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.vsdButton = B("心筋の断面", None, "心筋を断面で見る（VSD・中隔）"); r.addWidget(self.vsdButton, 1)
        self.fourChButton = B("四腔断面", None, "左室・右室・中隔・両心房が一度に見える面で切る"); r.addWidget(self.fourChButton, 1)
        self.lumenButton = B("内腔を見る", None, "壁だけ・中は空洞"); r.addWidget(self.lumenButton); self.lumenButton.hide()
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r); r.addWidget(Lb("パッチ", "muted"))
        self.patchLButton = B("左室側から", None, "パッチを左室側から正面に見て、手前（左室の自由壁側）を切る。VR 心内なら左室の中で切るので、中隔の肉柱・乳頭筋とパッチの縁が立体で見える"); r.addWidget(self.patchLButton, 1)
        self.patchRButton = B("右室側から", None, "パッチを右室側から正面に見て、手前（右室の自由壁側）を切る。VR 心内なら右室の中で切るので、右室側の肉柱・調節帯とパッチの縁が立体で見える"); r.addWidget(self.patchRButton, 1)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r); r.addWidget(Lb("術前 CT", "muted"))
        self.prePatchCombo = qt.QComboBox(); r.addWidget(self.prePatchCombo, 1)
        self.prePatchCombo.setToolTip("同じ人の術前 CT。あれば位置を合わせて、術前の欠損が閉じた所・術後に新しく薄くなった所だけをパッチにする（もとから薄い所は外す）。なければ術後だけで探す（候補が多め）")
        self.preRefreshButton = B("↻", "ghost", "CT の一覧を読み直す"); r.addWidget(self.preRefreshButton)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.autoPatchButton = B("パッチを自動で探す", None, "左室と右室の血液の間が 2 mm 以下の薄い仕切り（本来の中隔は 8〜10 mm）を探してパッチにする。1 例 数十秒〜1 分（術前 CT の心腔を初めて認識する時は +4 分）。研究・教育用の推定"); r.addWidget(self.autoPatchButton, 1)
        self.patchRemoveButton = B("違う所を外す", None, "押してから、違うパッチのかたまりをクリック（何個でも）。もう一度押すと終わり", checkable=True); r.addWidget(self.patchRemoveButton)
        self.patchRemoveUndoButton = B("1つ戻す", "ghost", "外したかたまりを 1 つ戻す"); r.addWidget(self.patchRemoveUndoButton)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r); r.addWidget(Lb("濃さ", "muted"))
        self.capSlider = ctk.ctkSliderWidget(); self.capSlider.minimum = 0; self.capSlider.maximum = 100; self.capSlider.suffix = " %"
        self.capSlider.setToolTip("心筋の断面の濃さ")
        try: self.capSlider.value = float(qt.QSettings().value("CardiacView/capOpacityV2", 30))   # 初期値 30%
        except Exception: self.capSlider.value = 30
        r.addWidget(self.capSlider, 1)
        self.fillCheck = qt.QCheckBox("薄い壁の穴を補う"); self.fillCheck.checked = True
        self.fillCheck.setToolTip("ON: 部分容積で欠けた薄い壁（心房・大血管）を内腔の外側に約2.4mm足して閉じる。補った所はグレー。\n"
                                  "OFF: CT 値（-20〜175HU）だけで壁を作る。本物の欠損もアーチファクトの穴もそのまま見える。")
        c.addWidget(self.fillCheck)
        self.synthCheck = qt.QCheckBox("補った所をグレーで示す"); self.synthCheck.checked = True
        self.synthCheck.setToolTip("OFF にすると補った壁も同じ色で表示（見た目重視・発表用）。感染などの本物の穴との区別には ON で確認。")
        c.addWidget(self.synthCheck)

    def _buildCutPage(self, pages):
        """切る"""
        B, Lb = self._btn, self._lab
        P = pages["切る"]
        card, c, _ = self._card(P, "切断面")
        f = qt.QFormLayout(); f.setHorizontalSpacing(8); f.setVerticalSpacing(6); c.addLayout(f)
        self.cutCombo = qt.QComboBox()
        for lab, _ in CUT_MODES: self.cutCombo.addItem(lab)
        f.addRow(Lb("向き", "muted"), self.cutCombo)
        self.cutSlider = ctk.ctkSliderWidget(); self.cutSlider.minimum = 0; self.cutSlider.maximum = 100; self.cutSlider.value = 50
        self.cutSlider.suffix = " %"
        f.addRow(Lb("位置", "muted"), self.cutSlider)
        self.cutStep = qt.QHBoxLayout(); self.cutStep.setSpacing(4)
        st = qt.QSettings()
        self.stepSpin = qt.QDoubleSpinBox(); self.stepSpin.setRange(0.5, 20.0); self.stepSpin.setSingleStep(0.5); self.stepSpin.setDecimals(1)
        self.stepSpin.setSuffix(" mm"); self.stepSpin.setToolTip("◀ ▶ で動かす幅")
        try: self.stepSpin.setValue(float(st.value("CardiacView/stepMM", 5.0)))
        except Exception: self.stepSpin.setValue(5.0)
        self.cutMinus = B("◀", "tool"); self.cutPlus = B("▶", "tool")
        for b in (self.cutMinus, self.cutPlus): b.setMinimumWidth(40)
        self.cutStep.addWidget(self.cutMinus); self.cutStep.addWidget(self.stepSpin); self.cutStep.addWidget(self.cutPlus); self.cutStep.addStretch(1)
        self.flipButton = B("反転", None, "残す側を反対にする"); self.cutStep.addWidget(self.flipButton)
        f.addRow(Lb("移動", "muted"), self.cutStep)
        self._updateStepLabels()
        self.lockCheck = qt.QCheckBox("この断面で固定")
        self.lockCheck.setToolTip("いい断面ができたらチェック。3D をくるくる回しても切る面は体に固定されたまま。ホイールで面に垂直に平行移動")
        c.addWidget(self.lockCheck)
        self.insetCheck = qt.QCheckBox("左下に全体図（どこを切っているか）"); self.insetCheck.checked = True
        self.insetCheck.setToolTip("左下の小さな図はいつも正面から。オレンジ枠 = 切断面、黄色い線 = 切り口、水色の矢印 = 今見ている向き")
        c.addWidget(self.insetCheck)
        hn = Lb("ホイール: 切る位置 1 mm（Shift 5 mm）", "muted"); hn.setWordWrap(True); c.addWidget(hn)

        card, c, _ = self._card(P, "パッチ（塗って色分け）")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.paintButton = B("パッチを塗る", "vr", "3D の面の上を左ドラッグで緑に塗る（Ctrl＋ドラッグで消す）。何もない所のドラッグはいつもどおり回転。\n"
                             "もう一度押すか Esc で終わり。先に切って中を見せてから塗ると楽です", checkable=True)
        r.addWidget(self.paintButton, 1)
        self.brushBtns = {}; bg = qt.QButtonGroup(card); bg.setExclusive(True); self._brushGroup = bg
        try: bmm = float(qt.QSettings().value("CardiacView/brushMM", 4.0))
        except Exception: bmm = 4.0
        for lab, mm in (("細", 2.5), ("中", 4.0), ("太", 7.0)):
            b = B(lab, "seg", f"筆の太さ（半径 {mm:g} mm）", checkable=True); bg.addButton(b); r.addWidget(b); self.brushBtns[mm] = b
            b.checked = abs(mm - bmm) < 0.01
            b.connect("clicked()", lambda mm=mm: self._setBrush(mm))
        if not any(b.checked for b in self.brushBtns.values()): self.brushBtns[4.0].checked = True
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.patchFaceButton = B("正面から見る", None, "塗ったパッチを正面に向けて、その手前を切る（パッチの面で切る）"); r.addWidget(self.patchFaceButton, 1)
        self.patchUndoButton = B("1つ戻す", None, "最後のひと塗りを取り消す"); r.addWidget(self.patchUndoButton)
        self.patchClearButton = B("全部消す", None, "塗ったパッチを全部消す"); r.addWidget(self.patchClearButton)
        card.hide()                                                           # 手で塗る方式はやめる（恣意的になる）。CT の値で「似た所」をまとめて選ぶ方式に置き換える予定
        self.paintButton.connect("toggled(bool)", self._onPaint)
        self.patchFaceButton.connect("clicked()", self._onPatchFace)
        self.patchUndoButton.connect("clicked()", lambda: self._status(self.logic.patchUndo()))
        self.patchClearButton.connect("clicked()", lambda: self._status(self.logic.patchClear()))

    def _buildSlicePage(self, pages):
        """断面（画面の分け方・MPR）"""
        B, Lb = self._btn, self._lab
        P = pages["断面"]
        card, c, _ = self._card(P, "画面")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.layoutButtons = {}; lg = qt.QButtonGroup(card); lg.setExclusive(True)
        for key, lab, tip in (("3d", "3D", "3D だけを大きく"),
                              ("four", "4画面", "3D ＋ 軸位・矢状断・冠状断（元の CT）。線をドラッグで位置・回して斜め断面。Shift＋マウスで 3 断面をその点へ。ダブルクリックで 1 画面に拡大"),
                              ("cut", "3D＋断面", "左に 3D、右に 3D で切っている面そのものの断面（元の CT）。どちらでホイールを回しても一緒に動く")):
            b = B(lab, "seg", tip, checkable=True); lg.addButton(b); r.addWidget(b, 1); self.layoutButtons[key] = b
        self.layoutButtons["3d"].checked = True; self._layoutGroup = lg
        self.scaleCheck = qt.QCheckBox("目盛り（平行投影）"); self.scaleCheck.checked = True; self.scaleCheck.setToolTip("3D を平行投影にして長さの目盛りを出す（断面にも）")
        c.addWidget(self.scaleCheck)
        card.hide()                                                           # 画面割りは画像の上のバーへ

        card, c, hd = self._card(P, "MPR")
        self.mprResetButton = B("リセット", "ghost", "斜めにした断面を、軸位・矢状断・冠状断に戻す"); hd.addWidget(self.mprResetButton)
        self.obliqueCheck = qt.QCheckBox("線で斜めに（端の丸をドラッグ）"); self.obliqueCheck.checked = True
        self.obliqueCheck.setToolTip("4画面の色つきの線をドラッグ: 真ん中 = 位置、端の丸 = 回して斜めの断面（好きな MPR）")
        c.addWidget(self.obliqueCheck)
        self.outlineCheck = qt.QCheckBox("3D の輪郭を重ねる"); self.outlineCheck.setToolTip("3D の面（心臓・血管）の切り口の線を断面に重ねる")
        c.addWidget(self.outlineCheck)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r); r.addWidget(Lb("MIP 厚さ", "muted"))
        self.slabCombo = qt.QComboBox()
        for lab in ("なし", "5 mm", "10 mm", "20 mm", "40 mm"): self.slabCombo.addItem(lab)
        self.slabCombo.setToolTip("断面に厚みを持たせて最大値投影（血管・冠動脈を追いやすい）"); r.addWidget(self.slabCombo); r.addStretch(1)

        card, c, _ = self._card(P, "斜めの微調整")
        self.rotView = qt.QComboBox()
        for lab in ("軸位の中で回す", "矢状断の中で回す", "冠状断の中で回す"): self.rotView.addItem(lab)
        self.rotView.setToolTip("選んだ断面の中で、ほかの断面の線（向き）を回す。断面の上で [ ] キーでも 1°（Shift で 5°）")
        c.addWidget(self.rotView)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.rotButtons = []
        for lab, deg in (("↺5°", 5.0), ("↺1°", 1.0), ("↻1°", -1.0), ("↻5°", -5.0)):
            b = B(lab, "tool"); r.addWidget(b, 1); self.rotButtons.append((b, deg))
        self.mprAngleLabel = Lb("0°", "accent"); self.mprAngleLabel.setWordWrap(True); c.addWidget(self.mprAngleLabel)

    def _buildMeasurePage(self, pages):
        """計測"""
        B, Lb = self._btn, self._lab
        P = pages["計測"]
        card, c, hd = self._card(P, "計測")
        self.rulerClearButton = B("すべて消す", "ghost", "測った線・面積・角度をすべて消す（1 つだけ消す時は、その計測にマウスを乗せて Delete キー）"); hd.addWidget(self.rulerClearButton)
        g = qt.QGridLayout(); g.setHorizontalSpacing(4); g.setVerticalSpacing(4); c.addLayout(g)
        self.measureButtons = {}
        tips = {"line": "2 点クリックで長さ", "poly": "クリックで点を追加、右クリックで終了。折れ線の長さ",
                "curve": "クリックで点を追加、右クリックで終了。なめらかな曲線に沿った長さ（血管・弁輪など）",
                "area": "輪郭をクリックで囲み、右クリックで終了。面積と周長", "angle": "3 点クリックで角度"}
        for k, (key, lab, cls, pre) in enumerate(CardiacViewLogic.MEASURES):
            b = B(lab, "tool", tips[key]); g.addWidget(b, k // 3, k % 3); self.measureButtons[key] = b
        hn = Lb("3D の面・VR の上、または断面の上でクリック。1 つ消す: マウスを乗せて Delete", "muted"); hn.setWordWrap(True); c.addWidget(hn)

        card, c, _ = self._card(P, "大動脈")
        self.aortaButton = B("大動脈サイジングへ  ›", "primary", "中心線 → 径の表 → CSV（ステントグラフトのサイジング）"); c.addWidget(self.aortaButton)
        self.flyButton = B("大動脈の中に入る", None, "中心線に沿って大動脈の中から見る（先に大動脈サイジングで中心線を作る）"); c.addWidget(self.flyButton)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r); r.addWidget(Lb("位置", "muted"))
        self.flySlider = ctk.ctkSliderWidget(); self.flySlider.minimum = 0; self.flySlider.maximum = 100; self.flySlider.value = 20
        self.flySlider.setToolTip("中心線上の位置"); r.addWidget(self.flySlider, 1)

    def _buildSettingsPage(self, pages):
        """設定"""
        B, Lb = self._btn, self._lab
        P = pages["設定"]
        card, c, _ = self._card(P, "3D の作り方")
        f = qt.QFormLayout(); f.setHorizontalSpacing(8); c.addLayout(f)
        self.resSpin = qt.QDoubleSpinBox(); self.resSpin.setRange(0.4, 3.0); self.resSpin.setSingleStep(0.1); self.resSpin.value = 1.2; self.resSpin.suffix = " mm"
        f.addRow(Lb("メッシュ解像度", "muted"), self.resSpin)
        self.boneCheck = qt.QCheckBox("骨を別レイヤーにする"); self.boneCheck.checked = True
        self.boneCheck.setToolTip("TotalSegmentator の骨ラベルで骨を分ける"); c.addWidget(self.boneCheck)
        grid = qt.QGridLayout(); grid.setHorizontalSpacing(4); grid.setVerticalSpacing(3); c.addLayout(grid)
        for col, hh in enumerate(["", "名前", "下限 HU", "上限 HU", "色", "平滑"]):
            grid.addWidget(Lb(hh, "colh"), 0, col)
        for i, (name, lo, hi, col, sm, vis) in enumerate(DEFAULT_LAYERS):
            self._addLayerRow(grid, i + 1, name, lo, hi, col, sm, vis)
        grid.setColumnStretch(1, 1)
        self.buildButton = B("この設定で作り直す", None, "上のレイヤー設定で面を作り直す"); c.addWidget(self.buildButton)

        card, c, _ = self._card(P, "見た目"); self._lookLay = c
        f = qt.QFormLayout(); f.setHorizontalSpacing(8); f.setVerticalSpacing(6); c.addLayout(f)
        self.bgCombo = qt.QComboBox(); self.bgCombo.addItems(["黒", "濃いグレー", "白"]); f.addRow(Lb("背景", "muted"), self.bgCombo)
        try: self.bgCombo.currentIndex = max(0, min(2, int(qt.QSettings().value("CardiacView/bg", 0) or 0)))   # 前に選んだ背景（欄と画面を合わせる）
        except Exception: pass
        self.paletteCombo = qt.QComboBox(); self.paletteCombo.addItems(["リアル（深紅・金・薄紫）", "赤と青", "落ち着いた（前の色）"])
        self.paletteCombo.setToolTip("面と VR の色合い。分け方は同じで、色の濃さと光沢だけ変わる")
        self.paletteCombo.currentIndex = {"リアル": 0, "赤と青": 1}.get(common.CUR_PALETTE, 2); f.addRow(Lb("色合い", "muted"), self.paletteCombo)
        self.glossSlider = ctk.ctkSliderWidget(); self.glossSlider.minimum = 0; self.glossSlider.maximum = 100; self.glossSlider.value = 50; f.addRow(Lb("光沢", "muted"), self.glossSlider)
        self.opacitySlider = ctk.ctkSliderWidget(); self.opacitySlider.minimum = 0; self.opacitySlider.maximum = 100; self.opacitySlider.value = 100; f.addRow(Lb("血液の不透明度", "muted"), self.opacitySlider)
        self.fovSlider = ctk.ctkSliderWidget(); self.fovSlider.minimum = 15; self.fovSlider.maximum = 120; self.fovSlider.value = 30; f.addRow(Lb("視野角", "muted"), self.fovSlider)
        self.ssaoCheck = qt.QCheckBox("陰影で奥行きを出す（環境光遮蔽）"); self.ssaoCheck.checked = True; c.addWidget(self.ssaoCheck); self.ssaoCheck.hide()
        self.shadeCombo = qt.QComboBox(); self.shadeCombo.addItems(["なし", "ふつう", "強め"])
        self.shadeCombo.setToolTip("面: 環境光遮蔽（くぼみが暗くなる）と光の当たり方の差。VR: 環境光を下げてメリハリ。重い PC では自動で 1 段下げる")
        try: _lv = str(qt.QSettings().value("HUCViewS/shading") or "ふつう")
        except Exception: _lv = "ふつう"
        self.shadeCombo.currentIndex = {"なし": 0, "ふつう": 1, "強め": 2}.get(_lv, 1); f.addRow(Lb("陰影", "muted"), self.shadeCombo)

        card, c, _ = self._card(P, "その他"); self._otherLay = c
        self.freePlaneButton = B("自由な切断面を追加", None, "3D 上のハンドルで向き・位置を操作する切断面"); c.addWidget(self.freePlaneButton)
        r = qt.QHBoxLayout(); r.setSpacing(4); pages["計測"].addLayout(r)
        self.distButton = B("距離", "tool", "Slicer 標準の距離マーカー"); self.angleButton = B("角度", "tool", "Slicer 標準の角度マーカー"); self.curveButton = B("閉曲線", "tool", "Slicer 標準の閉曲線マーカー")
        for b in (self.distButton, self.angleButton, self.curveButton): r.addWidget(b, 1)
        self.saveButton = B("シーンを保存（.mrb）", None, "表示・計測をまとめて 1 ファイルに保存"); c.addWidget(self.saveButton)

    def _arrangeParts(self, v, pages):
        """置き場所の整理（同じものを 2 か所に置かない。専門的な設定は「設定」へ）"""
        Lb = self._lab
        r = qt.QHBoxLayout(); r.setSpacing(6); self._sceneLay.addLayout(r)
        self.aortaButton.setProperty("kind", ""); self.aortaButton.setText("大動脈サイジング  ›"); r.addWidget(self.aortaButton, 1)
        self.aortaButton.style().unpolish(self.aortaButton); self.aortaButton.style().polish(self.aortaButton)
        self._lookLay.addWidget(self.scaleCheck)
        card, c, _ = self._card(pages["設定"], "壁の補正"); c.addWidget(self.fillCheck); c.addWidget(self.synthCheck)
        self._otherLay.addWidget(self.flyButton)
        rr = qt.QHBoxLayout(); rr.setSpacing(6); rr.addWidget(Lb("中心線上の位置", "muted")); rr.addWidget(self.flySlider, 1); self._otherLay.addLayout(rr)
        self._otherLay.addWidget(self.saveButton)
        v.addStretch(1)
        try: t0 = int(qt.QSettings().value("CardiacView/tab", 0))
        except Exception: t0 = 0
        self._showTab(t0 if 0 <= t0 < len(self.pages) else 0)

    def _connectSignals(self):
        """signals"""
        self.loadButton.connect("clicked()", self.onLoad)
        self.dicomButton.connect("clicked()", self.onLoadDicom)
        self.quickButton.connect("clicked()", self.onQuick)
        self.buildButton.connect("clicked()", self.onBuild)
        self.cutTimer = qt.QTimer(); self.cutTimer.setSingleShot(True); self.cutTimer.setInterval(60)
        self.cutTimer.connect("timeout()", self._applyCut)
        self.cutCombo.connect("currentIndexChanged(int)", lambda i: self._applyCut())
        self.cutSlider.connect("valueChanged(double)", lambda v: self.cutTimer.start())
        self.flipButton.connect("clicked()", lambda: (self.logic.flipCut(), None))
        self.lockCheck.connect("toggled(bool)", self._onLock)
        self.insetCheck.connect("toggled(bool)", lambda on: self.logic.setInsetVisible(on))
        self.cutMinus.connect("clicked()", lambda: self._nudge(-self.stepSpin.value))
        self.cutPlus.connect("clicked()", lambda: self._nudge(+self.stepSpin.value))
        self.stepSpin.connect("valueChanged(double)", self._onStepChanged)
        for key, b in self.viewButtons.items():
            b.connect("clicked()", lambda k=key: self.logic.setView(k, self.fovSlider.value))
        for name, cb in self.layerChecks.items():
            cb.connect("toggled(bool)", lambda v, n=name: self._onLayerCheck(n, v))
        self.heartOnlyButton.connect("clicked()", self.onHeartOnly)
        self.lumenButton.connect("clicked()", self.onLumen)
        self.vsdButton.connect("clicked()", self.onVSD)
        self.patchLButton.connect("clicked()", lambda: self._onPatchSide("L")); self.patchRButton.connect("clicked()", lambda: self._onPatchSide("R"))
        self.preRefreshButton.connect("clicked()", self._fillPreCombo); self.autoPatchButton.connect("clicked()", self._onAutoPatch)
        self.prePatchCombo.connect("currentIndexChanged(int)", self._onPreCombo)   # 「なし」を選んだら、押すたびに術前 CT へ戻さない（前は戻っていた）
        self.patchRemoveButton.connect("toggled(bool)", self._onPatchRemove)
        self.patchRemoveUndoButton.connect("clicked()", lambda: self._status("1 つ戻しました" if self.logic.patchRemoveUndo() else "戻すものがありません"))
        self._preVols = [None]; self._fillPreCombo()
        self.fourChButton.connect("clicked()", self.onFourChamber)
        for key, b in self.sceneButtons.items(): b.connect("clicked()", lambda key=key: self.onScene(key))
        self.capSlider.connect("valueChanged(double)", self._onCapChanged)
        self.fillCheck.connect("toggled(bool)", self._onFillToggled)
        self.synthCheck.connect("toggled(bool)", self._onSynthToggled)
        self.vrTissueButton.connect("clicked()", lambda: self._onVR("tissue"))
        for key, b in self.layoutButtons.items(): b.connect("clicked()", lambda k=key: self.logic.setLayout(k))
        self.obliqueCheck.connect("toggled(bool)", lambda on: self.logic.setObliqueHandles(on))
        self.slabCombo.connect("currentIndexChanged(int)", lambda i: self.logic.setSlab([0, 5, 10, 20, 40][i]))
        self.mprResetButton.connect("clicked()", lambda: self.logic.resetMPR())
        self.outlineCheck.connect("toggled(bool)", lambda on: self.logic.setOutlines2D(on))
        for b, deg in self.rotButtons:
            b.connect("clicked()", lambda deg=deg: self.logic.rotateMPR(("Red", "Yellow", "Green")[self.rotView.currentIndex], deg))
        for key, b in self.rmodeButtons.items(): b.connect("clicked()", lambda k=key: self.logic.setRightMode(k))
        self.scaleCheck.connect("toggled(bool)", lambda on: self.logic.setScale(on))
        msgs = {"line": "始点と終点をクリック", "poly": "点をクリックで追加、終わったら右クリック", "curve": "点をクリックで追加、終わったら右クリック",
                "area": "輪郭を囲むようにクリック、終わったら右クリック", "angle": "3 点クリック（2 点目が角の頂点）"}
        for key, b in self.measureButtons.items():
            b.connect("clicked()", lambda k=key: (self.logic.startMeasure(k), self._status(msgs[k] + "（3D の面・VR の上、または断面）")))
        self.rulerClearButton.connect("clicked()", lambda: self.logic.clearRulers())   # 押した時のロジックで（入口が症例ごとにロジックを作り直す）
        self.vrBloodButton.connect("clicked()", lambda: self._onVR("blood"))
        self.bgCombo.connect("currentIndexChanged(int)", lambda i: self.logic.setBackground(i))
        self.paletteCombo.connect("currentIndexChanged(int)", self.onPalette)
        self.shadeCombo.connect("currentIndexChanged(int)", self.onShade)
        self.glossSlider.connect("valueChanged(double)", lambda v: self.logic.setGloss(v / 100.0))
        self.opacitySlider.connect("valueChanged(double)", lambda v: self.logic.setLayerOpacity("血液・血管", v / 100.0))
        self.ssaoCheck.connect("toggled(bool)", lambda v: self.logic.studioLighting(self.bgCombo.currentIndex, ssao=v))
        self.fovSlider.connect("valueChanged(double)", lambda v: self.logic.setFov(v))
        self.freePlaneButton.connect("clicked()", lambda: self.logic.addFreePlane())
        self.flyButton.connect("clicked()", lambda: self.logic.flyAorta(self.flySlider.value / 100.0))
        self.flySlider.connect("valueChanged(double)", lambda v: self.logic.flyAorta(v / 100.0, onlyIfFlying=True))
        self.distButton.connect("clicked()", lambda: self.logic.placeMarkup("vtkMRMLMarkupsLineNode", "距離"))
        self.angleButton.connect("clicked()", lambda: self.logic.placeMarkup("vtkMRMLMarkupsAngleNode", "角度"))
        self.curveButton.connect("clicked()", lambda: self.logic.placeMarkup("vtkMRMLMarkupsClosedCurveNode", "閉曲線"))
        self.aortaButton.connect("clicked()", self.onAortaSizing)
        self.saveButton.connect("clicked()", self.onSave)
        self.play4DButton.connect("toggled(bool)", self._onPlay4D)
        self.phaseSlider.connect("valueChanged(double)", self._onPhase4D)
        self.fpsSpin.connect("valueChanged(double)", self._onFps4D)
        self.end4DButton.connect("clicked()", self._end4D)
        for key, b in self.mode4DButtons.items(): b.connect("clicked()", lambda k=key: (self.logic.show4D(True), self.logic.set4DMode(k), self._label4D()))
        self.wl4DButton.connect("clicked()", lambda: (self.logic.resetWindow(), self._status("ウィンドウを最初の値に戻しました")))
        self._t4D = qt.QTimer(); self._t4D.setInterval(100); self._t4D.connect("timeout()", self._tick4D)
        self._uiTimer = qt.QTimer(); self._uiTimer.setInterval(200); self._uiTimer.connect("timeout()", self._uiTick)
        self._buildToolbar()
