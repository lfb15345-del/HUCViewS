# -*- coding: utf-8 -*-
"""大動脈サイジング: 手術のイメージ（教育用）— 人工血管・ステントグラフト・フェルト・頸部分枝・フラップの色分け
AortaSizingLogic の一部（GraftMixin）。
・自動: 伸ばした画像の断面の形（人工弁のリング・正円で太さ一定・フェルトの輪・ステントの始まり／終わり・太さの段差）。
        細かい再構成画像（0.3 mm 前後）を選ぶと、人工血管のしわ（スキャロップ、約 2.8 mm 間隔）も根拠にする。
・手で直す: 中心線の「ここから〜ここまで」を人工血管にする／外す。頸部分枝の吻合部を 3D でクリック。
・CT を加工して作る手術のイメージ（教育・説明用）。診断には使わない。"""
from .common import *
from scipy import ndimage

GP = "手術 "                                                                # この機能で作るモデルの名前の頭（画面を離れる時に隠す）
WHITE = (0.96, 0.96, 0.94); FELT = (0.86, 0.82, 0.70); FABRIC = (0.93, 0.94, 0.97)
RED = (0.78, 0.18, 0.18); FLAP = (0.96, 0.72, 0.74); METALC = (0.80, 0.83, 0.90)
ST = 0.5                                                                    # 伸ばした画像の断面の間隔（mm）
BR_KEYS = ("brachiocephalic trunk", "common carotid artery left", "subclavian artery left",
           "common carotid artery right", "subclavian artery right")


def _runs(mask, minlen):
    out = []; k = 0; n = len(mask)
    while k < n:
        if mask[k]:
            j = k
            while j + 1 < n and mask[j + 1]: j += 1
            if j - k + 1 >= minlen: out.append((k, j))
            k = j + 1
        else: k += 1
    return out


def _merge(rs, gap=0):
    out = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1] + gap + 1: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out


def _sub(rs, a0, b0):
    out = []
    for a, b in rs:
        if b < a0 or a > b0: out.append((a, b)); continue
        if a < a0: out.append((a, a0 - 1))
        if b > b0: out.append((b0 + 1, b))
    return out


def _poly(P, T):
    from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
    o = vtk.vtkPolyData(); vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(P, dtype=np.float64), deep=True)); o.SetPoints(vp)
    T = np.asarray(T, np.int64).reshape(-1, 3)
    cells = np.hstack([np.full((len(T), 1), 3, np.int64), T]).ravel()
    ca = vtk.vtkCellArray(); ca.SetCells(len(T), numpy_to_vtkIdTypeArray(np.ascontiguousarray(cells), deep=True)); o.SetPolys(ca)
    nm = vtk.vtkPolyDataNormals(); nm.SetInputData(o); nm.SplittingOff(); nm.ConsistencyOn(); nm.Update()
    out = vtk.vtkPolyData(); out.DeepCopy(nm.GetOutput()); return out


def _cyl(a, b, r, crimp=0.0, period=2.5, sides=32):
    """点 a〜b の筒（半径 r、crimp: しわの深さ）"""
    a = np.asarray(a, float); b = np.asarray(b, float); w = b - a; L = np.linalg.norm(w)
    if L < 0.5: return None
    w /= L; e = np.array([1.0, 0, 0]) if abs(w[0]) < 0.9 else np.array([0, 1.0, 0]); u = np.cross(w, e); u /= np.linalg.norm(u); v = np.cross(w, u)
    ss = np.linspace(0, L, max(2, int(L / 0.5) + 1)); ang = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    rr = r + (crimp * np.sin(2 * np.pi * ss / period) if crimp > 0 else 0 * ss)
    Q = a[None, None, :] + ss[:, None, None] * w[None, None, :] + rr[:, None, None] * (np.cos(ang)[None, :, None] * u[None, None, :] + np.sin(ang)[None, :, None] * v[None, None, :])
    n = len(ss); i = np.arange(n - 1)[:, None]; k = np.arange(sides)[None, :]
    p0 = i * sides + k; p1 = i * sides + (k + 1) % sides; p2 = (i + 1) * sides + (k + 1) % sides; p3 = (i + 1) * sides + k
    T = np.concatenate([np.stack([p0, p1, p2], -1).reshape(-1, 3), np.stack([p0, p2, p3], -1).reshape(-1, 3)])
    return _poly(Q.reshape(-1, 3), T)


def _tri(pd):
    from vtk.util.numpy_support import vtk_to_numpy
    tf = vtk.vtkTriangleFilter(); tf.SetInputData(pd); tf.Update(); t = tf.GetOutput()
    return vtk_to_numpy(t.GetPoints().GetData()).astype(float), vtk_to_numpy(t.GetPolys().GetConnectivityArray()).reshape(-1, 3)


