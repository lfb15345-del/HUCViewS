# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 見た目（陰影・光・深さの剥離を切る・背景）とカメラ（視点・視野・大動脈に沿って飛ぶ）
CardiacViewLogic の一部（LookMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class LookMixin:
    # ---------------------------------------------------------------- look
    # VR の「光の回り込み」（全体照明）は、この PC で止まるほど重かったので使わない。VR は光の当て方（環境光・拡散・つや）だけで陰影を変える
    SHADE = {"なし": dict(ssao=False, rad=10.0, ker=32, k2f=2.2, k2h=3.5, k2b=4.0, kI=0.95, samb=0.18, vamb=0.30, vdif=0.75, vspec=0.25),
             "ふつう": dict(ssao=True, rad=16.0, ker=32, k2f=5.0, k2h=10.0, k2b=3.0, kI=1.50, samb=0.08, vamb=0.10, vdif=0.62, vspec=0.40),
             "強め": dict(ssao=True, rad=22.0, ker=32, k2f=8.0, k2h=16.0, k2b=2.5, kI=1.75, samb=0.04, vamb=0.05, vdif=0.56, vspec=0.45)}
    # 明るさ: 正面の光と環境光を下げた分、斜めの光（kI）を強くして、全体の平均の明るさは「なし」とほぼ同じ（暗くしない）
    # 重さの約束: どの段階も 1 コマの計算量は同じ（SSAO の点の数は 32 まで）。違うのは光の向きの強さ（正面からの光を弱く・斜めの光を強く）と環境光だけ。動かしている間に増える計算はない
    SHADE_KEY = "HUCViewS/shading"

    def _shade(self):
        lv = getattr(self, "shadeLevel", None)
        if lv is None:
            try: lv = str(qt.QSettings().value(self.SHADE_KEY) or "ふつう")
            except Exception: lv = "ふつう"
            self.shadeLevel = lv if lv in self.SHADE else "ふつう"
        return self.SHADE[self.shadeLevel]

    def _applyVRShade(self):
        """VR の陰影: 環境光を下げて拡散・つやを上げる（重さは変わらない）"""
        s = self._shade()
        for dn in (getattr(self, "vrDisplay", None), getattr(self, "vr4D", None)):
            if dn is None or not hasattr(dn, "GetVolumePropertyNode"): continue
            pn = dn.GetVolumePropertyNode(); vp = pn.GetVolumeProperty() if pn is not None else None
            if vp is None: continue
            vp.ShadeOn(); vp.SetAmbient(s["vamb"]); vp.SetDiffuse(s["vdif"]); vp.SetSpecular(s["vspec"])

    def setShading(self, level, measure=True):
        """陰影: なし／ふつう／強め。面 = 環境光遮蔽の強さと光の向きのコントラスト、VR = 光の回り込み。重すぎる PC は 1 段下げる"""
        self.shadeLevel = level if level in self.SHADE else "ふつう"
        try: qt.QSettings().setValue(self.SHADE_KEY, self.shadeLevel)
        except Exception: pass
        self.studioLighting(self._bg(), ssao=True); self._applyVRShade()
        msg = ""
        if measure and self.shadeLevel != "なし":
            ms = self._frameMs(4)
            if ms > 2.5 * self.PERF_TARGET_MS:                                 # 1 コマ 75 ms を超える（13 fps 未満）→ 1 段下げる
                down = {"強め": "ふつう", "ふつう": "なし"}[self.shadeLevel]
                self.shadeLevel = down; self.studioLighting(self._bg(), ssao=True); self._applyVRShade()
                msg = f"この PC では重かったので「{down}」にしました（1 コマ {ms:.0f} ms）"
        self._view().forceRender(); return msg

    def studioLighting(self, bgIndex=0, ssao=False):
        v = self._view(); vn = self._viewNode()
        vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
        self._noDepthPeeling()
        self.setBackground(bgIndex, remember=False)
        try:
            ren = v.renderWindow().GetRenderers().GetFirstRenderer()
            ren.RemoveAllLights()
            s = self._shade()
            lk = vtk.vtkLightKit(); lk.SetKeyLightIntensity(float(s.get("kI", 0.95)));   # 陰影をつけても全体の明るさは「なし」と同じ（実測で合わせた）
            lk.SetKeyLightWarmth(0.6); lk.SetFillLightWarmth(0.4)
            lk.SetKeyToFillRatio(s["k2f"]); lk.SetKeyToHeadRatio(s["k2h"]); lk.SetKeyToBackRatio(s.get("k2b", 4.0))      # 陰影の段階で、明るい面と暗い面の差を変える
            lk.SetKeyLightAzimuth(25); lk.SetKeyLightElevation(45)
            lk.AddLightsToRenderer(ren)
            self._applySurfAmbient(s)                                           # 環境光を下げると、光の当たらない側が暗くなって陰影がつく
            ssao = bool(ssao) and s["ssao"]
            ren.SetUseSSAO(ssao)
            if ssao: ren.SetSSAORadius(s["rad"]); ren.SetSSAOBias(0.5); ren.SetSSAOKernelSize(s["ker"]); ren.SetSSAOBlur(True)
        except Exception as e:
            print("lighting:", e)
        v.forceRender()

    def _installNoPeelGuard(self):
        """深さの剥離は、シーンを空にした・読み込んだ後も含めていつも OFF に保つ（Slicer の既定は ON。AMD の GPU で描画が終わらなくなる）。
        3D の view node が変わるたびに見張る（アプリ全体で 1 つ）"""
        try:
            vn = self._viewNode()
            reg = getattr(slicer, "_cvNoPeel", None)
            if reg and reg.get("vn") is vn: return
            if reg:
                try: reg["vn"].RemoveObserver(reg["tag"])
                except Exception: pass
            def cb(caller=None, ev=None):
                try:
                    if caller.GetUseDepthPeeling(): caller.SetUseDepthPeeling(False)
                except Exception: pass
            tag = vn.AddObserver(vtk.vtkCommand.ModifiedEvent, cb)
            slicer._cvNoPeel = dict(vn=vn, tag=tag); cb(vn)
        except Exception as e: print("no-peel guard:", e)

    def _noDepthPeeling(self):
        """半透明は「深さの剥離」を使わず、1 回で描く方式（OIT）にする。
        剥離は GPU によって（AMD Radeon など）症例しだいで描画が終わらなくなる（MAC 重症 AS の症例で固まった）。
        半透明は心筋の切り口（平らな 1 枚）と外形くらいなので、見た目はほぼ同じで軽い。保存した症例を開いた時も切る"""
        try:
            vn = self._viewNode()
            if vn.GetUseDepthPeeling(): vn.SetUseDepthPeeling(False)
            ren = self._view().renderWindow().GetRenderers().GetFirstRenderer()
            if ren.GetUseDepthPeeling(): ren.SetUseDepthPeeling(False)
        except Exception as e: print("depth peeling:", e)
        self._installNoPeelGuard()

    def _applySurfAmbient(self, s=None):
        a = float((s or self._shade()).get("samb", 0.15))
        for k, n in self.layerModels.items():
            d = n.GetDisplayNode() if n else None
            if d is not None and k != "軟部組織": d.SetAmbient(a)

    BG_KEY = "CardiacView/bg"

    def _bg(self):
        """背景の色（0 = 黒, 1 = 濃いグレー, 2 = 白）。この症例で選んだもの → 無ければ前に選んだもの（PC ごとに覚える）"""
        i = getattr(self, "_bgIndex", None)
        if i is None:
            try: i = int(qt.QSettings().value(self.BG_KEY, 0) or 0)
            except Exception: i = 0
        return i if i in (0, 1, 2) else 0

    def setBackground(self, i, remember=True):
        vn = self._viewNode()
        i = int(i) if int(i) in (0, 1, 2) else 0
        col = [(0, 0, 0), (0.16, 0.17, 0.19), (1, 1, 1)][i]
        vn.SetBackgroundColor(*col); vn.SetBackgroundColor2(*col)
        self._bgIndex = i                                                    # 前はここで覚えていなかったので、陰影を変える・作り直す・症例を開くたびに黒へ戻っていた（欄は「白」のまま）
        if remember:
            try: qt.QSettings().setValue(self.BG_KEY, i)
            except Exception: pass

    # ---------------------------------------------------------------- camera
    def _sceneCenter(self):
        if self.bounds is None: self._updateBounds()
        if self.bounds is None: return np.array([0, 0, 0.0])
        lo, hi = self.bounds; return (lo + hi) / 2

    def _sceneRadius(self):
        if self.bounds is None: return 200.0
        lo, hi = self.bounds; return float(np.linalg.norm(hi - lo) / 2)

    def _visibleBounds(self):
        B = [n.GetPolyData().GetBounds() for name, n in self.layerModels.items()
             if n and n.GetPolyData() and n.GetPolyData().GetNumberOfPoints() and self.visible.get(name, True) and name != "胸骨ワイヤー"]
        if not B: return self.bounds
        A = np.array(B); return (A[:, 0::2].min(0), A[:, 1::2].max(0))

    def setView(self, key, fov=30):
        self.flying = False
        vb = self._visibleBounds()
        if vb is None: return
        lo, hi = vb; c = (lo + hi) / 2; D = float(np.max(hi - lo)) / 2 / math.tan(math.radians(fov / 2)) * 1.12
        dirs = {"A": (0, 1, 0), "P": (0, -1, 0), "L": (-1, 0, 0), "R": (1, 0, 0), "S": (0, 0, 1), "SURG": (0.35, 0.80, 0.50)}
        d = np.array(dirs.get(key, (0, 1, 0)), float); d /= np.linalg.norm(d)
        up = (0, 1, 0) if key == "S" else (0, 0, 1)
        cam = self._camera()
        cam.SetPosition(*(c + d * D)); cam.SetFocalPoint(*c); cam.SetViewUp(*up)
        cam.GetCamera().SetViewAngle(fov); cam.ResetClippingRange()
        self._fitParallel()
        if self.cutAxis == "VIEW": self.setCut("VIEW", self.cutFrac)
        self._view().forceRender()

    def setFov(self, fov):
        cam = self._camera()
        if cam: cam.GetCamera().SetViewAngle(fov); self._view().forceRender()

    def _centerline(self):
        best = None
        for n in slicer.util.getNodesByClass("vtkMRMLMarkupsCurveNode"):
            if n.GetNumberOfControlPoints() > 20 and (best is None or n.GetNumberOfControlPoints() > best.GetNumberOfControlPoints()): best = n
        return best

    def flyAorta(self, frac, onlyIfFlying=False):
        if onlyIfFlying and not self.flying: return
        cl = self._centerline()
        if cl is None: slicer.util.warningDisplay("中心線がありません。先に「大動脈サイジング」を実行してください。"); return
        pts = slicer.util.arrayFromMarkupsCurvePoints(cl, world=True)
        n = len(pts); i = int(np.clip(frac * (n - 1), 0, n - 12)); j = min(i + 10, n - 1)
        self.flying = True
        self.setLayerVisible("血液・血管", False)  # 血管の全グループ
        cam = self._camera()
        cam.SetPosition(*pts[i]); cam.SetFocalPoint(*pts[j]); cam.SetViewUp(0, 0, 1)
        cam.GetCamera().SetViewAngle(100); cam.ResetClippingRange(); self._view().forceRender()
