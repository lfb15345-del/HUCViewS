# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: パッチを自動で探す（VSD）・外す・やり直し・面の向き
CardiacViewLogic の一部（AutoPatchMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class AutoPatchMixin:
    # ---------------------------------------------------------------- パッチを自動で探す（VSD）
    # 術後 CT で「左室と右室の血液の間が 2 mm 以下」の薄い仕切りを探す（本来の中隔は 8〜10 mm）。
    # 術前 CT があれば位置を合わせて、術前の穴（左右の血液のつながり）が閉じた所・術後に新しく薄くなった所だけを残す（もとから薄い所は外す）。
    # 計算はボタンを押した時だけ（1 例 数十秒〜1 分）。結果は 1 枚の面（patchToSheet）
    PATCH_THIN_MM = 2.0

    @staticmethod
    def _toSitk(arr, M):
        import SimpleITK as sitk, sitkUtils
        n = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "cv_tmpSitk")
        try:
            slicer.util.updateVolumeFromArray(n, np.ascontiguousarray(arr))
            m = vtk.vtkMatrix4x4()
            for r in range(4):
                for c in range(4): m.SetElement(r, c, float(M[r, c]))
            n.SetIJKToRASMatrix(m)
            return sitkUtils.PullVolumeFromSlicer(n)
        finally:
            slicer.mrmlScene.RemoveNode(n)

    def _thinPartition(self, vol, hc, w=2.0, res=0.45, hole=False):
        """左室と右室の血液の間が w mm 以下の薄い仕切り。res mm の等方格子（左右の心室のまわりだけ）。
        戻り値: dict(thin, hole（hole=True の時: 左右の血液をつなぐ所＝欠損）, M（ijk→RAS）, info)"""
        from scipy import ndimage
        a0 = slicer.util.arrayFromVolume(vol); sp0 = np.array(vol.GetSpacing())[::-1]
        lv0 = self._segmentMaskArray(hc, vol, ("left ventricle",)); rv0 = self._segmentMaskArray(hc, vol, ("right ventricle",)); my0 = self._segmentMaskArray(hc, vol, ("myocardium",))
        if lv0 is None or rv0 is None or my0 is None or not lv0.any() or not rv0.any():
            raise RuntimeError("心腔のラベル（左室・右室・心筋）がありません")
        bb = self._bbox(lv0 | rv0, 12); f = sp0 / res; n0 = np.array(a0[bb].shape, float)
        A = ndimage.zoom(a0[bb].astype(np.float32), f, order=1)
        lv = ndimage.zoom(lv0[bb].astype(np.uint8), f, order=0) > 0; rv = ndimage.zoom(rv0[bb].astype(np.uint8), f, order=0) > 0
        my = ndimage.zoom(my0[bb].astype(np.uint8), f, order=0) > 0
        del lv0, rv0, my0
        # zoom は両端の画素の中心どうしを合わせるので、本当の刻みは（入力の数−1）/（出力の数−1）。前は 1/f として計算していて、
        # 厚いスライスの CT ほど奥の方で位置がずれた（3 mm スライスで最大 2.6 mm、5 mm で 4.6 mm。薄い CT は 0.05 mm 程度で変わらない）
        n1 = np.array(A.shape, float); g = np.where(n1 > 1, (n0 - 1) / np.maximum(n1 - 1, 1), 1.0 / f)
        sp = sp0 * g                                                          # 本当の格子の間隔（mm。z, y, x）
        myo = float(np.median(A[my])); bl = float(np.median(A[lv]))
        dlab = ndimage.distance_transform_edt(~lv, sampling=sp); drab = ndimage.distance_transform_edt(~rv, sampling=sp)
        near = rv & (dlab <= 10)
        rvsep = float(np.median(A[near])) if near.any() else bl
        thrL = myo + 0.5 * (bl - myo); thrR = myo + 0.5 * (rvsep - myo)
        BL = (A > thrL) & (dlab <= 3.0); BR = (A > thrR) & (drab <= 3.0) & ~BL & (dlab > 0)
        dL = ndimage.distance_transform_edt(~BL, sampling=sp); dR = ndimage.distance_transform_edt(~BR, sampling=sp)
        thin = (~BL) & (~BR) & (dL + dR <= w) & (dL > 0) & (dR > 0)
        S = vtk.vtkMatrix4x4(); vol.GetIJKToRASMatrix(S); Ms = slicer.util.arrayFromVTKMatrix(S)
        sc = np.diag([g[2], g[1], g[0], 1.0]); sc[:3, 3] = [bb[2].start, bb[1].start, bb[0].start]
        out = dict(thin=thin, M=Ms @ sc, sp=sp, info=dict(myo=round(myo), blood=round(bl), rv=round(rvsep)))
        if hole:                                                          # 欠損: 造影された血液のつながりのうち、左室にも右室にも接しているもの（ラベルの外の所）
            thr = myo + 0.55 * (bl - myo)
            C = (A > thr) & (dlab <= 6) & (drab <= 6)
            lab, n = ndimage.label(C, structure=np.ones((3, 3, 3)))
            both = (set(np.unique(lab[ndimage.binary_dilation(lv) & C])) & set(np.unique(lab[ndimage.binary_dilation(rv) & C]))) - {0}
            out["hole"] = np.isin(lab, list(both)) & ~lv & ~rv if both else np.zeros_like(C)
        return out

    def _regPreToPost(self, pre, hcPre, post, hcPost, status=lambda m: None):
        """術前 → 術後の位置合わせ（左室・右室のラベルをなめらかにした像どうしを、剛体 → アフィンで）。戻り値: (sitk 変換, 左室・右室の Dice)"""
        import SimpleITK as sitk
        from scipy import ndimage
        def chans(vol, hc):
            lv0 = self._segmentMaskArray(hc, vol, ("left ventricle",)); rv0 = self._segmentMaskArray(hc, vol, ("right ventricle",))
            if lv0 is None or rv0 is None or not lv0.any() or not rv0.any():   # 前は下の lv0 | rv0 で落ちて、画面に英語のエラーの文が出た
                raise RuntimeError("術前か術後の CT に、心腔のラベル（左室・右室）が無いので、位置を合わせられません")
            sp0 = np.array(vol.GetSpacing())[::-1]; step = max(1, int(round(1.5 / float(sp0.min()))))
            bb = self._bbox(lv0 | rv0, int(np.ceil(20.0 / sp0.min())))
            sl = tuple(slice(b.start, b.stop, step) for b in bb)
            lv = lv0[sl].astype(np.float32); rv = rv0[sl].astype(np.float32); del lv0, rv0
            gsp = sp0 * step
            img = ndimage.gaussian_filter(lv, 1.5 / gsp) + 2.0 * ndimage.gaussian_filter(rv, 1.5 / gsp)
            msk = ndimage.binary_dilation((lv > 0) | (rv > 0), iterations=max(1, int(round(8.0 / gsp.min())))).astype(np.uint8)
            S = vtk.vtkMatrix4x4(); vol.GetIJKToRASMatrix(S); Ms = slicer.util.arrayFromVTKMatrix(S)
            sc = np.diag([float(step)] * 3 + [1.0]); sc[:3, 3] = [bb[2].start, bb[1].start, bb[0].start]
            M = Ms @ sc
            return self._toSitk(img.astype(np.float32), M), self._toSitk(msk, M), (lv > 0, rv > 0, M)
        status("パッチ: 術前と術後の位置を合わせています…")
        F, Fm, fl = chans(post, hcPost); Mv, Mm, ml = chans(pre, hcPre)
        init = sitk.CenteredTransformInitializer(Fm, Mm, sitk.Euler3DTransform(), sitk.CenteredTransformInitializerFilter.MOMENTS)
        best = None
        for stage in ("rigid", "affine"):
            R = sitk.ImageRegistrationMethod()
            R.SetMetricAsMeanSquares(); R.SetMetricSamplingStrategy(R.RANDOM); R.SetMetricSamplingPercentage(0.2, 1)
            R.SetMetricFixedMask(Fm)
            R.SetOptimizerAsRegularStepGradientDescent(1.0, 1e-4, 300); R.SetOptimizerScalesFromPhysicalShift()
            R.SetShrinkFactorsPerLevel([2, 1]); R.SetSmoothingSigmasPerLevel([2, 0]); R.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
            R.SetInterpolator(sitk.sitkLinear)
            if stage == "rigid": tx = sitk.Euler3DTransform(init)
            else:
                tx = sitk.AffineTransform(3); tx.SetCenter(best.GetCenter()); tx.SetMatrix(best.GetMatrix()); tx.SetTranslation(best.GetTranslation())
            R.SetInitialTransform(tx, inPlace=True)
            R.Execute(F, Mv); best = tx
        dice = []
        for i in range(2):                                                   # 合い具合（術前の左室・右室を術後へ写して重なり）
            a = self._toSitk(ml[i].astype(np.uint8), ml[2]); b = self._toSitk(fl[i].astype(np.uint8), fl[2])
            rs = sitk.GetArrayFromImage(sitk.Resample(a, b, best, sitk.sitkNearestNeighbor, 0)) > 0; bb_ = sitk.GetArrayFromImage(b) > 0
            dice.append(round(2.0 * float((rs & bb_).sum()) / max(float(rs.sum() + bb_.sum()), 1.0), 2))
        return best, dice

    PATCH_DICE_OK = 0.6     # 術前と術後の位置合わせの重なり（Dice）がこれより低い時は、結果の文で知らせる
    PATCH_MAX_SLICE_MM = 1.25   # これより厚いスライスの CT では、2 mm の薄い仕切りを見分けにくい（3 mm の術前 CT で試すと、薄い術前 CT の結果から 7 mm 以上離れた）

    def autoPatch(self, pre=None, status=lambda m: None):
        """パッチの範囲を自動で探して「パッチ」の面（1 枚）にする。pre = 術前 CT（なければ術後だけ）。戻り値: 結果の文"""
        if getattr(self, "_patchBusy", False): return "パッチ: いま探している途中です。終わるまでお待ちください"
        if getattr(self, "_building", False): return "パッチ: 3D を作っている途中です。終わってから押してください"
        self._patchBusy = True                                                # 途中の文の表示で画面が動くので、もう一度押されると最初から 2 本目が走っていた
        try: return self._autoPatch(pre, status)
        finally: self._patchBusy = False

    @staticmethod
    def _patchClassify(labP, nP, vox, preThin, preHole, tol):
        """術後の薄い所（labP の 1..nP のかたまり）を、術前と比べて分ける。戻り値: パッチの所（術後に新しく薄くなった所 ＋ 術前の欠損のうち術後に閉じた所）。
        前はかたまりごとに格子全体をなめていた（数百個で数秒〜十数秒）。ここでは、まとめて数える（結果は同じ）"""
        from scipy import ndimage
        cnt = np.bincount(labP.ravel(), minlength=nP + 1); big = cnt * vox >= 3; big[0] = False   # 3 mm³ より小さいかたまりは使わない
        dHole = ndimage.binary_dilation(preHole, iterations=tol); dThin = ndimage.binary_dilation(preThin, iterations=tol)
        sz = np.maximum(cnt, 1)
        inThin = np.bincount(labP.ravel(), weights=dThin.ravel(), minlength=nP + 1) / sz
        inHole = np.bincount(labP.ravel(), weights=dHole.ravel(), minlength=nP + 1) / sz
        isChg = big & (inThin < 0.5) & (inHole < 0.5)                         # 術後に新しく薄くなった所
        chg = isChg[labP]; same = (big & ~isChg)[labP]                         # もとから薄い・欠損のまま
        labH, nH = ndimage.label(preHole, structure=np.ones((3, 3, 3))); sameD = ndimage.binary_dilation(same, iterations=tol)
        cH = np.maximum(np.bincount(labH.ravel(), minlength=nH + 1), 1)
        isClosed = np.bincount(labH.ravel(), weights=sameD.ravel(), minlength=nH + 1) / cH < 0.3; isClosed[0] = False
        return isClosed[labH] | chg                                            # 術前の欠損のうち、術後に閉じた所 ＋ 新しく薄くなった所

    def _autoPatch(self, pre=None, status=lambda m: None):
        import SimpleITK as sitk
        from scipy import ndimage
        t0 = time.time()
        post = getattr(self, "sourceVolume", None)
        if post is None and getattr(self, "workVolume", None) is not None:
            try:
                post, how = self._findSourceFor(self.workVolume)
                if post is not None: self.sourceVolume = post; print(f"[CardiacView 点検] パッチ: 元の CT を探し直しました: {post.GetName()}（{how}）")
            except Exception as e: print("[CardiacView 点検] パッチ: 元の CT の探し直しに失敗:", e)
        hcPost = self._findChambers()
        if post is None or hcPost is None:
            miss = (["元の CT"] if post is None else []) + (["AI の心腔ラベル"] if hcPost is None else [])
            raise RuntimeError(f"パッチを探すのに必要な {'・'.join(miss)} が見つかりません。上の青いボタンで 3D を作り直してください")
        status("パッチ: 術後の CT で薄い仕切りを探しています…")
        thick = [f"{nm} CT（{max(v.GetSpacing()):.1f} mm）" for nm, v in (("術後", post), ("術前", pre)) if v is not None and max(v.GetSpacing()) > self.PATCH_MAX_SLICE_MM]
        thickNote = (f"\n⚠ {'・'.join(thick)} のスライスが厚いので、{self.PATCH_THIN_MM:.0f} mm の薄い所を見分けにくく、結果は参考程度です（1 mm 以下の CT がおすすめ）") if thick else ""
        P = self._thinPartition(post, hcPost, w=self.PATCH_THIN_MM)
        thin = P["thin"]; Mp = P["M"]; gsp = np.asarray(P.get("sp", [0.45] * 3), float); vox = float(np.prod(gsp))
        labP, nP = ndimage.label(thin, structure=np.ones((3, 3, 3)))
        cnt = np.bincount(labP.ravel(), minlength=nP + 1)                     # かたまりごとの大きさ（前はかたまりの数だけ格子全体をなめていた）
        big = cnt * vox >= 3; big[0] = False
        mode = "術後のみ"; note = ""; warn = ""                                # warn = 結果の後ろに出す ⚠ の文
        if pre is not None:
            hcPre = self._segFor(pre, "heartchambers")
            if hcPre is None:
                status("パッチ: 術前 CT の心腔を自動認識しています（初回だけ・約 4 分）…")
                hcPre = self._runTS(pre, "heartchambers", status, label="パッチ: 術前 CT の心腔を自動認識中")
            tx, dice = self._regPreToPost(pre, hcPre, post, hcPost, status)
            status("パッチ: 術前の欠損・もとから薄い所と比べています…")
            Q = self._thinPartition(pre, hcPre, w=self.PATCH_THIN_MM, hole=True)
            ref = self._toSitk(thin.astype(np.uint8), Mp)
            def onPost(a, M): return sitk.GetArrayFromImage(sitk.Resample(self._toSitk(a.astype(np.uint8), M), ref, tx, sitk.sitkNearestNeighbor, 0)) > 0
            preThin = onPost(Q["thin"], Q["M"]); preHole = onPost(Q["hole"], Q["M"])
            tol = max(1, int(round(2.4 / float(gsp.min()))))                 # 位置合わせのずれを 2.4 mm まで許す
            patch = self._patchClassify(labP, nP, vox, preThin, preHole, tol); mode = "術前 CT あり"; note = f"（位置合わせの重なり 左室 {dice[0]:.2f}・右室 {dice[1]:.2f}）"
            if min(dice) < self.PATCH_DICE_OK:                                # 前は低くてもそのまま使い、何も知らせなかった（違う場所の欠損が写る）
                warn += f"\n⚠ 術前と術後の位置がよく合っていません（重なり {min(dice):.2f}）。術前 CT を使った結果は参考程度にしてください（「術前 CT」を「なし」にすると術後だけで探します）"
        else:
            patch = big[labP]
        patch = ndimage.binary_closing(ndimage.binary_dilation(patch, iterations=2), iterations=7)      # 0.9 mm ふくらませて 3 mm の隙間を埋める
        patch = ndimage.binary_fill_holes(patch)
        lp, k = ndimage.label(patch, structure=np.ones((3, 3, 3))); sz = np.bincount(lp.ravel()) * vox; sz[0] = 0
        keep = np.nonzero(sz >= 20)[0]; patch = np.isin(lp, keep)
        if not patch.any(): return f"パッチらしい所は見つかりませんでした（{mode}）" + warn + thickNote
        status("パッチ: 面を作っています…")
        tmpv = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "cv_tmpPatch")
        try:
            slicer.util.updateVolumeFromArray(tmpv, patch.astype(np.uint8))
            m4 = vtk.vtkMatrix4x4()
            for r in range(4):
                for c in range(4): m4.SetElement(r, c, float(Mp[r, c]))
            tmpv.SetIJKToRASMatrix(m4)
            md = self._surfaceFromBinary(patch.astype(np.uint8), tmpv, "パッチ_tmp", PATCH_COLOR, 1, keepSmall=True)
        finally:
            slicer.mrmlScene.RemoveNode(tmpv)
        blob = vtk.vtkPolyData(); blob.DeepCopy(md.GetPolyData()); slicer.mrmlScene.RemoveNode(md)
        node = self.layerModels.get(self.PATCH_KEY)
        if node is None or not slicer.mrmlScene.IsNodePresent(node):
            node = slicer.modules.models.logic().AddModel(blob); node.SetName("CV パッチ"); self._put(node)
            d = node.GetDisplayNode(); self._styleDisplay(d, PATCH_COLOR)
        else:
            node.SetAndObservePolyData(blob)
        old = slicer.mrmlScene.GetFirstNodeByName("cv_patch_blob")
        if old is not None: slicer.mrmlScene.RemoveNode(old)
        node.SetAttribute("CV.patchSheet", "0"); node.SetAttribute("CV.patchStrokes", "[]"); node.SetAttribute("CV.patchMode", mode)
        node.SetAttribute("CV.vrTint", ",".join(f"{x:.2f}" for x in PATCH_COLOR))
        self.layerModels[self.PATCH_KEY] = node; self.visible[self.PATCH_KEY] = True; self._strokes = []
        try: self.patchToSheet()
        except Exception as e:                                                # 1 枚にできなくても、範囲（塊）のまま見せて、続きを済ませる
            import traceback; traceback.print_exc(); warn += f"\n⚠ 1 枚の面にできなかったので、範囲のまま出しています（{e}）"
        d = node.GetDisplayNode()
        if d is not None:
            d.SetVisibility(self._layerShown(self.PATCH_KEY)); d.SetColor(*PATCH_COLOR); d.SetSpecular(0.12); d.SetPower(10)
        if self.cutAxis is not None: self._applyClipToModels(True)
        if getattr(self, "vrDisplay", None) is not None and not getattr(self, "vrOn", False): self.vrDisplay = None      # 次の VR でパッチの色を塗り直す
        self._patchRemoved = []
        n = len(keep)
        return f"パッチの範囲を自動で出しました（{mode}{note}・{n} か所・{time.time() - t0:.0f} 秒）。違う所は「違う所を外す」でクリック" + warn + thickNote

    def patchRemoveAt(self, ras, tol=12.0):
        """クリックした所に一番近いパッチのかたまりを外す。戻り値: 外せたか"""
        node = self.layerModels.get(self.PATCH_KEY); pd = node.GetPolyData() if node is not None else None
        if pd is None or pd.GetNumberOfPoints() == 0: return False
        cf = vtk.vtkPolyDataConnectivityFilter(); cf.SetInputData(pd); cf.SetExtractionModeToAllRegions(); cf.ColorRegionsOn(); cf.Update()
        o = cf.GetOutput()
        loc = vtk.vtkPointLocator(); loc.SetDataSet(o); loc.BuildLocator()
        pid = loc.FindClosestPoint([float(x) for x in ras])
        if pid < 0 or np.linalg.norm(np.array(o.GetPoint(pid)) - np.asarray(ras, float)) > tol: return False
        rid = o.GetPointData().GetArray("RegionId").GetValue(pid)
        th = vtk.vtkThreshold(); th.SetInputData(o); th.SetInputArrayToProcess(0, 0, 0, 0, "RegionId")
        th.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_BETWEEN); th.SetLowerThreshold(rid - 0.5); th.SetUpperThreshold(rid + 0.5); th.InvertOn(); th.Update()
        gf = vtk.vtkGeometryFilter(); gf.SetInputConnection(th.GetOutputPort()); gf.Update()
        new = vtk.vtkPolyData(); new.DeepCopy(gf.GetOutput())
        new.GetPointData().RemoveArray("RegionId"); new.GetCellData().RemoveArray("RegionId")
        prev = vtk.vtkPolyData(); prev.DeepCopy(pd); self.__dict__.setdefault("_patchRemoved", []).append((node.GetID(), prev))   # どのパッチの記録か（ノード）も覚える
        node.SetAndObservePolyData(new)
        if getattr(self, "vrDisplay", None) is not None and not getattr(self, "vrOn", False): self.vrDisplay = None
        self._view().scheduleRender()
        return True

    def patchRemoveUndo(self):
        st_ = getattr(self, "_patchRemoved", None) or []
        node = self.layerModels.get(self.PATCH_KEY)
        if not st_ or node is None: return False
        nid, prev = st_.pop()
        if nid != node.GetID() or not slicer.mrmlScene.IsNodePresent(node):       # 別の症例・別のパッチの記録（開き直した後など）は使わない
            self._patchRemoved = []; return False
        node.SetAndObservePolyData(prev)
        if getattr(self, "vrDisplay", None) is not None and not getattr(self, "vrOn", False): self.vrDisplay = None      # 外した時と同じ: 次の VR でパッチの色を塗り直す
        self._view().scheduleRender(); return True

    def patchUndo(self):
        st = getattr(self, "_strokes", None) or []
        if not st: return "戻すものがありません"
        last = max(s[0] for s in st); self._strokes = [s for s in st if s[0] != last]
        self._patchReplay(); self._patchBuild(); self._patchSave()
        return "ひと塗り戻しました"

    def patchClear(self):
        if not (getattr(self, "_strokes", None) or []): return "塗ったパッチはありません"
        self._strokes = []; self._pMask = {}; self._pMaskKey = {}; self._patchBuild(); self._patchSave()
        return "塗ったパッチを全部消しました（「1つ戻す」では戻りません）"

    def _roomCenters(self):
        """血液の面（左房・左室・右房・右室で塗り分け済み）から 左室・右室の中心 → (cLV, cRV) / None"""
        from vtk.util.numpy_support import vtk_to_numpy
        n = self.layerModels.get("血管:心臓"); pd = n.GetPolyData() if n is not None else None
        a = pd.GetPointData().GetArray("CV_room") if pd is not None else None
        if a is None: return None
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float); r = vtk_to_numpy(a).astype(int)
        if (r == 1).sum() < 20 or (r == 3).sum() < 20: return None
        return P[r == 1].mean(0), P[r == 3].mean(0)

    def patchFace(self, gap=4.0, side=None):
        """パッチを正面に向けて、パッチの手前を切る（体に固定）。side = "L"（左室側から）/ "R"（右室側から）/ None（今見ている側から）"""
        from vtk.util.numpy_support import vtk_to_numpy
        node = self.layerModels.get(self.PATCH_KEY)
        pd = node.GetPolyData() if node is not None else None
        if pd is None or pd.GetNumberOfPoints() < 3: return False
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        c = P.mean(0); _, _, Vt = np.linalg.svd(P - c, full_matrices=False); n = Vt[2] / np.linalg.norm(Vt[2])
        nr = pd.GetPointData().GetNormals()
        if nr is not None and nr.GetNumberOfTuples() == len(P):                 # 曲がった 1 枚のパッチ: 法線の向きの平均（表裏は問わない）が正面
            N = vtk_to_numpy(nr).astype(float); w_, V_ = np.linalg.eigh(N.T @ N); n = V_[:, -1] / np.linalg.norm(V_[:, -1])
        cn = self._camera(); cam = cn.GetCamera()
        pos = np.array(cam.GetPosition()); fp = np.array(cam.GetFocalPoint())
        cc = self._roomCenters() if side in ("L", "R") else None
        if cc is not None:
            d = cc[0 if side == "L" else 1] - c
            if float(d @ n) < 0: n = -n                                       # 左室側（右室側）にカメラ
        elif float((pos - c) @ n) < 0: n = -n                                 # 今見ている側から
        dist = float(np.linalg.norm(pos - fp)) or 300.0
        up = np.array(cam.GetViewUp(), float); up = up - n * float(up @ n)
        if np.linalg.norm(up) < 1e-3: up = np.array([0.0, 0.0, 1.0]) - n * n[2]
        up /= np.linalg.norm(up); rt = np.cross(up, n)
        half = float(max(np.abs((P - c) @ up).max(), np.abs((P - c) @ rt).max(), 8.0))
        self.flying = False; self._camGen = getattr(self, "_camGen", 0) + 1
        cn.SetFocalPoint(*c); cn.SetPosition(*(c + n * dist)); cn.SetViewUp(*up)
        if cam.GetParallelProjection(): cam.SetParallelScale(max(30.0, 2.2 * half))
        lo, hi = self._visibleBounds()
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        proj = corners @ n; dmin, dmax = float(proj.min()), float(proj.max())
        s_ = float(c @ n + max(0.0, float(((P - c) @ n).max())) + gap)
        if getattr(self, "vrOn", False):
            if getattr(self, "vrMode", "tissue") == "blood": s_ = float(c @ n)    # VR 造影は血液が詰まって見えるので、パッチの真ん中で切る（パッチは切らずに出す）
            else:                                                         # VR 心内は血液が透けるので、部屋の中で切る（中隔の肉柱・乳頭筋・パッチの縁が立体で見える）
                ext = max(0.0, float(((P - c) @ n).max()))
                half_ = 0.5 * float((cc[0 if side == "L" else 1] - c) @ n) if cc is not None else ext + 6.0   # パッチと部屋の真ん中の間
                s_ = float(c @ n + max(ext + 3.0, half_))
        self._lockN = n.tolist(); self._lockPrev = "VIEW"
        self.cutSign = 1.0                                                   # 「反転」を押した後でも、パッチの手前（カメラの側）を切る
        self.setCut("LOCK", float(np.clip((dmax - s_) / max(dmax - dmin, 1e-6), 0, 1)))
        cn.ResetClippingRange(); self._view().forceRender(); self._syncCutUI()
        return True
