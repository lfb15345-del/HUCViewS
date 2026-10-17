# -*- coding: utf-8 -*-
"""大動脈サイジング: TEVAR の計画: 仮想グラフト（広がりの予測）・SINE の目安・エントリー・治療長
AortaSizingLogic の一部（TevarPlanMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class TevarPlanMixin:

    # ================================================================ TEVAR 計画（仮想グラフト）と術後 CT との比較
    # 中心線の上に、置きたい範囲（近位端〜遠位端）でカバードステントを描く。エントリー・分枝を覆うかを色で示す。
    # 術後 CT は背骨で術前に重ね合わせ、金属（ステントの骨組み）から実際のグラフトの範囲を出して、計画とのずれを中心線に沿って測る。
    OVERSIZE = 0.10
    BRANCH_NAMES = ("腕頭動脈", "左総頸動脈", "左鎖骨下動脈", "腹腔動脈", "上腸間膜動脈", "最下位腎動脈", "右腎動脈", "左腎動脈")
    STATE_COL = {"cover": (0.25, 0.85, 0.35), "edge": (1.0, 0.8, 0.2), "open": (1.0, 0.3, 0.3), "block": (1.0, 0.3, 0.3), "ok": (0.6, 0.8, 1.0)}

    def planInit(self, force=False):
        """計画の初期値: テンプレートの近位/遠位ランディング（無ければ左鎖骨下 +10 mm から 150 mm）"""
        pl = getattr(self, "plan", None)
        if pl is not None and not force and pl.get("path") in self.frames: return pl
        p = self._mk("近位ランディング"); d = self._mk("遠位ランディング"); l = self._mk("左鎖骨下動脈")
        sp = p["s"] if p else ((l["s"] + 10.0) if l else float(self.curS))
        sd = d["s"] if d else sp + 150.0
        sd = min(max(sd, sp + 20.0), self.length - 1.0)
        self.plan = dict(path=self.path, p=float(sp), d=float(sd), os=self.OVERSIZE, dp=None, dd=None, on=True)
        return self.plan

    def _landD(self, s, path=None):
        """ランディング部の外径（Deq、前後 5 mm の中央値）"""
        vals = []
        F = self.frames[path or self.path]
        for x in np.arange(s - 5.0, s + 5.01, 2.5):
            try:
                m = self._dia(float(np.clip(x, 0, F["length"])), path, "outer")
                if m and np.isfinite(m["deq"]): vals.append(m["deq"])
            except Exception: pass
        return float(np.median(vals)) if vals else None

    def planDiams(self):
        """[(近位の径, 実測径, 手入力か), (遠位 …)]  径はオーバーサイズを掛けて 2 mm 刻みに切り上げ"""
        pl = self.plan; out = []
        for key, s in (("dp", pl["p"]), ("dd", pl["d"])):
            base = self._landD(s, pl["path"])
            if pl.get(key): out.append((float(pl[key]), base, True)); continue
            nom = None if base is None else 2.0 * math.ceil(base * (1.0 + pl["os"]) / 2.0)
            out.append((nom, base, False))
        return out

    def planSet(self, **kw):
        pl = self.planInit()
        for k, v in kw.items():
            if k in ("p", "d") and v is not None: v = float(np.clip(v, 0.0, self.frames[pl["path"]]["length"]))
            pl[k] = v
        if pl["d"] < pl["p"] + 10: pl["d"] = pl["p"] + 10
        self.planDraw()

    def _tubePD(self, P, N, B, R, nseg=56):
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        n = len(P); th = np.linspace(0, 2 * np.pi, nseg, endpoint=False)
        pts = (P[:, None, :] + R[:, None, None] * (np.cos(th)[None, :, None] * N[:, None, :] + np.sin(th)[None, :, None] * B[:, None, :])).reshape(-1, 3)
        i = np.arange(n - 1)[:, None]; j = np.arange(nseg)[None, :]; j2 = (j + 1) % nseg
        q = np.stack([i * nseg + j, i * nseg + j2, (i + 1) * nseg + j2, (i + 1) * nseg + j], -1).reshape(-1, 4)
        cells = np.c_[np.full(len(q), 4), q].astype(np.int64).ravel()
        vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(pts, np.float64), deep=True))
        ca = vtk.vtkCellArray(); ca.SetCells(len(q), numpy_to_vtkIdTypeArray(cells, deep=True))
        pd = vtk.vtkPolyData(); pd.SetPoints(vp); pd.SetPolys(ca)
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.Update()
        return nm.GetOutput()

    def _zStentsPD(self, F, ks, R, pitch=17.0, height=12.0, apices=5, C=None, Rth=None):
        """Z 型ステント（金属の骨組み）を、グラフトの筒の上に輪で並べる"""
        s = F["s"]; s0, s1 = s[ks[0]], s[ks[-1]]
        app = vtk.vtkAppendPolyData(); c = s0 + 1.0 + height / 2
        th = np.linspace(0, 2 * np.pi, apices * 24, endpoint=False)
        u = th * apices / (2 * np.pi); tri = 4.0 * np.abs(u - np.floor(u) - 0.5) - 1.0
        while c + height / 2 <= s1 - 0.5:
            ss = c + tri * height / 2
            kk = np.clip(np.round(ss / STEP).astype(int), ks[0], ks[-1]); rr = R[kk - ks[0]] * 1.01
            if Rth is not None: rr = _radAt(Rth, kk - ks[0], np.arctan2(np.cos(th), np.sin(th))) * 1.01 + 0.3
            pts = (F["P"] if C is None else C)[kk] + rr[:, None] * (np.cos(th)[:, None] * F["N"][kk] + np.sin(th)[:, None] * F["B"][kk])
            vp = vtk.vtkPoints()
            for p in pts: vp.InsertNextPoint(*p)
            pl = vtk.vtkPolyLine(); pl.GetPointIds().SetNumberOfIds(len(pts) + 1)
            for i in range(len(pts)): pl.GetPointIds().SetId(i, i)
            pl.GetPointIds().SetId(len(pts), 0)
            ca = vtk.vtkCellArray(); ca.InsertNextCell(pl); pd = vtk.vtkPolyData(); pd.SetPoints(vp); pd.SetLines(ca)
            tf = vtk.vtkTubeFilter(); tf.SetInputData(pd); tf.SetRadius(0.4); tf.SetNumberOfSides(8); tf.Update()
            app.AddInputData(tf.GetOutput()); c += pitch
        for k, sgn in ((ks[0], 1), (ks[-1], -1)):                            # 両端の金のマーカー（X 線で見える印）
            kk = int(np.clip(k + sgn * int(1.5 / STEP), ks[0], ks[-1]))
            for a in (0, np.pi / 2, np.pi, 3 * np.pi / 2):
                ra = R[kk - ks[0]] if Rth is None else float(_radAt(Rth, np.array([kk - ks[0]]), np.array([math.atan2(math.cos(a), math.sin(a))]))[0])
                p = (F["P"] if C is None else C)[kk] + ra * 1.02 * (np.cos(a) * F["N"][kk] + np.sin(a) * F["B"][kk])
                sp = vtk.vtkSphereSource(); sp.SetCenter(*p); sp.SetRadius(1.1); sp.SetThetaResolution(12); sp.SetPhiResolution(8); sp.Update()
                app.AddInputData(sp.GetOutput())
        app.Update(); return app.GetOutput()

    def _model(self, name, pd, color, opacity=1.0, slice2D=False, spec=0.3):
        m = slicer.mrmlScene.GetFirstNodeByName(name)
        if m is None or not m.IsA("vtkMRMLModelNode"):
            m = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name); m.CreateDefaultDisplayNodes()
        m.SetAndObservePolyData(pd); d = m.GetDisplayNode()
        d.SetColor(*color); d.SetOpacity(opacity); d.SetScalarVisibility(False); d.SetBackfaceCulling(False)
        d.SetSpecular(spec); d.SetPower(30); d.SetAmbient(0.15); d.SetDiffuse(0.8)
        d.SetVisibility2D(bool(slice2D)); d.SetSliceIntersectionThickness(2)
        d.RemoveAllViewNodeIDs(); d.AddViewNodeID("vtkMRMLViewNode1")
        if slice2D: d.AddViewNodeID("vtkMRMLSliceNodeRed")
        d.SetVisibility(True); return m

    # ================================================================ 仮想グラフトの「広がった形」
    #  慢性（フラップが硬い）: グラフトは真腔の周径に沿って広がる。三日月の真腔ではフラップが伸びて平らになる所まで
    #     → 径 ≒ 真腔の長径（グラフトの径が上限）。壁の中で真腔をいちばん多く覆う位置。三日月の両端は残る（ガター）。
    #     この症例の術後 CT で確かめた: 径の誤差 中央値 2.4 mm、中心のずれ 4.3 mm
    #  急性（フラップが動く）: 壁の中で丸く広がる（グラフトの径まで、大動脈の内側が上限）
    #  解離でない所（真腔 = 内腔全体）は、内腔の中で径まで広がり、楕円の所は壁に押されて沿う
    GRAFT_END_MM = 20.0      # 「端はあるがまま」の時、両端のこの長さで、押し広げた形から真腔のあるがままの形へなめらかに戻る
    ELL_RATIO = 0.82         # 解離（慢性）: 広がったグラフトの短径/長径。この症例の術後 CT で中央値 0.82（0.76〜0.86）
    ELL_PLUS = 0.0           # 長径 = 真腔の長径（足し算なし）。+3 mm でも試したが、楕円で測った実際の径・中心のずれは 0 の方が近かった（22.2/23.2 mm・2.9 mm vs 24.3・4.1 mm）
    GRAFT_WALL_MM = 1.5      # 外周（壁の外側）から、この厚みぶん内側までしかグラフトは広がらない
    NTH = 72

    def _aortaIn(self, k, path):
        """断面 k の大動脈の内側までの距離（mm、外周 − 壁の厚み。外は負）。伸ばした画像の格子で"""
        from scipy import ndimage
        cache = self.__dict__.setdefault("_aoInCache", {})
        kq = int(min(max(4 * round(k / 4.0), 0), len(self.frames[path]["P"]) - 1))
        xy = self._section(kq, "outer", path)
        if xy is None or len(xy) < 6: return None
        key = (path, kq, id(xy))
        if key in cache: return cache[key][1]
        if len(cache) > 3000: cache.clear()
        nu = int(round(2 * HALF / STEP)) + 1
        E = ndimage.distance_transform_edt(_rasterPoly(np.asarray(xy, float), nu)) * STEP - self.GRAFT_WALL_MM
        cache[key] = (xy, E); return E

    def _deploy(self, k, Rn, path, flap, useTL, axis="cl"):
        """断面 k で広がったグラフト: (中心 u, v, 半径の輪 Rth[72], ガター mm², 名目の半径)"""
        from scipy.signal import fftconvolve
        E = self._aortaIn(k, path)
        if E is None: return None
        Ai = E > 0; Emax = float(E.max())
        if Emax < 2.0: return None
        TLm = self.tl["masks"][k] if useTL else None
        if TLm is None or TLm.shape != Ai.shape or TLm.sum() < 8: TLm = Ai; useTL = False
        if useTL and flap == "fixed": return self._deployFixed(k, Rn, path, TLm, Ai, E)
        r = Rn; ell = None
        if useTL and flap == "chronic":
            xy = self._tlXY(k); mt = _polyMetrics(xy) if xy is not None else None
            if mt and mt["dmin"] / max(mt["dmax"], 1e-6) < 0.8:                 # 三日月・楕円の真腔: 楕円のまま広がる（長軸は真腔の長径の向き）
                a_, b_ = mt["maxLine"]; phi = math.atan2(b_[1] - a_[1], b_[0] - a_[0])
                A = min(Rn, (mt["dmax"] + self.ELL_PLUS) / 2.0); ell = (A, A * self.ELL_RATIO, phi); r = A
        elif useTL and flap == "acute":                                          # 急性: フラップがよく動いて丸くなるが、偽腔側の大動脈の真ん中までは行かない → 真腔の長径の円まで
            xy = self._tlXY(k); mt = _polyMetrics(xy) if xy is not None else None
            if mt: r = min(Rn, (mt["dmax"] + self.ELL_PLUS) / 2.0)
        r = float(max(r, 2.0))                                                   # 壁より大きい所は、壁に当たって沿う（下の放射で切る）
        key = (path, int(k), round(r, 1), useTL, id(E), axis, None if ell is None else (round(ell[1], 1), round(ell[2], 2)))
        cache = self.__dict__.setdefault("_depCache", {})
        if key in cache: return cache[key]
        if len(cache) > 6000: cache.clear()
        nu = Ai.shape[0]
        def shapeK():
            kr = int(math.ceil(r / STEP)); yy, xx = np.mgrid[-kr:kr + 1, -kr:kr + 1]
            if ell is None: return ((xx * xx + yy * yy) * STEP * STEP <= r * r).astype(np.float32)
            A, Bm, ph = ell; xu = (xx * math.cos(ph) + yy * math.sin(ph)) * STEP; yv = (-xx * math.sin(ph) + yy * math.cos(ph)) * STEP
            return ((xu / A) ** 2 + (yv / Bm) ** 2 <= 1.0).astype(np.float32)
        if ell is not None:                                                      # 楕円: 壁の中に入る中心だけ
            for _ in range(8):                                                   # 壁の中に入らなければ、少しずつ小さくする
                Kd = shapeK(); feasE = fftconvolve((~Ai).astype(np.float32), Kd, mode="same") < 0.5
                if feasE.any() or r < 4: break
                ell = (ell[0] * 0.92, ell[1] * 0.92, ell[2]); r = ell[0]
        if axis == "cl":                                                         # 作った中心線を軸にする。壁に当たる分だけ、近い所へずらす
            r0 = c0 = HALF / STEP
            ok0 = feasE[int(r0), int(c0)] if ell is not None else E[int(r0), int(c0)] >= r - 0.3
            if not ok0:
                feas = feasE if ell is not None else E >= r - 0.3
                if not feas.any(): feas = E >= E.max() - 0.3
                pts = np.argwhere(feas); j = pts[np.argmin(((pts - (r0, c0)) ** 2).sum(1))]; r0, c0 = float(j[0]), float(j[1])
        else:                                                                    # 真腔をいちばん多く覆う位置へ動かす
            Kd = shapeK()
            ov = fftconvolve(TLm.astype(np.float32), Kd, mode="same")
            feas = feasE if ell is not None else E >= r - 0.3
            if not feas.any(): feas = E >= E.max() - 0.3
            ov[~feas] = -1
            rc, cc = np.argwhere(TLm).mean(0); best = ov.max()
            cand = np.argwhere(ov >= best - max(abs(best) * 0.01, 1e-3)); j = cand[np.argmin(((cand - (rc, cc)) ** 2).sum(1))]   # 同じなら真腔の中心に近い方
            r0, c0 = float(j[0]), float(j[1])
        th = np.linspace(0, 2 * np.pi, self.NTH, endpoint=False); rs = np.arange(0, r + 0.26, 0.25)
        R_ = r0 + np.sin(th)[:, None] * rs[None] / STEP; C_ = c0 + np.cos(th)[:, None] * rs[None] / STEP
        ok = (R_ >= 0) & (R_ <= nu - 1) & (C_ >= 0) & (C_ <= nu - 1)
        ins = np.zeros(ok.shape, bool); ins[ok] = Ai[np.round(R_[ok]).astype(int), np.round(C_[ok]).astype(int)]
        first = np.argmax(~ins, axis=1); first[ins.all(1)] = len(rs) - 1
        Rth = np.maximum(rs[np.maximum(first - 1, 0)], 1.0)                  # 壁に当たる所は壁に沿う
        gy, gx = np.mgrid[0:nu, 0:nu]
        if ell is not None:
            A, Bm, ph = ell; Rth = np.minimum(Rth, A * Bm / np.sqrt((Bm * np.cos(th - ph)) ** 2 + (A * np.sin(th - ph)) ** 2))
            xu = ((gx - c0) * math.cos(ph) + (gy - r0) * math.sin(ph)) * STEP; yv = (-(gx - c0) * math.sin(ph) + (gy - r0) * math.cos(ph)) * STEP
            G = Ai & ((xu / A) ** 2 + (yv / Bm) ** 2 <= 1.0)
        else: G = Ai & (((gy - r0) ** 2 + (gx - c0) ** 2) * STEP * STEP <= r * r)
        gut = float((TLm & ~G).sum() * STEP * STEP) if useTL else 0.0
        out = (c0 * STEP - HALF, r0 * STEP - HALF, Rth, gut, Rn)
        cache[key] = out; return out

    def _deployFixed(self, k, Rn, path, TLm, Ai, E):
        """フラップは動かない: グラフトは術前の真腔の中だけ（細い角はガターとして残る）"""
        from scipy import ndimage
        key = (path, int(k), round(Rn, 1), "fixed", id(E), id(TLm))
        cache = self.__dict__.setdefault("_depCache", {})
        if key in cache: return cache[key]
        G0 = TLm & Ai; rr = max(1, int(round(2.0 / STEP))); yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]
        G = ndimage.binary_opening(G0, structure=(xx * xx + yy * yy) <= rr * rr)
        if G.sum() < 8: G = G0
        D = ndimage.distance_transform_edt(G); j = np.unravel_index(int(np.argmax(D)), D.shape); r0, c0 = float(j[0]), float(j[1])
        nu = G.shape[0]; th = np.linspace(0, 2 * np.pi, self.NTH, endpoint=False); rs = np.arange(0, Rn + 0.26, 0.25)
        R_ = r0 + np.sin(th)[:, None] * rs[None] / STEP; C_ = c0 + np.cos(th)[:, None] * rs[None] / STEP
        ok = (R_ >= 0) & (R_ <= nu - 1) & (C_ >= 0) & (C_ <= nu - 1)
        ins = np.zeros(ok.shape, bool); ins[ok] = G[np.round(R_[ok]).astype(int), np.round(C_[ok]).astype(int)]
        first = np.argmax(~ins, axis=1); first[ins.all(1)] = len(rs) - 1
        Rth = np.maximum(rs[np.maximum(first - 1, 0)], 1.0)
        X = np.c_[Rth * np.cos(th), Rth * np.sin(th)]; ga = 0.5 * abs(np.dot(X[:, 0], np.roll(X[:, 1], -1)) - np.dot(X[:, 1], np.roll(X[:, 0], -1)))
        gut = max(float(TLm.sum() * STEP * STEP) - ga, 0.0)
        out = (c0 * STEP - HALF, r0 * STEP - HALF, Rth, gut, Rn); cache[key] = out; return out

    def _rayLimit(self, k, path, u, v):
        """中心 (u, v) から壁の内側までの距離（72 方向、mm）"""
        E = self._aortaIn(k, path); nu = E.shape[0]; r0, c0 = (v + HALF) / STEP, (u + HALF) / STEP
        th = np.linspace(0, 2 * np.pi, self.NTH, endpoint=False); rs = np.arange(0, 45.0, 0.25)
        R_ = r0 + np.sin(th)[:, None] * rs[None] / STEP; C_ = c0 + np.cos(th)[:, None] * rs[None] / STEP
        ok = (R_ >= 0) & (R_ <= nu - 1) & (C_ >= 0) & (C_ <= nu - 1)
        ins = np.zeros(ok.shape, bool); ins[ok] = E[np.round(R_[ok]).astype(int), np.round(C_[ok]).astype(int)] > 0
        first = np.argmax(~ins, axis=1); first[ins.all(1)] = len(rs) - 1
        return np.maximum(rs[np.maximum(first - 1, 0)], 1.0)

    def _graftGeom(self, lo, hi, Dp, Dd, path):
        """_graftGeom0 の結果を覚えておく（表の更新・比べる のたびに計算し直さない）"""
        pl = getattr(self, "plan", None) or {}; tv = self.tlValid() if self.P is not None else False
        key = (round(float(lo), 2), round(float(hi), 2), round(float(Dp), 2), round(float(Dd), 2), path, self.path, id(self.straight),
               bool(pl.get("tl")), pl.get("flap"), pl.get("ends"), pl.get("axis"), tuple(tuple(float(x) for x in a) for a in (pl.get("adj") or [])),
               tv, id(self.tl) if tv else 0, self.tl.get("ver", 0) if tv else 0, len(self.P) if self.P is not None else 0)
        mem = self.__dict__.setdefault("_ggMemo", {})
        if key in mem:
            F, ks, R, C, gr, nom = mem[key]; self._graftRad = gr; self._graftNominal = nom
            return F, ks, R.copy(), C.copy()
        F, ks, R, C = self._graftGeom0(lo, hi, Dp, Dd, path)
        if len(mem) > 6: mem.clear()
        mem[key] = (F, ks, R.copy(), C.copy(), self._graftRad, self._graftNominal)
        return F, ks, R, C

    def _graftGeom0(self, lo, hi, Dp, Dd, path):
        """仮想グラフトの形。R = 断面ごとの相当半径、C = 中心。self._graftRad に半径の輪（広がった形）も置く"""
        from scipy import ndimage
        F = self.frames[path]; k0, k1 = self._k(lo, path), self._k(hi, path); ks = np.arange(k0, k1 + 1); n = len(ks)
        t = np.linspace(0.0, 1.0, n); Rn = (Dp + (Dd - Dp) * t) / 2.0
        C = F["P"].copy(); R = Rn.copy(); self._graftRad = None; self._graftNominal = Rn
        pl = getattr(self, "plan", None) or {}
        if path == self.path and self.straight is not None and n >= 2:
            try:
                useTL = bool(pl.get("tl")) and self.tlValid(); flap = pl.get("flap", "chronic")
                samp = list(range(0, n, 2))
                if samp[-1] != n - 1: samp.append(n - 1)
                axis = pl.get("axis") or ("tl" if useTL else "cl")              # 解離: ワイヤーは真腔を通るので、真腔に合わせる
                res = [(i, self._deploy(int(ks[i]), float(Rn[i]), path, flap, useTL, axis)) for i in samp]
                res = [(i, r) for i, r in res if r is not None]
                END = self.GRAFT_END_MM if pl.get("ends") == "asis" else 0.0
                if useTL and flap != "fixed" and END > 0 and res:                 # 端: フラップを押し広げきらず、真腔のあるがままの形へなめらかに戻る
                    sL = (ks - ks[0]) * STEP; dEnd = np.minimum(sL, sL[-1] - sL); new = []
                    for i, r in res:
                        wgt = 1.0 if dEnd[i] >= END else 0.5 - 0.5 * math.cos(math.pi * dEnd[i] / END)
                        if wgt < 0.999:
                            f = self._deploy(int(ks[i]), float(Rn[i]), path, "fixed", useTL, axis)
                            if f is not None: r = tuple(wgt * a + (1 - wgt) * b for a, b in zip(r[:4], f[:4])) + (r[4],)
                        new.append((i, r))
                    res = new
                if len(res) >= 2:
                    idx = np.array([i for i, _ in res]); x = np.arange(n)
                    sm = lambda a, sg: ndimage.gaussian_filter1d(a, sg / STEP, axis=0, mode="nearest")
                    cu = sm(np.interp(x, idx, [r[0] for _, r in res]), 2.0); cv = sm(np.interp(x, idx, [r[1] for _, r in res]), 2.0)
                    if flap == "fixed" and useTL:                                    # 真腔の中だけ: 真腔の形に合わせる
                        cu = sm(np.interp(x, idx, [r[0] for _, r in res]), 1.0); cv = sm(np.interp(x, idx, [r[1] for _, r in res]), 1.0)
                    else:                                                            # グラフトは硬い筒: 軸はなめらかに
                        cu = sm(np.interp(x, idx, [r[0] for _, r in res]), 5.0); cv = sm(np.interp(x, idx, [r[1] for _, r in res]), 5.0)
                    Rs = np.array([r[2] for _, r in res]); Rth = np.stack([np.interp(x, idx, Rs[:, j]) for j in range(Rs.shape[1])], 1)
                    Rth = ndimage.gaussian_filter1d(sm(Rth, 1.5), 1.0, axis=1, mode="wrap"); Rth = np.minimum(Rth, Rn[:, None])
                    for s0, du, dv, sc in pl.get("adj", []) or []:                    # 手で直した分（断面でドラッグ）
                        wgt = self._adjW(F["s"][ks], s0, self.ADJ_SOFT); cu = cu + wgt * du; cv = cv + wgt * dv
                        Rth = Rth * (1.0 + wgt * (sc - 1.0))[:, None]
                    Rth = np.minimum(Rth, Rn[:, None])
                    lim = np.stack([self._rayLimit(int(ks[i]), path, cu[i], cv[i]) for i in idx])          # なめらかにした後も、壁は越えない
                    Rth = np.minimum(Rth, np.stack([np.interp(x, idx, lim[:, j]) for j in range(lim.shape[1])], 1))
                    C[ks] = F["P"][ks] + cu[:, None] * F["B"][ks] + cv[:, None] * F["N"][ks]
                    R = np.sqrt((Rth ** 2).mean(1))
                    self._graftRad = dict(path=path, ks=ks, Rth=Rth, cu=cu, cv=cv, Rn=Rn, flap=flap, tl=useTL,
                                          gut=np.interp(x, idx, [r[3] for _, r in res]))
            except Exception as e:
                import traceback; print("graft deploy:", traceback.format_exc())
        return F, ks, R, C

    def roundLanding(self, span=30.0, rmin=0.82):
        """左鎖骨下動脈の直下で、断面が正円になる所（分枝の口を過ぎて 短径/長径 ≥ rmin）。その長さも"""
        l = self._mk("左鎖骨下動脈")
        if not l: return None
        rows = []
        for x in np.arange(l["s"], min(l["s"] + span, self.length - 1.0) + 1e-6, 0.5):
            k = self._k(x); m = None
            if self.tlValid():
                xy = self._tlXY(k); m = _polyMetrics(xy) if xy is not None else None
            if m is None: m = self._metK(int(4 * round(k / 4.0)), "lumen")
            if m: rows.append((float(x), m["dmin"] / max(m["dmax"], 1e-6), m["deq"]))
        st = next((i for i, r in enumerate(rows) if r[1] >= rmin and r[0] - l["s"] >= 1.0), None)
        if st is None: return None
        en = st
        while en + 1 < len(rows) and rows[en + 1][1] >= rmin - 0.04: en += 1
        return dict(s=rows[st][0], r=rows[st][1], deq=rows[st][2], length=rows[en][0] - rows[st][0], lsca=l["s"])

    def fit3DToGraft(self, view="lao"):
        """3D をグラフトの範囲（前後 3 cm）に合わせる。lao = 左前斜位、front = 正面、left = 左側面"""
        pl = self.planInit(); F = self.frames[pl["path"]]
        k0, k1 = self._k(pl["p"] - 30.0, pl["path"]), self._k(pl["d"] + 30.0, pl["path"])
        Pk = F["P"][k0:k1 + 1]; ctr = (Pk.min(0) + Pk.max(0)) / 2.0; ext = float(np.ptp(Pk, 0).max()) + 30.0
        v = slicer.app.layoutManager().threeDWidget(0).threeDView()
        cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(v.mrmlViewNode())
        dv = {"lao": (-0.64, 0.77, 0.0), "front": (0.0, 1.0, 0.0), "left": (-1.0, 0.0, 0.0)}[view]
        dv = np.array(dv) / np.linalg.norm(dv); asp = max(v.width, 1) / max(v.height, 1)
        c = cam.GetCamera(); half = ext / 2.0 / min(1.0, asp)
        if c.GetParallelProjection(): c.SetParallelScale(half * 1.05); dist = ext * 2.0
        else: dist = half / math.tan(math.radians(c.GetViewAngle() / 2.0)) * 1.05
        cam.SetFocalPoint(*ctr); cam.SetPosition(*(ctr + dv * dist)); cam.SetViewUp(0, 0, 1); cam.ResetClippingRange()

    def showOverlay3D(self, what, on):
        if what == "aorta":
            vm = getattr(self, "vesselModel", None)
            if vm is not None and slicer.mrmlScene.IsNodePresent(vm):
                d = vm.GetDisplayNode(); d.SetVisibility(bool(on)); d.SetOpacity(0.2)
        elif what == "post":
            for nm, op in (("TEVAR 術後（範囲）", 0.15), ("TEVAR 術後（金属）", 1.0)):   # 実際のステント = 金属そのもの（金色の点）。筒は当てはめた目安（うすく）
                m = slicer.mrmlScene.GetFirstNodeByName(nm)
                if m is not None and m.GetDisplayNode():
                    d = m.GetDisplayNode(); d.SetVisibility(bool(on)); d.SetOpacity(op)
                    if nm.endswith("（金属）"): d.SetPointSize(3.0)

    def _tubeRadPD(self, Cs, B, N, Rth):
        """半径の輪 Rth[k, 72]（角度 = B → N）で、断面の形どおりの筒"""
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        n, ns = Rth.shape; th = np.linspace(0, 2 * np.pi, ns, endpoint=False)
        pts = (Cs[:, None, :] + Rth[:, :, None] * (np.cos(th)[None, :, None] * B[:, None, :] + np.sin(th)[None, :, None] * N[:, None, :])).reshape(-1, 3)
        i = np.arange(n - 1)[:, None]; j = np.arange(ns)[None, :]; j2 = (j + 1) % ns
        q = np.stack([i * ns + j, i * ns + j2, (i + 1) * ns + j2, (i + 1) * ns + j], -1).reshape(-1, 4)
        cells = np.c_[np.full(len(q), 4), q].astype(np.int64).ravel()
        vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(pts, np.float64), deep=True))
        ca = vtk.vtkCellArray(); ca.SetCells(len(q), numpy_to_vtkIdTypeArray(cells, deep=True))
        pd = vtk.vtkPolyData(); pd.SetPoints(vp); pd.SetPolys(ca)
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.Update()
        return nm.GetOutput()

    # SINE の目安: 遠位端での真腔とグラフトの比（参考: 単施設の報告の群の平均。判定基準ではない）
    SINE_REF = dict(pre=dict(mean=(0.61, 0.94), per=(0.50, 0.77), area=(1.98, 4.00)),
                    emr=dict(mean=(1.22, 1.48), per=(1.18, 1.43), area=(1.58, 2.39)))

    def _tlMet(self, s):
        k = self._k(s)
        if not self.tlValid(): return None
        xy = self._tlXY(k)
        if xy is None: return None
        m = _polyMetrics(xy)
        if m is None: return None
        per = float(np.linalg.norm(np.diff(np.r_[xy, xy[:1]], axis=0), axis=1).sum())
        return dict(short=m["dmin"], long=m["dmax"], mean=(m["dmin"] + m["dmax"]) / 2.0, per=per, area=m["area"], s=float(s))

    def sineIdx(self):
        """遠位端: 真腔の短径・長径・周径・面積と、グラフトとの比（術前のオーバーサイズ / 予測した広がりのミスマッチ）"""
        pl = self.planInit()
        if pl["path"] != self.path or not self.tlValid(): return None
        (Dp, _, _), (Dd, _, _) = self.planDiams()
        if not Dd: return None
        a = self._tlMet(pl["d"]); b = self._tlMet(min(pl["d"] + 20.0, self.length - 1.0))
        if a is None: return None
        out = dict(tl=a, tl2=b, Dd=Dd,
                   pre=dict(mean=Dd / a["mean"] - 1, per=math.pi * Dd / a["per"] - 1, area=(math.pi * Dd * Dd / 4) / a["area"] - 1, short=Dd / a["short"] - 1))
        gr = getattr(self, "_graftRad", None)
        if gr is not None and gr["path"] == self.path:
            Rth = gr["Rth"][-1]; th = np.linspace(0, 2 * np.pi, len(Rth), endpoint=False); X = np.c_[Rth * np.cos(th), Rth * np.sin(th)]
            ga = 0.5 * abs(np.dot(X[:, 0], np.roll(X[:, 1], -1)) - np.dot(X[:, 1], np.roll(X[:, 0], -1)))
            gp = float(np.linalg.norm(np.diff(np.r_[X, X[:1]], axis=0), axis=1).sum()); gD = 2 * math.sqrt(ga / math.pi)
            out.update(gD=gD, gper=gp, garea=ga, gut=float(gr["gut"][-1]))
            if b is not None: out["emr"] = dict(mean=gD / b["mean"], per=gp / b["per"], area=ga / b["area"])
        return out

    def sineRow(self):
        """解析用: 計画・遠位端の真腔・SINE の目安を 1 行に（列名 → 値）"""
        si = self.sineIdx(); pl = self.planInit()
        if not si: return None
        lg = self.planLengths() or {}
        (Dp, mp, _), (Dd, md, _) = self.planDiams()
        vn = self.vol.GetName() if getattr(self, "vol", None) is not None else ""
        f = lambda v, n=2: "" if v is None or (isinstance(v, float) and not np.isfinite(v)) else (f"{v:.{n}f}" if isinstance(v, (float, np.floating)) else v)
        a, b = si["tl"], si.get("tl2") or {}
        row = [("保存日時", time.strftime("%Y-%m-%d %H:%M")), ("画像（シリーズ）", vn), ("研究 ID（手で記入）", ""), ("経路", pl["path"]),
               ("近位端 mm", f(self.rel(pl["p"]), 1)), ("遠位端 mm", f(self.rel(pl["d"]), 1)),
               ("治療長 中心線 mm", f(lg.get("cl"), 1)), ("治療長 内弯 mm", f(lg.get("inner"), 1)), ("治療長 外弯 mm", f(lg.get("outer"), 1)),
               ("近位 実測径 mm", f(mp, 1)), ("近位 グラフト径 mm", f(Dp, 1)), ("遠位 実測径 mm", f(md, 1)), ("遠位 グラフト径 mm", f(Dd, 1)),
               ("オーバーサイズ設定 %", f(pl["os"] * 100, 0)), ("フラップ", {"chronic": "慢性", "acute": "急性", "fixed": "動かない"}.get(pl.get("flap"), "")),
               ("両端", "あるがまま" if pl.get("ends") == "asis" else "押し広げる"),
               ("遠位端 真腔 短径", f(a["short"], 1)), ("遠位端 真腔 長径", f(a["long"], 1)), ("遠位端 真腔 平均径", f(a["mean"], 1)),
               ("遠位端 真腔 周径", f(a["per"], 1)), ("遠位端 真腔 面積 mm2", f(a["area"], 0)),
               ("2cm 先 真腔 短径", f(b.get("short"), 1)), ("2cm 先 真腔 長径", f(b.get("long"), 1)), ("2cm 先 真腔 周径", f(b.get("per"), 1)), ("2cm 先 真腔 面積 mm2", f(b.get("area"), 0)),
               ("オーバーサイズ 平均径", f(si["pre"]["mean"])), ("オーバーサイズ 周径", f(si["pre"]["per"])), ("オーバーサイズ 面積", f(si["pre"]["area"])), ("オーバーサイズ 短径", f(si["pre"]["short"])),
               ("予測 広がり径", f(si.get("gD"), 1)), ("予測 周径", f(si.get("gper"), 1)), ("予測 面積 mm2", f(si.get("garea"), 0)), ("予測 ガター mm2", f(si.get("gut"), 0))]
        e = si.get("emr") or {}
        row += [("ミスマッチ 平均径", f(e.get("mean"))), ("ミスマッチ 周径", f(e.get("per"))), ("ミスマッチ 面積", f(e.get("area")))]
        c = None
        try: c = self.comparePost() if getattr(self, "actual", None) is not None else None
        except Exception: c = None
        row += [("術後 近位端のずれ mm", f(c.get("dP") if c else None, 1)), ("術後 遠位端のずれ mm", f(c.get("dD") if c else None, 1)),
                ("術後 実際の長さ mm", f(c.get("realLen") if c else None, 1)), ("術後 実際の径 mm", f(c.get("Dreal") if c else None, 1))]
        row += [("ソフトの版", self._appVersion())] + _ctProtocol(getattr(self, "vol", None))
        return row

    def saveSineCSV(self, d=None):
        """この症例の 1 行を フォルダ d（TEVAR_SINE目安.csv）と、ドキュメント\\HeartView症例\\TEVAR_SINE_一覧.csv（症例を重ねていく）に"""
        row = self.sineRow()
        if not row: return None
        import csv
        hdr = [k for k, _ in row]; val = [v for _, v in row]
        d = d or self.outDir(); fn = os.path.join(d, "TEVAR_SINE目安.csv")
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh: w = csv.writer(fh); w.writerow(hdr); w.writerow(val)
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例"); os.makedirs(base, exist_ok=True)
        allfn = os.path.join(base, "TEVAR_SINE_一覧.csv")
        if os.path.exists(allfn):
            try: old = open(allfn, encoding="utf-8-sig").readline().strip()
            except Exception: old = ""
            if old != ",".join(hdr): allfn = os.path.join(base, "TEVAR_SINE_一覧_" + time.strftime("%Y%m%d") + ".csv")   # 列が変わった時は別のファイルに
        new = not os.path.exists(allfn)
        with open(allfn, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
            w = csv.writer(fh)
            if new: w.writerow(hdr)
            w.writerow(val)
        return fn, allfn

    def planDraw(self):
        pl = self.planInit()
        if not pl.get("on", True): self.planShow(False); return
        (Dp, _, _), (Dd, _, _) = self.planDiams()
        if not Dp or not Dd: return
        if pl.get("tl") and pl["path"] == self.path and not self.tlValid(): self.extractTL(getattr(self, "onStatus", None) or print)
        F, ks, R, C = self._graftGeom(pl["p"], pl["d"], Dp, Dd, pl["path"])
        if len(ks) < 4: return
        self._planDrawn = 2 * R; gr = getattr(self, "_graftRad", None)
        tube = self._tubeRadPD(C[ks], F["B"][ks], F["N"][ks], gr["Rth"]) if gr is not None else self._tubePD(C[ks], F["N"][ks], F["B"][ks], R)
        self._model("TEVAR 計画（布）", tube, (0.88, 0.93, 1.0), 0.45, slice2D=True, spec=0.15)
        self._model("TEVAR 計画（ステント）", self._zStentsPD(F, ks, R, C=C, Rth=None if gr is None else gr["Rth"]), (0.78, 0.8, 0.85), 1.0, spec=0.8)
        self._drawEntries(); self._drawGreen()

    def planShow(self, on):
        for nm in ("TEVAR 計画（布）", "TEVAR 計画（ステント）"):
            m = slicer.mrmlScene.GetFirstNodeByName(nm)
            if m is not None and m.GetDisplayNode(): m.GetDisplayNode().SetVisibility(bool(on))

    # ---- エントリー（断面をクリックして置く）
    def addEntry(self, ras):
        es = self.__dict__.setdefault("entries", [])
        name = f"エントリー{len(es) + 1}"
        es.append(dict(name=name, s=float(self.curS), path=self.path, xyz=[float(x) for x in ras]))
        self._drawEntries(); self._listsChanged(); return name

    def removeEntry(self, name):
        self.entries = [e for e in getattr(self, "entries", []) if e["name"] != name]
        for i, e in enumerate(self.entries): e["name"] = f"エントリー{i + 1}"
        self._drawEntries(); self._listsChanged()

    def coverage(self, lo, hi):
        """エントリー・分枝を、範囲 lo〜hi（中心線の mm）のグラフトが覆うか"""
        rows = []
        for e in getattr(self, "entries", []):
            s = e["s"]
            if lo <= s <= hi:
                m = min(s - lo, hi - s)
                rows.append(dict(kind="entry", name=e["name"], s=s, state="cover" if m >= 10 else "edge",
                                 text=f"覆う（端まで {m:.0f} mm）" if m >= 10 else f"覆うが端に近い（{m:.0f} mm）"))
            else:
                rows.append(dict(kind="entry", name=e["name"], s=s, state="open", text=f"覆わない（{(lo - s) if s < lo else (s - hi):.0f} mm 外）"))
        for mk in self.markers:
            nm = mk["name"].replace("（推定）", "")
            if not (nm in self.BRANCH_NAMES or (nm.endswith("動脈") and not nm.startswith("入口"))): continue
            s = mk["s"]
            if lo <= s <= hi: rows.append(dict(kind="branch", name=nm, s=s, state="block", text="この分枝を覆う"))
            else:
                gap = (lo - s) if s < lo else (s - hi)
                rows.append(dict(kind="branch", name=nm, s=s, state="ok", text=f"{'近位端' if s < lo else '遠位端'}まで {gap:.0f} mm"))
        rows.sort(key=lambda r: r["s"]); return rows

    def _drawEntries(self):
        pl = getattr(self, "plan", None); lo, hi = (pl["p"], pl["d"]) if pl else (1e9, -1e9)
        st = {e["name"]: r["state"] for r in self.coverage(lo, hi) for e in getattr(self, "entries", []) if r["name"] == e["name"]}
        for state, label in (("cover", "覆う"), ("edge", "端"), ("open", "覆わない")):
            n = self._node("vtkMRMLMarkupsFiducialNode", f"TEVAR エントリー（{label}）", ("vtkMRMLViewNode1", "vtkMRMLSliceNodeRed"),
                           self.STATE_COL[state], glyph=3.0, text=3.0)
            wasMod = n.StartModify(); n.RemoveAllControlPoints()
            for e in getattr(self, "entries", []):
                if st.get(e["name"], "open") == state:
                    i = n.AddControlPoint(vtk.vtkVector3d(*e["xyz"])); n.SetNthControlPointLabel(i, "E" + e["name"][len("エントリー"):])
            n.EndModify(wasMod)

    def planLengths(self):
        """計画したグラフトの治療長: 中心線、外弯 = グラフトの筒でいちばん長いすじ（大弯側）、内弯 = いちばん短いすじ（mm）"""
        pl = getattr(self, "plan", None)
        if not pl or pl.get("path") not in self.frames: return None
        try:
            (Dp, _, _), (Dd, _, _) = self.planDiams()
            F = self.frames[pl["path"]]; k0, k1 = self._k(pl["p"], pl["path"]), self._k(pl["d"], pl["path"])
            if k1 - k0 < 2 or not Dp or not Dd: return None
            ks = np.arange(k0, k1 + 1); r = np.linspace(Dp, Dd, len(ks)) / 2.0             # グラフト（名目の径）の筒の上の、まっすぐな「すじ」の長さ
            th = np.linspace(0, 2 * np.pi, 72, endpoint=False)
            X = F["P"][ks][None] + r[None, :, None] * (np.cos(th)[:, None, None] * F["B"][ks][None] + np.sin(th)[:, None, None] * F["N"][ks][None])
            Ls = np.linalg.norm(np.diff(X, axis=1), axis=2).sum(1); cl = float(np.linalg.norm(np.diff(F["P"][ks], axis=0), axis=1).sum())
        except Exception: return None
        return dict(cl=cl, inner=float(Ls.min()), outer=float(Ls.max()))
