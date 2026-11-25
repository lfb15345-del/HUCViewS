# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 4D（動く心臓）: 読み込み・窓・色・再生・位相
CardiacViewLogic の一部（FourDMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class FourDMixin:
    # ================================================================ 4D（動く心臓）
    # 同じ撮影の各位相（心電図同期の 0〜95% など）を、心臓のまわりだけ切り出して少し粗くし、Sequence にして再生する。
    # 3D の面・色分け VR は 1 位相（3D を作った CT）のまま。4D では元の CT 値の VR と断面が動く。
    @staticmethod
    def _ramBytes():
        try:
            import psutil; return float(psutil.virtual_memory().total)
        except Exception: pass
        try:
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("t", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong),
                            ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return float(m.t)
        except Exception: return 16e9

    def setup4D(self, phases, status=lambda m: None, budget=None):
        """phases: [(ラベル, ボリューム または 読み込む関数)]。関数なら 1 位相ずつ読み込んで、使い終わったら消す（メモリを食わない）。
        budget = 全位相合計のメモリ上限（バイト。既定は PC のメモリの 1/24、0.4〜1.6 GB）"""
        from scipy import ndimage
        if budget is None: budget = min(1.6e9, max(0.4e9, self._ramBytes() / 24.0))
        src = getattr(self, "sourceVolume", None); seg = self._findSegmentation(); hc = self._findChambers()
        if src is None or seg is None: raise RuntimeError("先に 3D を作ってください")
        if len(phases) < 2: raise RuntimeError("位相が 1 つしかありません")
        self.clear4D()
        status(f"4D（{len(phases)} 位相）を準備中: 心臓の範囲…")
        region = self._segmentMaskArray(hc, src, ("ventricle", "atrium", "aorta", "pulmonary artery", "myocardium")) if hc is not None else None
        r2 = self._segmentMaskArray(seg, src, ("heart", "atrial appendage", "aorta", "pulmonary vein", "pulmonary artery", "superior vena cava"))
        if r2 is not None: region = r2 if region is None else (region | r2)
        if region is None or region.sum() < 1000: raise RuntimeError("心臓のラベルがありません")
        sp = np.array(src.GetSpacing())[::-1]                                     # (z, y, x) mm
        rr = [np.nonzero(region.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
        m = np.ceil(15.0 / sp).astype(int)                                        # 心臓は動くので 15 mm 余裕
        lo = np.maximum(np.array([q.min() for q in rr]) - m, 0); hi = np.minimum(np.array([q.max() for q in rr]) + m + 1, region.shape)
        f = np.maximum(1, np.round(0.55 / sp)).astype(int)                         # まず 0.5〜0.6 mm 程度に
        per = budget / len(phases) / 2.0
        while np.prod(np.ceil((hi - lo) / f)) > per:                              # メモリに収まるまで、いちばん細かい向きから粗く
            f[int(np.argmin(sp * f))] += 1
        hi = lo + ((hi - lo) // f) * f
        crop = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi)); shp = tuple(int(x) for x in (hi - lo) // f)
        def pool(a):
            a = a[crop].reshape(shp[0], f[0], shp[1], f[1], shp[2], f[2])
            return a.mean(axis=(1, 3, 5), dtype=np.float32)
        # 心臓の外を消す重み（骨は 1〜3 mm で消す）
        gsp = sp * f
        rs = pool(region.astype(np.float32)) > 0.3; del region
        d = ndimage.distance_transform_edt(~rs, sampling=gsp)
        wgt = np.clip((11.0 - d) / 4.0, 0.0, 1.0).astype(np.float32); del d, rs      # ラベル + 7 mm は残し、11 mm で消す（動く分の余裕）
        bone = self._boneMaskArray(seg, src)
        if bone is not None and bone.any():
            bp = pool(bone.astype(np.float32)) > 0.3; del bone
            if bp.any(): wgt *= np.clip((ndimage.distance_transform_edt(~bp, sampling=gsp) - 1.0) / 2.0, 0.0, 1.0).astype(np.float32)
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M); A = slicer.util.arrayFromVTKMatrix(M)
        fx = f[::-1].astype(float); o = lo[::-1] + (fx - 1) / 2.0                      # (i, j, k) の順
        A2 = A.copy(); A2[:3, :3] = A[:3, :3] * fx[None, :]; A2[:3, 3] = (A @ np.r_[o, 1.0])[:3]
        M2 = slicer.util.vtkMatrixFromArray(A2)
        seq = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "CV 4D 位相")
        seq.SetIndexName("phase"); seq.SetIndexUnit(""); seq.SetIndexType(seq.NumericIndex)
        labels = []
        for i, (lab, vol) in enumerate(phases):
            status(f"4D を準備中: 位相 {i + 1}/{len(phases)}（{lab}）…")
            tmp = None; loaded = None; arr = None
            if callable(vol): vol = loaded = vol()
            if isinstance(vol, np.ndarray):                                   # 配列で渡された（3D を作った CT と同じ格子）
                arr, vol, loaded = vol, src, None
            same = (vol.GetImageData() is not None and tuple(vol.GetImageData().GetDimensions()) == tuple(src.GetImageData().GetDimensions())
                    and np.allclose(vol.GetSpacing(), src.GetSpacing(), atol=1e-3) and np.allclose(vol.GetOrigin(), src.GetOrigin(), atol=1e-2))
            if not same:
                tmp = slicer.modules.volumes.logic().ResampleVolumeToReferenceVolume(vol, src); vol = tmp
            a = pool(arr if arr is not None else slicer.util.arrayFromVolume(vol)); arr = None
            out = np.clip(-1024.0 + (a + 1024.0) * wgt, -1024, 3071).astype(np.int16); del a
            if tmp is not None: slicer.mrmlScene.RemoveNode(tmp)
            if loaded is not None and loaded is not src: slicer.mrmlScene.RemoveNode(loaded)
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", f"CV 4D {lab}")
            node.SetIJKToRASMatrix(M2); slicer.util.updateVolumeFromArray(node, out)
            seq.SetDataNodeAtValue(node, str(i)); slicer.mrmlScene.RemoveNode(node); labels.append(str(lab))
            slicer.app.processEvents()
        seq.SetAttribute("CV.4D.labels", "|".join(labels))
        br = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "CV 4D 再生")
        br.SetAndObserveMasterSequenceNodeID(seq.GetID()); br.SetPlaybackLooped(True); br.SetPlaybackRateFps(8.0)
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(br)
        proxy = br.GetProxyNode(seq); proxy.SetName("CV 4D")
        proxy.CreateDefaultDisplayNodes()
        self._adopt4D(br)
        self.vr4D.SetVisibility(False)
        status(f"4D（{len(phases)} 位相・{gsp[2]:.2f}×{gsp[1]:.2f}×{gsp[0]:.2f} mm）の準備ができました")
        return len(phases)

    def _adopt4D(self, br=None):
        """4D の部品（再生・位相・表示）を引き継ぐ。保存した症例を開いた時も"""
        br = br or slicer.mrmlScene.GetFirstNodeByName("CV 4D 再生")
        if br is None or not br.IsA("vtkMRMLSequenceBrowserNode"):
            self.br4D = self.seq4D = self.proxy4D = self.vr4D = None; return False
        self.br4D = br; self.seq4D = br.GetMasterSequenceNode(); self.proxy4D = br.GetProxyNode(self.seq4D)
        self._hideInternalVolumes()
        self.labels4D = (self.seq4D.GetAttribute("CV.4D.labels") or "").split("|")
        vrl = slicer.modules.volumerendering.logic()
        dn = vrl.GetFirstVolumeRenderingDisplayNode(self.proxy4D)
        if dn is None:
            c = self._camera(); st = (c.GetPosition(), c.GetFocalPoint(), c.GetViewUp(), c.GetParallelScale())   # Slicer がカメラを戻さないように
            dn = vrl.CreateDefaultVolumeRenderingNodes(self.proxy4D)
            def _back(c=c, st=st):
                try: c.SetPosition(*st[0]); c.SetFocalPoint(*st[1]); c.SetViewUp(*st[2]); c.SetParallelScale(st[3]); c.ResetClippingRange()
                except Exception: pass
            _back(); qt.QTimer.singleShot(0, _back); qt.QTimer.singleShot(150, _back)
        dn.RemoveAllViewNodeIDs(); dn.AddViewNodeID(self._viewNode().GetID())
        self.vr4D = dn; self._tf4D()
        try: slicer.modules.sequences.setToolBarVisible(False)                # 再生は CardiacView の欄で（Slicer 標準の再生バーは出さない）
        except Exception: pass
        return True

    def _base4D(self, mode):
        """4D の VR の標準の範囲（HU）。blood: 心筋の少し下〜造影血液の上、tissue: 心筋の少し下〜心筋と血液の中間"""
        c = self._cal(); myo = float(c.get("myo", 80.0)); bl = float(c.get("blood", 350.0)); mid = (myo + bl) / 2
        return (myo - 60, mid + 15) if mode == "tissue" else (myo - 50, bl + 150)

    def _win4D(self):
        mode = getattr(self, "mode4D", "blood"); w = (getattr(self, "win4DMap", None) or {}).get(mode)
        if w is None:
            lo, hi = self._base4D(mode); w = ((lo + hi) / 2, hi - lo)
        return w

    def set4DWindow(self, center=None, width=None):
        mode = getattr(self, "mode4D", "blood"); c0, w0 = self._win4D()
        c0 = c0 if center is None else float(center); w0 = max(20.0, w0 if width is None else float(width))
        self.win4DMap = dict(getattr(self, "win4DMap", None) or {}); self.win4DMap[mode] = (c0, w0)
        self._tf4D()

    def _tf4D(self, mode=None):
        """4D の VR の色と透明度。blood: 心筋は赤、造影された血液は明るい肌色（外から見た形・内腔）。
        tissue: 造影された血液を透明にして、弁・乳頭筋・壁の動きを見る。脂肪・肺はどちらも透明。
        ウィンドウ（右ドラッグ「ウィンドウ」や左右同時ドラッグ）で範囲をずらす・広げる"""
        if mode is not None: self.mode4D = mode
        mode = getattr(self, "mode4D", "blood")
        b0, b1 = self._base4D(mode); c0, w0 = self._win4D(); lo, hi = c0 - w0 / 2, c0 + w0 / 2
        X = lambda t: lo + (t - b0) / max(b1 - b0, 1.0) * (hi - lo)               # 標準の範囲 → 今のウィンドウ
        c = self._cal(); myo = float(c.get("myo", 80.0)); bl = float(c.get("blood", 350.0)); mid = (myo + bl) / 2
        vp = self.vr4D.GetVolumePropertyNode().GetVolumeProperty()
        if mode == "tissue":
            pts = [(-1024, 0), (X(myo - 60), 0), (X(myo), 0.55), (X(mid - 25), 0.75), (X(mid + 15), 0), (max(X(mid + 15) + 1, bl + 400), 0), (max(X(mid + 15) + 2, bl + 401), 0.6), (3071, 0.8)]
        else:
            pts = [(-1024, 0), (X(myo - 50), 0), (X(myo + 10), 0.25), (X(mid), 0.6), (X(bl + 150), 0.85), (3071, 0.9)]
        cols = [(-1024, (0, 0, 0)), (X(myo - 50), (0.45, 0.1, 0.08)), (X(myo + 10), (0.75, 0.3, 0.24)), (X(mid), (0.95, 0.6, 0.5)),
                (X(bl + 100), (1.0, 0.9, 0.82)), (max(X(bl + 100) + 1, 1500), (1, 1, 1)), (3071, (1, 1, 1))]
        def mono(p):                                                          # x が重なると点が減るので必ず少し増やす
            out = []
            for x, y in p: out.append((max(float(x), out[-1][0] + 0.01) if out else float(x), y))
            return out
        otf = vp.GetScalarOpacity(); ctf = vp.GetRGBTransferFunction()
        if otf is None or getattr(self, "_otf4D", None) is not otf:
            otf = vtk.vtkPiecewiseFunction(); ctf = vtk.vtkColorTransferFunction(); vp.SetScalarOpacity(otf); vp.SetColor(ctf)
            vp.ShadeOn(); vp.SetInterpolationTypeToLinear(); vp.SetAmbient(0.25); vp.SetDiffuse(0.8); vp.SetSpecular(0.3); vp.SetSpecularPower(20)
            self._otf4D = otf
        otf.RemoveAllPoints(); ctf.RemoveAllPoints()
        for x, y in mono(pts): otf.AddPoint(x, y)
        for x, col in mono(cols): ctf.AddRGBPoint(x, *col)
        try:
            if getattr(self, "on4D", False):
                self._setUR(f"<b>4D</b>　W {w0:.0f} / L {c0:.0f}\n<span style='color:#9aa3ad'>{lo:.0f} – {hi:.0f} HU</span>")
        except Exception: pass

    def set4DMode(self, mode):
        if getattr(self, "vr4D", None) is None: return
        self._tf4D(mode); self._view().scheduleRender()

    def has4D(self):
        return getattr(self, "br4D", None) is not None and slicer.mrmlScene.IsNodePresent(self.br4D)

    def n4D(self):
        return self.seq4D.GetNumberOfDataNodes() if self.has4D() else 0

    def clear4D(self):
        self.show4D(False)
        for cls in ("vtkMRMLSequenceBrowserNode", "vtkMRMLSequenceNode", "vtkMRMLScalarVolumeNode"):
            for n in list(slicer.util.getNodesByClass(cls)):
                if n.GetName() not in ("CV 4D 再生", "CV 4D 位相", "CV 4D"): continue
                try:
                    if hasattr(n, "GetNumberOfDisplayNodes"):
                        for d in [n.GetNthDisplayNode(i) for i in range(n.GetNumberOfDisplayNodes())]:
                            if d is not None: slicer.mrmlScene.RemoveNode(d)
                    slicer.mrmlScene.RemoveNode(n)
                except Exception: pass
        self.br4D = self.seq4D = self.proxy4D = self.vr4D = None

    def show4D(self, on):
        """on: 3D の面・色分け VR を隠して、動く VR と断面に切り替える。off: 元に戻す"""
        on = bool(on) and self.has4D()
        if on == bool(getattr(self, "on4D", False)): return
        lm = slicer.app.layoutManager()
        if on:
            st = dict(vr=bool(getattr(self, "vrOn", False)), models={}, bg={})
            if getattr(self, "vrDisplay", None) is not None: self.vrDisplay.SetVisibility(False)
            for k, n in self.layerModels.items():
                d = n.GetDisplayNode() if n else None
                if d is not None: d.SetVisibility(k in self.STATIC_4D and bool(self.visible.get(k, False)))
            cap = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
            if cap and cap.GetDisplayNode(): cap.GetDisplayNode().SetVisibility(False)
            for nm in ("Red", "Yellow", "Green"):
                w = lm.sliceWidget(nm)
                if w is None: continue
                cn = w.sliceLogic().GetSliceCompositeNode(); st["bg"][nm] = cn.GetBackgroundVolumeID(); cn.SetBackgroundVolumeID(self.proxy4D.GetID())
            try:
                d = self.proxy4D.GetDisplayNode(); s0 = self.sourceVolume.GetDisplayNode()
                if d is not None and s0 is not None: d.SetAutoWindowLevel(False); d.SetWindowLevel(s0.GetWindow(), s0.GetLevel())
            except Exception: pass
            self._st4D = st; self.vr4D.SetVisibility(True); self.on4D = True
            try: self._tf4D()                                                 # 右上に 4D のウィンドウを出す
            except Exception: pass
        else:
            self.play4D(False)
            st = getattr(self, "_st4D", None) or {}
            if getattr(self, "vr4D", None) is not None: self.vr4D.SetVisibility(False)
            self.on4D = False
            # 面と VR は「今の状態」に合わせる。前は、面をすべて戻した上で 4D の前の VR も出していたので、VR を出したまま 4D を終えると面と VR が重なった。
            # また 4D の前の VR の状態を控えから戻していたので、4D の途中で VR を消しても、終えた時に VR が戻った
            if getattr(self, "vrDisplay", None) is not None: self.vrDisplay.SetVisibility(bool(getattr(self, "vrOn", False)))
            self._applyLayerVis()
            for nm, vid in st.get("bg", {}).items():
                w = lm.sliceWidget(nm)
                if w is not None: w.sliceLogic().GetSliceCompositeNode().SetBackgroundVolumeID(vid)
            try: self._vrLabel()
            except Exception: pass
        try: self._clipSync()
        except Exception: pass
        self._view().scheduleRender()

    def play4D(self, on, fps=None):
        if not self.has4D(): return
        if fps is not None: self.br4D.SetPlaybackRateFps(float(fps))
        self.br4D.SetPlaybackActive(bool(on))

    def set4DPhase(self, i):
        if not self.has4D(): return
        self.br4D.SetPlaybackActive(False); self.br4D.SetSelectedItemNumber(int(i))

    def phase4D(self):
        return self.br4D.GetSelectedItemNumber() if self.has4D() else -1
