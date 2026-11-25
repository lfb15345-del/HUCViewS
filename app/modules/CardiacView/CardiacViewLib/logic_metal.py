# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 人工物（金属・胸骨ワイヤー）・骨・石灰化
CardiacViewLogic の一部（MetalMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *
from . import common          # 色合いで置き換わる名前は common.名前 で今の値を読む


class MetalMixin:
    # ================================================================ 人工物・石灰化
    METAL_HU = 2000.0

    @staticmethod
    def _bbox(m, mg=0):
        r = [np.nonzero(m.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
        return tuple(slice(max(0, int(q.min()) - mg), min(m.shape[i], int(q.max()) + 1 + mg)) for i, q in enumerate(r))

    @staticmethod
    def _boxVol(src, oi, oj, ok):
        """元の CT の一部（箱）の位置を持った「面を作るための入れ物」"""
        S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S); I = vtk.vtkMatrix4x4(); I.DeepCopy(S)
        for r in range(3): I.SetElement(r, 3, S.GetElement(r, 3) + S.GetElement(r, 0) * oi + S.GetElement(r, 1) * oj + S.GetElement(r, 2) * ok)
        class _Box:
            def GetIJKToRASMatrix(self, m): m.DeepCopy(I)
            def GetRASToIJKMatrix(self, m): m.DeepCopy(I); m.Invert()
        return _Box()

    def _srcSub(self, work, nearW):
        """作業画像のマスク nearW のまわりを、元の CT（細かい画素）から切り出す。細い金属は作業画像だと消えるため。
        返り値: (元 CT, 切り出した CT, その中の nearW, 箱の位置 (i0, j0, k0), 拡大率, ずれ) / None"""
        if nearW is None or not nearW.any(): return None
        src = getattr(self, "sourceVolume", None) or work
        sarr = slicer.util.arrayFromVolume(src)
        W = vtk.vtkMatrix4x4(); work.GetRASToIJKMatrix(W); S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S)
        Mw = np.array([[W.GetElement(r, c) for c in range(4)] for r in range(4)]); Ms = np.array([[S.GetElement(r, c) for c in range(4)] for r in range(4)])
        M = Mw @ Ms
        if np.abs(M[:3, :3] - np.diag(np.diag(M[:3, :3]))).max() > 1e-3:
            src, sarr, M = work, slicer.util.arrayFromVolume(work), np.eye(4)
        sh = nearW.shape
        zz, yy, xx = np.nonzero(nearW.any(axis=(1, 2)))[0], np.nonzero(nearW.any(axis=(0, 2)))[0], np.nonzero(nearW.any(axis=(0, 1)))[0]
        lo_w = np.array([xx.min(), yy.min(), zz.min()]) - 1; hi_w = np.array([xx.max(), yy.max(), zz.max()]) + 1
        sc = np.diag(M[:3, :3]); off = M[:3, 3]
        b1 = (lo_w - off) / sc; b2 = (hi_w - off) / sc
        lo_s = np.maximum(np.floor(np.minimum(b1, b2)).astype(int), 0); hi_s = np.minimum(np.ceil(np.maximum(b1, b2)).astype(int) + 1, np.array(sarr.shape[::-1]))
        i0, j0, k0 = (int(v) for v in lo_s); i1, j1, k1 = (int(v) for v in hi_s)
        if i1 <= i0 or j1 <= j0 or k1 <= k0: return None
        sub = sarr[k0:k1, j0:j1, i0:i1]
        ix = np.clip(np.rint(sc[0] * np.arange(i0, i1) + off[0]).astype(int), 0, sh[2] - 1)
        jy = np.clip(np.rint(sc[1] * np.arange(j0, j1) + off[1]).astype(int), 0, sh[1] - 1)
        kz = np.clip(np.rint(sc[2] * np.arange(k0, k1) + off[2]).astype(int), 0, sh[0] - 1)
        nearS = nearW[kz[:, None, None], jy[None, :, None], ix[None, None, :]]
        return src, sub, nearS, (i0, j0, k0), sc, off

    def findWires(self, work, segNode):
        """胸骨のまわり（AI の胸骨ラベル + 8 mm）で 2000 HU 以上 = 胸骨ワイヤー。細いので元の CT（細かい画素）で探す。
        返り値 dict(mask=元 CT の箱の中のワイヤー, at=箱の位置, src=元 CT, workMask=作業画像で 2.5 mm 太らせたワイヤー（骨から抜く）, n=かたまりの数, mm3=体積) / None"""
        from scipy import ndimage
        if segNode is None: return None
        st = self._segmentMaskArray(segNode, work, ("sternum",))
        if st is None or not st.any(): return None
        sp = np.array(work.GetSpacing(), float)[::-1]                        # (z, y, x)
        box = self._bbox(st, int(np.ceil(10.0 / sp.min())))
        nearW = np.zeros(st.shape, bool)
        nearW[box] = ndimage.distance_transform_edt(~st[box], sampling=sp) <= 8.0
        cut = self._srcSub(work, nearW)
        if cut is None: return None
        src, sub, nearS, (i0, j0, k0), sc, off = cut
        wire = (sub >= self.METAL_HU) & nearS
        if not wire.any(): return None
        vox = float(np.prod(src.GetSpacing()))
        lab, n = ndimage.label(wire, structure=np.ones((3, 3, 3)))
        sizes = np.bincount(lab.ravel(), minlength=n + 1) * vox
        keep = sizes >= 2.0; keep[0] = False
        wire = keep[lab]
        if not wire.any(): return None
        kk, jj, ii = np.nonzero(wire); sh = nearW.shape
        ix = np.clip(np.rint(sc[0] * (ii + i0) + off[0]).astype(int), 0, sh[2] - 1)
        jy = np.clip(np.rint(sc[1] * (jj + j0) + off[1]).astype(int), 0, sh[1] - 1)
        kz = np.clip(np.rint(sc[2] * (kk + k0) + off[2]).astype(int), 0, sh[0] - 1)
        wW = np.zeros(sh, bool); wW[kz, jy, ix] = True
        b2 = self._bbox(wW, int(np.ceil(3.5 / sp.min())) + 1)
        wW[b2] = ndimage.binary_dilation(wW[b2], iterations=max(1, int(round(2.5 / sp.min()))))   # ワイヤーのにじみ（金属のまわりの明るい所）も骨にしない
        return dict(mask=wire, at=(i0, j0, k0), src=src, workMask=wW, n=int(keep.sum()), mm3=round(float(wire.sum() * vox)))

    def _buildBone(self, arr, work, spacing, segNode, boneMask, body):
        """骨の面。胸骨ワイヤー（金属）は骨から抜いて、人工物（銀）の面に入れる（骨の中に埋もれて見えなくなるため）"""
        from scipy import ndimage
        # AI の骨ラベルは 3mm 格子でカクカク → 形は CT 値（≥200HU）で取り、ラベルは「どこが骨か」の目印にだけ使う
        near = ndimage.distance_transform_edt(~boneMask, sampling=spacing) <= 3.0
        bm = (arr >= 200) & near
        if body is not None: bm &= body
        if segNode is not None:
            vv = self._segmentMaskArray(segNode, work, ("aorta", "vena cava", "pulmonary", "heart", "atrial appendage", "brachiocephalic", "subclavian", "carotid", "iliac", "kidney"))
            if vv is not None: bm &= ~ndimage.binary_dilation(vv, iterations=1)
        wires = None
        try: wires = self.findWires(work, segNode)
        except Exception as e:
            import traceback; traceback.print_exc(); print("wires:", e)
        if wires is not None: bm &= ~wires["workMask"]
        bm = ndimage.binary_closing(bm, iterations=1)
        bm = self._cleanBinary(bm.astype(np.uint8), spacing, minVox=150)
        self.layerModels["骨"] = self._surfaceFromBinary(bm, work, "骨", common.BONE_COLOR, 2); self.visible["骨"] = True
        old = slicer.mrmlScene.GetFirstNodeByName("CV 胸骨ワイヤー")             # 胸骨ワイヤーは別の層（銅色）にせず、人工物（銀）の層にまとめる（先生の判断・版 15）。前の版の層は消す
        if old: slicer.mrmlScene.RemoveNode(old)
        self.layerModels.pop("胸骨ワイヤー", None); self.visible.pop("胸骨ワイヤー", None); self.wireStats = dict(n=0, mm3=0); self._wirePD = None
        if wires is not None:
            m = wires["mask"]; sl = self._bbox(m, 4); i0, j0, k0 = wires["at"]
            if max(wires["src"].GetSpacing()) > 1.25:                             # 厚いスライス（2〜5mm）では細い線が面にならず消える → 1 画素ふくらませる
                m = m.copy(); m[sl] = ndimage.binary_dilation(m[sl], iterations=1)
            model = self._surfaceFromBinary(np.ascontiguousarray(m[sl]).astype(np.uint8), self._boxVol(wires["src"], i0 + sl[2].start, j0 + sl[1].start, k0 + sl[0].start),
                                            "胸骨ワイヤー", WIRE_COLOR, 1, keepSmall=True)
            pd = vtk.vtkPolyData(); pd.DeepCopy(model.GetPolyData()); self._wirePD = pd   # 面だけ持っておき、人工物の面に足す（buildImplantsCalc → _withWires）
            slicer.mrmlScene.RemoveNode(model)
            self.wireStats = dict(n=wires["n"], mm3=wires["mm3"])
        print("胸骨ワイヤー:", self.wireStats)

    def redoMetal(self, status=lambda m: None):
        """前に作った症例で、骨・人工物（胸骨ワイヤーを含む）・石灰化だけ作り直す（保存してある AI ラベルを使う）。画面のボタンは無い（試験・保守用）"""
        work = getattr(self, "workVolume", None); segNode = self._findSegmentation()
        if work is None or work.GetImageData() is None or segNode is None:
            raise RuntimeError("AI のラベルか作業用の画像がありません。「3D を自動で作る」からやり直してください")
        arr = slicer.util.arrayFromVolume(work); spacing = float(min(work.GetSpacing()))
        boneVis = bool(self.visible.get("骨", False))
        status("骨のラベルを取得中…"); boneMask = self._boneMaskArray(segNode, work)
        if boneMask is not None:
            status("骨・胸骨ワイヤーを作り直しています…"); slicer.app.processEvents()
            self._buildBone(arr, work, spacing, segNode, boneMask, self._bodyMask(arr))
        status("人工物・石灰化を探しています…"); slicer.app.processEvents()
        self.buildImplantsCalc(arr, work, spacing, segNode, boneMask)
        for k in ("骨", "人工物", "石灰化"):
            n = self.layerModels.get(k)
            if n is None or n.GetDisplayNode() is None: continue
            on = boneVis if k == "骨" else True
            self.visible[k] = on; n.GetDisplayNode().SetVisibility(self._layerShown(k))   # VR・4D の途中は VR の上に出さない
        self._updateBounds()
        if self.cutAxis is not None: self._applyClipToModels(True)
        try: self.updateInset()
        except Exception: pass
        w = getattr(self, "wireStats", None) or {}; s = getattr(self, "implantStats", None) or {}
        return f"作り直しました: 人工物 {s.get('metal_n', 0)} 個・胸骨ワイヤー {w.get('n', 0)} 個（どちらも銀）・石灰化 {s.get('calc_n', 0)} 個（黄白）"

    def _withWires(self, model):
        """人工物の層（model。無ければ None）に、_buildBone で作って持っておいた胸骨ワイヤーの面を足す。ワイヤーだけの時は人工物の層をワイヤーで作る"""
        wpd = getattr(self, "_wirePD", None); self._wirePD = None
        if wpd is None or wpd.GetNumberOfPoints() == 0: return model
        if model is None:
            model = slicer.modules.models.logic().AddModel(wpd); model.SetName("CV 人工物"); self._styleDisplay(model.GetDisplayNode(), IMPLANT_COLOR); self._put(model)
        else:
            ap = vtk.vtkAppendPolyData(); ap.AddInputData(model.GetPolyData()); ap.AddInputData(wpd); ap.Update()
            pd = vtk.vtkPolyData(); pd.DeepCopy(ap.GetOutput()); model.SetAndObservePolyData(pd)
        return model

    def _styleImplant(self, model):
        d = model.GetDisplayNode(); d.SetSpecular(0.9); d.SetPower(70); d.SetAmbient(0.25)          # 金属らしく光らせる

    def buildImplantsCalc(self, arr, work, spacing, segNode, boneMask=None):
        """心臓・大血管のまわりで、金属（人工弁のリング・ステント・クリップ・ワイヤー）と石灰化を CT 値から見つけて、別の色の面にする。
        - 金属: 2000 HU 以上
        - 石灰化: その症例の造影血液より 250 HU 以上高い所（最低 650 HU）。金属のまわりのにじみは除く
        - 骨（胸骨のワイヤーを含む）と、造影剤が濃いまま流れ込む静脈（上大静脈・腕頭静脈・鎖骨下静脈）の中は除く
        パッチや人工血管（布・ePTFE）は CT 値では見分けられないので対象外（将来 AI で）"""
        from scipy import ndimage
        c = self._cal(); blood = float(c.get("blood") or (c.get("blood_lo", 180) + 150))
        calcT = max(650.0, blood + 250.0)
        vv = self._segmentMaskArray(segNode, work, ("heart", "aorta", "pulmonary", "atrial appendage", "brachiocephalic trunk", "subclavian artery",
                                                    "common carotid", "iliac artery", "coronary", "vena cava"))
        if vv is None or not vv.any():
            if getattr(self, "_wirePD", None) is not None:                     # 心臓・血管のラベルが無くても、胸骨ワイヤーは人工物として出す
                old = slicer.mrmlScene.GetFirstNodeByName("CV 人工物")
                if old: slicer.mrmlScene.RemoveNode(old)
                model = self._withWires(None); self._styleImplant(model); self.layerModels["人工物"] = model; self.visible["人工物"] = True
            return
        near = ndimage.distance_transform_edt(~vv, sampling=spacing) <= 6.0
        if boneMask is not None and boneMask.any():
            near &= ~(ndimage.distance_transform_edt(~boneMask, sampling=spacing) <= 2.0)
        try:                                                                 # 心腔・大血管の内側（縁から 2 mm より内）は造影剤のむら（右心系への流入など）なので石灰化にしない
            hc = self._findChambers()
            inner = self._segmentMaskArray(hc, work, ("ventricle", "atrium", "pulmonary artery")) if hc is not None else None
            v2 = self._segmentMaskArray(segNode, work, ("vena cava", "atrium"))
            inner = v2 if inner is None else (inner if v2 is None else inner | v2)
            if inner is not None and inner.any():
                near &= ~ndimage.binary_erosion(inner, iterations=max(1, int(round(2.0 / float(np.min(spacing) if np.ndim(spacing) else spacing)))))
        except Exception as e: print("calc inner:", e)
        veins = self._segmentMaskArray(segNode, work, ("superior vena cava", "brachiocephalic vein", "subclavian vein", "jugular vein"))
        if veins is not None and veins.any(): near &= ~ndimage.binary_dilation(veins, iterations=1)
        # 作業用画像（0.8mm・ぼかし済み）では小さな石灰化や細いワイヤーが消えるので、元の CT（0.3〜0.5mm）で探す
        src = getattr(self, "sourceVolume", None) or work
        sarr = slicer.util.arrayFromVolume(src)
        W = vtk.vtkMatrix4x4(); work.GetRASToIJKMatrix(W); S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S)
        Mw = np.array([[W.GetElement(r, c) for c in range(4)] for r in range(4)]); Ms = np.array([[S.GetElement(r, c) for c in range(4)] for r in range(4)])
        M = Mw @ Ms                                              # 元CT の IJK → 作業画像の IJK
        sh = near.shape                                         # (z, y, x)
        if np.abs(M[:3, :3] - np.diag(np.diag(M[:3, :3]))).max() > 1e-3:
            src, sarr, M = work, arr, np.eye(4)                  # 向きが違う時は作業画像で（まれ）
            work.GetIJKToRASMatrix(S)                            # 面の置き場所（boxAt）も作業画像の行列で（前は元 CT の行列のままで、面がずれた。_srcSub は前から正しい）
        # 心臓・血管の近く（作業画像の箱）だけ元CTから切り出す
        zz, yy, xx = np.nonzero(near.any(axis=(1, 2)))[0], np.nonzero(near.any(axis=(0, 2)))[0], np.nonzero(near.any(axis=(0, 1)))[0]
        lo_w = np.array([xx.min(), yy.min(), zz.min()]) - 1; hi_w = np.array([xx.max(), yy.max(), zz.max()]) + 1
        sc = np.diag(M[:3, :3]); off = M[:3, 3]
        b1 = (lo_w - off) / sc; b2 = (hi_w - off) / sc
        lo_s = np.maximum(np.floor(np.minimum(b1, b2)).astype(int), 0); hi_s = np.minimum(np.ceil(np.maximum(b1, b2)).astype(int) + 1, np.array(sarr.shape[::-1]))
        i0, j0, k0 = lo_s; i1, j1, k1 = hi_s
        sub = sarr[k0:k1, j0:j1, i0:i1]
        ix = np.clip(np.rint(sc[0] * np.arange(i0, i1) + off[0]).astype(int), 0, sh[2] - 1)
        jy = np.clip(np.rint(sc[1] * np.arange(j0, j1) + off[1]).astype(int), 0, sh[1] - 1)
        kz = np.clip(np.rint(sc[2] * np.arange(k0, k1) + off[2]).astype(int), 0, sh[0] - 1)
        nearS = near[kz[:, None, None], jy[None, :, None], ix[None, None, :]]
        metal = (sub >= self.METAL_HU) & nearS
        calc = (sub >= calcT) & (sub < self.METAL_HU) & nearS
        del nearS
        if metal.any() and calc.any():                           # 金属（ステントの線など）につながっている「石灰化」は、厚いスライスでぼけた金属 → 人工物にまとめる
            lc, nc = ndimage.label(calc, structure=np.ones((3, 3, 3)))
            touch = np.unique(lc[ndimage.binary_dilation(metal, iterations=2) & calc]); touch = touch[touch > 0]
            if len(touch):
                mv = np.isin(lc, touch); metal |= mv; calc &= ~mv
            del lc
        if metal.any():                                          # 金属のにじみ（ハレーション）は石灰化にしない（金属のまわりの箱だけで計算＝速い）
            for sl in ndimage.find_objects(ndimage.label(metal)[0]):
                sl = tuple(slice(max(0, q.start - 4), q.stop + 4) for q in sl)
                calc[sl] &= ~ndimage.binary_dilation(metal[sl], iterations=3)
        vox = float(np.prod(src.GetSpacing()))
        def bbox(m, mg=0):
            r = [np.nonzero(m.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
            return tuple(slice(max(0, q.min() - mg), min(m.shape[i], q.max() + 1 + mg)) for i, q in enumerate(r))
        def clean(m, min_mm3):
            sl = bbox(m); sm = m[sl]                              # 候補のある範囲だけで数える（速い）
            lab, n = ndimage.label(sm, structure=np.ones((3, 3, 3)))
            sizes = np.bincount(lab.ravel(), minlength=n + 1) * vox
            keep = sizes >= min_mm3; keep[0] = False
            out = np.zeros_like(m); out[sl] = keep[lab]
            return out, int(keep.sum())
        metal, nM = clean(metal, 3.0) if metal.any() else (metal, 0)
        calc, nC = clean(calc, 2.0) if calc.any() else (calc, 0)
        self.implantStats = dict(metal_mm3=round(float(metal.sum() * vox)), metal_n=nM, calc_mm3=round(float(calc.sum() * vox)), calc_n=nC, calcT=round(calcT))
        # 切り出した箱の位置を持った「面を作るための入れ物」（見つかった所のまわりだけで面を作る＝速い）
        def boxAt(oi, oj, ok):
            I = vtk.vtkMatrix4x4(); I.DeepCopy(S)
            for r in range(3): I.SetElement(r, 3, S.GetElement(r, 3) + S.GetElement(r, 0) * oi + S.GetElement(r, 1) * oj + S.GetElement(r, 2) * ok)
            class _Box:
                def GetIJKToRASMatrix(self, m): m.DeepCopy(I)
                def GetRASToIJKMatrix(self, m): m.DeepCopy(I); m.Invert()
            return _Box()
        for name, m, col in (("人工物", metal, IMPLANT_COLOR), ("石灰化", calc, common.CALC_COLOR)):
            old = slicer.mrmlScene.GetFirstNodeByName(f"CV {name}")
            if old: slicer.mrmlScene.RemoveNode(old)
            self.layerModels.pop(name, None)
            model = None
            if m.any():
                sl = bbox(m, 4)
                model = self._surfaceFromBinary(np.ascontiguousarray(m[sl]).astype(np.uint8), boxAt(i0 + sl[2].start, j0 + sl[1].start, k0 + sl[0].start),
                                                name, col, 1, keepSmall=True)
            if name == "人工物": model = self._withWires(model)                 # 胸骨ワイヤーも人工物（銀）にまとめる
            if model is None: continue
            d = model.GetDisplayNode()
            if name == "人工物": self._styleImplant(model)
            else: d.SetSpecular(0.5); d.SetPower(30); d.SetAmbient(0.3)
            self.layerModels[name] = model; self.visible[name] = True
        print("人工物・石灰化:", self.implantStats)
