# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 表示の操作（4D の再生・層・切断・VR・補う・ふた・場面の切り替え）
CardiacViewWidget の一部（ViewUIMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class ViewUIMixin:
    def _sync4D(self):
        L = self.logic; n = L.n4D() if hasattr(L, "n4D") else 0
        self.box4D.setVisible(n >= 2)
        if n < 2: return
        self.phaseSlider.blockSignals(True); self.phaseSlider.maximum = n - 1; self.phaseSlider.value = max(0, L.phase4D()); self.phaseSlider.blockSignals(False)
        self._label4D()

    def _label4D(self):
        L = self.logic; i = max(0, L.phase4D()); n = L.n4D(); labs = getattr(L, "labels4D", []) or []
        lab = labs[i] if i < len(labs) and labs[i] else f"{i + 1}"
        self.phaseLabel.setText(f"{lab}  ({i + 1}/{n})")
        try:
            L._setUL("1_4d", f"<span style='color:#f5cd5f'><b>4D</b>　{lab}（{i + 1}/{n}）</span>" if getattr(L, "on4D", False) else "")
        except Exception: pass

    def _onLayerCheck(self, name, on):
        L = self.logic; L.setLayerVisible(name, on, user=True)
        if getattr(L, "on4D", False) and on and not any(k in L.STATIC_4D for k in L._namesFor(name)):
            self._status(f"4D 中は「{name}」の面は出しません（動く心臓と重なるため）。「4D を終了」で表示されます。骨・軟部組織・人工物は 4D でも一緒に出せます。")

    def _onPlay4D(self, on):
        L = self.logic
        if on:
            L.show4D(True); L.play4D(True, self.fpsSpin.value); self.play4DButton.setText("❚❚ 止める"); self._t4D.start()
            self._status("4D 再生中: 回す・切る・4画面はそのまま使えます。スライダーで 1 位相ずつ。")
        else:
            L.play4D(False); self.play4DButton.setText("▶ 再生"); self._t4D.stop(); self._sync4D()

    def _onPhase4D(self, v):
        L = self.logic
        if self.play4DButton.checked: self.play4DButton.checked = False
        L.show4D(True); L.set4DPhase(int(round(v))); self._label4D()

    def _onFps4D(self, v):
        qt.QSettings().setValue("CardiacView/fps4D", float(v))
        if self.play4DButton.checked: self.logic.play4D(True, v)

    def _tick4D(self):
        L = self.logic
        if not L.has4D(): self._t4D.stop(); return
        self.phaseSlider.blockSignals(True); self.phaseSlider.value = max(0, L.phase4D()); self.phaseSlider.blockSignals(False)
        self._label4D()

    def _end4D(self):
        if self.play4DButton.checked: self.play4DButton.checked = False
        self.logic.show4D(False); self._label4D()
        self._status("4D を終了しました（" + ("色分け VR" if getattr(self.logic, "vrOn", False) else "面") + " の表示に戻りました）")

    def _applyCut(self):
        axis = CUT_MODES[self.cutCombo.currentIndex][1]
        if self.logic.cutAxis == "LOCK" and axis == "VIEW":                # 固定中はスライダーで固定した面を動かす
            self.logic.setCut("LOCK", self.cutSlider.value / 100.0); return
        if self.lockCheck.checked:
            self.lockCheck.blockSignals(True); self.lockCheck.checked = False; self.lockCheck.blockSignals(False); self.logic._lockN = None
        self.logic.setCut(axis, self.cutSlider.value / 100.0)

    def _onLock(self, on):
        L = self.logic
        if on:
            if L.cutAxis is None:                                           # まだ切っていなければ「画面の正面から」で切ってから固定
                self.cutCombo.setCurrentIndex(1); L.setCut("VIEW", self.cutSlider.value / 100.0)
            ok = L.lockCut(True)
            if ok:
                self.cutSlider.blockSignals(True); self.cutSlider.value = L.cutFrac * 100; self.cutSlider.blockSignals(False)
                self._status("断面を固定しました。左ドラッグで回しても切り口はそのまま。ホイールで面を平行移動。")
            else:
                self.lockCheck.blockSignals(True); self.lockCheck.checked = False; self.lockCheck.blockSignals(False)
        else:
            L.lockCut(False); self._status("固定を外しました（切る面はまた画面の正面に合わせます）。")

    def _updateStepLabels(self):
        mm = self.stepSpin.value
        self.cutMinus.setText("◀"); self.cutPlus.setText("▶")
        self.cutMinus.setToolTip(f"{mm:g} mm 戻す"); self.cutPlus.setToolTip(f"{mm:g} mm 進める")

    def _onStepChanged(self, v):
        self._updateStepLabels()
        qt.QSettings().setValue("CardiacView/stepMM", float(v))   # 次回も同じ刻みで

    def _onVR(self, mode):
        btn, other = (self.vrTissueButton, self.vrBloodButton) if mode == "tissue" else (self.vrBloodButton, self.vrTissueButton)
        on = btn.checked
        if getattr(self.logic, "on4D", False): self._end4D()                 # 前は「VR を出す」時だけ 4D を終えていた → 4D の途中で VR を消すと、動く VR の上に面が重なり、4D を終えると消したはずの VR が戻った
        other.blockSignals(True); other.checked = False; other.blockSignals(False)
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.logic.showVR(on, mode if on else None)
            self._status("VR 表示中: 左右ボタン同時ドラッグでウィンドウ調整（横=幅、縦=中心）。ホイールで切る位置。" if on else "面の表示に戻しました")
        except Exception as e:
            import traceback; traceback.print_exc(); btn.checked = False; self._status(f"VR エラー: {e}")
        finally:
            qt.QApplication.restoreOverrideCursor()

    def _onSynthToggled(self, on):
        self.logic.showSynth = bool(on)
        if self.logic.layerModels.get("心臓壁") is not None: self.logic.colorWallEpiEndo()

    def _onFillToggled(self, on):
        L = self.logic
        if L.layerModels.get("心臓壁") is None: return
        L.wallFill = bool(on); self._toSurfaces()                             # 作り直した壁を見せる（VR・4D の途中だと隠れたまま）
        self._status("壁を作り直しています…（約5秒）"); slicer.app.processEvents()
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            L.rebuildWall()
            L._applyClipToModels(L.cutAxis is not None)
            if L.cutAxis is not None: L.setCut(L.cutAxis, getattr(L, "cutFrac", 0.5))
            L.setCapOpacity(self.capSlider.value / 100.0)
        except Exception as e:                                               # 前は、失敗すると「壁を作り直しています…」のまま止まっていた
            import traceback; traceback.print_exc(); self._status(f"エラー: 壁を作り直せませんでした（{e}）"); return
        finally:
            qt.QApplication.restoreOverrideCursor()
        self._status("壁の補完: " + ("ON（グレーが補った所）" if on else "OFF（CT 値だけの壁）"))

    def _onCapChanged(self, v):
        self.logic.setCapOpacity(v / 100.0)
        qt.QSettings().setValue("CardiacView/capOpacityV2", float(v))

    def _nudge(self, mm):
        frac = self.logic.nudgeCut(mm)
        if frac is not None:
            self.cutSlider.blockSignals(True); self.cutSlider.value = frac * 100; self.cutSlider.blockSignals(False)

    def _showOnly(self, names):
        for name, cb in self.layerChecks.items():
            on = name in names
            cb.blockSignals(True); cb.checked = on; cb.blockSignals(False)
            self.logic.setLayerVisible(name, on)

    SCENES = {"aorta": ("血管:大動脈系", "人工物", "石灰化", "胸骨ワイヤー", "パッチ"),
              "vessels": ("血管:", "人工物", "石灰化", "胸骨ワイヤー", "パッチ"),
              "body": ("血管:", "骨", "人工物", "石灰化", "胸骨ワイヤー", "パッチ")}

    def onScene(self, key, remember=True):
        """見たいものをワンクリックで: 心臓（四腔断面）/ 大動脈 / 血管すべて / 骨と血管"""
        L = self.logic
        for k, b in self.sceneButtons.items(): b.setChecked(k == key)
        if remember: qt.QSettings().setValue("CardiacView/scene", key)
        if getattr(L, "on4D", False): self._end4D()
        if not L.layerModels: return
        if getattr(L, "vrOn", False): L.showVR(False)
        for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"): d.SetVisibility(False)   # 残っている VR も必ず消す
        for b in (self.vrTissueButton, self.vrBloodButton): b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        try: L._vrLabel()
        except Exception: pass
        if key == "heart":
            self.onFourChamber() if L._findChambers() is not None else self.onVSD()
            try: L.updateInset()
            except Exception: pass
            return
        L.capBlood = False
        if L.cutAxis == "LOCK" or self.lockCheck.checked:
            self.lockCheck.blockSignals(True); self.lockCheck.checked = False; self.lockCheck.blockSignals(False); L._lockN = None
        self.cutCombo.blockSignals(True); self.cutCombo.currentIndex = 0; self.cutCombo.blockSignals(False)
        L.setCut(None, getattr(L, "cutFrac", 0.5))                      # 切らずに全体
        want = self.SCENES[key]
        shown = []
        for k in list(L.layerModels.keys()):
            on = any(k == w or (w.endswith(":") and k.startswith(w)) for w in want)
            L.setLayerVisible(k, on)
            if on: shown.append(k)
        if key == "aorta" and "血管:大動脈系" not in L.layerModels:
            self._status("大動脈のモデルがありません（AI ラベルに大動脈がない撮影範囲です）")
        groups = {"血液・血管": any(k.startswith("血管") for k in shown), "骨": "骨" in shown, "人工物・石灰化": any(k in shown for k in ("人工物", "石灰化", "胸骨ワイヤー")), "パッチ": "パッチ" in shown}
        for name, cb in self.layerChecks.items():
            cb.blockSignals(True); cb.checked = bool(groups.get(name, False)); cb.blockSignals(False)
        L.setView("A", self.fovSlider.value)
        try: L.updateInset()
        except Exception: pass
        if key == "aorta": self._status("大動脈を表示しています。径を測るときは「大動脈サイジング」を使ってください。")

    def onFourChamber(self):
        self.onVSD()
        frac = self.logic.fourChamber()
        if frac is not None:
            self.cutCombo.blockSignals(True); self.cutCombo.currentIndex = 1; self.cutCombo.blockSignals(False)
            self.cutSlider.blockSignals(True); self.cutSlider.value = frac * 100; self.cutSlider.blockSignals(False)
        else:
            self._status("心腔モデルがないため四腔断面を計算できません")

    def onLumen(self):
        self._toSurfaces()
        self.logic.capBlood = False
        self._showOnly(("心臓壁",))
        self.logic.setView("A", self.fovSlider.value)
        self._applyCut()

    def onHeartOnly(self):
        self._toSurfaces()
        self.logic.capBlood = False
        self._showOnly(("血液・血管", "人工物・石灰化", "パッチ"))
        self.logic.setView("A", self.fovSlider.value)
        self._applyCut()
