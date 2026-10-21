# -*- coding: utf-8 -*-
"""大動脈サイジング: 手術のイメージ（教育用）の画面。AortaSizingWidget の一部（GraftUIMixin）。
「6 研究」のタブにカードを 1 つ置く。中身の計算は logic_graft.py（GraftMixin）。"""
from .common import *


class GraftUIMixin:
    def _buildGraft(self, pl):
        card, c = self._card(pl, "手術のイメージ（人工血管・ステント・フェルト）", "教育用")
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("細かい画像", "muted"))
        self.gHires = qt.QComboBox(); r.addWidget(self.gHires, 1)
        self.gHires.setToolTip("人工血管のしわ（スキャロップ）を探す画像。0.3〜0.5 mm の再構成画像（冠状断・弓部にそった斜位の矢状断など）を選ぶ。なしでも形だけで判定する")
        self.gRefresh = self._btn("↻", None, "画像の一覧を読み直す"); r.addWidget(self.gRefresh)
        self.gAutoBtn = self._btn("自動で色分け", "primary", "人工弁のリング・正円で太さ一定・フェルトの輪・ステント（金属）・太さの段差、"
                                  "細かい画像があれば人工血管のしわから、人工血管（クリーム色）・ステントグラフトの布（青白）・フェルト（黄土色）・頸部分枝・フラップ（薄ピンク）を色分けする")
        c.addWidget(self.gAutoBtn)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.gFromBtn = self._btn("ここから", None, "ストレッチ像のカーソルの位置を「ここから」にする"); r.addWidget(self.gFromBtn)
        self.gToBtn = self._btn("ここまで", None, "ストレッチ像のカーソルの位置を「ここまで」にする"); r.addWidget(self.gToBtn)
        self.gRangeLab = self._lab("—", "muted"); r.addWidget(self.gRangeLab, 1)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.gAddBtn = self._btn("人工血管にする", None, "「ここから〜ここまで」を人工血管（クリーム色）にする"); r.addWidget(self.gAddBtn, 1)
        self.gDelBtn = self._btn("人工血管から外す", None, "「ここから〜ここまで」を人工血管から外す"); r.addWidget(self.gDelBtn, 1)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.gTrBtn = self._btn("頸部分枝をたどる（オプション）", None, "MPR か 3D で、たどりたい頸部の動脈の先のほうをクリック → 大動脈からそこまで、造影された内腔の中だけを通って"
                                "その血管を描く（1 本ずつ。何本でも。もう一度押すと終わり）", True)
        r.addWidget(self.gTrBtn, 1)
        self.gBrBtn = self._btn("枝の吻合部をクリック", None, "MPR か 3D で、たどった枝の吻合部をクリック → 起始部からそこまでを人工血管（クリーム色）にする（もう一度押すと終わり）", True)
        r.addWidget(self.gBrBtn, 1)
        r = qt.QHBoxLayout(); c.addLayout(r); r.addStretch(1)
        self.gUndoBtn = self._btn("1 つ戻す", None, "手で直したのを 1 つ戻す"); r.addWidget(self.gUndoBtn)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.gShowBtn = self._btn("3D に出す", None, "手術のイメージを出す／元の血管に戻す", True); self.gShowBtn.checked = True; r.addWidget(self.gShowBtn, 1)
        self.gClearBtn = self._btn("消す", None, "手術のイメージを消して元の血管に戻す"); r.addWidget(self.gClearBtn)
        self.gLab = qt.QLabel("—"); self.gLab.setWordWrap(True); self.gLab.setStyleSheet("font-size:12px; color:#dfe6ee")
        self.gLab.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred); self.gLab.setMinimumWidth(10); c.addWidget(self.gLab)
        c.addWidget(self._lab("クリーム色 = 人工血管・青白 = ステントグラフトの布・黄土色 = フェルト・薄ピンク = フラップ・赤 = 自分の血管。"
                              "CT を加工して作った手術のイメージ（教育・説明用）で、診断には使いません。", "muted"))
        self._gFrom = self._gTo = None; self._gVols = [None]; self._gPickObs = None
        self.gRefresh.connect("clicked()", self._gFill); self.gAutoBtn.connect("clicked()", self.onGraftAuto)
        self.gFromBtn.connect("clicked()", lambda: self._gSet(0)); self.gToBtn.connect("clicked()", lambda: self._gSet(1))
        self.gAddBtn.connect("clicked()", lambda: self.onGraftEdit(True)); self.gDelBtn.connect("clicked()", lambda: self.onGraftEdit(False))
        self.gBrBtn.connect("toggled(bool)", lambda on: self.onGraftBranchPick(on, "anast")); self.gUndoBtn.connect("clicked()", self.onGraftUndo)
        self.gTrBtn.connect("toggled(bool)", lambda on: self.onGraftBranchPick(on, "trace"))
        self.gShowBtn.connect("toggled(bool)", lambda on: self.logic.graftShow(on)); self.gClearBtn.connect("clicked()", self.onGraftClear)
        self._gFill()

    def _gFill(self):
        self.gHires.clear(); self.gHires.addItem("なし（形だけで判定）"); self._gVols = [None]; best = None
        L = self.logic; skip = (getattr(L, "vol", None), getattr(L, "straight", None))
        for v in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"):
            if v.IsA("vtkMRMLLabelMapVolumeNode") or v in skip or v.GetName().startswith(("SA ", "TEVAR ", "研究 ", "手術 ")): continue
            sp = v.GetSpacing(); self.gHires.addItem(f"{v.GetName()}（{min(sp):.2f}×{max(sp):.1f} mm）"); self._gVols.append(v)
            if min(sp) <= 0.5 and max(sp) <= 2.05 and (best is None or min(sp) < best[0]): best = (min(sp), len(self._gVols) - 1)
        if best is not None: self.gHires.setCurrentIndex(best[1])

    def _gSet(self, i):
        s = float(self.logic.curS)
        if i == 0: self._gFrom = s
        else: self._gTo = s
        f = "—" if self._gFrom is None else f"{self._gFrom:.0f} mm"; t = "—" if self._gTo is None else f"{self._gTo:.0f} mm"
        self.gRangeLab.setText(f"{f} 〜 {t}")

    def _gDone(self, out):
        if out is not None: self.gLab.setText(out or "人工血管は見つかりませんでした"); self.gShowBtn.blockSignals(True); self.gShowBtn.checked = True; self.gShowBtn.blockSignals(False)

    def onGraftAuto(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        i = self.gHires.currentIndex; hv = self._gVols[i] if 0 <= i < len(self._gVols) else None
        self._gDone(self._busy(lambda: L.graftAuto(self._say, hv)))

    def onGraftEdit(self, on):
        if self._gFrom is None or self._gTo is None: self._say("先に「ここから」「ここまで」を押してください（ストレッチ像のカーソルの位置）。"); return
        self._gDone(self._busy(lambda: self.logic.graftEdit(self._gFrom, self._gTo, on, self._say)))

    def onGraftUndo(self):
        self._gDone(self._busy(lambda: self.logic.graftUndo(self._say)))

    def onGraftClear(self):
        self.gBrBtn.checked = False; self.gTrBtn.checked = False; self.logic.graftClear(); self.gLab.setText("—"); self._say("手術のイメージを消しました。")

    def onGraftBranchPick(self, on, mode="anast"):
        btn = self.gTrBtn if mode == "trace" else self.gBrBtn; other = self.gBrBtn if mode == "trace" else self.gTrBtn
        if not on:
            if getattr(self, "_gPickMode", None) == mode: self._gPickEnd()
            return
        if not getattr(self.logic, "gState", None): self._say("先に「自動で色分け」を押してください。"); btn.checked = False; return
        if other.checked: other.blockSignals(True); other.checked = False; other.blockSignals(False); self._gPickEnd()
        self._gPickMode = mode
        n = slicer.mrmlScene.GetFirstNodeByName("手術 吻合部の点")
        if n is None: n = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "手術 吻合部の点")
        n.RemoveAllControlPoints(); n.CreateDefaultDisplayNodes()
        self._gPickNode = n; self._gPickObs = n.AddObserver(slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, self._gPicked)
        sel = slicer.app.applicationLogic().GetSelectionNode(); sel.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode"); sel.SetActivePlaceNodeID(n.GetID())
        it = slicer.app.applicationLogic().GetInteractionNode(); it.SetPlaceModePersistence(1); it.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)
        self._say("MPR か 3D で、たどりたい頸部の動脈の先のほうをクリックしてください（1 本ずつ。終わったらもう一度ボタン）。" if mode == "trace"
                  else "MPR か 3D で、たどった枝の吻合部をクリックしてください（何本でも。終わったらもう一度ボタン）。")

    def _gPicked(self, caller, ev):
        n = caller
        if n.GetNumberOfControlPoints() == 0: return
        p = [0.0, 0.0, 0.0]; n.GetNthControlPointPositionWorld(n.GetNumberOfControlPoints() - 1, p)
        def run():
            if getattr(self, "_gPickMode", "anast") == "trace":
                try:
                    out = self._busy(lambda: self.logic.graftTraceBranch(p, self._say))
                    if out: self.gLab.setText(self.logic.gSummary)
                except Exception as e: self._say(str(e))
                try: n.RemoveAllControlPoints()
                except Exception: pass
                return
            try:
                key, s = self.logic.graftBranchAt(p, self._say)
                nm = {"brachiocephalic trunk": "腕頭", "common carotid artery left": "左総頸", "subclavian artery left": "左鎖骨下",
                      "common carotid artery right": "右総頸", "subclavian artery right": "右鎖骨下"}.get(key, key)
                self._say(f"{nm}: 起始部から {s:.0f} mm を吻合部にしました（そこまで白）。"); self.gLab.setText(self.logic.gSummary)
            except Exception as e: self._say(str(e))
            try: n.RemoveAllControlPoints()
            except Exception: pass
        qt.QTimer.singleShot(0, run)

    def _gPickEnd(self):
        n = getattr(self, "_gPickNode", None)
        if n is not None and self._gPickObs is not None:
            try: n.RemoveObserver(self._gPickObs)
            except Exception: pass
        self._gPickObs = None
        it = slicer.app.applicationLogic().GetInteractionNode(); it.SetPlaceModePersistence(0); it.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)
