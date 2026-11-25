# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 面づくり（マスク → なめらかな面）・向き・表示の設定
CardiacViewLogic の一部（SurfaceMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class SurfaceMixin:
    def _cleanBinary(self, binary, spacing, minVox=60):
        """CT 寝台（薄く広い板）と微小な粒を除く"""
        try:
            from scipy import ndimage
        except Exception:
            return binary
        lab, n = ndimage.label(binary)
        if n == 0: return binary
        sizes = ndimage.sum(binary, lab, range(1, n + 1))
        objs = ndimage.find_objects(lab)
        dims = np.array(binary.shape, float)
        keep = np.zeros(n + 1, bool)
        for i, sl in enumerate(objs, start=1):
            sz = sizes[i - 1]
            if sz < minVox: continue
            ext = np.array([s_.stop - s_.start for s_ in sl], float)
            big = (ext / dims) > 0.7
            thin = (ext * spacing) < 30.0
            if big.sum() >= 2 and thin.sum() >= 1 and sz > 3000: continue   # 寝台
            keep[i] = True
        return keep[lab].astype(np.uint8)

    def _surfaceFromBinary(self, binary, vol, name, color, smooth, keepSmall=False, step=1):
        """step=2: 格子を 1/2 にして面を作る（半透明の軟部組織など細かさのいらない層。三角形が 1/4 で 4 倍速い）"""
        from vtk.util.numpy_support import numpy_to_vtk
        full = binary
        if step > 1: binary = np.ascontiguousarray(binary[::step, ::step, ::step])
        img = vtk.vtkImageData(); bb = _bbox3(binary, 10)                   # マスクの範囲 + 10 だけで面を作る（同じ番号の格子のまま。点と三角形は前と 1 ビットも同じ・ずっと速く軽い）
        if bb is None: img.SetDimensions(binary.shape[2], binary.shape[1], binary.shape[0]); sub = binary
        else:
            sub = binary[bb]; z0, y0, x0 = (b.start for b in bb)
            img.SetExtent(x0, x0 + sub.shape[2] - 1, y0, y0 + sub.shape[1] - 1, z0, z0 + sub.shape[0] - 1)
        img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(sub.ravel()), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        src = img
        if smooth >= 1:
            cast = vtk.vtkImageCast(); cast.SetInputData(img); cast.SetOutputScalarTypeToFloat(); cast.Update()
            gs = vtk.vtkImageGaussianSmooth(); gs.SetInputConnection(cast.GetOutputPort())
            sd = 0.8 if smooth == 1 else 1.3
            if step > 1: sd = max(0.6, sd / step)                       # mm で同じぼかし
            gs.SetStandardDeviations(sd, sd, sd); gs.SetRadiusFactors(2, 2, 2); gs.Update(); src = gs.GetOutput()
        mc = vtk.vtkFlyingEdges3D(); mc.SetInputData(src); mc.SetValue(0, 0.5)
        mc.ComputeNormalsOff(); mc.ComputeScalarsOff(); mc.ComputeGradientsOff(); mc.Update()
        pd = mc.GetOutput()
        def sinc(p, it, pb):
            ws = vtk.vtkWindowedSincPolyDataFilter(); ws.SetInputData(p); ws.SetNumberOfIterations(it)
            ws.SetPassBand(pb); ws.BoundarySmoothingOff(); ws.FeatureEdgeSmoothingOff(); ws.NonManifoldSmoothingOn(); ws.NormalizeCoordinatesOn(); ws.Update()
            return ws.GetOutput()
        if smooth >= 1 and pd.GetNumberOfPoints() > 0:          # 先になめらかにしてから間引く（間引きの角が出ない）
            pd = sinc(pd, 60 if smooth == 1 else 80, 0.01)          # 段々（等高線のような縞）が消えるまで。形は縮まない
        if pd.GetNumberOfPolys() > MAX_TRIS:
            dec = vtk.vtkQuadricDecimation(); dec.SetInputData(pd); dec.SetTargetReduction(1.0 - MAX_TRIS / pd.GetNumberOfPolys()); dec.Update(); pd = dec.GetOutput()
            if smooth >= 1: pd = sinc(pd, 10, 0.08)
        m = vtk.vtkMatrix4x4(); vol.GetIJKToRASMatrix(m)
        if step > 1:
            for r in range(3):
                for c in range(3): m.SetElement(r, c, m.GetElement(r, c) * step)
        tr = vtk.vtkTransform(); tr.SetMatrix(m)
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputData(pd); tp.SetTransform(tr); tp.Update()
        # 法線の向きを部品ごとに決める: AutoOrient は閉じた内側の面（心内膜）を外向きにしてしまい逆になる。
        # 各部品で「法線の裏側が組織（binary=1）、表側が組織外」になっているかを実際のマスクで確かめ、逆なら反転する。
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(tp.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOff(); nm.Update()
        result = nm.GetOutput()
        try:                                                   # 浮いた小さなかけら（ノイズ）を消す（石灰化・人工物は小さくても残す）
            if keepSmall: raise StopIteration
            cf = vtk.vtkPolyDataConnectivityFilter(); cf.SetInputData(result); cf.SetExtractionModeToAllRegions(); cf.Update()
            sizes = [cf.GetRegionSizes().GetValue(i) for i in range(cf.GetNumberOfExtractedRegions())]
            if len(sizes) > 1:
                thr = max(120, 0.01 * max(sizes))
                keepIds = [i for i, n in enumerate(sizes) if n >= thr]
                if len(keepIds) < len(sizes):
                    cf2 = vtk.vtkPolyDataConnectivityFilter(); cf2.SetInputData(result); cf2.SetExtractionModeToSpecifiedRegions()
                    for i in keepIds: cf2.AddSpecifiedRegion(i)
                    cf2.Update(); cl = vtk.vtkCleanPolyData(); cl.SetInputData(cf2.GetOutput()); cl.Update()
                    result = cl.GetOutput()
                    print(f"{name}: 小さなかけら {len(sizes) - len(keepIds)} 個を除去")
        except StopIteration: pass
        except Exception as e:
            print("debris:", e)
        try:
            result = self._orientByMask(result, full, vol)
        except Exception as e:
            print("orient:", e)
        old = slicer.mrmlScene.GetFirstNodeByName(f"CV {name}")
        if old: slicer.mrmlScene.RemoveNode(old)
        model = slicer.modules.models.logic().AddModel(result)
        model.SetName(f"CV {name}")
        self._styleDisplay(model.GetDisplayNode(), color)
        self._put(model)
        return model

    def _orientByMask(self, pd, binary, vol, dmm=1.0):
        """頂点ごとに法線を「組織の外向き」にそろえる（ぼかしたマスクを法線の前後で比べる）。
        閉じた内側の面（心内膜）や非多様体のつなぎ目で向きが逆になるのを防ぐ。"""
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk, numpy_to_vtkIdTypeArray
        from scipy import ndimage
        out = vtk.vtkPolyData(); out.DeepCopy(pd)
        if out.GetNumberOfPoints() == 0: return pd
        if out.GetPointData().GetNormals() is None:
            nf = vtk.vtkPolyDataNormals(); nf.SetInputData(out); nf.SplittingOff(); nf.ConsistencyOn(); nf.AutoOrientNormalsOff(); nf.Update(); out.DeepCopy(nf.GetOutput())
        P = vtk_to_numpy(out.GetPoints().GetData()).astype(float)
        N = vtk_to_numpy(out.GetPointData().GetNormals()).astype(np.float32).copy()
        M = vtk.vtkMatrix4x4(); vol.GetRASToIJKMatrix(M); A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        bb = _bbox3(binary, 8)                                 # ぼかし（半径 3）はマスクの範囲 + 8 の中だけで（外は 0。結果は同じ）
        off = np.zeros(3) if bb is None else np.array([b.start for b in bb], float)
        sm = ndimage.gaussian_filter((binary if bb is None else binary[bb]).astype(np.float32), 0.8)
        def samp(Q):
            H = (np.c_[Q, np.ones(len(Q))] @ A.T)[:, :3]      # i, j, k
            return ndimage.map_coordinates(sm, [H[:, 2] - off[0], H[:, 1] - off[1], H[:, 0] - off[2]], order=1, mode="constant", cval=0.0)
        score = samp(P - N * dmm) - samp(P + N * dmm)          # 正しい向きなら > 0
        flipV = score < -0.02
        N[flipV] *= -1
        na = numpy_to_vtk(N, deep=True); na.SetName("Normals"); out.GetPointData().SetNormals(na)
        polys = out.GetPolys()
        conn = vtk_to_numpy(polys.GetConnectivityArray()).copy(); offs = vtk_to_numpy(polys.GetOffsetsArray())
        if len(offs) > 1 and np.all(np.diff(offs) == 3):
            tri = conn.reshape(-1, 3)
            # 三角形の巻き順も、頂点法線の平均と合うように直す（裏面色のため）
            g = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
            nmean = N[tri[:, 0]] + N[tri[:, 1]] + N[tri[:, 2]]
            fc = np.sum(g * nmean, axis=1) < 0
            tri[fc] = tri[fc][:, [0, 2, 1]]
            ca = vtk.vtkCellArray(); ca.SetData(numpy_to_vtkIdTypeArray(offs.astype(np.int64), deep=True), numpy_to_vtkIdTypeArray(tri.ravel().astype(np.int64), deep=True))
            out.SetPolys(ca)
        print(f"法線: {int(flipV.sum())}/{len(P)} 頂点を外向きに修正")
        return out

    def _styleDisplay(self, d, color, opacity=1.0):
        d.SetScalarVisibility(False); d.SetColor(*color); d.SetOpacity(opacity)
        d.SetVisibility2D(True); d.SetSliceIntersectionThickness(2)
        d.SetBackfaceCulling(False); d.SetAmbient(0.12); d.SetDiffuse(0.82); d.SetSpecular(0.4); d.SetPower(35)
        try: d.SetBackfaceColorHSVOffset(0.0, -0.05, -0.22)   # 内側は同じ色のやや暗いトーン
        except Exception: pass
        try: d.SetInterpolation(d.PhongInterpolation)
        except Exception: pass

    def _updateBounds(self):
        B = [n.GetPolyData().GetBounds() for n in self.layerModels.values() if n and n.GetPolyData() and n.GetPolyData().GetNumberOfPoints()]
        if not B:
            self.bounds = None; return
        A = np.array(B); self.bounds = (A[:, 0::2].min(0), A[:, 1::2].max(0))

    def _namesFor(self, name):
        if name == "人工物・石灰化": return ["人工物", "石灰化", "胸骨ワイヤー"]
        if name == "血液・血管":
            return [k for k in self.layerModels if k == name or k.startswith("血管")]
        return [name]
