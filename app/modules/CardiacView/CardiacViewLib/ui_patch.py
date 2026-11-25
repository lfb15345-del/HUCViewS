# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: パッチ（塗って色分け・自動で探す・外す）・VSD
CardiacViewWidget の一部（PatchUIMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class PatchUIMixin:
    # ---- パッチ（塗って色分け）・胸骨ワイヤー
    def _brushMM(self):
        for mm, b in self.brushBtns.items():
            if b.checked: return mm
        return 4.0

    def _setBrush(self, mm):
        qt.QSettings().setValue("CardiacView/brushMM", float(mm)); self.logic.paintR = float(mm)

    def _onPaint(self, on):
        L = self.logic
        if on:
            if getattr(L, "vrOn", False) or getattr(L, "on4D", False): self._toSurfaces()
            if not L._paintTargets():
                self.paintButton.blockSignals(True); self.paintButton.checked = False; self.paintButton.blockSignals(False)
                self._status("塗れる面がありません（先に 3D の面を出してください）"); return
            self._status("パッチ: 準備中…")
            L.paintStart(self._brushMM())
            cb = self.layerChecks.get("パッチ")
            if cb is not None: cb.blockSignals(True); cb.checked = True; cb.blockSignals(False)
            self._status("パッチ: 面の上を左ドラッグで塗る（Ctrl＋ドラッグで消す）。何もない所のドラッグは回転。終わりは Esc かボタン")
        else:
            self._status(L.paintEnd())

    def _onPreCombo(self, i):
        self._preChosen = True                                                # 先生が選んだ（一覧を作り直す時は信号を止めているので、ここに来るのは手で選んだ時だけ）

    def _fillPreCombo(self):
        L = self.logic; cur = self._preVols[self.prePatchCombo.currentIndex] if 0 <= self.prePatchCombo.currentIndex < len(self._preVols) else None
        src = getattr(L, "sourceVolume", None)
        if getattr(self, "_preFor", None) is not src: self._preChosen = False; self._preFor = src       # 別の症例になったら、選び直し
        self.prePatchCombo.blockSignals(True); self.prePatchCombo.clear(); self.prePatchCombo.addItem("なし（術後だけで探す）"); self._preVols = [None]
        skip = {getattr(L, "sourceVolume", None), getattr(L, "workVolume", None)}
        for v in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"):
            if v.IsA("vtkMRMLLabelMapVolumeNode") or v.IsA("vtkMRMLVectorVolumeNode") or v in skip: continue
            nm = v.GetName()
            if nm.startswith(("CV ", "cv_")) or "_cv" in nm: continue
            self.prePatchCombo.addItem(nm); self._preVols.append(v)
        idx = self._preVols.index(cur) if (cur is not None and cur in self._preVols) else 0 if (cur is None and getattr(self, "_preChosen", False)) else next((i for i, v in enumerate(self._preVols) if v is not None and ("術前" in v.GetName() or "pre" in v.GetName().lower())), 0)
        self.prePatchCombo.currentIndex = idx; self.prePatchCombo.blockSignals(False)

    def _onAutoPatch(self):
        L = self.logic
        if getattr(L, "on4D", False): self._end4D()                          # 4D の途中は、出したパッチが動く心臓に隠れて見えない
        self._fillPreCombo(); i = self.prePatchCombo.currentIndex
        pre = self._preVols[i] if 0 <= i < len(self._preVols) else None
        if self.patchRemoveButton.checked: self.patchRemoveButton.checked = False
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: msg = L.autoPatch(pre, self._status)
        except Exception as e:
            import traceback; traceback.print_exc(); msg = f"パッチ: うまくいきませんでした（{e}）"
        finally: qt.QApplication.restoreOverrideCursor()
        try:
            cb = self.layerChecks.get("パッチ")
            if cb is not None and not cb.checked: cb.checked = True
        except Exception: pass
        self._status(msg)

    def _onPatchRemove(self, on):
        if not on: self._patchPickEnd(); return
        L = self.logic
        if getattr(L, "on4D", False): self._end4D()                          # 4D の途中はパッチが隠れていてクリックできない
        if L.layerModels.get(L.PATCH_KEY) is None: self._status("パッチがありません"); self.patchRemoveButton.checked = False; return
        n = slicer.mrmlScene.GetFirstNodeByName("cv_patch_pick")
        if n is None: n = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "cv_patch_pick")
        n.RemoveAllControlPoints(); n.CreateDefaultDisplayNodes()
        self._ppNode = n; self._ppObs = n.AddObserver(slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, self._patchPicked)
        sel = slicer.app.applicationLogic().GetSelectionNode(); sel.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode"); sel.SetActivePlaceNodeID(n.GetID())
        it = slicer.app.applicationLogic().GetInteractionNode(); it.SetPlaceModePersistence(1); it.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)
        self._status("違うパッチのかたまりをクリック（何個でも）。終わったらもう一度「違う所を外す」")

    def _patchPicked(self, caller, ev):
        n = caller
        if n.GetNumberOfControlPoints() == 0: return
        p = [0.0, 0.0, 0.0]; n.GetNthControlPointPositionWorld(n.GetNumberOfControlPoints() - 1, p)
        def run():
            try: ok = self.logic.patchRemoveAt(p)
            except Exception as e: ok = False; print("patch remove:", e)
            self._status("そのかたまりを外しました（「1つ戻す」で戻せます）" if ok else "近くにパッチがありません（パッチの上をクリック）")
            try: n.RemoveAllControlPoints()
            except Exception: pass
        qt.QTimer.singleShot(0, run)

    def _patchPickEnd(self):
        n = getattr(self, "_ppNode", None)
        if n is not None and getattr(self, "_ppObs", None) is not None:
            try: n.RemoveObserver(self._ppObs)
            except Exception: pass
        self._ppObs = None
        it = slicer.app.applicationLogic().GetInteractionNode(); it.SetPlaceModePersistence(0); it.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)

    def _onPatchSide(self, side):
        L = self.logic
        if L.layerModels.get(L.PATCH_KEY) is None: self._status("この症例にはパッチがありません"); return
        if not L.patchFace(side=side): self._status("パッチがありません"); return
        self.lockCheck.blockSignals(True); self.lockCheck.checked = True; self.lockCheck.blockSignals(False)
        self.cutCombo.blockSignals(True); self.cutCombo.currentIndex = 1; self.cutCombo.blockSignals(False)
        self.cutSlider.blockSignals(True); self.cutSlider.value = L.cutFrac * 100; self.cutSlider.blockSignals(False)
        nm = "左室" if side == "L" else "右室"
        self._status(f"パッチを{nm}側から見ています（{nm}の手前を切りました）。ホイールで切る位置。「この断面で固定」を外すと画面の正面から")

    def _onPatchFace(self):
        if self.paintButton.checked: self.paintButton.checked = False
        L = self.logic
        if not L.patchFace(): self._status("先に「パッチを塗る」で塗ってください"); return
        self.lockCheck.blockSignals(True); self.lockCheck.checked = True; self.lockCheck.blockSignals(False)
        self.cutCombo.blockSignals(True); self.cutCombo.currentIndex = 1; self.cutCombo.blockSignals(False)
        self.cutSlider.blockSignals(True); self.cutSlider.value = L.cutFrac * 100; self.cutSlider.blockSignals(False)
        self._status("パッチを正面に向けて、手前を切りました。ホイールで切る位置。「この断面で固定」を外すと元の切り方へ")

    def onVSD(self):
        # 心筋の切り口を塗り、内腔は空けておく（血液は出さない）
        self._toSurfaces()
        for k, b in getattr(self, "sceneButtons", {}).items(): b.setChecked(k == "heart")
        self.logic.capBlood = False; self.logic.capWall = True
        self._showOnly(("心臓壁", "心筋", "人工物・石灰化", "パッチ"))
        self.logic.setCapOpacity(self.capSlider.value / 100.0)
        self.logic.setView("A", self.fovSlider.value)
        self._applyCut()
