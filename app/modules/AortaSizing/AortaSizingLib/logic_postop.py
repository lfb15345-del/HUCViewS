# -*- coding: utf-8 -*-
"""大動脈サイジング: 術後 CT: 読み込み・重ね合わせ・金属（ステント）・比べる・広がり
AortaSizingLogic の一部（PostOpMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class PostOpMixin:

    # ---- 術後 CT
    def loadPostFolder(self, folder, status=print):
        """術後 CT のフォルダから、造影・軸位で一番薄いシリーズを選んで読み込む（院内 PC の中だけ）"""
        import pydicom
        from concurrent.futures import ThreadPoolExecutor
        files = [os.path.join(dp, f) for dp, dn, fn in os.walk(folder) for f in fn]
        status(f"術後 CT: {len(files)} ファイルを調べています…")
        mpr = []
        def hdr(p):
            try:
                d = pydicom.dcmread(p, stop_before_pixels=True, force=True)
                it = str(getattr(d, "ImageType", ""))
                if "LOCALIZER" in it or "SECONDARY" in it or str(getattr(d, "Modality", "")) != "CT": return None
                iop = [float(x) for x in d.ImageOrientationPatient]
                if abs(iop[0]) < 0.9 or abs(iop[4]) < 0.9:                            # 軸位でない薄い再構成（MPR）は金属用に覚えておく
                    if 0 < float(getattr(d, "SliceThickness", 0) or 0) <= 2.5 and int(d.Rows) >= 512: mpr.append((p, str(d.SeriesInstanceUID)))
                    return None
                return (p, str(d.SeriesInstanceUID), bool(str(getattr(d, "ContrastBolusAgent", "")).strip()), "ORIGINAL" in it,
                        float(getattr(d, "SliceThickness", 0) or 0), int(d.Rows))
            except Exception: return None
        with ThreadPoolExecutor(8) as ex: H = [h for h in ex.map(hdr, files) if h]
        by = {}
        for h in H: by.setdefault(h[1], []).append(h)
        cand = [(v[0][2], -v[0][4], len(v) * max(v[0][4], 0.5), v[0][3], uid) for uid, v in by.items() if len(v) >= 30 and v[0][5] >= 256]
        if not cand: raise RuntimeError("術後 CT の軸位シリーズが見つかりませんでした")
        cand.sort(reverse=True); uid = cand[0][-1]; paths = [h[0] for h in by[uid]]
        status(f"術後 CT: {len(paths)} 枚（{-cand[0][1]:g} mm）を読み込み中…")
        def rd(p):
            d = pydicom.dcmread(p, force=True)
            a = d.pixel_array.astype(np.float32) * float(getattr(d, "RescaleSlope", 1) or 1) + float(getattr(d, "RescaleIntercept", 0) or 0)
            return [float(x) for x in d.ImagePositionPatient], [float(x) for x in d.PixelSpacing], [float(x) for x in d.ImageOrientationPatient], np.clip(a, -1024, 4000).astype(np.int16)
        with ThreadPoolExecutor(8) as ex: S = list(ex.map(rd, paths))
        r = np.array(S[0][2][:3]); c = np.array(S[0][2][3:]); n = np.cross(r, c)
        S.sort(key=lambda x: float(np.dot(x[0], n)))
        pos = np.array([float(np.dot(x[0], n)) for x in S]); dz = float(np.median(np.diff(pos))) if len(S) > 1 else 1.0
        arr = np.stack([x[3] for x in S]); ps = S[0][1]; o = np.array(S[0][0])
        M = np.eye(4); M[:3, 0] = r * ps[1]; M[:3, 1] = c * ps[0]; M[:3, 2] = n * dz; M[:3, 3] = o
        M = np.diag([-1, -1, 1, 1]) @ M                                              # LPS → RAS
        node = slicer.mrmlScene.GetFirstNodeByName("術後 CT")
        if node is None: node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "術後 CT")
        slicer.util.updateVolumeFromArray(node, arr)
        m = vtk.vtkMatrix4x4()
        for i in range(4):
            for j in range(4): m.SetElement(i, j, float(M[i, j]))
        node.SetIJKToRASMatrix(m); node.CreateDefaultDisplayNodes()
        dn = node.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        self.post = node; self.postT = None; self.postMPR = [p for p, _ in mpr]; self._mprCache = None
        status(f"術後 CT を読み込みました（{arr.shape[0]} 枚・{dz:.1f} mm 間隔）")
        return node

    @staticmethod
    def _volPts(vol, mask, stride=(1, 1, 1)):
        idx = np.argwhere(mask) * np.array(stride)
        m = vtk.vtkMatrix4x4(); vol.GetIJKToRASMatrix(m)
        A = np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])
        return idx[:, ::-1] @ A[:3, :3].T + A[:3, 3]

    def registerPost(self, status=print):
        """術後 CT を術前に重ねる（グラフトのまわりの背骨・肋骨で剛体の位置合わせ）。戻り値: 4×4（術後 → 術前）と誤差 mm"""
        from scipy.spatial import cKDTree
        post = getattr(self, "post", None)
        if post is None: raise RuntimeError("先に術後 CT を読み込んでください")
        pl = self.planInit(); F = self.frames[pl["path"]]
        def stride(vol):
            sp = vol.GetSpacing(); return tuple(int(max(1, round(2.0 / x))) for x in (sp[2], sp[1], sp[0]))
        a0 = slicer.util.arrayFromVolume(self.vol); s0 = stride(self.vol)
        a1 = slicer.util.arrayFromVolume(post); s1 = stride(post)
        bo = self._boneRaw()                                                          # 術前は AI の骨ラベルの中だけ（造影された血管・心臓を骨と取り違えない）
        m0 = a0[::s0[0], ::s0[1], ::s0[2]] > 400
        if bo is not None: m0 &= bo[::s0[0], ::s0[1], ::s0[2]]
        B0 = self._volPts(self.vol, m0, s0)
        B1 = self._volPts(post, a1[::s1[0], ::s1[1], ::s1[2]] > 400, s1)             # 術後は皮質骨くらいの高さ（造影の血管より上）
        self._regPts = (B0, B1)
        lo, hi = max(0.0, pl["p"] - 60.0), min(F["length"], pl["d"] + 60.0)
        C = F["P"][self._k(lo, pl["path"]):self._k(hi, pl["path"]) + 1:4]
        d0, _ = cKDTree(C).query(B0, distance_upper_bound=90.0); T0 = B0[np.isfinite(d0)]          # グラフトのまわり 9 cm の骨
        if len(T0) < 500: raise RuntimeError("位置合わせに使う骨が足りません")
        status(f"位置合わせ: 骨の点 術前 {len(T0)} / 術後 {len(B1)}")
        # 1) 体軸方向のずれ: 骨の量の縦の分布をずらして合わせる
        bins = np.arange(-1500, 3000, 5.0)
        h0 = np.histogram(B0[:, 2], bins)[0].astype(float); h1 = np.histogram(B1[:, 2], bins)[0].astype(float)
        h0 = (h0 - h0.mean()) / (h0.std() + 1e-9); h1 = (h1 - h1.mean()) / (h1.std() + 1e-9)
        best = max(range(-140, 141), key=lambda k: float(np.dot(h0, np.roll(h1, k))))
        dz = best * 5.0
        zlo, zhi = T0[:, 2].min() - dz, T0[:, 2].max() - dz
        S1 = B1[(B1[:, 2] > zlo - 40) & (B1[:, 2] < zhi + 40)]
        t = np.array([np.median(T0[:, 0]) - np.median(S1[:, 0]), np.median(T0[:, 1]) - np.median(S1[:, 1]), dz])
        Rm = np.eye(3); tree = cKDTree(T0)
        if len(S1) > 60000: S1 = S1[np.random.default_rng(0).choice(len(S1), 60000, replace=False)]
        # 2) ICP（近い点どうしを少しずつ合わせる。遠い点は外す）
        rms = None
        for it in range(60):
            X = S1 @ Rm.T + t; d, j = tree.query(X)
            lim = max(4.0, 25.0 * (0.92 ** it)); ok = d < lim
            if ok.sum() < 200: break
            ok &= d <= np.percentile(d[ok], 85)
            A, Bq = X[ok], T0[j[ok]]; ca, cb = A.mean(0), Bq.mean(0)
            U, _, Vt = np.linalg.svd((A - ca).T @ (Bq - cb)); D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
            dR = Vt.T @ D @ U.T; Rm = dR @ Rm; t = dR @ (t - ca) + cb
            rms = float(np.sqrt(np.mean(d[ok] ** 2)))
        M = np.eye(4); M[:3, :3] = Rm; M[:3, 3] = t
        self.postT = M; self.postRms = rms
        tn = slicer.mrmlScene.GetFirstNodeByName("術後→術前") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "術後→術前")
        vm = vtk.vtkMatrix4x4()
        for i in range(4):
            for j in range(4): vm.SetElement(i, j, float(M[i, j]))
        tn.SetMatrixTransformToParent(vm); post.SetAndObserveTransformNodeID(tn.GetID())
        status(f"位置合わせ: 骨のずれ {rms:.1f} mm（体軸方向 {dz:.0f} mm 移動）")
        return M, rms

    @staticmethod
    def _icp(S, tree, T0, Rm, t, iters=40, lim0=25.0):
        rms = None
        for it in range(iters):
            X = S @ Rm.T + t; d, j = tree.query(X)
            lim = max(3.0, lim0 * (0.9 ** it)); ok = d < lim
            if ok.sum() < 150: return Rm, t, None
            ok &= d <= np.percentile(d[ok], 85)
            A, Bq = X[ok], T0[j[ok]]; ca, cb = A.mean(0), Bq.mean(0)
            U, _, Vt = np.linalg.svd((A - ca).T @ (Bq - cb)); D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
            dR = Vt.T @ D @ U.T; Rm = dR @ Rm; t = dR @ (t - ca) + cb
            rms = float(np.sqrt(np.mean(d[ok] ** 2)))
        return Rm, t, rms

    def extractStent(self, thr=450.0, status=print):
        """術後 CT の金属（ステントの骨組み）を拾い、中心線に沿った範囲を出す。
        体の曲がり方は術前と術後で少し違うので、中心線に沿って 4 cm ごとに背骨で合わせ直してから拾う（区間ごとの剛体）"""
        from scipy.spatial import cKDTree
        post = self.post; M = self.postT; pl = self.planInit(); path = pl["path"]; F = self.frames[path]
        B0, B1 = self._regPts
        a1 = slicer.util.arrayFromVolume(post)
        Y = self._volPts(post, a1 > thr)                                             # 術後の座標の金属・骨の候補
        Xg = Y @ M[:3, :3].T + M[:3, 3]
        dg, kg = cKDTree(F["P"]).query(Xg); sg = F["s"][kg]
        self._ensureArrF(); A = self._rasToIjk; aoD, boD = self._tvMasks(); sh = self.arr.shape
        t0 = cKDTree(B0); B1g = B1 @ M[:3, :3].T + M[:3, 3]
        keepX, keepS, segs = [], [], []
        L_ = F["length"]; c = 0.0
        while c < L_:
            lo, hi = c - 20.0, c + 20.0; c += 30.0
            sel = (sg >= lo) & (sg < hi) & (dg < 45.0)
            if sel.sum() == 0: continue
            k0, k1 = self._k(max(lo, 0), path), self._k(min(hi, L_), path); C = F["P"][k0:k1 + 1:4]
            cT = cKDTree(C); dT, _ = cT.query(B0, distance_upper_bound=80.0); T0 = B0[np.isfinite(dT)]
            dS, _ = cT.query(B1g, distance_upper_bound=95.0); S = B1[np.isfinite(dS)]
            if len(T0) < 300 or len(S) < 300: continue
            if len(S) > 30000: S = S[np.random.default_rng(1).choice(len(S), 30000, replace=False)]
            Rm, t, rms = self._icp(S, cKDTree(T0), T0, M[:3, :3].copy(), M[:3, 3].copy(), iters=30, lim0=8.0)
            segs.append((c - 30.0, rms)); self.__dict__.setdefault("_segT", {})[c - 30.0] = (Rm, t)
            if rms is None or rms > 3.5: continue                                     # この区間は骨が合わない → 使わない
            X = Y[sel] @ Rm.T + t
            I = np.round(X @ A[:3, :3].T + A[:3, 3]).astype(int)
            inb = (I[:, 0] >= 0) & (I[:, 0] < sh[2]) & (I[:, 1] >= 0) & (I[:, 1] < sh[1]) & (I[:, 2] >= 0) & (I[:, 2] < sh[0])
            X, I = X[inb], I[inb]
            ok = self.arr[I[:, 2], I[:, 1], I[:, 0]] < 600.0                           # 術前から高い所（骨・石灰化）は除く
            if aoD is not None: ok &= aoD[I[:, 2], I[:, 1], I[:, 0]]                    # 術前の大動脈（少し広げる）の中だけ
            if boD is not None: ok &= ~boD[I[:, 2], I[:, 1], I[:, 0]]                   # 骨（少し広げる）は除く
            X = X[ok]
            if len(X) == 0: continue
            d, k = cKDTree(F["P"]).query(X); s = F["s"][k]; m = (s >= c - 45.0) & (s < c - 15.0)    # 区間の真ん中 3 cm だけ使う（重なりなし）
            keepX.append(X[m]); keepS.append(s[m])
        self._segRms = segs
        if not keepX or sum(len(x) for x in keepX) < 30: raise RuntimeError("術後 CT にステントの金属が見つかりませんでした")
        X = np.concatenate(keepX); s = np.concatenate(keepS)
        # 中心線に沿って 2 mm ごとに数え、すき間 20 mm 以内でつながる、いちばん点の多い範囲をグラフトとする
        b = np.floor(s / 2.0).astype(int); cnt = np.bincount(b, minlength=b.max() + 1); occ = np.where(cnt >= 3)[0]
        runs = []; st = occ[0]; pv = occ[0]
        for x in occ[1:]:
            if (x - pv) * 2.0 > 20.0: runs.append((st, pv)); st = x
            pv = x
        runs.append((st, pv)); r0, r1 = max(runs, key=lambda r: cnt[r[0]:r[1] + 1].sum())
        lo, hi = r0 * 2.0, (r1 + 1) * 2.0
        sel = (s >= lo - 2) & (s <= hi + 2); X, s = X[sel], s[sel]
        self.actual = dict(lo=float(lo), hi=float(hi), pts=X, s=s, path=path)
        bad = [f"{a:.0f}" for a, r in segs if r is None or r > 3.5]
        status(f"術後のグラフト: 中心線 {lo:.0f}〜{hi:.0f} mm（{hi - lo:.0f} mm）・金属 {len(X)} 点" + (f"（骨が合わない区間 {len(bad)} か所は除外）" if bad else ""))
        self._drawActual(); self._drawGreen()
        return self.actual

    def _tvMasks(self):
        if getattr(self, "_tvMask", None) is None or self._tvMask[2] is not self.vol:
            from scipy import ndimage
            sp = self.vol.GetSpacing(); it = lambda mm, ax: max(1, int(round(mm / sp[ax])))
            def dil(m, mm):
                if m is None: return None
                st = np.zeros((3, 3, 3), bool); st[1, 1, :] = st[1, :, 1] = st[:, 1, 1] = True
                out = m
                for _ in range(max(it(mm, 0), it(mm, 2))): out = ndimage.binary_dilation(out, st)
                return out
            ao = self._mask(("aorta",))
            bo = self._mask(("vertebra", "rib", "sternum", "clavicula", "scapula", "hip", "sacrum", "femur", "humerus", "costal"))
            self._tvMask = (dil(ao, 3.0), dil(bo, 1.5), self.vol, bo)
        return self._tvMask[0], self._tvMask[1]

    def _boneRaw(self):
        self._tvMasks(); return self._tvMask[3]

    def _drawActual(self):
        ac = getattr(self, "actual", None)
        if ac is None: return
        from vtk.util.numpy_support import numpy_to_vtk
        vis = {}
        for nm in ("TEVAR 術後（金属）", "TEVAR 術後（範囲）"):
            m0 = slicer.mrmlScene.GetFirstNodeByName(nm)
            if m0 is not None and m0.GetDisplayNode(): vis[nm] = (m0.GetDisplayNode().GetVisibility(), m0.GetDisplayNode().GetOpacity(), m0.GetDisplayNode().GetPointSize())
        vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(ac["pts"], np.float64), deep=True))
        pd = vtk.vtkPolyData(); pd.SetPoints(vp)
        vg = vtk.vtkVertexGlyphFilter(); vg.SetInputData(pd); vg.Update()
        m = self._model("TEVAR 術後（金属）", vg.GetOutput(), (1.0, 0.72, 0.2), 1.0, spec=0.6)
        d = m.GetDisplayNode(); d.SetPointSize(4.0)
        try: d.SetRepresentation(d.PointsRepresentation)
        except Exception: pass
        try: d.SetRenderPointsAsSpheres(True)
        except Exception: pass
        # 実際のグラフトの筒（うすい金色）: 断面ごとに金属の輪へ円を当てはめた中心と径。計画の白い筒と並べて比べる
        self._fitRings()
        if ac.get("C") is not None:
            F = self.frames[ac["path"]]; ks = ac["ks"]
            tube = self._tubeRadPD(ac["C"], F["B"][ks], F["N"][ks], ac["Rth"] + 0.6) if ac.get("Rth") is not None else self._tubePD(ac["C"], F["N"][ks], F["B"][ks], ac["R"] + 0.6)
            self._model("TEVAR 術後（範囲）", tube, (1.0, 0.75, 0.3), 0.25, spec=0.1)
        for nm, (v, op, psz) in vis.items():                                             # 前の表示状態（出す/隠す・透明度）に戻す
            m0 = slicer.mrmlScene.GetFirstNodeByName(nm)
            if m0 is not None and m0.GetDisplayNode(): m0.GetDisplayNode().SetVisibility(v); m0.GetDisplayNode().SetOpacity(op); m0.GetDisplayNode().SetPointSize(psz)

    def _cancelDrags(self):
        """途中のドラッグ（範囲・重ね合わせ・シミュレーション）を取り消す"""
        if getattr(self, "_alDrag", None) is not None and self._alDrag[0] == "s":
            d = self._alDrag; self.actual["lo"], self.actual["hi"] = d[4], d[5]
        self._alDrag = None; self._pdDrag = None; self._tvDrag = None; self.rangeMode = False
        try: self._drawGreen(); self._showContour(exact=False)
        except Exception: pass

    def _fitRings(self):
        """術後の金属を、中心線の各断面（前後 4 mm）で楕円に当てはめる → 実際のグラフトの中心・長径・短径・向き。
        ステントは正円に広がるとは限らない（解離では楕円）ので、円ではなく楕円で（円だと径と中心に系統誤差が出る）"""
        ac = self.actual; F = self.frames[ac["path"]]
        from scipy.spatial import cKDTree
        from scipy import ndimage
        k0, k1 = self._k(ac["lo"], ac["path"]), self._k(ac["hi"], ac["path"]); ks = np.arange(k0, k1 + 1); n = len(ks)
        X = ac["pts"]; _, kk = cKDTree(F["P"]).query(X)
        d = X - F["P"][kk]; u = (d * F["B"][kk]).sum(1); v = (d * F["N"][kk]).sum(1)
        cu, cv, A, Bm, c2, s2 = (np.full(n, np.nan) for _ in range(6)); w = int(4.0 / STEP)
        for i in range(0, n, 4):
            m = np.abs(kk - ks[i]) <= w
            if m.sum() < 15: continue
            uu, vv = u[m], v[m]
            e = _fitEllipse(uu, vv)
            if e is None or not (12.0 <= e[2] <= e[1] <= 60.0 and e[2] / e[1] >= 0.45): continue
            (x0, y0), maj, mnr, ph = e
            ang = np.sort(np.arctan2(vv - y0, uu - x0)); gap = np.max(np.diff(np.r_[ang, ang[0] + 2 * np.pi]))
            if gap >= np.pi * 0.8: continue                                           # 輪の半分以上に金属がある時だけ
            cu[i], cv[i], A[i], Bm[i] = x0, y0, maj / 2, mnr / 2
            ecc = (maj - mnr) / max(maj, 1e-6); c2[i], s2[i] = ecc * math.cos(2 * ph), ecc * math.sin(2 * ph)   # 向きは 2 倍角で（180° で同じ）
        ok = np.isfinite(A)
        if ok.sum() < 3: ac["C"] = None; return
        idx = np.arange(n); sm = lambda a: ndimage.gaussian_filter1d(np.interp(idx, idx[ok], a[ok]), 3.0 / STEP, mode="nearest")
        cu, cv, A, Bm, c2, s2 = (sm(a) for a in (cu, cv, A, Bm, c2, s2))
        Bm = np.minimum(Bm, A); ph = 0.5 * np.arctan2(s2, c2)
        th = np.linspace(0, 2 * np.pi, self.NTH, endpoint=False)
        Rth = A[:, None] * Bm[:, None] / np.sqrt((Bm[:, None] * np.cos(th[None] - ph[:, None])) ** 2 + (A[:, None] * np.sin(th[None] - ph[:, None])) ** 2)
        ac.update(ks=ks, C=F["P"][ks] + cu[:, None] * F["B"][ks] + cv[:, None] * F["N"][ks], R=np.sqrt(A * Bm), A=A, Bm=Bm, phi=ph, Rth=Rth, cu=cu, cv=cv, fitOK=ok)

    def comparePost(self):
        """計画と術後の違い（中心線に沿った mm。＋ は遠位＝足側へずれた）"""
        pl = self.planInit(); ac = getattr(self, "actual", None)
        if ac is None: return None
        lo, hi = ac["lo"], ac["hi"]
        out = dict(dP=lo - pl["p"], dD=hi - pl["d"], planLen=pl["d"] - pl["p"], realLen=hi - lo, rms=getattr(self, "postRms", None),
                   zres=float(self.post.GetSpacing()[2]) if getattr(self, "post", None) is not None else None,
                   rows=self.coverage(lo, hi))
        try:
            if ac.get("C") is not None and pl["path"] == ac["path"]:
                (Dp, _, _), (Dd, _, _) = self.planDiams()
                F, ksP, Rp, Cp = self._graftGeom(pl["p"], pl["d"], Dp, Dd, pl["path"])
                both = np.intersect1d(ksP, ac["ks"])
                if len(both) > 4:
                    iP = both - ksP[0]; iA = both - ac["ks"][0]
                    off = np.linalg.norm(Cp[both] - ac["C"][iA], axis=1)
                    Rn = getattr(self, "_graftNominal", None)
                    if Rn is not None and len(Rn) == len(Rp): out["Dnom"] = float(np.median(2 * Rn[iP]))
                    out.update(Dplan=float(np.median(2 * Rp[iP])), Dreal=float(np.median(2 * ac["R"][iA])),
                               DrealMin=float(np.min(2 * ac["R"][iA])), DrealMax=float(np.max(2 * ac["R"][iA])),
                               offMed=float(np.median(off)), offMax=float(np.max(off)), offAt=float(self.frames[pl["path"]]["s"][both[int(np.argmax(off))]]))
                    if ac.get("A") is not None: out.update(RealMaj=float(np.median(2 * ac["A"][iA])), RealMin=float(np.median(2 * ac["Bm"][iA])))
        except Exception as e: print("compare geom:", e)
        return out

    ALIGN_SOFT = 30.0        # 重ね合わせを手で直した時、前後どのくらい（mm）がなめらかについてくるか
    ADJ_SOFT = 20.0          # シミュレーションを手で直した時の、同じ長さ

    @staticmethod
    def _adjW(x, s0, W):
        d = np.abs(np.asarray(x, float) - s0); return np.where(d < W, 0.5 + 0.5 * np.cos(np.pi * np.minimum(d / W, 1.0)), 0.0)

    def _postShiftAt(self, ks):
        """断面 ks での、術後 CT のずれ（術前の座標で 3D のベクトル、mm）= 大動脈の外形で合わせ直した分 ＋ 手で直した分"""
        ks = np.asarray(ks); x = self.s[ks]; out = np.zeros((len(ks), 3))
        ps = getattr(self, "postShift", None)
        if ps is not None and ps.get("path") == self.path:
            out += np.stack([np.interp(x, ps["s"], ps["t"][:, j]) for j in range(3)], 1)
        for s0, vec in getattr(self, "postManual", None) or []:
            if s0 == "s": out += -float(vec) * self.T[ks]                          # 中心線に沿って全体を ds だけ滑らせる（ストレッチ像の上下ドラッグ）
            else: out += self._adjW(x, s0, self.ALIGN_SOFT)[:, None] * np.asarray(vec)[None, :]
        return out

    def _liveAlign(self):
        d = getattr(self, "_alDrag", None)
        return d[2] if d is not None and d[0] == "xy" else np.zeros(3)

    def refinePost(self, status=print, lo=None, hi=None, seg=15.0, half=20.0):
        """背骨で合わせた術後 CT を、中心線に沿った区間ごとに大動脈の外形でもう一度合わせる（3D の平行移動、区間どうしはなめらかに）。
        呼吸・体位で大動脈は背骨に対して数 mm〜1 cm ずれ、弓部では頭尾方向にもずれるため。金属（実際のグラフト）もこの合わせ方で拾い直す"""
        from scipy import ndimage
        self.postShift = None
        post = self.post; a = np.clip(slicer.util.arrayFromVolume(post).astype(np.float32), -150, 150)
        m = vtk.vtkMatrix4x4(); post.GetIJKToRASMatrix(m)
        A = np.linalg.inv(np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])) @ np.linalg.inv(self.postT)
        ac = getattr(self, "actual", None); pl = getattr(self, "plan", None) or {}
        lo = lo if lo is not None else min([v for v in (ac and ac["lo"], pl.get("p")) if v is not None] or [0.0]) - 30.0
        hi = hi if hi is not None else max([v for v in (ac and ac["hi"], pl.get("d")) if v is not None] or [self.length]) + 30.0
        lo, hi = max(lo, 0.0), min(hi, self.length - 1.0)
        nu = int(round(2 * HALF / STEP)) + 1; g = np.arange(nu) * STEP - HALF; rng = np.random.default_rng(0)
        IN, SH, KK = [], [], []                                                       # 断面ごとに、外周の内側（壁 1.5 mm を除く）と外側 2〜6 mm の点
        for k in range(4 * int(math.ceil(self._k(lo) / 4.0)), self._k(hi) + 1, 4):             # 2 mm おき（計算済みの断面に合わせる）
            xy = self._section(k, "outer")
            if xy is None or len(xy) < 6: continue
            Mk = _rasterPoly(np.asarray(xy, float), nu); Din = ndimage.distance_transform_edt(Mk) * STEP; Dout = ndimage.distance_transform_edt(~Mk) * STEP
            for msk, lst in (((Din > 1.5), IN), (((Dout > 2) & (Dout < 6)), SH)):
                rc = np.argwhere(msk)
                if len(rc) > 150: rc = rc[rng.choice(len(rc), 150, replace=False)]
                lst.append(self.P[k] + g[rc[:, 1]][:, None] * self.B[k] + g[rc[:, 0]][:, None] * self.N[k])
            KK.append(k)
        if len(KK) < 5: status("大動脈の外形で合わせ直せませんでした（背骨の重ね合わせのまま）"); return None
        kin = np.repeat(KK, [len(x) for x in IN]); ksh = np.repeat(KK, [len(x) for x in SH]); IN = np.concatenate(IN); SH = np.concatenate(SH)
        def val(X, t):
            H = (X + t) @ A[:3, :3].T + A[:3, 3]
            return ndimage.map_coordinates(a, [H[:, 2], H[:, 1], H[:, 0]], order=1, mode="nearest")
        out = []; t_prev = np.zeros(3)
        for c in np.arange(lo + half, hi - half + 1e-6, seg) if hi - lo > 2 * half else [0.5 * (lo + hi)]:
            mi = np.abs(self.s[kin] - c) <= half; ms = np.abs(self.s[ksh] - c) <= half
            if mi.sum() < 200 or ms.sum() < 200: continue
            Xi, Xs = IN[mi], SH[ms]
            sc = lambda t: val(Xi, t).mean() - val(Xs, t).mean()
            kc = self._k(c); Bc, Nc = self.B[kc], self.N[kc]                          # 断面の中だけで動かす（長さ方向は外形では決まらないので背骨合わせのまま）
            ka, kb = self._k(c - half), self._k(c + half); turn = math.degrees(math.acos(float(np.clip(self.T[ka] @ self.T[kb], -1, 1))))
            curved = turn > 35.0                                                       # 曲がっている所（弓部）は、長さ方向も外形で決まる
            s0 = sc(np.zeros(3)); best = (s0, np.zeros(3), 0.0, 0.0)
            for step, span in ((1.5, 12.0), (0.5, 1.5)):
                c0u, c0v = best[2], best[3]; ax = np.arange(-span, span + 1e-6, step)
                for du in ax:
                    for dv in ax:
                        t = (c0u + du) * Bc + (c0v + dv) * Nc; v = sc(t)
                        if v > best[0]: best = (v, t, c0u + du, c0v + dv)
            if curved:
                Tc = self.T[kc]; base_ = best[1]
                for dw in np.arange(-8.0, 8.01, 1.0):
                    for du in np.arange(-1.0, 1.01, 0.5):
                        for dv in np.arange(-1.0, 1.01, 0.5):
                            t = base_ + dw * Tc + du * Bc + dv * Nc; v = sc(t)
                            if v > best[0]: best = (v, t, best[2], best[3])
            if best[0] - s0 < 3.0: best = (s0, np.zeros(3), 0.0, 0.0)                # はっきり良くならなければ動かさない
            out.append((c, *best[1], best[0] - s0, float(curved))); status(f"大動脈の外形で合わせ直しています… {self.rel(c):.0f} mm")
        if len(out) < 2: status("大動脈の外形で合わせ直せませんでした（背骨の重ね合わせのまま）"); return None
        O = np.array(out); T = O[:, 1:4].copy()
        if len(T) >= 3: T = ndimage.median_filter(T, size=(3, 1), mode="nearest")
        T = ndimage.gaussian_filter1d(T, 1.0, axis=0, mode="nearest")
        self.postShift = dict(path=self.path, s=O[:, 0], t=T, mag=np.linalg.norm(T, axis=1))
        mag = self.postShift["mag"]
        status(f"術後 CT を大動脈の外形で合わせ直しました（背骨合わせからのずれ 中央値 {np.median(mag):.1f} mm・最大 {mag.max():.1f} mm）")
        self._restent(status)
        return self.postShift

    def _mprMetal(self, thr=450.0, status=print):
        """薄い MPR（2 mm 以下の冠状断・矢状断）から金属の点を拾う（術後の座標 RAS）。5 mm の軸位より頭尾方向がずっと細かい"""
        files = getattr(self, "postMPR", None) or []
        if not files or getattr(self, "postT", None) is None or self.P is None: return None
        M = self.postT; ck = (id(M), self.path, len(self.P))
        cc_ = getattr(self, "_mprCache", None)
        if cc_ is not None and cc_[0] == ck: return cc_[1]
        import pydicom
        from scipy.spatial import cKDTree
        tree = cKDTree(self.P[::4]); Minv = np.linalg.inv(M)
        from concurrent.futures import ThreadPoolExecutor
        status(f"薄い再構成（{len(files)} 枚）から金属を拾っています…")
        def rd(p):
            try:
                d = pydicom.dcmread(p, force=True)
                a = d.pixel_array.astype(np.float32) * float(getattr(d, "RescaleSlope", 1) or 1) + float(getattr(d, "RescaleIntercept", 0) or 0)
                rr, cc = np.nonzero(a > thr)
                if len(rr) == 0: return None
                if len(rr) > 60000: j = np.random.default_rng(0).choice(len(rr), 60000, replace=False); rr, cc = rr[j], cc[j]
                iop = np.array([float(x) for x in d.ImageOrientationPatient]); ps = [float(x) for x in d.PixelSpacing]; o = np.array([float(x) for x in d.ImagePositionPatient])
                X = o + cc[:, None] * iop[:3] * ps[1] + rr[:, None] * iop[3:] * ps[0]
                X = (X * np.array([-1.0, -1.0, 1.0])).astype(np.float32)             # LPS → RAS（術後の座標）
                Xg = X @ M[:3, :3].T + M[:3, 3]; dd, _ = tree.query(Xg, distance_upper_bound=60.0)
                X = X[np.isfinite(dd)]                                               # 中心線から 60 mm 以内だけ
                return X if len(X) else None
            except Exception: return None
        with ThreadPoolExecutor(8) as ex: parts = [x for x in ex.map(rd, files) if x is not None]
        self._mprCache = (ck, np.concatenate(parts) if parts else None)
        return self._mprCache[1]

    def expansionReport(self, step=2.0):
        """実際のステント（金属に楕円を当てはめる）が、術前の真腔からどれだけ広がったか（断面ごと・区間ごと）"""
        ac = getattr(self, "actual", None)
        if ac is None or ac.get("path") != self.path or not self.tlValid(): return None
        from scipy.spatial import cKDTree
        X = ac["pts"]; _, kk = cKDTree(self.P).query(X); rows = []
        for x in np.arange(ac["lo"] + 2.0, ac["hi"] - 2.0 + 1e-6, step):
            k = self._k(x); m = np.abs(kk - k) <= int(2.0 / STEP)
            if m.sum() < 20: continue
            d = X[m] - self.P[k]; e = _fitEllipse(d @ self.B[k], d @ self.N[k])
            if e is None or not (8.0 < e[2] <= e[1] < 50.0): continue
            xy = self._tlXY(k); t = _polyMetrics(xy) if xy is not None else None
            if t is None: continue
            per_t = float(np.linalg.norm(np.diff(np.r_[xy, xy[:1]], axis=0), axis=1).sum())
            a_, b_ = e[1] / 2, e[2] / 2; area = math.pi * a_ * b_; per = math.pi * (3 * (a_ + b_) - math.sqrt((3 * a_ + b_) * (a_ + 3 * b_)))
            dfl = dwl = np.nan                                                        # 偽腔側（フラップ）と壁側に、術前の真腔の縁からどれだけ動いたか
            try:
                tm = self.tl["masks"][k]; E = self._aortaIn(k, self.path); rc = np.argwhere(tm); tlc = np.c_[rc[:, 1], rc[:, 0]] * STEP - HALF
                fr = np.argwhere((E > 0) & ~tm) if E is not None else np.zeros((0, 2))
                if len(fr) > 50 and len(tlc) > 20:
                    cT = tlc.mean(0); uF = np.c_[fr[:, 1], fr[:, 0]].mean(0) * STEP - HALF - cT; uF /= np.linalg.norm(uF) + 1e-9
                    near = np.abs(d @ self.T[k]) <= 2.5; me = np.c_[d @ self.B[k], d @ self.N[k]][near] if near.sum() >= 15 else np.c_[d @ self.B[k], d @ self.N[k]]
                    pm = (me - cT) @ uF; pt = (tlc - cT) @ uF
                    dfl = float(np.percentile(pm, 95) - pt.max()); dwl = float(-np.percentile(pm, 5) + pt.min())
            except Exception: pass
            rows.append(dict(s=float(x), maj=e[1], min=e[2], area=area, per=per, tl_long=t["dmax"], tl_short=t["dmin"], tl_area=t["area"], tl_per=per_t, d_flap=dfl, d_wall=dwl))
        if len(rows) < 3: return None
        lo, hi = ac["lo"], ac["hi"]; S = np.array([r["s"] for r in rows])
        def summ(msk):
            if not np.any(msk): return None
            g = lambda key: np.array([r[key] for r in rows])[msk]
            return dict(n=int(msk.sum()), maj=float(np.median(g("maj"))), min=float(np.median(g("min"))), tl_long=float(np.median(g("tl_long"))), tl_short=float(np.median(g("tl_short"))),
                        r_long=float(np.median(g("maj") / g("tl_long"))), r_short=float(np.median(g("min") / g("tl_short"))),
                        r_area=float(np.median(g("area") / g("tl_area"))), r_per=float(np.median(g("per") / g("tl_per"))), ratio=float(np.median(g("min") / g("maj"))),
                        d_flap=float(np.nanmedian(g("d_flap"))) if np.isfinite(g("d_flap")).any() else None, d_wall=float(np.nanmedian(g("d_wall"))) if np.isfinite(g("d_wall")).any() else None)
        reg = dict(prox=summ(S < lo + 20.0), mid=summ((S >= lo + 20.0) & (S <= hi - 20.0)), dist=summ(S > hi - 20.0), all=summ(S > -1e9))
        self.expansion = dict(rows=rows, reg=reg, lo=lo, hi=hi)
        return self.expansion

    def saveExpansionCSV(self, d=None):
        ex = getattr(self, "expansion", None)
        if not ex: return None
        import csv
        d = d or self.outDir(); fn = os.path.join(d, "TEVAR_広がり.csv")
        with open(fn, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["位置 mm（中心線）", "基準からの位置 mm", "実際 長径", "実際 短径", "実際 面積 mm2", "実際 周径", "術前真腔 長径", "術前真腔 短径", "術前真腔 面積 mm2", "術前真腔 周径",
                        "長径の比", "短径の比", "面積の比", "周径の比", "偽腔側への広がり mm", "壁側への広がり mm"])
            for r in ex["rows"]:
                w.writerow([f"{r['s']:.1f}", f"{self.rel(r['s']):.1f}", f"{r['maj']:.1f}", f"{r['min']:.1f}", f"{r['area']:.0f}", f"{r['per']:.1f}",
                            f"{r['tl_long']:.1f}", f"{r['tl_short']:.1f}", f"{r['tl_area']:.0f}", f"{r['tl_per']:.1f}",
                            f"{r['maj'] / r['tl_long']:.2f}", f"{r['min'] / r['tl_short']:.2f}", f"{r['area'] / r['tl_area']:.2f}", f"{r['per'] / r['tl_per']:.2f}",
                            f"{r['d_flap']:.1f}" if np.isfinite(r["d_flap"]) else "", f"{r['d_wall']:.1f}" if np.isfinite(r["d_wall"]) else ""])
        return fn

    def _restent(self, status=print, thr=450.0):
        """金属（ステント）を拾い直す: 術後 CT の金属の画素を、背骨の重ね合わせ → 大動脈の外形で合わせ直したずれ の順に術前の座標へ"""
        from scipy.spatial import cKDTree
        ac = getattr(self, "actual", None)
        if ac is None or ac.get("path") != self.path: return
        if "pts0" not in ac: ac["pts0"] = ac["pts"]
        M = self.postT; Y = None
        try: Y = self._mprMetal(thr, status)
        except Exception as e: print("mpr metal:", e)
        src = "薄い再構成"
        if Y is None:
            a1 = slicer.util.arrayFromVolume(self.post); Y = self._volPts(self.post, a1 > thr); src = "軸位"
        X = Y @ M[:3, :3].T + M[:3, 3]
        d, k = cKDTree(self.P).query(X); sel = (d < 45.0) & (self.s[k] >= ac["lo"] - 4.0) & (self.s[k] <= ac["hi"] + 4.0)
        X, k = X[sel], k[sel]
        X = X - self._postShiftAt(k)
        self._ensureArrF(); A = self._rasToIjk; aoD, boD = self._tvMasks(); shp = self.arr.shape
        I = np.round(X @ A[:3, :3].T + A[:3, 3]).astype(int)
        inb = (I[:, 0] >= 0) & (I[:, 0] < shp[2]) & (I[:, 1] >= 0) & (I[:, 1] < shp[1]) & (I[:, 2] >= 0) & (I[:, 2] < shp[0])
        X, I = X[inb], I[inb]
        ok = self.arr[I[:, 2], I[:, 1], I[:, 0]] < 600.0
        if aoD is not None: ok &= aoD[I[:, 2], I[:, 1], I[:, 0]]
        if boD is not None: ok &= ~boD[I[:, 2], I[:, 1], I[:, 0]]
        X = X[ok]
        if len(X) < 30: status("金属を拾い直せませんでした（前の結果のまま）"); return
        if len(X) > 40000: X = X[np.random.default_rng(0).choice(len(X), 40000, replace=False)]
        ac["pts"] = X; _, kk = cKDTree(self.P).query(X); ss = self.s[kk]; ac["s"] = ss
        b_ = np.floor(ss / 2.0).astype(int); cnt = np.bincount(b_, minlength=b_.max() + 1)   # 端も合わせ直した金属で測り直す（まばらな点は端に数えない）
        occ = np.where(cnt >= max(3, 0.2 * np.median(cnt[cnt > 0])))[0]
        if len(occ):
            runs = []; st = pv = occ[0]
            for x_ in occ[1:]:
                if (x_ - pv) * 2.0 > 20.0: runs.append((st, pv)); st = x_
                pv = x_
            runs.append((st, pv)); r0, r1 = max(runs, key=lambda r: cnt[r[0]:r[1] + 1].sum())
            if (r1 + 1 - r0) * 2.0 > 0.5 * (ac["hi"] - ac["lo"]): ac["lo"], ac["hi"] = r0 * 2.0, (r1 + 1) * 2.0
        self._drawActual(); self._drawGreen()
        ac["src"] = src; status(f"金属を拾い直しました（{src}・{len(X)} 点）")

    def postStraight(self):
        """術後 CT を、術前の中心線に沿って伸ばした画像（術前と同じ位置で並べて見られる）"""
        from scipy import ndimage
        post = self.post; Minv = np.linalg.inv(self.postT)
        a = slicer.util.arrayFromVolume(post).astype(np.float32)
        m = vtk.vtkMatrix4x4(); post.GetIJKToRASMatrix(m)
        A = np.linalg.inv(np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])) @ Minv
        u = np.arange(-HALF, HALF + 1e-6, STEP); nu = len(u); UU, VV = np.meshgrid(u, u)
        K = len(self.P); out = np.zeros((K, nu, nu), np.int16)
        for k0 in range(0, K, 64):
            k1 = min(K, k0 + 64)
            sh = self._postShiftAt(np.arange(k0, k1))                                  # 大動脈の外形で合わせ直したずれ（3D）
            Q = self.P[k0:k1, None, None, :] + UU[None, :, :, None] * self.B[k0:k1, None, None, :] + VV[None, :, :, None] * self.N[k0:k1, None, None, :] + sh[:, None, None, :]
            H = Q.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
            out[k0:k1] = ndimage.map_coordinates(a, [H[:, 2], H[:, 1], H[:, 0]], order=1, mode="nearest").reshape(k1 - k0, nu, nu).astype(np.int16)
        node = slicer.mrmlScene.GetFirstNodeByName("SA stretched post") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SA stretched post")
        slicer.util.updateVolumeFromArray(node, out)
        node.SetSpacing(STEP, STEP, STEP); node.SetOrigin(-HALF, -HALF, 0.0)
        mm = vtk.vtkMatrix4x4(); mm.Identity(); mm.SetElement(2, 2, -1.0); node.SetIJKToRASDirectionMatrix(mm)
        node.CreateDefaultDisplayNodes(); dn = node.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        return node

    def showPostStretch(self, on):
        """右のストレッチ像（S2）を術後 CT にする / 戻す"""
        try:
            cn = slicer.app.layoutManager().sliceWidget("Orange").mrmlSliceCompositeNode()
            if on:
                n = slicer.mrmlScene.GetFirstNodeByName("SA stretched post") or self.postStraight()
                cn.SetBackgroundVolumeID(n.GetID()); self.orangeRot = getattr(self, "orangeRot", None)
            else:
                st = self.straight; cn.SetBackgroundVolumeID(st.GetID() if st is not None else None)
        except Exception as e: print("post stretch:", e)
