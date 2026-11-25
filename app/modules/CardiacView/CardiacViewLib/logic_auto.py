# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 全自動（CT の読み込み・格子・AI・較正・品質・手順・シーンの引き継ぎ）
CardiacViewLogic の一部（AutoMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *
from . import common          # 色合いで置き換わる名前は common.名前 で今の値を読む


class AutoMixin:
    # ================================================================ 全自動（他の画像でも同じ手順で）
    DEFAULT_CAL = dict(wall_lo=-20.0, wall_hi=175.0, blood_lo=180.0, blood_hi=900.0)

    def _cal(self):
        # 測れなかった値（None）は入れない → 使う側の既定値が効く（心腔ラベルが無いと rv=None が残り、VR の準備が float(None) で落ちていた）
        c = dict(self.DEFAULT_CAL); c.update({k: v for k, v in (getattr(self, "calib", {}) or {}).items() if v is not None}); return c

    def loadDicomFolder(self, folder):
        from DICOMLib import DICOMUtils
        loaded = []
        with DICOMUtils.TemporaryDICOMDatabase() as db:
            DICOMUtils.importDicom(folder, db)
            for p in db.patients(): loaded += DICOMUtils.loadPatientByUID(p)
        vols = [slicer.mrmlScene.GetNodeByID(i) for i in loaded]
        vols = [v for v in vols if v is not None and v.IsA("vtkMRMLScalarVolumeNode") and v.GetImageData() is not None]
        if not vols: return None
        return max(vols, key=lambda v: np.prod(v.GetImageData().GetDimensions()))

    def autoSpacing(self, vol):
        sp = max(vol.GetSpacing())                       # 一番粗い方向（たいていスライス厚）
        return float(np.clip(round(0.6 * sp, 1), 0.8, 1.5))   # 2mm→1.2, 0.5mm→0.8, 5mm→1.5

    @staticmethod
    def _aiFailText(e, tail, kind=""):
        """AI（別プロセス）が失敗した時の、短い理由。前は「Command '[…PythonSlicer.exe…' returned non-zero exit status 1.」としか出ず、理由（ライセンス・メモリ・ネットワーク）が分からなかった。
        tail = AI の出力の最後の方の行。分からない時は、最後の 1 行（無ければ元のエラー）"""
        low = "\n".join(tail[-40:]).lower()
        if kind != "total" and "license" in low: return "この AI はライセンスの登録が必要です（入口の「AI ライセンスを登録」から。無料）"
        if any(k in low for k in ("out of memory", "memoryerror", "unable to allocate", "bad allocation", "bad_alloc", "not enough memory")):
            return "メモリが足りません（ほかのアプリを閉じてから、もう一度作ってください）"
        if any(k in low for k in ("connectionerror", "urlopen error", "max retries exceeded", "getaddrinfo failed", "name resolution", "connecttimeout", "proxyerror", "sslerror", "certificate verify failed")):
            return "AI のデータを取り込めませんでした（初回だけネットワークが必要です。つながっているか確かめてください）"
        last = next((l.strip() for l in reversed(tail) if l.strip()), "")
        return (f"AI が途中で止まりました: {last[:140]}" if last else (str(e) or type(e).__name__)[:160])

    @staticmethod
    def _aiDevice():
        """AI（TotalSegmentator）がどこで動いたか。拡張と同じ決め方: CUDA の使える NVIDIA の GPU があれば GPU、無ければ CPU
        （拡張は「--device cpu／gpu」を自分で決めて渡す。Mac の GPU〔MPS〕は、今の拡張では使わない設定＝Mac では CPU）。
        PyTorch は、拡張が AI を動かす前に読み込んだものを見るだけ（ここで新しく読み込まない＝重くしない）。戻り値: ("GPU"/"CPU"/"不明", GPU の名前とメモリ)"""
        t = sys.modules.get("torch")
        if t is None: return "不明", None
        try:
            if t.backends.cuda.is_built() and t.cuda.is_available():
                pr = t.cuda.get_device_properties(t.cuda.current_device())
                return "GPU", f"{pr.name}・{pr.total_memory / 2 ** 30:.1f} GB"
        except Exception as e: return "不明", (str(e) or type(e).__name__)[:60]
        return "CPU", None

    def _runTS(self, vol, kind, status, label=None):
        try: import TotalSegmentator
        except ImportError as e: raise RuntimeError("AI の拡張（TotalSegmentator）が入っていません。HUCViewS のインストーラーをもう一度実行してください") from e
        tail = []                                                             # AI の出力の最後の方（失敗した時に理由を探す）
        tsl = TotalSegmentator.TotalSegmentatorLogic()
        tsl.logCallback = lambda t: slicer.app.processEvents()      # AI 計算中も画面（進捗表示）を止めない
        base = label or {"total": "1/4 臓器を自動認識中", "heartchambers": "2/4 心腔を自動認識中"}.get(kind, "AI で認識中")   # パッチの術前 CT の時は「2/4」を出さない
        tStart = time.time(); last = [0.0]

        def _logNonBlocking(proc, returnOutput=False):
            """AI（別プロセス）の出力を別スレッドで読む。画面はその間も動く（前は出力が途切れる 20〜60 秒ほど「応答なし」になった）"""
            import threading, queue
            from subprocess import CalledProcessError
            q = queue.Queue(); killed = [False]
            def reader():
                try:
                    while True:
                        try: line = proc.stdout.readline()
                        except UnicodeDecodeError: continue
                        if not line: break
                        q.put(line)
                        if sys.platform == "darwin" and "Saved in " in line:     # Mac: 保存後に AI の後片付けが終わらず止まることがある（元の拡張と同じ対処）
                            try: proc.kill()
                            except Exception: pass
                            killed[0] = True; break
                finally: q.put(None)
            threading.Thread(target=reader, daemon=True).start()
            output = ""
            while True:
                try: line = q.get(timeout=0.1)
                except queue.Empty:
                    slicer.app.processEvents()
                    el = time.time() - tStart
                    if el - last[0] >= 1.0:
                        last[0] = el
                        try: status(f"{base}（AI・{el:.0f} 秒）…")
                        except Exception: pass
                    continue
                if line is None: break
                if returnOutput: output += line
                tail.append(line.rstrip()); del tail[:-40]
                tsl.log(line.rstrip())
            proc.wait()
            if proc.returncode != 0 and not killed[0]: raise CalledProcessError(proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr)
            return output if returnOutput else None
        tsl.logProcessOutput = _logNonBlocking
        import importlib.util as _iu
        if _iu.find_spec("torch") is None or _iu.find_spec("totalsegmentator") is None:   # 新しく入れた PC では初回だけ AI の部品を入れる（読み込みはしない＝速い）
            status("初回だけ AI の部品（PyTorch・TotalSegmentator）を入れています。数分〜十数分かかります…"); slicer.app.processEvents()
            try: tsl.setupPythonRequirements()
            except Exception as e:
                import traceback; traceback.print_exc()
                raise RuntimeError("AI の部品を入れられませんでした（ネットワークにつながっているか確かめてください）: " + (str(e) or type(e).__name__)[:120]) from e
        seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"{vol.GetName()} {kind}")
        inp = self._aiInput(vol, kind)
        seg.SetReferenceImageGeometryParameterFromVolumeNode(inp)
        t0 = time.time()
        try:
            if kind == "total":
                tsl.process(inp, seg, quality="fast", task="total")
            else:
                tsl.process(inp, seg, task="heartchambers_highres")
        except Exception as e:
            slicer.mrmlScene.RemoveNode(seg)
            raise RuntimeError(self._aiFailText(e, tail, kind)) from e
        finally:
            if inp is not vol: slicer.mrmlScene.RemoveNode(inp)
        dt = time.time() - t0
        print(f"AI {kind}: {dt:.0f} 秒（渡した CT {tuple(round(x, 2) for x in inp.GetSpacing()) if inp is not vol else '元のまま'}）")
        try:                                                                  # 性能の記録用（秒・どこで動いたか。患者情報なし）
            dev, gname = self._aiDevice()
            r = {"s": round(dt), "dev": dev}
            if gname: r["gpu"] = gname
            self.aiRec = dict(getattr(self, "aiRec", None) or {}); self.aiRec[kind] = r
        except Exception as e: print("ai record:", e)
        if seg.GetSegmentation().GetNumberOfSegments() == 0:
            slicer.mrmlScene.RemoveNode(seg); raise RuntimeError("結果が空でした")
        seg.SetReferenceImageGeometryParameterFromVolumeNode(vol)
        if seg.GetDisplayNode(): seg.GetDisplayNode().SetVisibility(False)
        self._put(seg)
        return seg

    def calibrate(self, work):
        """この CT の造影具合から閾値を決める（心筋・血液・脂肪の CT 値をラベルで実測）"""
        from scipy import ndimage
        arr = slicer.util.arrayFromVolume(work)
        tot = self._findSegmentation(); hc = self._findChambers()
        def med(mask, q=50):
            if mask is None: return None
            m = ndimage.binary_erosion(mask, iterations=1)
            if m.sum() < 200: m = mask
            if m.sum() < 50: return None
            return float(np.percentile(arr[m], q))
        myo = med(self._segmentMaskArray(hc, work, ("myocardium",))) if hc else None
        bl = med(self._segmentMaskArray(hc, work, ("left ventricle", "aorta"))) if hc else None
        if bl is None and tot: bl = med(self._segmentMaskArray(tot, work, ("aorta",)))
        blHi = None
        if hc: blHi = med(self._segmentMaskArray(hc, work, ("left ventricle", "left atrium", "aorta")), 99)
        rv = med(self._segmentMaskArray(hc, work, ("right ventricle",))) if hc else None
        fat = None
        heart = self._segmentMaskArray(tot, work, ("heart",)) if tot else None
        if heart is not None and heart.sum() > 1000:
            ring = ndimage.binary_dilation(heart, iterations=4) & ~ndimage.binary_dilation(heart, iterations=1)
            v = arr[ring]; v = v[(v > -200) & (v < -30)]
            if len(v) > 200: fat = float(np.median(v))
        if myo is None: myo = 84.0 if bl is None else min(120.0, 0.5 * bl)   # ラベルがない時の仮値
        if fat is None: fat = -90.0
        c = dict(self.DEFAULT_CAL)
        if bl is not None and bl > myo + 30:
            c["blood_lo"] = float(np.clip(myo + 0.27 * (bl - myo), 110, 300))
        c["wall_lo"] = float(np.clip(fat + 0.40 * (myo - fat), -60, 20))
        c["wall_hi"] = c["blood_lo"] - 5
        c["blood_hi"] = float(max(900.0, (blHi or 0) + 150))
        c.update(myo=myo, blood=bl, rv=rv, fat=fat)
        self.calib = c
        return c

    def qualityReport(self, vol, c, t):
        sp = vol.GetSpacing(); thick = max(sp)
        lines = [f"できました（{t:.0f} 秒）。上の「見たいもの」（心臓／大動脈／血管すべて／骨と血管）で切り替えられます。"]
        lines.append(f"自動調整: 血液 ≥{c['blood_lo']:.0f} HU / 壁 {c['wall_lo']:.0f}〜{c['wall_hi']:.0f} HU / メッシュ {self.lastSpacing:.1f} mm")
        note = []
        if c.get("blood") is not None:
            d = c["blood"] - c["myo"]
            note.append(f"左心系の造影 {c['blood']:.0f} HU（心筋 {c['myo']:.0f}）")
            if d < 120: note.append("⚠ 造影が薄く、壁と血液の境界が不確か")
        else:
            note.append("⚠ 心腔ラベルなし（heartchambers 未実行/失敗）→ 左右の色分け・心筋は作れません")
        if c.get("rv") is not None and c["rv"] - c["myo"] < 80:
            note.append(f"右心系の造影が薄い（{c['rv']:.0f} HU）→ 右心系はAIラベル頼み")
        if thick > 1.5: note.append(f"スライス {thick:.1f} mm：薄い壁は補完（グレー）が多くなります")
        syn = getattr(self, "_wallSynth", None); ev = getattr(self, "_wallEvidence", None)
        if syn is not None and ev is not None:
            frac = syn.sum() / max(1, syn.sum() + ev.sum())
            note.append(f"補った壁 {frac*100:.0f}%")
        return "\n".join(lines + ["／".join(note)])

    def autoPipeline(self, vol, specs, boneLayer, status=lambda m: None):
        """① ボタン: セグメンテーション → 閾値の自動調整 → 3D 作成 → 品質メモ"""
        if getattr(self, "_building", False): raise RuntimeError("いま作っている途中です。終わるまでお待ちください")
        self._building = True
        try: return self._autoPipeline(vol, specs, boneLayer, status)
        finally: self._building = False

    def _autoPipeline(self, vol, specs, boneLayer, status):
        t0 = time.time()
        tm = {}; lap = [time.time()]                                          # 段階ごとの秒数（性能の記録用）
        def mark(k):
            now = time.time(); tm[k] = round(now - lap[0], 1); lap[0] = now
        self._noDepthPeeling()                                                # 作る途中の描画でも剥離を使わない（AMD で固まる）
        self.sourceVolume = vol; self.calib = {}; self.aiRec = {}
        if self._segFor(vol, "total") is None:
            status("1/4 臓器を自動認識中（AI）…"); slicer.app.processEvents()
            self._runTS(vol, "total", status); mark("ai_total")
        lap[0] = time.time()
        if self._segFor(vol, "heartchambers") is None:
            status("2/4 心腔を自動認識中（AI）…"); slicer.app.processEvents()
            self.hcError = None
            try: self._runTS(vol, "heartchambers", status)
            except Exception as e:
                import traceback; traceback.print_exc()
                self.hcError = str(e) or type(e).__name__; print("heartchambers:", e)
            mark("ai_heart")
        lap[0] = time.time()
        spacing = self.autoSpacing(vol); self.lastSpacing = spacing
        status("3/4 造影の具合を測って閾値を調整中…"); slicer.app.processEvents()
        work = self._resample(vol, spacing); self.workVolume = work
        c = self.calibrate(work)
        try:
            import json
            work.SetAttribute("CardiacView.calib", json.dumps({k: v for k, v in c.items() if isinstance(v, (int, float)) or v is None}))
            work.SetAttribute("CardiacView.source", vol.GetName())
        except Exception as e: print("calib attr:", e)
        print("calib:", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in c.items()})
        specs = [dict(sp) for sp in specs]
        for sp in specs:
            if sp["name"] == "血液・血管": sp["lo"] = int(round(c["blood_lo"]))
        mark("calib")
        status("4/4 3D を作成中…"); slicer.app.processEvents()
        self.wallFill = True
        self.buildLayers(vol, specs, spacing, boneLayer, status)
        mark("surf")
        try:                                                                  # VR もここで 1 回だけ作っておく（保存されて、開いた時に VR がすぐ出る）
            status("VR を準備中…"); slicer.app.processEvents()
            c0 = self._camera(); cst = (c0.GetPosition(), c0.GetFocalPoint(), c0.GetViewUp(), c0.GetParallelScale())
            self.vrPrepError = None
            self.setupVR(status)
            if self.vrDisplay is not None: self.vrDisplay.SetVisibility(False)
            c0.SetPosition(*cst[0]); c0.SetFocalPoint(*cst[1]); c0.SetViewUp(*cst[2]); c0.SetParallelScale(cst[3])
        except Exception as e:
            import traceback; traceback.print_exc()
            self.vrPrepError = str(e); print("VR 準備:", e)
        mark("vr")
        self._hideInternalVolumes()
        rep = self.qualityReport(vol, c, time.time() - t0)
        issues = self.checkCase()
        if issues: rep += "\n⚠ 点検: " + "／".join(issues)
        tm["all"] = round(time.time() - t0, 1)
        try: self._buildPerfLog(vol, tm, issues)
        except Exception as e: print("build perf log:", e)
        return rep

    @staticmethod
    def _issueCodes(issues, hcError=None):
        """点検の結果を、性能の記録に残せる短い種類に直す（画像の名前・エラーの文そのものは残さない）"""
        codes = []
        for m in issues or []:
            for key, code in (("元の CT が見つかりません", "元の CT なし"), ("作業用の画像", "作業用の画像を使用"), ("全身ラベルがありません", "全身ラベルなし"),
                              ("心腔ラベルがありません", "心腔ラベルなし"), ("VR の準備に失敗", "VR 準備の失敗")):
                if key in m and code not in codes: codes.append(code)
            if m.startswith("一部が作れませんでした"):
                parts = re.findall(r"(?:^|・|: )([^・:（]+)（", m)
                codes.append("部品の失敗: " + "・".join(p.strip() for p in parts if p.strip())[:40])
        if hcError and "心腔ラベルなし" in codes:
            low = str(hcError)
            why = "ライセンス" if "ライセンス" in low else ("メモリ" if "メモリ" in low else ("ネットワーク" if "ネットワーク" in low else "そのほか"))
            codes[codes.index("心腔ラベルなし")] = f"心腔ラベルなし（{why}）"
        return codes

    def _buildPerfLog(self, vol, tm, issues):
        """3D を作った時間を段階ごとに、性能の記録へ（患者情報なし: 秒・画像の大きさ・AI がどこで動いたか・PyTorch の種類・点検の種類だけ）。
        PyTorch の種類（例 2.14.1+cpu ＝ CPU 専用）で、GPU 用の部品を入れると速くなる PC かが分かる"""
        import importlib.metadata as md
        try: tv = md.version("torch")
        except Exception: tv = None
        rec = {"kind": "3D を作る時間(秒)", "t": tm, "ai": getattr(self, "aiRec", None) or {}, "torch": tv,
               "ct": list(vol.GetImageData().GetDimensions()) if vol is not None and vol.GetImageData() is not None else None,
               "mm": round(float(getattr(self, "lastSpacing", 0) or 0), 2), "check": self._issueCodes(issues, getattr(self, "hcError", None))}
        self._perfLog(rec)

    def adoptScene(self):
        """保存した症例（.mrb）を開いたあと、シーン中の CV モデルを引き継ぐ"""
        import json
        self._hideInternalVolumes()                                          # 前の版で保存した症例でも、内部用の画像を CT の欄に出さない
        self.layerModels = {}; self.visible = {}
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            nm = n.GetName()
            if nm == "CV パッチの範囲（元の塊）": n.SetName("cv_patch_blob"); continue          # 昨日の版で保存した症例: 隠した元の塊は層にしない
            if not nm.startswith("CV ") or nm == "CV 心筋断面": continue
            key = nm[3:]; self.layerModels[key] = n
            d = n.GetDisplayNode(); self.visible[key] = bool(d.GetVisibility()) if d else False
        if "心筋" in self.layerModels: self.visible["心筋"] = True
        self.workVolume = None; self.sourceVolume = None
        self._patchRemoved = []                                              # 前に開いていた症例の「外したパッチ」の記録を持ち越さない
        self._wallSynth = None; self._wallEvidence = None; self._wallFor = None; self._vrExtra = set()   # 前の症例の「補った壁」の配列・VR の途中で出した層も持ち越さない
        try:
            k = self._purgeExportColors()
            if k: print(f"[CardiacView] 使われていない色表を {k} 個外しました（前の版のラベル書き出しの残り）")
        except Exception as e: print("色表の片付け:", e)
        vols = [v for v in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
                if not v.IsA("vtkMRMLLabelMapVolumeNode") and not v.IsA("vtkMRMLVectorVolumeNode")]   # VR（CV VR）・ラベルは作業用の画像ではない
        work = next((v for v in vols if v.GetAttribute("CardiacView.calib") is not None), None) \
            or next((v for v in vols if "_cv" in v.GetName()), None)
        if work is not None:
            self.workVolume = work
            try: self.calib = json.loads(work.GetAttribute("CardiacView.calib") or "{}")
            except Exception: self.calib = {}
            try: self.sourceVolume, how = self._findSourceFor(work)
            except Exception as e:                                             # 探し方で失敗しても、症例は前の版と同じように開く
                import traceback; traceback.print_exc()
                self.sourceVolume = slicer.mrmlScene.GetFirstNodeByName(work.GetAttribute("CardiacView.source") or work.GetName().split("_cv")[0]); how = f"名前（探し直しに失敗: {e}）"
            print(f"[CardiacView 点検] 作業用の画像: {work.GetName()} → 元の CT: {self.sourceVolume.GetName() if self.sourceVolume else 'なし'}（{how}）")
        try: self.lastSpacing = float(min(self.workVolume.GetSpacing())) if self.workVolume else 1.2
        except Exception: self.lastSpacing = 1.2
        self.clip = slicer.mrmlScene.GetFirstNodeByName("CV clip")
        try:
            self.on4D = False
            if self._adopt4D(): self.vr4D.SetVisibility(False)
        except Exception as e: print("4D adopt:", e)
        self.cutPlane = slicer.mrmlScene.GetFirstNodeByName("切断面")
        self.cutAxis = None
        self.vrOn = False; self.vrDisplay = None; self.vrNode = None          # 保存した時の VR は隠す（残ると面にかぶり、切っても VR だけ別の位置で切れる）
        for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"):
            if d is getattr(self, "vr4D", None): continue
            try: d.SetVisibility(False); d.SetClipping(False)
            except Exception: pass
        self._pMask = {}; self._pMaskKey = {}; self.paintOn = False; self._painting = False; self._strokes = []
        pn = self.layerModels.get("パッチ")
        if pn is not None:
            try: self._strokes = json.loads(pn.GetAttribute("CV.patchStrokes") or "[]")
            except Exception: self._strokes = []
            if not self._strokes and pn.GetAttribute("CV.patchSheet") != "1":
                try: self.patchToSheet()
                except Exception as e: print("patch sheet:", e)
        try:
            w = slicer.modules.cardiacview.widgetRepresentation().self()
            w.paintButton.blockSignals(True); w.paintButton.checked = False; w.paintButton.blockSignals(False)
        except Exception: pass
        for n in self._measureNodes():                                       # 面積の計測: 点を動かした時に面積を出し直す見張りを付け直す（見張りは保存されない）
            if n.GetAttribute("CV.measure") == "area":
                try: self._watchArea(n)
                except Exception as e: print("area watch:", e)
        self._updateBounds()
        try: self.studioLighting(self._bg(), ssao=True)
        except Exception: pass
        try: self.applyPalette(common.CUR_PALETTE, rebuildVR=False)               # 保存した症例も、今の色合いで
        except Exception as e: print("palette:", e)
        return len(self.layerModels)
