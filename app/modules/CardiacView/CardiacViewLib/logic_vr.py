# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: VR（ボリュームレンダリング）: 心内構造・造影・色分け・窓・切断との同期・動かす間だけ粗く
CardiacViewLogic の一部（VRMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *
from . import common          # 色合いで置き換わる名前は common.名前 で今の値を読む


class VRMixin:
    # ---------------------------------------------------------------- VR（ボリュームレンダリング）: 心内構造を見る
    VR_MODES = {"tissue": "心内構造（弁・乳頭筋・中隔）", "blood": "造影（血液の鋳型）"}
    # 部屋ごとの色（左心系 = 暖色、右心系 = 寒色）。右心系は造影の目盛りも別に持つ
    VR_GROUPS = [("hc", ("left ventricle", "myocardium"), (0.88, 0.44, 0.40), "L"),
                 ("hc", ("left atrium",), (0.95, 0.62, 0.50), "L"),
                 ("hc", ("aorta",), (0.93, 0.30, 0.28), "L"),
                 ("tot", ("pulmonary vein",), (0.95, 0.55, 0.45), "L"),
                 ("tot", ("atrial appendage left",), (0.95, 0.62, 0.50), "L"),
                 ("hc", ("right ventricle",), (0.45, 0.58, 0.90), "R"),
                 ("hc", ("right atrium",), (0.58, 0.68, 0.93), "R"),
                 ("hc", ("pulmonary artery",), (0.42, 0.50, 0.88), "R"),
                 ("tot", ("vena cava",), (0.50, 0.62, 0.92), "R")]
    VR_NEUTRAL = (0.88, 0.72, 0.62)
    VR_PALE = None
    VR_SEPTUM = None

    def _gridNode(self, src, lo, hi, step):
        """src の一部（lo..hi, ijk = z,y,x）を step 倍の粗さで覆う空の参照ボリューム（ラベルの書き出し先）"""
        shp = [int(np.ceil((h - l) / step)) for l, h in zip(lo, hi)]
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "cv_vrgrid")
        img = vtk.vtkImageData(); img.SetDimensions(shp[2], shp[1], shp[0]); img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        node.SetAndObserveImageData(img)
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M)
        G = vtk.vtkMatrix4x4(); G.DeepCopy(M)
        o = [sum(M.GetElement(r, c) * v for c, v in enumerate((lo[2], lo[1], lo[0], 1))) for r in range(3)]
        for r in range(3):
            for c in range(3): G.SetElement(r, c, M.GetElement(r, c) * step)
            G.SetElement(r, 3, o[r])
        node.SetIJKToRASMatrix(G)
        return node, shp

    def _applyVRTints(self, rgb, src, lo, step):
        """VR の色に「範囲の色」を重ねる。self.vrTints = [dict(mask=配列 (z,y,x), ijkToRAS=4x4, color=(r,g,b)), ...]
        範囲の各点を VR の粗い格子へ写して塗る（範囲だけ計算するので速い）"""
        self._vrTintHits = []
        tints = list(getattr(self, "vrTints", None) or [])
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            tc = n.GetAttribute("CV.vrTint"); pd = n.GetPolyData()
            if not tc or pd is None or pd.GetNumberOfPoints() == 0: continue
            from vtk.util.numpy_support import vtk_to_numpy
            tints.append(dict(points=vtk_to_numpy(pd.GetPoints().GetData()).astype(float), color=tuple(float(x) for x in tc.split(","))))
        if not tints: return
        from scipy import ndimage
        S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S); Ms = slicer.util.arrayFromVTKMatrix(S)
        G = Ms @ np.array([[step, 0, 0, lo[2]], [0, step, 0, lo[1]], [0, 0, step, lo[0]], [0, 0, 0, 1.0]])   # 粗い格子 (i, j, k) → RAS
        Gi = np.linalg.inv(G); sh = rgb.shape[:3]
        for t in tints:
            if t.get("points") is not None:
                ras = np.c_[t["points"], np.ones(len(t["points"]))].T
            else:
                m = t.get("mask")
                if m is None or not m.any(): continue
                idx = np.argwhere(m)                                               # (z, y, x)
                ras = t["ijkToRAS"] @ np.c_[idx[:, ::-1], np.ones(len(idx))].T
            g = np.rint((Gi @ ras)[:3]).astype(int)                                  # (i, j, k)
            ok = (g[0] >= 0) & (g[0] < sh[2]) & (g[1] >= 0) & (g[1] < sh[1]) & (g[2] >= 0) & (g[2] < sh[0])
            hit = np.zeros(sh, bool); hit[g[2][ok], g[1][ok], g[0][ok]] = True
            hit = ndimage.binary_dilation(hit, iterations=1)
            rgb[hit] = np.array(t.get("color", (0.15, 0.85, 0.35)), np.float32)
            self._vrTintHits.append((hit, np.array(t.get("color", (0.15, 0.85, 0.35)), np.float32)))   # 淡くした後にもう一度この色で塗る（パッチが白くならないように）

    def setupVR(self, status=lambda m: None):
        """心臓まわりだけ切り出した元の CT を、部屋ごとに色分け・造影の目盛りをそろえた RGBA の VR にする"""
        from scipy import ndimage
        self._syncVRPalette()
        src = getattr(self, "sourceVolume", None)
        if src is None or self._isWorkVolume(src):                       # 症例を開いた後に元の CT が結び付いていない → 探し直す
            w = getattr(self, "workVolume", None) or (src if self._isWorkVolume(src) else None)
            try: found, how = self._findSourceFor(w) if w is not None else (None, "作業用の画像もない")
            except Exception as e: found, how = None, f"探し直しに失敗: {e}"
            if found is not None:
                self.sourceVolume = src = found; print(f"[CardiacView 点検] VR: 元の CT を探し直しました: {src.GetName()}（{how}）")
            elif w is not None:
                src = w; print(f"[CardiacView 点検] VR: 元の CT が無いので作業用の画像「{w.GetName()}」で VR を作ります（{how}）")
        seg = self._findSegmentation(); hc = self._findChambers()
        if src is None or seg is None:
            miss = (["元の CT"] if src is None else []) + (["AI の全身ラベル"] if seg is None else [])
            raise RuntimeError(f"VR に必要な {'・'.join(miss)} が見つかりません。上の青いボタンで 3D を作り直してください（症例ファイルに入っていない可能性があります）")
        status("VR を準備中（心臓まわりの切り出し・色分け）…")
        vkeys = ("atrial appendage", "aorta", "pulmonary vein", "vena cava", "pulmonary artery", "brachiocephalic trunk")
        region = self._segmentMaskArray(seg, src, vkeys)
        h2 = self._segmentMaskArray(hc, src, ("ventricle", "atrium", "aorta", "pulmonary artery", "myocardium")) if hc is not None else None
        if h2 is None: h2 = self._segmentMaskArray(seg, src, ("heart",))     # 心腔ラベルが無いときだけ全身ラベル（3mm）
        if h2 is not None: region = h2 if region is None else (region | h2)
        if region is None or region.sum() < 1000: raise RuntimeError("心臓のラベルがありません")
        sp = np.array(src.GetSpacing())[::-1]                       # (z, y, x) mm
        rr = [np.nonzero(region.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
        m = np.ceil(10.0 / sp).astype(int)
        lo = np.maximum(np.array([q.min() for q in rr]) - m, 0); hi = np.minimum(np.array([q.max() for q in rr]) + m + 1, region.shape)
        crop = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi)); full = tuple(int(b - a) for a, b in zip(lo, hi))
        # 重い計算（距離・ぼかし）は 2 倍粗い格子で行う。弱い GPU（ds=2）はその格子のまま VR にする（細かくしてから粗くする無駄をしない）
        ds = self._vrDownFactor()
        if ds == 1 and float(np.prod(full)) > 30e6: ds = 2          # 細かすぎる CT（0.3mm 級）をそのまま VR にすると GPU/メモリが足りず落ちる（実測）→ 0.6〜0.8mm で十分
        self.vrDownUsed = ds
        step = 2; gsp = sp * step
        cs = tuple(slice(int(a), int(b), step) for a, b in zip(lo, hi))
        grid, gshape = self._gridNode(src, lo, hi, step)
        try:
            status("VR を準備中（縁をなめらかに）…")
            # 切り出しの縁は「ばっさり」ではなく 3mm かけて薄くする（縁が段々・細かい線にならない）
            rs = ndimage.gaussian_filter(region[cs].astype(np.float32), 2.5 / gsp) > 0.5   # ラベルの段々（スライス方向）を丸める
            del region
            dreg = ndimage.distance_transform_edt(~rs, sampling=gsp)
            wgt = np.clip((8.0 - dreg) / 3.0, 0.0, 1.0).astype(np.float32)    # 5mm までは 1、8mm で 0（ゆっくり消す）
            wgt = ndimage.gaussian_filter(wgt, 1.0 / gsp)
            del dreg, rs
            bone = self._boneMaskArray(seg, grid)
            if bone is not None and bone.any():
                db = ndimage.distance_transform_edt(~bone, sampling=gsp)
                wgt *= np.clip((db - 1.0) / 2.0, 0.0, 1.0); del db               # 骨の 1〜3mm でなめらかに消す
            del bone
            # ---- 部屋ラベル（粗い格子）
            status("VR を準備中（部屋の色分け）…")
            lab = np.zeros(gshape, np.int8)
            for gi, (which, gkeys, col, side) in enumerate(self.VR_GROUPS, start=1):
                node = hc if which == "hc" else seg
                if node is None: continue
                mk = self._segmentMaskArray(node, grid, gkeys)
                if mk is not None: lab[(lab == 0) & mk] = gi
            self._vrSeptIdx = None
            if getattr(self, "VR_SEPTUM", None) is not None and hc is not None:   # 中隔（右室に接する側から 10 mm までの心筋）を別の色に
                myoM = self._segmentMaskArray(hc, grid, ("myocardium",)); rvM = self._segmentMaskArray(hc, grid, ("right ventricle",))
                if myoM is not None and rvM is not None and rvM.any():
                    dRV = ndimage.distance_transform_edt(~rvM, sampling=gsp); sept = myoM & (dRV < 10.0); del dRV
                    if sept.sum() > 50: self._vrSeptIdx = len(self.VR_GROUPS) + 1; lab[sept] = self._vrSeptIdx
                del myoM, rvM
        finally:
            slicer.mrmlScene.RemoveNode(grid)
        c = dict(self._cal())
        if "myo" not in c or "blood" not in c:                   # 古い症例など: 心筋・血液の CT 値をラベルから測る
            try:
                hu0 = slicer.util.arrayFromVolume(src)[crop]
                g2, _ = self._gridNode(src, lo, hi, 1)
                def med(node, keys):
                    mk = self._segmentMaskArray(node, g2, keys) if node is not None else None
                    if mk is None or mk.sum() < 200: return None
                    from scipy import ndimage as _nd
                    mk2 = _nd.binary_erosion(mk, iterations=1); mk = mk2 if mk2.sum() > 100 else mk
                    return float(np.median(hu0[mk]))
                vm = med(hc, ("myocardium",)); vb = med(hc, ("left ventricle",)) or med(seg, ("aorta",)); vr = med(hc, ("right ventricle",))
                slicer.mrmlScene.RemoveNode(g2)
                if vm is not None: c["myo"] = vm
                if vb is not None: c["blood"] = vb
                if vr is not None: c["rv"] = vr
                if "fat" not in c: c["fat"] = -80.0
                self._calVR = c; print("VR 用に CT 値を測定:", {k: round(v) for k, v in c.items() if isinstance(v, float)})
            except Exception as e: print("VR calib:", e)
        myo = float(c.get("myo", 80.0)); bL = float(c.get("blood", 350.0)); bR = float(c.get("rv", bL))
        bR = max(bR, myo + 25.0)
        cols = np.array([self.VR_NEUTRAL] + [g[2] for g in self.VR_GROUPS] + ([self.VR_SEPTUM] if getattr(self, "_vrSeptIdx", None) else []), np.float32)
        isR = np.array([False] + [g[3] == "R" for g in self.VR_GROUPS] + ([False] if getattr(self, "_vrSeptIdx", None) else []))
        if (lab > 0).any():
            dist, ind = ndimage.distance_transform_edt(lab == 0, sampling=gsp, return_indices=True)
            near = lab[tuple(ind)]; near[dist > 15.0] = 0; del dist, ind
        else:
            near = lab
        rgb = cols[near]                                              # (z, y, x, 3)
        for k in range(3): rgb[..., k] = ndimage.gaussian_filter(rgb[..., k], 1.5 / gsp)   # 境目をぼかす
        try: self._applyVRTints(rgb, src, lo, step)                       # 部屋の色の上に、決めた範囲（パッチなど）を別の色で塗る（ぼかした後: 白が薄まらないように）
        except Exception as e: print("VR tint:", e)
        bloc = np.where(isR[near], bR, bL).astype(np.float32)
        bloc = ndimage.gaussian_filter(bloc, 4.0 / gsp)               # 左右の目盛りを 4mm かけてつなぐ
        del near, lab
        status("VR を準備中（造影の目盛り）…")
        s0 = float(getattr(self, "vrSigma", 0.7))
        sig_mm = np.array([max(s0, 0.4 * sp[0]), s0, s0])                  # スライスが厚いほど z を強めにならす（5mm → 2mm）
        hu = slicer.util.arrayFromVolume(src)[crop].astype(np.float32)
        hu = ndimage.gaussian_filter(hu, sigma=sig_mm / sp)                 # ノイズ（細かい線・ザラつき）と段差を抑える（細かい格子で＝折り返しが出ない）
        if ds == step:
            hu = hu[::step, ::step, ::step]                                # 粗い格子のまま使う
            if hu.shape != rgb.shape[:3]: hu = hu[:rgb.shape[0], :rgb.shape[1], :rgb.shape[2]]
        else:
            ds = 1; self.vrDownUsed = 1
            def up2(a):                                                    # 2 倍に直線補間（scipy の zoom より 10 倍速く、メモリも少ない）
                for ax in range(3):
                    n = a.shape[ax]
                    b = np.empty(a.shape[:ax] + (2 * n,) + a.shape[ax + 1:], np.float32)
                    i0 = [slice(None)] * 3; i1 = [slice(None)] * 3; i0[ax] = slice(0, None, 2); i1[ax] = slice(1, None, 2)
                    b[tuple(i0)] = a
                    lo_ = [slice(None)] * 3; hi_ = [slice(None)] * 3; lo_[ax] = slice(0, n - 1); hi_[ax] = slice(1, n)
                    o1 = [slice(None)] * 3; o1[ax] = slice(1, 2 * n - 2, 2)
                    b[tuple(o1)] = (a[tuple(lo_)] + a[tuple(hi_)]) * 0.5
                    last = [slice(None)] * 3; last[ax] = slice(2 * n - 1, 2 * n); src_ = [slice(None)] * 3; src_[ax] = slice(n - 1, n)
                    b[tuple(last)] = a[tuple(src_)]
                    a = b; del b
                return a[:full[0], :full[1], :full[2]]
            out = np.empty(full + (4,), np.uint8)
            for k in range(3):                                             # 色は 1 色ずつ（大きな配列を同時に持たない）
                out[..., k] = np.clip(up2(rgb[..., k]) * 255.0, 0, 255).astype(np.uint8)
            del rgb
            bloc = up2(bloc); wgt = up2(wgt)
            t = (hu - myo) / np.maximum(bloc - myo, 25.0); del hu, bloc
            t = np.clip(100.0 + 100.0 * t, 0, 255); t *= wgt; del wgt   # 縁では値を下げて透明へ（なめらか）
            out[..., 3] = t.astype(np.uint8); del t
        if ds == step:
            t = (hu - myo) / np.maximum(bloc - myo, 25.0)
            v = np.clip(100.0 + 100.0 * t, 0, 255) * wgt                     # 縁では値を下げて透明へ（なめらか）
            out = np.empty(hu.shape + (4,), np.uint8)
            out[..., :3] = np.clip(rgb * 255.0, 0, 255).astype(np.uint8); out[..., 3] = v.astype(np.uint8)
            del hu, t, v, rgb, bloc, wgt
        pale = getattr(self, "VR_PALE", None)
        if pale:                                                          # 心筋の濃さ（目盛り 100〜105）は部屋の色を淡く、135 から上（血液の面）は部屋の色のまま。間はなめらかに（作る時に 1 回だけ）
            for z0 in range(0, out.shape[0], 24):
                sl = out[z0:z0 + 24]; w = np.clip((sl[..., 3].astype(np.float32) - 105.0) / 30.0, 0.0, 1.0); w = w * w * (3.0 - 2.0 * w)
                f = float(pale) * (1.0 - w)
                for k in range(3):
                    c = sl[..., k].astype(np.float32); sl[..., k] = (c + (255.0 - c) * f).astype(np.uint8)
                del sl, w, f
        for hit, col in getattr(self, "_vrTintHits", None) or []:            # パッチなど: 淡くする前の色のまま（切り口もこの色）
            try:
                if hit.shape != out.shape[:3]:                                    # 細かい格子（2 倍）にした時
                    hit = np.repeat(np.repeat(np.repeat(hit, 2, 0), 2, 1), 2, 2)[:out.shape[0], :out.shape[1], :out.shape[2]]
                out[hit, :3] = np.clip(col * 255.0, 0, 255).astype(np.uint8)
            except Exception as e: print("VR tint2:", e)
        self._vrTintHits = []
        spz = sp[0] * ds
        zf = int(round(sp[0] / (1.0 * ds))) if sp[0] > 1.5 else 1      # 厚いスライス（2〜5mm）は z を 1mm（粗い格子は 2mm）に曲線補間（板状の段差を消す）
        if zf > 1:
            nz = out.shape[0]
            vz = ndimage.zoom(out[..., 3].astype(np.float32), (zf, 1, 1), order=3)
            rgbz = ndimage.zoom(out[..., :3], (zf, 1, 1, 1), order=1)
            out = np.concatenate([rgbz, np.clip(vz, 0, 255).astype(np.uint8)[..., None]], axis=-1); del vz, rgbz
            zscale = (nz - 1) / max(out.shape[0] - 1, 1)                  # 新しい z 間隔 = 元 × zscale
        else:
            zscale = 1.0
        node = slicer.mrmlScene.GetFirstNodeByName("CV VR")
        if node is not None and not node.IsA("vtkMRMLVectorVolumeNode"):
            slicer.mrmlScene.RemoveNode(node); node = None
        if node is None:
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "CV VR"); self._put(node)
        slicer.util.updateVolumeFromArray(node, out)
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M)
        o = [sum(M.GetElement(r, cc) * vv for cc, vv in enumerate((lo[2], lo[1], lo[0], 1))) for r in range(3)]
        for r in range(3): M.SetElement(r, 3, o[r]); M.SetElement(r, 2, M.GetElement(r, 2) * zscale)
        if ds > 1:
            for r in range(3):
                for cc in range(3): M.SetElement(r, cc, M.GetElement(r, cc) * ds)
        node.SetIJKToRASMatrix(M)
        vrl = slicer.modules.volumerendering.logic()
        dn = vrl.GetFirstVolumeRenderingDisplayNode(node) or vrl.CreateDefaultVolumeRenderingNodes(node)
        dn.SetVisibility(False)
        try:
            vn = self._viewNode()
            # 最初は安全な「標準」画質（弱い GPU で最高画質をいきなり描くと 2 秒を超えて Windows が GPU をリセットし、強制終了になる）
            vn.SetVolumeRenderingQuality(1)
            vn.SetVolumeRenderingOversamplingFactor(1.0); vn.SetVolumeRenderingSurfaceSmoothing(True)
        except Exception as e: print("VR quality:", e)
        try:
            # VR の切断は GPU の「切り取り面」で行う。Slicer 標準の切り取り（ClipNode）は面を動かすたびに
            # ボリューム全体を CPU で塗りつぶして GPU に送り直すので、1 コマ 0.7 秒（開発 PC）〜数秒かかっていた
            dn.SetClipping(False)
        except Exception as e: print("VR clip:", e)
        self._installVRClip()
        self.vrNode, self.vrDisplay = node, dn
        self.vrScale = (myo, bL)                                     # 表示用: 目盛り → 左心系の HU 相当
        try:                                                         # 何から作った VR か（症例を開いた時、同じならそのまま使う）
            node.SetAttribute("CV.vrSig", self._vrSig()); node.SetAttribute("CV.vrScale", f"{myo:.2f},{bL:.2f}"); node.SetAttribute("CV.vrDown", str(int(ds)))
        except Exception as e: print("VR sig:", e)
        if getattr(self, "vrMode", None) is None: self.vrMode = "tissue"
        self.vrWin = None
        self.setVRWindow()
        status("VR の準備ができました")
        return dn

    VR_CACHE_VER = "1"

    def _syncVRPalette(self):
        """VR の色を今の色合い（リアル など）に。作り直したばかりのロジック（新しい症例を作った直後）は既定の色のままなので"""
        p = PALETTES.get(common.CUR_PALETTE) or PALETTES["リアル"]
        self.VR_GROUPS = [(g[0], g[1], c, g[3]) for g, c in zip(type(self).VR_GROUPS, p["vr"])]
        self.VR_NEUTRAL = p["vrN"]; self.VR_PALE = p.get("vrPale"); self.VR_SEPTUM = p.get("vrSeptum")

    def _vrSig(self):
        """VR の色の元（CT・色合い・パッチの色と形・格子の粗さ）。同じなら保存した VR をそのまま使える"""
        import hashlib
        self._syncVRPalette()
        src = getattr(self, "sourceVolume", None)
        dims = src.GetImageData().GetDimensions() if src is not None and src.GetImageData() is not None else None
        parts = [self.VR_CACHE_VER, src.GetName() if src is not None else "", str(dims),
                 repr([tuple(round(float(x), 3) for x in g[2]) for g in self.VR_GROUPS]), repr(getattr(self, "VR_NEUTRAL", None)),
                 repr(getattr(self, "VR_PALE", None)), repr(getattr(self, "VR_SEPTUM", None)), f"{float(getattr(self, 'vrSigma', 0.7)):.2f}", str(self._vrDownFactor())]
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            tc = n.GetAttribute("CV.vrTint"); pd = n.GetPolyData()
            if tc and pd is not None and pd.GetNumberOfPoints():
                parts.append(f"{n.GetName()}|{tc}|{pd.GetNumberOfPoints()}|" + ",".join(f"{x:.1f}" for x in pd.GetBounds()))
        for t in getattr(self, "vrTints", None) or []:
            m = t.get("mask"); parts.append(f"mask|{int(m.sum()) if m is not None else 0}|{t.get('color')}")
        return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()

    def _reuseVR(self):
        """保存した症例の VR（CV VR）が今の CT・色合い・パッチと同じなら、作り直さずに使う（VR がすぐ出る。作り直しは約 9 秒）"""
        node = slicer.mrmlScene.GetFirstNodeByName("CV VR")
        if node is None or not node.IsA("vtkMRMLVectorVolumeNode") or node.GetImageData() is None: return False
        sc = (node.GetAttribute("CV.vrScale") or "").split(",")
        if len(sc) != 2 or node.GetAttribute("CV.vrSig") != self._vrSig(): return False
        vrl = slicer.modules.volumerendering.logic()
        dn = vrl.GetFirstVolumeRenderingDisplayNode(node) or vrl.CreateDefaultVolumeRenderingNodes(node)
        dn.SetVisibility(False); dn.SetClipping(False)
        try:
            vn = self._viewNode(); vn.SetVolumeRenderingQuality(1); vn.SetVolumeRenderingOversamplingFactor(1.0); vn.SetVolumeRenderingSurfaceSmoothing(True)
        except Exception as e: print("VR quality:", e)
        self._installVRClip()
        self.vrNode, self.vrDisplay = node, dn
        self.vrScale = (float(sc[0]), float(sc[1])); self.vrDownUsed = int(node.GetAttribute("CV.vrDown") or 1)
        if getattr(self, "vrMode", None) is None: self.vrMode = "tissue"
        self.vrWin = None
        self.setVRWindow()
        print("VR: 保存した VR をそのまま使いました")
        return True

    def _installVRClip(self):
        """3D 画面を描く直前に、切断面（と自由切断面）を VR の GPU 切り取り面へ写す（アプリ全体で 1 つ）"""
        try:
            rw = self._view().renderWindow()
            reg = getattr(slicer, "_cvVRClip", None)
            if reg and reg[0] is rw: return
            if reg:
                try: reg[0].RemoveObserver(reg[1])
                except Exception: pass
            def cb(c=None, e=None):
                L = _cvCur()
                if L is not None:
                    try: L._clipSync()
                    except Exception as ex: print("clip sync:", ex)
            slicer._cvVRClip = (rw, rw.AddObserver(vtk.vtkCommand.StartEvent, cb))
        except Exception as e: print("vr clip install:", e)

    def _activePlanes(self):
        """いま効いている切断面: [(中心, 残す側の法線)]"""
        planes = []
        clip = self.clip if (self.clip is not None and slicer.mrmlScene.IsNodePresent(self.clip)) else None
        if clip is None: return planes, None
        for i in range(clip.GetNumberOfClippingNodes()):
            nd = slicer.mrmlScene.GetNodeByID(clip.GetNthClippingNodeID(i))
            if nd is None or not hasattr(nd, "GetNormal"): continue
            st = clip.GetClippingNodeState(nd)
            if st == clip.ClipOff: continue
            c = [0.0, 0.0, 0.0]; n = [0.0, 0.0, 1.0]
            try: nd.GetOriginWorld(c)
            except Exception: c = list(nd.GetCenter())
            try: nd.GetNormalWorld(n)
            except Exception: n = list(nd.GetNormal())
            sgn = -1.0 if st == clip.ClipNegativeSpace else 1.0           # ClipNegativeSpace = 法線側を取り除く（実測）→ 残すのは逆側
            planes.append((tuple(round(x, 3) for x in c), tuple(round(sgn * x, 5) for x in n)))
        return planes, clip

    def _noPlanes(self):
        e = getattr(self, "_emptyPlanes", None)                  # 空の入れ物（None を渡すと vtk の引数が曖昧でエラーになる）
        if e is None: e = self._emptyPlanes = vtk.vtkPlaneCollection()
        return e

    def _planeColl(self, attr, planes):
        coll = getattr(self, attr, None)
        if coll is None: coll = vtk.vtkPlaneCollection(); setattr(self, attr, coll)
        key = tuple(planes)
        if getattr(self, attr + "Key", None) != key or coll.GetNumberOfItems() != len(planes):
            coll.RemoveAllItems()
            for c, n in planes:
                pl = vtk.vtkPlane(); pl.SetOrigin(*c); pl.SetNormal(*n); coll.AddItem(pl)
            setattr(self, attr + "Key", key)
        return coll

    def _clipSync(self):
        """切断面 1 枚の時は、VR も面も GPU の「切り取り面」で切る（面を動かしても CPU で作り直さない＝なめらか）。
        2 枚以上（自由切断面を足した時）は Slicer 標準（交わった所だけ切る）に任せる。切り口の蓋を塗るレイヤーも Slicer 標準"""
        planes, clip = self._activePlanes()
        gpu = len(planes) == 1
        # ---- VR
        dn = getattr(self, "vrDisplay", None)
        if dn is not None and getattr(self, "vrOn", False):
            m = self._vrMapper()
            if gpu or not planes:
                if dn.GetClipping(): dn.SetClipping(False)
                if m is not None:
                    if planes:
                        coll = self._planeColl("_vrPlanes", planes)
                        if m.GetClippingPlanes() is not coll: m.SetClippingPlanes(coll)
                    elif m.GetClippingPlanes() is not None and m.GetClippingPlanes().GetNumberOfItems(): m.SetClippingPlanes(self._noPlanes())
            else:
                if m is not None and m.GetClippingPlanes() is not None and m.GetClippingPlanes().GetNumberOfItems(): m.SetClippingPlanes(self._noPlanes())
                if clip is not None and not dn.GetClipping():
                    dn.SetAndObserveClipNodeID(clip.GetID()); dn.SetClipping(True)
        # ---- 4D の VR（1 枚なら GPU で切る）
        d4 = getattr(self, "vr4D", None)
        if d4 is not None and getattr(self, "on4D", False):
            m4 = self._mapperOf(d4)
            if gpu or not planes:
                if d4.GetClipping(): d4.SetClipping(False)
                if m4 is not None:
                    want = self._planeColl("_vr4Planes", planes) if planes else self._noPlanes()
                    if m4.GetClippingPlanes() is not want: m4.SetClippingPlanes(want)
            elif clip is not None:
                if m4 is not None: m4.SetClippingPlanes(self._noPlanes())
                if not d4.GetClipping(): d4.SetAndObserveClipNodeID(clip.GetID()); d4.SetClipping(True)
        # ---- 面のレイヤー
        try: dm = self._view().displayableManagerByClassName("vtkMRMLModelDisplayableManager")
        except Exception: dm = None
        coll = self._planeColl("_mdPlanes", planes) if gpu else None
        for n in list(self.layerModels.values()):
            d = n.GetDisplayNode() if n else None
            if d is None: continue
            want = d.GetAttribute("CV.clipWant") == "1" and bool(planes)                  # パッチも他の面と同じに切る（切らないと浮いて見える）
            useGpu = want and gpu and d.GetAttribute("CV.cap") != "1"
            slicerClip = want and not useGpu
            if bool(d.GetClipping()) != slicerClip: d.SetClipping(slicerClip)
            a = dm.GetActorByID(d.GetID()) if dm is not None else None
            mp = a.GetMapper() if a is not None else None
            if mp is None: continue
            if useGpu:
                if mp.GetClippingPlanes() is not coll: mp.SetClippingPlanes(coll)
            elif mp.GetClippingPlanes() is not None and mp.GetClippingPlanes().GetNumberOfItems():
                mp.SetClippingPlanes(self._noPlanes())

    def _vrDefaults(self, mode):
        c = getattr(self, "_calVR", None) or self._cal(); myo = float(c.get("myo", 80.0)); fat = float(c.get("fat", -80.0)); bL = float(c.get("blood", 350.0))
        vfat = 100.0 + 100.0 * (fat - myo) / max(bL - myo, 25.0)
        if mode == "blood": return 150.0, 40.0                        # 心筋と血液の中間から上を不透明に（立ち上がりを狭く＝面がくっきり）
        a = (vfat + 100.0) / 2.0; b = 150.0                           # 脂肪と心筋の中間 〜 心筋と血液の中間
        return (a + b) / 2.0, b - a

    def _vrHU(self, v):
        myo, bL = getattr(self, "vrScale", (80.0, 350.0))
        return myo + (v - 100.0) / 100.0 * (bL - myo)

    def resetWindow(self):
        """ウィンドウを最初の値に戻す: VR は部屋ごとの標準、断面は心臓用（脂肪〜造影血液が見える幅）"""
        if getattr(self, "vrDisplay", None) is not None:
            self.vrWin = None; self.setVRWindow()
        if getattr(self, "on4D", False):
            self.win4DMap = {}; self._tf4D()
            try:
                d = self.proxy4D.GetDisplayNode(); c = self._cal(); lo = float(c.get("fat", -80)) - 60; hi = float(c.get("blood", 350)) + 250
                d.SetAutoWindowLevel(False); d.SetWindowLevel(hi - lo, (hi + lo) / 2)
            except Exception: pass
        src = getattr(self, "sourceVolume", None)
        d = src.GetDisplayNode() if src is not None else None
        if d is not None:
            try:
                c = self._cal(); lo = float(c.get("fat", -80)) - 60; hi = float(c.get("blood", 350)) + 250
                d.SetAutoWindowLevel(False); d.SetWindowLevel(hi - lo, (hi + lo) / 2)
            except Exception: d.SetAutoWindowLevel(True)
        try: self._vrLabel()
        except Exception: pass
        self._view().scheduleRender()

    def setVRWindow(self, center=None, width=None):
        dn = getattr(self, "vrDisplay", None)
        if dn is None: return
        mode = getattr(self, "vrMode", "tissue")
        if self.vrWin is None: self.vrWin = self._vrDefaults(mode)
        c0, w0 = self.vrWin
        c0 = c0 if center is None else float(center); w0 = max(6.0, w0 if width is None else float(width))
        self.vrWin = (c0, w0)
        vp = dn.GetVolumePropertyNode().GetVolumeProperty()
        a, b = c0 - w0 / 2, c0 + w0 / 2; e = max(3.0, 0.15 * w0)
        if mode == "blood": pts = [(0, 0), (max(1, a), 0), (min(254, b), 0.85), (255, 0.9)]
        else: pts = [(0, 0), (max(1, a - e), 0), (a + e, 0.8), (b - e, 0.8), (min(254, b + e), 0), (255, 0)]
        xs = []                                                   # x が重なると点が減るので、必ず少しずつ増やす
        for x, y in pts: xs.append(max(float(x), xs[-1] + 0.01) if xs else float(x))
        pts = [(x, y) for x, (_, y) in zip(xs, pts)]
        otf = vp.GetScalarOpacity()
        if getattr(self, "_vrOtfProp", None) is vp and getattr(self, "_vrOtfMode", None) == mode and otf is not None and otf.GetSize() == len(pts):
            # ドラッグ中は今ある関数の点だけ動かす（作り直すと描画のしくみごと作り直しになり 3 倍重い）
            for _ in range(3):                                          # 点は並べ替えられるので、狙いどおりになるまで（大きく動かした時も）2〜3 回で揃う
                for i, (x, y) in enumerate(pts): otf.SetNodeValue(i, [x, y, 0.5, 0.0])
                cur = []
                for i in range(otf.GetSize()):
                    v_ = [0.0] * 4; otf.GetNodeValue(i, v_); cur.append((v_[0], v_[1]))
                if all(abs(a_[0] - b_[0]) < 1e-3 and abs(a_[1] - b_[1]) < 1e-3 for a_, b_ in zip(cur, pts)): break
        else:
            vp.IndependentComponentsOff()
            otf = vtk.vtkPiecewiseFunction()
            for x, y in pts: otf.AddPoint(x, y)
            vp.SetScalarOpacity(otf)
            vp.ShadeOn(); vp.SetInterpolationTypeToLinear()
            sh = self._shade(); vp.SetAmbient(sh["vamb"]); vp.SetDiffuse(sh["vdif"]); vp.SetSpecular(sh["vspec"]); vp.SetSpecularPower(30)   # 陰影の設定どおり
            vp.SetScalarOpacityUnitDistance(0.5 if mode == "blood" else 1.0)   # 造影: もやを減らして面をくっきり。心内: 半透明のまま（中の心筋・弁・乳頭筋が透けて見えるように）
            self._vrOtfProp, self._vrOtfMode = vp, mode
        self._vrLabel()

    def _vrLabel(self):
        if getattr(self, "on4D", False): return                               # 4D の時は 4D のウィンドウを出している
        try:
            v = self._view(); ca = v.cornerAnnotation()
            if getattr(self, "vrOn", False) and self.vrWin is not None:
                c0, w0 = self.vrWin
                lo, hi = self._vrHU(c0 - w0 / 2), self._vrHU(c0 + w0 / 2)
                self._setUR(f"<b>VR</b>　W {hi - lo:.0f} / L {(lo + hi) / 2:.0f}\n<span style='color:#9aa3ad'>{lo:.0f} – {hi:.0f} HU</span>")
            else: self._setUR("")
            ca.GetTextProperty().SetColor(1, 0.9, 0.5); v.scheduleRender()
        except Exception: pass

    VR_KEEP = ("パッチ",)                                                  # VR の中でも面で出すもの（VR は CT 値で透けるので、薄い布が見えなくなる）

    def _layerShown(self, k):
        """層 k の面を今の画面に出すか。self.visible（層のチェック）と VR・4D の状態から決める（面をどこで作り直しても同じ決まりで出す）。
        4D の途中は動かない面（STATIC_4D）だけ。VR の途中は VR_KEEP と、VR の途中で先生がチェックを入れた層（_vrExtra）だけ（VR が面に隠れないように）"""
        if not self.visible.get(k, False): return False
        if getattr(self, "on4D", False): return k in self.STATIC_4D
        if getattr(self, "vrOn", False): return k in self.VR_KEEP or k in (getattr(self, "_vrExtra", None) or ())
        return True

    def _applyLayerVis(self):
        """面の出し方を「今の層の選び方」（self.visible）と VR の状態に合わせる（_layerShown）。
        前は VR を消した時に「VR を出した時の控え」に戻していたので、VR の途中で層のチェックを変えると、画面とチェックが食い違った"""
        vr = bool(getattr(self, "vrOn", False))
        for k, n in self.layerModels.items():
            if n and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(self._layerShown(k))
        if vr:
            cap = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
            if cap and cap.GetDisplayNode(): cap.GetDisplayNode().SetVisibility(False)
        else: self.updateMyoCap()

    def showVR(self, on, mode=None):
        first = on and getattr(self, "vrDisplay", None) is None
        if first:                                                             # 初めての VR で Slicer がカメラを戻してしまうので、今の向き・大きさを保つ
            c = self._camera(); st = (c.GetPosition(), c.GetFocalPoint(), c.GetViewUp(), c.GetParallelScale())
            reused = False
            try: reused = self._reuseVR()
            except Exception as e: print("VR reuse:", e)
            if not reused: self.setupVR()
            gen0 = getattr(self, "_camGen", 0)
            def _back(c=c, st=st, gen0=gen0):
                if getattr(self, "_camGen", 0) != gen0: return                # その間に向きを変えた（パッチの正面など）ならそのまま
                try: c.SetPosition(*st[0]); c.SetFocalPoint(*st[1]); c.SetViewUp(*st[2]); c.SetParallelScale(st[3]); c.ResetClippingRange()
                except Exception: pass
            _back(); qt.QTimer.singleShot(0, _back); qt.QTimer.singleShot(150, _back)
        if mode is not None and mode != getattr(self, "vrMode", None):
            self.vrMode = mode; self.vrWin = None; self.setVRWindow()
        if not (on and getattr(self, "vrOn", False)): self._vrExtra = set()   # VR を消す時・新しく出す時は「VR の途中で出した層」を忘れる（VR の色の切り替えでは覚えたまま）
        self.vrOn = bool(on)
        d4 = bool(getattr(self, "on4D", False))                              # 4D の途中は、動く VR が画面を持つ。ここでは「VR を出したいか」だけ覚えて、4D を終えた時（show4D）に合わせる
        if getattr(self, "vrDisplay", None) is not None: self.vrDisplay.SetVisibility(self.vrOn and not d4)
        if not d4: self._applyLayerVis()
        try:
            ren = self._view().renderWindow().GetRenderers().GetFirstRenderer(); vs = ren.GetVolumes(); vs.InitTraversal()
            for _ in range(vs.GetNumberOfItems()): vs.GetNextVolume().GetMapper().SetUseJittering(True)   # OFF だと木目状の細かい線が出る
        except Exception: pass
        try: self._applyVRShade()
        except Exception as e: print("VR shade:", e)
        if on and not d4 and (first or getattr(self, "vrStillQ", None) is None):
            try: self._tuneVR()
            except Exception as e: print("tuneVR:", e)
        self.installMouse(); self._installPerfMon(); self._vrLabel(); self._view().forceRender()

    def _mapperOf(self, dn):
        """その VR 表示の GPU マッパー（4D 表示中は、見えている VR が 4D のもの）"""
        try:
            dm = self._view().displayableManagerByClassName("vtkMRMLVolumeRenderingDisplayableManager")
            a = dm.GetVolumeActor(dn) if hasattr(dm, "GetVolumeActor") else None
            if a is not None and a.GetMapper() is not None: return a.GetMapper()
        except Exception: pass
        try:
            ren = self._view().renderWindow().GetRenderers().GetFirstRenderer(); vs = ren.GetVolumes(); vs.InitTraversal()
            dims = tuple(self.proxy4D.GetImageData().GetDimensions()) if getattr(self, "proxy4D", None) is not None else None
            for _ in range(vs.GetNumberOfItems()):
                v = vs.GetNextVolume(); m = v.GetMapper()
                if m is None or not v.GetVisibility(): continue
                try:
                    inp = m.GetInput()
                    if dims is not None and inp is not None and tuple(inp.GetDimensions()) != dims: continue
                except Exception: pass
                return m
        except Exception: pass
        return None

    def _vrMapper(self):
        try:
            ren = self._view().renderWindow().GetRenderers().GetFirstRenderer(); vs = ren.GetVolumes(); vs.InitTraversal()
            for _ in range(vs.GetNumberOfItems()):
                m = vs.GetNextVolume().GetMapper()
                if m is not None and m.IsA("vtkGPUVolumeRayCastMapper"): return m
        except Exception: pass
        return None

    def _vrFast(self, fast=True):
        """VR は動かしている間だけ「描く点を粗く」（解像度だけ下げる）、止まったら細かく。
        自動画質（Adaptive）は動かす時と止まった時で光の通り方が変わって、離した瞬間に暗く見えるので使わない"""
        if not getattr(self, "vrOn", False) or not self._mine(): return
        vn = self._viewNode(); still = max(1, int(getattr(self, "vrStillQ", None) or 1))
        q = 1 if fast else still
        if vn.GetVolumeRenderingQuality() != q: vn.SetVolumeRenderingQuality(q)
        m = self._vrMapper()
        if m is not None:
            isd = float(getattr(self, "vrFastISD", 1.5) or 1.5) if fast else 1.0
            if m.GetAutoAdjustSampleDistances(): m.AutoAdjustSampleDistancesOff()
            if abs(m.GetImageSampleDistance() - isd) > 1e-3: m.SetImageSampleDistance(isd)

    def _vrSettle(self):
        if not getattr(self, "vrOn", False): return
        t = getattr(self, "_vrTimer", None)
        if t is None:
            t = self._vrTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(300)
            t.connect("timeout()", lambda: (self._vrFast(False), self._view().scheduleRender()))
        t.start()
