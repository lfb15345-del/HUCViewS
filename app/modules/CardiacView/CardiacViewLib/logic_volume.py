# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 元の CT と作業用の画像・AI のラベル（マスク）の取り出し
CardiacViewLogic の一部（VolumeMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class VolumeMixin:
    _WORK_RE = re.compile(r"_cv\d+(?:\.\d+)?mm(?:_\d+)?$")      # 作業用の画像の名前（_resample が付ける: <元の名前>_cv0.8mm）

    def _isWorkVolume(self, v):
        """CardiacView が作り直した作業用の画像（<元の名前>_cv<格子>mm）か。
        0.8 mm 等方に近い CT は作り直さない（_resample が元の CT をそのまま返す）ので、元の CT 自身に印（calib）が付く。それは元の CT として扱う
        （印だけで作業用とみなすと「元の CT が見つからない」「作業用の画像が使われています」と誤って出る）"""
        return v is not None and bool(self._WORK_RE.search(v.GetName() or ""))

    def _findSourceFor(self, work):
        """作業用の画像から元の CT を探す。(node, 見つけ方)。
        0) 作り直していない CT は自分自身　1) 保存してある元の名前　2) AI ラベル（全身・心腔）が作られた元の CT で、範囲が同じもの
        3) 作業用の画像と同じ範囲の CT。範囲の違う CT（術前 CT など）は取らない（違う CT で VR を作るより、作業用の画像で作る方が安全）
        （症例を開いた後に元の CT が名前で見つからず、VR が「先に 3D を自動で作る」で止まった。2026-11-18）"""
        if work is None: return None, "作業用の画像なし"
        wname = work.GetName() or ""
        if not self._WORK_RE.search(wname):                                  # 作り直していない CT（0.8 mm 等方に近い）: 元の CT 自身が作業用を兼ねている
            return (work, "元の CT をそのまま使った症例") if work.GetImageData() is not None else (None, "画像が空")
        def usable(v):
            return (v is not None and v is not work and v.IsA("vtkMRMLScalarVolumeNode") and not v.IsA("vtkMRMLLabelMapVolumeNode")
                    and not v.IsA("vtkMRMLVectorVolumeNode") and not self._isWorkVolume(v) and v.GetImageData() is not None)
        vols = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        name = work.GetAttribute("CardiacView.source") or self._WORK_RE.sub("", wname)
        for v in vols:
            if v.GetName() == name and usable(v): return v, "名前"
        wb = [0.0] * 6; work.GetRASBounds(wb)
        def same(v):                                                         # 作業用の画像は元の CT を格子だけ変えたもの → 範囲はほぼ同じ（術前 CT など別の CT を取らない）
            b = [0.0] * 6; v.GetRASBounds(b)
            return max(abs(b[i] - wb[i]) for i in range(6)) <= 5.0
        refs = []
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            r = n.GetNodeReference("referenceImageGeometryRef")
            if usable(r) and n.GetSegmentation().GetNumberOfSegments() >= 5 and r not in refs: refs.append(r)
        for r in refs:
            if same(r): return r, "AI ラベルの元の画像"
        cands = [v for v in vols if usable(v) and not (v.GetName() or "").startswith(("CV ", "cv_", "HV "))]
        fit = [v for v in cands if same(v)]
        if fit: return min(fit, key=lambda v: min(v.GetSpacing())), "作業用の画像と同じ範囲"
        return None, f"元の CT「{name}」がシーンにない"

    def _hideInternalVolumes(self):
        """内部用の画像（作業用・VR 用・4D の位相・一時的なもの）を、CT の欄などの「選ぶ欄」に出さない。
        前は CT の欄に並んでいて、選んで作ると違う画像から 3D を作ってしまった。戻り値: 隠した数"""
        n = 0
        try:
            for v in slicer.util.getNodesByClass("vtkMRMLVolumeNode"):
                nm = v.GetName() or ""; inner = nm.startswith(("cv_", "CV "))
                if not inner and self._isWorkVolume(v):                       # 作業用の画像は、元の CT がある時だけ隠す（元の CT が無い古い症例では、これを選んで作り直せるように残す）
                    src = self._findSourceFor(v)[0]; inner = src is not None and src is not v
                if inner and not v.GetHideFromEditors(): v.SetHideFromEditors(True); n += 1
        except Exception as e: print("hide internal volumes:", e)
        return n

    def resolveSource(self, vol):
        """CT の欄で作業用の画像が選ばれていたら元の CT に読み替える。(node, 説明)"""
        if not self._isWorkVolume(vol): return vol, ""
        src, how = self._findSourceFor(vol)
        if src is None: return vol, f"作業用の画像「{vol.GetName()}」が選ばれていますが、元の CT が見つかりません（{how}）"
        return src, f"作業用の画像「{vol.GetName()}」の代わりに元の CT「{src.GetName()}」を使います（{how}）"

    def checkCase(self):
        """症例を開いた後・3D を作った後の点検。足りないもの・おかしいものの文のリスト（空なら問題なし）"""
        out = []
        src = getattr(self, "sourceVolume", None)
        if src is None: out.append("元の CT が見つかりません（VR・作り直しができません）")
        elif self._isWorkVolume(src): out.append(f"元の CT の代わりに作業用の画像「{src.GetName()}」が使われています")
        if self._findSegmentation() is None: out.append("AI の全身ラベルがありません（VR が作れません）")
        if self._findChambers() is None:
            why = getattr(self, "hcError", None)
            out.append("AI の心腔ラベルがありません（VR の色分け・心腔の表示が粗くなります）" + (f"。心腔の AI が失敗: {why[:120]}" if why else ""))
        err = getattr(self, "vrPrepError", None)
        if err: out.append(f"VR の準備に失敗しました: {err}")
        be = getattr(self, "buildErrors", None)
        if be: out.append("一部が作れませんでした: " + "・".join(f"{w}（{e}）" for w, e in be))
        for m in out: print("[CardiacView 点検]", m)
        return out

    def _resample(self, vol, spacing):
        cur = vol.GetSpacing()
        if max(abs(cur[i] - spacing) for i in range(3)) < 0.05: return vol
        name = f"{vol.GetName()}_cv{spacing:.1f}mm"
        out = slicer.mrmlScene.GetFirstNodeByName(name)
        if out and out.GetImageData(): return out
        out = self._resliceTo(vol, (spacing, spacing, spacing), name, cubic=True)
        try:                                                   # ノイズと 5mm 厚の段差をならしてから面を作る（ツルツルに）
            from scipy import ndimage
            a = slicer.util.arrayFromVolume(out).astype(np.float32)
            sz = float(max(cur)); sxy = float(min(cur))
            sig = (max(0.6, 0.4 * sz) / spacing, max(0.6, sxy) / spacing, max(0.6, sxy) / spacing)   # (z, y, x) ボクセル単位
            a = ndimage.gaussian_filter(a, sigma=sig)
            slicer.util.updateVolumeFromArray(out, a.astype(np.int16))
            print(f"なめらか処理: σ = {sig[0]*spacing:.1f} mm（z）/ {sig[1]*spacing:.1f} mm（面内）")
        except Exception as e:
            print("denoise:", e)
        out.SetDisplayVisibility(False)
        return out

    def _resliceTo(self, vol, spacing, name, cubic=False):
        """vol を spacing (x, y, z mm) に作り直した新しいボリューム（向き・原点はそのまま）。
        Slicer の再サンプリング（別プロセス）より 10 倍ほど速い（0.35 mm の CT → 0.8 mm で 1〜2 秒）"""
        img = vol.GetImageData(); cur = vol.GetSpacing(); dims = img.GetDimensions()
        src = vtk.vtkImageData(); src.ShallowCopy(img); src.SetSpacing(*cur); src.SetOrigin(0, 0, 0)
        n = [max(1, int(math.floor((dims[i] - 1) * cur[i] / spacing[i])) + 1) for i in range(3)]
        rs = vtk.vtkImageReslice(); rs.SetInputData(src)
        rs.SetOutputSpacing(*spacing); rs.SetOutputOrigin(0, 0, 0); rs.SetOutputExtent(0, n[0] - 1, 0, n[1] - 1, 0, n[2] - 1)
        rs.SetInterpolationModeToCubic() if cubic else rs.SetInterpolationModeToLinear()
        rs.SetBackgroundLevel(float(img.GetScalarRange()[0])); rs.Update()
        o = vtk.vtkImageData(); o.DeepCopy(rs.GetOutput()); o.SetSpacing(1, 1, 1); o.SetOrigin(0, 0, 0)
        out = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
        D = vtk.vtkMatrix4x4(); vol.GetIJKToRASDirectionMatrix(D)
        out.SetIJKToRASDirectionMatrix(D); out.SetSpacing(*spacing); out.SetOrigin(vol.GetOrigin())
        out.SetAndObserveImageData(o)
        out.SetDisplayVisibility(False)
        return out

    def _aiInput(self, vol, kind):
        """AI（TotalSegmentator）に渡す CT。AI はどうせ自分の格子（total 速い版 3 mm・心腔 0.73×0.73×1.0 mm）に作り直すので、
        それより細かい CT は先に近い細かさにしてから渡す（書き出し・読み込み・作り直しが 10〜50 分の 1 になる）。粗くはしない"""
        cur = vol.GetSpacing()
        want = (1.5, 1.5, 1.5) if kind == "total" else (0.7, 0.7, 1.0)
        sp = tuple(max(cur[i], want[i]) for i in range(3))
        if all(abs(sp[i] - cur[i]) < 0.02 for i in range(3)): return vol
        return self._resliceTo(vol, sp, f"cv_ai_{kind}", cubic=False)

    TOTAL_MIN_SEGS = 5      # 名前で分からない全身ラベルとみなす最小の区域の数

    def _segFor(self, vol, kind):
        """vol に対応するセグメンテーション。kind: "total" / "heartchambers" """
        if vol is None: return None
        want = [f"{vol.GetName()} {kind}"] + ([f"{vol.GetName()} segmentation"] if kind == "total" else [])
        cands = []
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            sg = n.GetSegmentation()
            names = [sg.GetNthSegment(i).GetName().lower() for i in range(sg.GetNumberOfSegments())]
            isHC = any("left ventricle" in x for x in names)
            if not names: continue
            if kind == "total" and n.GetName() in want: return n               # この CT 用に作った全身ラベル（名前で分かる）は、中身（区域の数など）によらず使う
            if isHC != (kind == "heartchambers"): continue
            if n.GetName() in want: return n
            if kind == "total" and len(names) < self.TOTAL_MIN_SEGS: continue  # 名前で分からない時だけ数で見る（視野の狭い心臓 CT は全身ラベルが 20 個以下になりうる → 前は見つからず VR が作れなかった）
            r = n.GetNodeReference("referenceImageGeometryRef")
            if r is not None and r.GetID() == vol.GetID(): cands.append(n)
        return max(cands, key=lambda n: n.GetSegmentation().GetNumberOfSegments()) if cands else None

    def _findSegmentation(self):
        src = getattr(self, "sourceVolume", None)
        if src is not None:
            n = self._segFor(src, "total")
            if n is not None: return n
        best = None
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):          # 心腔ラベルではない AI ラベルのうち、区域が一番多いもの
            sg = n.GetSegmentation(); k = sg.GetNumberOfSegments()
            named = n.GetName().endswith((" total", " segmentation"))
            if not named and any("left ventricle" in sg.GetNthSegment(i).GetName().lower() for i in range(k)): continue
            if (named and k > 0) or k >= self.TOTAL_MIN_SEGS:
                if best is None or k > best.GetSegmentation().GetNumberOfSegments(): best = n
        return best

    def _segmentMaskArray(self, segNode, refVol, keywords):
        sg = segNode.GetSegmentation()
        ids = vtk.vtkStringArray(); sg.GetSegmentIDs(ids)
        sel = vtk.vtkStringArray()
        for k in range(ids.GetNumberOfValues()):
            sid = ids.GetValue(k)
            nm = sg.GetSegment(sid).GetName().lower().replace("_", " ")
            if any(t.replace("_", " ") in nm for t in keywords): sel.InsertNextValue(sid)
        if sel.GetNumberOfValues() == 0: return None
        return self._exportMask(segNode, sel, refVol, "cv_tmpLabel")

    @staticmethod
    def _exportMask(segNode, sel, refVol, name):
        """選んだ区域（sel）を refVol の格子のマスク（bool の配列）にする。
        書き出しは色表ノードを 1 つ作り、ラベルの画像を消しても色表はシーンに残っていた（1 回の 3D 作りで約 30 個。症例に保存されていた）→ ここで消す"""
        before = {n.GetID() for n in slicer.util.getNodesByClass("vtkMRMLColorTableNode")}
        lab = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", name)
        try:
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(segNode, sel, lab, refVol)
            return slicer.util.arrayFromVolume(lab) > 0
        finally:
            slicer.mrmlScene.RemoveNode(lab)
            for n in slicer.util.getNodesByClass("vtkMRMLColorTableNode"):
                if n.GetID() not in before and n.GetSingletonTag() is None: slicer.mrmlScene.RemoveNode(n)

    _EXPORT_CT_RE = re.compile(r"_ColorTable(_\d+)?$")

    def _purgeExportColors(self):
        """前の版で作った症例に残っている、ラベルの書き出しの色表（どこからも使われていないもの）をシーンから外す。戻り値: 外した数"""
        used = set()
        for i in range(slicer.mrmlScene.GetNumberOfNodes()):
            n = slicer.mrmlScene.GetNthNode(i)
            if n.IsA("vtkMRMLDisplayNode") and n.GetColorNodeID(): used.add(n.GetColorNodeID())
            for r in range(n.GetNumberOfNodeReferenceRoles()):
                role = n.GetNthNodeReferenceRole(r)
                for j in range(n.GetNumberOfNodeReferences(role)):
                    rid = n.GetNthNodeReferenceID(role, j)
                    if rid: used.add(rid)
        k = 0
        for n in slicer.util.getNodesByClass("vtkMRMLColorTableNode"):
            if n.GetSingletonTag() is None and n.GetID() not in used and self._EXPORT_CT_RE.search(n.GetName() or ""):
                slicer.mrmlScene.RemoveNode(n); k += 1
        return k

    def _boneMaskArray(self, segNode, refVol):
        sg = segNode.GetSegmentation()
        ids = vtk.vtkStringArray(); sg.GetSegmentIDs(ids)
        sel = vtk.vtkStringArray()
        for k in range(ids.GetNumberOfValues()):
            sid = ids.GetValue(k)
            if any(t in sg.GetSegment(sid).GetName().lower() for t in BONE_KEYWORDS): sel.InsertNextValue(sid)
        if sel.GetNumberOfValues() == 0: return None
        return self._exportMask(segNode, sel, refVol, "cv_boneLabel")

    def _bodyMask(self, arr):
        """体の外（寝台・マット・ノイズ）を落とすマスク: -500HU 以上の最大連結成分をスライスごとに穴埋め"""
        try:
            from scipy import ndimage
        except Exception:
            return None
        m = arr > -500
        lab, n = ndimage.label(m)
        if n == 0: return None
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        body = lab == (int(np.argmax(sizes)) + 1)
        for z in range(body.shape[0]):
            body[z] = ndimage.binary_fill_holes(body[z])
        body = ndimage.binary_dilation(body, iterations=1)
        return body
