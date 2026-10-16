# -*- coding: utf-8 -*-
"""大動脈サイジング: 断面の輪郭（外周・内腔）と径・径の推移
AortaSizingLogic の一部（SectionMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class SectionMixin:

    # ---------------------------------------------------------------- 断面（表面を平面で切る）
    def _cutter(self, mode):
        c = self._cutters.get(mode)
        if c is None:
            pl = vtk.vtkPlane(); cut = vtk.vtkCutter(); cut.SetInputData(self.surf[mode]); cut.SetCutFunction(pl)
            con = vtk.vtkPolyDataConnectivityFilter(); con.SetInputConnection(cut.GetOutputPort()); con.SetExtractionModeToClosestPointRegion()
            st = vtk.vtkStripper(); st.SetInputConnection(con.GetOutputPort()); st.JoinContiguousSegmentsOn()
            c = self._cutters[mode] = (pl, con, st)
        return c

    def _section(self, k, mode=None, path=None):
        """断面の輪郭（2D 座標、mm）。手直しがあればそれ。無ければ AI ラベルの輪郭を目安に、元の CT 上で縁を正確化"""
        mode = mode or self.mode; path = path or self.path
        key = (path, mode, int(k))
        ov = self.override.get(key)
        if ov is not None: return ov
        if key in self.cache: return self.cache[key]
        xy = None
        if getattr(self, "precise", True):
            try:
                gl = self._sectionSurf(k, "lumen", path); go = self._sectionSurf(k, "outer", path)
                both = self._edgeContour(int(k), path, "both", gl, go)
                if both is not None:
                    for md, v in zip(("lumen", "outer"), both):
                        kk = (path, md, int(k))
                        if kk not in self.cache and v is not None: self.cache[kk] = v
                    xy = both[0] if mode == "lumen" else both[1]
            except Exception as e:
                print("edge:", e); xy = None
        if xy is None: xy = self._sectionSurf(k, mode, path)
        self.cache[key] = xy
        return xy

    def _sectionSurf(self, k, mode, path):
        """AI ラベルから作った血管表面を、中心線に直交する面で切った輪郭（目安）"""
        key = ("surf", path, mode, int(k))
        if key in self.cache: return self.cache[key]
        F = self.frames[path]; P, T, N, B = F["P"][k], F["T"][k], F["N"][k], F["B"][k]
        pl, con, st = self._cutter(mode)
        pl.SetOrigin(*P); pl.SetNormal(*T); con.SetClosestPoint(*P)
        cut = con.GetInputAlgorithm(); cut.Update(); xy = None
        if cut.GetOutput().GetNumberOfPoints() == 0:                       # 何も切れない（その面に血管表面が無い）→ VTK の警告を出さない
            self.cache[key] = None; return None
        st.Update(); pd = st.GetOutput()
        if pd.GetNumberOfLines():
            from vtk.util.numpy_support import vtk_to_numpy
            pts = vtk_to_numpy(pd.GetPoints().GetData()); ids = vtk.vtkIdList(); best = None
            lines = pd.GetLines(); lines.InitTraversal()
            while lines.GetNextCell(ids):
                idx = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]
                if best is None or len(idx) > len(best): best = idx
            q = pts[best] - P
            xy = _resample(np.c_[q @ B, q @ N])
            if xy is not None and (np.hypot(*xy.mean(0)) > 25 or _polyMetrics(xy)["dmax"] > 2 * HALF): xy = None
        self.cache[key] = xy
        return xy

    # ---------------------------------------------------------------- 正確な輪郭: 元の CT 上で、中心から放射状に「濃さが一番急に変わる所」を探す（サブピクセル）
    NRAY = 120
    RAY_DR = 0.15

    def _ensureArrF(self):
        if getattr(self, "arrF", None) is None:
            from scipy import ndimage
            self.arr = slicer.util.arrayFromVolume(self.vol).astype(np.float32)
            self.arrF = ndimage.spline_filter(self.arr, order=3, mode="nearest")
        if getattr(self, "_rasToIjk", None) is None: self._rasToIjk = np.linalg.inv(self._ijk2ras())

    @staticmethod
    def _polar(xy, c, th):
        q = xy - c; a = np.arctan2(q[:, 1], q[:, 0]); r = np.hypot(q[:, 0], q[:, 1])
        o = np.argsort(a); a, r = a[o], r[o]
        return np.interp(th, a, r, period=2 * np.pi)

    def _rays(self, P, B, N, c, th, R):
        from scipy import ndimage
        d = np.c_[np.cos(th), np.sin(th)]                                   # 断面内の向き
        X = c[None, None, :] + R[None, :, None] * d[:, None, :]              # (ray, r, 2)
        W = P + X[..., :1] * B + X[..., 1:] * N                              # 世界座標
        A = self._rasToIjk; H = W.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
        prof = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=3, prefilter=False, mode="nearest").reshape(len(th), len(R))
        return ndimage.gaussian_filter(prof, (0.8, 1.0)), d

    def _cleanRadii(self, r, ref):
        from scipy import ndimage
        med = ndimage.median_filter(r, size=9, mode="wrap")
        bad = np.abs(r - med) > np.maximum(1.5, 0.15 * med)
        r = np.where(bad, med, r)
        r = ndimage.gaussian_filter1d(r, 1.2, mode="wrap")
        return np.clip(r, 0.3 * ref.min(), None)

    def _blobGuide(self, P, B, N, c0, rlim):
        """元の CT で、中心線のそばの造影された塊（内腔）を直接さがして目安の円にする（ラベルが細い・ずれている時）"""
        from scipy import ndimage
        h = 0.25; u = np.arange(-rlim, rlim + 1e-6, h); UU, VV = np.meshgrid(u, u)
        W = P + (c0[0] + UU)[..., None] * B + (c0[1] + VV)[..., None] * N
        A = self._rasToIjk; H = W.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
        img = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=1, prefilter=False, mode="nearest").reshape(UU.shape)
        m = ndimage.binary_opening((img > self.thr) & (img < 1200) & (UU ** 2 + VV ** 2 <= rlim ** 2), iterations=2)
        lab, n = ndimage.label(m)
        if n == 0: return None
        ii = np.argwhere(m); d2 = (UU[m] ** 2 + VV[m] ** 2)
        j = int(np.argmin(d2))
        if d2[j] > 6.0 ** 2: return None                                    # 中心線から 6 mm 以内に造影の塊が無い
        comp = lab == lab[tuple(ii[j])]
        area = comp.sum() * h * h
        cx, cy = UU[comp].mean() + c0[0], VV[comp].mean() + c0[1]
        return np.array([cx, cy]), math.sqrt(area / math.pi), area

    def _edgeContour(self, k, path, mode, gl, go):
        """gl / go: AI ラベル由来の内腔 / 外周の輪郭（目安）。戻り値: 正確化した輪郭 (NPOLY, 2) か None"""
        self._ensureArrF()
        F = self.frames[path]; P, B, N = F["P"][k], F["B"][k], F["N"][k]
        ref = gl if gl is not None else go
        c0 = ref.mean(0) if ref is not None else np.zeros(2)
        rg = math.sqrt(_polyMetrics(ref)["area"] / math.pi) if ref is not None else 0.0
        bl = self._blobGuide(P, B, N, c0, float(min(max(2.5 * rg + 8.0, 14.0), 30.0)))
        if bl is not None:
            cb, rb, ab = bl
            small = rg < 6.0                                                   # 腸骨など細い所はラベルが細く・ずれやすい
            use = gl is None or (small and (ab > 1.6 * math.pi * rg * rg or np.linalg.norm(cb - c0) > max(1.5, 0.4 * rg)))
            if use and (gl is None or ab < 5.0 * math.pi * rg * rg + 60.0):     # ラベルより造影の塊を信じる（大きすぎる塊＝骨などは除く）
                t = np.linspace(-np.pi, np.pi, NPOLY, endpoint=False)
                gl = cb + rb * np.c_[np.cos(t), np.sin(t)]
                if go is None or _polyMetrics(go)["area"] < 1.1 * ab: go = cb + (rb + 1.0) * np.c_[np.cos(t), np.sin(t)]
        if gl is None: return None
        th = np.linspace(-np.pi, np.pi, self.NRAY, endpoint=False)
        c = gl.mean(0)
        rgl = self._polar(gl, c, th); rgo = self._polar(go, c, th) if go is not None else rgl * 1.15
        rmax = float(min(1.5 * max(rgo.max(), rgl.max()) + 6.0, 60.0))
        R = np.arange(0.0, rmax, self.RAY_DR)
        prof, d = self._rays(P, B, N, c, th, R)
        dr = self.RAY_DR; g = np.gradient(prof, dr, axis=1)
        center = prof[:, R < max(1.0, 0.35 * rgl.min())]
        Ilum = float(np.median(center)) if center.size else float(np.median(prof[:, :5]))
        calcT = Ilum + max(150.0, 0.35 * abs(Ilum))
        rl = rgl.copy(); okL = np.zeros(len(th), bool)
        for j in range(len(th)):                                             # 内腔: 半値（内腔とすぐ外の組織の中間）を最初に下回る所
            lo, hi = 0.3 * rgl[j], 1.35 * rgl[j] + 3.0
            w = np.where((R >= lo) & (R <= hi))[0]
            if len(w) < 4: continue
            pj = prof[j, w]
            T0 = 0.5 * (Ilum + 60.0)
            cal = np.where(pj > calcT)[0]; bel = np.where(pj < T0)[0]
            if len(cal) and (not len(bel) or cal[0] < bel[0]):              # 先に石灰化に当たる → 立ち上がりの中点が内腔の縁
                ic = cal[0]; peak = pj[ic:ic + int(2.0 / dr)].max(); half = 0.5 * (Ilum + peak)
                rise = np.where(pj[:ic + 1] >= half)[0]
                if len(rise):
                    i = rise[0]
                    if i > 0: rl[j] = R[w[i - 1]] + (half - pj[i - 1]) / max(pj[i] - pj[i - 1], 1e-6) * dr
                    else: rl[j] = R[w[i]]
                    okL[j] = True
                continue
            if not len(bel): continue
            ri = R[w[bel[0]]]
            outside = prof[j, (R >= ri + 1.0) & (R <= ri + 2.5)]
            Iout = float(min(np.median(outside), 150.0)) if outside.size else 60.0
            if Ilum - Iout < 80.0: continue                                  # コントラストが足りない → 目安のまま
            T = 0.5 * (Ilum + Iout); b2 = np.where(pj < T)[0]
            if not len(b2): continue
            i = b2[0]
            if i > 0: rl[j] = R[w[i - 1]] + (pj[i - 1] - T) / max(pj[i - 1] - pj[i], 1e-6) * dr   # 線形補間でサブピクセル
            else: rl[j] = R[w[i]]
            okL[j] = True
        if okL.mean() < 0.4: return None if mode != "both" else None
        rl = self._cleanRadii(np.where(okL, rl, rgl), rgl)
        lum = _resample(c + rl[:, None] * d)
        if mode == "lumen": return lum
        ro = rgo.copy(); okO = np.zeros(len(th), bool)
        for j in range(len(th)):
            lo, hi = rl[j] + 0.5, max(rgo[j], rl[j] + 1.0) + 2.5               # 目安（ラベル）から 2.5mm 以内だけ探す
            w = np.where((R >= lo) & (R <= hi))[0]
            if len(w) < 4: continue
            gj = g[j, w]; pj = prof[j, w]
            after = np.r_[pj[int(1.0 / dr):], np.full(int(1.0 / dr), pj[-1])][:len(pj)]
            cand = np.where((after < 20.0) & (gj < -30.0))[0]                # 外は脂肪・肺（低い CT 値）へ落ちる所
            if not len(cand): continue
            i = cand[np.argmin(np.abs(R[w[cand]] - rgo[j]) + 0.02 * gj[cand])]  # 目安に近く、変化が急な所
            ro[j] = R[w[i]]; okO[j] = True
        if okO.mean() < 0.4: out = _resample(c + np.maximum(rgo, rl + 0.5)[:, None] * d) if go is not None else None
        else:
            ro = self._cleanRadii(np.where(okO, ro, rgo), rgo)
            out = _resample(c + np.maximum(ro, rl + 0.3)[:, None] * d)
        return (lum, out) if mode == "both" else out

    def _metK(self, k, mode=None, path=None):
        xy = self._section(k, mode, path)
        m = _polyMetrics(xy) if xy is not None else None
        if m is not None:
            m["xy"] = xy; m["edited"] = (path or self.path, mode or self.mode, int(k)) in self.override
        return m

    def _k(self, s=None, path=None):
        F = self.frames[path or self.path]
        return int(min(max(round((self.curS if s is None else s) / STEP), 0), len(F["P"]) - 1))

    def metricsAt(self, s=None, path=None):
        if not self.frames or self.path is None: return None
        path = path or self.path
        if path not in self.frames: return None
        m = self._metK(self._k(s, path), None, path)
        if m is None: return None
        return dict(area=m["area"], deq=m["deq"], dmax=m["dmax"], dmin=m["dmin"], edited=m["edited"])

    def rel(self, s):
        return float(s) - (self.baseS if self.baseS is not None else 0.0)

    def _profile(self, reuse=None):
        K = len(self.s); ks = np.arange(0, K, 4)
        res = np.full((K, 4), np.nan)
        if reuse is not None:                                          # 局所の修正: 変わっていない所は前の値をそのまま使う
            old, a, b, shift = reuse
            res[:a] = old[:a]; res[b + 1:] = old[b + 1 - shift:]
            ks = np.arange(a - a % 4, b + 1, 4)
        for k in ks:
            m = self._metK(int(k))
            if m: res[k] = (m["area"], m["deq"], m["dmax"], m["dmin"])
        for i in range(4):                                             # 2 mm ごとの値を 0.5 mm に補間（グラフ用）
            ok = ~np.isnan(res[:, i])
            if ok.sum() > 1: res[:, i] = np.interp(self.s, self.s[ok], res[ok, i])
        self.prof = res
        tbl = slicer.mrmlScene.GetFirstNodeByName("SA 径の推移") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "SA 径の推移")
        from vtk.util.numpy_support import numpy_to_vtk
        vt = vtk.vtkTable()                                                    # 列を消してから足すとグラフが一瞬「列なし」になり警告が出るので、表ごと差し替える
        for name, data in (("s", self.s), ("Max", res[:, 2]), ("Min", res[:, 3]), ("Deq", res[:, 1])):
            a = numpy_to_vtk(np.ascontiguousarray(np.nan_to_num(data[::4], nan=0.0), dtype=np.float32), deep=True); a.SetName(name)
            vt.AddColumn(a)
        tbl.SetAndObserveTable(vt)
        chart = slicer.mrmlScene.GetFirstNodeByName("SA 径グラフ") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "SA 径グラフ")
        if chart.GetNumberOfPlotSeriesNodes() == 0:
            for n in list(slicer.util.getNodesByClass("vtkMRMLPlotSeriesNode")):
                if n.GetAttribute("SA"): slicer.mrmlScene.RemoveNode(n)
            for col, rgb in (("Max", (0.85, 0.25, 0.2)), ("Min", (0.2, 0.45, 0.85)), ("Deq", (0.45, 0.45, 0.45))):
                ps = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", col); ps.SetAttribute("SA", col)
                ps.SetAndObserveTableNodeID(tbl.GetID()); ps.SetXColumnName("s"); ps.SetYColumnName(col)
                ps.SetPlotType(ps.PlotTypeScatter); ps.SetMarkerStyle(ps.MarkerStyleNone); ps.SetLineStyle(ps.LineStyleSolid); ps.SetColor(*rgb); ps.SetLineWidth(2)
                chart.AddAndObservePlotSeriesNodeID(ps.GetID())
            chart.SetXAxisTitle("Distance from origin (mm)"); chart.SetYAxisTitle("Diameter (mm)")
        chart.SetLegendVisibility(False); chart.SetXAxisRangeAuto(False); chart.SetXAxisRange(0.0, max(self.length, 1.0)); chart.SetYAxisRangeAuto(True)
        chart.SetTitle(f"{PATH_EN.get(self.path, '')}  {'outer' if self.mode == 'outer' else 'lumen'}   red=Max  blue=Min  gray=Deq")
        tbl.Modified(); self.chart = chart

    def setMode(self, mode):
        self.mode = mode
        if self.prof is not None: self._profile(); self._showContour()

    def undoContour(self):
        self.override.pop((self.path, self.mode, self._k()), None)
        self._refreshK(self._k())

    def _refreshK(self, k):
        m = self._metK(k)
        if m and self.prof is not None: self.prof[k] = (m["area"], m["deq"], m["dmax"], m["dmin"])
        self._showContour()
