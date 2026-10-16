# -*- coding: utf-8 -*-
"""大動脈サイジング: まとめ・画像・PDF・CSV・レポート
AortaSizingLogic の一部（ReportMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class ReportMixin:

    def summary(self, tpl):
        if self.P is None: return "中心線がありません"
        out = [f"=== {tpl} まとめ（研究・教育用。最終判断は元画像で）==="]
        need = [m for m in self.markers if m.get("auto")]
        if need: out.append("※ 自動で置いた（要確認）マーカー: " + "、".join(m["name"] for m in need))
        ren, ne, sac, bif = self._mk("最下位腎動脈"), self._mk("ネック終端（瘤の始まり）"), self._mk("瘤の最大径"), self._mk("大動脈分岐")
        if tpl == "EVAR":
            if ren:
                out.append(f"[ネック] 最下位腎動脈 {self.rel(ren['s']):+.1f} mm")
                for d in (0, 10, 15):
                    m = self._dia(ren["s"] + d)
                    if m: out.append(f"  +{d:2d} mm: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                if ne:
                    cl, inn, o = self._curveLengths(ren["s"], ne["s"])
                    out.append(f"  ネック長 {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
                    a = _angle(self._tangent(ren["s"] - 20, ren["s"]), self._tangent(ren["s"], ne["s"]))
                    out.append(f"  腎上角 α {a:.0f}°")
                    if bif:
                        b = _angle(self._tangent(ren["s"], ne["s"]), self._tangent(ne["s"], bif["s"]))
                        out.append(f"  腎下角 β（ネック↔瘤の軸） {b:.0f}°")
            if ne and bif:
                mx = self._maxIn(ne["s"], bif["s"])
                if mx: out.append(f"[瘤] 最大径 Dmax {mx[1]['dmax']:.1f} mm（{self.rel(mx[0]):+.1f} mm、外周）")
            if sac:
                m = self._dia(sac["s"])
                if m: out.append(f"[瘤] マーカー位置の径 Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
            if ren and bif:
                cl, inn, o = self._curveLengths(ren["s"], bif["s"])
                out.append(f"[長さ] 最下位腎動脈 → 分岐 {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
            for side, pth in (("右", "大動脈→右腸骨"), ("左", "大動脈→左腸骨")):
                iia, cfa = self._mk(f"{side}内腸骨起始"), self._mk(f"{side}遠位（総大腿）")
                if pth not in self.frames:
                    if iia or cfa: out.append(f"[{side}] 経路がまだ作られていません（3D で{side}の線をクリック）")
                    continue
                if ren and iia:
                    cl, inn, o = self._curveLengths(ren["s"], iia["s"], pth)
                    out.append(f"[{side}] 最下位腎動脈 → 内腸骨起始 {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
                if bif and iia:
                    m = self._dia(iia["s"] - 5, pth)
                    if m: out.append(f"[{side}] 総腸骨（内腸骨の 5 mm 手前）: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                    cl, _, _ = self._curveLengths(bif["s"], iia["s"], pth); out.append(f"[{side}] 総腸骨の長さ {cl:.1f} mm")
                if iia and cfa:
                    best = None
                    for s in np.arange(iia["s"] + 5, cfa["s"], 2.0):
                        m = self._dia(s, pth, "lumen")
                        if m and (best is None or m["dmin"] < best[1]["dmin"]): best = (s, m)
                    if best:
                        o = self._dia(best[0], pth)
                        out.append(f"[{side}] アクセス（外腸骨）最小内腔径 Dmin {best[1]['dmin']:.1f}（Deq {best[1]['deq']:.1f}）mm　{self.rel(best[0]):+.0f} mm"
                                   + (f"　外周 Dmin {o['dmin']:.1f}" if o else ""))
                if cfa:
                    m = self._dia(cfa["s"], pth)
                    if m: out.append(f"[{side}] 遠位（総大腿）: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                    if ren:
                        cl, _, _ = self._curveLengths(ren["s"], cfa["s"], pth); out.append(f"[{side}] 最下位腎動脈 → 遠位 {cl:.1f} mm")
        elif tpl == "TEVAR":
            bca, lcca, lsca = self._mk("腕頭動脈"), self._mk("左総頸動脈"), self._mk("左鎖骨下動脈")
            pz, ent, dz, cel = self._mk("近位ランディング"), self._mk("瘤 / エントリー"), self._mk("遠位ランディング"), self._mk("腹腔動脈")
            for nm, m in (("腕頭動脈", bca), ("左総頸動脈", lcca), ("左鎖骨下動脈", lsca), ("腹腔動脈", cel)):
                if m: out.append(f"[分枝] {nm} {self.rel(m['s']):+.1f} mm" + (f"　{m['clock']}" if m.get("clock") else ""))
            if pz:
                zone = "?"
                if bca and pz["s"] < bca["s"]: zone = "0"
                elif lcca and pz["s"] < lcca["s"]: zone = "1"
                elif lsca and pz["s"] < lsca["s"]: zone = "2"
                elif lsca and pz["s"] < lsca["s"] + 20: zone = "3"
                elif lsca: zone = "4"
                out.append(f"[近位ランディング] {self.rel(pz['s']):+.1f} mm　Zone {zone}")
                for d in (0, 10, 20):
                    m = self._dia(pz["s"] + d)
                    if m: out.append(f"  +{d:2d} mm: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                if lsca and pz["s"] >= lsca["s"]:
                    cl, inn, o = self._curveLengths(lsca["s"], pz["s"]); out.append(f"  左鎖骨下動脈 → 近位ランディング {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
            if dz:
                out.append(f"[遠位ランディング] {self.rel(dz['s']):+.1f} mm")
                for d in (0, -10, -20):
                    m = self._dia(dz["s"] + d)
                    if m: out.append(f"  {d:+3d} mm: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                if cel: cl, _, _ = self._curveLengths(dz["s"], cel["s"]); out.append(f"  遠位ランディング → 腹腔動脈 {cl:.1f} mm")
            if pz and dz:
                cl, inn, o = self._curveLengths(pz["s"], dz["s"])
                out.append(f"[長さ] 近位 → 遠位ランディング: 中心線 {cl:.1f} mm　内弯 {inn:.1f} mm　外弯 {o:.1f} mm")
            pl_ = getattr(self, "plan", None); lg = self.planLengths() if pl_ else None
            if lg:
                out.append(f"[計画のグラフト] {self.rel(pl_['p']):+.1f} → {self.rel(pl_['d']):+.1f} mm　治療長 中心線 {lg['cl']:.1f} mm　内弯 {lg['inner']:.1f} mm　外弯 {lg['outer']:.1f} mm")
                try:
                    (Dp, mp, _), (Dd, md, _) = self.planDiams()
                    if Dp and Dd: out.append(f"  径: 近位 {mp:.1f} → {Dp:.0f} mm・遠位 {md:.1f} → {Dd:.0f} mm（オーバーサイズ {pl_['os'] * 100:.0f}%）")
                except Exception: pass
                try: si = self.sineIdx()
                except Exception: si = None
                if si:
                    a = si["tl"]; out.append(f"[遠位端の SINE の目安] 真腔 短径 {a['short']:.1f}・長径 {a['long']:.1f}・周径 {a['per']:.0f} mm・面積 {a['area']:.0f} mm²")
                    p_ = si["pre"]; out.append(f"  オーバーサイズ（グラフト ÷ 真腔 − 1）: 平均径 {p_['mean']:.2f}・周径 {p_['per']:.2f}・面積 {p_['area']:.2f}")
                    if "emr" in si: e = si["emr"]; out.append(f"  ミスマッチ（予測の広がり ÷ 2 cm 先の真腔）: 平均径 {e['mean']:.2f}・周径 {e['per']:.2f}・面積 {e['area']:.2f}")
                    out.append("  参考値は単施設の報告の群平均で、判定の基準ではありません")
                mx = self._maxIn(pz["s"], dz["s"])
                if mx: out.append(f"[瘤] 区間内の最大径 Dmax {mx[1]['dmax']:.1f} mm（{self.rel(mx[0]):+.1f} mm）")
                a = _angle(self._tangent(pz["s"] - 10, pz["s"] + 10), self._tangent(dz["s"] - 10, dz["s"] + 10))
                out.append(f"[屈曲] 近位↔遠位の向きの差 {a:.0f}°")
            if ent:
                m = self._dia(ent["s"]); out.append(f"[エントリー] {self.rel(ent['s']):+.1f} mm" + (f"　Dmax {m['dmax']:.1f} mm" if m else "") + (f"　{ent['clock']}" if ent.get("clock") else ""))
        out.append(""); out.append("[全マーカー]")
        for m in self.markers:
            mm = self.metricsAt(m["s"], m["path"])
            out.append(f"  {m['name']:16s} {self.rel(m['s']):+7.1f} mm" + (f"  Dmax {mm['dmax']:.1f} / Dmin {mm['dmin']:.1f} / Deq {mm['deq']:.1f}" if mm else "") + (f"  {m['clock']}" if m.get("clock") else ""))
        return "\n".join(out)

    # ---------------------------------------------------------------- 出力（高画質 PNG / サイジングシート PDF）
    def _wl(self):
        d = self.vol.GetDisplayNode(); return float(d.GetWindow()), float(d.GetLevel())

    @staticmethod
    def _qimageGray(a8):
        """uint8 の 2 次元配列 → QImage（ARGB32、描き込める形）"""
        from vtk.util.numpy_support import numpy_to_vtk
        h, w = a8.shape
        img = vtk.vtkImageData(); img.SetDimensions(w, h, 1); img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(a8[::-1]).ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        wr = vtk.vtkPNGWriter(); wr.SetInputData(img); wr.WriteToMemoryOn(); wr.Write()
        from vtk.util.numpy_support import vtk_to_numpy
        q = qt.QImage(); q.loadFromData(qt.QByteArray(vtk_to_numpy(wr.GetResult()).tobytes()), "PNG")
        return q.convertToFormat(qt.QImage.Format_ARGB32)

    @staticmethod
    def _font(px, bold=False):
        f = qt.QFont("Yu Gothic UI"); f.setPixelSize(int(px)); f.setBold(bold); return f

    def _pill(self, p, x, y, text, col, px=26, anchor="lt"):
        p.setFont(self._font(px, True)); fm = qt.QFontMetrics(p.font())
        w = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text); h = fm.height()
        if "r" in anchor: x -= w + 16
        if "b" in anchor: y -= h + 8
        p.setPen(qt.QPen(qt.QColor(0, 0, 0, 0))); p.setBrush(qt.QBrush(qt.QColor(10, 12, 16, 200))); p.drawRoundedRect(qt.QRectF(x, y, w + 16, h + 8), 8, 8)
        p.setPen(qt.QPen(qt.QColor(*[int(255 * c) for c in col]))); p.drawText(qt.QPointF(x + 8, y + 4 + fm.ascent()), text)

    def renderSection(self, s=None, path=None, size=1400, title=""):
        """断面の高画質画像（元 CT を 3 次補間で切り直し、輪郭と径を描き込む）"""
        from scipy import ndimage
        path = path or self.path; F = self.frames[path]; s = self.curS if s is None else float(s)
        k = self._k(s, path); P, T = F["P"][k], F["T"][k]
        if path == self.path: X, Y = self._inplane(k)
        else: X, Y = F["B"][k], F["N"][k]
        mO = self._metK(k, "outer", path); mL = self._metK(k, "lumen", path)
        dm = max([m["dmax"] for m in (mO, mL) if m] + [20.0]); fov = float(np.clip(dm * 2.0, 36.0, 100.0))
        u = (np.arange(size) + 0.5) / size * fov - fov / 2
        UU, VV = np.meshgrid(u, -u)
        Q = P + UU[..., None] * X + VV[..., None] * Y
        A = np.linalg.inv(self._ijk2ras()); H = Q.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
        if getattr(self, "arrF", None) is None: self.arrF = ndimage.spline_filter(slicer.util.arrayFromVolume(self.vol).astype(np.float32), order=3, mode="nearest")
        img = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=3, prefilter=False, mode="nearest").reshape(size, size)
        win, lev = self._wl(); a8 = np.clip((img - (lev - win / 2)) / max(win, 1) * 255, 0, 255).astype(np.uint8)
        q = self._qimageGray(a8); p = qt.QPainter(q); p.setRenderHint(qt.QPainter.Antialiasing, True); p.setRenderHint(qt.QPainter.TextAntialiasing, True)
        Fk = self.frames[path]; Bk, Nk = Fk["B"][k], Fk["N"][k]
        def px(xy):                                                        # 断面の 2D 座標 (B, N) → 画像のピクセル
            Wd = P + np.outer(xy[:, 0], Bk) + np.outer(xy[:, 1], Nk) - P
            return np.c_[(Wd @ X + fov / 2) / fov * size, (fov / 2 - Wd @ Y) / fov * size]
        def poly(xy, col, w, closed=True):
            pts = px(xy); pg = qt.QPolygonF()
            for x, y in pts: pg.append(qt.QPointF(float(x), float(y)))
            if closed and len(pts): pg.append(qt.QPointF(float(pts[0, 0]), float(pts[0, 1])))
            pen = qt.QPen(qt.QColor(*[int(255 * c) for c in col])); pen.setWidthF(w); pen.setCapStyle(qt.Qt.RoundCap); pen.setJoinStyle(qt.Qt.RoundJoin)
            p.setPen(pen); p.setBrush(qt.QBrush()); p.drawPolyline(pg)
            return pts
        sc = size / 1400.0
        if mO: poly(mO["xy"], self.OUTER_COL, 3.2 * sc)
        if mL: poly(mL["xy"], self.LUMEN_COL, 2.6 * sc)
        m = mO if self.mode == "outer" else mL
        if m:
            for key, val, col in (("maxLine", "dmax", (1.0, 0.35, 0.3)), ("minLine", "dmin", (0.35, 0.65, 1.0))):
                a, b = m[key]; pts = poly(np.array([a, b]), col, 3.0 * sc, closed=False)
                self._pill(p, pts[1, 0] + 8, pts[1, 1] - 20 * sc, f"{m[val]:.1f}", col, 30 * sc)
        # 目盛り（10 mm）
        L10 = 10.0 / fov * size; x0, y0 = 40 * sc, size - 50 * sc
        pen = qt.QPen(qt.QColor(255, 255, 255)); pen.setWidthF(4 * sc); p.setPen(pen)
        p.drawLine(qt.QPointF(x0, y0), qt.QPointF(x0 + L10, y0))
        for xx in (x0, x0 + L10): p.drawLine(qt.QPointF(xx, y0 - 10 * sc), qt.QPointF(xx, y0 + 10 * sc))
        p.setFont(self._font(24 * sc, True)); p.drawText(qt.QPointF(x0, y0 - 18 * sc), "10 mm")
        # 見出しと値
        pos = f"{self.rel(s):+.1f} mm" + (" from baseline" if self.baseS is not None else "")
        self._pill(p, 24 * sc, 24 * sc, (title + "   " if title else "") + pos, (1, 1, 1), 32 * sc)
        y = 90 * sc
        for mm, nm, col in ((mO, "外周", self.OUTER_COL), (mL, "内腔", self.LUMEN_COL)):
            if mm: self._pill(p, 24 * sc, y, f"{nm}  Dmax {mm['dmax']:.1f}  Dmin {mm['dmin']:.1f}  Deq {mm['deq']:.1f} mm  ({mm['area']:.0f} mm²)", col, 26 * sc); y += 52 * sc
        p.end()
        return q, dict(outer=mO, lumen=mL, s=s, path=path)

    def renderStretched(self, pxmm=4.0):
        """ストレッチ像（今の回転角）を高画質で。マーカー・ベースライン・現在位置を描き込む"""
        from scipy import ndimage
        sn = slicer.app.layoutManager().sliceWidget("Green").mrmlSliceNode()
        M = slicer.util.arrayFromVTKMatrix(sn.GetSliceToRAS())
        a = slicer.util.arrayFromVolume(self.straight).astype(np.float32)
        R2I = vtk.vtkMatrix4x4(); self.straight.GetRASToIJKMatrix(R2I); R2I = slicer.util.arrayFromVTKMatrix(R2I)
        # 画面の Green と同じ平面。横 ±HALF、縦は経路全体
        ends = [np.linalg.inv(M) @ np.r_[r, 1] for r in (self._greenRAS(0.0)[0], self._greenRAS(0.0)[1], self._greenRAS(self.length)[0], self._greenRAS(self.length)[1])]
        xs = [e[0] for e in ends]; ys = [e[1] for e in ends]
        x0, x1 = min(xs) - 2, max(xs) + 2; y0, y1 = min(ys) - 4, max(ys) + 4
        nx, ny = int((x1 - x0) * pxmm), int((y1 - y0) * pxmm)
        xx = x0 + (np.arange(nx) + 0.5) / pxmm; yy = y1 - (np.arange(ny) + 0.5) / pxmm
        XX, YY = np.meshgrid(xx, yy)
        R = (M[:3, :3] @ np.stack([XX.ravel(), YY.ravel(), np.zeros(XX.size)])).T + M[:3, 3]
        I = R @ R2I[:3, :3].T + R2I[:3, 3]
        img = ndimage.map_coordinates(a, [I[:, 2], I[:, 1], I[:, 0]], order=1, mode="constant", cval=-1000).reshape(ny, nx)
        win, lev = self._wl(); a8 = np.clip((img - (lev - win / 2)) / max(win, 1) * 255, 0, 255).astype(np.uint8)
        src = self._qimageGray(a8); G = 330                                   # 右側にラベル用の余白
        q = qt.QImage(nx + G, ny + 60, qt.QImage.Format_ARGB32); q.fill(qt.QColor(20, 22, 26))
        p = qt.QPainter(q); p.setRenderHint(qt.QPainter.Antialiasing, True); p.setRenderHint(qt.QPainter.TextAntialiasing, True)
        p.drawImage(qt.QPointF(0, 60), src)
        p.setFont(self._font(24, True)); p.setPen(qt.QPen(qt.QColor(235, 238, 242)))
        p.drawText(qt.QPointF(10, 38), f"ストレッチ像  {PATH_EN.get(self.path, '')}  rot {self.rot:.0f}°")
        Minv = np.linalg.inv(M)
        def pix(r):
            v = Minv @ np.r_[r, 1]; return qt.QPointF((v[0] - x0) * pxmm, (y1 - v[1]) * pxmm + 60)
        def hline(sv, col, w, dash=False):
            ab = self._greenRAS(sv); a, b = pix(ab[0]), pix(ab[1]); y = (a.y() + b.y()) / 2
            pen = qt.QPen(qt.QColor(*[int(255 * c) for c in col])); pen.setWidthF(w)
            if dash: pen.setStyle(qt.Qt.DashLine)
            p.setPen(pen); p.drawLine(qt.QPointF(0, y), qt.QPointF(nx + 14, y)); return y
        items = []
        if self.baseS is not None: items.append((hline(self.baseS, (0.4, 1.0, 0.45), 2.5), "ベースライン 0", (0.4, 1.0, 0.45)))
        for mk in self.markers:
            if not self._onPath(mk): continue
            o = self._dia(mk["s"]); txt = f"{mk['name']}  {self.rel(mk['s']):+.0f} mm" + (f"  Ø{o['deq']:.1f}" if o else "")
            items.append((hline(mk["s"], (0.3, 0.9, 0.95), 2.0, dash=True), txt, (0.3, 0.9, 0.95)))
        items.sort(key=lambda t: t[0]); last = -1e9
        for y, txt, col in items:                                            # ラベルが重ならないよう少しずらす
            ly = max(y - 16, last + 36); last = ly
            pen = qt.QPen(qt.QColor(*[int(255 * c) for c in col])); pen.setWidthF(1.5); p.setPen(pen)
            p.drawLine(qt.QPointF(nx + 14, y), qt.QPointF(nx + 26, ly + 16))
            self._pill(p, nx + 28, ly, txt, col, 20)
        L50 = 50 * pxmm; yb = ny + 40
        pen = qt.QPen(qt.QColor(255, 255, 255)); pen.setWidthF(3); p.setPen(pen)
        p.drawLine(qt.QPointF(nx + 30, yb), qt.QPointF(nx + 30, yb - L50)); p.setFont(self._font(18, True)); p.drawText(qt.QPointF(nx + 40, yb - L50 / 2), "50 mm")
        p.end()
        return q

    def render3D(self, scale=1):
        v3 = slicer.app.layoutManager().threeDWidget(0).threeDView(); rw = v3.renderWindow()
        v3.forceRender()
        f = vtk.vtkWindowToImageFilter(); f.SetInput(rw); f.SetScale(scale, scale); f.ReadFrontBufferOff(); f.ShouldRerenderOn(); f.Update()
        wr = vtk.vtkPNGWriter(); wr.SetInputConnection(f.GetOutputPort()); wr.WriteToMemoryOn(); wr.Write()
        from vtk.util.numpy_support import vtk_to_numpy
        q = qt.QImage(); q.loadFromData(qt.QByteArray(vtk_to_numpy(wr.GetResult()).tobytes()), "PNG")
        v3.forceRender(); return q

    def outDir(self):
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例")
        d = os.path.join(base, "サイジング_" + time.strftime("%Y%m%d_%H%M%S")); os.makedirs(d, exist_ok=True)
        return d

    def exportImages(self, d=None, status=print):
        """高画質 PNG: 3D・ストレッチ像・各マーカーの断面（＋今の断面）"""
        d = d or self.outDir(); files = []
        keep = (self.curS, self.path)
        status("3D を書き出し中…"); q = self.render3D(); fn = os.path.join(d, "01_3D.png"); q.save(fn); files.append(("3D", fn))
        status("ストレッチ像を書き出し中…"); q = self.renderStretched(); fn = os.path.join(d, "02_stretched.png"); q.save(fn); files.append(("ストレッチ像", fn))
        q, _ = self.renderSection(title="現在位置"); fn = os.path.join(d, "03_current_section.png"); q.save(fn); files.append(("現在の断面", fn))
        for i, mk in enumerate(self.markers):
            if mk["path"] not in self.frames: continue
            status(f"断面を書き出し中… {mk['name']}")
            q, _ = self.renderSection(mk["s"], mk["path"] if mk["path"] in self.frames else None, title=mk["name"])
            safe = "".join(ch for ch in mk["name"] if ch not in '\\/:*?"<>|（）() ')
            fn = os.path.join(d, f"{10 + i:02d}_section_{safe}.png"); q.save(fn); files.append((mk["name"], fn))
        self.exported = files
        return d, files

    def _markerRows(self):
        rows = []
        for m in self.markers:
            o = self._dia(m["s"], m["path"]) if m["path"] in self.frames else None
            l = self._dia(m["s"], m["path"], "lumen") if m["path"] in self.frames else None
            rows.append(dict(m=m, o=o, l=l, side={"大動脈→右腸骨": "右", "大動脈→左腸骨": "左"}.get(m["path"], "")
                             if m["s"] > getattr(self, "sharedLen", 0) + 2 else "共通"))
        return rows

    def writeCSV(self, d):
        import csv
        with open(os.path.join(d, "markers.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["マーカー", "経路", "位置 mm", "外周 Dmax", "外周 Dmin", "外周 Deq", "外周 面積", "内腔 Dmax", "内腔 Dmin", "内腔 Deq", "内腔 面積", "クロック", "自動"])
            for r in self._markerRows():
                m = r["m"]; f2 = lambda q, k: f"{q[k]:.1f}" if q else ""
                w.writerow([m["name"], r["side"], f"{self.rel(m['s']):.1f}"] + [f2(r["o"], k) for k in ("dmax", "dmin", "deq", "area")]
                           + [f2(r["l"], k) for k in ("dmax", "dmin", "deq", "area")] + [m.get("clock") or "", "要確認" if m.get("auto") else ""])
        with open(os.path.join(d, "measurements.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["名前", "種類", "値", "場所", "位置"])
            for r in self.measureRows(): w.writerow([r["name"], r["kind"], r["value"], r["where"], r["pos"]])
        with open(os.path.join(d, "profile.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["距離 mm", "ベースラインから mm", "面積", "Deq", "Dmax", "Dmin"])
            if self.prof is not None:
                for k in range(0, len(self.s), 4): w.writerow([f"{self.s[k]:.1f}", f"{self.rel(self.s[k]):.1f}"] + [f"{x:.1f}" for x in self.prof[k]])

    def sizingSheet(self, tpl, status=print):
        """サイジングシート（A4 の PDF）: まとめ・マーカー表・手動計測・画像。CSV と PNG も同じフォルダへ"""
        import html as _h
        d, files = self.exportImages(None, status)
        status("サイジングシート（PDF）を作成中…")
        summ = self.summary(tpl); self.writeCSV(d)
        if tpl == "TEVAR":
            try: self.saveSineCSV(d)
            except Exception as e: print("sine csv:", e)
        open(os.path.join(d, "summary.txt"), "w", encoding="utf-8").write(summ)
        doc = qt.QTextDocument(); doc.setDefaultFont(self._font(11))
        for i, (nm, fn) in enumerate(files): doc.addResource(qt.QTextDocument.ImageResource, qt.QUrl(f"img{i}.png"), qt.QImage(fn))
        E = _h.escape
        css = ("<style>body{font-family:'Yu Gothic UI','Meiryo';color:#1d2026} h1{font-size:22px;margin:0} .mut{color:#6b7280;font-size:10px}"
               "h2{font-size:13px;color:#0f5c8c;margin:10px 0 4px 0;border-bottom:1px solid #cfd6de}"
               "td,th{padding:3px 6px;font-size:11px} th{background:#eef2f6;color:#334155;text-align:left} .num{text-align:right}</style>")
        H = [f"<html><head><meta charset='utf-8'>{css}</head><body>"]
        H.append(f"<table width='100%'><tr><td><h1>大動脈サイジングシート　{E(tpl)}</h1>"
                 f"<span class='mut'>{E(self.vol.GetName() if self.vol else '')}　作成 {time.strftime('%Y-%m-%d %H:%M')}　HUCViewS AortaSizing</span></td>"
                 f"<td align='right' class='mut'>研究・教育用（非医療機器）<br>最終判断は元画像で</td></tr></table>")
        H.append("<h2>まとめ</h2><table width='100%' cellspacing='0'>")
        for line in summ.splitlines()[1:]:
            if line.startswith("[全マーカー]"): break
            if not line.strip(): continue
            b = line.startswith("[") or line.startswith("※")
            H.append(f"<tr><td>{'<b>' if b else ''}{E(line.strip())}{'</b>' if b else ''}</td></tr>")
        H.append("</table>")
        H.append("<h2>マーカー（外周 / 内腔）</h2><table width='100%' cellspacing='0' border='0'><tr><th>マーカー</th><th>側</th><th class='num'>位置 mm</th>"
                 "<th class='num'>外周 Dmax</th><th class='num'>Dmin</th><th class='num'>Deq</th><th class='num'>内腔 Dmax</th><th class='num'>Dmin</th><th class='num'>Deq</th><th>クロック</th></tr>")
        for i, r in enumerate(self._markerRows()):
            m = r["m"]; f2 = lambda q, k: f"{q[k]:.1f}" if q else "—"; bg = "#ffffff" if i % 2 == 0 else "#f7f9fb"
            H.append(f"<tr style='background:{bg}'><td>{E(m['name'])}{' <span class=mut>(自動・要確認)</span>' if m.get('auto') else ''}</td><td>{r['side']}</td>"
                     f"<td class='num'>{self.rel(m['s']):+.1f}</td>" + "".join(f"<td class='num'>{f2(r['o'], k)}</td>" for k in ("dmax", "dmin", "deq"))
                     + "".join(f"<td class='num'>{f2(r['l'], k)}</td>" for k in ("dmax", "dmin", "deq")) + f"<td>{E(m.get('clock') or '')}</td></tr>")
        H.append("</table>")
        mr = self.measureRows()
        if mr:
            H.append("<h2>手動計測</h2><table width='100%' cellspacing='0'><tr><th>名前</th><th>種類</th><th>値</th><th>場所</th><th>位置</th></tr>")
            for r in mr: H.append(f"<tr><td>{E(r['name'])}</td><td>{E(r['kind'])}</td><td><b>{E(r['value'])}</b></td><td>{E(r['where'])}</td><td>{E(r['pos'])}</td></tr>")
            H.append("</table>")
        def sz(i, w=None, h=None):
            im = qt.QImage(files[i][1]); iw, ih = max(im.width(), 1), max(im.height(), 1)
            if w is None: w = h * iw / ih
            if h is None: h = w * ih / iw
            return f"width='{int(w)}' height='{int(h)}'"
        H.append("<h2 style='page-break-before:always'>画像</h2><table cellspacing='6'><tr>"
                 f"<td valign='top'><img src='img0.png' {sz(0, w=300)}></td><td valign='top'><img src='img1.png' {sz(1, h=560)}></td>"
                 f"<td valign='top'><img src='img2.png' {sz(2, w=210)}></td></tr></table>")
        secs = list(enumerate(files))[3:]
        if secs:
            H.append("<h2>マーカー位置の断面</h2><table cellspacing='6'>")
            for j in range(0, len(secs), 3):
                H.append("<tr>" + "".join(f"<td><img src='img{i}.png' width='215' height='215'></td>" for i, _ in secs[j:j + 3]) + "</tr>")
            H.append("</table>")
        H.append("</body></html>")
        doc.setHtml("".join(H))
        pdf = os.path.join(d, "sizing_sheet.pdf")
        w = qt.QPdfWriter(pdf); w.setPageSize(qt.QPageSize(qt.QPageSize.A4)); w.setResolution(200)
        try: w.setPageMargins(qt.QMarginsF(10, 10, 10, 10), qt.QPageLayout.Millimeter)
        except Exception: pass
        w.setTitle("Aortic sizing sheet"); w.setCreator("HUCViewS AortaSizing")
        getattr(doc, "print")(w)
        self.lastOut = d
        return pdf

    def saveReport(self, tpl):
        import csv
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例")
        d = os.path.join(base, "サイジング_" + time.strftime("%Y%m%d_%H%M")); os.makedirs(d, exist_ok=True)
        txt = self.summary(tpl)
        with open(os.path.join(d, "summary.txt"), "w", encoding="utf-8") as f: f.write(txt)
        with open(os.path.join(d, "markers.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["マーカー", "経路", "ベースラインからの距離 mm", "Dmax", "Dmin", "Deq", "面積 mm2", "クロック", "自動"])
            for m in self.markers:
                mm = self.metricsAt(m["s"], m["path"]) or {}
                w.writerow([m["name"], m["path"], f"{self.rel(m['s']):.1f}"] + [f"{mm[k]:.1f}" if k in mm else "" for k in ("dmax", "dmin", "deq", "area")] + [m.get("clock") or "", "要確認" if m.get("auto") else ""])
        with open(os.path.join(d, "profile.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["距離 mm", "ベースラインから mm", "面積", "Deq", "Dmax", "Dmin"])
            if self.prof is not None:
                for k in range(0, len(self.s), 4):
                    w.writerow([f"{self.s[k]:.1f}", f"{self.rel(self.s[k]):.1f}"] + [f"{x:.1f}" for x in self.prof[k]])
        slicer.util.mainWindow().grab().save(os.path.join(d, "screen.png"))
        shots = []
        for m in self.markers:
            if not self._onPath(m): continue
            self.setPosition(m["s"]); slicer.app.processEvents()
            fn = f"marker_{len(shots) + 1}_{MARK_EN.get(m['name'], 'mk')}.png".replace(" ", "_").replace("/", "")
            slicer.app.layoutManager().sliceWidget("Red").sliceView().grab().save(os.path.join(d, fn)); shots.append((m["name"], fn))
        html = ["<html><head><meta charset='utf-8'><title>Sizing report</title></head><body style='font-family:sans-serif'>",
                f"<h2>大動脈サイジング（{tpl}）</h2><p style='color:#888'>研究・教育用。最終判断は元画像で。{time.strftime('%Y-%m-%d %H:%M')}</p>",
                "<pre>" + txt.replace("<", "&lt;") + "</pre>", "<img src='screen.png' width='900'>"]
        for name, fn in shots: html.append(f"<h4>{name}</h4><img src='{fn}' width='400'>")
        html.append("</body></html>")
        with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as f: f.write("\n".join(html))
        return d
