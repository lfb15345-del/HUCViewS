# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 心筋・壁（外膜・内膜）・心筋の断面のふた・四腔
CardiacViewLogic の一部（WallMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *
from . import common          # 色合いで置き換わる名前は common.名前 で今の値を読む


class WallMixin:
    def updateMyoCap(self):
        """心筋の切り口だけを正しく塗る（内腔の穴は空けたまま）。vtkCutter + vtkContourTriangulator"""
        my = self.layerModels.get("心筋")
        capNode = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
        if getattr(self, "on4D", False) or getattr(self, "vrOn", False):   # 4D・VR の表示中は切り口の塗りを出さない（VR の上にかぶる）
            if capNode is not None and capNode.GetDisplayNode() is not None: capNode.GetDisplayNode().SetVisibility(False)
            return
        show = (my is not None and self.visible.get("心筋", False) and self.cutAxis is not None and self.cutPlane is not None)
        # 切っている間は心筋の「外形」は隠す（心臓壁の内膜と重なってチラつき、内腔がべた塗りに見えるため）。
        # 心筋は切り口（実質）だけを塗る。切らないときは外形を半透明で出す。
        if my is not None and my.GetDisplayNode():
            my.GetDisplayNode().SetVisibility(bool(self.visible.get("心筋", False)) and self.cutAxis is None)
        if not show:
            if capNode and capNode.GetDisplayNode(): capNode.GetDisplayNode().SetVisibility(False)
            return
        o = [0, 0, 0]; n = [0, 0, 0]; self.cutPlane.GetCenter(o); self.cutPlane.GetNormal(n)
        n = np.array(n, float); n /= np.linalg.norm(n)
        plane = vtk.vtkPlane(); plane.SetOrigin(*o); plane.SetNormal(*n)
        cut = vtk.vtkCutter(); cut.SetInputData(my.GetPolyData()); cut.SetCutFunction(plane)
        strip = vtk.vtkStripper(); strip.SetInputConnection(cut.GetOutputPort()); strip.JoinContiguousSegmentsOn()
        tri = vtk.vtkContourTriangulator(); tri.SetInputConnection(strip.GetOutputPort()); tri.Update()
        pd = vtk.vtkPolyData(); pd.DeepCopy(tri.GetOutput())
        # カメラ側に 0.2mm ずらして、壁の面とのちらつきを防ぐ
        sign = 1.0 if self.cutSign > 0 else -1.0
        tf = vtk.vtkTransform(); tf.Translate(*(n * 0.8 * sign))   # 切り口の三角形のはみ出し(~1mm)より手前に
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputData(pd); tp.SetTransform(tf); tp.Update()
        out = tp.GetOutput()
        from vtk.util.numpy_support import numpy_to_vtk
        vpn = np.array(self._camera().GetCamera().GetViewPlaneNormal(), float)
        # 三角形の巻き順と法線をそろえてカメラ向きにする（バラバラだと SSAO/両面ライティングで黒ずむ）
        from vtk.util.numpy_support import vtk_to_numpy
        P = vtk_to_numpy(out.GetPoints().GetData()).astype(float) if out.GetNumberOfPoints() else np.zeros((0, 3))
        if out.GetNumberOfPolys():
            conn = vtk_to_numpy(out.GetPolys().GetConnectivityArray()).reshape(-1, 3).copy()
            gn = np.cross(P[conn[:, 1]] - P[conn[:, 0]], P[conn[:, 2]] - P[conn[:, 0]])
            bad = (gn @ vpn) < 0
            conn[bad] = conn[bad][:, [0, 2, 1]]
            ca = vtk.vtkCellArray()
            from vtk.util.numpy_support import numpy_to_vtkIdTypeArray
            off = numpy_to_vtkIdTypeArray(np.arange(0, 3 * len(conn) + 1, 3, dtype=np.int64), deep=True)
            cn = numpy_to_vtkIdTypeArray(conn.ravel().astype(np.int64), deep=True)
            ca.SetData(off, cn); out.SetPolys(ca)
        nrm = np.tile(vpn, (out.GetNumberOfPoints(), 1)).astype(np.float32)
        na = numpy_to_vtk(nrm, deep=True); na.SetName("Normals"); out.GetPointData().SetNormals(na)
        if capNode is None:
            capNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "CV 心筋断面")
            capNode.CreateDefaultDisplayNodes(); self._put(capNode)
        capNode.SetAndObservePolyData(out)
        d = capNode.GetDisplayNode()
        d.SetScalarVisibility(False); d.SetColor(*common.MYO_CUT_COLOR); d.SetBackfaceCulling(False)
        d.SetAmbient(0.85); d.SetDiffuse(0.20); d.SetSpecular(0.0)   # 切り口はフラットな面として均一に
        d.SetOpacity(getattr(self, "capOpacity", 1.0)); d.SetVisibility(True); d.SetVisibility2D(False)

    def setCapOpacity(self, op):
        """心筋の濃さ: 切り口の塗りと、心筋そのものの不透明度を一緒に変える"""
        self.capOpacity = float(op)
        m = self.layerModels.get("心臓壁")
        if m and m.GetDisplayNode(): m.GetDisplayNode().SetClippingCapOpacity(self.capOpacity)
        my = self.layerModels.get("心筋")
        if my and my.GetDisplayNode():
            my.GetDisplayNode().SetOpacity(max(0.15, self.capOpacity))
        self.updateMyoCap()

    def _maskPointsRAS(self, mask, maxPts=20000):
        idx = np.argwhere(mask)
        if len(idx) == 0: return None
        if len(idx) > maxPts: idx = idx[np.random.default_rng(0).choice(len(idx), maxPts, replace=False)]
        M = vtk.vtkMatrix4x4(); self.workVolume.GetIJKToRASMatrix(M)
        A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        ijk1 = np.c_[idx[:, 2], idx[:, 1], idx[:, 0], np.ones(len(idx))]
        return (ijk1 @ A.T)[:, :3]

    def fourChamber(self):
        """左室の長軸と右室中心を含む面（四腔断面）で切り、その面を正面から見る。戻り値は切断位置(0..1)"""
        hc = self._findChambers()
        if hc is None or self.workVolume is None: return None
        lv = self._maskPointsRAS(self._segmentMaskArray(hc, self.workVolume, ("left ventricle",)))
        la = self._maskPointsRAS(self._segmentMaskArray(hc, self.workVolume, ("left atrium",)))
        rv = self._maskPointsRAS(self._segmentMaskArray(hc, self.workVolume, ("right ventricle",)))
        if lv is None or la is None or rv is None: return None
        lac = la.mean(0); lvc = lv.mean(0); rvc = rv.mean(0)
        apex = lv[np.argmax(np.linalg.norm(lv - lac, axis=1))]
        axis = apex - lac; axis /= np.linalg.norm(axis)
        n = np.cross(axis, rvc - lvc); n /= np.linalg.norm(n)
        if n[1] < 0: n = -n                       # カメラは前（anterior）側
        center = (lvc + rvc + lac) / 3.0
        vb = self._visibleBounds()                 # 見えている心臓の大きさで距離を決める（体幹全体の CT でも心臓が小さくならない）
        r = float(np.linalg.norm(vb[1] - vb[0]) / 2) if vb is not None else self._sceneRadius()
        cn = self._camera()
        cn.SetFocalPoint(*center); cn.SetPosition(*(center + n * r * 2.2)); cn.SetViewUp(*(-axis))
        try: self._fitParallel()                                               # 画面の縦横比に合わせて心臓全体を収める
        except Exception as e: print('fit:', e)
        cn.GetCamera().SetViewAngle(30); cn.ResetClippingRange()
        lo, hi = self._visibleBounds()
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        proj = corners @ n; dmin, dmax = proj.min(), proj.max()
        frac = float(np.clip((dmax - center @ n) / max(dmax - dmin, 1e-6), 0, 1))
        self.cutSign = 1.0                                                   # 「反転」を押した後でも、四腔断面はカメラの側を切る（反転のままだと奥を切って、切り口が見えない）
        self.setCut("VIEW", frac)
        self._view().forceRender()
        return frac

    def rebuildWall(self):
        """心臓壁を作り直す。心腔ラベルがあれば、内腔（右心系の造影不良な血液も含む）を壁から除外する"""
        segNode = self._findSegmentation(); hc = self._findChambers()
        if segNode is None or self.workVolume is None: return False
        from scipy import ndimage
        work = self.workVolume; arr = slicer.util.arrayFromVolume(work); sp = float(min(work.GetSpacing()))
        # 壁を作る範囲: 心臓の外形は高解像度の心腔ラベル（心腔＋心筋）、大血管は全身ラベル。
        # 全身ラベルの「心臓」は 3mm 格子でカクカクなので、心腔ラベルがあればそちらを使う。範囲は本当の距離で 4mm 外まで（なめらか）
        hcAll = self._segmentMaskArray(hc, work, ("ventricle", "atrium", "myocardium", "aorta", "pulmonary artery")) if hc is not None else None
        hvv = self._segmentMaskArray(segNode, work, ("atrial appendage", "aorta", "pulmonary vein", "vena cava", "brachiocephalic trunk", "pulmonary artery"))
        hv0 = hcAll if hcAll is not None else self._segmentMaskArray(segNode, work, ("heart",))
        hv = hv0 if hvv is None else (hvv if hv0 is None else (hv0 | hvv))
        if hv is None: return False
        hv = ndimage.gaussian_filter(hv.astype(np.float32), 1.2 / sp) > 0.5
        region = ndimage.distance_transform_edt(~hv, sampling=work.GetSpacing()[::-1]) <= (4.0 if hcAll is not None else 2.4)
        c = self._cal()
        wall = (arr >= c["wall_lo"]) & (arr <= c["wall_hi"]) & region
        cav = None
        if hc is not None:
            cav = self._segmentMaskArray(hc, work, ("left ventricle", "left atrium", "right ventricle", "right atrium", "aorta", "pulmonary artery"))
            if cav is not None: wall &= ~cav
        # 薄い壁（左房・右房・大血管 1〜2mm）は部分容積で CT 値帯から外れ、穴になる。
        #   血液側: 造影血液と平均されて >175HU、脂肪側: 脂肪と平均されて <-20HU。
        # → 内腔ラベルの外側に必ず 2 ボクセル（約2.4mm）の殻を足して、壁を閉じる。
        lumen = hvv                                                            # 上で取った全身ラベルの大血管と同じもの（同じ書き出しを 2 回しない。hvv は書き換えていない）
        lumen = np.zeros_like(wall) if lumen is None else lumen.astype(bool)   # "heart"（心臓全体）は内腔ではないので入れない
        if cav is not None: lumen |= cav
        # AI の全身ラベルは 3mm 格子で作られていてカクカク → ラベル由来の内腔は強めに（約1.8mm）ならす
        lumen = ndimage.gaussian_filter(lumen.astype(np.float32), 1.8 / sp) > 0.5
        # ラベルの切れ目（大動脈基部・バルサルバ洞、LVOT など）も内腔として扱う: 心臓まわりで造影された血液
        bl = (arr >= c["blood_lo"]) & (arr <= 3000) & region
        bl = ndimage.gaussian_filter(bl.astype(np.float32), 0.8 / sp) > 0.5
        nLab = int(lumen.sum()); lumen |= bl
        print(f"内腔: ラベル {nLab} + 造影血液（ラベル外）{int(lumen.sum()) - nLab} ボクセル")
        if cav is not None: wall &= ~lumen
        nIt = max(1, int(round(2.4 / sp)))
        shell = ndimage.binary_dilation(lumen, iterations=nIt) & ~lumen
        print(f"壁: CT値帯 {int(wall.sum())} + 内腔の殻 {int((shell & ~wall).sum())} ボクセル")
        self._wallEvidence = wall.copy()            # CT 値で裏付けのある壁
        self._wallSynth = shell & ~wall             # 補った壁
        self._wallFor = self._wallKey(work)          # どの CT の配列か（colorWallEpiEndo が、別の症例の配列を大きさが同じというだけで使わないように）
        if getattr(self, "wallFill", True):
            wall |= shell
        wall = self._cleanBinary(wall.astype(np.uint8), sp, minVox=200)
        old = self.layerModels.get("心臓壁")
        vis = self.visible.get("心臓壁", True)
        if old: slicer.mrmlScene.RemoveNode(old)
        m = self._surfaceFromBinary(wall, work, "心臓壁", common.EPI_COLOR, 1)
        self.layerModels["心臓壁"] = m; self.visible["心臓壁"] = vis
        m.GetDisplayNode().SetVisibility(self._layerShown("心臓壁"))         # VR・4D の途中に作り直した時は、面を VR の上に出さない（前は出た）
        self.colorWallEpiEndo()
        return True

    def buildMyocardium(self):
        """心腔モデルの myocardium から、中隔を含む心筋のモデルを作る"""
        hcNode = self._findChambers()
        if hcNode is None or self.workVolume is None: return False
        mask = self._segmentMaskArray(hcNode, self.workVolume, ("myocardium",))
        if mask is None or mask.sum() < 100: return False
        # 右室の自由壁を足す: 右室内腔のまわり ~5mm の殻で、筋肉の CT 値（-20〜175HU）のところ
        try:
            from scipy import ndimage
            arr = slicer.util.arrayFromVolume(self.workVolume)
            sp = float(min(self.workVolume.GetSpacing()))
            rv = self._segmentMaskArray(hcNode, self.workVolume, ("right ventricle",))
            leftc = self._segmentMaskArray(hcNode, self.workVolume, ("left ventricle", "left atrium", "aorta", "right atrium", "pulmonary artery"))
            if rv is not None:
                it = max(2, int(round(3.5 / sp)))   # 右室自由壁は薄い（3〜4mm）
                shell = ndimage.binary_dilation(rv, iterations=it) & ~rv
                c = self._cal(); rvwall = shell & (arr >= c["wall_lo"]) & (arr <= c["wall_hi"])
                if leftc is not None: rvwall &= ~leftc
                lab, n = ndimage.label(rvwall)
                if n:
                    sizes = ndimage.sum(rvwall, lab, range(1, n + 1))
                    keep = np.zeros(n + 1, bool); keep[1:] = sizes >= 150
                    rvwall = keep[lab]
                mask = mask | rvwall
                print(f"右室自由壁を追加: {int(rvwall.sum())} ボクセル")
        except Exception as e:
            print("rv wall:", e)
        m = self._surfaceFromBinary(mask.astype(np.uint8), self.workVolume, "心筋", common.MYO_COLOR, 1)
        self.layerModels["心筋"] = m; self.visible["心筋"] = False; m.GetDisplayNode().SetVisibility(False)
        return True

    def _findChambers(self):
        src = getattr(self, "sourceVolume", None)
        if src is not None:
            n = self._segFor(src, "heartchambers")
            if n is not None: return n
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):          # 元の CT から見つからない時も、シーンの心腔ラベルを使う
            sg = n.GetSegmentation()
            if any("left ventricle" in sg.GetNthSegment(i).GetName().lower() for i in range(sg.GetNumberOfSegments())):
                return n
        return None

    def colorWallEpiEndo(self):
        """心臓壁の各頂点を 外膜 / 左心系の内膜 / 右心系の内膜 に塗り分ける（法線方向の CT 値と心腔ラベルで判定）"""
        m = self.layerModels.get("心臓壁")
        if m is None or self.workVolume is None: return
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
        vol = self.workVolume; arr = slicer.util.arrayFromVolume(vol)
        c = self._cal(); blood = (arr >= c["blood_lo"]) & (arr <= c["blood_hi"])
        hcNode = self._findChambers()
        left = right = None
        if hcNode is not None:
            left = self._segmentMaskArray(hcNode, vol, ("left atrium", "left ventricle", "aorta"))
            right = self._segmentMaskArray(hcNode, vol, ("right atrium", "right ventricle", "pulmonary artery"))
        pd = m.GetPolyData()
        if pd.GetPointData().GetNormals() is None:
            nf = vtk.vtkPolyDataNormals(); nf.SetInputData(pd); nf.SplittingOff(); nf.AutoOrientNormalsOn(); nf.Update(); pd.DeepCopy(nf.GetOutput())
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        N = vtk_to_numpy(pd.GetPointData().GetNormals()).astype(float)
        M = vtk.vtkMatrix4x4(); vol.GetRASToIJKMatrix(M)
        A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        nz, ny, nx = arr.shape
        endo = np.zeros(len(P)); lh = np.zeros(len(P)); rh = np.zeros(len(P))
        steps = (1.0, 2.0, 3.5)
        for dmm in steps:
            H = np.c_[P + N * dmm, np.ones(len(P))] @ A.T
            ijk = np.rint(H[:, :3]).astype(int)
            i, j, k = ijk[:, 0], ijk[:, 1], ijk[:, 2]
            ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny) & (k >= 0) & (k < nz)
            def look(mask):
                h = np.zeros(len(P), bool); h[ok] = mask[k[ok], j[ok], i[ok]]; return h
            b = look(blood)
            if left is not None or right is not None:                         # 片側の心腔ラベルが無い（先天性・術後など）時は、無い側を空として扱う（前は右が無いと落ちて、壁の色分けも心筋も作られなかった）
                l = look(left) if left is not None else np.zeros(len(P), bool)
                r = look(right) if right is not None else np.zeros(len(P), bool)
                lh += l; rh += r; b = b | l | r
            endo += b
        isEndo = endo / len(steps) >= 0.34
        cls = np.zeros(len(P), np.int8)                    # 0 = 外膜, 1 = 左心系, 2 = 右心系
        cls[isEndo] = 1
        if left is not None or right is not None: cls[isEndo & (rh > lh)] = 2
        # まだら（外膜に内膜色の点が散る）を防ぐ: メッシュの近所で多数決
        try:
            from scipy import sparse
            from vtk.util.numpy_support import vtk_to_numpy as _v2n
            tri0 = _v2n(pd.GetPolys().GetConnectivityArray()).reshape(-1, 3)
            e0 = np.r_[tri0[:, [0, 1]], tri0[:, [1, 2]], tri0[:, [2, 0]]]
            W0 = sparse.coo_matrix((np.ones(len(e0) * 2, np.float32), (np.r_[e0[:, 0], e0[:, 1]], np.r_[e0[:, 1], e0[:, 0]])), shape=(len(P), len(P))).tocsr()
            W0 = W0 + sparse.identity(len(P), dtype=np.float32, format="csr"); deg0 = np.asarray(W0.sum(1)).ravel()
            F = np.stack([(cls == q).astype(np.float32) for q in range(3)], 1)
            for _ in range(5): F = (W0 @ F) / deg0[:, None]
            cls = np.argmax(F, axis=1).astype(np.int8)
        except Exception as ex:
            print("class smooth:", ex)
        val = np.zeros(len(P), np.float32)                 # 0 = 外膜
        val[cls == 1] = 1/3                                 # 1/3 = 左心系（または判定不能の内膜）
        val[cls == 2] = 2/3                                 # 2/3 = 右心系
        # 補った壁（CT 値の裏付けなし）: 面の内側（組織側）を覗いて、補完マスクにしかない所
        syn = getattr(self, "_wallSynth", None); ev = getattr(self, "_wallEvidence", None); isSyn = None
        fill = getattr(self, "wallFill", True)
        if fill and syn is not None and ev is not None and syn.shape == arr.shape and getattr(self, "_wallFor", None) == self._wallKey(vol):
            sh = np.zeros(len(P)); eh = np.zeros(len(P))
            for dmm in (0.6, 1.2, 1.8):
                H = np.c_[P - N * dmm, np.ones(len(P))] @ A.T
                ijk = np.rint(H[:, :3]).astype(int); i, j, k = ijk[:, 0], ijk[:, 1], ijk[:, 2]
                ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny) & (k >= 0) & (k < nz)
                a1 = np.zeros(len(P), bool); a1[ok] = syn[k[ok], j[ok], i[ok]]; sh += a1
                a2 = np.zeros(len(P), bool); a2[ok] = ev[k[ok], j[ok], i[ok]]; eh += a2
            raw = ((sh >= 2) & (eh == 0)).astype(np.float32)
            # まだらにならないよう、メッシュ上で近所の多数決（数回の平均化）で領域としてまとめる
            try:
                from scipy import sparse
                from vtk.util.numpy_support import vtk_to_numpy as _v2n
                tri = _v2n(pd.GetPolys().GetConnectivityArray()).reshape(-1, 3)
                e = np.r_[tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]
                W = sparse.coo_matrix((np.ones(len(e) * 2, np.float32), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(len(P), len(P))).tocsr()
                W = W + sparse.identity(len(P), dtype=np.float32, format="csr")
                deg = np.asarray(W.sum(1)).ravel()
                f = raw
                for _ in range(4): f = (W @ f) / deg
                isSyn = f >= 0.5
            except Exception as ex:
                print("syn smooth:", ex); isSyn = raw > 0.5
            if getattr(self, "showSynth", True): val[isSyn] = 1.0   # 1.0 = 補った壁（グレー）。隠すときは内外の色のまま
            print(f"補った壁の頂点: {isSyn.mean()*100:.1f}%")
        elif fill:                                              # 補った所の元の配列が無い（保存した症例を開いた後）: 面に残した印を使う
            ks = pd.GetPointData().GetArray("WallSynth"); kc = pd.GetPointData().GetArray("WallClass")   # （前は、開き直した後に「補った壁を見せる」を切り替えると、グレーの印が消えて戻らなかった）
            if ks is not None and ks.GetNumberOfTuples() == len(P): isSyn = vtk_to_numpy(ks) > 0
            elif kc is not None and kc.GetNumberOfTuples() == len(P): isSyn = vtk_to_numpy(kc) > 0.9      # 前の版で保存した症例（グレーを見せて保存した時だけ分かる）
            if isSyn is not None and getattr(self, "showSynth", True): val[isSyn] = 1.0
        if isSyn is not None:                                   # 印そのものも面に持たせる（面と一緒に保存される）
            sa = numpy_to_vtk(np.asarray(isSyn).astype(np.uint8), deep=True); sa.SetName("WallSynth"); pd.GetPointData().AddArray(sa)
        va = numpy_to_vtk(val, deep=True); va.SetName("WallClass")
        pd.GetPointData().AddArray(va)
        old = slicer.mrmlScene.GetFirstNodeByName("CV EpiEndo")
        if old: slicer.mrmlScene.RemoveNode(old)
        ct = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode", "CV EpiEndo")
        ct.SetTypeToUser(); ct.SetNumberOfColors(256); ct.SetNamesInitialised(True)
        for t in range(256):
            x = t / 255.0
            c = common.EPI_COLOR if x < 1/6 else (common.ENDO_COLOR if x < 0.5 else (common.ENDO_R_COLOR if x < 5/6 else (SYNTH_COLOR if getattr(self, "showSynth", True) else common.EPI_COLOR)))
            ct.SetColor(t, f"c{t}", c[0], c[1], c[2], 1.0)
        d = m.GetDisplayNode()
        d.SetActiveScalarName("WallClass"); d.SetAndObserveColorNodeID(ct.GetID())
        d.SetScalarRangeFlag(d.UseManualScalarRange); d.SetScalarRange(0.0, 1.0); d.SetScalarVisibility(True)
        m.Modified()
        return hcNode is not None

    @staticmethod
    def _wallKey(vol):
        """壁の配列（_wallSynth など）がどの CT のものかのしるし"""
        try: return (vol.GetID(), vol.GetName(), tuple(round(float(x), 3) for x in vol.GetOrigin()), tuple(vol.GetImageData().GetDimensions()))
        except Exception: return None