class GraftMixin:
    # ================================================================ 断面の特徴
    def _gSections(self):
        """伸ばした画像から、断面ごと・72 方向の内腔の半径と、縁の金属・石灰化、外側 1〜7 mm の濃い輪（フェルト）"""
        S = slicer.util.arrayFromVolume(self.straight).astype(np.float32); K, nu, _ = S.shape; c = nu // 2
        ang = np.linspace(0, 2 * np.pi, 72, endpoint=False); rr = np.arange(0, 38, 0.25); idx = np.arange(len(rr))
        X = c + np.outer(np.cos(ang), rr / ST); Y = c + np.outer(np.sin(ang), rr / ST)
        core = S[:, c - 3:c + 4, c - 3:c + 4].reshape(K, -1); lum = np.median(core, axis=1)
        thr = np.clip(0.5 * (lum + 60.0), 120, 400)
        R = np.zeros((K, 72)); metal = np.zeros((K, 72), bool); felt = np.zeros((K, 72), bool); calc = np.zeros((K, 72), bool)
        for k in range(K):
            prof = ndimage.map_coordinates(S[k], [Y.ravel(), X.ravel()], order=1).reshape(72, len(rr))
            inside = prof > thr[k]; first = np.argmax(~inside, axis=1); first[inside.all(1)] = len(rr) - 1
            R[k] = rr[first]; d = idx[None, :] - first[:, None]
            ring = (d >= -12) & (d < 12); out = (d >= 4) & (d < 28)
            metal[k] = ((prof >= 1500) & ring).any(1); calc[k] = ((prof >= 600) & (prof < 1500) & ring).any(1)
            felt[k] = ((prof >= 180) & (prof < 1500) & out).any(1)
        return dict(R=R, metal=metal.astype(float), felt=felt.astype(float), calc=calc.astype(float), thr=thr)

    def _gClassify(self, f):
        """形からの判定: ステントグラフト（縁の金属が 30 mm 以上）・人工弁のリング・人工血管（正円で太さ一定、フェルトの輪から）"""
        R = f["R"]; K = len(R); r = np.median(R, axis=1); mm = lambda x: max(1, int(round(x / ST)))
        circ = ndimage.uniform_filter1d(1 - R.std(1) / np.maximum(R.mean(1), 1e-3), mm(6))
        met = ndimage.uniform_filter1d(f["metal"].mean(1) + 0.5 * f["calc"].mean(1), mm(10))
        stent = ndimage.binary_closing(met >= 0.08, iterations=mm(10)) & (met >= 0.02)
        st = _merge(_runs(stent, mm(30)), mm(40))
        feltK = ndimage.uniform_filter1d(f["felt"].mean(1), mm(4)); metK = f["metal"].mean(1)
        valve = None; ring = np.nonzero(metK[:mm(20)] >= 0.06)[0]
        if len(ring) and ring.max() - ring.min() <= mm(15) and not any(a <= mm(15) for a, b in st): valve = (int(ring.min()), int(ring.max()))
        def feltNear(k, w=12):
            a, b = max(0, k - mm(w)), min(K, k + mm(w)); j = a + int(np.argmax(feltK[a:b])); return j if feltK[j] >= 0.40 else None
        start = None; rings = []
        if valve is not None: start = valve[0]
        else:
            good = (circ >= 0.86) & (r >= 9) & (r <= 18)
            for k in range(mm(5), min(K, mm(60))):
                if good[k:k + mm(10)].all():
                    j = feltNear(k)
                    if j is not None: start = k; rings.append(j)
                    break
        graft = []
        if start is not None:
            nxt = [a for a, b in st if a > start]
            if nxt and (nxt[0] - start) * ST <= 200: end = nxt[0]
            else:
                end = start; bad = 0
                for k in range(start, K):
                    if circ[k] >= 0.75 and r[k] > 3: end = k; bad = 0
                    else:
                        bad += 1
                        if bad > mm(15): break
            graft = [(start, end)]
            j = feltNear(end)
            if j is not None and all(abs(j - x) > mm(8) for x in rings): rings.append(j)
        for a, b in st:                                                     # ステントの端のフェルト（FET の吻合部など）
            for e in (a, b):
                j = feltNear(e, 8)
                if j is not None and all(abs(j - x) > mm(8) for x in rings): rings.append(j)
        return dict(stent=st, graft=graft, rings=sorted(rings), valve=valve, r=r, circ=circ)

    def _gWrap(self, f, c):
        """ステントの区間で、外側が人工血管（ステントにぴったり・丸い）の所。外周の直径 − 内腔の直径 ≤ 8 mm かつ 外周が丸い"""
        prof = getattr(self, "prof", None)
        if prof is None or len(prof) != len(f["R"]): return []
        lum = 2 * np.median(f["R"], axis=1); outer = np.nan_to_num(prof[:, 1]); ratio = prof[:, 3] / np.maximum(prof[:, 2], 1e-3)
        tight = ndimage.uniform_filter1d((((outer - lum) <= 8.0) & (ratio >= 0.82)).astype(float), int(10 / ST)) >= 0.6
        out = []
        for a, b in c["stent"]:
            for x, y in _runs(tight[a:b + 1], int(15 / ST)): out.append((a + x, a + y))
        return out

    # ================================================================ しわ（スキャロップ）
    def _gStraightFrom(self, vol, s0, s1, ds=0.25, half=30.0, du=0.3, path=None):
        """中心線（path = (s, P, N, B)、無ければ大動脈）にそって、別の（細かい）画像から伸ばした画像を作る"""
        a = slicer.util.arrayFromVolume(vol); s_, P_, N_, B_ = path if path is not None else (self.s, self.P, self.N, self.B)
        M = vtk.vtkMatrix4x4(); vol.GetRASToIJKMatrix(M); R2I = np.array([[M.GetElement(i, j) for j in range(4)] for i in range(4)])
        sk = np.arange(s0, s1, ds); P = np.c_[[np.interp(sk, s_, P_[:, j]) for j in range(3)]].T
        N = np.c_[[np.interp(sk, s_, N_[:, j]) for j in range(3)]].T; N /= np.linalg.norm(N, axis=1, keepdims=True)
        B = np.c_[[np.interp(sk, s_, B_[:, j]) for j in range(3)]].T; B /= np.linalg.norm(B, axis=1, keepdims=True)
        u = np.arange(-half, half + 1e-6, du); n = len(u); out = np.full((len(sk), n, n), -1000.0, np.float32)
        for c0 in range(0, len(sk), 200):                                   # 少しずつ（メモリ節約）
            c1 = min(len(sk), c0 + 200)
            allp = P[c0:c1, None, None, :] + u[None, :, None, None] * N[c0:c1, None, None, :] + u[None, None, :, None] * B[c0:c1, None, None, :]
            ijk = (R2I[:3, :3] @ allp.reshape(-1, 3).T).T + R2I[:3, 3]
            lo = np.maximum(np.floor(ijk.min(0)).astype(int) - 2, 0); hi = np.minimum(np.ceil(ijk.max(0)).astype(int) + 3, np.array(a.shape[::-1]))
            if np.any(hi <= lo): continue
            sub = a[lo[2]:hi[2], lo[1]:hi[1], lo[0]:hi[0]].astype(np.float32)
            out[c0:c1] = ndimage.map_coordinates(sub, [ijk[:, 2] - lo[2], ijk[:, 1] - lo[1], ijk[:, 0] - lo[0]], order=1, cval=-1000).reshape(c1 - c0, n, n)
        return out, sk, B, N

    @staticmethod
    def _gEdge(S, du, nang=72):
        """伸ばした画像で、断面ごと・方向ごとの内腔のふちの半径（しきい値を横切る所を直線補間）"""
        K, nu, _ = S.shape; c = nu // 2; ang = np.linspace(0, 2 * np.pi, nang, endpoint=False); rr = np.arange(0, nu // 2 * du - du, 0.2)
        X = c + np.outer(np.cos(ang), rr / du); Y = c + np.outer(np.sin(ang), rr / du)
        lum = np.median(S[:, c - 3:c + 4, c - 3:c + 4].reshape(K, -1), axis=1); th = np.clip(0.5 * (lum + 60.0), 120, 400)
        R = np.full((K, nang), np.nan); MET = np.zeros((K, nang), bool)
        for k in range(K):
            prof = ndimage.map_coordinates(S[k], [Y.ravel(), X.ravel()], order=1).reshape(nang, len(rr))
            below = prof < th[k]; f = np.argmax(below, axis=1); ok = below.any(1) & (f > 0)
            i0 = np.clip(f - 1, 0, len(rr) - 1); p0 = prof[np.arange(nang), i0]; p1 = prof[np.arange(nang), f]
            w = np.clip((p0 - th[k]) / np.maximum(p0 - p1, 1e-3), 0, 1); R[k, ok] = (rr[i0] + w * 0.2)[ok]
            near = (rr[None, :] >= np.nan_to_num(R[k], nan=0)[:, None] - 2) & (rr[None, :] <= np.nan_to_num(R[k], nan=0)[:, None] + 4)
            MET[k] = ((prof >= 1200) & near).any(1)
        return R, MET

    def _gScallop(self, hires, status=print, s1=300.0, ds=0.25):
        """細かい画像でふちの傾き（陰影と同じ）を調べ、2.2〜3.6 mm 間隔のしわがそろって出る所を返す（中心線の番号の区間）"""
        status("人工血管のしわ（スキャロップ）を探しています…")
        S, sk, B, N = self._gStraightFrom(hires, 0, min(float(self.s[-1]), s1), ds=ds, half=30, du=0.3)
        R, MET = self._gEdge(S, 0.3)
        K, na = R.shape; ang = np.linspace(0, 2 * np.pi, na, endpoint=False)
        M = vtk.vtkMatrix4x4(); hires.GetIJKToRASDirectionMatrix(M); nrm = np.array([M.GetElement(i, 2) for i in range(3)])
        sp = hires.GetSpacing(); thick = int(np.argmax(sp))                 # いちばん粗い向き（再構成画像のスライスの向き）
        nrm = np.array([M.GetElement(i, thick) for i in range(3)])
        dirn = np.abs(np.cos(ang)[None, :] * (B @ nrm)[:, None] + np.sin(ang)[None, :] * (N @ nrm)[:, None])
        Rf = R.copy()
        for a in range(na):
            x = Rf[:, a]; bad = np.isnan(x)
            if bad.all(): Rf[:, a] = 0; continue
            x[bad] = np.interp(np.where(bad)[0], np.where(~bad)[0], x[~bad])
        D = np.gradient(ndimage.gaussian_filter1d(Rf, 0.3 / ds, axis=0), ds, axis=0); D -= ndimage.gaussian_filter1d(D, 6.0 / ds, axis=0)
        METr = ndimage.binary_dilation(MET, np.ones((int(4 / ds), 3)))
        W = int(12 / ds); han = np.hanning(W)[:, None]; NF = 4 * W; fr = np.fft.rfftfreq(NF, ds); per = 1 / np.maximum(fr, 1e-9)
        pk = (per >= 2.2) & (per <= 3.6); lo = (per > 3.6) & (per <= 7.0); hi = (per >= 1.4) & (per < 2.2)
        vote = np.zeros(K)
        for kc in range(W // 2, K - W // 2, 2):
            k0 = kc - W // 2; good = (dirn[kc] < 0.5) & ~METr[k0:k0 + W].any(0)
            if good.sum() < 8: continue
            seg = D[k0:k0 + W][:, good]; seg = seg - seg.mean(0); Pw = np.abs(np.fft.rfft(seg * han, n=NF, axis=0)) ** 2
            vote[kc:kc + 2] = (Pw[pk].max(0) > 2.5 * np.maximum(Pw[lo].mean(0), Pw[hi].mean(0))).mean()
        vote = ndimage.uniform_filter1d(vote, int(4 / ds))
        seeds = []
        for a, b in _runs(vote >= 0.35, int(4 / ds)):
            seeds.append((int(round(sk[a] / ST)), int(round(sk[b] / ST))))
        self.gVote = (sk, vote)
        return seeds

    def _gExtend(self, seeds, c):
        """しわが見つかった所を、両側の吻合部（フェルトの輪・ステントの始まり・弁のリング）まで広げる。無ければ正円が続く所まで"""
        K = len(c["r"]); circ, r = c["circ"], c["r"]; mm = lambda x: int(round(x / ST))
        bounds = sorted(set(list(c["rings"]) + [a for a, b in c["stent"]] + ([c["valve"][0]] if c["valve"] else [])))
        out = []
        for a, b in seeds:
            lo = max([x for x in bounds if x <= a], default=None); hi = min([x for x in bounds if x >= b], default=None)
            if lo is None:
                lo = a
                while lo > 0 and circ[lo - 1] >= 0.75 and r[lo - 1] > 3 and a - lo < mm(150): lo -= 1
            if hi is None:
                hi = b
                while hi < K - 1 and circ[hi + 1] >= 0.75 and r[hi + 1] > 3 and hi - b < mm(150): hi += 1
            out.append((int(lo), int(hi)))
        return out

    # ================================================================ 頸部分枝
    def _gBranchTrack(self, m, excl=None):
        """枝のラベルを体軸の断面ごとにたどる: 中心の点・内腔の太さ（直交断面に補正）・起始部からの距離"""
        a = self._gArr(); sp = np.array(self.vol.GetSpacing()); px = sp[0] * sp[1]; I2R = self._ijk2ras()
        zs = np.where(m.any((1, 2)))[0]; pts = []; prev = None
        for z in zs:
            lb, n = ndimage.label(m[z])
            if n == 0: continue
            cms = ndimage.center_of_mass(m[z], lb, range(1, n + 1)); sz = ndimage.sum(m[z], lb, range(1, n + 1))
            j = int(np.argmax(sz)) if prev is None else int(np.argmin([np.hypot(q[0] - prev[0], q[1] - prev[1]) for q in cms]))
            cy, cx = cms[j]
            if prev is not None and np.hypot(cy - prev[0], cx - prev[1]) * sp[0] > 15: continue
            prev = (cy, cx); comp = lb == j + 1
            reg = ndimage.binary_dilation(comp, iterations=2) & (a[z] > 200) & (a[z] < 1000)
            if excl is not None: reg &= ~excl[z]                         # 静脈（無名静脈・上大静脈）やとなりの枝は太さに入れない
            l2, n2 = ndimage.label(reg); jj = l2[int(cy), int(cx)]
            if jj == 0 and n2 and comp.any(): jj = np.bincount(l2[comp]).argmax()
            pts.append((z, cx, cy, ((l2 == jj).sum() if jj else comp.sum()) * px))
        if len(pts) < 4: return None
        P = np.array(pts, float)
        R = (I2R @ np.c_[P[:, 1], P[:, 2], P[:, 0], np.ones(len(P))].T).T[:, :3]
        Rs = ndimage.gaussian_filter1d(R, 1.0, axis=0, mode="nearest"); T = np.gradient(Rs, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
        D = 2 * np.sqrt(P[:, 3] * np.abs(T[:, 2]) / np.pi); s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Rs, axis=0), axis=1))]
        sd = np.arange(0, s[-1] + 0.25, 0.5)                               # 0.5 mm ごと（境目がギザギザにならないように）
        return dict(R=np.c_[[np.interp(sd, s, Rs[:, j]) for j in range(3)]].T, s=sd, D=np.interp(sd, s, ndimage.median_filter(D, 3, mode="nearest")))

    @staticmethod
    def _gStep(s, D, smax=70.0, minL=9.0, minR=12.0, minStep=1.0):
        """起始部から smax mm までで、太さが段差で変わる所（2 段の一定値で一番よく合う所）。見つからなければ None"""
        k = (s >= 5.0) & (s <= smax); s_, D_ = s[k], D[k]; best = None          # 起始部の 5 mm は部分容積で細く見えるので使わない
        for i in range(1, len(s_)):
            if s_[i] < minL or s_[-1] - s_[i] < minR: continue
            l, r = D_[:i], D_[i:]; sse = ((l - l.mean()) ** 2).sum() + ((r - r.mean()) ** 2).sum()
            if best is None or sse < best[0]: best = (sse, i, l.mean(), r.mean())
        if best is None or abs(best[2] - best[3]) < max(minStep, 0.08 * best[2]): return None
        return float(0.5 * (s_[best[1] - 1] + s_[best[1]]))

    def _gBranchHires(self, t, hires, smax=90.0):
        """細かい画像で枝にそって切った像から、吻合部らしい所を探す:
        ① くびれ（太さが前後より 2 割以上細い所）  ② 継ぎ目の線（内腔を横切る細い暗い線、ふだんの 1.8 倍以上）。8〜60 mm で最初の所"""
        sd = t["s"]; P = ndimage.gaussian_filter1d(t["R"], 4, axis=0, mode="nearest"); T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
        N = np.cross(T, [1.0, 0, 0]); N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-6); B = np.cross(T, N)
        S, sk, _, _ = self._gStraightFrom(hires, 0, min(float(sd[-1]), smax), ds=0.25, half=12, du=0.25, path=(sd, P, N, B))
        R, MET = self._gEdge(S, 0.25, 36)
        if np.isnan(R).mean() > 0.5: return None
        D = ndimage.median_filter(np.nan_to_num(2 * np.nanmedian(R, axis=1)), 9)
        c = S.shape[1] // 2; yy, xx = np.mgrid[:S.shape[1], :S.shape[1]]; rad = np.hypot(yy - c, xx - c) * 0.25; seam = np.zeros(len(sk))
        for k in range(len(sk)):
            m = rad <= max(1.0, 0.375 * D[k])
            if m.sum() < 10 or D[k] < 2: continue
            v = ndimage.gaussian_filter(S[k], 0.8)[m]; seam[k] = np.median(v) - np.percentile(v, 3)
        seam = ndimage.uniform_filter1d(seam, 6); w = int(4 / 0.25); g0 = int(2 / 0.25)
        rng = [k for k in range(int(8 / 0.25), min(len(sk) - w - g0, int(60 / 0.25)))]
        if not rng: return None
        base = np.median(seam[rng[0]:rng[-1] + 1]) + 1e-3
        for k in rng:                                                        # ① くびれ
            l = np.median(D[k - g0 - w:k - g0]); r = np.median(D[k + g0:k + g0 + w])
            if D[k] > 2 and D[k] < 0.8 * min(l, r) and D[k] == D[max(0, k - w):k + w].min(): return float(sk[k])
        for k in rng:                                                        # ② 継ぎ目の線
            if seam[k] >= 1.8 * base and seam[k] == seam[max(0, k - w):k + w].max(): return float(sk[k])
        return None

    def _gBranches(self, status=print, hires=None):
        status("頸部分枝をたどっています…")
        tr = {}; sA = {}
        vein = self._mask(("brachiocephalic vein", "superior vena cava", "subclavian vein", "jugular vein"))   # 濃く染まった無名静脈が枝に重なる
        vein = None if vein is None else ndimage.binary_dilation(vein, iterations=1)
        ms = {key: self._mask((key,)) for key in BR_KEYS}
        for key in BR_KEYS:
            m = ms[key]
            if m is not None and m.any():
                ex = vein.copy() if vein is not None else np.zeros(m.shape, bool)
                for k2, m2 in ms.items():
                    if k2 != key and m2 is not None: ex |= m2 & ~m
                t = self._gBranchTrack(m & ~(vein if vein is not None else False), ex)
                if t is not None: tr[key] = t
        def anast(key, **kw):
            h = None
            if hires is not None:
                try: h = self._gBranchHires(tr[key], hires)
                except Exception as e: print("[graft] branch hires", key, e)
            return h if h is not None else self._gStep(tr[key]["s"], tr[key]["D"], **kw)
        for key in BR_KEYS[:3]:
            if key in tr:
                st_ = anast(key); sA[key] = st_ if st_ is not None else float(tr[key]["s"][-1]) + 1.0
        if "brachiocephalic trunk" in tr and sA.get("brachiocephalic trunk", 0) > tr["brachiocephalic trunk"]["s"][-1]:
            for key in BR_KEYS[3:]:                                         # 腕頭で段差なし → 右総頸・右鎖骨下でさがす
                if key in tr:
                    st_ = anast(key, minL=3.0); sA[key] = st_ if st_ is not None else 0.0
        for key in tr: sA.setdefault(key, -1.0)
        return tr, sA

    # ================================================================ 大動脈の中の膜（フラップ）
    def _gMembrane(self, skip=()):
        S = slicer.util.arrayFromVolume(self.straight).astype(np.float32); K, nu, _ = S.shape; c = nu // 2
        yy, xx = np.mgrid[:nu, :nu]; rad = np.hypot(yy - c, xx - c) * ST
        disk = lambda r: (np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r)
        skipK = np.zeros(K, bool)
        for a, b in skip: skipK[max(0, a - int(3 / ST)):min(K, b + int(3 / ST))] = True
        M = np.zeros(S.shape, bool)
        for k in range(K):
            if skipK[k]: continue
            t = ndimage.gaussian_filter(S[k], 0.6); lum = np.percentile(S[k][rad < 12], 90)
            if lum < 200: continue
            lo = 60 + 0.3 * (lum - 60); hi = 0.5 * (lum + 60)
            lb, n = ndimage.label((t >= lo) & (t < 600)); keep = np.zeros((nu, nu), bool)
            for i in range(1, n + 1):
                mm_ = lb == i
                if mm_.sum() >= 30 and rad[mm_].min() <= 10: keep |= mm_
            if not keep.any(): continue
            ins = ndimage.binary_fill_holes(ndimage.binary_closing(np.pad(keep, 10), disk(6))[10:-10, 10:-10]); ins = ndimage.binary_erosion(ins, disk(2))
            th = ndimage.grey_closing(t, footprint=disk(5)) - t
            mk = ins & (th >= 55) & (t < hi); mk &= ~ndimage.binary_opening(mk, disk(4)); mk &= ndimage.binary_erosion(ins, disk(2))
            mk &= ~ndimage.binary_dilation(t >= 500, disk(6))
            lb, nn = ndimage.label(mk, np.ones((3, 3)))
            if nn >= 1:                                                     # 一番大きい膜に沿った曲線から 3 mm 以内だけ（血栓のふち・壁ぎわを除く）
                sz_ = ndimage.sum(mk, lb, range(1, nn + 1)); P0 = np.argwhere(lb == 1 + int(np.argmax(sz_))).astype(float)
                if len(P0) >= 8:
                    mu = P0.mean(0); U = np.linalg.svd(P0 - mu, full_matrices=False)[2]; Q0 = (P0 - mu) @ U.T
                    deg = 2 if np.ptp(Q0[:, 0]) * ST > 6 else 1; cf = np.polyfit(Q0[:, 0], Q0[:, 1], deg)
                    for _ in range(2):
                        inl = np.abs(Q0[:, 1] - np.polyval(cf, Q0[:, 0])) * ST <= 2.0
                        if inl.sum() >= 8: cf = np.polyfit(Q0[inl, 0], Q0[inl, 1], deg)
                    PA = np.argwhere(mk); QA = (PA - mu) @ U.T; ok_ = np.abs(QA[:, 1] - np.polyval(cf, QA[:, 0])) * ST <= 3.0
                    mk = np.zeros_like(mk); mk[PA[ok_, 0], PA[ok_, 1]] = True
            M[k] = mk
        M = ndimage.binary_opening(M, np.ones((5, 1, 1), bool)); M = ndimage.binary_closing(M, np.ones((5, 3, 3), bool))
        lab, n = ndimage.label(M)
        if n == 0: return None
        sz = ndimage.sum(M, lab, range(1, n + 1)); ok = np.zeros(n + 1, bool); ok[1:] = sz >= 4000
        for i in np.where(ok)[0]:
            sl = ndimage.find_objects((lab == i).astype(np.uint8))[0]
            if (sl[0].stop - sl[0].start) * ST < 20: ok[i] = False
        M = ok[lab]
        return M if M.any() else None

    # ================================================================ 形づくり
    def _gArr(self):
        if getattr(self, "_gA", None) is None or getattr(self, "_gAvol", None) is not self.vol:
            self._gA = slicer.util.arrayFromVolume(self.vol); self._gAvol = self.vol
        return self._gA

    def _gTube(self, R, k0, k1, off=0.4, crimp=0.0, period=3.0):
        """中心線の k0〜k1 に、測った内腔の形（72 方向の半径）で筒の面を作る（crimp: しわの深さ mm）"""
        P, N, B = self.P, self.N, self.B; ang = np.linspace(0, 2 * np.pi, 72, endpoint=False); k1 = min(k1, len(P) - 1)
        if k1 - k0 < 2: return None
        Rs = ndimage.median_filter(R[k0:k1 + 1], size=(9, 5), mode="nearest"); Rs = ndimage.gaussian_filter(Rs, (3, 1.5), mode=("nearest", "wrap"))
        ks = np.arange(k0, k1 + 1)
        if crimp > 0: Rs = Rs + crimp * np.sin(2 * np.pi * (ks - k0)[:, None] * ST / period)
        Q = P[ks, None, :] + (Rs + off)[:, :, None] * (np.cos(ang)[None, :, None] * B[ks, None, :] + np.sin(ang)[None, :, None] * N[ks, None, :])
        n = len(ks); i = np.arange(n - 1)[:, None]; a = np.arange(72)[None, :]
        p0 = i * 72 + a; p1 = i * 72 + (a + 1) % 72; p2 = (i + 1) * 72 + (a + 1) % 72; p3 = (i + 1) * 72 + a
        T = np.concatenate([np.stack([p0, p1, p2], -1).reshape(-1, 3), np.stack([p0, p2, p3], -1).reshape(-1, 3)])
        return _poly(Q.reshape(-1, 3), T)

    def _gModel(self, name, pd, color, opacity=1.0, spec=0.25, power=15):
        m = self._model(GP + name, pd, color, opacity, False, spec); d = m.GetDisplayNode(); d.SetPower(power)
        m.SetAttribute("SA.graft", "1"); return m

    def _gVessel(self):
        """3D の血管（SA 血管）を写して使う（大動脈サイジングの面そのものは変えない）"""
        vm = getattr(self, "vesselModel", None) or slicer.mrmlScene.GetFirstNodeByName("SA 血管")
        if vm is None or vm.GetPolyData() is None: return None, None
        return _tri(vm.GetPolyData())

    # ================================================================ 自動の判定
    def graftAuto(self, status=print, hires=None, flap=True):
        """断面の形（＋細かい画像があればしわ）から、人工血管・ステント・フェルト・頸部分枝・フラップを判定して描く"""
        if self.P is None or self.straight is None: raise RuntimeError("先に中心線を作ってください。")
        status("断面の形を調べています…")
        f = self._gSections(); c = self._gClassify(f); wr = self._gWrap(f, c)
        seeds = []
        if hires is not None:
            try: seeds = self._gScallop(hires, status)
            except Exception as e: print("[graft] scallop", e); seeds = []
        graft = list(c["graft"])
        if seeds: graft = _merge(graft + self._gExtend(seeds, c))
        tr, sA = self._gBranches(status, hires)
        memb = None
        if flap:
            status("大動脈の中の膜（フラップ）を探しています…")
            try: memb = self._gMembrane(skip=list(c["stent"]) + graft + wr)
            except Exception as e: print("[graft] membrane", e)
        self.gState = dict(f=f, c=c, wr=wr, seeds=seeds, auto=graft, tracks=tr, sAuto=sA, memb=memb,
                           manual=getattr(self, "gState", {}).get("manual", []) if getattr(self, "gState", None) and getattr(self, "_gStateVol", None) is self.vol else [],
                           brManual=getattr(self, "gState", {}).get("brManual", {}) if getattr(self, "gState", None) and getattr(self, "_gStateVol", None) is self.vol else {})
        self._gStateVol = self.vol
        return self.graftRender(status)

    def _gFinal(self):
        g = self.gState; K = len(self.P); graft = list(g["auto"])
        for a, b, on in g["manual"]:
            a, b = max(0, min(a, b)), min(K - 1, max(a, b))
            graft = _merge(graft + [(a, b)]) if on else _sub(graft, a, b)
        return graft

    # ================================================================ 描く
    def graftRender(self, status=print):
        from vtk.util.numpy_support import vtk_to_numpy
        from scipy.spatial import cKDTree
        g = self.gState; f, c = g["f"], g["c"]; R = f["R"]; K = len(self.P); s = self.s; mm = lambda x: int(round(x / ST))
        self.graftClear(keepState=True)
        graft = self._gFinal()
        cov = np.zeros(K, bool)
        for a, b in graft: cov[a:b + 1] = True
        # ステントの外側: 人工血管の端から続く所。フェルト（吻合部）より先は FET などステントグラフトの布
        ends = [b for a, b in graft]; over = []; fabric = []
        for a, b in sorted(g["wr"]):
            if not any(abs(a - e) <= mm(10) for e in ends): continue
            ring = [x for x in c["rings"] if a - mm(6) <= x <= b]
            if ring:
                if ring[0] > a: over.append((a, ring[0]))
            else: over.append((a, b)); ends.append(b)
        for a, b in over: cov[a:b + 1] = True
        native = []                                                         # ステントの区間のうち、外が自分の大動脈の所
        for a, b in c["stent"]:
            k = a
            for oa, ob in sorted(over + [x for x in graft if x[0] <= b and x[1] >= a]):
                if oa > k: native.append((k, min(b, oa - 1)))
                k = max(k, ob + 1)
            if k <= b: native.append((k, b))
        # 血管の面（写し）: 人工血管の区間は除く（枝は残す）・ステントのまわり／膜のまわりは半透明に
        P_, T_ = self._gVessel()
        if P_ is not None:
            dd, kk = cKDTree(self.P).query(P_); rr = ndimage.median_filter(np.median(R, axis=1), size=21)
            bad = cov[kk] & (dd <= rr[kk] + 6.0); keep = ~bad[T_].any(1)
            semi = np.zeros(K, bool)
            for a, b in native: semi[a:b + 1] = True
            mb = g.get("memb")
            if mb is not None:
                ks = np.where(mb.any(axis=(1, 2)))[0]; semi[max(0, ks[0] - 20):min(K, ks[-1] + 20)] = True
            sm = semi[kk][T_].any(1)
            T1 = T_[keep & ~sm]; T2 = T_[keep & sm]
            if len(T1): self._gModel("大動脈", _poly(P_, T1), RED, 1.0, 0.45, 22)
            if len(T2): self._gModel("大動脈（半透明）", _poly(P_, T2), RED, 0.28, 0.3, 22)
            vm = getattr(self, "vesselModel", None) or slicer.mrmlScene.GetFirstNodeByName("SA 血管")
            if vm is not None and vm.GetDisplayNode(): vm.GetDisplayNode().SetVisibility(False)
        man = np.zeros(K, bool)
        for a, b, on in g["manual"]:
            if on: man[max(0, min(a, b)):max(a, b) + 1] = True
        for i, (a, b) in enumerate(graft):
            m = self._gTube(R, a, b, off=0.5, crimp=0.35)
            if m is not None: self._gModel(f"人工血管{i + 1}", m, WHITE, 1.0)
        for i, (a, b) in enumerate(over):
            m = self._gTube(R, a, b, off=1.2, crimp=0.35)
            if m is not None: self._gModel(f"人工血管（ステントの外）{i + 1}", m, WHITE, 0.6)
        for i, (a, b) in enumerate(c["stent"]):
            m = self._gTube(R, a, b, off=0.3)
            if m is not None: self._gModel(f"ステントグラフト（布）{i + 1}", m, FABRIC, 0.6)
        for i, k in enumerate(c["rings"]):
            m = self._gTube(R + 1.6, max(0, k - 5), min(K - 1, k + 5), off=0.5)
            if m is not None: self._gModel(f"フェルト{i + 1}", m, FELT, 1.0)
        self._gMetal(); self._gFlapModel()
        # 頸部分枝: AI のラベル（TotalSegmentator）は術後の頸部で別の所（造影されていない組織など）を枝としていることがあり、
        # 間違った血管を出すのはビューアとして致命的なので、確かめた方法でたどれるまで出さない（BRANCHES_FROM_AI = False）
        if getattr(self, "BRANCHES_FROM_AI", False): self._gBranchModels()
        txt = []
        if graft: txt.append("人工血管 " + "、".join(f"{s[a]:.0f}〜{s[b]:.0f} mm" for a, b in graft))
        if c["stent"]: txt.append("ステント " + "、".join(f"{s[a]:.0f}〜{s[b]:.0f} mm" for a, b in c["stent"]))
        if c["rings"]: txt.append("フェルト " + "、".join(f"{s[k]:.0f}" for k in c["rings"]) + " mm")
        if g["seeds"]: txt.append("しわ（スキャロップ）" + "、".join(f"{s[a]:.0f}〜{s[b]:.0f}" for a, b in g["seeds"]) + " mm")
        if g["manual"]: txt.append(f"手で直した所 {len(g['manual'])} か所")
        self.gSummary = " ／ ".join(txt); status("手術のイメージ: " + (self.gSummary or "人工血管は見つかりませんでした"))
        return self.gSummary

    def _gMetal(self):
        a = self._gArr(); ao = self._mask(("aorta",))
        if ao is None: return
        met = (a >= 1500) & ndimage.binary_dilation(ao, iterations=6)
        if not met.any(): return
        from vtk.util.numpy_support import numpy_to_vtk
        img = vtk.vtkImageData(); img.SetDimensions(met.shape[2], met.shape[1], met.shape[0])
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(met.astype(np.float32).ravel()), deep=True))
        gs = vtk.vtkImageGaussianSmooth(); gs.SetInputData(img); gs.SetStandardDeviations(0.5, 0.5, 0.5); gs.Update()
        fe = vtk.vtkFlyingEdges3D(); fe.SetInputConnection(gs.GetOutputPort()); fe.SetValue(0, 0.35); fe.Update()
        M = vtk.vtkMatrix4x4(); self.vol.GetIJKToRASMatrix(M); t = vtk.vtkTransform(); t.SetMatrix(M)
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputConnection(fe.GetOutputPort()); tp.SetTransform(t); tp.Update()
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(tp.GetOutputPort()); nm.SplittingOff(); nm.Update()
        pd = vtk.vtkPolyData(); pd.DeepCopy(nm.GetOutput()); m = self._gModel("金属", pd, METALC, 1.0, 0.9, 70)

    def _gBranchModels(self):
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
        from scipy.spatial import cKDTree
        g = self.gState; tr = g["tracks"]
        if not tr: return
        m = self._mask(("brachiocephalic trunk", "common carotid artery", "subclavian artery"))
        if m is None or not m.any(): return
        vein = self._mask(("brachiocephalic vein", "superior vena cava", "subclavian vein", "jugular vein"))
        if vein is not None: m = m & ~vein                                  # 枝の面に静脈を混ぜない
        img = vtk.vtkImageData(); img.SetDimensions(m.shape[2], m.shape[1], m.shape[0])
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(m.astype(np.float32).ravel()), deep=True))
        sp = self.vol.GetSpacing(); sd = [max(0.6, 1.3 / x) for x in sp]          # 1.3 mm でならす（厚いスライスの段々を消す）
        gs = vtk.vtkImageGaussianSmooth(); gs.SetInputData(img); gs.SetStandardDeviations(*sd); gs.SetRadiusFactors(3, 3, 3); gs.Update()
        fe = vtk.vtkFlyingEdges3D(); fe.SetInputConnection(gs.GetOutputPort()); fe.SetValue(0, 0.42); fe.Update()
        M = vtk.vtkMatrix4x4(); self.vol.GetIJKToRASMatrix(M); t = vtk.vtkTransform(); t.SetMatrix(M)
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputConnection(fe.GetOutputPort()); tp.SetTransform(t); tp.Update()
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(tp.GetOutputPort()); sm.SetNumberOfIterations(40); sm.SetPassBand(0.02); sm.NormalizeCoordinatesOn(); sm.NonManifoldSmoothingOn(); sm.Update()
        pd = vtk.vtkPolyData(); pd.DeepCopy(sm.GetOutput())
        X = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        keys = list(tr.keys()); allP = np.vstack([tr[k]["R"] for k in keys]); ids = np.concatenate([np.full(len(tr[k]["s"]), i) for i, k in enumerate(keys)])
        sv = np.concatenate([tr[k]["s"] for k in keys]); _, nn_ = cKDTree(allP).query(X)
        sA = dict(g["sAuto"]); sA.update(g.get("brManual", {}))
        lim = np.array([sA.get(keys[i], -1.0) for i in range(len(keys))])
        sc = lim[ids[nn_]] - sv[nn_]                                        # ＋ = 起始部側（人工血管）
        arr = numpy_to_vtk(np.ascontiguousarray(sc), deep=True); arr.SetName("g"); pd.GetPointData().SetScalars(arr)
        cp = vtk.vtkClipPolyData(); cp.SetInputData(pd); cp.SetValue(0.0); cp.GenerateClippedOutputOn(); cp.Update()
        gr = cp.GetOutput(); nat = cp.GetClippedOutput()
        if gr.GetNumberOfPoints():
            nm = vtk.vtkPolyDataNormals(); nm.SetInputData(gr); nm.SplittingOff(); nm.ComputePointNormalsOn(); nm.Update(); gp = nm.GetOutput()
            Y = vtk_to_numpy(gp.GetPoints().GetData()).astype(float); Nn = vtk_to_numpy(gp.GetPointData().GetNormals()).astype(float)
            _, n2 = cKDTree(allP).query(Y); Y = Y + (0.35 * np.sin(2 * np.pi * sv[n2] / 2.5))[:, None] * Nn
            vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(Y), deep=True)); gp.SetPoints(vp); gp.GetPointData().SetScalars(None)
            nm2 = vtk.vtkPolyDataNormals(); nm2.SetInputData(gp); nm2.SplittingOff(); nm2.Update(); o = vtk.vtkPolyData(); o.DeepCopy(nm2.GetOutput())
            self._gModel("頸部分枝（人工血管）", o, WHITE, 1.0)
        if nat.GetNumberOfPoints():
            nat.GetPointData().SetScalars(None); nm = vtk.vtkPolyDataNormals(); nm.SetInputData(nat); nm.SplittingOff(); nm.Update()
            o = vtk.vtkPolyData(); o.DeepCopy(nm.GetOutput()); self._gModel("頸部分枝", o, RED, 1.0, 0.45, 22)
        # 枝の始まり（AI のラベルは大動脈から少し離れて始まる）と大動脈の人工血管の間を筒でつなぐ（途切れて見えないように）
        Rm = np.median(g["f"]["R"], axis=1); tree = cKDTree(self.P); app_w = vtk.vtkAppendPolyData(); app_r = vtk.vtkAppendPolyData(); nw = nr = 0
        for key in BR_KEYS[:3]:
            t_ = tr.get(key)
            if t_ is None: continue
            p0 = t_["R"][0]; d0, k = tree.query(p0)
            if d0 > Rm[k] + 30: continue                                    # 大動脈から遠すぎる（たどり違い）
            u = (p0 - self.P[k]) / max(d0, 1e-3); q = self.P[k] + u * max(Rm[k] - 2.0, 1.0)
            sel = (t_["s"] >= 5) & (t_["s"] <= 20); r = 0.5 * float(np.median(t_["D"][sel] if sel.any() else t_["D"]))
            gk = sA.get(key, -1.0) > 0; cy = _cyl(q, p0 + u * 1.5, max(r, 2.0), 0.3 if gk else 0.0)
            if cy is None: continue
            (app_w if gk else app_r).AddInputData(cy)
            if gk: nw += 1
            else: nr += 1
        if nw: app_w.Update(); o = vtk.vtkPolyData(); o.DeepCopy(app_w.GetOutput()); self._gModel("頸部分枝（人工血管・つなぎ）", o, WHITE, 1.0)
        if nr: app_r.Update(); o = vtk.vtkPolyData(); o.DeepCopy(app_r.GetOutput()); self._gModel("頸部分枝（つなぎ）", o, RED, 1.0, 0.45, 22)

    def _gFlapModel(self):
        M = self.gState.get("memb")
        if M is None: return
        from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        K, nu, _ = M.shape; c = nu // 2; idx = np.where(M.any(axis=(1, 2)))[0]
        a, b = max(0, idx[0] - 3), min(K, idx[-1] + 4); F = ndimage.gaussian_filter(M[a:b].astype(np.float32), 1.0)
        im = vtk.vtkImageData(); im.SetDimensions(nu, nu, b - a); im.GetPointData().SetScalars(numpy_to_vtk(F.ravel().copy(), deep=True))
        fe = vtk.vtkFlyingEdges3D(); fe.SetInputData(im); fe.SetValue(0, 0.25); fe.ComputeNormalsOff(); fe.Update()
        pd = fe.GetOutput()
        if pd.GetNumberOfPoints() == 0: return
        X = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        kf = X[:, 2] + a; k0 = np.clip(np.floor(kf).astype(int), 0, K - 2); w = (kf - k0)[:, None]
        P = self.P[k0] * (1 - w) + self.P[k0 + 1] * w; Bv = self.B[k0] * (1 - w) + self.B[k0 + 1] * w; Nv = self.N[k0] * (1 - w) + self.N[k0 + 1] * w
        Q = P + (X[:, 0:1] - c) * ST * Bv + (X[:, 1:2] - c) * ST * Nv
        vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(Q), deep=True)); pd.SetPoints(vp)
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputData(pd); sm.SetNumberOfIterations(20); sm.SetPassBand(0.05); sm.NormalizeCoordinatesOn(); sm.Update()
        o_ = sm.GetOutput(); o_.GetPointData().Initialize()
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(o_); nm.SplittingOff(); nm.Update(); o = vtk.vtkPolyData(); o.DeepCopy(nm.GetOutput())
        self._gModel("フラップ", o, FLAP, 1.0, 0.2, 15)

    # ================================================================ 手で直す
    def graftEdit(self, s0, s1, on, status=print):
        """中心線の s0〜s1 mm を人工血管にする（on=True）／外す（on=False）"""
        if not getattr(self, "gState", None): raise RuntimeError("先に「自動で色分け」を押してください。")
        k0, k1 = int(round(min(s0, s1) / ST)), int(round(max(s0, s1) / ST))
        self.gState["manual"].append((k0, k1, bool(on))); return self.graftRender(status)

    def graftUndo(self, status=print):
        g = getattr(self, "gState", None)
        if not g: return ""
        if g["manual"]: g["manual"].pop()
        elif g.get("brManual"): g["brManual"].popitem()
        return self.graftRender(status)

    def graftBranchAt(self, ras, status=print):
        """3D でクリックした点に一番近い頸部分枝の、その位置を吻合部にする（起始部〜そこまでが人工血管）"""
        g = getattr(self, "gState", None)
        if not g or not g["tracks"]: raise RuntimeError("頸部分枝が見つかっていません。")
        best = None
        for key, t in g["tracks"].items():
            d = np.linalg.norm(t["R"] - np.asarray(ras)[None, :], axis=1); i = int(np.argmin(d))
            if best is None or d[i] < best[0]: best = (d[i], key, float(t["s"][i]))
        if best[0] > 15: raise RuntimeError("枝から離れています（15 mm 以内をクリックしてください）。")
        g.setdefault("brManual", {})[best[1]] = best[2]
        try:                                                                # 先生が決めた吻合部を記録（自動の判定を合わせる正解に使う。位置だけで個人の情報は入れない）
            import os, csv, datetime
            f_ = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例", "手術のイメージ_吻合部.csv"); os.makedirs(os.path.dirname(f_), exist_ok=True)
            new_ = not os.path.exists(f_)
            with open(f_, "a", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                if new_: w.writerow(["日時", "シリーズ", "枝", "起始部からの距離mm", "自動mm", "R", "A", "S"])
                w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), self.vol.GetName() if self.vol else "", best[1], round(best[2], 1),
                            round(float(g["sAuto"].get(best[1], -1)), 1)] + [round(float(x), 1) for x in ras])
        except Exception as e: print("[graft] log", e)
        self.graftRender(status); return best[1], best[2]

    def graftShow(self, on):
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if n.GetName().startswith(GP) and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(bool(on))
        vm = getattr(self, "vesselModel", None) or slicer.mrmlScene.GetFirstNodeByName("SA 血管")
        if vm is not None and vm.GetDisplayNode(): vm.GetDisplayNode().SetVisibility(not on)

    def graftClear(self, keepState=False):
        for n in list(slicer.util.getNodesByClass("vtkMRMLModelNode")):
            if n.GetName().startswith(GP): slicer.mrmlScene.RemoveNode(n)
        if not keepState:
            self.gState = None
            vm = getattr(self, "vesselModel", None) or slicer.mrmlScene.GetFirstNodeByName("SA 血管")
            if vm is not None and vm.GetDisplayNode(): vm.GetDisplayNode().SetVisibility(True)
