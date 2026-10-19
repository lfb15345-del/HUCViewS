# -*- coding: utf-8 -*-
"""大動脈サイジング: 中心線の自動作成・経路・伸ばした画像
AortaSizingLogic の一部（CoreMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class CoreMixin:
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.vol = self.seg = None
        self.curves = {}; self.paths = {}
        self.path = None; self.curS = 0.0; self.length = 0.0
        self.P = self.T = self.N = self.B = self.s = None
        self.mode = "outer"; self.rot = 0.0
        self.surf = {}; self._cutters = {}; self.cache = {}; self.override = {}
        self.markers = []; self.baseXYZ = None
        self.straight = None; self.arr = None; self.prof = None
        self.onChanged = lambda: None; self.onPath = lambda: None
        self._iTags = []; self._busyEdit = False; self._clockCb = None; self._drag = False
        self._pending = None; self._pendingRot = None; self._saved = None; self._editing = False
        self._timer = qt.QTimer(); self._timer.setSingleShot(True); self._timer.setInterval(20)
        self._timer.connect("timeout()", self._flush)
        self.contNode = self.dLines = self.posNode = self.cursorNode = self.markG = self.mark3 = None
        self.chart = None; self.extMask = None; self.thr = 180.0

    # ---------------------------------------------------------------- 入力
    def _inputs(self):
        vol = seg = None
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            vol = getattr(cv, "sourceVolume", None)
            if vol is not None: seg = cv._segFor(vol, "total")
        except Exception: pass
        if seg is None:
            best = None                                   # 腸骨動脈まで入っている全身ラベルを優先（心臓だけの症例と取り違えない）
            for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
                sg = n.GetSegmentation()
                names = [_norm(sg.GetNthSegment(i).GetName()) for i in range(sg.GetNumberOfSegments())]
                r = n.GetNodeReference("referenceImageGeometryRef")
                if "aorta" not in names or len(names) <= 20 or r is None or not r.IsA("vtkMRMLScalarVolumeNode"): continue
                score = 10 * sum(any(_match(x, k) for x in names) for k in ("iliac artery right", "iliac artery left")) + len(names) / 1000
                if best is None or score > best[0]: best = (score, n, r)
            if best is not None: seg, vol = best[1], best[2]
        if vol is None or seg is None:
            raise RuntimeError("CT と臓器ラベル（TotalSegmentator）が見つかりません。先に入口で「3D を作る」を行ってください。")
        if vol is not getattr(self, "vol", None):                          # 別の症例に変わった: 前の症例の CT（伸ばした画像の元）・断面の計算を捨てる
            self.arr = None; self.arrF = None; self.cache = {}; self._built = {}
        self.vol, self.seg = vol, seg
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic; self.thr = float(cv._cal().get("blood_lo", 180.0))
        except Exception: self.thr = 180.0
        return vol, seg

    def _mask(self, keys, exact=False):
        sg = self.seg.GetSegmentation(); out = None
        for i in range(sg.GetNumberOfSegments()):
            sid = sg.GetNthSegmentID(i); nm = _norm(sg.GetSegment(sid).GetName())
            if any(_match(nm, k, exact) for k in keys):
                a = slicer.util.arrayFromSegmentBinaryLabelmap(self.seg, sid, self.vol) > 0
                out = a if out is None else (out | a)
        return out

    def _ijk2ras(self):
        m = vtk.vtkMatrix4x4(); self.vol.GetIJKToRASMatrix(m)
        return np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])

    def _pts(self, mask):
        idx = np.argwhere(mask); A = self._ijk2ras()
        return (np.c_[idx[:, 2], idx[:, 1], idx[:, 0], np.ones(len(idx))] @ A.T)[:, :3]

    # ---------------------------------------------------------------- ① 血管と中心線
    def autoCenterline(self, status=print):
        from scipy import ndimage
        vol, seg = self._inputs()
        _ensureVMTK(status)
        status("1/4 大動脈・腸骨動脈の形を準備中…")
        aorta = self._mask(("aorta",), exact=True)
        if aorta is None or aorta.sum() < 500: raise RuntimeError("大動脈のラベルがありません")
        zz = self._pts(aorta)[:, 2]
        dims = vol.GetImageData().GetDimensions(); fov = min(dims[0] * vol.GetSpacing()[0], dims[1] * vol.GetSpacing()[1])
        if float(zz.max() - zz.min()) < 80 or fov < 220:                      # 心臓だけの撮影（FOV が小さい）では大動脈が少ししか写っていない
            raise RuntimeError(f"この CT は心臓だけの撮影です（撮影範囲 {fov:.0f} mm・大動脈 {zz.max() - zz.min():.0f} mm 分）。"
                               "大動脈サイジングは、胸部〜腹部まで撮った造影 CT で使ってください。")
        ilR = self._mask(("iliac artery right",)); ilL = self._mask(("iliac artery left",))
        status("1/4 鼠径部まで血管をたどっています…")
        ext = {}
        for name, m, fem in (("右腸骨", ilR, ("femur right",)), ("左腸骨", ilL, ("femur left",))):
            if m is None or m.sum() < 200: continue
            e = self._extendToGroin(m, self._mask(fem))
            if e is not None: ext[name] = e
        vessel = aorta.copy()
        for m in (ilR, ilL):
            if m is not None: vessel |= m
        for e in ext.values(): vessel |= e
        self.extMask = None
        for e in ext.values(): self.extMask = e if self.extMask is None else (self.extMask | e)
        # 0.6 mm 等方の表面。5mm 厚でコインを積んだようにならないよう、符号付き距離（mm 単位）で滑らかに作る
        sp = np.array(vol.GetSpacing())[::-1]                                 # (z, y, x) mm
        ISO = 1.0
        f = sp / ISO
        vessel = ndimage.binary_closing(vessel, iterations=2)                 # 延長部のつなぎ目をふさぐ
        vessel = self._bridge(vessel, np.array(vol.GetSpacing())[::-1], status)  # ラベルの途切れ（5mm 厚で多い）を橋渡し
        ix = np.argwhere(vessel); lo = np.maximum(ix.min(0) - 4, 0); hi = np.minimum(ix.max(0) + 5, vessel.shape)
        crop = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi))           # 血管の周りだけで計算（速さ）
        A0 = self._ijk2ras(); A = A0.copy()
        A[:3, 3] = (A0 @ np.r_[lo[2], lo[1], lo[0], 1.0])[:3]
        A[:3, :3] = A0[:3, :3] * (ISO / sp[::-1])
        iso = self._smoothIso(vessel[crop], sp, f)
        lab, n = ndimage.label(iso)
        if n > 1:
            sizes = ndimage.sum(iso, lab, range(1, n + 1)); iso = lab == (1 + int(np.argmax(sizes)))
        self.surf = {"outer": self._surface(iso, A)}
        status("1/4 内腔（造影部分）の表面を作成中…")
        hu = slicer.util.arrayFromVolume(vol)
        lum = vessel & (hu >= self.thr)
        lum = ndimage.binary_opening(lum, iterations=1)
        for k in range(lum.shape[0]): lum[k] = ndimage.binary_fill_holes(lum[k])
        liso = self._smoothIso(lum[crop], sp, f) & iso
        self.surf["lumen"] = self._surface(liso, A) if liso.sum() > 100 else self.surf["outer"]
        self._cutters = {}; self.cache = {}; self.override = {}
        self._models()
        import ExtractCenterline
        ecl = ExtractCenterline.ExtractCenterlineLogic()
        status("2/4 中心線を計算中（VMTK）…")
        pre = ecl.preprocess(self.surf["outer"], 15000, 4.0, False)
        apts = self._pts(aorta); ref = None
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            hc = cv._segFor(vol, "heartchambers")
            if hc is not None:
                lv = cv._segmentMaskArray(hc, vol, ("left ventricle",))
                if lv is not None and lv.sum() > 100: ref = self._pts(lv).mean(0)
        except Exception: pass
        if ref is None:
            heart = self._mask(("heart",), exact=True)
            ref = self._pts(heart).mean(0) if heart is not None and heart.sum() > 100 else apts[np.argmax(apts[:, 2])]
        d = np.linalg.norm(apts - ref, axis=1); p0 = apts[np.argmin(d)]
        root = apts[np.linalg.norm(apts - p0, axis=1) < 10].mean(0)
        ends = {}
        for name, m in (("右腸骨", ilR), ("左腸骨", ilL)):
            if m is not None and m.sum() > 200:
                mm = (m | ext[name]) if name in ext else m
                pts = self._pts(mm); zmin = pts[:, 2].min(); ends[name] = pts[pts[:, 2] < zmin + 6].mean(0)
        if not ends:
            zmin = apts[:, 2].min(); ends["大動脈"] = apts[apts[:, 2] < zmin + 6].mean(0)
        from vtk.util.numpy_support import vtk_to_numpy as _v2n
        from scipy.spatial import cKDTree as _KD
        sp_surf = _v2n(pre.GetPoints().GetData()); stree = _KD(sp_surf)
        def snap(p):
            d, i = stree.query(p); return sp_surf[i], float(d)
        root, _ = snap(root)
        good = {}
        for k, p in ends.items():
            q, d = snap(p)
            if d > 25:                                    # 表面から大きく外れた端点は信用しない（延長失敗）
                lab = ilR if "右" in k else (ilL if "左" in k else None)
                base = self._pts(lab) if lab is not None and lab.any() else apts         # 腸骨が無い時は大動脈ラベルの下端
                status(f"注意: {k} の端点が血管表面から {d:.0f} mm 離れていたため、{'腸骨' if lab is not None else '大動脈'}ラベルの下端を使います")
                near = sp_surf[_KD(base).query(sp_surf)[0] < 8.0]               # その側の腸骨ラベルに沿った表面だけ
                if len(near): q = near[np.argmin(near[:, 2])]                 # その中で一番下 = 取れている範囲の末端
                else: q, _ = snap(base[base[:, 2] < base[:, 2].min() + 6].mean(0))
            good[k] = q
        ends = good
        ep = slicer.mrmlScene.GetFirstNodeByName("SA 端点") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "SA 端点")
        ep.RemoveAllControlPoints(); ep.GetDisplayNode().SetVisibility(False)
        ep.AddControlPoint(vtk.vtkVector3d(*root))
        for k, p in ends.items(): ep.AddControlPoint(vtk.vtkVector3d(*p))
        cl, _vor = ecl.extractCenterline(pre, ep, 1.0)
        status("3/4 経路を整理中…")
        lines = self._lines(cl)
        self._dbg = dict(pre=pre, ep=ep, root=root, ends=dict(ends), lines=[(l[0], l[-1], len(l)) for l in lines])
        if not lines: raise RuntimeError("中心線を作れませんでした（ラベルが途切れている可能性）")
        paths = {}; used = []
        for k, p in ends.items():
            scored = sorted(lines, key=lambda L: min(np.linalg.norm(L[0] - p), np.linalg.norm(L[-1] - p)))
            best = None
            for cand in scored:
                dend = min(np.linalg.norm(cand[0] - p), np.linalg.norm(cand[-1] - p))
                if dend > 30: break
                if any(cand is u for u in used): continue
                best = cand; break
            if best is None:
                status(f"注意: {k} 側の中心線が端点まで届きませんでした。中心線を手で追加してください。"); continue
            used.append(best)
            if np.linalg.norm(best[0] - root) > np.linalg.norm(best[-1] - root): best = best[::-1]
            name = "大動脈→" + k if k != "大動脈" else "大動脈"
            # 同じ線が二度選ばれたら（分岐が片方しか取れていない）重複を避ける
            dup = any(len(b) == len(best) and np.allclose(b, best) for b in paths.values())
            if dup and len(paths) >= 1:
                status(f"注意: {k} 側の中心線を分離できませんでした（分岐がうまく取れていません）。3D で確認してください。")
                continue
            paths[name] = best
        for n in list(slicer.util.getNodesByClass("vtkMRMLMarkupsCurveNode")):
            if n.GetName().startswith("SA 中心線"): slicer.mrmlScene.RemoveNode(n)
        self.curves = {}; self.frames = {}; self._built = {}; self.markers = []; self.baseS = None
        for name, pts in paths.items():
            c = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode", f"SA 中心線 {name}")
            s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
            for t in np.arange(0, s[-1], 10.0).tolist() + [s[-1]]:
                q = np.array([np.interp(t, s, pts[:, i]) for i in range(3)]); c.AddControlPoint(vtk.vtkVector3d(*q))
            col = PATH_COLORS.get(name, (1.0, 0.85, 0.2))
            d = c.GetDisplayNode(); d.SetSelectedColor(*col); d.SetColor(*col); d.SetActiveColor(*col)
            d.SetGlyphScale(1.6); d.SetLineThickness(0.4); d.SetPointLabelsVisibility(False); d.SetVisibility(False)
            try: d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.55)          # 血管の中の中心線も透けて見える
            except Exception: pass
            try: d.SetPropertiesLabelVisibility(False)
            except Exception: pass
            c.SetCurveTypeToCardinalSpline(); c.SetLocked(True)
            self.curves[name] = c
        status("4/4 中心線ができました（経路 {} 本）".format(len(paths)))
        self._autoMarkers = True
        return list(paths.keys())

    def _bridge(self, mask, sp, status=print, maxGap=25.0, r=2.5):
        """離れたラベルの破片を、一番近い点どうしを細い円柱でつないで本体に合流させる"""
        from scipy import ndimage
        from scipy.spatial import cKDTree
        lab, n = ndimage.label(mask)
        if n <= 1: return mask
        sizes = ndimage.sum(mask, lab, range(1, n + 1)); main = 1 + int(np.argmax(sizes))
        out = mask.copy(); joined = 0
        def border(m):
            b = m & ~ndimage.binary_erosion(m)
            return np.argwhere(b)
        body = border(lab == main) * sp
        for c in np.argsort(-sizes):
            c = int(c) + 1
            if c == main or sizes[c - 1] < 30: continue
            pc = border(lab == c) * sp
            if len(pc) == 0: continue
            d, i = cKDTree(body).query(pc)
            j = int(np.argmin(d))
            if d[j] > maxGap: continue
            a, b = pc[j], body[i[j]]
            nstep = int(np.ceil(np.linalg.norm(b - a) / 0.3)) + 1
            ball = np.ceil(r / sp).astype(int)
            for t in np.linspace(0, 1, nstep):
                q = np.round((a + (b - a) * t) / sp).astype(int)
                lo = np.maximum(q - ball, 0); hi = np.minimum(q + ball + 1, mask.shape)
                zz, yy, xx = np.ogrid[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
                ok = ((zz - q[0]) * sp[0]) ** 2 + ((yy - q[1]) * sp[1]) ** 2 + ((xx - q[2]) * sp[2]) ** 2 <= r * r
                out[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] |= ok
            body = np.vstack([body, pc]); joined += 1
        if joined: status(f"1/4 途切れていた血管ラベル {joined} か所をつなぎました")
        return out

    def _extendToGroin(self, iliac, femur, maxLen=120.0):
        """腸骨ラベルの下端から、造影された血管を下へたどる（総大腿動脈まで）"""
        from scipy import ndimage
        arr = slicer.util.arrayFromVolume(self.vol); thr = self.thr
        A = self._ijk2ras(); sp = np.array(self.vol.GetSpacing())
        pts = self._pts(iliac); zmin = pts[:, 2].min(); end = pts[pts[:, 2] < zmin + 6].mean(0)
        zstop = zmin - maxLen
        if femur is not None and femur.sum() > 500:
            fz = self._pts(femur)[:, 2]; zstop = max(zstop, fz.max() - 70.0)
        Ainv = np.linalg.inv(A)
        def ijk(p): return (Ainv @ np.r_[p, 1])[:3]
        c = ijk(end); rad = np.array([30 / sp[0], 30 / sp[1]])
        kz = [ijk(np.r_[end[:2], z])[2] for z in (end[2] + 5, zstop)]
        k0, k1 = int(max(0, min(kz))), int(min(arr.shape[0] - 1, max(kz)))
        if k1 - k0 < 2: return None
        i0, i1 = int(max(0, c[0] - rad[0])), int(min(arr.shape[2] - 1, c[0] + rad[0]))
        j0, j1 = int(max(0, c[1] - rad[1])), int(min(arr.shape[1] - 1, c[1] + rad[1]))
        box = np.zeros(arr.shape, bool); box[k0:k1 + 1, j0:j1 + 1, i0:i1 + 1] = True
        blood = (arr >= thr) & (arr <= 1500) & box
        lab, n = ndimage.label(blood | (iliac & box))
        seeds = np.unique(lab[iliac & box]); seeds = seeds[seeds > 0]
        if len(seeds) == 0: return None
        grown = np.isin(lab, seeds) & ~iliac
        if grown.sum() < 30: return None
        return ndimage.binary_opening(grown, iterations=1) | (grown & ndimage.binary_erosion(grown))

    def _smoothIso(self, mask, sp, f):
        """5mm 厚のマスクを、mm 単位の符号付き距離で等方アップサンプルして滑らかな面にする"""
        from scipy import ndimage
        if mask.sum() < 10: return ndimage.zoom(mask.astype(np.float32), f, order=1) > 0.5
        din = ndimage.distance_transform_edt(mask, sampling=sp).astype(np.float32)
        dout = ndimage.distance_transform_edt(~mask, sampling=sp).astype(np.float32)
        sdf = dout - din                                                      # 内側が負、mm 単位
        sdf = ndimage.gaussian_filter(sdf, sigma=(2.5 / sp[0], 0.6, 0.6))     # z 方向（厚い軸）を強めにならす
        up = ndimage.zoom(sdf, f, order=1)
        return up < 0

    def _surface(self, binary, ijk2ras):
        from vtk.util.numpy_support import numpy_to_vtk
        PAD = 3                                                               # 画像の端で面が開かないよう、周りを 0 で囲む
        binary = np.pad(binary, PAD); ijk2ras = ijk2ras.copy(); ijk2ras[:3, 3] -= ijk2ras[:3, :3] @ np.array([PAD, PAD, PAD], float)
        img = vtk.vtkImageData(); img.SetDimensions(binary.shape[2], binary.shape[1], binary.shape[0])
        img.AllocateScalars(vtk.VTK_FLOAT, 1)
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(binary.astype(np.float32).ravel()), deep=True))
        gs = vtk.vtkImageGaussianSmooth(); gs.SetInputData(img); gs.SetStandardDeviations(0.6, 0.6, 0.6); gs.Update()
        mc = vtk.vtkFlyingEdges3D(); mc.SetInputConnection(gs.GetOutputPort()); mc.SetValue(0, 0.4987); mc.ComputeNormalsOff(); mc.Update()
        m = vtk.vtkMatrix4x4()
        for r in range(4):
            for c in range(4): m.SetElement(r, c, float(ijk2ras[r, c]))
        tr = vtk.vtkTransform(); tr.SetMatrix(m)
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputConnection(mc.GetOutputPort()); tp.SetTransform(tr); tp.Update()
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(tp.GetOutputPort()); sm.SetNumberOfIterations(30); sm.SetPassBand(0.05)
        sm.BoundarySmoothingOff(); sm.FeatureEdgeSmoothingOff(); sm.NonManifoldSmoothingOn(); sm.NormalizeCoordinatesOn()
        cf = vtk.vtkPolyDataConnectivityFilter(); cf.SetInputConnection(sm.GetOutputPort()); cf.SetExtractionModeToLargestRegion()
        cl = vtk.vtkCleanPolyData(); cl.SetInputConnection(cf.GetOutputPort())
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(cl.GetOutputPort()); nm.SplittingOff(); nm.AutoOrientNormalsOn(); nm.Update()
        out = vtk.vtkPolyData(); out.DeepCopy(nm.GetOutput()); out.GetPointData().SetScalars(None); return out

    def _lines(self, pd):
        from vtk.util.numpy_support import vtk_to_numpy
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        out = []; ids = vtk.vtkIdList(); lines = pd.GetLines(); lines.InitTraversal()
        while lines.GetNextCell(ids):
            idx = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]
            if len(idx) > 5: out.append(P[idx])
        return out

    def _models(self):
        """3D 用の血管モデル（外周は半透明、内腔は見せない）"""
        for n in list(slicer.util.getNodesByClass("vtkMRMLModelNode")):
            if n.GetName() == "SA 血管": slicer.mrmlScene.RemoveNode(n)
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputData(self.surf["outer"])     # 見た目用はもっとなめらかに（計測には使わない）
        sm.SetNumberOfIterations(80); sm.SetPassBand(0.005); sm.NormalizeCoordinatesOn(); sm.NonManifoldSmoothingOn()
        sm.BoundarySmoothingOff(); sm.FeatureEdgeSmoothingOff()
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(sm.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOn(); nm.Update()
        pd = vtk.vtkPolyData(); pd.DeepCopy(nm.GetOutput())
        m = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "SA 血管"); m.SetAndObservePolyData(pd)
        m.CreateDefaultDisplayNodes(); d = m.GetDisplayNode()
        d.SetColor(0.86, 0.36, 0.33); d.SetOpacity(1.0); d.SetScalarVisibility(False); d.SetVisibility2D(False); d.SetBackfaceCulling(False)
        d.SetInterpolation(1)                                                 # Gouraud（なめらかな陰影）
        d.SetAmbient(0.18); d.SetDiffuse(0.72); d.SetSpecular(0.55); d.SetPower(22); d.SetEdgeVisibility(False)
        d.RemoveAllViewNodeIDs(); d.AddViewNodeID("vtkMRMLViewNode1")
        self.vesselModel = m

    # ---------------------------------------------------------------- フレームと伸ばした画像
    def _frames(self, pts):
        from scipy import ndimage
        s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
        keep = np.r_[True, np.diff(s) > 1e-6]; pts, s = pts[keep], s[keep]
        t = np.arange(0, s[-1], STEP)
        P = np.stack([np.interp(t, s, pts[:, i]) for i in range(3)], 1)
        P = ndimage.gaussian_filter1d(P, sigma=SMOOTH_MM / STEP, axis=0, mode="nearest")
        T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
        up = np.array([0, 1.0, 0])
        if abs(T[0] @ up) > 0.9: up = np.array([0, 0, 1.0])
        n = up - (up @ T[0]) * T[0]; n /= np.linalg.norm(n)
        N = np.zeros_like(P); N[0] = n
        for i in range(len(P) - 1):                                # 回転最小フレーム
            v1 = P[i + 1] - P[i]; c1 = v1 @ v1
            if c1 < 1e-12: N[i + 1] = N[i]; continue
            rL = N[i] - (2 / c1) * (v1 @ N[i]) * v1; tL = T[i] - (2 / c1) * (v1 @ T[i]) * v1
            v2 = T[i + 1] - tL; c2 = v2 @ v2
            N[i + 1] = rL - (2 / c2) * (v2 @ rL) * v2 if c2 > 1e-12 else rL
            N[i + 1] /= np.linalg.norm(N[i + 1])
        B = np.cross(T, N)
        return dict(P=P, T=T, N=N, B=B, s=t, length=float(t[-1]) if len(t) else 0.0)

    def _use(self, name):
        F = self.frames[name]
        self.P, self.T, self.N, self.B, self.s, self.length = F["P"], F["T"], F["N"], F["B"], F["s"], F["length"]

    def _reseat(self, c):
        ts = list(np.arange(0, self.length, 10.0)) + [self.length]
        wasMod = c.StartModify(); c.RemoveAllControlPoints()
        for t in ts:
            k = min(int(round(t / STEP)), len(self.P) - 1); c.AddControlPoint(vtk.vtkVector3d(*self.P[k]))
        c.EndModify(wasMod)

    def _straighten(self, name):
        from scipy import ndimage
        if self.arr is None:
            self.arr = slicer.util.arrayFromVolume(self.vol).astype(np.float32)
            self.arrF = ndimage.spline_filter(self.arr, order=3, mode="nearest")      # 3次スプラインの前処理（1回だけ）
        out = self._straightArr(self.P, self.N, self.B)
        return self._straightNode(name, out)

    def _straightArr(self, PP, NN, BB):
        """中心線のフレーム（P, N, B）に沿って元の CT を切り出し、伸ばした画像の配列（K × nu × nu）を作る"""
        from scipy import ndimage
        A = np.linalg.inv(self._ijk2ras())
        u = np.arange(-HALF, HALF + 1e-6, STEP); nu = len(u)
        UU, VV = np.meshgrid(u, u)
        K = len(PP); out = np.zeros((K, nu, nu), np.int16)
        for k0 in range(0, K, 64):
            k1 = min(K, k0 + 64)
            P = PP[k0:k1, None, None, :]; Nn = NN[k0:k1, None, None, :]; Bb = BB[k0:k1, None, None, :]
            Q = P + UU[None, :, :, None] * Bb + VV[None, :, :, None] * Nn
            H = Q.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
            out[k0:k1] = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=3, prefilter=False, mode="nearest").reshape(k1 - k0, nu, nu).astype(np.int16)
        return out

    def _straightNode(self, name, out):
        node = slicer.mrmlScene.GetFirstNodeByName("SA stretched " + PATH_EN.get(name, name))
        if node is None: node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SA stretched " + PATH_EN.get(name, name))
        slicer.util.updateVolumeFromArray(node, out)
        node.SetSpacing(STEP, STEP, STEP); node.SetOrigin(-HALF, -HALF, 0.0)
        m = vtk.vtkMatrix4x4(); m.Identity(); m.SetElement(2, 2, -1.0); node.SetIJKToRASDirectionMatrix(m)
        node.CreateDefaultDisplayNodes(); dn = node.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        return node

    def selectPath(self, name, status=print):
        if name not in self.curves: return
        for k, c in self.curves.items(): c.GetDisplayNode().SetLineThickness(0.7 if k == name else 0.3)
        self.rebuild(name, status)
        try: self.onPath()
        except Exception: pass

    def rebuild(self, name, status=print):
        c = self.curves.get(name)
        if c is None: raise RuntimeError("中心線がありません")
        cp = slicer.util.arrayFromMarkupsCurvePoints(c, world=True).astype(float)
        self.path = name
        built = self._built.get(name)
        if built is not None and built["n"] == c.GetNumberOfControlPoints() and np.allclose(built["cp"], slicer.util.arrayFromMarkupsControlPoints(c, world=True)):
            self.frames[name] = built["frames"]; self._use(name); self.straight = built["vol"]
        else:
            status("中心線をならして、伸ばした画像を作成中…")
            self.frames[name] = self._frames(cp); self._use(name); self._reseat(c)
            self.frames[name] = self._frames(slicer.util.arrayFromMarkupsCurvePoints(c, world=True).astype(float)); self._use(name)   # 点を置き直した曲線そのものに合わせる（後の部分修正と一致させる）
            for key in [k for k in self.cache if name in k[:2]]: self.cache.pop(key)
            self.straight = self._straighten(name)
            self._built[name] = dict(n=c.GetNumberOfControlPoints(), cp=slicer.util.arrayFromMarkupsControlPoints(c, world=True), frames=self.frames[name], vol=self.straight)
        self.sharedLen = self._sharedLength()
        status("断面を計算中…")
        self._profile()
        if getattr(self, "_autoMarkers", False):
            self._autoMarkers = False; self._prefillMarkers()
        self.curS = min(self.curS, self.length)
        self.showLayout()
        self.setRotation(0.0)

    def _sharedLength(self):
        others = [k for k in self.curves if k != self.path]
        if not others: return self.length
        o = others[0]
        pts = self.frames[o]["P"] if o in self.frames else slicer.util.arrayFromMarkupsCurvePoints(self.curves[o], world=True)
        from scipy.spatial import cKDTree
        d, _ = cKDTree(pts).query(self.P[::4])
        far = np.where(d > 4.0)[0]
        return float(self.s[far[0] * 4]) if len(far) else self.length
