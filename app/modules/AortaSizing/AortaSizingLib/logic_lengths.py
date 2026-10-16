# -*- coding: utf-8 -*-
"""大動脈サイジング: 長さ: 中心線・内弯・外弯、自動の目印、3D の定規
AortaSizingLogic の一部（LengthMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class LengthMixin:

    # ---------------------------------------------------------------- 計測
    def _curveLengths(self, s0, s1, path=None, rad=None):
        """中心線・内弯・外弯の長さ（内弯 = 曲がりの内側）。壁の側の長さ = ∫(1 ∓ κ r) ds（κ = 中心線の曲率、r = 半径）。
        rad を渡すとその半径（例: グラフト）、無ければ大動脈の Deq/2"""
        F = self.frames[path or self.path]; P, T = F["P"], F["T"]
        k0, k1 = self._k(s0, path), self._k(s1, path)
        if k1 - k0 < 2: return 0.0, 0.0, 0.0
        from scipy import ndimage
        Tm = ndimage.gaussian_filter1d(T, sigma=10 / STEP, axis=0, mode="nearest"); Tm = Tm / np.maximum(np.linalg.norm(Tm, axis=1, keepdims=True), 1e-9)
        kap = np.linalg.norm(np.gradient(Tm, STEP, axis=0), axis=1)[k0:k1 + 1]
        if rad is not None: r = np.broadcast_to(np.asarray(rad, float), (k1 - k0 + 1,)) if np.ndim(rad) == 0 else np.interp(np.linspace(0, 1, k1 - k0 + 1), np.linspace(0, 1, len(rad)), rad)
        else:
            pr = self.prof if (path or self.path) == self.path else None
            r = np.array([(pr[k, 1] if pr is not None and k < len(pr) and not np.isnan(pr[k, 1]) else 20.0) / 2 for k in range(k0, k1 + 1)])
        ds = np.linalg.norm(np.diff(P[k0:k1 + 1], axis=0), axis=1); kr = 0.5 * (kap[:-1] * r[:-1] + kap[1:] * r[1:])
        return float(ds.sum()), float((ds * np.clip(1 - kr, 0, None)).sum()), float((ds * (1 + kr)).sum())

    # ---------------------------------------------------------------- ぽちっと: 目印を自動で置いて、長さを 3D に
    LEN_SPECS = {"EVAR": [("Neck", "最下位腎動脈", "ネック終端（瘤の始まり）", "chain"), ("Sac", "ネック終端（瘤の始まり）", "大動脈分岐", "chain"),
                          ("{S}CIA", "大動脈分岐", "{side}内腸骨起始", "chain"), ("{S}EIA", "{side}内腸骨起始", "{side}遠位（総大腿）", "chain"),
                          ("Renal-Bif", "最下位腎動脈", "大動脈分岐", "total"), ("Renal-{S}IIA", "最下位腎動脈", "{side}内腸骨起始", "total"),
                          ("Renal-{S}Dist", "最下位腎動脈", "{side}遠位（総大腿）", "total")],
                 "TEVAR": [("LCCA-LSCA", "左総頸動脈", "左鎖骨下動脈", "chain"), ("LSCA-PLZ", "左鎖骨下動脈", "近位ランディング", "chain"),
                           ("PLZ-DLZ", "近位ランディング", "遠位ランディング", "chain"), ("DLZ-Celiac", "遠位ランディング", "腹腔動脈", "chain")]}

    def _side(self, path=None):
        return "左" if "左" in (path or self.path or "") else "右"

    def autoLandmarks(self):
        """径の推移から: ネック終端（瘤の始まり）・瘤の最大径・内腸骨起始 を自動で置く（? つき。手で置いた印は動かさない）。→ 置いた名前・メモ"""
        from scipy import ndimage
        if self.prof is None: return [], []
        S = self.s; De = ndimage.gaussian_filter1d(np.nan_to_num(self.prof[:, 1]), 2.0 / STEP)
        ratio = self.prof[:, 2] / np.maximum(self.prof[:, 3], 1e-3)
        put, note = [], []
        def place(name, sv):
            m = self._mk(name)
            if m is not None and not m.get("auto"): return
            self.addMarker(name, float(sv), auto=True); put.append(name)
        ren = self._mk("最下位腎動脈"); bif = self._mk("大動脈分岐")
        if ren is not None and self._onPath(ren):
            k0 = self._k(ren["s"]); kb = self._k(bif["s"]) if bif is not None and self._onPath(bif) else min(len(S) - 1, k0 + int(150 / STEP))
            if bif is None:                                                   # 分岐: 腎動脈の下で、断面が 2 つの腔で長くなり、そのあと細くなる所
                for k in range(k0 + int(20 / STEP), min(len(S) - int(20 / STEP), k0 + int(220 / STEP))):
                    if ratio[k] > 1.6 and np.median(De[k + int(10 / STEP):k + int(20 / STEP)]) < 0.8 * np.median(De[k - int(20 / STEP):k - int(10 / STEP)]):
                        place("大動脈分岐", S[k]); kb = k; break
            D0 = float(np.median(De[k0:k0 + int(5 / STEP) + 1])); run = int(5 / STEP); ne = None
            for k in range(k0 + int(5 / STEP), kb - int(10 / STEP)):
                if np.all(De[k:k + run] > 1.1 * D0): ne = k; break
            if ne is not None:
                km = ne + int(np.argmax(De[ne:kb - int(5 / STEP)])) if kb - int(5 / STEP) > ne else ne
                if De[km] >= max(30.0, 1.3 * D0):
                    place("ネック終端（瘤の始まり）", S[ne]); place("瘤の最大径", S[km])
                else: note.append(f"腎動脈下の径 {D0:.0f} mm → 最大 {De[km]:.0f} mm（瘤なし）")
            else: note.append(f"腎動脈下の径 {D0:.0f} mm・瘤なし（ネック = 分岐まで）")
        bif = self._mk("大動脈分岐")
        if bif is not None and self._onPath(bif) and self.path in self.frames:
            kb = self._k(bif["s"]); a, b = kb + int(15 / STEP), min(len(S) - int(20 / STEP), kb + int(120 / STEP)); w = int(6 / STEP); w2 = int(16 / STEP)
            for k in range(a, b):                                             # 内腸骨起始: 断面が枝の口で長くなり（長径/短径 > 1.8）、そのあと細くなる所
                if ratio[k] > 1.8 and np.median(De[k + w:k + w2]) < 0.9 * np.median(De[max(k - w2, 0):k - w]):
                    k1 = k
                    while k1 > a and ratio[k1 - 1] > 1.3: k1 -= 1
                    place(f"{self._side()}内腸骨起始", S[k1]); break
            else: note.append(f"{self._side()}内腸骨起始は見つかりませんでした（手で置けます）")
        return put, note

    def lengthRows(self, tpl):
        """テンプレートの長さ（印の間の中心線の長さ）: [(英語ラベル, 日本語, s0, s1, 中心線, 内弯, 外弯)]"""
        out = []
        side = self._side(); S_ = "R" if side == "右" else "L"
        for lab, a, b, kind in self.LEN_SPECS.get(tpl, []):
            a, b = a.replace("{side}", side), b.replace("{side}", side); lab = lab.replace("{S}", S_)
            ma, mb = self._mk(a), self._mk(b)
            if ma is None or mb is None or not self._onPath(ma) or not self._onPath(mb): continue
            s0, s1 = sorted((ma["s"], mb["s"]))
            if s1 - s0 < 1.0: continue
            cl, inn, o = self._curveLengths(s0, s1)
            if lab == "Renal-Bif" and self._mk("ネック終端（瘤の始まり）") is None: kind = "chain"   # 瘤が無ければ 腎動脈→分岐 がつながった区間
            out.append((lab, f"{a.replace('（瘤の始まり）', '')} → {b.replace('（瘤の始まり）', '')}", s0, s1, cl, inn, o, kind))
        pl = getattr(self, "plan", None)
        if tpl == "TEVAR" and pl and pl.get("path") == self.path:
            lg = self.planLengths()
            if lg: out.append(("Graft", "計画のグラフト（治療長）", pl["p"], pl["d"], lg["cl"], lg["inner"], lg["outer"], "total"))
        out.sort(key=lambda r: (r[7] != "chain", r[2], r[3]))
        return out

    def drawLengths(self, tpl, on=True):
        """長さを 3D に: 血管の横に定規のような線と「Neck 25 mm」の文字"""
        names = ("SA 長さ（線）", "SA 長さ（文字）")
        if not on or self.P is None:
            for nm in names:
                n = slicer.mrmlScene.GetFirstNodeByName(nm)
                if n is not None and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(False)
            return []
        rows = self.lengthRows(tpl)
        app = vtk.vtkAppendPolyData(); txt = self._node("vtkMRMLMarkupsFiducialNode", "SA 長さ（文字）", ("vtkMRMLViewNode1",), (1.0, 0.95, 0.4), glyph=0.01, text=3.2)
        wasMod = txt.StartModify(); txt.RemoveAllControlPoints()
        nC = nT = 0
        for i, (lab, _, s0, s1, cl, inn, o, kind) in enumerate(rows):
            ks = np.arange(self._k(s0), self._k(s1) + 1)
            if len(ks) < 2: continue
            if kind == "chain": up = np.array([-1.0, 0.0, 0.0]); lev = 0; lab_off = 4.0 + 12.0 * (nC % 2); nC += 1     # つながった区間: 患者の左側に 1 列（短い区間が続く時は文字を左右にずらす）
            else: up = np.array([1.0, 0.0, 0.0]); lev = nT; lab_off = 4.0; nT += 1                                  # 合計: 患者の右側に、外へ並べる
            D = np.nan_to_num(self.prof[ks, 1], nan=20.0) if self.prof is not None else np.full(len(ks), 20.0)
            off = up[None] - (self.T[ks] @ up)[:, None] * self.T[ks]; off /= np.maximum(np.linalg.norm(off, axis=1, keepdims=True), 1e-6)
            X = self.P[ks] + off * (D[:, None] / 2 + 6.0 + 8.0 * lev)
            pts = vtk.vtkPoints(); [pts.InsertNextPoint(*x) for x in X]
            line = vtk.vtkPolyLine(); line.GetPointIds().SetNumberOfIds(len(X))
            for j in range(len(X)): line.GetPointIds().SetId(j, j)
            ca = vtk.vtkCellArray(); ca.InsertNextCell(line); pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetLines(ca)
            tb = vtk.vtkTubeFilter(); tb.SetInputData(pd); tb.SetRadius(0.9); tb.SetNumberOfSides(8); tb.Update(); app.AddInputData(tb.GetOutput())
            for e in (X[0], X[-1]):                                           # 端の小さな玉
                sp = vtk.vtkSphereSource(); sp.SetCenter(*e); sp.SetRadius(1.8); sp.Update(); app.AddInputData(sp.GetOutput())
            jm = len(X) // 2 if kind == "chain" else len(X) - 1 - min(len(X) // 4, int(8 / STEP))                       # 合計の文字は下の端の近くに（重ならない）
            j = txt.AddControlPoint(vtk.vtkVector3d(*(X[jm] + off[jm] * lab_off))); txt.SetNthControlPointLabel(j, f"{lab} {cl:.0f} mm")
        txt.EndModify(wasMod); txt.GetDisplayNode().SetVisibility(True)
        if app.GetNumberOfInputConnections(0) or rows:
            app.Update(); self._model("SA 長さ（線）", app.GetOutput(), (1.0, 0.85, 0.3), 1.0, spec=0.2)
        return rows

    def _tangent(self, s0, s1, path=None):
        F = self.frames[path or self.path]; k0, k1 = sorted((self._k(s0, path), self._k(s1, path)))
        t = F["T"][k0:k1 + 1].mean(0); return t / (np.linalg.norm(t) + 1e-12)

    def between(self, r1, r2):
        a, b = self.markers[r1], self.markers[r2]
        if a["s"] > b["s"]: a, b = b, a
        path = b["path"] if b["s"] > getattr(self, "sharedLen", 0) else a["path"]
        if path not in self.frames: return "この経路はまだ作っていません。3D で線をクリックして切り替えてください。"
        cl, inn, out = self._curveLengths(a["s"], b["s"], path)
        ang = _angle(self._tangent(a["s"] - 10, a["s"], path), self._tangent(b["s"], b["s"] + 10, path))
        d = np.linalg.norm(np.array(a["xyz"]) - np.array(b["xyz"]))
        ma, mb = self.metricsAt(a["s"], path), self.metricsAt(b["s"], path)
        txt = [f"{a['name']} → {b['name']}（{PATH_EN.get(path, path)}）",
               f"中心線の長さ {cl:.1f} mm　直線距離 {d:.1f} mm", f"内弯 {inn:.1f} mm　外弯 {out:.1f} mm",
               f"屈曲角（両端の向きの差） {ang:.0f}°"]
        if ma: txt.append(f"{a['name']}: Dmax {ma['dmax']:.1f} / Dmin {ma['dmin']:.1f} / Deq {ma['deq']:.1f} mm")
        if mb: txt.append(f"{b['name']}: Dmax {mb['dmax']:.1f} / Dmin {mb['dmin']:.1f} / Deq {mb['deq']:.1f} mm")
        return "\n".join(txt)

    def neckMeasurement(self):
        if self.P is None: return "中心線がありません"
        s0 = self.curS; lines = [f"ネック計測（{self.rel(s0):+.1f} mm から遠位へ）", "  位置    外周 Dmax / Dmin / Deq      内腔 Dmax / Dmin / Deq"]
        for d in (0, 5, 10, 15):
            o = self.metricsAt(s0 + d); l = self._metK(self._k(s0 + d), "lumen")
            so = f"{o['dmax']:.1f} / {o['dmin']:.1f} / {o['deq']:.1f}" if o else "—"
            sl = f"{l['dmax']:.1f} / {l['dmin']:.1f} / {l['deq']:.1f}" if l else "—"
            lines.append(f"  +{d:2d} mm   {so:22s} {sl}")
        return "\n".join(lines)

    def _dia(self, s, path=None, mode="outer"):
        if path is not None and path not in self.frames: return None
        return self._metK(self._k(s, path), mode, path)

    def _maxIn(self, s0, s1, path=None):
        best = None
        for s in np.arange(min(s0, s1), max(s0, s1) + 0.01, 2.0):
            m = self._dia(s, path)
            if m and (best is None or m["dmax"] > best[1]["dmax"]): best = (float(s), m)
        return best
