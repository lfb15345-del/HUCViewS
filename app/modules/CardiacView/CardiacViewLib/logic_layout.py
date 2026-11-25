# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 一般的なビューアの機能: スケール・右ドラッグの切り替え・画面の並び（1・2・4 画面）・MPR・計測
CardiacViewLogic の一部（LayoutMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class _MprMark:
    """4 画面の 3D に「3 断面が交わる点」の十字マーク（いつも手前に表示＝体の中でも見える）。アプリ全体で 1 つ"""
    COLS = {"Red": (0.95, 0.30, 0.20), "Yellow": (0.93, 0.84, 0.30), "Green": (0.43, 0.69, 0.29)}

    def __init__(self, view):
        old = getattr(slicer, "_cvMprMark", None)
        if old is not None:
            try: old.remove()
            except Exception: pass
        slicer._cvMprMark = self
        self.view = view; rw = view.renderWindow(); self.rw = rw
        main = rw.GetRenderers().GetFirstRenderer()
        n = rw.GetNumberOfLayers(); rw.SetNumberOfLayers(n + 1)
        self.ren = vtk.vtkRenderer(); self.ren.SetLayer(n); self.ren.SetInteractive(0); self.ren.SetActiveCamera(main.GetActiveCamera())
        rw.AddRenderer(self.ren)
        self.lines = {}
        for nm, col in self.COLS.items():
            src = vtk.vtkLineSource(); a = vtk.vtkActor(); m = vtk.vtkPolyDataMapper(); m.SetInputConnection(src.GetOutputPort()); a.SetMapper(m)
            pr = a.GetProperty(); pr.SetColor(*col); pr.SetLineWidth(5.0); pr.LightingOff(); pr.SetOpacity(1.0)
            self.ren.AddActor(a); self.lines[nm] = (src, a)
        self.ball = vtk.vtkSphereSource(); self.ball.SetThetaResolution(20); self.ball.SetPhiResolution(14)
        ba = vtk.vtkActor(); bm = vtk.vtkPolyDataMapper(); bm.SetInputConnection(self.ball.GetOutputPort()); ba.SetMapper(bm)
        ba.GetProperty().SetColor(1, 1, 1); ba.GetProperty().SetAmbient(0.6); self.ren.AddActor(ba); self.ballA = ba
        self.tags = []; self.on = False

    def remove(self):
        for o, t in self.tags:
            try: o.RemoveObserver(t)
            except Exception: pass
        self.tags = []
        try: self.rw.RemoveRenderer(self.ren)
        except Exception: pass

    def show(self, on):
        self.on = bool(on); self.ren.SetDraw(1 if on else 0)
        lm = slicer.app.layoutManager()
        if on and not self.tags:
            for nm in self.COLS:
                w = lm.sliceWidget(nm)
                if w is None: continue
                sn = w.mrmlSliceNode(); self.tags.append((sn, sn.AddObserver(vtk.vtkCommand.ModifiedEvent, lambda c, e: self.update())))
        if on: self.update()
        self.view.scheduleRender()

    def update(self):
        if not self.on: return
        lm = slicer.app.layoutManager(); N = {}; d = []
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            if w is None: return
            M = slicer.util.arrayFromVTKMatrix(w.mrmlSliceNode().GetSliceToRAS())
            n = M[:3, 2] / (np.linalg.norm(M[:3, 2]) + 1e-12); N[nm] = n; d.append(float(n @ M[:3, 3]))
        try: c = np.linalg.solve(np.array([N["Red"], N["Yellow"], N["Green"]]), np.array(d))
        except Exception: return
        Lg = _cvCur(); vb = Lg._visibleBounds() if Lg is not None and hasattr(Lg, "_visibleBounds") else None
        L = float(np.linalg.norm(np.array(vb[1]) - np.array(vb[0]))) * 0.10 if vb is not None else 25.0   # 体の大きさの 1 割
        L = float(np.clip(L, 15.0, 45.0))
        for nm in self.COLS:                                     # その断面に垂直な線（＝ほかの 2 断面が交わる線）をその断面の色で
            o = [k for k in self.COLS if k != nm]
            u = np.cross(N[o[0]], N[o[1]]); nu = np.linalg.norm(u)
            if nu < 1e-6: continue
            u /= nu; src, a = self.lines[nm]
            src.SetPoint1(*(c - u * L)); src.SetPoint2(*(c + u * L))
        self.ball.SetCenter(*c); self.ball.SetRadius(max(2.5, L * 0.12))
        self.view.scheduleRender()


