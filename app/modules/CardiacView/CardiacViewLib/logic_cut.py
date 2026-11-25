# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 切断（クリップ: 再計算なし・即時）・全体図（_Inset）・自由平面
CardiacViewLogic の一部（CutMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class _Inset:
    """3D 画面の左下に「全体図」（いつも正面から）を出し、今の切断面がどこを切っているかを示す。
    枠 = 切断面（オレンジ）、黄色い線 = 心臓・血管の表面と交わる所、矢印 = 今どちらから見ているか"""
    def __init__(self, view):
        self.view = view; rw = view.renderWindow(); self.rw = rw
        old = getattr(slicer, "_cvInset", None)                              # アプリ全体で 1 つだけ
        if old is not None and old is not self:
            try: old.remove()
            except Exception: pass
        slicer._cvInset = self
        n = rw.GetNumberOfLayers(); rw.SetNumberOfLayers(n + 1)
        self.ren = vtk.vtkRenderer(); self.ren.SetLayer(n); self.ren.SetInteractive(0)
        self.ren.SetViewport(0.006, 0.01, 0.25, 0.33); self.ren.SetBackground(0.10, 0.11, 0.14); self.ren.SetPreserveColorBuffer(0)
        self.ren.SetUseDepthPeeling(0)
        rw.AddRenderer(self.ren)
        self.body = vtk.vtkActor(); self.bodyMap = vtk.vtkPolyDataMapper(); self.body.SetMapper(self.bodyMap)
        self.bodyMap.SetScalarModeToUsePointData(); self.bodyMap.SetColorModeToDirectScalars()
        p = self.body.GetProperty(); p.SetAmbient(0.35); p.SetDiffuse(0.75); p.SetSpecular(0.2)
        self.plane = vtk.vtkPlaneSource(); self.planeA = vtk.vtkActor(); m = vtk.vtkPolyDataMapper(); m.SetInputConnection(self.plane.GetOutputPort())
        self.planeA.SetMapper(m); pp = self.planeA.GetProperty(); pp.SetColor(1.0, 0.62, 0.15); pp.SetOpacity(0.18); pp.LightingOff()
        self.frame = vtk.vtkActor(); fm = vtk.vtkPolyDataMapper(); fe = vtk.vtkFeatureEdges(); fe.SetInputConnection(self.plane.GetOutputPort())
        fe.BoundaryEdgesOn(); fe.FeatureEdgesOff(); fe.ManifoldEdgesOff(); fe.NonManifoldEdgesOff(); fe.ColoringOff()
        fm.SetInputConnection(fe.GetOutputPort()); self.frame.SetMapper(fm)
        fp = self.frame.GetProperty(); fp.SetColor(1.0, 0.62, 0.15); fp.SetLineWidth(2.5); fp.LightingOff()
        self.cutLine = vtk.vtkActor(); self.cutMap = vtk.vtkPolyDataMapper(); self.cutLine.SetMapper(self.cutMap)
        cp = self.cutLine.GetProperty(); cp.SetColor(1.0, 0.95, 0.3); cp.SetLineWidth(3.0); cp.LightingOff()
        self.cutMap.SetResolveCoincidentTopologyToPolygonOffset()
        self.arrow = vtk.vtkActor(); self.arrowSrc = vtk.vtkArrowSource(); self.arrowSrc.SetTipResolution(16); self.arrowSrc.SetShaftResolution(12)
        self.arrowTf = vtk.vtkTransform(); af = vtk.vtkTransformPolyDataFilter(); af.SetInputConnection(self.arrowSrc.GetOutputPort()); af.SetTransform(self.arrowTf)
        am = vtk.vtkPolyDataMapper(); am.SetInputConnection(af.GetOutputPort()); self.arrow.SetMapper(am); self.arrow.GetProperty().SetColor(0.35, 0.85, 1.0)
        self.txt = []
        for s, pos in (("R", (6, 0)), ("L", (-14, 0))):
            t = vtk.vtkTextActor(); t.SetInput(s); tp = t.GetTextProperty(); tp.SetFontSize(13); tp.SetBold(True); tp.SetColor(0.75, 0.78, 0.84)
            t.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport(); t.SetPosition(0.04 if s == "R" else 0.90, 0.88)
            self.ren.AddActor2D(t); self.txt.append(t)
        for a in (self.body, self.planeA, self.frame, self.cutLine, self.arrow): self.ren.AddActor(a)
        self.planeA.SetVisibility(False); self.frame.SetVisibility(False); self.cutLine.SetVisibility(False); self.arrow.SetVisibility(False)
        self.pd = None; self.center = np.zeros(3); self.R = 100.0
        self._camTag = None

    def remove(self):
        try: self.rw.RemoveRenderer(self.ren)
        except Exception: pass
        if self._camTag is not None:
            try: self._camObj.RemoveObserver(self._camTag)
            except Exception: pass

    def setVisible(self, on):
        self.ren.SetDraw(1 if on else 0); self.view.scheduleRender()

    @staticmethod
    def _small(n):
        """全体図用の小さい形（格子でまとめた間引き）。部屋の色（CV_room）があれば部屋ごとに分けて色を保つ。
        形が変わらない限り作り直さない（症例を開いた時に 1 回だけ）"""
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtkIdTypeArray
        pd = n.GetPolyData(); d = n.GetDisplayNode()
        cache = getattr(slicer, "_cvInsetCache", None)
        if cache is None: cache = slicer._cvInsetCache = {}
        key = (n.GetID(), pd.GetMTime(), tuple(round(x, 3) for x in d.GetColor()))
        if key in cache: return cache[key]
        parts = []
        room = pd.GetPointData().GetArray("CV_room"); rgb = pd.GetPointData().GetArray("CV_roomRGB")
        try:
            conn = vtk_to_numpy(pd.GetPolys().GetConnectivityArray()); off = vtk_to_numpy(pd.GetPolys().GetOffsetsArray())
            tri = conn.reshape(-1, 3) if (len(off) and np.all(np.diff(off) == 3)) else None
        except Exception: tri = None
        if room is not None and rgb is not None and tri is not None:
            R = vtk_to_numpy(room); C = vtk_to_numpy(rgb); cr = R[tri[:, 0]]
            for r in np.unique(cr):
                sub = tri[cr == r]
                if len(sub) < 50: continue
                ca = vtk.vtkCellArray()
                ca.SetData(numpy_to_vtkIdTypeArray(np.arange(0, 3 * len(sub) + 1, 3, dtype=np.int64), deep=True), numpy_to_vtkIdTypeArray(sub.ravel().astype(np.int64), deep=True))
                g = vtk.vtkPolyData(); g.SetPoints(pd.GetPoints()); g.SetPolys(ca)
                parts.append((g, [int(x) for x in np.median(C[R == r], axis=0)]))
        if not parts:
            g = vtk.vtkPolyData(); g.SetPoints(pd.GetPoints()); g.SetPolys(pd.GetPolys())         # 形だけ（色・法線の配列を外すと 10 倍速い）
            parts.append((g, [int(255 * x) for x in d.GetColor()]))
        out = []
        for g, c in parts:
            dec = vtk.vtkQuadricClustering(); dec.SetInputData(g)
            dec.SetNumberOfDivisions(64, 64, 64); dec.AutoAdjustNumberOfDivisionsOff(); dec.Update()
            nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(dec.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.NonManifoldTraversalOff(); nm.Update()
            q = vtk.vtkPolyData(); q.DeepCopy(nm.GetOutput())                      # 法線は部屋ごとに（まとめてから付けると継ぎ目が黒い線になる）
            if not q.GetNumberOfPoints(): continue
            col = vtk.vtkUnsignedCharArray(); col.SetNumberOfComponents(3); col.SetName("rgb"); col.SetNumberOfTuples(q.GetNumberOfPoints())
            for i in range(3): col.FillComponent(i, c[i])
            q.GetPointData().SetScalars(col); out.append(q)
        if len(cache) > 40: cache.clear()
        cache[key] = out
        return out

    def setModels(self, nodes):
        app = vtk.vtkAppendPolyData(); k = 0
        for n in nodes:
            pd = n.GetPolyData(); d = n.GetDisplayNode()
            if pd is None or pd.GetNumberOfPoints() == 0 or d is None: continue
            for q in self._small(n): app.AddInputData(q); k += 1
        if k == 0: return
        app.Update()
        self.pd = vtk.vtkPolyData(); self.pd.DeepCopy(app.GetOutput()); self.bodyMap.SetInputData(self.pd)
        b = self.pd.GetBounds(); lo = np.array(b[0::2]); hi = np.array(b[1::2])
        self.center = (lo + hi) / 2; self.R = float(np.linalg.norm(hi - lo) / 2)
        cam = self.ren.GetActiveCamera(); cam.ParallelProjectionOn()
        cam.SetFocalPoint(*self.center); cam.SetPosition(*(self.center + np.array([0, 1.0, 0]) * self.R * 4)); cam.SetViewUp(0, 0, 1)
        self.half = (hi - lo) / 2.0
        asp = 1.35                                    # 全体図の縦横比（だいたい）
        cam.SetParallelScale(float(max(self.half[2], self.half[0] / asp)) * 1.18); self.ren.ResetCameraClippingRange()
        self.view.scheduleRender()

    def setPlane(self, c, n):
        if self.pd is None: return
        n = np.array(n, float); n /= np.linalg.norm(n) + 1e-12; c = np.array(c, float)
        c = c - n * float((c - self.center) @ n) + n * float((c - self.center) @ n)     # 面上の点
        cc = self.center + n * float((c - self.center) @ n)                          # 体の中心に一番近い面上の点
        u = np.cross(n, [0, 0, 1.0]);
        if np.linalg.norm(u) < 1e-3: u = np.cross(n, [0, 1.0, 0])
        u /= np.linalg.norm(u); v = np.cross(n, u); h = float(np.max(self.half)) * 1.05
        self.plane.SetOrigin(*(cc - h * u - h * v)); self.plane.SetPoint1(*(cc + h * u - h * v)); self.plane.SetPoint2(*(cc - h * u + h * v)); self.plane.Update()
        pl = vtk.vtkPlane(); pl.SetOrigin(*cc); pl.SetNormal(*n)
        cut = vtk.vtkCutter(); cut.SetInputData(self.pd); cut.SetCutFunction(pl); cut.Update()
        self.cutMap.SetInputData(cut.GetOutput()); self.cutMap.ScalarVisibilityOff()
        for a in (self.planeA, self.frame, self.cutLine): a.SetVisibility(True)
        self.view.scheduleRender()

    def hidePlane(self):
        for a in (self.planeA, self.frame, self.cutLine): a.SetVisibility(False)
        self.view.scheduleRender()

    def setViewDir(self, dop):
        """今の 3D 画面の視線の向き（カメラ → 焦点）を矢印で示す（全体図の外から中心へ）"""
        if self.pd is None: return
        d = np.array(dop, float); d /= np.linalg.norm(d) + 1e-12
        start = self.center - d * float(np.max(self.half)) * 1.05; L = float(np.max(self.half)) * 0.42
        x = d; y = np.cross(x, [0, 0, 1.0])
        if np.linalg.norm(y) < 1e-3: y = np.cross(x, [0, 1.0, 0])
        y /= np.linalg.norm(y); z = np.cross(x, y)
        m = vtk.vtkMatrix4x4()
        for r in range(3):
            m.SetElement(r, 0, x[r] * L); m.SetElement(r, 1, y[r] * L); m.SetElement(r, 2, z[r] * L); m.SetElement(r, 3, start[r])
        self.arrowTf.SetMatrix(m); self.arrow.SetVisibility(True); self.view.scheduleRender()

    def followCamera(self, camNode):
        cam = camNode.GetCamera(); self._camObj = cam
        if self._camTag is not None:
            try: cam.RemoveObserver(self._camTag)
            except Exception: pass
        def upd(c=None, e=None):
            fp = np.array(cam.GetFocalPoint()); pos = np.array(cam.GetPosition()); self.setViewDir(fp - pos)
        self._camTag = cam.AddObserver(vtk.vtkCommand.ModifiedEvent, upd); upd()


class CutMixin:
    # ---------------------------------------------------------------- cut (clip node: 再計算なし・即時)
    def _clipNode(self):
        if self.clip is None or not slicer.mrmlScene.IsNodePresent(self.clip):
            self.clip = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLClipNode", "CV clip")
            self.clip.SetClipType(self.clip.ClipIntersection)
            try: self.clip.SetClippingMethod(self.clip.WholeCells)   # Straight だと頂点色（内膜/外膜）が消える
            except Exception: pass
            self._put(self.clip)
        return self.clip

    def _applyClipToModels(self, enable):
        clip = self._clipNode()
        for n in self.layerModels.values():
            d = n.GetDisplayNode() if n else None
            if not d: continue
            if enable:
                d.SetAndObserveClipNodeID(clip.GetID()); d.SetAttribute("CV.clipWant", "1")
                isVessel = n.GetName().startswith("CV 血管")
                isWall = n.GetName() in ("CV 心臓壁", "CV 心筋")
                cap = (isWall and getattr(self, "capWall", True)) or (isVessel and getattr(self, "capBlood", False))
                if n.GetName() == "CV 心臓壁" and self.layerModels.get("心筋") is not None:
                    cap = False
                if n.GetName() == "CV 心筋":
                    cap = False   # Slicer 標準の蓋は穴（内腔）まで塗ってしまうので、自前の断面（updateMyoCap）を使う
                d.SetAttribute("CV.cap", "1" if cap else "0")
                try:
                    d.SetClippingCapSurface(bool(cap)); d.SetClippingCapOpacity(getattr(self, "capOpacity", 0.5) if isWall else 1.0); d.SetClippingOutline(False)
                    if n.GetName() == "CV 心臓壁": d.SetClippingCapColorHSVOffset(-0.04, 0.30, -0.25)
                    if n.GetName() == "CV 心筋": d.SetClippingCapColorHSVOffset(0.0, 0.0, 0.0)   # 切り口は濃いアンバー（切った心筋）
                except Exception: pass
            else:
                d.SetAttribute("CV.clipWant", "0"); d.SetClipping(False)
        lay = set(n for n in self.layerModels.values() if n is not None)
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):             # ほかの画面の面（大動脈サイジング・研究・読み込んだ面）も、見えていれば一緒に切る
            if n in lay: continue
            d = n.GetDisplayNode(); nm = n.GetName()
            if d is None or nm == "CV 心筋断面" or nm.endswith("Volume Slice"): continue
            if enable:
                if d.GetVisibility():
                    d.SetAndObserveClipNodeID(clip.GetID()); d.SetClipping(True); d.SetAttribute("CV.clipOther", "1")
            elif d.GetAttribute("CV.clipOther") == "1":
                d.SetClipping(False); d.SetAttribute("CV.clipOther", "0")
        self._installVRClip()
        try: self._clipSync()
        except Exception as e: print("clip sync:", e)
        self._view().scheduleRender()

    def setCut(self, axis, frac):
        """axis: None=切らない, 0=x(左右), 1=y(前後), 2=z(上下). frac: 0..1"""
        self.cutAxis = axis; self.cutFrac = frac
        if axis is None:
            self._clearCuts(); return
        vb = self._visibleBounds() if hasattr(self, "_visibleBounds") else self.bounds
        if vb is None: return
        lo, hi = vb
        if axis in ("VIEW", "LOCK"):
            # 画面の正面から: 法線＝カメラの視線方向。0% で何も切らず、100% で全部切る
            # LOCK: 決めた断面を体に固定（回しても切り口はそのまま）
            if axis == "LOCK" and getattr(self, "_lockN", None) is not None: n = np.array(self._lockN, float)
            else: n = np.array(self._camera().GetCamera().GetViewPlaneNormal(), float)
            n /= np.linalg.norm(n)
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            proj = corners @ n; dmin, dmax = proj.min(), proj.max()
            c = (lo + hi) / 2.0
            c = c + n * ((dmax - frac * (dmax - dmin)) - float(c @ n))
        else:
            c = (lo + hi) / 2.0
            c[axis] = lo[axis] + frac * (hi[axis] - lo[axis])
            n = np.zeros(3); n[axis] = 1.0
        if self.cutPlane is None or not slicer.mrmlScene.IsNodePresent(self.cutPlane):
            self.cutPlane = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "切断面")
            try: self.cutPlane.SetSizeMode(self.cutPlane.SizeModeAbsolute)
            except Exception: pass
            self.cutPlane.SetSize(600, 600)
            self.cutPlane.GetDisplayNode().SetVisibility(False)
            self._put(self.cutPlane)
        wm = self.cutPlane.StartModify()
        self.cutPlane.SetCenter(*c); self.cutPlane.SetNormal(*n)
        self.cutPlane.EndModify(wm)
        clip = self._clipNode()
        if not clip.HasClippingNodeID(self.cutPlane.GetID()):
            clip.AddAndObserveClippingNodeID(self.cutPlane.GetID())
        # 実測: ClipNegativeSpace で法線側（カメラ側）が取り除かれる
        state = clip.ClipNegativeSpace if self.cutSign > 0 else clip.ClipPositiveSpace
        clip.SetClippingNodeState(self.cutPlane, state)
        self._applyClipToModels(True)
        self.updateMyoCap()
        self._ensureViewObserver()
        self.installMouse()
        self._syncCutSlice()
        if getattr(self, "inset", None) is not None and self.inset.pd is not None: self._insetPlane()
        elif getattr(self, "insetOn", True) and getattr(self, "bounds", None) is not None: self.updateInset()
        self._view().scheduleRender()

    INSET_SKIP = ("CV 軟部組織", "CV 骨", "CV 胸骨ワイヤー")
    INSET_SKIP2 = ("CV 心筋", "CV 心筋断面", "CV 石灰化")

    def updateInset(self):
        """左下の全体図を作り直す（モデルを作った後に呼ぶ）"""
        if not getattr(self, "insetOn", True): return
        try:
            ins = getattr(self, "inset", None)
            if ins is None or getattr(slicer, "_cvInset", None) is not ins: ins = self.inset = _Inset(self._view())
            allm = [n for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith("CV ") and n.GetPolyData() is not None and n.GetPolyData().GetNumberOfPoints()]
            # 全体図は「血液の面」（1 枚の面・部屋ごとの色）で描く。見えている層にかかわらず同じ絵（いつも正面からの全体）。
            # 心臓壁・心筋は内外 2 枚の面なので、粗くまとめると内と外が混ざってしわしわになる（MAC の症例で目立った）
            nodes = [n for n in allm if n.GetName().startswith("CV 血管")]
            if not nodes:
                nodes = [n for n in allm if n.GetName() not in self.INSET_SKIP + self.INSET_SKIP2 and n.GetDisplayNode() is not None and n.GetDisplayNode().GetVisibility()]
            if not nodes: nodes = [n for n in allm if n.GetName().startswith("CV 心臓壁")]
            ins.setModels(nodes); ins.followCamera(self._camera()); ins.setVisible(True); ins._autoHidden = False
            self._lastSize = None                                             # 画面が狭ければ次の描画でまた隠す
            self._insetPlane()
        except Exception as e: print("inset:", e)

    def _insetPlane(self):
        ins = getattr(self, "inset", None)
        if ins is None: return
        if self.cutAxis is None or self.cutPlane is None: ins.hidePlane()
        else: ins.setPlane(self.cutPlane.GetCenter(), self.cutPlane.GetNormal())

    def setInsetVisible(self, on):
        self.insetOn = bool(on)
        if on: self.updateInset()
        elif getattr(self, "inset", None) is not None: self.inset.setVisible(False)

    def lockCut(self, on):
        """今の切断面を体に固定する（回転しても切り口が動かない）。戻り値: 固定できたか"""
        if on:
            if self.cutAxis is None or self.cutPlane is None: return False
            if self.cutAxis == "LOCK": return True
            n = np.array(self.cutPlane.GetNormal(), float); n /= np.linalg.norm(n)
            c = np.array(self.cutPlane.GetCenter(), float)
            lo, hi = self._visibleBounds() if hasattr(self, "_visibleBounds") else self.bounds
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            proj = corners @ n; dmin, dmax = proj.min(), proj.max()
            self._lockN = n.tolist(); self._lockPrev = self.cutAxis
            self.setCut("LOCK", float(np.clip((dmax - c @ n) / max(dmax - dmin, 1e-6), 0, 1))); self._syncCutUI()
            return True
        if self.cutAxis == "LOCK":
            prev = getattr(self, "_lockPrev", "VIEW"); self._lockN = None
            f = getattr(self, "cutFrac", 0.5)
            if prev in (0, 1, 2): f = 1.0 - f                                 # 軸で切る時は位置の数え方が逆（固定中は遠い側から、軸は近い側から）。そのまま渡すと、外した時に切る位置が反対側へ飛ぶ
            self.setCut(prev if prev != "LOCK" else "VIEW", f); self._syncCutUI()
        return False

    def _ensureViewObserver(self):
        """回転が終わったら「画面の正面から」の切断面を追従させる（アプリ全体で 1 つ。今のロジックへ届ける）"""
        try:
            inter = self._view().interactor()
            reg = getattr(slicer, "_cvViewObs", None)
            if reg and reg[0] is inter: return
            if reg:
                try: reg[0].RemoveObserver(reg[1])
                except Exception: pass
            def cb(c=None, e=None):
                L = _cvCur()
                if L is not None:
                    try: L._onViewInteractionEnd()
                    except Exception as ex: print("view end:", ex)
            slicer._cvViewObs = (inter, inter.AddObserver(vtk.vtkCommand.EndInteractionEvent, cb))
        except Exception as e:
            print("observer:", e)

    def _onViewInteractionEnd(self, caller=None, event=None):
        if self.cutAxis == "VIEW" and not self.flying:
            self.setCut("VIEW", getattr(self, "cutFrac", 0.5))
        elif self.cutAxis is not None:
            self.updateMyoCap()   # 断面の陰影をカメラの向きに合わせ直す

    def nudgeCut(self, mm):
        if self.cutAxis is None or self.bounds is None: return None
        lo, hi = self._visibleBounds() if hasattr(self, "_visibleBounds") else self.bounds
        if self.cutAxis in ("VIEW", "LOCK"):
            n = np.array(self._lockN if self.cutAxis == "LOCK" else self._camera().GetCamera().GetViewPlaneNormal(), float); n /= np.linalg.norm(n)
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            proj = corners @ n; span = max(proj.max() - proj.min(), 1e-6)
            frac = float(np.clip(getattr(self, "cutFrac", 0.5) + mm / span, 0, 1))
        else:
            span = max(hi[self.cutAxis] - lo[self.cutAxis], 1e-6)
            frac = float(np.clip(getattr(self, "cutFrac", 0.5) + mm / span, 0, 1))
        self.setCut(self.cutAxis, frac); return frac

    def flipCut(self):
        self.cutSign *= -1.0
        clip = self._clipNode()
        if self.cutAxis is not None and self.cutPlane is not None:
            self.setCut(self.cutAxis, self.cutFrac)
        for p in self.planes:
            st = clip.GetClippingNodeState(p)
            clip.SetClippingNodeState(p, clip.ClipPositiveSpace if st == clip.ClipNegativeSpace else clip.ClipNegativeSpace)

    def addFreePlane(self):
        plane = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", f"自由切断面 {len(self.planes)+1}")
        c = self._sceneCenter()
        n = np.array(self._camera().GetCamera().GetViewPlaneNormal())
        plane.SetCenter(*c); plane.SetNormal(*(-n)); plane.SetSize(250, 250)
        try: plane.SetSizeMode(plane.SizeModeAbsolute)
        except Exception: pass
        dp = plane.GetDisplayNode()
        dp.SetHandlesInteractive(True); dp.SetTranslationHandleVisibility(True); dp.SetRotationHandleVisibility(True); dp.SetScaleHandleVisibility(False)
        dp.SetOpacity(0.12); dp.SetVisibility2D(False)
        self._put(plane); self.planes.append(plane)
        clip = self._clipNode()
        clip.AddAndObserveClippingNodeID(plane.GetID()); clip.SetClippingNodeState(plane, clip.ClipNegativeSpace)
        self._applyClipToModels(True)

    def removeFreePlanes(self):
        clip = self._clipNode()
        for p in self.planes:
            if clip.HasClippingNodeID(p.GetID()): clip.RemoveClippingNodeID(p.GetID())
            slicer.mrmlScene.RemoveNode(p)
        self.planes = []

    def _clearCuts(self):
        clip = self._clipNode()
        if self.cutPlane is not None and clip.HasClippingNodeID(self.cutPlane.GetID()):
            clip.RemoveClippingNodeID(self.cutPlane.GetID())
        if clip.GetNumberOfClippingNodes() == 0:
            self._applyClipToModels(False)
        self.updateMyoCap()
        self._insetPlane()
