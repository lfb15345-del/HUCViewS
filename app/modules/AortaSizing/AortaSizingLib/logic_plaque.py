# -*- coding: utf-8 -*-
"""大動脈サイジング（研究用・隠し機能）: プラーク・壁在血栓を断面ごとに拾い、1 個ずつに番号をつけて特徴を出す。
shaggy aorta の見える化・術前後の比較・ラジオミクスの土台。AortaSizingLogic の一部（PlaqueMixin）。

測り方（断面ごと、中心線に直交、既定 1 mm おき）
- 内腔と外周の輪郭（計測と同じもの）に、内腔の重心から 72 方向（5°）の線を引き、
  壁の厚み = 外周までの距離 − 内腔までの距離（放射方向の厚み）
- 壁の中の CT 値（内腔側・外側の縁 0.5 mm は造影剤のにじみ・部分容積を避けて除く）
- 厚みが「拾う厚み」以上のつながった所（長さ方向 × 角度、角度は一周つながる）を 1 個のプラークとする
- Hosaka の shagginess: 内腔の輪郭の長さ ÷（π × 平均径）− 1 の 100 倍（平均径 = 重心を通る 180 方向の径の平均）
"""
from .common import *


class PlaqueMixin:
    PLQ_NTH = 72            # 角度の分け方（5°）
    PLQ_THR = 3.0           # この厚み（mm）以上をプラークとして拾う
    PLQ_DS = 1.0            # 断面の間隔 mm
    PLQ_HU_LOW = 50.0       # 低い CT 値の目安（脂質の多い粥腫・柔らかい血栓）
    PLQ_EDGE = 0.5          # 内腔側・外側の縁は除く（mm）
    PLQ_NOTCH = 1.5         # 潰瘍様のくぼみの候補: 内腔がまわり（±15°）より外へ これ以上 へこむ（mm）

    # ---------------------------------------------------------------- 範囲と小さな道具
    def plaqueRange(self, which="lsca-celiac"):
        """解析の範囲（中心線 mm）と、その名前"""
        bif = self._mk("大動脈分岐"); end = float(bif["s"]) if bif is not None and self._onPath(bif) else float(self.length)
        if which == "aorta": return 0.0, end, "基部〜大動脈分岐"
        if which == "plan":
            pl = getattr(self, "plan", None)
            if pl and pl.get("path") == self.path: return float(pl["p"]), float(pl["d"]), "計画の範囲"
        a = self._mk("左鎖骨下動脈"); c = self._mk("腹腔動脈"); lab_ = "左鎖骨下〜腹腔動脈"
        if c is None or not self._onPath(c): c = self._mk("最下位腎動脈"); lab_ = "左鎖骨下〜最下位腎動脈（腹腔動脈の印なし）"
        s0 = float(a["s"]) if a is not None and self._onPath(a) else 0.0
        s1 = float(c["s"]) if c is not None and self._onPath(c) else end
        if s1 - s0 < 10.0: return 0.0, end, "基部〜大動脈分岐（印が足りない）"
        return s0, s1, lab_

    @staticmethod
    def _polyCentroid(xy):
        x, y = xy[:, 0], xy[:, 1]; x2, y2 = np.roll(x, -1), np.roll(y, -1); cr = x * y2 - x2 * y; A = cr.sum() / 2.0
        if abs(A) < 1e-9: return xy.mean(0)
        return np.array([((x + x2) * cr).sum(), ((y + y2) * cr).sum()]) / (6.0 * A)

    @staticmethod
    def _polyRay(xy, c, th):
        """多角形 xy に、点 c から角度 th の向きの半直線が当たる所までの距離（いちばん遠い交点。当たらなければ nan）"""
        import warnings
        A = np.asarray(xy, float); E = np.roll(A, -1, 0) - A; w = A - np.asarray(c, float)
        d = np.c_[np.cos(th), np.sin(th)]
        den = -d[:, None, 0] * E[None, :, 1] + d[:, None, 1] * E[None, :, 0]
        with np.errstate(divide="ignore", invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            den = np.where(np.abs(den) < 1e-12, np.nan, den)
            t = (-w[None, :, 0] * E[None, :, 1] + w[None, :, 1] * E[None, :, 0]) / den
            u = (d[:, None, 0] * w[None, :, 1] - d[:, None, 1] * w[None, :, 0]) / den
            t = np.where((u >= -1e-9) & (u <= 1 + 1e-9) & (t > 0), t, np.nan)
            return np.nanmax(t, axis=1)

    def _plqZone(self, s):
        get = lambda nm: (lambda m: float(m["s"]) if m is not None and self._onPath(m) else None)(self._mk(nm))
        ls, ce, rn, bf = get("左鎖骨下動脈"), get("腹腔動脈"), get("最下位腎動脈"), get("大動脈分岐")
        if ls is not None and s < ls: return "弓部"
        if bf is not None and s > bf: return "腸骨"
        if rn is not None and s > rn: return "腎動脈下"
        if ce is not None and s > ce: return "腹部分枝の間"
        if ls is not None: return "下行"
        return "?"

    def _plqNearBranch(self, s, lim=10.0):
        best = None
        for nm in ("腕頭動脈", "左総頸動脈", "左鎖骨下動脈", "腹腔動脈", "上腸間膜動脈", "右腎動脈", "左腎動脈", "最下位腎動脈", "大動脈分岐"):
            m = self._mk(nm)
            if m is None or not self._onPath(m): continue
            d = abs(float(m["s"]) - s)
            if d <= lim and (best is None or d < best[1]): best = (nm, d)
        return best

    # ---------------------------------------------------------------- 本体
    def plaqueAnalyze(self, which="lsca-celiac", thr=None, status=print):
        """断面ごとの厚み・CT 値 → プラーク 1 個ずつの特徴。結果は self.plaque"""
        from scipy import ndimage
        if self.P is None or self.straight is None: return None
        thr = float(thr or self.PLQ_THR); s0, s1, rlab = self.plaqueRange(which)
        a = slicer.util.arrayFromVolume(self.straight); K, nu, _ = a.shape
        NT = self.PLQ_NTH; dth = 2 * np.pi / NT; th = (np.arange(NT) + 0.5) * dth
        th180 = np.arange(180) * np.pi / 180.0; E_ = self.PLQ_EDGE
        Tm = ndimage.gaussian_filter1d(self.T, sigma=10 / STEP, axis=0, mode="nearest"); Tm = Tm / np.maximum(np.linalg.norm(Tm, axis=1, keepdims=True), 1e-9)
        kapV = np.gradient(Tm, STEP, axis=0)
        secs = []; t0 = time.time(); xs = np.arange(s0, s1 + 1e-6, self.PLQ_DS)
        for jx, x in enumerate(xs):
            k = self._k(x); lum = self._section(k, "lumen", self.path); out = self._section(k, "outer", self.path)
            if lum is None or out is None or len(lum) < 8 or len(out) < 8: continue
            c = self._polyCentroid(np.asarray(lum, float))
            rl = self._polyRay(lum, c, th); ro = self._polyRay(out, c, th)
            if np.isnan(rl).mean() > 0.2: continue
            if np.isnan(rl).any(): ok = ~np.isnan(rl); rl = np.interp(th, th[ok], rl[ok], period=2 * np.pi)
            ro = np.where(np.isnan(ro), rl, ro); t = np.clip(ro - rl, 0, None)
            # Hosaka
            r1 = self._polyRay(lum, c, th180); r2 = self._polyRay(lum, c, th180 + np.pi); dm = float(np.nanmean(r1 + r2))
            per = float(np.linalg.norm(np.diff(np.r_[lum, lum[:1]], axis=0), axis=1).sum())
            hos = (per / (np.pi * dm) - 1.0) * 100.0 if dm > 1 else float("nan")
            # 壁の中の CT 値（各方向で r_l+縁 〜 r_o−縁 を 0.25 mm ごと）
            img = a[k].astype(np.float32); M = int(min(np.ceil(np.nanmax(t) / 0.25) + 1, 160))
            rs = rl[:, None] + E_ + 0.25 * np.arange(M)[None]; valid = rs <= (ro - E_)[:, None]
            uu = c[0] + rs * np.cos(th)[:, None]; vv = c[1] + rs * np.sin(th)[:, None]
            hu = ndimage.map_coordinates(img, [(vv + HALF) / STEP, (uu + HALF) / STEP], order=1, mode="nearest")
            rin = np.clip(rl[:, None] - 1.0, 0, None) * np.linspace(0, 1, 8)[None]          # 内腔（縁から 1 mm 内側まで）
            hl = ndimage.map_coordinates(img, [(c[1] + rin * np.sin(th)[:, None] + HALF) / STEP, (c[0] + rin * np.cos(th)[:, None] + HALF) / STEP], order=1, mode="nearest")
            lumMed = float(np.median(hl)); thrCa = max(600.0, lumMed + 250.0)
            n_ = valid.sum(1); huS = np.where(valid, hu, 0).sum(1)
            huMean = np.where(n_ > 0, huS / np.maximum(n_, 1), np.nan)
            low = np.where(n_ > 0, (valid & (hu < self.PLQ_HU_LOW)).sum(1) / np.maximum(n_, 1), np.nan)
            ca = np.where(n_ > 0, (valid & (hu > thrCa)).sum(1) / np.maximum(n_, 1), np.nan)
            med = ndimage.median_filter(rl, size=7, mode="wrap"); notch = (rl - med) > self.PLQ_NOTCH
            Rref = float(np.median(rl[t < thr])) if (t < thr).sum() >= 6 else float(np.median(rl)); prot = np.clip(Rref - rl, 0, None)
            areaBin = 0.5 * (ro ** 2 - rl ** 2) * dth
            lA = float(_polyMetrics(np.asarray(lum, float))["area"]); oA = float(_polyMetrics(np.asarray(out, float))["area"])
            secs.append(dict(x=float(x), k=int(k), c=c, rl=rl, ro=ro, t=t, hu=huMean, n=n_, low=low, ca=ca, notch=notch, prot=prot, area=areaBin,
                             hos=hos, lumMed=lumMed, thrCa=thrCa, lDeq=2 * math.sqrt(lA / math.pi), oDeq=2 * math.sqrt(oA / math.pi)))
            if jx % 50 == 0: status(f"プラークを拾っています… {100 * jx // max(len(xs), 1)}%")
        if len(secs) < 3: return None
        J = len(secs); Tmap = np.array([q["t"] for q in secs]); mask = Tmap >= thr
        lab, n = ndimage.label(mask, structure=np.ones((3, 3), int))
        par = list(range(n + 1))
        def f(z):
            while par[z] != z: par[z] = par[par[z]]; z = par[z]
            return z
        for j in range(J):                                                    # 角度は一周つながる（0° と 355°）
            for dj in (-1, 0, 1):
                jj = j + dj
                if 0 <= jj < J and lab[j, NT - 1] and lab[jj, 0]:
                    ra, rb = f(lab[j, NT - 1]), f(lab[jj, 0])
                    if ra != rb: par[ra] = rb
        lab = np.vectorize(lambda z: f(z) if z else 0)(lab) if n else lab
        plaques = []
        for cid in sorted(set(lab[lab > 0].tolist())):
            jj, ii = np.nonzero(lab == cid)
            sx = np.array([secs[j]["x"] for j in jj]); L_ = float(sx.max() - sx.min() + self.PLQ_DS)
            tt = Tmap[jj, ii]
            if len(jj) < 3 or (L_ < 3.0 and tt.max() < 5.0): continue
            ar = np.array([secs[j]["area"][i] for j, i in zip(jj, ii)]); nn = np.array([secs[j]["n"][i] for j, i in zip(jj, ii)])
            huv = np.array([secs[j]["hu"][i] for j, i in zip(jj, ii)]); lowv = np.array([secs[j]["low"][i] for j, i in zip(jj, ii)]); cav = np.array([secs[j]["ca"][i] for j, i in zip(jj, ii)])
            okh = np.isfinite(huv) & (nn > 0)
            wgt = lambda v: float(np.sum(v[okh] * nn[okh]) / max(nn[okh].sum(), 1)) if okh.any() else float("nan")
            jm, im = jj[int(np.argmax(tt))], ii[int(np.argmax(tt))]
            sc = float(np.sum(sx * tt) / tt.sum()); ang = float(np.arctan2(np.sum(np.sin(th[ii]) * tt), np.sum(np.cos(th[ii]) * tt)))
            kc = self._k(sc); wv = math.cos(ang) * self.B[kc] + math.sin(ang) * self.N[kc]; wv = wv - (wv @ self.T[kc]) * self.T[kc]
            clk = ((math.degrees(math.atan2(wv @ np.array([-1.0, 0, 0]), wv @ np.array([0, 1.0, 0]))) + 360) % 360) / 30.0 or 12.0
            kv = kapV[kc]; kn = float(np.linalg.norm(kv))
            if kn < 1.0 / 300.0: side = "まっすぐ"
            else:
                cs = float((wv / (np.linalg.norm(wv) + 1e-9)) @ (kv / kn)); side = "内弯" if cs > 0.5 else ("外弯" if cs < -0.5 else "側方")
            circ = max(int((jj == j).sum()) for j in set(jj.tolist())) * 360.0 / NT
            nb = self._plqNearBranch(sc)
            plaques.append(dict(s0=float(sx.min()), s1=float(sx.max()), length=L_, s=sc, sMax=float(secs[jm]["x"]), angMax=float(th[im]), jMax=int(jm), iMax=int(im),
                                tMax=float(tt.max()), tMean=float(np.sum(tt * ar) / max(ar.sum(), 1e-9)), vol=float(ar.sum() * self.PLQ_DS), circ=circ,
                                hu=wgt(huv), low=wgt(lowv), ca=wgt(cav), ulcer=int(sum(secs[j]["notch"][i] for j, i in zip(jj, ii))),
                                prot=float(max(secs[j]["prot"][i] for j, i in zip(jj, ii))), clock=clk, side=side, zone=self._plqZone(sc),
                                branch=(f"{nb[0]}（{nb[1]:.0f} mm）" if nb else ""), cid=int(cid)))
        plaques.sort(key=lambda q: q["s"])
        for i, q in enumerate(plaques, 1): q["id"] = i
        idOf = {q["cid"]: q["id"] for q in plaques}
        labId = np.vectorize(lambda z: idOf.get(int(z), 0))(lab) if plaques else np.zeros_like(lab)
        sp = self.vol.GetSpacing() if getattr(self, "vol", None) is not None else (np.nan, np.nan, np.nan)
        hosV = np.array([q["hos"] for q in secs]); tmaxS = Tmap.max(1)
        circFrac = (Tmap >= thr).mean(1)
        summ = dict(range=rlab, s0=s0, s1=s1, thr=thr, n=len(plaques), vol=float(sum(q["vol"] for q in plaques)), tMax=float(Tmap.max()),
                    len5=float((tmaxS >= 5.0).sum() * self.PLQ_DS), circ23=bool((circFrac > 2 / 3).any()), ulcer=int(sum(q["ulcer"] for q in plaques)),
                    hosaka=float(np.nanmean(hosV)), nsec=J, spacing=tuple(float(x) for x in sp), time=time.time() - t0)
        summ["shaggyItems"] = int(summ["tMax"] > 5.0) + int(summ["circ23"]) + int(summ["ulcer"] > 0)
        self.plaque = dict(path=self.path, K=K, vol=self.straight, secs=secs, lab=labId, plaques=plaques, summ=summ, which=which)
        self._plqLastDir = None
        status(f"プラーク {len(plaques)} 個（{time.time() - t0:.0f} 秒）")
        return self.plaque

    def plaqueValid(self):
        q = getattr(self, "plaque", None)
        return q is not None and q.get("path") == self.path and q.get("K") == len(self.P) and q.get("vol") is self.straight

    # ---------------------------------------------------------------- 3D: 壁を厚みで色分け・プラークの番号
    def drawPlaque(self, on=True):
        names = ("研究 壁の厚み", "研究 プラーク番号")
        if not on or not self.plaqueValid():
            for nm in names:
                m = slicer.mrmlScene.GetFirstNodeByName(nm)
                if m is not None and m.GetDisplayNode(): m.GetDisplayNode().SetVisibility(False)
            return
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        q = self.plaque; secs = q["secs"]; NT = self.PLQ_NTH; th = (np.arange(NT) + 0.5) * 2 * np.pi / NT; J = len(secs)
        pts = np.zeros((J * NT, 3)); sc = np.zeros(J * NT, np.float32)
        for j, s_ in enumerate(secs):
            k = s_["k"]; r = s_["ro"] + 0.4
            u = s_["c"][0] + r * np.cos(th); v = s_["c"][1] + r * np.sin(th)
            pts[j * NT:(j + 1) * NT] = self.P[k] + u[:, None] * self.B[k] + v[:, None] * self.N[k]; sc[j * NT:(j + 1) * NT] = s_["t"]
        jj, ii = np.meshgrid(np.arange(J - 1), np.arange(NT), indexing="ij"); jj, ii = jj.ravel(), ii.ravel(); i2 = (ii + 1) % NT
        quads = np.stack([jj * NT + ii, jj * NT + i2, (jj + 1) * NT + i2, (jj + 1) * NT + ii], -1)
        cells = np.c_[np.full(len(quads), 4), quads].ravel().astype(np.int64)
        pd = vtk.vtkPolyData(); vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(pts), deep=True)); pd.SetPoints(vp)
        ca = vtk.vtkCellArray(); ca.SetCells(len(quads), numpy_to_vtkIdTypeArray(cells, deep=True)); pd.SetPolys(ca)
        arr = numpy_to_vtk(sc, deep=True); arr.SetName("壁の厚み mm"); pd.GetPointData().AddArray(arr); pd.GetPointData().SetActiveScalars("壁の厚み mm")
        m = self._model("研究 壁の厚み", pd, (1, 1, 1), 1.0, spec=0.1); d = m.GetDisplayNode()
        cn = None
        for nm in ("ColdToHotRainbow", "Inferno", "Viridis", "Rainbow"):
            cn = slicer.mrmlScene.GetFirstNodeByName(nm)
            if cn is not None and cn.IsA("vtkMRMLColorNode"): break
        if cn is not None: d.SetAndObserveColorNodeID(cn.GetID())
        d.SetActiveScalarName("壁の厚み mm"); d.SetScalarVisibility(True)
        d.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseManualScalarRange); d.SetScalarRange(0.0, 8.0)
        lb = self._node("vtkMRMLMarkupsFiducialNode", "研究 プラーク番号", ("vtkMRMLViewNode1",), (1.0, 1.0, 1.0), glyph=0.01, text=3.0)
        wasMod = lb.StartModify(); lb.RemoveAllControlPoints()
        for p_ in q["plaques"]:
            s_ = secs[p_["jMax"]]; k = s_["k"]; a_ = p_["angMax"]; r = s_["ro"][p_["iMax"]] + 4.0
            x = self.P[k] + (s_["c"][0] + r * math.cos(a_)) * self.B[k] + (s_["c"][1] + r * math.sin(a_)) * self.N[k]
            j = lb.AddControlPoint(vtk.vtkVector3d(*x)); lb.SetNthControlPointLabel(j, f"P{p_['id']} {p_['tMax']:.1f}")
        lb.EndModify(wasMod); lb.GetDisplayNode().SetVisibility(True)

    # ---------------------------------------------------------------- 書き出し
    def _plqDir(self):
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例", "研究_プラーク")
        vn = self.vol.GetName() if getattr(self, "vol", None) is not None else "case"
        d = os.path.join(base, f"{vn}_{time.strftime('%Y%m%d_%H%M%S')}"); os.makedirs(d, exist_ok=True); return d

    def plaqueAudit(self):
        q = self.plaque; s = q["summ"]
        nov = len([k for k in getattr(self, "override", {}) if k[0] == self.path and s["s0"] - 1 <= k[2] * STEP <= s["s1"] + 1])
        return [("ソフトの版", self._appVersion()), ("範囲", s["range"]), ("範囲 mm", f"{s['s0']:.0f}–{s['s1']:.0f}"), ("拾う厚み mm", f"{s['thr']:g}"),
                ("断面の間隔 mm", f"{self.PLQ_DS:g}"), ("方向の数", str(self.PLQ_NTH)), ("低い CT 値の目安 HU", f"{self.PLQ_HU_LOW:g}"),
                ("縁を除く mm", f"{self.PLQ_EDGE:g}"), ("くぼみの目安 mm", f"{self.PLQ_NOTCH:g}"),
                ("元の CT の画素間隔 x/y/z mm", "/".join(f"{v:.2f}" for v in s["spacing"])), ("輪郭の手直し（範囲内の断面数）", str(nov))] + _ctProtocol(getattr(self, "vol", None))

    def savePlaqueCSV(self):
        import csv
        if not self.plaqueValid(): return None
        q = self.plaque; s = q["summ"]; d = self._plqDir(); g = lambda v, n=1: "" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{round(v, n) + 0.0:.{n}f}"
        with open(os.path.join(d, "プラーク.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["番号", "始まり mm", "終わり mm", "長さ mm", "最大の厚み mm", "平均の厚み mm", "体積 mm3", "全周に占める最大 度", "CT 値 平均 HU", "低い CT 値の割合",
                        "石灰化の割合", "潰瘍様のくぼみ候補（点）", "内腔への突出 mm", "位置（時、足側から）", "曲がり", "区域", "近くの枝"])
            for p in q["plaques"]:
                w.writerow([p["id"], g(self.rel(p["s0"])), g(self.rel(p["s1"])), g(p["length"]), g(p["tMax"]), g(p["tMean"]), g(p["vol"], 0), g(p["circ"], 0), g(p["hu"], 0),
                            g(p["low"], 2), g(p["ca"], 2), p["ulcer"], g(p["prot"]), g(p["clock"]), p["side"], p["zone"], p["branch"]])
        with open(os.path.join(d, "断面ごと.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh); w.writerow(["位置 mm", "基準からの位置 mm", "内腔 Deq", "外周 Deq", "最大の厚み mm", "拾う厚み以上の割合（全周）", "Hosaka（内腔のギザギザ）", "内腔の CT 値 中央値"])
            for x in q["secs"]:
                w.writerow([g(x["x"]), g(self.rel(x["x"])), g(x["lDeq"]), g(x["oDeq"]), g(float(x["t"].max())), g(float((x["t"] >= s["thr"]).mean()), 2), g(x["hos"], 2), g(x["lumMed"], 0)])
        vn = self.vol.GetName() if getattr(self, "vol", None) is not None else ""
        row = [("保存日時", time.strftime("%Y-%m-%d %H:%M")), ("画像（シリーズ）", vn), ("研究 ID（手で記入）", ""), ("経路", self.path),
               ("プラークの数", str(s["n"])), ("体積の合計 mm3", g(s["vol"], 0)), ("最大の厚み mm", g(s["tMax"])), ("厚み 5 mm 以上の長さ mm", g(s["len5"], 0)),
               ("全周の 2/3 を超える所", "あり" if s["circ23"] else "なし"), ("潰瘍様のくぼみ候補（点）", str(s["ulcer"])), ("shaggy の 3 項目（候補を含む）", str(s["shaggyItems"])),
               ("Hosaka（範囲の平均）", g(s["hosaka"], 2)), ("断面の数", str(s["nsec"]))] + self.plaqueAudit()
        hdr = [k for k, _ in row]; val = [v for _, v in row]
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例"); allfn = os.path.join(base, "プラーク_一覧.csv")
        if os.path.exists(allfn):
            try: old = open(allfn, encoding="utf-8-sig").readline().strip()
            except Exception: old = ""
            if old != ",".join(hdr): allfn = os.path.join(base, "プラーク_一覧_" + time.strftime("%Y%m%d") + ".csv")
        new = not os.path.exists(allfn)
        with open(allfn, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
            w = csv.writer(fh)
            if new: w.writerow(hdr)
            w.writerow(val)
        self._plqLastDir = d
        return d, allfn

    def savePlaqueMasks(self, d=None):
        """ラジオミクス用: 伸ばした画像（範囲だけ）と、プラークの番号のラベル（同じ格子）を NRRD で"""
        if not self.plaqueValid(): return None
        q = self.plaque; secs = q["secs"]; NT = self.PLQ_NTH; dth = 2 * np.pi / NT
        a = slicer.util.arrayFromVolume(self.straight); K, nu, _ = a.shape
        k0 = max(min(x["k"] for x in secs) - 2, 0); k1 = min(max(x["k"] for x in secs) + 2, K - 1)
        lab3 = np.zeros((k1 - k0 + 1, nu, nu), np.uint16)
        cols, rows = np.meshgrid(np.arange(nu) * STEP - HALF, np.arange(nu) * STEP - HALF)
        hstep = max(int(round(self.PLQ_DS / STEP)), 1)
        for j, x in enumerate(secs):
            ids = q["lab"][j]
            if not ids.any(): continue
            uu = cols - x["c"][0]; vv = rows - x["c"][1]; rr = np.hypot(uu, vv); b = (np.floor((np.arctan2(vv, uu) % (2 * np.pi)) / dth).astype(int)) % NT
            inside = (rr > x["rl"][b]) & (rr <= x["ro"][b]) & (ids[b] > 0)
            sl = np.where(inside, ids[b], 0).astype(np.uint16)
            for kk in range(x["k"], min(x["k"] + hstep, k1 + 1)): lab3[kk - k0] = np.maximum(lab3[kk - k0], sl)
        d = d or getattr(self, "_plqLastDir", None) or self._plqDir()
        m = vtk.vtkMatrix4x4(); self.straight.GetIJKToRASMatrix(m)
        o = [sum(m.GetElement(r, c_) * v for c_, v in enumerate((0, 0, k0, 1))) for r in range(3)]
        out = []
        for cls_, nm, arr in (("vtkMRMLScalarVolumeNode", "plaque_image", np.ascontiguousarray(a[k0:k1 + 1])), ("vtkMRMLLabelMapVolumeNode", "plaque_label", lab3)):
            n_ = slicer.mrmlScene.AddNewNodeByClass(cls_, "研究 " + nm); n_.SetIJKToRASMatrix(m); n_.SetOrigin(*o)
            slicer.util.updateVolumeFromArray(n_, arr); fn = os.path.join(d, nm + ".nrrd")
            slicer.util.saveNode(n_, fn, {"useCompression": True}); slicer.mrmlScene.RemoveNode(n_); out.append(fn)
        open(os.path.join(d, "マスクの説明.txt"), "w", encoding="utf-8").write(
            "plaque_image.nrrd = 中心線に沿って伸ばした画像（0.5 mm 格子、中心線に直交する断面を積み重ねたもの。元の CT から補間）\n"
            "plaque_label.nrrd = 同じ格子でのプラークの番号（プラーク.csv の番号と同じ。0 = プラークでない）\n"
            "注意: 伸ばした画像は元の CT を補間したもの。元の CT のスライス厚が厚いと、長さ方向のきめは粗くなる。\n"
            + "\n".join(f"{k}: {v}" for k, v in self.plaqueAudit()) + "\n")
        return out
