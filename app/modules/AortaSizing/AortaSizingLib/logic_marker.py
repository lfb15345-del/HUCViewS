# -*- coding: utf-8 -*-
"""大動脈サイジング: 印（マーカー）・手動計測・ベースライン・クロック
AortaSizingLogic の一部（MarkerMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class MarkerMixin:

    # ---------------------------------------------------------------- マーカー・ベースライン
    def _xyzAt(self, s, path=None):
        F = self.frames[path or self.path]; return F["P"][self._k(s, path)]

    def addMarker(self, name, s=None, path=None, auto=False, clock=None):
        s = self.curS if s is None else float(s); path = path or self.path
        if name == "マーカー":                                            # 自由なマーカーは上書きせず、番号を振って残す
            name = "マーカー{}".format(1 + sum(1 for m in self.markers if m["name"].startswith("マーカー")))
        prev = self._mk(name)
        self.markers = [m for m in self.markers if m["name"] != name]
        self.markers.append(dict(name=name, s=s, path=path, xyz=self._xyzAt(s, path).tolist(), auto=auto, clock=clock))
        self.markers.sort(key=lambda m: m["s"])
        if not auto: self._hist = getattr(self, "_hist", []); self._hist.append(("marker", (name, prev)))
        self._drawMarkers()
        return name

    def removeMarker(self, r):
        if 0 <= r < len(self.markers): self.markers.pop(r); self._drawMarkers()

    def removeMarkerByName(self, name):
        self.markers = [m for m in self.markers if m["name"] != name]; self._drawMarkers()

    def jumpToMarker(self, r):
        if not (0 <= r < len(self.markers)): return
        m = self.markers[r]
        if m["path"] != self.path and m["s"] > getattr(self, "sharedLen", 0) + 2: self._switch(m["path"], m["s"])
        else: self.setPosition(m["s"])

    def setBaseline(self):
        self.baseS = float(self.curS); self._drawMarkers(); self._showContour()

    def _onPath(self, m):
        return m["path"] == self.path or m["s"] <= getattr(self, "sharedLen", 0) + 2

    def _drawMarkers(self):
        if self.mark3 is None: return
        wasMod = self.mark3.StartModify(); self.mark3.RemoveAllControlPoints()
        for m in self.markers:
            lab = MARK_EN.get(m["name"].replace("（推定）", ""), m["name"][:8]) + (" " + m["clock"] if m.get("clock") else "") + ("?" if m.get("auto") else "")
            i = self.mark3.AddControlPoint(vtk.vtkVector3d(*m["xyz"])); self.mark3.SetNthControlPointLabel(i, lab)
        self.mark3.EndModify(wasMod)
        self._drawGreen(); self._listsChanged()

    def _prefillMarkers(self):
        from scipy.spatial import cKDTree
        tree = cKDTree(self.P)
        for name, abbr, keys in BRANCHES:
            m = self._mask(keys)
            if m is None or m.sum() < 30: continue
            pts = self._pts(m)
            if len(pts) > 20000: pts = pts[np.random.default_rng(0).choice(len(pts), 20000, replace=False)]
            d, i = tree.query(pts)
            if d.min() > 25: continue
            self.addMarker(name, float(self.s[i[np.argmin(d)]]), auto=True)
        lowest = None
        for keys in (("kidney right",), ("kidney left",)):
            m = self._mask(keys)
            if m is None or m.sum() < 100: continue
            pts = self._pts(m); d, i = tree.query(pts)
            if d.min() > 60: continue
            s = float(self.s[i[np.argmin(d)]]); lowest = s if lowest is None else max(lowest, s)
        if lowest is not None: self.addMarker("最下位腎動脈", lowest, auto=True)
        if len(self.curves) >= 2 and getattr(self, "sharedLen", 0) < self.length: self.addMarker("大動脈分岐", self.sharedLen, auto=True)

    # ---------------------------------------------------------------- 手動計測（画面に残る・一覧・出力に入る）
    MEASURES = [("line", "直線", "vtkMRMLMarkupsLineNode", "L", (1.0, 0.85, 0.2)),
                ("poly", "連続線", "vtkMRMLMarkupsCurveNode", "P", (0.45, 1.0, 0.6)),
                ("curve", "カーブ", "vtkMRMLMarkupsCurveNode", "C", (0.4, 0.9, 1.0)),
                ("area", "面積", "vtkMRMLMarkupsClosedCurveNode", "A", (1.0, 0.55, 0.9)),
                ("angle", "角度", "vtkMRMLMarkupsAngleNode", "Ang", (1.0, 0.7, 0.3))]
    VIEW_JA = {"Red": "断面", "Yellow": "軸位", "Green": "ストレッチ", "3D": "3D"}

    def _placing(self):
        inter = slicer.app.applicationLogic().GetInteractionNode()
        return inter.GetCurrentInteractionMode() == inter.Place

    def measureNodes(self):
        self.measures = [n for n in getattr(self, "measures", []) if slicer.mrmlScene.IsNodePresent(n)]
        return self.measures

    def startMeasure(self, kind):
        """直線 / 連続線 / カーブ / 面積 / 角度。どのビューでもクリックで置く。置いた後も点はドラッグで直せる"""
        self.cancelMeasure()
        key, lab, cls, pre, col = next(m for m in self.MEASURES if m[0] == kind)
        num = 1 + max([int(n.GetAttribute("SA.num") or 0) for n in self.measureNodes() if n.GetAttribute("SA.measure") == kind] + [0])
        n = slicer.mrmlScene.AddNewNodeByClass(cls, f"{pre}{num}")
        for a, v in (("SA.measure", kind), ("SA.num", str(num)), ("SA.label", f"{lab} {num}"), ("SA.s", f"{self.curS:.2f}"),
                     ("SA.path", self.path or ""), ("SA.rot", f"{self.rot:.1f}"), ("SA.view", "")):
            n.SetAttribute(a, v)
        if kind == "poly": n.SetCurveTypeToLinear()
        try:
            if kind in ("line", "poly", "curve"): n.GetMeasurement("length").SetEnabled(True)
            if kind == "angle": n.GetMeasurement("angle").SetEnabled(True)
            if kind == "area": n.GetMeasurement("area").SetEnabled(False); n.GetMeasurement("length").SetEnabled(False)
        except Exception: pass
        d = n.GetDisplayNode()
        d.SetSelectedColor(*col); d.SetColor(*col); d.SetActiveColor(1.0, 1.0, 1.0)
        d.SetTextScale(2.6); d.SetGlyphScale(1.3); d.SetLineThickness(0.25); d.SetPointLabelsVisibility(False)
        try: d.SetPropertiesLabelVisibility(True); d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.5)
        except Exception: pass
        V = slicer.vtkMRMLMarkupsNode
        for ev in (V.PointPositionDefinedEvent, V.PointModifiedEvent, V.PointRemovedEvent, V.PointEndInteractionEvent):
            n.AddObserver(ev, lambda c, e, n=n: self._measChanged(n))
        self.measureNodes().append(n); self._activeMeasure = n
        self._hist = getattr(self, "_hist", []); self._hist.append(("measure", n))
        sel = slicer.app.applicationLogic().GetSelectionNode()
        sel.SetReferenceActivePlaceNodeClassName(cls); sel.SetActivePlaceNodeID(n.GetID())
        inter = slicer.app.applicationLogic().GetInteractionNode()
        inter.SetPlaceModePersistence(1 if kind in ("poly", "curve", "area") else 0)   # 多点は右クリック / Enter で終わり
        inter.SetCurrentInteractionMode(inter.Place)
        return n

    def finishMeasure(self):
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place: inter.SetCurrentInteractionMode(inter.ViewTransform)
        n = getattr(self, "_activeMeasure", None); self._activeMeasure = None
        if n is not None and slicer.mrmlScene.IsNodePresent(n):
            need = {"line": 2, "poly": 2, "curve": 2, "area": 3, "angle": 3}[n.GetAttribute("SA.measure")]
            if n.GetNumberOfDefinedControlPoints() < need: slicer.mrmlScene.RemoveNode(n)
        self._listsChanged()

    def cancelMeasure(self):
        if getattr(self, "_activeMeasure", None) is not None: self.finishMeasure()

    def _measChanged(self, n):
        if not slicer.mrmlScene.IsNodePresent(n): return
        if not n.GetAttribute("SA.view") and n.GetNumberOfDefinedControlPoints() >= 1:
            v = getattr(self, "_lastView", "Red") or "Red"
            n.SetAttribute("SA.view", v)
            if v == "Orange": v = "Green"; n.SetAttribute("SA.view", v)
            ids = {"Green": ["vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeOrange"]}.get(v, ["vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeYellow", "vtkMRMLViewNode1"])
            n.GetDisplayNode().SetViewNodeIDs(ids)               # ストレッチ像の上の計測は、別の座標なのでそこだけに出す
            if v == "Red": n.SetAttribute("SA.s", f"{self.curS:.2f}"); n.SetAttribute("SA.rot", f"{self.rot:.1f}"); n.SetAttribute("SA.path", self.path or "")
        if n.GetAttribute("SA.measure") == "area":
            v = self.measureValue(n)
            nm = f"A{n.GetAttribute('SA.num')} {v[0]:.0f} mm2" if v else n.GetName()
            if n.GetName() != nm: n.SetName(nm)
        kind = n.GetAttribute("SA.measure")
        need = {"line": 2, "angle": 3}.get(kind)
        if need and n.GetNumberOfDefinedControlPoints() >= need and getattr(self, "_activeMeasure", None) is n:
            qt.QTimer.singleShot(0, self.finishMeasure)
        self._listsChanged()

    def measureValue(self, n):
        """(数値, 単位, 表示用の文字)"""
        kind = n.GetAttribute("SA.measure"); nd = n.GetNumberOfDefinedControlPoints()
        try:
            if kind == "line" and nd >= 2:
                v = float(n.GetLineLengthWorld()); return v, "mm", f"{v:.1f} mm"
            if kind in ("poly", "curve") and nd >= 2:
                v = float(n.GetCurveLengthWorld()); return v, "mm", f"{v:.1f} mm"
            if kind == "angle" and nd >= 3:
                v = float(n.GetAngleDegrees()); return v, "°", f"{v:.0f}°"
            if kind == "area" and nd >= 3:
                P = slicer.util.arrayFromMarkupsCurvePoints(n, world=True)
                c = P.mean(0); _, _, vt = np.linalg.svd(P - c, full_matrices=False)
                q = (P - c) @ vt[:2].T; x, y = q[:, 0], q[:, 1]
                a = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
                return a, "mm²", f"{a:.0f} mm² (Deq {2 * math.sqrt(a / math.pi):.1f})"
        except Exception as e: print("measure:", e)
        return None

    def measureRows(self):
        rows = []
        for n in self.measureNodes():
            v = self.measureValue(n); kind = n.GetAttribute("SA.measure")
            lab = next((m[1] for m in self.MEASURES if m[0] == kind), kind)
            where = self.VIEW_JA.get(n.GetAttribute("SA.view") or "", "—")
            try: s = float(n.GetAttribute("SA.s"))
            except Exception: s = None
            rows.append(dict(node=n, name=n.GetAttribute("SA.label") or n.GetName(), kind=lab, value=v[2] if v else "（置いている途中）",
                             num=v[0] if v else None, where=where, s=s, pos=(f"{self.rel(s):+.1f} mm" if (s is not None and where == "断面") else "")))
        return rows

    def jumpToMeasure(self, n):
        v = n.GetAttribute("SA.view")
        try:
            if v == "Red":
                p = n.GetAttribute("SA.path")
                if p and p != self.path and p in self.curves: self._switch(p, float(n.GetAttribute("SA.s")))
                self.setRotation(float(n.GetAttribute("SA.rot") or 0)); self.setPosition(float(n.GetAttribute("SA.s")))
            elif n.GetNumberOfControlPoints():
                c = np.mean([n.GetNthControlPointPositionWorld(i) for i in range(n.GetNumberOfControlPoints())], axis=0)
                if v == "Yellow": slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode().JumpSliceByCentering(*c)
        except Exception as e: print("jump:", e)

    def deleteMeasure(self, n):
        if getattr(self, "_activeMeasure", None) is n: self._activeMeasure = None
        if slicer.mrmlScene.IsNodePresent(n): slicer.mrmlScene.RemoveNode(n)
        self._listsChanged()

    def clearMeasures(self):
        self.cancelMeasure()
        for n in list(self.measureNodes()): slicer.mrmlScene.RemoveNode(n)
        self.measures = []; self._listsChanged()

    def undoLast(self):
        pend = getattr(self, "pendingFix", None)
        if pend:
            pend.pop(); self._drawPending()
            if getattr(self, "_fixLab", None) is not None: self._fixHud(True)
            cb = getattr(self, "onFixChanged", None)
            if cb: cb()
            return "最後の修正点を消しました"
        """最後にしたこと（計測 or マーカー）を 1 つ戻す"""
        hist = getattr(self, "_hist", [])
        while hist:
            kind, obj = hist.pop()
            if kind == "measure" and slicer.mrmlScene.IsNodePresent(obj): self.deleteMeasure(obj); return "計測を 1 つ戻しました"
            if kind == "center":
                path, cps = obj; c = self.curves.get(path)
                if c is None or path != self.path: continue
                c.RemoveAllControlPoints()
                for q in cps: c.AddControlPoint(vtk.vtkVector3d(*q))
                self._rebuildKeep(); return "中心線の修正を 1 つ戻しました"
            if kind == "marker":
                name, prev = obj
                self.markers = [m for m in self.markers if m["name"] != name]
                if prev is not None: self.markers.append(prev); self.markers.sort(key=lambda m: m["s"])
                self._drawMarkers(); return f"「{name}」を戻しました"
        n = (self.measureNodes() or [None])[-1]
        if n is not None: self.deleteMeasure(n); return "計測を 1 つ戻しました"
        return "戻せるものがありません"

    def _listsChanged(self):
        t = getattr(self, "_lcTimer", None)
        if t is None:
            t = self._lcTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(60)
            t.connect("timeout()", lambda: getattr(self, "onListsChanged", lambda: None)())
        t.start()

    # ---------------------------------------------------------------- 断面を記録（ピン）
    def pinSection(self):
        n = 1 + max([int(m["name"][2:]) for m in self.markers if m["name"].startswith("断面") and m["name"][2:].isdigit()] + [0])
        self.addMarker(f"断面{n}"); return f"断面{n}"

    # ---------------------------------------------------------------- テンプレートの手順
    def stepPath(self, name):
        if name.startswith("右") and "大動脈→右腸骨" in self.curves: return "大動脈→右腸骨"
        if name.startswith("左") and "大動脈→左腸骨" in self.curves: return "大動脈→左腸骨"
        return None

    def suggest(self, name):
        """その項目の、だいたいの位置（mm）。わからなければ None"""
        m = self._mk(name)
        if m is not None: return m["s"], m["path"]
        path = self.stepPath(name) or self.path
        try:
            if name == "瘤の最大径":
                a = self._mk("ネック終端（瘤の始まり）") or self._mk("最下位腎動脈"); b = self._mk("大動脈分岐")
                if a and b and self.prof is not None:
                    k0, k1 = sorted((self._k(a["s"]), self._k(b["s"])))
                    if k1 > k0: k = k0 + int(np.nanargmax(self.prof[k0:k1, 2])); return float(self.s[k]), self.path
            if name == "ネック終端（瘤の始まり）":
                r = self._mk("最下位腎動脈"); b = self._mk("大動脈分岐")
                if r and b and self.prof is not None:
                    k0, k1 = self._k(r["s"]), self._k(b["s"]); base = np.nanmedian(self.prof[k0:k0 + int(10 / STEP), 1])
                    for k in range(k0 + int(5 / STEP), k1):
                        if self.prof[k, 1] > base * 1.15: return float(self.s[k]), self.path
            if name.endswith("遠位（総大腿）") and path in self.frames:
                fem = self._mask(("femur right",) if name.startswith("右") else ("femur left",))
                if fem is not None and fem.sum() > 500:
                    ztop = self._pts(fem)[:, 2].max(); P = self.frames[path]["P"]
                    k = int(np.argmin(np.abs(P[:, 2] - (ztop - 10)))); return float(k * STEP), path
            if name == "近位ランディング":
                l = self._mk("左鎖骨下動脈")
                if l: return l["s"] + 10.0, self.path
        except Exception as e: print("suggest:", e)
        return None

    # ---------------------------------------------------------------- クロック位置
    def startClock(self, cb):
        self._clockCb = cb

    def _setClock(self, ras):
        k = self._k(); T = self.T[k]; v = ras - self.P[k]
        ant = np.array([0, 1.0, 0]); ant -= (ant @ T) * T; ant /= np.linalg.norm(ant) + 1e-9
        left = np.array([-1.0, 0, 0]); left -= (left @ T) * T; left /= np.linalg.norm(left) + 1e-9
        clk = _clock(float(v @ left), float(v @ ant))
        self.clockNode.RemoveAllControlPoints(); i = self.clockNode.AddControlPoint(vtk.vtkVector3d(*ras)); self.clockNode.SetNthControlPointLabel(i, clk)
        near = [m for m in self.markers if self._onPath(m) and abs(m["s"] - self.curS) < 5]
        if near: near[0]["clock"] = clk; name = near[0]["name"]
        else: self.addMarker(f"入口 {clk}", clock=clk); name = f"入口 {clk}"
        self._drawMarkers()
        return f"クロック位置 {clk}（12 時 = 前、3 時 = 患者の左）を「{name}」に記録しました。"

    def _mk(self, name):
        for m in self.markers:
            if m["name"] == name: return m
        return None
