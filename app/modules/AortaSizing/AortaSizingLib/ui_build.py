# -*- coding: utf-8 -*-
"""大動脈サイジング: 画面を組み立てる（setup）
AortaSizingWidget の一部（WidgetBuildMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class WidgetBuildMixin:

    # ---------------------------------------------------------------- 画面
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = AortaSizingLogic(); L = self.logic
        root = qt.QWidget(); root.setObjectName("saRoot"); root.setStyleSheet(STYLE)
        root.setAttribute(qt.Qt.WA_StyledBackground, True)
        _sc = qt.QScrollArea(); _sc.setWidgetResizable(True); _sc.setFrameShape(qt.QFrame.NoFrame); _sc.setWidget(root)   # パネルを狭くしても使える
        _sc.setStyleSheet("QScrollArea{background:#15171c; border:none}")
        try:
            import CardiacView; _sc.setStyleSheet(CardiacView.SC_STYLE); root.setStyleSheet(STYLE + CardiacView._iconCSS().replace("cvRoot", "saRoot"))
        except Exception: pass
        _sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        self.layout.addWidget(_sc); self.layout.setContentsMargins(0, 0, 0, 0)
        v = qt.QVBoxLayout(root); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(10); self.root = root

        # ヘッダー
        h = qt.QHBoxLayout(); v.addLayout(h)
        back = self._btn("‹ 入口", "ghost", "HeartView の入口へ戻る"); h.addWidget(back)
        back.connect("clicked()", lambda: slicer.util.selectModule("HeartView") if hasattr(slicer.modules, "heartview") else None)
        t = self._lab("大動脈サイジング"); t.setStyleSheet("font-size:17px; font-weight:bold; color:#ffffff"); h.addWidget(t); h.addStretch(1)
        h.addWidget(self._lab("研究・教育用", "muted"))

        # ステップ
        sb = qt.QHBoxLayout(); sb.setSpacing(0); v.addLayout(sb); self.stepGrp = qt.QButtonGroup(root); self.stepBtns = []; self._stepBar = sb
        for i, txt in enumerate(("1 中心線", "2 計測", "3 計画", "4 術後", "5 出力")):
            b = self._btn(txt, "step", checkable=True); self.stepGrp.addButton(b, i); sb.addWidget(b); self.stepBtns.append(b)
            b.connect("clicked()", lambda i=i: self.showStep(i))

        # 読み取りカード（いつも見える）
        card, c = self._card(v)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.posLabel = self._lab("—", "big"); r.addWidget(self.posLabel)
        self.pathChip = self._lab(""); self.pathChip.setStyleSheet("padding:2px 8px; border-radius:9px; font-size:11px; font-weight:bold; color:#15171c")
        r.addWidget(self.pathChip); r.addStretch(1)
        self.modeGrp, (self.outerBtn, self.lumenBtn) = self._seg(["外周", "内腔"], r)
        self.outerBtn.checked = True; self.outerBtn.setToolTip("径の線（赤・青）を外周で出す  [L]"); self.lumenBtn.setToolTip("径の線を内腔で出す  [L]")
        g = qt.QGridLayout(); g.setHorizontalSpacing(14); g.setVerticalSpacing(2); c.addLayout(g)
        for j, txt in enumerate(("", "Dmax", "Dmin", "Deq", "面積 mm²")): g.addWidget(self._lab(txt, "colh"), 0, j)
        self.vals = {}
        for i, (key, nm, col) in enumerate((("outer", "外周", "#59d0ff"), ("lumen", "内腔", "#ffd84d"))):
            l = self._lab(f"<span style='color:{col}'>●</span> {nm}"); g.addWidget(l, i + 1, 0)
            for j, f in enumerate(("dmax", "dmin", "deq", "area")):
                w = self._lab("—", "val"); g.addWidget(w, i + 1, j + 1); self.vals[(key, f)] = w
        r2 = qt.QHBoxLayout(); c.addLayout(r2)
        self.pinBtn = self._btn("📌 この断面を記録  P", "primary", "今の断面（外周・内腔の径）をマーカーとして残す"); r2.addWidget(self.pinBtn)
        self.baseBtn = self._btn("ここを 0 mm に", None, "ベースライン（距離の基準）にする"); r2.addWidget(self.baseBtn)
        r2 = qt.QHBoxLayout(); c.addLayout(r2)                              # 2 段に（パネルが狭くてもはみ出さない）
        self.editContBtn = self._btn("輪郭を直す", None, "断面の輪郭を点で手直し", checkable=True); r2.addWidget(self.editContBtn)
        self.wlBtn = self._btn("ウィンドウを戻す", None, "断面・ストレッチ像の濃さを最初（血管用 W800/L200）に戻す"); r2.addWidget(self.wlBtn)
        hint = self._hintTop = self._lab("断面: ホイール 1 mm（Shift 5 mm）・ストレッチ像（直交 2 方向）: クリック/ドラッグで移動、ホイールで回転・"
                         "Ctrl+クリック 中心線をそこへ（断面・ストレッチ像）・Enter 置く・P 記録・L 外周/内腔・Ctrl+Z 戻す・Esc 中止", "muted"); hint.setWordWrap(True); c.addWidget(hint)

        self.stack = qt.QStackedWidget(); v.addWidget(self.stack, 1)

        # ---- ページ 1: 中心線
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10); self.stack.addWidget(pg)
        flow = self._lab("流れ: CT を開く → 1 中心線 → 2 計測 → 3 計画（3D で穴の場所・仮想ステント）→ 手術 → 4 術後（術後 CT を重ねて違いを見る）→ 5 出力", "muted")
        flow.setWordWrap(True); pl.addWidget(flow)
        card, c = self._card(pl, "中心線", "AI ラベル + VMTK")
        self.autoButton = self._btn("自動で中心線を作る（1 分ほど）", "primary"); c.addWidget(self.autoButton)
        c.addWidget(self._lab("経路", "muted"))
        self.pathGrp, (self.rightBtn, self.leftBtn, self.aortaBtn) = self._seg(["右（橙）", "左（水色）", "大動脈のみ"], c)
        self.fixButton = self._btn("中心線を合わせる（大きな軸位でクリック）", "primary", "大きな軸位の画面で、真腔の中心を上から順にクリックしていくだけ。最後に Enter で反映", True); c.addWidget(self.fixButton)
        self.fixHint = self._lab("真腔の中心をクリックすると黄色い点が置かれ、自動で 1 cm 先の高さへ進みます（計算はまだしません）。"
                                 "ずれている所だけクリックすれば OK。ホイールで上下、Enter で反映、Backspace で 1 つ戻す、Esc で終わる（残った点は反映）。", "muted")
        self.fixHint.setWordWrap(True); self.fixHint.hide(); c.addWidget(self.fixHint)
        self.fixRow = qt.QWidget(); fr = qt.QHBoxLayout(self.fixRow); fr.setContentsMargins(0, 0, 0, 0); c.addWidget(self.fixRow)
        fr.addWidget(self._lab("進む幅", "muted")); self.fixStepGrp, self.fixStepBtns = self._seg(["5", "10", "20 mm"], fr); self.fixStepBtns[1].checked = True
        self.fixApply = self._btn("反映して作り直す（0 点）", "primary", "置いた修正点で、中心線をまとめて 1 回だけ作り直す"); fr.addWidget(self.fixApply, 1)
        self.fixClear = self._btn("点を消す", None, "反映していない修正点を全部消す"); fr.addWidget(self.fixClear)
        self.fixRow.hide()
        self.editButton = self._btn("中心線を手で直す（3 断面でクリック / ドラッグ）", "primary", "軸位・矢状断・冠状断のどこでも、中心線の近くをクリックするとそこへ動き、押したままドラッグでずらせます", True); c.addWidget(self.editButton)
        self.editHint = self._lab("3 断面のどこでも: 中心線（線）の近くをクリック → そこへ動く。押したままドラッグ → ずらす。"
                                  "右クリック → 点を消す。ホイール → スライス送り。Ctrl+Z → 戻す。終わったら「完了」か Enter（ここで 1 回だけ作り直します）。", "muted")
        self.editHint.setWordWrap(True); self.editHint.hide(); c.addWidget(self.editHint)
        self.fixButton.hide()
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.addPtButton = self._btn("通る点を追加"); r.addWidget(self.addPtButton); self.addPtButton.hide()
        self.centerHereButton = self._btn("ここを中心に寄せる"); r.addWidget(self.centerHereButton)
        self.centerAllButton = self._btn("全体を中心に寄せる"); r.addWidget(self.centerAllButton)
        c.addWidget(self._lab("3D の線をクリック = 左右の切り替えとその位置へ移動", "muted"))
        c.addWidget(self._lab("細かい修正: 断面やストレッチ像で Ctrl+クリック = その位置の中心線をクリックした所へ（Ctrl+Z で戻す）", "muted"))
        nxt = self._btn("次へ: 計測 ›", "ghost"); nxt.connect("clicked()", lambda: self.showStep(1)); pl.addWidget(nxt, 0, qt.Qt.AlignRight)
        pl.addStretch(1)

        # ---- ページ 2: 計測
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10)
        sc = qt.QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(qt.QFrame.NoFrame); sc.setWidget(pg)
        sc.setStyleSheet("QScrollArea{background:transparent} QScrollArea > QWidget > QWidget{background:transparent}"); self.stack.addWidget(sc)
        card, c = self._card(pl, "テンプレート", "順番に置いていくだけ")
        self.tplGrp, self.tplBtns = self._seg(list(TEMPLATES), c)
        self.tplBtns[0].checked = True
        self._lenSlot = qt.QVBoxLayout(); c.addLayout(self._lenSlot)
        self.stepList = qt.QListWidget(); self.stepList.setMinimumHeight(190); c.addWidget(self.stepList)
        nb = qt.QFrame(); nb.setStyleSheet("QFrame{background:#16324a; border:1px solid #2c6b93; border-radius:10px}"); nl = qt.QVBoxLayout(nb); nl.setContentsMargins(10, 8, 10, 8)
        self.nextLabel = self._lab("—"); self.nextLabel.setStyleSheet("color:#ffffff; font-size:14px; font-weight:bold; border:none"); nl.addWidget(self.nextLabel)
        self.nextHint = self._lab("", "muted"); self.nextHint.setStyleSheet("border:none; color:#a9c7dc; font-size:11px"); self.nextHint.setWordWrap(True); nl.addWidget(self.nextHint)
        c.addWidget(nb)
        self.lenBtn = self._btn("長さを自動で出す（3D に）", "primary", "印（ネック終端・瘤の最大径・内腸骨起始など）を径の推移から自動で置き（? つき・手で置いた印はそのまま）、"
                                "ネック長・腎動脈→分岐・総腸骨などの長さを 3D の血管の横に出します。印は断面を動かして「ここに置く」で直せます", True); c.addWidget(self.lenBtn)
        self.lenLab = qt.QLabel(""); self.lenLab.setTextFormat(qt.Qt.RichText); self.lenLab.setWordWrap(True); self.lenLab.setStyleSheet("font-size:12px; color:#dfe6ee")
        self.lenLab.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred); self.lenLab.setMinimumWidth(10); c.addWidget(self.lenLab); self.lenLab.hide()
        c.removeWidget(self.lenBtn); c.removeWidget(self.lenLab); self._lenSlot.addWidget(self.lenBtn); self._lenSlot.addWidget(self.lenLab)
        bg = qt.QGridLayout(); bg.setHorizontalSpacing(4); bg.setVerticalSpacing(4); self._lenSlot.addLayout(bg); self.brChips = {}
        for i, nm in enumerate(self.BR_CHIPS):
            b = self._btn(self.SHORT.get(nm, nm), None, f"{nm}: 断面（または 3D のクリック）でその枝の口に合わせて押す → 印。? の印は 1 回押すとそこへ移動、合っていればもう一度押すと確認（✓）。Ctrl+Z で戻す")
            b.setStyleSheet("padding:3px 4px; font-size:11px"); bg.addWidget(b, i // 4, i % 4); self.brChips[nm] = b
            b.connect("clicked()", lambda nm=nm: self.onBranchChip(nm))
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.placeBtn = self._btn("ここに置く  ⏎", "primary"); r.addWidget(self.placeBtn, 2)
        self.skipBtn = self._btn("スキップ"); r.addWidget(self.skipBtn)
        self.prevBtn = self._btn("‹ 戻る"); r.addWidget(self.prevBtn)
        self.unplaceBtn = self._btn("外す"); r.addWidget(self.unplaceBtn)

        card, c = self._card(pl, "手動計測", "どのビューでも。点はあとからドラッグで直せる")
        tr = qt.QHBoxLayout(); tr.setSpacing(4); c.addLayout(tr); self.toolBtns = {}
        for key, lab, *_ in AortaSizingLogic.MEASURES:
            b = self._btn(lab, "tool", {"line": "2 点の距離", "poly": "折れ線の長さ（右クリック / Enter で終わり）", "curve": "曲線の長さ（右クリック / Enter で終わり）",
                                         "area": "囲んだ面積（右クリック / Enter で終わり）", "angle": "3 点の角度"}[key], True)
            tr.addWidget(b); self.toolBtns[key] = b; b.connect("clicked()", lambda key=key: self.onTool(key))
        self.measTable = qt.QTableWidget(0, 4); self.measTable.setHorizontalHeaderLabels(["名前", "値", "場所", "位置"])
        self._tbl(self.measTable, 120); c.addWidget(self.measTable)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.measDel = self._btn("選んだ計測を消す"); r.addWidget(self.measDel)
        self.measClear = self._btn("全部消す", "ghost"); r.addWidget(self.measClear); r.addStretch(1)
        self.undoBtn = self._btn("↶ 戻す  Ctrl+Z", "ghost"); r.addWidget(self.undoBtn)

        card, c = self._card(pl, "マーカー", "クリックでその位置へ")
        self.markTable = qt.QTableWidget(0, 7)
        self.markTable.setHorizontalHeaderLabels(["マーカー", "側", "位置", "外 Dmax", "外 Dmin", "外 Deq", "内 Deq"])
        self._tbl(self.markTable, 170); c.addWidget(self.markTable)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.delMarkButton = self._btn("選んだマーカーを消す"); r.addWidget(self.delMarkButton)
        self.measureButton = self._btn("2 つの間を測る"); self.measureButton.setToolTip("表で 2 つ選ぶ（Ctrl+クリック）"); r.addWidget(self.measureButton)
        self.neckButton = self._btn("ネック 0/5/10/15"); r.addWidget(self.neckButton)

        card, c = self._card(pl, "結果", "マーカーを置くと自動で更新")
        self.resultBox = qt.QTextBrowser(); self.resultBox.setMinimumHeight(200); c.addWidget(self.resultBox)
        nxt = self._btn("次へ: 計画 ›", "ghost"); nxt.connect("clicked()", lambda: self.showStep(2)); pl.addWidget(nxt, 0, qt.Qt.AlignRight)
        pl.addStretch(1)

        # ---- ページ 3: 計画（穴の場所を 3D で確かめ、仮想ステントを置く）
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10)
        sc = qt.QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(qt.QFrame.NoFrame); sc.setWidget(pg); sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{background:transparent} QScrollArea > QWidget > QWidget{background:transparent}"); self.stack.addWidget(sc)
        card, c = self._card(pl, "使い方")
        c.addWidget(self._lab("① 解離なら「真腔に沿わせる」→ 3D に真腔（水色）・偽腔（紫）を出して穴の場所を確かめる（緑の線が偽腔に入っていたら「真腔をクリックで直す」）"
                              "　② 断面で穴をクリックしてエントリーを置く　③ 「クリックで 近位端 → 遠位端」→ ストレッチ像を 2 回クリック（Enter 2 回でも）→ −/＋ で微調整"
                              "　④ フラップ・両端・径を選ぶ → 遠位端の SINE の目安を見る", "muted"))
        card, c = self._card(pl, "解離（真腔）", "緑の線 = 断面の真腔")
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.tlBtn = self._btn("真腔に沿わせる", None, "中心線の点から、造影された真腔を断面ごとにたどり（フラップで止まる）、グラフトを真腔の中心に置きます", True); r.addWidget(self.tlBtn, 1)
        self.tlShowBtn = self._btn("真腔を 3D に", None, "たどった真腔をうすい水色で 3D に出す", True); self.tlShowBtn.checked = True; r.addWidget(self.tlShowBtn)
        self.tlInfo = self._lab("中心線が真腔を通っていれば、ボタン 1 つで真腔をたどります（数秒）。", "muted"); self.tlInfo.setWordWrap(True); c.addWidget(self.tlInfo)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.tlFixBtn = self._btn("真腔をクリックで直す", None, "緑の線が偽腔に入っている断面で、本当の真腔の中をクリック → その前後をたどり直します（Ctrl+Z で戻す）", True); r.addWidget(self.tlFixBtn, 1)
        self.tlFixReset = self._btn("直しを消す", None, "真腔の手直しをすべて消して、自動でたどり直す"); r.addWidget(self.tlFixReset)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.flShowBtn = self._btn("偽腔を 3D に（紫）", None, "造影される偽腔を紫で 3D に出す。グラフト（白）が偽腔の入口側をふさいでいるかを見る", True); r.addWidget(self.flShowBtn, 1)
        self.flInfo = self._lab("", "muted"); self.flInfo.setWordWrap(True); c.addWidget(self.flInfo)
        card, c = self._card(pl, "エントリーと分枝", "緑 覆う・黄 端に近い・赤 覆わない")
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.entryBtn = self._btn("エントリーを置く", "primary", "押してから、断面（X）でエントリーの穴をクリック", True); r.addWidget(self.entryBtn, 1)
        self.entryDel = self._btn("選んだエントリーを消す"); r.addWidget(self.entryDel)
        self.covTable = qt.QTableWidget(0, 4); self.covTable.setHorizontalHeaderLabels(["名前", "位置", "計画", "術後"])
        self._tbl(self.covTable, 170); c.addWidget(self.covTable)

        card, c = self._card(pl, "仮想グラフト", "置きたい範囲にカバードステントを描く")
        self.tvPick = self._btn("クリックで 近位端 → 遠位端", "primary", "押してから、ストレッチ像（または 3D）を 近位端 → 遠位端 の順に 2 回クリック。Enter でも（今の断面を 近位端 → 遠位端）", True); c.addWidget(self.tvPick)
        self.tvRange = self._btn("範囲をドラッグで決める", None, "押してから、右のストレッチ像で 近位端 → 遠位端 までドラッグ", True); self.tvRange.setVisible(False)
        self.tvLen = qt.QLabel("—"); self.tvLen.setStyleSheet("font-size:17px; font-weight:bold; color:#ffffff"); c.addWidget(self.tvLen)
        self.tvLen.setToolTip("微調整: 近位端・遠位端の −/＋（1 mm・Shift を押しながらで 5 mm）、または ストレッチ像の白い線をつかんで動かす")
        g = qt.QGridLayout(); g.setHorizontalSpacing(8); g.setVerticalSpacing(6); c.addLayout(g)
        for j, t in enumerate(("", "位置", "径（実測 → グラフト）")): g.addWidget(self._lab(t, "colh"), 0, j)
        self.tvRows = {}
        for r, (key, name) in enumerate((("p", "近位端"), ("d", "遠位端")), 1):
            g.addWidget(self._lab(name, "h"), r, 0)
            pos = self._lab("—"); pos.setStyleSheet("font-size:13px; font-weight:bold; color:#ffffff"); g.addWidget(pos, r, 1)
            dia = self._lab("—"); g.addWidget(dia, r, 2)
            b = self._btn("ここに", None, f"今の断面の位置を{name}にする"); g.addWidget(b, r, 3)
            b.connect("clicked()", lambda key=key: self.onTvHere(key))
            for j, (t, dl) in enumerate((("−", -1.0), ("＋", 1.0))):
                nb = self._btn(t, None, f"{name}を 1 mm {'近位' if dl < 0 else '遠位'}へ（Shift で 5 mm）"); nb.setFixedWidth(34); g.addWidget(nb, r, 4 + j)
                nb.connect("clicked()", lambda key=key, dl=dl: self.onTvNudge(key, dl))
            self.tvRows[key] = (pos, dia)
        g.setColumnStretch(2, 1)
        self.tvRound = self._btn("近位端を 左鎖骨下直下の正円部に", None, "左鎖骨下動脈の口を過ぎて、断面が正円（短径/長径 ≥ 0.82）になる所を近位端にする")
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("オーバーサイズ", "muted"))
        self.osGrp, self.osBtns = self._seg(["0%", "5%", "10%", "15%", "20%"], r)
        self.osBtns[2].checked = True
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("フラップ", "muted"))
        self.flapGrp, self.flapBtns = self._seg(["慢性", "急性", "動かない"], r)
        self.flapBtns[0].checked = True
        self.flapBtns[0].setToolTip("フラップを押して真腔が広がる（径 ≒ 真腔の長径まで）。三日月の両端はガターとして残る。断面の緑の線 = 押されて動くフラップ")
        self.flapBtns[1].setToolTip("フラップがよく動く: 真腔の長径の円まで丸く広がる（グラフトの名目径が上限。偽腔側の大動脈の真ん中までは行かない）")
        self.flapBtns[2].setToolTip("フラップは動かない: グラフトは術前の真腔の中だけ（細い角はガター）")
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("両端", "muted"))
        self.endGrp, self.endBtns = self._seg(["押し広げる", "あるがまま"], r)
        self.endBtns[0].checked = True
        self.endBtns[0].setToolTip("端までフラップを押して広がる（この症例の術後 CT はこちらに近い）")
        self.endBtns[1].setToolTip("両端の 2 cm で、真腔のあるがままの形へなめらかに戻る（端はフラップを押し広げきらない）")
        c.addWidget(self.tvRound)
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("径を手で決める", "muted"))
        self.dpSpin = qt.QSpinBox(); self.ddSpin = qt.QSpinBox()
        for sp, tip in ((self.dpSpin, "近位の径（自動 = 実測 × オーバーサイズ）"), (self.ddSpin, "遠位の径（自動 = 実測 × オーバーサイズ）")):
            sp.setRange(0, 60); sp.setSpecialValueText("自動"); sp.setSuffix(" mm"); sp.setToolTip(tip); r.addWidget(sp)
        r.addStretch(1)
        self.tvSummary = self._lab("", "muted"); self.tvSummary.setWordWrap(True); c.addWidget(self.tvSummary)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.tvShowBtn = self._btn("3D に表示", None, "仮想グラフトを出す / 隠す", True); self.tvShowBtn.checked = True; r.addWidget(self.tvShowBtn)
        self.tvGoP = self._btn("近位端へ"); r.addWidget(self.tvGoP)
        self.tvGoD = self._btn("遠位端へ"); r.addWidget(self.tvGoD)
        r = qt.QHBoxLayout(); c.addLayout(r)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.planEditBtn = self._btn("断面でシミュレーションを直す", None, "白い輪の中をドラッグ = ずらす、輪のふちをドラッグ = 太さ。前後 2 cm がなめらかについてくる。Ctrl+Z で 1 つ戻す", True); r.addWidget(self.planEditBtn, 1)
        self.planAdjReset = self._btn("直しを消す", None, "手で直した分をすべて消して、計算どおりに戻す"); r.addWidget(self.planAdjReset)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.ovAorta = self._btn("大動脈を重ねる", None, "3D に大動脈（外周）をうすく重ねる", True); self.ovAorta.checked = True; r.addWidget(self.ovAorta)
        self.ovPost = self._btn("術後を重ねる", None, "術後 CT の実際のグラフト（金色）を 3D に重ねる", True); r.addWidget(self.ovPost)
        self.fit3d = self._btn("3D を合わせる", None, "3D をグラフトの範囲に合わせる（左前斜位。押すたびに 左前斜位 → 正面 → 左側面）"); r.addWidget(self.fit3d)
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("グラフトの軸", "muted"))
        self.axisGrp, self.axisBtns = self._seg(["中心線", "真腔に合わせる"], r)
        self.axisBtns[0].checked = True
        self.axisBtns[0].setToolTip("作った中心線をグラフトの軸にする（位置を変えたい時は中心線を直す）")
        self.axisBtns[1].setToolTip("断面ごとに、真腔をいちばん多く覆う位置へ軸を動かす")

        card, c = self._card(pl, "遠位端と SINE の目安")
        self.sineLab = qt.QLabel("—"); self.sineLab.setTextFormat(qt.Qt.RichText); self.sineLab.setWordWrap(True)
        self.sineLab.setStyleSheet("font-size:12px; color:#dfe6ee"); self.sineLab.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred)
        self.sineLab.setMinimumWidth(10); c.addWidget(self.sineLab)
        c.addWidget(self._lab("オーバーサイズ = グラフト ÷ 遠位端の真腔 − 1。ミスマッチ = 広がりの予測 ÷ 2 cm 先の真腔。"
                              "参考 = 単施設の報告の非 SINE 群 / SINE 群の平均（VEITH 2024 抄録、ミスマッチは術後の値）。"
                              "緑 = 非 SINE 群より小・黄 = 間・赤 = SINE 群以上。判定の基準ではありません。", "muted"))
        nxt = self._btn("次へ: 術後 ›", "ghost"); nxt.connect("clicked()", lambda: self.showStep(3)); pl.addWidget(nxt, 0, qt.Qt.AlignRight)
        pl.addStretch(1)
        usage = pl.itemAt(0).widget()
        gc = self.tvPick.parentWidget(); pl.removeWidget(gc); pl.insertWidget(0, gc)     # 仮想グラフト（範囲・フラップ・両端）をいちばん上に（スクロールせずに見える）
        # スクロールしなくてよいように、ふだん使わないものはしまう（機能は残す）
        sineNote = c.itemAt(c.count() - 1).widget()
        if sineNote is not None: self.sineLab.setToolTip(sineNote.text); sineNote.setVisible(False)
        for x in (usage, nxt, self.tvRound, self.tvSummary, self.entryBtn.parentWidget(), self.sineLab.parentWidget()): x.setVisible(False)
        for x in (self.dpSpin, self.tvShowBtn, self.axisBtns[0], self.ovAorta): self._hideRow(x)
        for lab_ in gc.findChildren(qt.QLabel):
            if lab_.text in ("位置", "径（実測 → グラフト）"): lab_.setVisible(False)
        gl = gc.layout()                                                      # 解離のボタンは 仮想グラフト の上の 1 行に
        tlCard = self.tlBtn.parentWidget(); row = qt.QHBoxLayout(); row.setSpacing(6)
        self.tlFixBtn.setText("真腔を直す"); self.flShowBtn.setText("偽腔を 3D に")
        for b in (self.tlBtn, self.tlFixBtn, self.flShowBtn): row.addWidget(b, 1)
        gl.insertLayout(1, row); tlCard.setVisible(False)
        gl.removeWidget(self.tvPick); gl.removeWidget(self.tvLen)            # 範囲のボタンと長さを 1 行に
        r0 = qt.QHBoxLayout(); r0.addWidget(self.tvPick, 1); r0.addWidget(self.tvLen); gl.insertLayout(2, r0)
        self.tvPick.setText("近位 → 遠位 をクリック")
        self.sineShort = qt.QLabel(""); self.sineShort.setTextFormat(qt.Qt.RichText); self.sineShort.setWordWrap(True)
        self.sineShort.setStyleSheet("font-size:12px; color:#dfe6ee"); self.sineShort.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred); self.sineShort.setMinimumWidth(10)
        gl.addWidget(self.sineShort)

        # ---- ページ 4: 術後（術後 CT を重ねて、計画との違いを見る）
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10)
        sc = qt.QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(qt.QFrame.NoFrame); sc.setWidget(pg); sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{background:transparent} QScrollArea > QWidget > QWidget{background:transparent}"); self.stack.addWidget(sc)
        card, c = self._card(pl, "使い方")
        c.addWidget(self._lab("① 「術後 CT を読み込む」でフォルダを選ぶ　② 「比べる」（背骨 → 大動脈の外形で重ね、薄い再構成から金属を拾う。1 分ほど）"
                              "　③ 表と断面（白 = 計画、金色の点 = 実際の金属）、3D で違いを見る。「実際と同じ範囲で描いて比べる」で形だけを比べられます", "muted"))
        card, c = self._card(pl, "術後 CT と比べる", "背骨 → 大動脈の外形で重ねて、実際のステントを測る")
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.postLoadBtn = self._btn("術後 CT を読み込む", None, "術後 CT の DICOM フォルダを選ぶ（院内 PC の中で読むだけ）"); r.addWidget(self.postLoadBtn, 1)
        self.postCmpBtn = self._btn("比べる", "primary", "重ね合わせ → 金属（ステント）を拾う → 計画とのずれ"); r.addWidget(self.postCmpBtn)
        self.postInfo = self._lab("まだ読み込んでいません", "muted"); self.postInfo.setWordWrap(True); c.addWidget(self.postInfo)
        g2 = qt.QGridLayout(); g2.setHorizontalSpacing(10); g2.setVerticalSpacing(2); c.addLayout(g2); g2.setColumnStretch(3, 1)
        for j, t in enumerate(("", "計画", "術後", "ずれ")): g2.addWidget(self._lab(t, "colh"), 0, j)
        for j in (1, 2, 3): g2.setColumnStretch(j, 1)
        self.cmpLab = {}
        for i, (key, name) in enumerate((("p", "近位端"), ("d", "遠位端"), ("len", "長さ"), ("dia", "径"), ("off", "中心のずれ")), 1):
            g2.addWidget(self._lab(name), i, 0)
            for j, col in enumerate(("plan", "post", "diff"), 1):
                w_ = self._lab("—"); w_.setStyleSheet("font-size:12px; font-weight:bold; color:#ffffff"); w_.setWordWrap(True)
                w_.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred); w_.setMinimumWidth(10); g2.addWidget(w_, i, j); self.cmpLab[(key, col)] = w_
        c.addWidget(self._lab("術前の真腔からの広がり（実際のステント ÷ 術前の真腔）", "h"))
        self.expLab = qt.QLabel("「比べる」のあとに出ます。"); self.expLab.setTextFormat(qt.Qt.RichText); self.expLab.setWordWrap(True)
        self.expLab.setStyleSheet("font-size:12px; color:#dfe6ee"); self.expLab.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred); self.expLab.setMinimumWidth(10)
        c.addWidget(self.expLab)
        self.expCsvBtn = self._btn("広がりの表を CSV に保存", None, "断面 2 mm ごとの 実際の長径・短径・面積・周径 と 術前の真腔 と その比（ドキュメント\\HeartView症例）"); c.addWidget(self.expCsvBtn)
        self.sameRangeBtn = self._btn("実際と同じ範囲で描いて比べる", None, "仮想グラフトを、術後の実際のグラフトと同じ範囲に置き直して、形（太さ・位置）だけを比べる。もう一度押すと元の計画に戻る", True); c.addWidget(self.sameRangeBtn)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.alignBtn = self._btn("重ね合わせを手で直す", "primary", "断面: 金色の点（実際の金属）をドラッグ → その高さの前後 3 cm をずらす。ストレッチ像: 上下にドラッグ → 全体を頭尾方向に。Ctrl+Z で 1 つ戻す", True); r.addWidget(self.alignBtn, 1)
        self.alignReset = self._btn("手直しを消す", None, "手で直した分をすべて消して、自動の重ね合わせに戻す"); r.addWidget(self.alignReset)
        c.addWidget(self._lab("断面で金色の点を内腔の壁などに合わせてドラッグ（その高さの前後 3 cm）、ストレッチ像で上下にドラッグすると全体が頭尾方向に動きます。離すと金属を拾い直し、表も更新します。", "muted"))
        self.postStretchBtn = self._btn("右のストレッチ像を術後にする", None, "右のストレッチ像（S2）を術後 CT にして、左と同じ向きで並べる", True); c.addWidget(self.postStretchBtn)
        c.addWidget(self._lab("ずれ: ＋ = 計画より遠位（足側）、− = 近位（頭側）。中心線に沿った長さ。術後 CT のスライス間隔の半分ほどの誤差があります。"
                              "径・中心のずれ = 計画と術後が重なる範囲での比較（術後は金属に楕円を当てはめた値。径 = 面積が同じ円の径、かっこ内は長径×短径）。断面: 白 = 計画、金色 = 術後、緑 = 術前の真腔。", "muted"))
        nxt = self._btn("次へ: 出力 ›", "ghost"); nxt.connect("clicked()", lambda: self.showStep(4)); pl.addWidget(nxt, 0, qt.Qt.AlignRight)
        pl.addStretch(1)
        pl.itemAt(0).widget().setVisible(False); nxt.setVisible(False)
        for lab_ in c.parentWidget().findChildren(qt.QLabel):
            tx = lab_.text
            if tx.startswith("断面で金色の点を"): self.alignBtn.setToolTip(tx); lab_.setVisible(False)
            elif tx.startswith("ずれ: ＋"): self.postCmpBtn.setToolTip(self.postCmpBtn.toolTip + "\n" + tx); lab_.setVisible(False)
        c.removeWidget(self.postStretchBtn); r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self.postStretchBtn, 1); r.addWidget(self.ovPost)
        self.postStretchBtn.setText("右を術後のストレッチ像に"); self.ovPost.setText("3D に金属"); self.ovPost.setVisible(True)

        # ---- ページ 5: 出力
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10); self.stack.addWidget(pg)
        card, c = self._card(pl, "出力", "この PC の ドキュメント\\HeartView症例 に保存")
        self.pdfBtn = self._btn("サイジングシート（PDF）を作る", "primary"); c.addWidget(self.pdfBtn)
        c.addWidget(self._lab("まとめ・マーカー表（外周/内腔）・手動計測・3D・ストレッチ像・各マーカーの断面を A4 に。PNG と CSV も同じフォルダに入ります。", "muted"))
        self.pngBtn = self._btn("高画質画像（PNG）だけ保存"); c.addWidget(self.pngBtn)
        self.secBtn = self._btn("今の断面だけ PNG で保存"); c.addWidget(self.secBtn)
        self.helixCsvBtn = self._btn("解離の形を CSV に（断面ごとの表 ＋ 一覧に 1 行）", None, "真腔をたどり、逆向きにもたどって食い違う所を「要確認」に。断面ごと（2 mm）の 真腔の面積・割合・重心のずれ・位置（時）・回転 と、"
                                     "1 行の要約（解離の範囲・回転・巻き・最大径・版・設定・手直しの回数）を ドキュメント\\HeartView症例\\解離らせん_一覧.csv に追記（解析用）"); c.addWidget(self.helixCsvBtn)
        self.sineCsvBtn = self._btn("SINE の目安を CSV に（一覧に 1 行追加）", None, "計画・治療長・遠位端の真腔・SINE の目安（と術後のずれ）を 1 行に。ドキュメント\\HeartView症例\\TEVAR_SINE_一覧.csv に症例ごとに追記（解析用）"); c.addWidget(self.sineCsvBtn)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.outLabel = self._lab("まだ保存していません", "muted"); self.outLabel.setWordWrap(True); r.addWidget(self.outLabel, 1)
        self.openBtn = self._btn("フォルダを開く"); self.openBtn.enabled = False; r.addWidget(self.openBtn)
        pl.addStretch(1)

        self.status = self._lab("", "muted"); self.status.setWordWrap(True); v.addWidget(self.status)

        # ---- つなぎ
        self.autoButton.connect("clicked()", self.onAuto)
        self.rightBtn.connect("clicked()", lambda: self._pick("大動脈→右腸骨"))
        self.leftBtn.connect("clicked()", lambda: self._pick("大動脈→左腸骨"))
        self.aortaBtn.connect("clicked()", lambda: self._pick("大動脈"))
        self.editButton.connect("toggled(bool)", self.onEdit)
        self.fixButton.connect("toggled(bool)", self.onFix)
        self.fixApply.connect("clicked()", lambda: self._busy(L.applyFixes, self._say))
        for b, v in zip(self.fixStepBtns, (5.0, 10.0, 20.0)): b.connect("clicked()", lambda v=v: (setattr(L, "fixStep", v), L._fixHud(True) if getattr(L, "_fixLab", None) else None))
        self.fixClear.connect("clicked()", L.clearFixes)
        L.onFixChanged = self._fixChanged
        self.addPtButton.connect("clicked()", self.onAddPoint)
        self.centerHereButton.connect("clicked()", lambda: self._recenter(False))
        self.centerAllButton.connect("clicked()", lambda: self._recenter(True))
        self.outerBtn.connect("clicked()", lambda: self._mode("outer"))
        self.lumenBtn.connect("clicked()", lambda: self._mode("lumen"))
        self.pinBtn.connect("clicked()", self.onPin)
        self.baseBtn.connect("clicked()", lambda: (L.setBaseline(), self.refreshLists(), self._say("ここを 0 mm（ベースライン）にしました。")))
        self.editContBtn.connect("toggled(bool)", self.onContEdit)
        self.wlBtn.connect("clicked()", self.onResetWL)
        for b in self.tplBtns: b.connect("clicked()", self.onTemplate)
        self.stepList.connect("itemClicked(QListWidgetItem*)", lambda it: self.gotoStep(self.stepList.row(it)))
        self.placeBtn.connect("clicked()", self.onPlace)
        self.skipBtn.connect("clicked()", lambda: self.gotoStep(self._step + 1))
        self.prevBtn.connect("clicked()", lambda: self.gotoStep(self._step - 1))
        self.unplaceBtn.connect("clicked()", self.onUnplace)
        self.measTable.connect("cellClicked(int,int)", lambda r, c: self._measAt(r) and L.jumpToMeasure(self._measAt(r)))
        for k in (qt.QKeySequence.Delete, qt.Qt.Key_Backspace):                 # 表で選んで Delete でも消せる
            sc = qt.QShortcut(qt.QKeySequence(k), self.measTable); sc.setContext(qt.Qt.WidgetShortcut); sc.connect("activated()", self.onMeasDel)
        self.measDel.connect("clicked()", self.onMeasDel)
        self.measClear.connect("clicked()", lambda: (L.clearMeasures(), self._say("計測を全部消しました。")))
        self.undoBtn.connect("clicked()", self.onUndo)
        self.markTable.connect("cellClicked(int,int)", lambda r, c: L.jumpToMarker(r))
        self.delMarkButton.connect("clicked()", self.onDelMark)
        self.measureButton.connect("clicked()", self.onMeasure)
        self.neckButton.connect("clicked()", lambda: self._showText(L.neckMeasurement()))
        self.pdfBtn.connect("clicked()", self.onPDF)
        for b in self.osBtns: b.connect("clicked()", self.onTvOversize)
        for b in self.flapBtns: b.connect("clicked()", self.onTvFlap)
        self.tvRound.connect("clicked()", self.onTvRound)
        self.tvRange.connect("toggled(bool)", self.onTvRange)
        self.tvPick.connect("toggled(bool)", self.onTvPick)
        self.flShowBtn.connect("toggled(bool)", self.onFLShow)
        for b in self.axisBtns: b.connect("clicked()", self.onTvAxis)
        for b in self.endBtns: b.connect("clicked()", self.onTvEnds)
        self.ovAorta.connect("toggled(bool)", lambda on: L.showOverlay3D("aorta", on))
        self.ovPost.connect("toggled(bool)", lambda on: L.showOverlay3D("post", on))
        self.fit3d.connect("clicked()", self.onFit3D)
        self.dpSpin.connect("valueChanged(int)", lambda v: self.onTvDiam()); self.ddSpin.connect("valueChanged(int)", lambda v: self.onTvDiam())
        self.tvShowBtn.connect("toggled(bool)", self.onTvShow)
        self.tvGoP.connect("clicked()", lambda: L.setPosition(L.planInit()["p"])); self.tvGoD.connect("clicked()", lambda: L.setPosition(L.planInit()["d"]))
        self.entryBtn.connect("toggled(bool)", self.onEntry); self.entryDel.connect("clicked()", self.onEntryDel)
        self.covTable.connect("cellClicked(int,int)", lambda r, c: L.setPosition(self._covRows[r]["s"]) if r < len(getattr(self, "_covRows", [])) else None)
        self.postLoadBtn.connect("clicked()", self.onPostLoad); self.postCmpBtn.connect("clicked()", self.onPostCompare)
        self.postStretchBtn.connect("toggled(bool)", self.onPostStretch)
        self.sameRangeBtn.connect("toggled(bool)", self.onSameRange)
        self.expCsvBtn.connect("clicked()", self.onExpCsv)
        self.alignBtn.connect("toggled(bool)", self.onAlignMode); self.alignReset.connect("clicked()", self.onAlignReset)
        self.planEditBtn.connect("toggled(bool)", self.onPlanEdit); self.planAdjReset.connect("clicked()", self.onPlanAdjReset)
        self.tlBtn.connect("toggled(bool)", self.onTL)
        self.tlFixBtn.connect("toggled(bool)", self.onTLFix); self.tlFixReset.connect("clicked()", self.onTLFixReset)
        self.tlShowBtn.connect("toggled(bool)", lambda on: (lambda m: m and m.GetDisplayNode().SetVisibility(on))(slicer.mrmlScene.GetFirstNodeByName("TEVAR 真腔")))
        self.pngBtn.connect("clicked()", self.onPNG)
        self.secBtn.connect("clicked()", self.onSecPNG)
        self.lenBtn.connect("toggled(bool)", self.onLengths)
        self.sineCsvBtn.connect("clicked()", self.onSineCsv)
        self.helixCsvBtn.connect("clicked()", self.onHelixCsv)
        self.openBtn.connect("clicked()", lambda: qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(self._lastDir)))
        L.onChanged = self.refreshReadout
        L.onListsChanged = self.refreshLists
        L.onPath = self._syncPathButtons
        L.onKey = self.onKey
        L.onStatus = self._say
        self._step = 0; self._lastDir = ""
        inter = slicer.app.applicationLogic().GetInteractionNode()
        self._interTag = inter.AddObserver(inter.InteractionModeChangedEvent, lambda c, e: self._syncTools())
        self._buildResearch()                                              # 6 研究（隠しタブ）
        self.showStep(0); self.onTemplate(); self._syncPathButtons()
