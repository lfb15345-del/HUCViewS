# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 読み込み・3D を作る・保存・大動脈サイジングへ
CardiacViewWidget の一部（CaseUIMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class CaseUIMixin:
    # ---------------------------------------------------------------- slots
    def onLoad(self):
        path = qt.QFileDialog.getOpenFileName(None, "CT を開く", "", "Volumes (*.nrrd *.nii *.nii.gz *.mha);;All (*)")
        if not path: return
        node = slicer.util.loadVolume(path)
        if node: self.volumeSelector.setCurrentNode(node)

    def onLoadDicom(self):
        d = qt.QFileDialog.getExistingDirectory(None, "DICOM フォルダ（1シリーズ）を選ぶ")
        if not d: return
        self._status("DICOM を読み込み中…"); slicer.app.processEvents()
        node = self.logic.loadDicomFolder(d)
        if node: self.volumeSelector.setCurrentNode(node); self._status(f"読み込みました: {node.GetName()}　→ ① を押してください")
        else: self._status("CT 画像が見つかりませんでした")

    def onQuick(self):
        vol = self.volumeSelector.currentNode()
        if not vol: self._status("CT を選んでください"); return False
        try:
            vol, note = self.logic.resolveSource(vol)
            if note:
                print("[CardiacView 点検]", note)
                if not self.logic._isWorkVolume(vol): self.volumeSelector.setCurrentNode(vol)
        except Exception as e: print("[CardiacView 点検] 元の CT の読み替えに失敗:", e)
        try:
            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            specs = self._layerSpecs()
            rep = self.logic.autoPipeline(vol, specs, self.boneCheck.checked, self._status)
            try:                                             # ここから下は「見せ方の準備」。失敗しても 3D はできているので、作成の失敗にはしない（入口は失敗だと症例を保存しない）
                self.resSpin.value = self.logic.lastSpacing
                for row in self.layerRows:                   # 自動で決めた閾値を詳細設定にも反映
                    if row["name"].text == "血液・血管": row["lo"].value = int(self.logic.calib["blood_lo"])
                self.fillCheck.blockSignals(True); self.fillCheck.checked = True; self.fillCheck.blockSignals(False)
                self.logic.setCapOpacity(self.capSlider.value / 100.0)
                self.logic.updateInset()
                sc = str(qt.QSettings().value("CardiacView/scene", "heart") or "heart")
                self.onScene(sc if sc in self.sceneButtons else "heart", remember=False)   # 覚えた値が壊れていても心臓の表示から
            except Exception as e:
                import traceback; traceback.print_exc()
                rep += f"\n⚠ 表示の準備の一部に失敗しました（{e}）。上の「見たいもの」を押し直してください"
            try:
                self.logic.setScale(self.scaleCheck.checked)
                key = next((k for k, b in self.rmodeButtons.items() if b.checked), "zoom"); self.logic.setRightMode(key)
            except Exception as e: print("scale/mode:", e)
            try:
                self.logic.tunePerformance()                 # この PC の速さに合わせて自動で軽くする
                self.ssaoCheck.blockSignals(True); self.ssaoCheck.checked = self.logic._view().renderWindow().GetRenderers().GetFirstRenderer().GetUseSSAO(); self.ssaoCheck.blockSignals(False)
            except Exception as e: print("tune:", e)
            self._status(rep)
            return True
        except Exception as e:
            import traceback; traceback.print_exc()
            self._status(f"エラー: {e}")
            return False
        finally:
            qt.QApplication.restoreOverrideCursor()

    def onBuild(self):
        return self.onQuick()

    def _toSurfaces(self):
        """面の表示（色分け面・心筋の断面など）へ切り替える前に、VR と 4D を止める。
        VR が上に残ると、面の色分けも切り口も VR に隠れて「一部しか切れていない」ように見えるため"""
        L = self.logic
        try:
            if getattr(L, "on4D", False): self._end4D()
            if getattr(L, "vrOn", False): L.showVR(False)
            for b in (self.vrTissueButton, self.vrBloodButton): b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
            for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"):
                if d.GetVisibility(): d.SetVisibility(False)
            L._vrLabel()
        except Exception as e: print("toSurfaces:", e)

    def onAortaSizing(self):
        if hasattr(slicer.modules, "aortasizing"):                           # 新しい「大動脈サイジング」画面へ
            slicer.util.selectModule("AortaSizing"); return
        script = os.path.join(os.path.dirname(MODULE_DIR), "run_phase1.py")
        if not os.path.exists(script):
            self._status(f"run_phase1.py が見つかりません: {script}"); return
        self._status("大動脈サイジングを実行中…")
        exec(open(script, encoding="utf-8").read(), {"__name__": "__cardiacview_phase1__"})
        self._status("大動脈サイジング完了（CSV は slicer_input に出力）")

    def onSave(self):
        if getattr(self.logic, "on4D", False): self._end4D()                  # 4D 表示のまま保存すると、開いた時に面が隠れたままになる
        return self._onSave()

    def _onSave(self):
        hvL = None                                                           # アプリ画面では、入口（HeartView）が今の症例のファイルを覚えている
        if getattr(slicer, "heartviewAppMode", False):
            try: hvL = slicer.modules.heartview.widgetRepresentation().self().logic
            except Exception: hvL = None
        path = qt.QFileDialog.getSaveFileName(None, "シーンを保存", getattr(hvL, "casePath", None) or "", "Medical Reality Bundle (*.mrb)")
        if not path: return
        if not path.lower().endswith(".mrb"): path += ".mrb"
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self._status("保存しています…")
            if hvL is not None and hasattr(hvL, "_saveTo"):
                hvL._saveTo(path)                                            # 別の名前で書いてから入れ替える・失敗は例外・名前の制御文字を直す
            else:
                try:
                    import HeartView; HeartView.cleanSceneText()                   # 名前に混ざった制御文字（日本語の DICOM）で、保存したファイルが開けなくなるのを防ぐ
                except Exception as e: print("cleanSceneText:", e)
                if not slicer.util.saveScene(path) or not os.path.exists(path):   # 失敗しても例外は出ない（False が返る）
                    raise RuntimeError(f"保存できませんでした（{path}）。保存先に書き込めるか・空き容量があるかを確かめてください")
            self._status(f"保存: {path}")
        except Exception as e:
            import traceback; traceback.print_exc(); self._status(f"エラー: {e}")
        finally:
            qt.QApplication.restoreOverrideCursor()
