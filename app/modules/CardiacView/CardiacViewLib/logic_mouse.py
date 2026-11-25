# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: マウス・キー（3D と断面: 回転・拡大・ウィンドウ・移動・切る位置・削除）
CardiacViewLogic の一部（MouseMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class MouseMixin:
    # ---------------------------------------------------------------- マウス（Zio 風）
    def installMouse(self):
        """マウス操作（アプリ全体で 1 組）。どのロジックが作っても、届け先は今の画面のロジック。
        3D: 左右同時ドラッグ = VR のウィンドウ／ホイール = 切る位置／右ドラッグ = 選んだ機能
        断面（2D）: 右ドラッグ = 選んだ機能（拡大・ウィンドウ・移動・切る位置＝スライス送り）"""
        lm = slicer.app.layoutManager()
        it = self._view().interactor()
        reg = getattr(slicer, "_cvMouse", None)
        if reg and reg.get("it") is it and reg.get("v") == 4: return
        if reg:
            for i, t in reg.get("tags", []):
                try: i.RemoveObserver(t)
                except Exception: pass
        tags = []; E = vtk.vtkCommand
        def add(itr, ev, name, *a):
            def cb(c, e, name=name, a=a):
                L = _cvCur()
                if L is None or not hasattr(L, name): return
                try: getattr(L, name)(c, *a)
                except Exception: import traceback; traceback.print_exc()
            tags.append((itr, itr.AddObserver(ev, cb, 2.0)))
        add(it, E.LeftButtonPressEvent, "_mPress", "L"); add(it, E.RightButtonPressEvent, "_mPress", "R")
        add(it, E.LeftButtonReleaseEvent, "_mRelease", "L"); add(it, E.RightButtonReleaseEvent, "_mRelease", "R")
        add(it, E.MouseMoveEvent, "_mMove")
        add(it, E.MiddleButtonPressEvent, "_mMid", True); add(it, E.MiddleButtonReleaseEvent, "_mMid", False)
        add(it, E.MouseWheelForwardEvent, "_mWheel", +1); add(it, E.MouseWheelBackwardEvent, "_mWheel", -1)
        for nm in ("Red", "Yellow", "Green"):
            try: sit = lm.sliceWidget(nm).sliceView().interactor()
            except Exception: continue
            add(sit, E.RightButtonPressEvent, "_sPress", nm); add(sit, E.MouseMoveEvent, "_sMove"); add(sit, E.RightButtonReleaseEvent, "_sRelease")
            add(sit, E.MouseWheelForwardEvent, "_sWheel", nm, +1); add(sit, E.MouseWheelBackwardEvent, "_sWheel", nm, -1)
            add(sit, E.LeftButtonPressEvent, "_dbl", nm)
            add(sit, E.KeyPressEvent, "_sKey", nm)
            add(sit, E.KeyPressEvent, "_delKey", nm)
        add(it, E.LeftButtonPressEvent, "_dbl", "3D")
        add(it, E.KeyPressEvent, "_delKey", "3D")
        slicer._cvMouse = dict(it=it, tags=tags, v=4)

    def _mMid(self, it, down):
        if down: self._vrFast(True)
        else: self._vrSettle()

    def _flash(self, msg):
        """3D 画面の上に一言だけ出す（2 秒）"""
        try:
            self._setUL("3_flash", msg)
            t = getattr(self, "_flashTimer", None)
            if t is None:
                t = self._flashTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(2200)
                t.connect("timeout()", lambda: self._setUL("3_flash", ""))
            t.start()
        except Exception: pass

    def _mine(self):
        if _cvCur() is not self: return False
        try: return slicer.util.selectedModule() in ("CardiacView", "HeartView")
        except Exception: return True

    def _mAbort(self, it):
        for i, t in (getattr(slicer, "_cvMouse", None) or {}).get("tags", []):
            if i is it:
                try: it.GetCommand(t).SetAbortFlag(1)
                except Exception: pass

    def _winGet(self):
        return self._win4D() if getattr(self, "on4D", False) else getattr(self, "vrWin", None)

    def _winSet(self, win0, dx, dy):
        """横 = 幅、縦 = 中心。4D は HU で直接、色分け VR は 0〜255 の目盛り（1 = 約 2.7 HU）"""
        c0, w0 = win0
        if getattr(self, "on4D", False): self.set4DWindow(center=c0 - dy * 1.5, width=w0 + dx * 2.0)
        else: self.setVRWindow(center=c0 - dy * 0.4, width=w0 + dx * 0.6)

    def _mPress(self, it, b):
        if not self._mine(): return
        if not hasattr(self, "_btn"): self._btn = {"L": False, "R": False}; self._wl = None
        if b == "L" and getattr(self, "paintOn", False) and not it.GetShiftKey():   # パッチを塗る（面の上を押した時だけ。何もない所はいつもの回転）
            try:
                if self._paintPress(it): self._mAbort(it); return
            except Exception:
                import traceback; traceback.print_exc(); self._painting = False
        self._vrFast(True)
        self._btn[b] = True
        mode = getattr(self, "rmode", "zoom")
        inter = slicer.app.applicationLogic().GetInteractionNode()
        placing = inter.GetCurrentInteractionMode() == inter.Place
        if b == "R" and mode == "window" and not (getattr(self, "vrOn", False) or getattr(self, "on4D", False)):
            self._flash("ウィンドウは VR か断面で使えます"); mode = "zoom"          # 面の表示にはウィンドウが無い → いつもの拡大
        if b == "R" and mode == "cut" and self.cutAxis is None and not placing:
            self.setCut("VIEW", 0.0); self._syncCutUI()                          # まだ切っていなければ「正面から」で切り始める
        if b == "R" and not self._btn["L"] and mode != "zoom" and not placing:          # 右ドラッグの機能（ボタンで切替）
            cam = self._camera()
            self._rdrag = (mode, it.GetEventPosition(), (cam.GetFocalPoint(), cam.GetPosition()), self._winGet(), getattr(self, "cutFrac", 0.5))
            self._mAbort(it); return
        if self._btn["L"] and self._btn["R"] and (getattr(self, "vrOn", False) or getattr(self, "on4D", False)) and self._mine():
            self._wl = (it.GetEventPosition(), self._winGet())
            self._mAbort(it)

    def _mRelease(self, it, b):
        if not self._mine(): return
        if not hasattr(self, "_btn"): self._btn = {"L": False, "R": False}; self._wl = None
        self._btn[b] = False
        if b == "L" and getattr(self, "_painting", False):
            self._paintRelease(); self._mAbort(it); return
        if b == "R" and getattr(self, "_rdrag", None) is not None:
            self._rdrag = None; self._mAbort(it); self._vrSettle(); return
        if not (self._btn["L"] or self._btn["R"]): self._vrSettle()
        if self._wl is not None:
            if not (self._btn["L"] or self._btn["R"]): self._wl = None
            if b == "R": self._mAbort(it)

    def _mMove(self, it):
        if getattr(self, "_painting", False) and self._mine():
            try: self._paintMove(it)
            except Exception:
                import traceback; traceback.print_exc(); self._painting = False
            self._mAbort(it); return
        rd = getattr(self, "_rdrag", None)
        if rd is not None and self._mine():
            mode, (x0, y0), cam0, win0, frac0 = rd; x, y = it.GetEventPosition()
            if mode == "window" and win0 is not None and (getattr(self, "vrOn", False) or getattr(self, "on4D", False)):
                self._winSet(win0, x - x0, y - y0)
            elif mode == "pan":
                self._pan(x0, y0, x, y, cam0)
            elif mode == "cut" and self.cutAxis is not None:
                lo, hi = self._visibleBounds(); span = float(np.linalg.norm(hi - lo))
                f = float(np.clip(frac0 + (y - y0) * 0.25 / max(span, 1.0), 0.0, 1.0))
                self.setCut(self.cutAxis, f)
                try:
                    sl = slicer.modules.cardiacview.widgetRepresentation().self().cutSlider
                    sl.blockSignals(True); sl.value = f * 100; sl.blockSignals(False)
                except Exception: pass
            self._view().scheduleRender(); self._mAbort(it); return
        if getattr(self, "_wl", None) is None or not self._mine(): return
        (x0, y0), win0 = self._wl; x, y = it.GetEventPosition()
        if win0 is not None: self._winSet(win0, x - x0, y - y0)
        self._view().scheduleRender(); self._mAbort(it)

    def _syncCutUI(self):
        try:
            w = slicer.modules.cardiacview.widgetRepresentation().self()
            idx = next((i for i, (_, a) in enumerate(CUT_MODES) if a == self.cutAxis), None)
            if self.cutAxis == "LOCK": idx = 1
            if idx is not None: w.cutCombo.blockSignals(True); w.cutCombo.setCurrentIndex(idx); w.cutCombo.blockSignals(False)
            w.cutSlider.blockSignals(True); w.cutSlider.value = getattr(self, "cutFrac", 0.5) * 100; w.cutSlider.blockSignals(False)
            w.lockCheck.blockSignals(True); w.lockCheck.checked = (self.cutAxis == "LOCK"); w.lockCheck.blockSignals(False)   # 固定中は必ずチェックを見せる（外せば画面の正面に戻る）
        except Exception: pass

    # ---- 断面（2D）の右ドラッグ: DICOM ビューアと同じ感覚
    def _sPress(self, it, nm):
        if not self._mine(): return
        mode = getattr(self, "rmode", "zoom")
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if mode == "zoom" or inter.GetCurrentInteractionMode() == inter.Place: return
        sw = slicer.app.layoutManager().sliceWidget(nm); sn = sw.mrmlSliceNode()
        cn = sw.sliceLogic().GetSliceCompositeNode(); vol = slicer.mrmlScene.GetNodeByID(cn.GetBackgroundVolumeID() or "")
        dn = vol.GetDisplayNode() if vol is not None else None
        wl = (dn.GetWindow(), dn.GetLevel()) if dn is not None and hasattr(dn, "GetWindow") else None
        isCut = (nm == "Red" and getattr(self, "layoutKind", "") == "cut" and self.cutAxis is not None)
        self._sdrag = dict(nm=nm, mode=mode, p0=it.GetEventPosition(), last=it.GetEventPosition(), wl=wl, dn=dn,
                           M0=slicer.util.arrayFromVTKMatrix(sn.GetSliceToRAS()), X0=slicer.util.arrayFromVTKMatrix(sn.GetXYToRAS()),
                           off0=sn.GetSliceOffset(), isCut=isCut)
        self._mAbort(it)

    def _sMove(self, it):
        d = getattr(self, "_sdrag", None)
        if d is None: return
        sw = slicer.app.layoutManager().sliceWidget(d["nm"]); sn = sw.mrmlSliceNode()
        (x0, y0), (x, y) = d["p0"], it.GetEventPosition()
        if d["mode"] == "window" and d["wl"] is not None:
            d["dn"].SetAutoWindowLevel(False)
            d["dn"].SetWindowLevel(max(1.0, d["wl"][0] + (x - x0) * 2.0), d["wl"][1] - (y - y0) * 2.0)   # 横 = 幅、縦 = 中心
        elif d["mode"] == "pan":
            X = d["X0"]; a = X @ np.array([x0, y0, 0, 1.0]); b = X @ np.array([x, y, 0, 1.0])
            M = d["M0"].copy(); M[:3, 3] += (a - b)[:3]
            vm = vtk.vtkMatrix4x4()
            for r in range(4):
                for c in range(4): vm.SetElement(r, c, float(M[r, c]))
            sn.GetSliceToRAS().DeepCopy(vm); sn.UpdateMatrices()
        elif d["mode"] == "cut":
            if d["isCut"]:                                                       # 3D の切断面を表示している断面 → 切る位置そのものを動かす
                dy = y - d["last"][1]
                if dy: self.nudgeCut(dy * 0.5); self._syncCutUI()
            else: sn.SetSliceOffset(d["off0"] + (y - y0) * 0.5)                   # ふつうの断面 → スライス送り（0.5 mm / ピクセル）
        d["last"] = (x, y)
        self._mAbort(it)

    def _delKey(self, it, nm):
        """Delete / BackSpace = 計測を 1 つ丸ごと消す（心臓・大動脈どちらの画面でも）。
        マウスを乗せている計測 → それ。描いている途中 → それ。どれでもなければ最後に触った計測"""
        if (it.GetKeySym() or "") == "Escape" and getattr(self, "paintOn", False):   # Esc = パッチを塗り終わる
            try: slicer.modules.cardiacview.widgetRepresentation().self().paintButton.checked = False
            except Exception: self.paintEnd()
            return
        if (it.GetKeySym() or "") not in ("Delete", "BackSpace"): return
        cands = [n for n in slicer.util.getNodesByClass("vtkMRMLMarkupsNode")
                 if n.GetAttribute("CV.measure") or n.GetAttribute("SA.measure")]
        if not cands: return
        target = None
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place:
            pid = slicer.app.applicationLogic().GetSelectionNode().GetActivePlaceNodeID()
            target = next((n for n in cands if n.GetID() == pid), None)
            inter.SetCurrentInteractionMode(inter.ViewTransform)
        if target is None:
            for n in cands:
                d = n.GetDisplayNode()
                try:
                    if d is not None and d.GetActiveComponentType() != d.ComponentNone: target = n; break
                except Exception: pass
        if target is None: target = max(cands, key=lambda n: n.GetMTime())
        name = target.GetName()
        sa = None
        if target.GetAttribute("SA.measure"):
            try: sa = slicer.modules.aortasizing.widgetRepresentation().self().logic
            except Exception: sa = None
        if sa is not None and hasattr(sa, "deleteMeasure"): sa.deleteMeasure(target)
        else: slicer.mrmlScene.RemoveNode(target)
        self.rulers = [n for n in getattr(self, "rulers", []) if slicer.mrmlScene.IsNodePresent(n)]
        self._flash(f"消しました：{name}")
        try:
            for i, t in (getattr(slicer, "_cvMouse", None) or {}).get("tags", []):
                if i is it:
                    try: it.GetCommand(t).SetAbortFlag(1)
                    except Exception: pass
        except Exception: pass

    def _sKey(self, it, nm):
        """4 画面: マウスを乗せた断面で [ ] = 線を 1° 回す（Shift で 5°）"""
        if not self._mine() or getattr(self, "layoutKind", "") != "four": return
        k = it.GetKeySym() or ""
        if k in ("bracketleft", "bracketright", "braceleft", "braceright"):
            self.rotateMPR(nm, (5.0 if it.GetShiftKey() else 1.0) * (1 if k in ("bracketleft", "braceleft") else -1)); self._mAbort(it)

    def _dbl(self, it, nm):
        if not self._mine() or it.GetRepeatCount() < 1: return
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place: return
        qt.QTimer.singleShot(0, lambda: self._toggleMaximize(nm)); self._mAbort(it)

    def _sWheel(self, it, nm, d):
        """3D の切断面を映している断面（3D＋切断面の左）では、ホイール = 切る位置（3D と一緒に動く。別の所へ飛ばない）"""
        if not self._mine() or it.GetControlKey(): return
        if nm == "Red" and getattr(self, "layoutKind", "") == "cut" and self.cutAxis is not None:
            self.nudgeCut(d * (5.0 if it.GetShiftKey() else 1.0)); self._syncCutUI(); self._mAbort(it)

    def _sRelease(self, it):
        if getattr(self, "_sdrag", None) is not None:
            self._sdrag = None; self._mAbort(it)

    def _mWheel(self, it, d):
        if not self._mine(): return
        self._vrFast(True); self._vrSettle()
        if it.GetControlKey() or self.cutAxis is None: return
        step = 5.0 if it.GetShiftKey() else 1.0                       # ホイール 1 目盛 = 1mm、Shift で 5mm
        frac = self.nudgeCut(d * step)
        try:
            sl = slicer.modules.cardiacview.widgetRepresentation().self().cutSlider
            if frac is not None: sl.blockSignals(True); sl.value = frac * 100; sl.blockSignals(False)
        except Exception: pass
        self._mAbort(it)
