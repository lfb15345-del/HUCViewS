# -*- coding: utf-8 -*-
"""大動脈サイジング: 画面のレイアウト・断面とストレッチ像の描画・表示の保存と復元
AortaSizingLogic の一部（ViewMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class ViewMixin:

    # ---------------------------------------------------------------- 画面
    def _sliceOnly(self, node, ids):
        d = node.GetDisplayNode()
        if d is None: return
        d.RemoveAllViewNodeIDs()
        for i in ids: d.AddViewNodeID(i)

    def _node(self, cls, name, views, color, glyph=1.5, line=0.3, text=0.0, locked=True):
        n = slicer.mrmlScene.GetFirstNodeByName(name)
        if n is None or not n.IsA(cls): n = slicer.mrmlScene.AddNewNodeByClass(cls, name)
        n.SetLocked(locked); d = n.GetDisplayNode()
        d.SetSelectedColor(*color); d.SetColor(*color); d.SetActiveColor(*color); d.SetGlyphScale(glyph); d.SetLineThickness(line)
        d.SetTextScale(text); d.SetPointLabelsVisibility(text > 0)
        try: d.SetPropertiesLabelVisibility(False); d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.6)
        except Exception: pass
        self._sliceOnly(n, views); return n

    def _ensureNodes(self):
        RED, GREEN, YEL, V3 = "vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeYellow", "vtkMRMLViewNode1"
        self.contNode = self._node("vtkMRMLMarkupsClosedCurveNode", "SA 輪郭", (RED,), (1.0, 0.85, 0.2), glyph=1.3, line=0.25, locked=False)
        self.contNode.SetCurveTypeToCardinalSpline()
        if not getattr(self, "_contTag", None):
            self.contNode.RemoveObservers(slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent)
            self._contTag = self.contNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent, self._onContourEdited)
        self.dLines = [self._node("vtkMRMLMarkupsLineNode", "Dmax", (RED,), (0.95, 0.35, 0.3), glyph=0.8, line=0.15, text=2.5),
                       self._node("vtkMRMLMarkupsLineNode", "Dmin", (RED,), (0.3, 0.6, 1.0), glyph=0.8, line=0.15, text=2.5)]
        for ln in self.dLines:
            if ln.GetNumberOfControlPoints() < 2:
                ln.RemoveAllControlPoints(); ln.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); ln.AddControlPoint(vtk.vtkVector3d(0, 0, 0))
        self.cursorNode = self._node("vtkMRMLMarkupsLineNode", "SA cursor", (GREEN,), (1.0, 0.3, 0.25), glyph=1.0, line=0.35)
        if self.cursorNode.GetNumberOfControlPoints() < 2:
            self.cursorNode.RemoveAllControlPoints(); self.cursorNode.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); self.cursorNode.AddControlPoint(vtk.vtkVector3d(0, 0, 0))
        self.posNode = self._node("vtkMRMLMarkupsFiducialNode", "SA 現在位置", (V3, YEL), (1.0, 0.3, 0.2), glyph=4.0)
        if self.posNode.GetNumberOfControlPoints() < 1: self.posNode.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); self.posNode.SetNthControlPointLabel(0, "")
        self.markG = self._node("vtkMRMLMarkupsFiducialNode", "SA markers S", (GREEN,), (0.3, 0.9, 0.9), glyph=1.6, text=2.6)
        self.mark3 = self._node("vtkMRMLMarkupsFiducialNode", "SA markers 3D", (V3,), (0.3, 0.9, 0.9), glyph=2.5, text=3.0)
        self.baseG = self._node("vtkMRMLMarkupsLineNode", "SA baseline", (GREEN,), (0.4, 1.0, 0.4), glyph=1.0, line=0.3, text=2.6)
        if self.baseG.GetNumberOfControlPoints() < 2:
            self.baseG.RemoveAllControlPoints(); self.baseG.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); self.baseG.AddControlPoint(vtk.vtkVector3d(0, 0, 0))
        self.clockNode = self._node("vtkMRMLMarkupsFiducialNode", "SA clock", (RED,), (0.4, 1.0, 0.4), glyph=2.0, text=3.0)

    def showLayout(self):
        if self.straight is None: return
        lm = slicer.app.layoutManager()
        lm.layoutLogic().GetLayoutNode().AddLayoutDescription(LAYOUT_ID, LAYOUT_XML)
        lm.setLayout(LAYOUT_ID)
        self._editing = False
        for nm, volNode in (("Red", self.vol), ("Yellow", self.vol), ("Green", self.straight), ("Orange", self.straight)):
            w = lm.sliceWidget(nm)
            if w is None: continue
            cn = w.sliceLogic().GetSliceCompositeNode(); cn.SetBackgroundVolumeID(volNode.GetID()); cn.SetForegroundVolumeID(None); cn.SetLabelVolumeID(None)
            w.sliceController().setVisible(False)
        dn = self.vol.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        for vn in (self.vol, self.straight):
            d = vn.GetDisplayNode()
            if d is not None: d.SetInterpolate(True)
        for nm in ("Red", "Green", "Orange", "Yellow"):                         # 画像を曲線補間でなめらかに（元が5mm厚でもカクつかない）
            try:
                sl = lm.sliceWidget(nm).sliceLogic()
                for layer in (sl.GetBackgroundLayer(), sl.GetForegroundLayer()):
                    r = layer.GetReslice()
                    if r is not None: r.SetInterpolationModeToCubic()
            except Exception: pass
        for m in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if m.GetName().startswith("CV ") and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility2D(False)
        for d in slicer.util.getNodesByClass("vtkMRMLSegmentationDisplayNode"):
            try: d.SetVisibility2D(False)
            except Exception: pass
        try:
            for dn2 in slicer.util.getNodesByClass("vtkMRMLSliceDisplayNode"): dn2.SetIntersectingSlicesVisibility(False)
        except Exception: pass
        pv = lm.plotWidget(0)
        if pv is not None and self.chart is not None: pv.mrmlPlotViewNode().SetPlotChartNodeID(self.chart.GetID())
        for k, c in self.curves.items():
            c.SetLocked(True); c.GetDisplayNode().SetVisibility(True); self._sliceOnly(c, ("vtkMRMLViewNode1",))
        self._ensureNodes()
        for n in (self.posNode, self.mark3, self.clockNode): n.GetDisplayNode().SetVisibility(True)
        for n in [self.cursorNode, self.markG, self.baseG] + list(self.dLines or []): n.GetDisplayNode().SetVisibility(False)   # 軽い描画（_Overlay）に置き換え
        self.contNode.GetDisplayNode().SetVisibility(bool(getattr(self, "contourEdit", False)))
        for ov in ("ovRed", "ovGreen", "ovOrange"):
            o = getattr(self, ov, None)
            if o is not None: o.remove()
        self.ovRed = _Overlay("Red"); self.ovGreen = _Overlay("Green")
        self.ovOrange = _Overlay("Orange") if lm.sliceWidget("Orange") is not None else None
        self._saveCV()                                                     # 心臓の画面の 3D の状態を覚えてから変える
        rn = lm.sliceWidget("Red").mrmlSliceNode(); rn.SetSliceVisible(True)
        for nm in ("Green", "Orange", "Yellow"):
            if lm.sliceWidget(nm) is not None: lm.sliceWidget(nm).mrmlSliceNode().SetSliceVisible(False)
        self._fit3D(); self._fitViews(); self._watch(); self._drawMarkers()

    def _fitViews(self):
        lm = slicer.app.layoutManager()
        def fit(sn, fy):
            d = sn.GetDimensions(); asp = (d[0] / max(d[1], 1)) if d[1] else 1.0
            sn.SetFieldOfView(fy * asp, fy, 1.0); sn.SetXYZOrigin(0, 0, 0)
        fit(lm.sliceWidget("Green").mrmlSliceNode(), self.length * 1.04 + 10)
        if lm.sliceWidget("Orange") is not None: fit(lm.sliceWidget("Orange").mrmlSliceNode(), self.length * 1.04 + 10)
        fit(lm.sliceWidget("Red").mrmlSliceNode(), 60.0)
        fit(lm.sliceWidget("Yellow").mrmlSliceNode(), 160.0)

    def _fit3D(self):
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            for name, on in (("心臓壁", False), ("心筋", False), ("軟部組織", False), ("骨", False), ("血液・血管", False)):
                cv.setLayerVisible(name, on)
            cv._clearCuts()
            for k, m in cv.layerModels.items():
                if m is not None and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility(False)
        except Exception: pass
        v3 = slicer.app.layoutManager().threeDWidget(0).threeDView()
        vn = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        try:
            vn.SetBackgroundColor(0.11, 0.13, 0.17); vn.SetBackgroundColor2(0.02, 0.02, 0.03)   # 落ち着いた濃紺のグラデ
            vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
            vn.SetOrientationMarkerType(vn.OrientationMarkerTypeHuman) if hasattr(vn, "OrientationMarkerTypeHuman") else None
        except Exception: pass
        try:
            ren = v3.renderWindow().GetRenderers().GetFirstRenderer()
            ren.SetUseDepthPeeling(True); ren.SetMaximumNumberOfPeels(8); ren.SetOcclusionRatio(0.1)
            ren.SetUseSSAO(True); ren.SetSSAORadius(12.0); ren.SetSSAOBias(0.01); ren.SetSSAOKernelSize(32); ren.SetSSAOBlur(True)
            v3.renderWindow().SetMultiSamples(8)                               # アンチエイリアスで輪郭をなめらかに
            if getattr(self, "_tvMode", False): ren.SetUseDepthPeeling(False); ren.SetUseSSAO(False)   # TEVAR: 半透明（血管・グラフトの布）を描くため
        except Exception: pass
        if self.P is None: return
        allp = np.vstack([slicer.util.arrayFromMarkupsCurvePoints(c, world=True) for c in self.curves.values()])
        lo, hi = allp.min(0), allp.max(0); cen = (lo + hi) / 2; ext = float(np.max(hi - lo))
        cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(slicer.app.layoutManager().threeDWidget(0).mrmlViewNode())
        cam.SetFocalPoint(*cen); cam.SetPosition(*(cen + np.array([0, -1.0, 0]) * ext * 2.1)); cam.SetViewUp(0, 0, 1)
        cam.GetCamera().SetViewAngle(30); cam.ResetClippingRange()

    def _inplane(self, k=None):
        k = self._k() if k is None else k; th = math.radians(self.rot)
        B, N = self.B[k], self.N[k]
        return math.cos(th) * B + math.sin(th) * N, -math.sin(th) * B + math.cos(th) * N

    def setPosition(self, s):
        if self.P is None: return
        s = float(np.clip(s, 0, self.length)); self.curS = s; k = self._k()
        lm = slicer.app.layoutManager()
        rn = lm.sliceWidget("Red").mrmlSliceNode()
        X, Y = self._inplane(k); T = self.T[k]; P = self.P[k]
        M = rn.GetSliceToRAS()
        for r in range(3): M.SetElement(r, 0, X[r]); M.SetElement(r, 1, Y[r]); M.SetElement(r, 2, T[r]); M.SetElement(r, 3, P[r])
        self._resliceMode(False)
        rn.UpdateMatrices()
        self._drawGreen()
        self._showContour(exact=False)
        try: self._prefetchTimer.stop()
        except Exception: pass
        self._settleLater()                                              # 軸位・3D の位置は、動きが止まってから

    def _resliceMode(self, cubic):
        """断面の補間: 動かしている間は線形（速い）、止まったら 3 次（なめらか）"""
        if getattr(self, "_cubicNow", None) == cubic: return
        self._cubicNow = cubic
        for nm in ("Red", "Green", "Orange", "Yellow"):
            try:
                sl = slicer.app.layoutManager().sliceWidget(nm).sliceLogic()
                r = sl.GetBackgroundLayer().GetReslice()
                if r is None: continue
                (r.SetInterpolationModeToCubic if cubic else r.SetInterpolationModeToLinear)()
                if cubic: sl.GetBackgroundLayer().Modified(); slicer.app.layoutManager().sliceWidget(nm).sliceView().scheduleRender()
            except Exception: pass

    def _settleLater(self):
        t = getattr(self, "_settleTimer", None)
        if t is None:
            t = self._settleTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(120); t.connect("timeout()", self._settle)
        t.start()

    def _settle(self):
        if self.P is None: return
        k = self._k(); P = self.P[k]
        try:
            yn = slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode()
            if yn.GetOrientation() != "Axial": yn.SetOrientationToAxial()
            if not getattr(self, "fixMode", False): yn.JumpSliceByCentering(P[0], P[1], P[2])
            if self.posNode is not None: self.posNode.SetNthControlPointPosition(0, *P)
            self._drawAxialCenters()
            self._resliceMode(True)
            if getattr(self, "_approx", False): self._showContour()
            self._prefetchStart()
        except Exception as e: print("settle:", e)

    def _prefetchStart(self):
        """手が止まっている間に、今の位置から外側へ向かって断面を先回りで計算しておく（次のスクロールが速い）"""
        t = getattr(self, "_prefetchTimer", None)
        if t is None:
            t = self._prefetchTimer = qt.QTimer(); t.setInterval(5); t.connect("timeout()", self._prefetchTick)
        k0 = self._k(); K = len(self.s)
        order = [k0]
        for d in range(1, K): order += [k for k in (k0 + d, k0 - d) if 0 <= k < K]
        self._pfQueue = order; self._pfPath = self.path; t.start()

    def _prefetchTick(self):
        import time as _t
        if self.path != getattr(self, "_pfPath", None) or not getattr(self, "_pfQueue", None):
            self._prefetchTimer.stop(); return
        t0 = _t.time()
        while self._pfQueue and _t.time() - t0 < 0.012:                 # 1 回 12 ms まで（操作をじゃましない）
            k = self._pfQueue.pop(0)
            if (self.path, "outer", k) in self.cache and (self.path, "lumen", k) in self.cache: continue
            try: self._section(k, "outer")
            except Exception: pass

    def setRotation(self, deg):
        self.rot = float(deg) % 360.0; th = math.radians(self.rot); c, s = math.cos(th), math.sin(th)
        gn = slicer.app.layoutManager().sliceWidget("Green").mrmlSliceNode()
        gn.SetSliceToRASByNTP(-s, c, 0, -c, -s, 0, 0, 0, -self.length / 2, 0)
        ow = slicer.app.layoutManager().sliceWidget("Orange")                # もう 1 枚のストレッチ像は 90° 回した向き（直交 2 方向を同時に見る）
        if ow is not None:
            off = math.radians(getattr(self, "orangeOff", 90.0)); c2, s2 = math.cos(th + off), math.sin(th + off)
            ow.mrmlSliceNode().SetSliceToRASByNTP(-s2, c2, 0, -c2, -s2, 0, 0, 0, -self.length / 2, 0)
        self._fitViews()
        self.setPosition(self.curS); self._drawMarkers()

    LUMEN_COL = (1.0, 0.85, 0.2); OUTER_COL = (0.35, 0.85, 1.0)

    def _metFast(self, k, md):
        """動かしている最中: その位置が未計算なら、近くの計算済み断面（±2 mm 以内）で代用して描画を止めない"""
        key = (self.path, md, int(k))
        if key in self.override or key in self.cache: return self._metK(k, md), False
        for d in range(1, 5):
            for kk in (k - d, k + d):
                kk2 = (self.path, md, int(kk))
                if kk2 in self.override or kk2 in self.cache: return self._metK(kk, md), True
        return self._metK(k, md), False

    def _showContour(self, exact=True):
        if self.prof is None or self.contNode is None: return
        k = self._k(); P, B, N = self.P[k], self.B[k], self.N[k]
        if exact: mL = self._metK(k, "lumen"); mO = self._metK(k, "outer"); ap = False
        else:
            (mL, a1), (mO, a2) = self._metFast(k, "lumen"), self._metFast(k, "outer"); ap = a1 or a2
        self._approx = ap
        m = mL if self.mode == "lumen" else mO
        W = lambda xy: P + np.outer(xy[:, 0], B) + np.outer(xy[:, 1], N)
        edit = bool(getattr(self, "contourEdit", False))
        lines, labels = [], []
        for mm, col, md in ((mO, self.OUTER_COL, "outer"), (mL, self.LUMEN_COL, "lumen")):
            if mm is None or (edit and md == self.mode): continue
            lines.append((W(mm["xy"]), col, True))
        try:
            gr = getattr(self, "_graftRad", None)
            if gr is not None and gr["path"] == self.path and gr["ks"][0] <= k <= gr["ks"][-1] and (getattr(self, "plan", None) or {}).get("on", True):
                i = k - gr["ks"][0]; Rt = gr["Rth"][i]; th = np.linspace(0, 2 * np.pi, len(Rt), endpoint=False)
                xy = np.c_[gr["cu"][i] + Rt * np.cos(th), gr["cv"][i] + Rt * np.sin(th)]
                pd_ = getattr(self, "_pdDrag", None)
                if pd_ is not None:                                                    # シミュレーションをドラッグ中
                    cc_ = np.array([gr["cu"][i], gr["cv"][i]])
                    xy = xy + pd_["d"] if pd_["kind"] == "move" else cc_ + (xy - cc_) * pd_["sc"]
                a_ = 0.5 * abs(np.dot(xy[:, 0], np.roll(xy[:, 1], -1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], -1)))
                lines.append((W(xy), (0.95, 0.97, 1.0), True))
                labels.append((W(xy[27:28])[0], f"Plan {2 * math.sqrt(a_ / math.pi):.0f} ({2 * gr['Rn'][i]:.0f})", (0.95, 0.97, 1.0), 14))
                if gr["gut"][i] >= 5: labels.append((W(xy[45:46])[0], f"Gutter {gr['gut'][i]:.0f} mm2", (0.95, 0.97, 1.0), 13))
                if gr["tl"] and gr["flap"] != "fixed" and self.tlValid():          # グラフトが術前の真腔の外へ広がる所 = フラップが押されて動く所
                    tm = self.tl["masks"][k]; nn = tm.shape[0]
                    rr_ = np.clip(np.round((xy[:, 1] + HALF) / STEP).astype(int), 0, nn - 1); cc_ = np.clip(np.round((xy[:, 0] + HALF) / STEP).astype(int), 0, nn - 1)
                    o = ~tm[rr_, cc_]
                    if o.any() and not o.all():
                        idx = np.roll(np.arange(len(xy)), -int(np.argmin(o))); segs, cur = [], []
                        for ii in idx:
                            if o[ii]: cur.append(ii)
                            elif cur: segs.append(cur); cur = []
                        if cur: segs.append(cur)
                        for sg in segs:
                            if len(sg) >= 2: lines.append((W(xy[sg]), (0.3, 1.0, 0.45), False))
                        sg = max(segs, key=len)
                        if len(sg) >= 4: labels.append((W(xy[sg[len(sg) // 2]:sg[len(sg) // 2] + 1])[0], "Flap pushed", (0.3, 1.0, 0.45), 13))
        except Exception as e: print("plan ring:", e)
        try:
            ac = getattr(self, "actual", None)
            if ac is not None and ac.get("C") is not None and ac["path"] == self.path and ac["ks"][0] <= k <= ac["ks"][-1]:
                i = k - ac["ks"][0]; cc_ = ac["C"][i] - P
                if ac.get("Rth") is not None:                                              # 実際のステント = 金属に当てはめた楕円
                    Rt = ac["Rth"][i]; th = np.linspace(0, 2 * np.pi, len(Rt), endpoint=False); xy = np.c_[cc_ @ B + Rt * np.cos(th), cc_ @ N + Rt * np.sin(th)]
                else:
                    th = np.linspace(0, 2 * np.pi, 72, endpoint=False); xy = np.c_[cc_ @ B + ac["R"][i] * np.cos(th), cc_ @ N + ac["R"][i] * np.sin(th)]
                lab_ = f"Post {2 * ac['A'][i]:.0f}x{2 * ac['Bm'][i]:.0f}" if ac.get("A") is not None else f"Post {2 * ac['R'][i]:.0f}"
                lines.append((W(xy), (1.0, 0.72, 0.2), True)); labels.append((W(xy[54:55])[0], lab_, (1.0, 0.72, 0.2), 14))
            if ac is not None and ac.get("path") == self.path:                          # 実際の金属（この断面の前後 2.5 mm）を金色の点で
                Tk = np.cross(B, N); dX = ac["pts"] + self._liveAlign() - P; mm_ = np.abs(dX @ Tk) <= 2.5
                if mm_.any():
                    q = dX[mm_]; uu, vv = q @ B, q @ N
                    if len(uu) > 400: j_ = np.random.default_rng(0).choice(len(uu), 400, replace=False); uu, vv = uu[j_], vv[j_]
                    for a_, b_ in zip(uu, vv):
                        lines.append((W(np.array([[a_ - 0.5, b_], [a_ + 0.5, b_]])), (1.0, 0.8, 0.25), False))
                        lines.append((W(np.array([[a_, b_ - 0.5], [a_, b_ + 0.5]])), (1.0, 0.8, 0.25), False))
        except Exception as e: print("post ring:", e)
        try:
            if self.tlValid():
                xy = self._tlXY(k)
                if xy is not None:
                    lines.append((W(xy), (0.3, 1.0, 0.45), True)); d = self.tl["deq"][k]
                    if np.isfinite(d): labels.append((W(xy[24:25])[0], f"TL {d:.1f}", (0.3, 1.0, 0.45), 14))
        except Exception as e: print("tl contour:", e)
        if m is not None:
            for key, lab, col in (("maxLine", "dmax", (1.0, 0.35, 0.3)), ("minLine", "dmin", (0.35, 0.65, 1.0))):
                a, b = m[key]; ab = W(np.array([a, b]))
                lines.append((ab, col, False)); labels.append((ab[1], f"{m[lab]:.1f}", col, 15))
        if getattr(self, "ovRed", None) is not None: self.ovRed.set(lines, labels)
        if edit:                                                          # 手直し中だけ、点をつかめる曲線を出す
            self._busyEdit = True
            wasMod = self.contNode.StartModify(); self.contNode.RemoveAllControlPoints()
            if m is not None:
                xy = m["xy"]; idx = np.linspace(0, len(xy), NEDIT, endpoint=False).astype(int)
                for x, y in xy[idx]: self.contNode.AddControlPoint(vtk.vtkVector3d(*(P + x * B + y * N)))
            self.contNode.EndModify(wasMod); self._busyEdit = False
        self._mL, self._mO = mL, mO
        self._annotate(k, m)
        try: self.onChanged()
        except Exception: pass

    def setContourEdit(self, on):
        self.contourEdit = bool(on)
        if self.contNode is not None: self.contNode.GetDisplayNode().SetVisibility(self.contourEdit)
        self._showContour()

    def _greenRAS(self, s, frac=1.0, rot=None):
        th = math.radians(self.rot if rot is None else rot); t = np.array([-math.cos(th), -math.sin(th), 0.0])
        return np.array([t * (HALF - 1) * frac + np.array([0, 0, -s]), -t * (HALF - 1) * frac + np.array([0, 0, -s])])

    def _drawGreen(self):
        """ストレッチ像: 現在位置（赤）・ベースライン（緑）・マーカー（水色）・マウスの位置（白）を軽く描く"""
        if self.P is None or getattr(self, "_editing", False): return
        for ovn, vn, rot in (("ovGreen", "Green", self.rot), ("ovOrange", "Orange", self.rot + getattr(self, "orangeOff", 90.0))):
            o = getattr(self, ovn, None)
            if o is not None: self._drawStretch(o, vn, rot)

    def _drawStretch(self, o, vn, rot):
        G = lambda s, frac=1.0: self._greenRAS(s, frac, rot)
        lines, labels = [], []
        if self.baseS is not None:
            ab = G(self.baseS); lines.append((ab, (0.4, 1.0, 0.45), False)); labels.append((ab[0], "0", (0.4, 1.0, 0.45), 12))
        try:
            sn = slicer.app.layoutManager().sliceWidget(vn).mrmlSliceNode(); mmpp = sn.GetFieldOfView()[1] / max(sn.GetDimensions()[1], 1)
        except Exception: mmpp = 1.0
        lastLab = -1e9
        for mk in sorted(self.markers, key=lambda m: m["s"]):
            if not self._onPath(mk): continue
            ab = G(mk["s"], 0.55); lines.append((ab, (0.3, 0.9, 0.95), False))
            sl = max(mk["s"], lastLab + 15 * mmpp); lastLab = sl                # 近いマーカーの文字が重ならないよう下へずらす
            lab = MARK_EN.get(mk["name"].replace("（推定）", ""), "Sec" + mk["name"][2:] if mk["name"].startswith("断面") else "M") + ("?" if mk.get("auto") else "")
            if vn == "Green": labels.append((G(sl, 0.55)[0], f"{lab} {self.rel(mk['s']):+.0f}", (0.3, 0.9, 0.95), 12))
        hs = getattr(self, "_hoverS", None)
        if hs is not None and self.prof is not None:
            kk = int(min(max(round(hs / STEP), 0), len(self.prof) - 1)); dmax, dmin = self.prof[kk, 2], self.prof[kk, 3]
            ab = G(hs); lines.append((ab, (0.85, 0.85, 0.85), False))
            if np.isfinite(dmax): labels.append((ab[1], f"{self.rel(hs):+.0f} mm  {dmax:.1f}/{dmin:.1f}", (1, 1, 1), 13))
        pl = getattr(self, "plan", None)
        pk = getattr(self, "_pickP", None)
        if pk is not None and getattr(self, "pickPD", None):
            ab = G(pk); lines.append((ab, (1.0, 0.9, 0.2), False))
            if vn == "Green": labels.append((ab[1], "P", (1.0, 0.9, 0.2), 13))
        if pl is not None and pl.get("on", True) and pl.get("path") == self.path:
            for sx, nm in ((pl["p"], "Plan P"), (pl["d"], "Plan D")):
                ab = G(sx); lines.append((ab, (0.95, 0.95, 1.0), False))
                if vn == "Green": labels.append((ab[1], nm, (0.95, 0.95, 1.0), 12))
            if vn == "Green": labels.append((G(0.5 * (pl["p"] + pl["d"]))[1], f"{pl['d'] - pl['p']:.0f} mm", (0.95, 0.95, 1.0), 15))
        ac = getattr(self, "actual", None)
        if ac is not None and ac.get("path") == self.path:
            for sx, nm in ((ac["lo"], "Post P"), (ac["hi"], "Post D")):
                ab = G(sx); lines.append((ab, (1.0, 0.72, 0.2), False))
                if vn != "Green" or getattr(self, "orangeOff", 90.0) != 0: labels.append((ab[0], nm, (1.0, 0.72, 0.2), 12))
        if pl is not None:
            st = {r["name"]: r["state"] for r in self.coverage(pl["p"], pl["d"]) if r["kind"] == "entry"}
            for e in getattr(self, "entries", []):
                if e.get("path") == self.path or e["s"] <= getattr(self, "sharedLen", 0) + 2:
                    lines.append((G(e["s"], 0.3), self.STATE_COL.get(st.get(e["name"], "open")), False))
        ab = G(self.curS); lines.append((ab, (1.0, 0.3, 0.25), False))
        o.set(lines, labels)

    def _annotate(self, k, m):
        lm = slicer.app.layoutManager()
        try:
            red = lm.sliceWidget("Red").sliceView(); ca = red.cornerAnnotation()
            mode = "Outer" if self.mode == "outer" else "Lumen"
            base = f"{self.rel(self.s[k]):+.1f} mm from baseline" if self.baseS is not None else f"{self.s[k]:.1f} mm from origin"
            mL, mO = getattr(self, "_mL", None), getattr(self, "_mO", None)
            def fmt(q, nm):
                return (f"{nm}  Dmax {q['dmax']:.1f}  Dmin {q['dmin']:.1f}  Deq {q['deq']:.1f} mm" + (" *" if q.get("edited") else "")) if q else f"{nm}  -"
            txt = base + "\n" + fmt(mO, "Outer") + "\n" + fmt(mL, "Lumen")
            ca.SetText(2, txt); ca.GetTextProperty().SetColor(1, 0.9, 0.3); ca.GetTextProperty().SetFontSize(16); red.scheduleRender()
            g = lm.sliceWidget("Green").sliceView(); c2 = g.cornerAnnotation()
            c2.SetText(2, f"{PATH_EN.get(self.path, '')}\n{base}\nrot {self.rot:.0f} deg"); c2.GetTextProperty().SetColor(1, 0.9, 0.3); g.scheduleRender()
            ow = lm.sliceWidget("Orange")
            if ow is not None:
                c4 = ow.sliceView().cornerAnnotation(); c4.SetText(2, f"rot {(self.rot + getattr(self, 'orangeOff', 90.0)) % 360:.0f} deg" + ("  POST-OP" if getattr(self, "orangeOff", 90.0) == 0 else "")); c4.GetTextProperty().SetColor(1, 0.75, 0.35); ow.sliceView().scheduleRender()
            y = lm.sliceWidget("Yellow").sliceView(); c3 = y.cornerAnnotation(); c3.SetText(2, "Axial (original)"); c3.GetTextProperty().SetColor(1, 0.9, 0.3)
        except Exception as e:
            print("annotate:", e)

    def _onContourEdited(self, caller=None, event=None):
        if self._busyEdit or self.prof is None: return
        k = self._k(); P, B, N = self.P[k], self.B[k], self.N[k]
        ctrl = slicer.util.arrayFromMarkupsControlPoints(self.contNode, world=True)
        if ctrl is None or len(ctrl) < 3: return
        base = self._section(k)
        q = ctrl - P; cxy = np.c_[q @ B, q @ N]
        if base is not None and len(base) == NPOLY and len(ctrl) == NEDIT:
            idx = np.linspace(0, NPOLY, NEDIT, endpoint=False).astype(int)
            disp = cxy - base[idx]
            pos = np.arange(NPOLY) / (NPOLY / NEDIT)
            i0 = np.floor(pos).astype(int) % NEDIT; i1 = (i0 + 1) % NEDIT; f = (pos - np.floor(pos))[:, None]
            new = base + (1 - f) * disp[i0] + f * disp[i1]
        else: new = _resample(cxy)
        self.override[(self.path, self.mode, k)] = new
        self._refreshK(k)

    # ---------------------------------------------------------------- マウス操作
    @staticmethod
    def _only(fn):
        """大動脈サイジングを開いている時だけ動く（心臓の画面のホイールや MPR を横取りしない）"""
        def cb(c, e):
            try:
                if slicer.util.selectedModule() != "AortaSizing": return
            except Exception: return
            return fn(c, e)
        return cb

    def suspend(self):
        """ほかの画面へ移る時: マウス操作の横取り・断面の上の線・3D の線や点をすべて引っ込める（戻ったら元どおり）"""
        for it, tag in list(self._iTags) + list(getattr(slicer, "_saITags", None) or []):
            try: it.RemoveObserver(tag)
            except Exception: pass
        self._iTags = []; slicer._saITags = self._iTags
        for t in ("_settleTimer", "_prefetchTimer", "_timer", "_lcTimer"):
            try: getattr(self, t).stop()
            except Exception: pass
        for ov in ("ovRed", "ovGreen", "ovOrange"):
            o = getattr(self, ov, None)
            if o is not None:
                try: o.remove()
                except Exception: pass
            setattr(self, ov, None)
        reg = getattr(slicer, "_saOverlays", None) or {}
        for k, o in list(reg.items()):
            try: o.remove()
            except Exception: pass
            reg.pop(k, None)
        hidden = getattr(self, "_hiddenNodes", None) or []
        for n in list(slicer.util.getNodesByClass("vtkMRMLDisplayableNode")):
            try:
                if not (n.GetName().startswith(("SA ", "TEVAR ", "研究 ")) or n.GetAttribute("SA.measure")): continue
                d = n.GetDisplayNode()
                if d is not None and d.GetVisibility(): d.SetVisibility(False); hidden.append(n)
            except Exception: pass
        self._hiddenNodes = hidden
        self._restoreCV()                                                  # 心臓の画面の 3D（面・カメラ・切断面）を元に戻す
        try:
            lm = slicer.app.layoutManager()
            for nm in ("Red", "Green", "Orange", "Yellow"):
                w = lm.sliceWidget(nm)
                if w is not None: w.sliceView().cornerAnnotation().SetText(2, ""); w.sliceView().scheduleRender()
        except Exception: pass

    def _saveCV(self):
        """心臓の画面の 3D の状態（面の表示・VR・カメラ・背景・切断面）を覚える。大動脈から戻る時に元に戻す"""
        if getattr(self, "_cvState", None) is not None: return
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            lm = slicer.app.layoutManager(); vn = lm.threeDWidget(0).mrmlViewNode()
            cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn).GetCamera()
            ren = lm.threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer()
            self._cvState = dict(
                visible=dict(getattr(cv, "visible", {}) or {}),
                models={k: m.GetDisplayNode().GetVisibility() for k, m in (getattr(cv, "layerModels", {}) or {}).items() if m is not None and m.GetDisplayNode() is not None},
                cam=(cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp(), cam.GetParallelProjection(), cam.GetParallelScale(), cam.GetViewAngle()),
                bg=(vn.GetBackgroundColor(), vn.GetBackgroundColor2()), ssao=ren.GetUseSSAO(),
                cut=(getattr(cv, "cutAxis", None), getattr(cv, "cutFrac", 0.5), getattr(cv, "_lockN", None)),
                sliceVis={nm: lm.sliceWidget(nm).mrmlSliceNode().GetSliceVisible() for nm in ("Red", "Yellow", "Green") if lm.sliceWidget(nm) is not None})
        except Exception as e: print("saveCV:", e); self._cvState = None

    def _restoreCV(self):
        st = getattr(self, "_cvState", None); self._cvState = None
        if not st: return
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            lm = slicer.app.layoutManager(); vn = lm.threeDWidget(0).mrmlViewNode()
            for name, on in st["visible"].items():
                try: cv.setLayerVisible(name, on)
                except Exception: pass
            for k, on in st["models"].items():
                m = cv.layerModels.get(k)
                if m is not None and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility(on)
            camN = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn); cam = camN.GetCamera()
            pos, fp, up, par, scale, ang = st["cam"]
            cam.SetParallelProjection(par); cam.SetParallelScale(scale); cam.SetViewAngle(ang)
            camN.SetPosition(*pos); camN.SetFocalPoint(*fp); camN.SetViewUp(*up); camN.ResetClippingRange()
            vn.SetBackgroundColor(*st["bg"][0]); vn.SetBackgroundColor2(*st["bg"][1])
            try: lm.threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer().SetUseSSAO(st["ssao"])
            except Exception: pass
            for nm, v in st["sliceVis"].items():
                try: lm.sliceWidget(nm).mrmlSliceNode().SetSliceVisible(v)
                except Exception: pass
            axis, frac, lockN = st["cut"]
            if axis is not None:
                if axis == "LOCK" and lockN is not None: cv._lockN = lockN
                cv.setCut(axis, frac)
            lm.threeDWidget(0).threeDView().scheduleRender()
        except Exception as e: print("restoreCV:", e)

    def resume(self):
        for n in getattr(self, "_hiddenNodes", None) or []:
            try:
                if slicer.mrmlScene.IsNodePresent(n): n.GetDisplayNode().SetVisibility(True)
            except Exception: pass
        self._hiddenNodes = []
        if self.straight is not None and self.vol is not None and slicer.mrmlScene.IsNodePresent(self.vol): self.showLayout()

    def _watch(self):
        lm = slicer.app.layoutManager()
        old = getattr(slicer, "_saITags", None) or []                         # アプリ全体で 1 組だけ（再読み込み・開き直しで古い操作が残らない）
        for it, tag in list(self._iTags) + list(old):
            try: it.RemoveObserver(tag)
            except Exception: pass
        self._iTags = []; slicer._saITags = self._iTags
        E = vtk.vtkCommand
        for nm in ("Red", "Green", "Orange", "Yellow"):
            if lm.sliceWidget(nm) is None: continue
            sv = lm.sliceWidget(nm).sliceView(); io = sv.interactorObserver()
            io.SetActionEnabled(io.BrowseSlice, False)
            # 普通の DICOM ビューアのように、左ドラッグでウィンドウ（濃さ・コントラスト）を変えられる。
            # 断面位置を左ドラッグで動かす Green だけは切る（そのぶんウィンドウは Red / 軸位で変え、全ビューに反映）。
            wl = nm not in ("Green", "Orange")
            io.SetActionEnabled(io.AdjustWindowLevelBackground, wl); io.SetActionEnabled(io.AdjustWindowLevelForeground, wl)
            try:
                siw = sv.displayableManagerByClassName("vtkMRMLCrosshairDisplayableManager").GetSliceIntersectionWidget()
                for act in (siw.ActionBrowseSlice, siw.ActionTranslateSliceIntersection, siw.ActionRotateSliceIntersection, siw.ActionSetCrosshairPosition):
                    siw.SetActionEnabled(act, False)
            except Exception: pass
            it = sv.interactor()
            def add(ev, fn, it=it): self._iTags.append((it, it.AddObserver(ev, self._only(fn), 1.0)))
            if nm == "Red":
                add(E.MouseWheelForwardEvent, lambda c, e: self._wheelRed(c, -1)); add(E.MouseWheelBackwardEvent, lambda c, e: self._wheelRed(c, +1))
                add(E.KeyPressEvent, lambda c, e: self._keyRed(c))
                add(E.LeftButtonPressEvent, lambda c, e: self._clickRed(c))
                add(E.MouseMoveEvent, lambda c, e: self._moveRed(c)); add(E.LeftButtonReleaseEvent, lambda c, e: self._releaseRed(c))
                add(E.LeaveEvent, lambda c, e: self._releaseRed(c) if (getattr(self, "_alDrag", None) is not None or getattr(self, "_pdDrag", None) is not None) else None)
            elif nm in ("Green", "Orange"):
                add(E.MouseWheelForwardEvent, lambda c, e: self._wheelGreen(c, +1)); add(E.MouseWheelBackwardEvent, lambda c, e: self._wheelGreen(c, -1))
                add(E.LeftButtonPressEvent, lambda c, e, nm=nm: self._pressGreen(c, nm)); add(E.MouseMoveEvent, lambda c, e, nm=nm: self._moveGreen(c, nm))
                add(E.LeftButtonReleaseEvent, lambda c, e: self._releaseGreen(c))
                add(E.LeaveEvent, lambda c, e: self._leaveGreen(c))
            else:                                   # Yellow 軸位: ホイールは断面位置に合わせる（勝手にスクロールさせない）
                add(E.MouseWheelForwardEvent, lambda c, e: self._wheelAx(c, +1)); add(E.MouseWheelBackwardEvent, lambda c, e: self._wheelAx(c, -1))
                add(E.LeftButtonPressEvent, lambda c, e: self._pressAx(c)); add(E.MouseMoveEvent, lambda c, e: self._moveAx(c))
                add(E.LeftButtonReleaseEvent, lambda c, e: self._releaseAx(c))
        for nm in [n for n in ("Red", "Green", "Orange", "Yellow") if lm.sliceWidget(n) is not None] + ["3D"]:   # どのビューで操作したか（計測の置き場所）と、共通のキー
            it = lm.threeDWidget(0).threeDView().interactor() if nm == "3D" else lm.sliceWidget(nm).sliceView().interactor()
            self._iTags.append((it, it.AddObserver(E.LeftButtonPressEvent, self._only(lambda c, e, nm=nm: setattr(self, "_lastView", nm)), 5.0)))
            self._iTags.append((it, it.AddObserver(E.KeyPressEvent, self._only(lambda c, e: self._keyAny(c)), 5.0)))
        self._linkWindowLevel()
        it3 = lm.threeDWidget(0).threeDView().interactor()
        self._iTags.append((it3, it3.AddObserver(E.LeftButtonPressEvent, self._only(lambda c, e: self._press3D(c)), 1.0)))
        self._iTags.append((it3, it3.AddObserver(E.LeftButtonReleaseEvent, self._only(lambda c, e: self._release3D(c)), 1.0)))

    def _linkWindowLevel(self):
        """元画像でウィンドウを変えたら、伸ばした画像（Green）にも同じ値を反映する"""
        d = self.vol.GetDisplayNode()
        if getattr(self, "_wlTag", None) is not None:
            try: self._wlSrc.RemoveObserver(self._wlTag)
            except Exception: pass
        self._wlSrc = d
        def onWL(caller=None, ev=None):
            if self.straight is None: return
            sd = self.straight.GetDisplayNode()
            if sd is None: return
            sd.SetAutoWindowLevel(False); sd.SetWindowLevel(d.GetWindow(), d.GetLevel())
        self._wlTag = d.AddObserver(vtk.vtkCommand.ModifiedEvent, onWL)
