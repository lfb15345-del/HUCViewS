# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: パッチ（3D の面の上で塗って色分け）・シートにする
CardiacViewLogic の一部（PatchMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class PatchMixin:
    # ---------------------------------------------------------------- パッチ（3D の面の上で塗って色分け）
    PATCH_KEY = "パッチ"
    PATCH_OFFSET = 0.35                                                       # 面から浮かせる距離 mm（重なってちらつかないように）

    def _paintTargets(self):
        """塗れる面: 見えているレイヤー（パッチ自身は除く）"""
        out = {}
        for k, n in self.layerModels.items():
            if k == self.PATCH_KEY or n is None: continue
            d = n.GetDisplayNode(); pd = n.GetPolyData()
            if d is None or not d.GetVisibility() or pd is None or pd.GetNumberOfPoints() == 0 or pd.GetNumberOfPolys() == 0: continue
            out[k] = n
        return out

    def _pcache(self, k, n):
        """面ごとの探し物用データ（点の KD 木・三角形の探索・頂点番号・法線）。面が作り直されたら作り直す"""
        from scipy.spatial import cKDTree
        from vtk.util.numpy_support import vtk_to_numpy
        c = self.__dict__.setdefault("_pc", {})
        pd = n.GetPolyData(); key = (n.GetID(), pd.GetNumberOfPoints(), pd.GetNumberOfPolys(), pd.GetPoints().GetMTime())
        e = c.get(k)
        if e is not None and e["key"] == key: return e
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(np.float64)
        polys = pd.GetPolys()
        try:
            off = vtk_to_numpy(polys.GetOffsetsArray()); con = vtk_to_numpy(polys.GetConnectivityArray())
            ok = len(off) > 1 and bool(np.all(np.diff(off) == 3))
        except Exception: ok = False
        if not ok:
            tf = vtk.vtkTriangleFilter(); tf.SetInputData(pd); tf.PassVertsOff(); tf.PassLinesOff(); tf.Update(); polys = tf.GetOutput().GetPolys()
            con = vtk_to_numpy(polys.GetConnectivityArray())
        T = con.reshape(-1, 3).astype(np.int64)
        ds = vtk.vtkPolyData(); ds.SetPoints(pd.GetPoints()); ds.SetPolys(polys)
        loc = vtk.vtkStaticCellLocator(); loc.SetDataSet(ds); loc.BuildLocator()
        nr = pd.GetPointData().GetNormals()
        if nr is None or nr.GetNumberOfTuples() != len(P):
            nm = vtk.vtkPolyDataNormals(); nm.SetInputData(ds); nm.SplittingOff(); nm.ComputePointNormalsOn(); nm.Update(); nr = nm.GetOutput().GetPointData().GetNormals()
        N = vtk_to_numpy(nr).astype(np.float64) if nr is not None and nr.GetNumberOfTuples() == len(P) else None
        e = dict(key=key, P=P, tree=cKDTree(P), loc=loc, ds=ds, T=T, N=N); c[k] = e
        return e

    def _paintPick(self, x, y):
        """画面の (x, y) の下にある、塗れる面の一番手前の点 → (面の名前, 点) / None。切って取り除いた側は通り抜ける"""
        ren = self._view().renderWindow().GetRenderers().GetFirstRenderer()
        def w(z):
            ren.SetDisplayPoint(float(x), float(y), z); ren.DisplayToWorld(); q = ren.GetWorldPoint()
            return np.array(q[:3], float) / (q[3] if abs(q[3]) > 1e-12 else 1.0)
        p0, p1 = w(0.0), w(1.0)
        planes = [(np.array(c, float), np.array(nn, float)) for c, nn in self._activePlanes()[0]]
        best = None; pts = vtk.vtkPoints(); ids = vtk.vtkIdList()
        for k, n in self._paintTargets().items():
            e = self._pcache(k, n); pts.Reset(); ids.Reset()
            e["loc"].IntersectWithLine(p0.tolist(), p1.tolist(), 1e-4, pts, ids)
            for i in range(pts.GetNumberOfPoints()):
                q = np.array(pts.GetPoint(i)); dist = float(np.linalg.norm(q - p0))
                if best is not None and dist >= best[0]: continue
                if planes and not any(float((q - c) @ nn) >= -0.05 for c, nn in planes): continue   # 切って消えている所
                best = (dist, k, q)
        return None if best is None else (best[1], best[2])

    def paintStart(self, r):
        self.paintOn = True; self.paintR = float(r); self._painting = False
        self.__dict__.setdefault("_strokes", [])
        for k, n in self._paintTargets().items(): self._pcache(k, n)          # 最初のひと塗りで待たないように先に準備
        self._patchSync()

    def paintEnd(self):
        was = getattr(self, "paintOn", False); self.paintOn = False; self._painting = False
        if was: self._patchBuild(); self._patchSave()
        a = float(getattr(self, "_patchAreaV", 0.0) or 0.0)
        return f"パッチを塗り終わりました（塗った広さ 約 {a / 100:.1f} cm²）" if a > 0 else "パッチ: 塗った所はありません"

    def _patchSync(self):
        """塗った記録（体の座標の筆の跡）と、面ごとの「塗った点」がずれていたら作り直す（面を作り直した時・開き直した時）"""
        pm = self.__dict__.setdefault("_pMask", {}); pk = self.__dict__.setdefault("_pMaskKey", {})
        for s in getattr(self, "_strokes", None) or []:
            n = self.layerModels.get(s[1])
            if n is None or n.GetPolyData() is None or n.GetPolyData().GetNumberOfPoints() == 0: continue
            e = self._pcache(s[1], n)
            if pm.get(s[1]) is None or pk.get(s[1]) != e["key"]: self._patchReplay(); return

    def _patchReplay(self):
        self._pMask = {}; self._pMaskKey = {}
        for sid, k, x, y, z, r, er in getattr(self, "_strokes", None) or []:
            n = self.layerModels.get(k)
            if n is None or n.GetPolyData() is None or n.GetPolyData().GetNumberOfPoints() == 0: continue
            self._dabMask(k, n, (x, y, z), r, er)

    def _dabMask(self, k, n, p, r, erase):
        e = self._pcache(k, n)
        pm = self.__dict__.setdefault("_pMask", {}); pk = self.__dict__.setdefault("_pMaskKey", {})
        m = pm.get(k)
        if m is None or len(m) != len(e["P"]) or pk.get(k) != e["key"]:
            m = pm[k] = np.zeros(len(e["P"]), bool); pk[k] = e["key"]
        idx = e["tree"].query_ball_point(np.asarray(p, float), float(r))
        if len(idx): m[np.asarray(idx, np.int64)] = not erase

    def _paintPress(self, it):
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place: return False      # 計測を置いている時は塗らない
        x, y = it.GetEventPosition(); hit = self._paintPick(x, y)
        if hit is None: return False
        st = self.__dict__.setdefault("_strokes", [])
        self._sid = max([s[0] for s in st], default=0) + 1
        self._painting = True; self._paintErase = bool(it.GetControlKey()); self._lastDab = None
        self._patchSync(); self._paintAt(hit)
        return True

    def _paintMove(self, it):
        x, y = it.GetEventPosition(); hit = self._paintPick(x, y)
        if hit is not None: self._paintAt(hit)

    def _paintRelease(self):
        self._painting = False; self._lastDab = None
        t = getattr(self, "_ptTimer", None)
        if t is not None: t.stop()
        self._patchBuild(); self._patchSave()

    def _paintAt(self, hit):
        k, p = hit; n = self.layerModels.get(k); p = np.asarray(p, float)
        r = float(getattr(self, "paintR", 4.0)); er = 1 if getattr(self, "_paintErase", False) else 0
        last = getattr(self, "_lastDab", None); seq = [p]
        if last is not None and last[0] == k:                                  # 速く動かしても途切れないように間を埋める
            d = float(np.linalg.norm(p - last[1]))
            if 0.5 * r < d < 60.0:
                m = int(np.ceil(d / (0.5 * r))); seq = [last[1] + (p - last[1]) * (i / m) for i in range(1, m + 1)]
        for q in seq:
            self._dabMask(k, n, q, r, er)
            self._strokes.append([self._sid, k, round(float(q[0]), 2), round(float(q[1]), 2), round(float(q[2]), 2), r, er])
        self._lastDab = (k, p)
        t = getattr(self, "_ptTimer", None)
        if t is None:
            t = self._ptTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(60); t.connect("timeout()", self._patchBuild)
        if not t.isActive(): t.start()

    def _patchBuild(self):
        """塗った点から「CV パッチ」の面を作る（塗った三角形を、面の表と裏へ少し浮かせて 2 枚）"""
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        app = vtk.vtkAppendPolyData(); cnt = 0; area = 0.0
        for k, m in list((getattr(self, "_pMask", None) or {}).items()):
            n = self.layerModels.get(k)
            if n is None or m is None or not m.any() or n.GetPolyData() is None: continue
            e = self._pcache(k, n)
            if len(m) != len(e["P"]): continue
            T = e["T"]; sel = m[T].all(axis=1)
            if not sel.any(): continue
            Ts = T[sel]; used = np.unique(Ts); remap = np.full(len(e["P"]), -1, np.int64); remap[used] = np.arange(len(used))
            Pu = e["P"][used]; Nu = e["N"][used] if e["N"] is not None else None; Tr = remap[Ts]
            area += 0.5 * float(np.linalg.norm(np.cross(Pu[Tr[:, 1]] - Pu[Tr[:, 0]], Pu[Tr[:, 2]] - Pu[Tr[:, 0]]), axis=1).sum())
            cells = np.ascontiguousarray(np.hstack([np.full((len(Tr), 1), 3, np.int64), Tr]).ravel())
            for sg in ((1.0, -1.0) if Nu is not None else (0.0,)):
                Q = np.ascontiguousarray(Pu + sg * self.PATCH_OFFSET * Nu) if Nu is not None else np.ascontiguousarray(Pu)
                pts = vtk.vtkPoints(); pts.SetData(numpy_to_vtk(Q, deep=True))
                ca = vtk.vtkCellArray(); ca.SetCells(len(Tr), numpy_to_vtkIdTypeArray(cells, deep=True))
                pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetPolys(ca); app.AddInputData(pd); cnt += 1
        self._patchAreaV = area
        node = self.layerModels.get(self.PATCH_KEY)
        if node is not None and not slicer.mrmlScene.IsNodePresent(node): node = None
        if node is None: node = slicer.mrmlScene.GetFirstNodeByName("CV パッチ")
        if cnt == 0:
            if node is not None: node.SetAndObservePolyData(vtk.vtkPolyData())
            self._view().scheduleRender(); return
        app.Update()
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(app.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOff(); nm.AutoOrientNormalsOff(); nm.Update()
        out = vtk.vtkPolyData(); out.DeepCopy(nm.GetOutput())
        if node is None:
            node = slicer.modules.models.logic().AddModel(out); node.SetName("CV パッチ")
            d = node.GetDisplayNode(); self._styleDisplay(d, PATCH_COLOR); d.SetSpecular(0.35); d.SetPower(25); d.SetAmbient(0.22)
            self._put(node)
        else:
            node.SetAndObservePolyData(out)
        self.layerModels[self.PATCH_KEY] = node; self.visible[self.PATCH_KEY] = True
        d = node.GetDisplayNode()
        if d is not None:
            if not d.GetVisibility(): d.SetVisibility(True)
            if self.cutAxis is not None and d.GetAttribute("CV.clipWant") != "1": self._applyClipToModels(True)
        self._view().scheduleRender()

    def _patchSave(self):
        """塗った記録を「CV パッチ」に持たせる（症例を保存すると一緒に残り、開き直しても続きを塗れる・戻せる）"""
        node = self.layerModels.get(self.PATCH_KEY)
        if node is not None and slicer.mrmlScene.IsNodePresent(node):
            node.SetAttribute("CV.patchStrokes", json.dumps(getattr(self, "_strokes", None) or [], ensure_ascii=False))

    def patchToSheet(self, step=2):
        """自動で出した「パッチの範囲」（閉じた塊＝袋のように見える）を、左室と右室の血液のちょうど真ん中の 1 枚の面にする。
        本物のパッチは中隔に縫い付けた 1 枚なので。開いた時に 1 回だけ（約 2 秒）。元の塊は隠したモデルに残す"""
        from scipy import ndimage
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
        node = self.layerModels.get(self.PATCH_KEY); src = getattr(self, "sourceVolume", None); hc = self._findChambers()
        pd = node.GetPolyData() if node is not None else None
        if pd is None or pd.GetNumberOfPolys() == 0 or src is None or hc is None: return False
        fe0 = vtk.vtkFeatureEdges(); fe0.SetInputData(pd); fe0.BoundaryEdgesOn(); fe0.FeatureEdgesOff(); fe0.NonManifoldEdgesOff(); fe0.ManifoldEdgesOff(); fe0.Update()
        if fe0.GetOutput().GetNumberOfCells() > 0.02 * pd.GetNumberOfPolys():
            node.SetAttribute("CV.patchSheet", "1"); return False                 # もともと 1 枚（縁がある）
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M); A = slicer.util.arrayFromVTKMatrix(M)
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        ijk = (np.linalg.inv(A) @ np.c_[P, np.ones(len(P))].T)[:3].T
        dims = np.array(src.GetImageData().GetDimensions()); sp = np.array(src.GetSpacing())
        mg = np.ceil(10.0 / sp).astype(int)
        lo = np.maximum(np.floor(ijk.min(0)).astype(int) - mg, 0); hi = np.minimum(np.ceil(ijk.max(0)).astype(int) + mg, dims - 1)
        st = np.where(sp * step <= 1.3, step, 1).astype(int)                 # 間引きは向きごと（x, y, z）。間引くと 1.3 mm より粗くなる向き（厚いスライス）は間引かない
        # （前は全部の向きを 2 つおきにしていて、厚いスライスの CT では左右の血液の真ん中の面が粗くなり、1 枚にできないことがあった。0.65 mm 以下の CT は前と同じ）
        hu = slicer.util.arrayFromVolume(src)[lo[2]:hi[2] + 1:st[2], lo[1]:hi[1] + 1:st[1], lo[0]:hi[0] + 1:st[0]].astype(np.float32)
        nz, ny, nx = hu.shape
        G = A @ np.array([[st[0], 0, 0, lo[0]], [0, st[1], 0, lo[1]], [0, 0, st[2], lo[2]], [0, 0, 0, 1.0]])
        spc = np.array([np.linalg.norm(G[:3, 2]), np.linalg.norm(G[:3, 1]), np.linalg.norm(G[:3, 0])])   # (z, y, x) mm
        def vm(X):
            m = vtk.vtkMatrix4x4()
            for r in range(4):
                for c_ in range(4): m.SetElement(r, c_, X[r, c_])
            return m
        ref = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "cv_tmpRef")
        img = vtk.vtkImageData(); img.SetDimensions(nx, ny, nz); img.AllocateScalars(vtk.VTK_SHORT, 1); ref.SetAndObserveImageData(img); ref.SetIJKToRASMatrix(vm(G))
        try:
            LV = self._segmentMaskArray(hc, ref, ("left ventricle",)); RV = self._segmentMaskArray(hc, ref, ("right ventricle",))
        finally:
            slicer.mrmlScene.RemoveNode(ref)
        if LV is None or RV is None or not LV.any() or not RV.any(): return False
        tf = vtk.vtkTransform(); tf.SetMatrix(vm(np.linalg.inv(G)))
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputData(pd); tp.SetTransform(tf); tp.Update()
        stn = vtk.vtkPolyDataToImageStencil(); stn.SetInputConnection(tp.GetOutputPort()); stn.SetOutputOrigin(0, 0, 0); stn.SetOutputSpacing(1, 1, 1)
        stn.SetOutputWholeExtent(0, nx - 1, 0, ny - 1, 0, nz - 1); stn.Update()
        one = vtk.vtkImageData(); one.SetDimensions(nx, ny, nz); one.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1); one.GetPointData().GetScalars().Fill(1)
        sti = vtk.vtkImageStencil(); sti.SetInputData(one); sti.SetStencilConnection(stn.GetOutputPort()); sti.ReverseStencilOff(); sti.SetBackgroundValue(0); sti.Update()
        blob = vtk_to_numpy(sti.GetOutput().GetPointData().GetScalars()).reshape(nz, ny, nx) > 0
        if not blob.any(): return False
        c = self._cal(); thr = 0.5 * (float(c.get("myo", 80)) + float(c.get("blood", 350)))
        blood = ndimage.median_filter(hu, 3) > thr                                  # 造影された血液を、近い方の部屋（左室・右室）に分ける
        dLl = ndimage.distance_transform_edt(~LV, sampling=spc); dRl = ndimage.distance_transform_edt(~RV, sampling=spc)
        bL = blood & (dLl < dRl) & (dLl < 6); bR = blood & (dRl <= dLl) & (dRl < 6)
        if not bL.any() or not bR.any(): return False
        f = (ndimage.distance_transform_edt(~bL, sampling=spc) - ndimage.distance_transform_edt(~bR, sampling=spc)).astype(np.float32)
        def im_(a, name):
            im = vtk.vtkImageData(); im.SetDimensions(nx, ny, nz); v = numpy_to_vtk(np.ascontiguousarray(a.ravel()), deep=True); v.SetName(name); im.GetPointData().SetScalars(v); return im
        fe = vtk.vtkFlyingEdges3D(); fe.SetInputData(im_(f, "f")); fe.SetValue(0, 0.0); fe.ComputeNormalsOff(); fe.ComputeScalarsOff(); fe.Update()   # 左右の血液のちょうど真ん中
        pr = vtk.vtkProbeFilter(); pr.SetInputConnection(fe.GetOutputPort()); pr.SetSourceData(im_(ndimage.gaussian_filter(blob.astype(np.float32), 1.0), "blob")); pr.Update()
        o = pr.GetOutput(); o.GetPointData().SetActiveScalars("blob")
        cl = vtk.vtkClipPolyData(); cl.SetInputData(o); cl.SetValue(0.5); cl.Update()                                 # 塊の中だけ
        if cl.GetOutput().GetNumberOfPolys() == 0: return False
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(cl.GetOutputPort()); sm.SetNumberOfIterations(20); sm.SetPassBand(0.05)
        sm.BoundarySmoothingOn(); sm.FeatureEdgeSmoothingOff(); sm.NonManifoldSmoothingOn(); sm.NormalizeCoordinatesOn(); sm.Update()
        tr = vtk.vtkTransform(); tr.SetMatrix(vm(G)); tp2 = vtk.vtkTransformPolyDataFilter(); tp2.SetInputConnection(sm.GetOutputPort()); tp2.SetTransform(tr); tp2.Update()
        fh = vtk.vtkFillHolesFilter(); fh.SetInputConnection(tp2.GetOutputPort()); fh.SetHoleSize(6.0)              # 小さな穴（周り 2〜40 mm 程度）はふさぐ（布は 1 枚）
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(fh.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOff(); nm.ComputePointNormalsOn(); nm.Update()
        sheet = vtk.vtkPolyData(); sheet.DeepCopy(nm.GetOutput()); sheet.GetPointData().SetScalars(None)
        keep = slicer.mrmlScene.GetFirstNodeByName("cv_patch_blob")
        if keep is None:
            keep = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "cv_patch_blob"); keep.SetHideFromEditors(True)
            cp = vtk.vtkPolyData(); cp.DeepCopy(pd); keep.SetAndObservePolyData(cp)
        node.SetAndObservePolyData(sheet); node.SetAttribute("CV.patchSheet", "1")
        d = node.GetDisplayNode()
        if d is not None: d.SetBackfaceCulling(False); d.SetFrontfaceCulling(False)
        self._view().scheduleRender()
        return True