class LayoutMixin:
    # ---------------------------------------------------------------- 一般的なビューアの機能: スケール・右ドラッグ切替・マルチビュー
    RMODES = [("zoom", "拡大"), ("window", "ウィンドウ"), ("pan", "移動"), ("cut", "切る位置")]

    def setScale(self, on=True):
        """3D を平行投影にして目盛りを出す（画面のどこでも同じ縮尺）。断面にも目盛り"""
        self.scaleOn = bool(on)
        vn = self._viewNode()
        vn.SetRenderMode(vn.Orthographic if on else vn.Perspective)
        vn.SetRulerType(vn.RulerTypeThin if on else vn.RulerTypeNone); vn.SetRulerColor(vn.RulerColorWhite)
        for sn in slicer.util.getNodesByClass("vtkMRMLSliceNode"):
            try: sn.SetRulerType(sn.RulerTypeThin if on else sn.RulerTypeNone); sn.SetRulerColor(sn.RulerColorWhite)
            except Exception: pass
        self._fitParallel(); self._view().forceRender()

    def _fitParallel(self, margin=1.08, recenter=False):
        """画面の縦横比を考えて、見えているもの全体を収める（細い画面でも横が切れない）。形の点を画面の向きに投影して測る"""
        vn = self._viewNode(); cam = self._camera().GetCamera()
        P = self._shownPoints()
        if P is None: return
        W, H = self._view().renderWindow().GetSize(); asp = (W / float(H)) if (W > 10 and H > 10) else 1.0
        fp = np.array(cam.GetFocalPoint()); p = np.array(cam.GetPosition()); dop = fp - p; dop = dop / (float(np.linalg.norm(dop)) or 1.0)
        up = np.array(cam.GetViewUp()); up = up - dop * np.dot(up, dop); up = up / (np.linalg.norm(up) or 1.0); rt = np.cross(dop, up)
        X = P - fp; u = X @ up; r = X @ rt
        if recenter:                                                           # 画面の真ん中へ（奥行き方向は動かさない）
            d = up * (u.max() + u.min()) / 2 + rt * (r.max() + r.min()) / 2; fp = fp + d; p = p + d
            cam.SetFocalPoint(*fp); cam.SetPosition(*p); u = u - (u.max() + u.min()) / 2; r = r - (r.max() + r.min()) / 2
        hu = float(np.max(np.abs(u))); hr = float(np.max(np.abs(r)))
        need = max(hu, hr / asp) * margin * (1.15 if getattr(self, "on4D", False) else 1.0)   # 4D は心臓のまわりも少し描くので余白を多めに
        if vn.GetRenderMode() == vn.Orthographic:
            cam.SetParallelScale(need)
        elif recenter:
            ang = math.radians(cam.GetViewAngle()); D = need / math.tan(ang / 2) + float(np.max(np.abs((P - fp) @ dop)))
            cam.SetPosition(*(fp - dop * D))
        try: self._view().renderWindow().GetRenderers().GetFirstRenderer().ResetCameraClippingRange()
        except Exception: pass
        self._lastSize = None

    def _shownPoints(self, maxPts=40000):
        """今 3D に出ている形の点（間引き）。隠した骨・軟部組織は入れない。VR・4D の時は心臓・血管"""
        from vtk.util.numpy_support import vtk_to_numpy
        vr = getattr(self, "vrOn", False) or getattr(self, "on4D", False); arrs = []
        heart = [k for k in self.layerModels if "心臓壁" in k] or [k for k in self.layerModels if not any(x in k for x in ("軟部", "骨", "人工物"))]
        for name, n in self.layerModels.items():                              # VR・4D は心臓のまわりだけを描くので、心臓の範囲で合わせる
            try:
                pd = n.GetPolyData() if n else None; d = n.GetDisplayNode() if n else None
                if pd is None or d is None or not pd.GetNumberOfPoints(): continue
                if (vr and name in heart) or (not vr and d.GetVisibility()): arrs.append(vtk_to_numpy(pd.GetPoints().GetData()))
            except Exception: pass
        if not arrs:
            vb = self._visibleBounds()
            if vb is None: return None
            lo, hi = vb; return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
        n = sum(len(a) for a in arrs); k = max(1, n // maxPts)
        return np.concatenate([a[::k] for a in arrs]).astype(float)

    def _shownBounds(self):
        """今 3D に出ているものの範囲（隠した骨・軟部組織は入れない。VR・4D の時は心臓・血管の範囲）"""
        B = []; vr = getattr(self, "vrOn", False) or getattr(self, "on4D", False)
        for name, n in self.layerModels.items():
            try:
                pd = n.GetPolyData() if n else None; d = n.GetDisplayNode() if n else None
                if pd is None or d is None or not pd.GetNumberOfPoints(): continue
                if d.GetVisibility() or (vr and not any(k in name for k in ("軟部", "骨", "人工物"))): B.append(pd.GetBounds())
            except Exception: pass
        if not B: return self._visibleBounds()
        A = np.array(B); return (A[:, 0::2].min(0), A[:, 1::2].max(0))

    def _setUL(self, key, text):
        """左上の表示（4D の位相・一言メッセージ）をまとめて出す"""
        d = self.__dict__.setdefault("_ulTexts", {}); d[key] = text or ""
        _hud().set("3d", "tl", "<br>".join(t for k, t in sorted(d.items()) if t))
        try: self._view().cornerAnnotation().SetText(2, "")
        except Exception: pass

    def _setUR(self, text):
        """右上の表示（ウィンドウの値）"""
        _hud().set("3d", "tr", (text or "").replace("\n", "<br>"))
        try: self._view().cornerAnnotation().SetText(3, ""); self._view().scheduleRender()
        except Exception: pass

    SLICE_JA = {"Red": "軸位", "Yellow": "矢状断", "Green": "冠状断"}

    def applyWL(self, w, l):
        """断面のウィンドウを決まった値に（いま断面に出ている CT すべて）"""
        lm = slicer.app.layoutManager(); done = set()
        vols = [getattr(self, "sourceVolume", None)]
        for nm in lm.sliceViewNames():
            try:
                cn = lm.sliceWidget(nm).mrmlSliceCompositeNode(); vols.append(slicer.mrmlScene.GetNodeByID(cn.GetBackgroundVolumeID() or ""))
            except Exception: pass
        for v in vols:
            d = v.GetDisplayNode() if v is not None else None
            if d is None or d.GetID() in done: continue
            d.SetAutoWindowLevel(False); d.SetWindowLevel(float(w), float(l)); done.add(d.GetID())
        self._mprWL = True

    def _applyChrome(self):
        """断面の上の Slicer のバー（細かい数字・ピン）を隠し、日本語の小さな表示に置き換える"""
        lm = slicer.app.layoutManager()
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            if w is not None:
                try: w.sliceController().setVisible(False)
                except Exception: pass
        try: lm.threeDWidget(0).threeDController().setVisible(False)
        except Exception: pass
        try:                                                                  # 4D の再生は左のパネルで操作するので、Slicer の再生バーは隠す
            for t in slicer.util.mainWindow().findChildren(qt.QToolBar):
                if t.objectName == "SequenceBrowserToolBar": t.hide()
        except Exception: pass
        self._hudUpdate()

    def _hudUpdate(self):
        h = _hud(); lm = slicer.app.layoutManager(); kind = getattr(self, "layoutKind", "3d")
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            vis = w is not None and kind in ("four", "cut") and w.isVisible()
            if not vis:
                for pos in ("tl", "L", "R", "T", "B"): h.set(nm, pos, None)
                continue
            try:
                M = w.mrmlSliceNode().GetSliceToRAS()
                x = np.array([M.GetElement(i, 0) for i in range(3)]); y = np.array([M.GetElement(i, 1) for i in range(3)])
                name = "切断面" if (kind == "cut" and nm == "Red") else self.SLICE_JA[nm]
                if kind == "four" and (np.abs(x).max() < 0.995 or np.abs(y).max() < 0.995): name += "（斜め）"
                wl = ""
                cn = w.mrmlSliceCompositeNode(); vol = slicer.mrmlScene.GetNodeByID(cn.GetBackgroundVolumeID() or "")
                d = vol.GetDisplayNode() if vol is not None else None
                if d is not None: wl = f"　<span style='color:#9aa3ad'>W {d.GetWindow():.0f} / L {d.GetLevel():.0f}</span>"
                slab = getattr(self, "slabMM", 0) or 0
                if slab: wl += f"　<span style='color:#9aa3ad'>MIP {slab:g} mm</span>"
                h.set(nm, "tl", f"<b>{name}</b>{wl}")
                let = lambda v: ("RL", "AP", "SI")[int(np.argmax(np.abs(v)))][0 if v[int(np.argmax(np.abs(v)))] > 0 else 1]
                h.set(nm, "R", let(x)); h.set(nm, "L", let(-x)); h.set(nm, "T", let(y)); h.set(nm, "B", let(-y))
            except Exception as e: print("hud:", e)
        h.placeAll()


    def _viewSizeWatch(self):
        """3D 画面の大きさが変わったら（画面割り・パネルの開閉・ウィンドウの大きさ）: 細い向きの見える範囲を保ち、全体図と文字を画面に合わせる"""
        try: ren = self._view().renderWindow().GetRenderers().GetFirstRenderer()
        except Exception: return
        old = getattr(slicer, "_cvSizeTag", None)
        if old is not None:
            if old[0] is ren and old[2] is self: return
            try: old[0].RemoveObserver(old[1])
            except Exception: pass
        self._lastSize = None
        slicer._cvSizeTag = (ren, ren.AddObserver("StartEvent", self._onViewStart), self)

    def _onViewStart(self, caller=None, ev=None):
        try:
            v = self._view(); W, H = v.renderWindow().GetSize()
            if W < 20 or H < 20: return
            last = getattr(self, "_lastSize", None)
            if last == (W, H): return
            self._lastSize = (W, H)
            if last is not None:
                a0 = min(1.0, last[0] / float(last[1])); a1 = min(1.0, W / float(H))
                if abs(a0 - a1) > 1e-3:                                           # 細くなったら引いて、太くなったら戻す（横が切れない）
                    cam = self._camera().GetCamera(); f = a0 / a1
                    if cam.GetParallelProjection(): cam.SetParallelScale(cam.GetParallelScale() * f)
                    else:
                        fp = np.array(cam.GetFocalPoint()); p = np.array(cam.GetPosition()); cam.SetPosition(*(fp + (p - fp) * f))
                    caller.ResetCameraClippingRange()
            self._layoutOverlay(W, H)
        except Exception as e: print("view size:", e)

    def _layoutOverlay(self, W, H):
        v = self._view()
        try: dpr = max(1.0, W / float(max(1, v.width)))
        except Exception: dpr = 1.0
        ins = getattr(self, "inset", None)
        if ins is not None and getattr(slicer, "_cvInset", None) is ins:          # 全体図はピクセルで決めた大きさ（画面が狭いと出さない）
            w = min(0.26 * W, 220 * dpr); h = w / 1.35
            if h > 0.34 * H: h = 0.34 * H; w = h * 1.35
            m = 6 * dpr
            ins.ren.SetViewport(m / W, m / H, (m + w) / W, (m + h) / H)
            small = W < 330 * dpr or H < 240 * dpr
            if small:
                if ins.ren.GetDraw(): ins.ren.SetDraw(0); ins._autoHidden = True
            elif getattr(ins, "_autoHidden", False):
                ins._autoHidden = False
                if getattr(self, "insetOn", True): ins.ren.SetDraw(1)
        try:
            ca = v.cornerAnnotation(); ca.SetMaximumFontSize(int(13 * dpr)); ca.SetMinimumFontSize(0)   # 大きい画面でも文字が大きくなりすぎない（狭い画面では自動で小さく）
            ca.SetLinearFontScaleFactor(5); ca.SetNonlinearFontScaleFactor(0.35)
        except Exception: pass

    def setRightMode(self, mode):
        self.rmode = mode
        self._modeLabel()

    def _modeLabel(self):
        try:
            ca = self._view().cornerAnnotation()
            ca.SetText(1, "")
            self._setUL("2_rmode", "")                                          # 今の機能は上のバーで分かるので画面には出さない（すっきり）
        except Exception: pass

    def _pan(self, x0, y0, x1, y1, cam0):
        ren = self._view().renderWindow().GetRenderers().GetFirstRenderer()
        fp, pos = np.array(cam0[0]), np.array(cam0[1])
        ren.SetWorldPoint(*fp, 1.0); ren.WorldToDisplay(); z = ren.GetDisplayPoint()[2]
        def w(x, y):
            ren.SetDisplayPoint(x, y, z); ren.DisplayToWorld(); p = ren.GetWorldPoint(); return np.array(p[:3]) / (p[3] or 1.0)
        d = w(x0, y0) - w(x1, y1)
        cam = self._camera(); cam.SetFocalPoint(*(fp + d)); cam.SetPosition(*(pos + d))

    def setLayout(self, kind):
        """kind: "3d" / "four"（3D ＋ 軸位・矢状断・冠状断の MPR）/ "cut"（3D ＋ 切っている面の断面）"""
        lm = slicer.app.layoutManager(); self.layoutKind = kind; self._maxPrev = None
        src = getattr(self, "sourceVolume", None)
        try:                                                                  # 大動脈サイジングの線・マウス操作が残っていたら引っ込める
            if hasattr(slicer.modules, "aortasizing"): slicer.modules.aortasizing.widgetRepresentation().self().logic.suspend()
        except Exception: pass
        for nm in ("Red", "Yellow", "Green"):                                 # 3D に断面の板は出さない。4 画面だけ位置の枠線を出す（線は断面どうしの交線表示にも必要）
            try: lm.sliceWidget(nm).mrmlSliceNode().SetSliceVisible(kind == "four")
            except Exception: pass
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if n.GetName().endswith("Volume Slice") and n.GetDisplayNode() is not None:
                try: n.GetDisplayNode().SetVisibility3D(False)
                except Exception: pass
        if kind == "3d":
            lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
            try:
                ch = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode"); ch.SetCrosshairMode(ch.NoCrosshair)   # 3D だけの時は十字を出さない
            except Exception: pass
            self.setObliqueHandles(getattr(self, "obliqueOn", True))
        elif kind == "four":
            ln = lm.layoutLogic().GetLayoutNode()
            if not ln.IsLayoutDescription(CV_LAYOUT_FOUR): ln.AddLayoutDescription(CV_LAYOUT_FOUR, CV_LAYOUT_FOUR_XML)
            lm.setLayout(CV_LAYOUT_FOUR)
            self._equalSplit(); qt.QTimer.singleShot(120, self._equalSplit)        # 画面の大きさが決まってからもう一度そろえる
        else:
            ln = lm.layoutLogic().GetLayoutNode()
            if not ln.IsLayoutDescription(CV_LAYOUT_CUT): ln.AddLayoutDescription(CV_LAYOUT_CUT, CV_LAYOUT_CUT_XML)
            lm.setLayout(CV_LAYOUT_CUT)
        if kind != "3d" and src is not None:
            slicer.util.setSliceViewerLayers(background=src, foreground=None, label=None, fit=False)
            d = src.GetDisplayNode()
            if d is not None and not getattr(self, "_mprWL", False):
                c = self._cal(); lo = float(c.get("fat", -80)) - 60; hi = float(c.get("blood", 350)) + 250
                d.SetAutoWindowLevel(False); d.SetWindowLevel(hi - lo, (hi + lo) / 2); self._mprWL = True
            if kind == "four": self.resetMPR(render=False); qt.QTimer.singleShot(150, lambda: self.resetMPR())   # 画面割りが決まってから大きさをそろえる
            self.setOutlines2D(getattr(self, "outlines2D", False))
            for nm in ("Red", "Yellow", "Green"):
                w = lm.sliceWidget(nm)
                if w is not None: w.sliceController().setVisible(False)
            self._sliceInteraction(kind)
        try:                                                                  # 4 画面の 3D に 3 断面の交点（今細かく見ている所）
            mk = getattr(slicer, "_cvMprMark", None)
            if kind == "four" and (mk is None or mk.view is not self._view()): mk = _MprMark(self._view())
            if mk is not None: mk.show(kind == "four")
        except Exception as e: print("mpr mark:", e)
        self.setScale(getattr(self, "scaleOn", True))
        if kind == "cut":
            if self.cutAxis is None: self.setCut("VIEW", getattr(self, "cutFrac", 0.5)); self._syncCutUI()
            self._syncCutSlice()
            try:
                w = lm.sliceWidget("Red"); sn = w.mrmlSliceNode(); sn.SetFieldOfView(*self._cutFov(), 1.0)
            except Exception: pass
        reg = getattr(slicer, "_cvMouse", None)
        if reg: reg["v"] = 0                                                  # 断面ビューが増えたので付け直す
        self.installMouse(); self._installPerfMon()
        self._viewSizeWatch()
        qt.QTimer.singleShot(250, lambda: (self._fitParallel(recenter=True), self._view().scheduleRender(), self._hudUpdate()))

    def _cutFov(self):
        lo, hi = self._visibleBounds() if self.bounds is not None else (np.zeros(3), np.ones(3) * 200)
        r = float(np.max(hi - lo)) * 1.05; return r, r

    def _sliceInteraction(self, kind):
        """断面をふつうの DICOM ビューアと同じ操作に戻す（大動脈サイジングで止めた操作もここで戻す）。
        ホイール = スライス送り / 左ドラッグ = ウィンドウ / 右ドラッグ = 上で選んだ機能 / 中ドラッグ = 移動 / Shift＋マウス = 3 断面をその点へ"""
        lm = slicer.app.layoutManager()
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            if w is None: continue
            sv = w.sliceView(); io = sv.interactorObserver()
            for act in (io.BrowseSlice, io.AdjustWindowLevelBackground, io.AdjustWindowLevelForeground):
                try: io.SetActionEnabled(act, True)
                except Exception: pass
            try:
                siw = sv.displayableManagerByClassName("vtkMRMLCrosshairDisplayableManager").GetSliceIntersectionWidget()
                for act in (siw.ActionBrowseSlice, siw.ActionTranslateSliceIntersection, siw.ActionRotateSliceIntersection, siw.ActionSetCrosshairPosition):
                    siw.SetActionEnabled(act, True)
            except Exception: pass
        for cn in slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode"):   # 断面どうしを連動させない（ホイールで全部が動かない）
            try: cn.SetLinkedControl(False); cn.SetHotLinkedControl(False)
            except Exception: pass
        try:
            ch = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode")
            ch.SetCrosshairMode(ch.ShowSmallBasic if kind == "four" else ch.NoCrosshair); ch.SetCrosshairBehavior(ch.OffsetJumpSlice)   # 十字は 4 画面だけ。Shift＋マウスで 3 断面をその点へ
        except Exception: pass
        self.setObliqueHandles(kind == "four" and getattr(self, "obliqueOn", True))

    def setObliqueHandles(self, on):
        """4 画面の色つきの線（ほかの断面との交線）を出し、ドラッグで位置・回転（斜め MPR）できるようにする"""
        self.obliqueOn = bool(on) if getattr(self, "layoutKind", "") == "four" else getattr(self, "obliqueOn", True)
        show = getattr(self, "layoutKind", "") == "four"
        for dn in slicer.util.getNodesByClass("vtkMRMLSliceDisplayNode"):
            for f, v in (("SetIntersectingSlicesVisibility", show), ("SetIntersectingSlicesInteractive", show and on),
                         ("SetIntersectingSlicesTranslationEnabled", show and on), ("SetIntersectingSlicesRotationEnabled", show and on)):
                try: getattr(dn, f)(bool(v))
                except Exception: pass
            try: dn.SetIntersectingSlicesInteractiveHandlesVisibilityMode(dn.AlwaysVisible if (show and on) else dn.NeverVisible)   # 線の端に回す丸・真ん中に動かす丸を常に出す
            except Exception as e: print("handles:", e)
            try: dn.SetIntersectingSlicesLineThicknessMode(1)
            except Exception: pass

    def resetMPR(self, render=True):
        """斜めにした断面を、軸位・矢状断・冠状断に戻す（いまの十字の位置・心臓の中心で）"""
        lm = slicer.app.layoutManager()
        c = self._sceneCenter()
        try:
            ch = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode"); p = [0.0, 0.0, 0.0]; ch.GetCrosshairRAS(p)
            if np.linalg.norm(np.array(p)) > 1e-3 and getattr(self, "_mprCentered", False): c = np.array(p)
        except Exception: pass
        self._mprCentered = True
        r = float(np.max(self._visibleBounds()[1] - self._visibleBounds()[0])) * 1.1 if self.bounds is not None else 250.0
        for nm, ori in (("Red", "Axial"), ("Yellow", "Sagittal"), ("Green", "Coronal")):
            w = lm.sliceWidget(nm)
            if w is None: continue
            sn = w.mrmlSliceNode(); sn.SetOrientation(ori); sn.JumpSliceByCentering(*c)
            dims = sn.GetDimensions(); asp = dims[1] / max(dims[0], 1)
            sn.SetFieldOfView(r, r * asp, sn.GetFieldOfView()[2])
        try: ch.SetCrosshairRAS(*c)
        except Exception: pass
        self.mprAngle = {}
        try: slicer.modules.cardiacview.widgetRepresentation().self().mprAngleLabel.setText("0°")
        except Exception: pass

    def setOutlines2D(self, on):
        """断面に 3D の面の切り口（輪郭線）を出すか。ふつうの MPR は出さない（CT だけ）"""
        self.outlines2D = bool(on)
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if n.GetName().startswith("CV ") and n.GetDisplayNode() is not None:
                n.GetDisplayNode().SetVisibility2D(bool(on))
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            d = n.GetDisplayNode()
            if d is not None: d.SetVisibility2D(bool(on))

    def _mprCenter(self):
        """3 断面が交わる点"""
        lm = slicer.app.layoutManager(); N = []; d = []
        for nm in ("Red", "Yellow", "Green"):
            M = slicer.util.arrayFromVTKMatrix(lm.sliceWidget(nm).mrmlSliceNode().GetSliceToRAS())
            n = M[:3, 2] / (np.linalg.norm(M[:3, 2]) + 1e-12); N.append(n); d.append(float(n @ M[:3, 3]))
        try: return np.linalg.solve(np.array(N), np.array(d))
        except Exception: return self._sceneCenter()

    def rotateMPR(self, view, deg):
        """view の断面の中で、ほかの 2 つの断面の線を deg 度回す（= 斜め MPR の微調整）。交点を中心に回す"""
        lm = slicer.app.layoutManager()
        if lm.sliceWidget(view) is None: return
        c = self._mprCenter()
        n = slicer.util.arrayFromVTKMatrix(lm.sliceWidget(view).mrmlSliceNode().GetSliceToRAS())[:3, 2]; n = n / (np.linalg.norm(n) + 1e-12)
        t = math.radians(deg); K = np.array([[0, -n[2], n[1]], [n[2], 0, -n[0]], [-n[1], n[0], 0]])
        R = np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)
        for nm in ("Red", "Yellow", "Green"):
            if nm == view: continue
            sn = lm.sliceWidget(nm).mrmlSliceNode(); M = slicer.util.arrayFromVTKMatrix(sn.GetSliceToRAS())
            M[:3, :3] = R @ M[:3, :3]; M[:3, 3] = c + R @ (M[:3, 3] - c)
            vm = sn.GetSliceToRAS()
            for r in range(3):
                for k in range(4): vm.SetElement(r, k, float(M[r, k]))
            sn.UpdateMatrices()
        self.mprAngle = getattr(self, "mprAngle", {}); self.mprAngle[view] = self.mprAngle.get(view, 0.0) + deg
        try:
            w = slicer.modules.cardiacview.widgetRepresentation().self()
            w.mprAngleLabel.setText("  ".join(f"{dict(Red='軸', Yellow='矢', Green='冠')[k]} {v:+.0f}°" for k, v in self.mprAngle.items() if abs(v) > 0.01) or "0°")
        except Exception: pass

    def setSlab(self, mm):
        """断面に厚み（最大値投影 MIP）。0 = なし"""
        self.slabMM = mm
        for nm in ("Red", "Yellow", "Green"):
            w = slicer.app.layoutManager().sliceWidget(nm)
            if w is None: continue
            sn = w.mrmlSliceNode()
            try:
                sn.SetSlabReconstructionEnabled(mm > 0)
                if mm > 0: sn.SetSlabReconstructionThickness(float(mm)); sn.SetSlabReconstructionType(vtk.VTK_IMAGE_SLAB_MAX)
            except Exception as e: print("slab:", e)

    def _equalSplit(self):
        """4 画面の仕切りを等分に（縦も横も半分ずつ）"""
        try:
            vp = slicer.app.layoutManager().viewport()
            for sp in vp.findChildren(qt.QSplitter):
                g = lambda a: a() if callable(a) else a
                n = int(g(sp.count))
                if n < 2: continue
                tot = int(g(sp.width) if g(sp.orientation) == qt.Qt.Horizontal else g(sp.height))
                sp.setSizes([max(1, tot // n)] * n)
        except Exception as e: print("equal split:", e)

    def _toggleMaximize(self, which):
        """ダブルクリック: その画面だけを大きく ⇔ 元の分割に戻す"""
        lm = slicer.app.layoutManager(); L = slicer.vtkMRMLLayoutNode
        prev = getattr(self, "_maxPrev", None)
        if prev is not None:
            self._maxPrev = None; lm.setLayout(prev)
            if prev == CV_LAYOUT_FOUR: self._equalSplit(); qt.QTimer.singleShot(120, self._equalSplit)
            return
        if getattr(self, "layoutKind", "3d") == "3d": return
        self._maxPrev = lm.layout
        lm.setLayout({"Red": L.SlicerLayoutOneUpRedSliceView, "Yellow": L.SlicerLayoutOneUpYellowSliceView,
                      "Green": L.SlicerLayoutOneUpGreenSliceView}.get(which, L.SlicerLayoutOneUp3DView))

    def _syncCutSlice(self):
        """3D で切っている面を、左（Red）の断面にそのまま出す（向きも画面と同じ）"""
        if getattr(self, "layoutKind", "3d") != "cut" or self.cutPlane is None or self.cutAxis is None: return
        w = slicer.app.layoutManager().sliceWidget("Red")
        if w is None: return
        c = [0.0, 0.0, 0.0]
        try: self.cutPlane.GetCenterWorld(c)
        except Exception: self.cutPlane.GetCenter(c)
        c = np.array(c)
        cam = self._camera().GetCamera()
        n = np.array(cam.GetViewPlaneNormal(), float) if self.cutAxis == "VIEW" else np.array(self.cutPlane.GetNormal(), float)   # LOCK は固定した面
        up = np.array(cam.GetViewUp(), float); up -= (up @ n) * n
        if np.linalg.norm(up) < 1e-6: up = np.array([0, 0, 1.0]) - n[2] * n
        up /= np.linalg.norm(up); x = np.cross(up, n)
        sn = w.mrmlSliceNode(); M = sn.GetSliceToRAS()
        for r in range(3): M.SetElement(r, 0, x[r]); M.SetElement(r, 1, up[r]); M.SetElement(r, 2, n[r]); M.SetElement(r, 3, c[r])
        sn.UpdateMatrices()

    MEASURES = [("line", "直線", "vtkMRMLMarkupsLineNode", "L"), ("poly", "連続点", "vtkMRMLMarkupsCurveNode", "P"),
                ("curve", "カーブ", "vtkMRMLMarkupsCurveNode", "C"), ("area", "面積", "vtkMRMLMarkupsClosedCurveNode", "A"),
                ("angle", "角度", "vtkMRMLMarkupsAngleNode", "Ang")]

    def startMeasure(self, kind="line"):
        """計測: 直線 / 連続点（折れ線）/ カーブ / 面積（閉曲線）/ 角度。3D（面・VR の上）でも断面でもクリックで置く"""
        self.rulers = [n for n in getattr(self, "rulers", []) if slicer.mrmlScene.IsNodePresent(n)]
        key, lab, cls, pre = next(m for m in self.MEASURES if m[0] == kind)
        used = [re.match(rf"{pre}(\d+)", n.GetName() or "") for n in self._measureNodes() if n.GetAttribute("CV.measure") == kind]
        num = 1 + max([int(m.group(1)) for m in used if m] or [0])                # 開き直した症例・消した後でも番号が重ならない
        n = slicer.mrmlScene.AddNewNodeByClass(cls, f"{pre}{num}")                 # 3D の文字は英数字だけ表示できる
        n.SetAttribute("CV.measure", kind)
        if kind == "poly": n.SetCurveTypeToLinear()
        if kind in ("line", "poly", "curve"):
            try: n.GetMeasurement("length").SetEnabled(True)
            except Exception: pass
        if kind == "angle":
            try: n.GetMeasurement("angle").SetEnabled(True)
            except Exception: pass
        if kind == "area":                                  # Slicer 標準の面積は 0 のままになるので、自前で計算して名前に出す
            try: n.GetMeasurement("area").SetEnabled(False); n.GetMeasurement("length").SetEnabled(True)
            except Exception: pass
            base = n.GetName()
            def upd(caller=None, ev=None, n=n, base=base):
                try:
                    P = slicer.util.arrayFromMarkupsCurvePoints(n, world=True)
                    if P is None or len(P) < 3: return
                    c = P.mean(0); _, _, vt = np.linalg.svd(P - c, full_matrices=False)
                    q = (P - c) @ vt[:2].T; x, y = q[:, 0], q[:, 1]
                    a = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))   # 当てはめた平面の上の面積（mm2）
                    nm = f"{base}: {a / 100.0:.2f} cm2"
                    if n.GetName() != nm: n.SetName(nm)
                except Exception as e: print("area:", e)
            for evn in (slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                        slicer.vtkMRMLMarkupsNode.PointRemovedEvent, slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent):
                n.AddObserver(evn, upd)
        d = n.GetDisplayNode()
        col = {"line": (1.0, 0.85, 0.2), "poly": (0.4, 1.0, 0.6), "curve": (0.4, 0.9, 1.0), "area": (1.0, 0.55, 0.9), "angle": (1.0, 0.7, 0.3)}[kind]
        d.SetSelectedColor(*col); d.SetColor(*col); d.SetActiveColor(1.0, 1.0, 1.0)
        d.SetTextScale(3.0); d.SetGlyphScale(1.4); d.SetLineThickness(0.3); d.SetPointLabelsVisibility(False)
        try: d.SetPropertiesLabelVisibility(True); d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.5)
        except Exception: pass
        self._put(n); self.rulers.append(n)
        sel = slicer.app.applicationLogic().GetSelectionNode()
        sel.SetReferenceActivePlaceNodeClassName(cls); sel.SetActivePlaceNodeID(n.GetID())
        inter = slicer.app.applicationLogic().GetInteractionNode()
        inter.SetPlaceModePersistence(1 if kind in ("poly", "curve", "area") else 0)   # 多点は右クリックで終了
        inter.SetCurrentInteractionMode(inter.Place)
        return n

    def startRuler(self):
        return self.startMeasure("line")

    def _measureNodes(self):
        """このビューアで置いた計測（印 CV.measure の付いた線・曲線・面積・角度）。シーンから探す（保存した症例を開いた後・ロジックを作り直した後も見つかる）"""
        return [n for n in slicer.util.getNodesByClass("vtkMRMLMarkupsNode") if n.GetAttribute("CV.measure")]

    def clearRulers(self):
        nodes = list(getattr(self, "rulers", []))
        nodes += [n for n in self._measureNodes() if n not in nodes]
        for n in nodes:
            if slicer.mrmlScene.IsNodePresent(n): slicer.mrmlScene.RemoveNode(n)
        self.rulers = []

    # ---------------------------------------------------------------- measure
    def placeMarkup(self, cls, name):
        node = slicer.mrmlScene.AddNewNodeByClass(cls, name)
        self._put(node)
        try: node.GetDisplayNode().SetPropertiesLabelVisibility(True)
        except Exception: pass
        slicer.modules.markups.logic().SetActiveList(node)
        slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)
