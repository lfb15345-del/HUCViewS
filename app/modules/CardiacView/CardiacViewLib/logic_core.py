# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 土台（初期化・シーンの小道具）と、層（面）の作成・表示・色合い・つや
CardiacViewLogic の一部（CoreMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *
from . import common          # 色合いで置き換わる名前は common.名前 で今の値を読む


class CoreMixin:
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.layerModels = {}
        self.planes = []          # 自由平面
        self.cutPlane = None      # スライダー駆動の平面
        self.clip = None
        self.cutAxis = None
        self.cutFrac = 0.5
        self._viewObsTag = None
        self.cutSign = 1.0
        self.flying = False
        self.workVolume = None
        self.folderItem = None
        self.bounds = None
        self.visible = {}

    # ---------------------------------------------------------------- scene helpers
    def _folder(self):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        if self.folderItem is None or not sh.GetItemName(self.folderItem):
            self.folderItem = sh.CreateFolderItem(sh.GetSceneItemID(), "CardiacView")
        return self.folderItem

    def _put(self, node):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        sh.SetItemParent(sh.GetItemByDataNode(node), self._folder())

    def _view(self):
        return slicer.app.layoutManager().threeDWidget(0).threeDView()

    def _viewNode(self):
        return self._view().mrmlViewNode()

    def _camera(self):
        return slicer.modules.cameras.logic().GetViewActiveCameraNode(self._viewNode())

    # ---------------------------------------------------------------- layers
    def buildLayers(self, vol, specs, spacing, boneLayer, status=lambda m: None):
        t0 = time.time()
        self.buildErrors = []                                                 # 作れなかった部品（前は print だけで、報告は「できました」のままだった）→ checkCase が報告に出す
        def fail(what, e):
            import traceback; traceback.print_exc(); print(f"{what}:", e); self.buildErrors.append((what, (str(e) or type(e).__name__)[:60]))
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
        for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"): d.SetVisibility(False)
        for s in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            if s.GetDisplayNode(): s.GetDisplayNode().SetVisibility(False)

        status("再サンプリング中…")
        work = self._resample(vol, spacing); self.workVolume = work
        segNode = self._findSegmentation()
        boneMask = None
        if boneLayer and segNode:
            status("骨ラベルを取得中…"); boneMask = self._boneMaskArray(segNode, work)

        self.removeFreePlanes(); self._clearCuts()
        for n in list(self.layerModels.values()):
            if n: slicer.mrmlScene.RemoveNode(n)
        self.layerModels.clear()
        self._strokes = []; self._pMask = {}; self._pMaskKey = {}

        arr = slicer.util.arrayFromVolume(work)
        status("体の範囲を抽出中…")
        body = self._bodyMask(arr)
        for sp in specs:
            status(f"レイヤー「{sp['name']}」を生成中…")
            binary = ((arr >= sp["lo"]) & (arr <= sp["hi"])).astype(np.uint8)
            if boneMask is not None: binary[boneMask] = 0
            if body is not None: binary[~body] = 0
            binary = self._cleanBinary(binary, spacing)
            if sp["name"] == "血液・血管" and segNode is not None:
                try:
                    from scipy import ndimage
                    # 骨の縁を広めに除外
                    if boneMask is not None:
                        binary[ndimage.binary_dilation(boneMask, iterations=2)] = 0
                    # ラベル付き血管につながる成分だけ残す（骨片・ノイズ除去）
                    allv = self._segmentMaskArray(segNode, work, tuple(k for _, keys, _ in common.VESSEL_GROUPS for k in keys))
                    if allv is not None:
                        lab, nlab = ndimage.label(binary, structure=np.ones((3, 3, 3)))
                        hit = np.unique(lab[allv & (binary > 0)])
                        keep = np.zeros(nlab + 1, bool); keep[hit] = True; keep[0] = False
                        before = int(binary.sum()); binary = keep[lab].astype(np.uint8)
                        status(f"  血管につながらない塊を除去: {before - int(binary.sum())} ボクセル")
                except Exception as e:
                    print("vessel cleanup:", e)
                # ラベルで色分けした複数モデルに分ける。ラベルの外側 2.5mm 以内の血液（ラベルより少し太い造影部分）は
                # 一番近いラベルの仲間にする（別の薄い殻にすると大動脈の表面とちらついて縞模様になる）
                from scipy import ndimage
                gmask = {}; labmap = np.zeros(binary.shape, np.int8)
                for gi, (gname, keys, col) in enumerate(common.VESSEL_GROUPS, start=1):
                    mk = self._segmentMaskArray(segNode, work, keys)
                    if mk is None: continue
                    gmask[gname] = mk; labmap[(labmap == 0) & mk] = gi
                if (labmap > 0).any():
                    dist, ind = ndimage.distance_transform_edt(labmap == 0, return_indices=True)
                    near = labmap[tuple(ind)]
                    rim = (binary > 0) & (labmap == 0) & (dist * spacing <= 2.5)
                    for gi, (gname, keys, col) in enumerate(common.VESSEL_GROUPS, start=1):
                        if gname in gmask: gmask[gname] = gmask[gname] | (rim & (near == gi))
                    del dist, ind, near
                remaining = binary.copy()
                for gname, keys, col in common.VESSEL_GROUPS:
                    mask = gmask.get(gname)
                    if mask is None: continue
                    part = (remaining > 0) & mask
                    if part.sum() < 50: continue
                    model = self._surfaceFromBinary(part.astype(np.uint8), work, gname, col, sp["smooth"])
                    model.GetDisplayNode().SetVisibility(sp["visible"]); self.layerModels[gname] = model; self.visible[gname] = sp["visible"]
                    remaining[part] = 0
                    status(f"  {gname} 完了")
                try: self._colorChambersLR()
                except Exception as e: fail("左右の色分け", e)
                if remaining.sum() > 50:
                    gname, col = common.VESSEL_OTHER
                    model = self._surfaceFromBinary(remaining, work, gname, col, sp["smooth"])
                    model.GetDisplayNode().SetVisibility(sp["visible"]); self.layerModels[gname] = model; self.visible[gname] = sp["visible"]
                continue
            model = self._surfaceFromBinary(binary, work, sp["name"], sp["color"], sp["smooth"], step=2 if sp["name"] == "軟部組織" else 1)
            model.GetDisplayNode().SetVisibility(sp["visible"]); self.layerModels[sp["name"]] = model; self.visible[sp["name"]] = sp["visible"]
            if sp["name"] == "軟部組織":
                # 他の組織を覆い隠さないよう半透明・控えめな色に
                d = model.GetDisplayNode(); d.SetOpacity(0.18); d.SetColor(0.80, 0.72, 0.66); d.SetSpecular(0.05)
        if boneMask is not None:
            status("レイヤー「骨」・胸骨ワイヤーを生成中…")
            try: self._buildBone(arr, work, spacing, segNode, boneMask, body)       # 前は、骨で失敗すると心臓壁・心筋まで全部が作られずに終わっていた
            except Exception as e: fail("骨", e)
        if segNode is not None:
            try:
                status("人工物（人工弁・ステントなど）と石灰化を探しています…")
                self.buildImplantsCalc(arr, work, spacing, segNode, boneMask)
            except Exception as e: fail("人工物・石灰化", e)
        if segNode is not None:
            ok = False
            try:
                status("レイヤー「心臓壁」を生成中…")
                self.visible["心臓壁"] = False
                self.rebuildWall(); ok = True
            except Exception as e: fail("心臓壁", e)
            if ok:
                try:
                    status("レイヤー「心筋」を生成中…")
                    self.buildMyocardium()
                except Exception as e: fail("心筋", e)
        self._updateBounds()
        self.studioLighting(self._bg(), ssao=True)   # 環境光遮蔽で奥行きを出す（GPU 負荷は小さい）。背景は選んだ色のまま
        self.setView("A", 30)
        status(f"完了（{time.time()-t0:.0f} 秒）")

    STATIC_4D = ("骨", "軟部組織", "人工物", "胸骨ワイヤー")                                 # 4D でも一緒に出せる面（心臓と一緒に動かないもの）

    def setLayerVisible(self, name, vis, user=False):
        """層のチェック。4D の途中は、動かない骨・軟部組織・人工物だけ面を出す（心臓・血管の面は動く VR と重なるので、4D を終えた時に）。
        user=True（先生がチェックを押した）: VR の途中なら VR の上にも出す（前は出した後、VR の色を切り替えると黙って消えた）。
        プログラムから呼ぶ時（大動脈サイジングから戻る時など）は、VR の上に出す層を増やさない"""
        d4 = bool(getattr(self, "on4D", False)); ex = self.__dict__.setdefault("_vrExtra", set())
        for k in self._namesFor(name):
            self.visible[k] = bool(vis)
            if not vis: ex.discard(k)
            elif user and getattr(self, "vrOn", False): ex.add(k)             # 4D の途中でも、VR に戻った時に出す
            n = self.layerModels.get(k)
            if n and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(self._layerShown(k))
        if d4:
            try: self._clipSync()
            except Exception: pass
            self._view().scheduleRender()
            return
        if name == "心筋":
            self.updateMyoCap()

    def setLayerOpacity(self, name, op):
        for k in self._namesFor(name):
            n = self.layerModels.get(k)
            if n and n.GetDisplayNode(): n.GetDisplayNode().SetOpacity(op)

    def applyPalette(self, name, rebuildVR=True):
        """色合いを変える: 今ある面の色・光沢、壁の色表、心筋の切り口、VR の色（VR を出していれば作り直す）"""
        p = _setPalette(name)
        cmap = {"血管:大動脈系": p["aorta"], "血管:体静脈": p["sysvein"], "血管:肺静脈": p["pv"], "血管:心臓": p["heart"], "血管:肺動脈ほか": p["pa"],
                "骨": p["bone"], "石灰化": p["calc"], "心筋": p["myo"]}
        for k, col in cmap.items():
            n = self.layerModels.get(k); d = n.GetDisplayNode() if n else None
            if d is None: continue
            d.SetColor(*col)
            if k.startswith("血管") or k == "心筋": d.SetSpecular(p["spec"]); d.SetPower(p["power"]); d.SetAmbient(self._shade().get("samb", p["amb"])); d.SetDiffuse(p["dif"])
        pt = self.layerModels.get(self.PATCH_KEY)
        if pt is not None and pt.GetDisplayNode() is not None:
            dp = pt.GetDisplayNode(); dp.SetColor(*PATCH_COLOR); dp.SetSpecular(0.12); dp.SetPower(10); dp.SetDiffuse(0.85)
            if pt.GetAttribute("CV.vrTint"): pt.SetAttribute("CV.vrTint", ",".join(f"{x:.2f}" for x in PATCH_COLOR))
        try: self._colorChambersLR(p)
        except Exception as e: print("chambers LR:", e)
        w_ = self.layerModels.get("心臓壁")
        if w_ is not None and w_.GetDisplayNode(): d = w_.GetDisplayNode(); d.SetSpecular(p["spec"]); d.SetPower(p["power"]); d.SetAmbient(self._shade().get("samb", p["amb"])); d.SetDiffuse(p["dif"])
        ct = slicer.mrmlScene.GetFirstNodeByName("CV EpiEndo")
        if ct is not None:
            for tt in range(256):
                x = tt / 255.0
                c = common.EPI_COLOR if x < 1/6 else (common.ENDO_COLOR if x < 0.5 else (common.ENDO_R_COLOR if x < 5/6 else (SYNTH_COLOR if getattr(self, "showSynth", True) else common.EPI_COLOR)))
                ct.SetColor(tt, f"c{tt}", c[0], c[1], c[2], 1.0)
        cap = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
        if cap is not None and cap.GetDisplayNode(): cap.GetDisplayNode().SetColor(*common.MYO_CUT_COLOR)
        self.VR_GROUPS = [(g[0], g[1], c, g[3]) for g, c in zip(type(self).VR_GROUPS, p["vr"])]; self.VR_NEUTRAL = p["vrN"]; self.VR_PALE = p.get("vrPale"); self.VR_SEPTUM = p.get("vrSeptum")
        if rebuildVR and getattr(self, "vrOn", False) and getattr(self, "vrDisplay", None) is not None:
            try:
                self.vrDisplay.SetVisibility(False); self.vrDisplay = None; self.showVR(True, getattr(self, "vrMode", None))
            except Exception as e:                                            # 前は print だけで、VR も面も映らない画面になった → 面の表示に戻して知らせる
                import traceback; traceback.print_exc()
                try: self.showVR(False)
                except Exception as e2: print("palette VR → 面:", e2)
                try:
                    w = slicer.modules.cardiacview.widgetRepresentation().self()
                    if w.logic is self:
                        for b in (w.vrTissueButton, w.vrBloodButton): b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
                        w._status(f"色合いは変えましたが、VR を作り直せませんでした（{e}）。面の表示に戻しました")
                except Exception as e2: print("palette VR → 画面:", e2)
        else:
            if getattr(self, "vrDisplay", None) is not None and not getattr(self, "vrOn", False):
                self.vrDisplay = None                                         # 次に VR を出す時に新しい色で作る
        try: self._view().scheduleRender()
        except Exception: pass

    ROOMS = (("left atrium",), ("left ventricle",), ("right atrium",), ("right ventricle",))   # 0 左房 / 1 左室 / 2 右房 / 3 右室

    def _colorChambersLR(self, p=None):
        """「血管:心臓」（心腔の血液の面）を 左房・左室・右房・右室 で塗り分ける。頂点ごとに一番近い心腔ラベルで決める。
        決めた結果（CV_room）は面に持たせる（保存される）ので計算は 1 回だけ。色合いを変えた時は色だけ塗り直す"""
        from scipy import ndimage
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
        p = p or PALETTES.get(common.CUR_PALETTE, PALETTES["リアル"])
        node = self.layerModels.get("血管:心臓"); pd = node.GetPolyData() if node is not None else None
        if pd is None or pd.GetNumberOfPoints() == 0 or node.GetDisplayNode() is None: return False
        arr = pd.GetPointData().GetArray("CV_room")
        if arr is None or arr.GetNumberOfTuples() != pd.GetNumberOfPoints():
            hc = self._findChambers()
            if hc is None: return False
            P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
            h = 1.5; lo = P.min(0) - 5.0; n = (np.ceil((P.max(0) + 5.0 - lo) / h).astype(int) + 1)
            G = vtk.vtkMatrix4x4()
            for a in range(3): G.SetElement(a, a, h); G.SetElement(a, 3, float(lo[a]))
            ref = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "cv_tmpRef")
            img = vtk.vtkImageData(); img.SetDimensions(int(n[0]), int(n[1]), int(n[2])); img.AllocateScalars(vtk.VTK_SHORT, 1); ref.SetAndObserveImageData(img); ref.SetIJKToRASMatrix(G)
            lab = None
            try:
                for i, keys in enumerate(self.ROOMS):
                    m = self._segmentMaskArray(hc, ref, keys)
                    if m is None: continue
                    if lab is None: lab = np.zeros(m.shape, np.uint8)
                    lab[m & (lab == 0)] = i + 1
            finally:
                slicer.mrmlScene.RemoveNode(ref)
            if lab is None or len(np.unique(lab)) < 3: return False
            _, ind = ndimage.distance_transform_edt(lab == 0, return_indices=True); near = lab[tuple(ind)]; del ind
            ijk = np.clip(np.rint((P - lo) / h).astype(int), 0, n - 1)
            room = (near[ijk[:, 2], ijk[:, 1], ijk[:, 0]].astype(np.int16) - 1).clip(0, 3).astype(np.uint8)
            arr = numpy_to_vtk(room, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR); arr.SetName("CV_room"); pd.GetPointData().AddArray(arr)
        room = vtk_to_numpy(arr).astype(int)
        cols = np.array([p.get("la", p["heart"]), p["heart"], p.get("ra", p.get("heartR", p["pa"])), p.get("heartR", p["pa"])], float)
        rgb = numpy_to_vtk(np.ascontiguousarray((cols[room] * 255).round().astype(np.uint8)), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR); rgb.SetName("CV_roomRGB")
        pd.GetPointData().RemoveArray("CV_roomRGB"); pd.GetPointData().AddArray(rgb); pd.Modified()
        d = node.GetDisplayNode()
        d.SetActiveScalarName("CV_roomRGB"); d.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseDirectMapping); d.SetScalarVisibility(True)   # 色をそのまま（部屋の境目はなめらかに混ざる）
        return True

    def setGloss(self, g):
        for n in list(self.layerModels.values()):
            d = n.GetDisplayNode() if n else None
            if d: d.SetSpecular(0.1 + 0.6 * g); d.SetPower(8 + 60 * g)
