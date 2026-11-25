# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 性能の自動調整（GPU なしの PC でも、なめらかさ優先）・性能の記録（この PC と NAS）
CardiacViewLogic の一部（PerfMixin）。元の CardiacView.py の中身をそのまま移したもの。"""
from .common import *


class PerfMixin:
    # ---------------------------------------------------------------- 性能の自動調整（GPU なしの PC でも、なめらかさ優先）
    PERF_TARGET_MS = 30.0          # 回転 1 コマの目標（約 33fps）
    VR_STILL_MAX_MS = 400.0        # 止まった時は最高画質（心内の細かい構造）。1 コマ 0.4 秒を超える PC だけ一段下げる

    def _frameMs(self, n=6):
        v = self._view(); rw = v.renderWindow(); cam = self._camera().GetCamera()
        def done():
            try: rw.WaitForCompletion()                    # GPU が描き終わるまで待ってから計る
            except Exception: rw.GetPixelData(0, 0, 0, 0, 1)
        rw.Render(); done(); t = time.time()
        for _ in range(n): cam.Azimuth(4); rw.Render(); done()
        dt = (time.time() - t) / n
        for _ in range(n): cam.Azimuth(-4)
        rw.Render()
        return dt * 1000.0

    def tunePerformance(self, status=lambda m: None):
        """このPCの描画の速さを測って、重い効果を切る・メッシュを間引く（結果は self.perf とログに残す）"""
        v = self._view(); rw = v.renderWindow(); ren = rw.GetRenderers().GetFirstRenderer()
        perf = {}
        try:
            cap = rw.ReportCapabilities() or ""
            perf["gpu"] = next((l.split(":", 1)[1].strip() for l in cap.splitlines() if "renderer string" in l), "?")
        except Exception: perf["gpu"] = "?"
        try:
            st = qt.QSettings()                                 # PC の機種は 1 日 1 回だけ記録（GPU 載せ替えの判断用）
            if st.value("HUCViewS/pcInfoDay") != time.strftime("%Y%m%d"):
                gi = self._gpuInfo(); perf["pc"] = gi.get("pc"); perf["nvidia"] = gi.get("nvidia"); st.setValue("HUCViewS/pcInfoDay", time.strftime("%Y%m%d"))
        except Exception: pass
        ms = self._frameMs(); perf["surf_ms_start"] = round(ms, 1); steps = []
        if ms > self.PERF_TARGET_MS and ren.GetUseSSAO():
            ren.SetUseSSAO(False); ms = self._frameMs(); steps.append("SSAO off")
        if ms > self.PERF_TARGET_MS and ren.GetUseDepthPeeling():
            ren.SetUseDepthPeeling(False)
            try: self._viewNode().SetUseDepthPeeling(False)
            except Exception: pass
            ms = self._frameMs(); steps.append("depth peeling off")
        k = 0
        while ms > self.PERF_TARGET_MS and k < 3:                     # メッシュを半分ずつ間引く（最大 3 回 = 1/8）
            for name, n in self.layerModels.items():
                if not n or n.GetPolyData() is None or n.GetPolyData().GetNumberOfPolys() < 60000: continue
                dec = vtk.vtkQuadricDecimation(); dec.SetInputData(n.GetPolyData()); dec.SetTargetReduction(0.5); dec.Update()
                nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(dec.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOff(); nm.Update()
                pd = vtk.vtkPolyData(); pd.DeepCopy(nm.GetOutput())
                n.SetAndObservePolyData(pd)
            if self.layerModels.get("心臓壁") is not None:
                try: self.colorWallEpiEndo()
                except Exception: pass
            k += 1; ms = self._frameMs(); steps.append(f"mesh 1/{2 ** k}")
        perf["surf_ms"] = round(ms, 1); perf["steps"] = steps
        self.perf = perf
        self._perfLog(perf)
        print("性能:", perf)
        status(f"描画の速さ: 1コマ {perf['surf_ms']:.0f} ms" + (f"（自動で軽くしました: {', '.join(steps)}）" if steps else ""))
        return perf

    def _gpuInfo(self):
        """GPU の名前とメモリ（NVIDIA なら nvidia-smi）。診断用"""
        info = {}
        try:
            cap = self._view().renderWindow().ReportCapabilities() or ""
            info["gl"] = next((l.split(":", 1)[1].strip() for l in cap.splitlines() if "renderer string" in l), "?")
        except Exception: info["gl"] = "?"
        import sys, subprocess, platform
        win = sys.platform == "win32"; kw = {"creationflags": 0x08000000} if win else {}
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, timeout=5, **kw)
            if r.returncode == 0: info["nvidia"] = r.stdout.decode("utf-8", "replace").strip()
        except Exception: pass
        try:                                                   # PC の機種・CPU・メモリ（GPU を載せ替えられるかの判断用）
            if win:
                ps = ("$c=Get-CimInstance Win32_ComputerSystem; $p=Get-CimInstance Win32_Processor | Select-Object -First 1; "
                      "Write-Output ($c.Manufacturer + ' | ' + $c.Model + ' | ' + $p.Name + ' | RAM ' + [math]::Round($c.TotalPhysicalMemory/1GB) + 'GB')")
                r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=10, **kw)
                if r.returncode == 0: info["pc"] = r.stdout.decode("utf-8", "replace").strip()
            elif sys.platform == "darwin":
                q = lambda k: subprocess.run(["sysctl", "-n", k], capture_output=True, timeout=5).stdout.decode().strip()
                info["pc"] = f"Apple | {q('hw.model')} | {q('machdep.cpu.brand_string')} | RAM {round(int(q('hw.memsize') or 0) / 2**30)}GB"
            else:
                info["pc"] = f"{platform.system()} | {platform.machine()} | {platform.processor()}"
        except Exception: pass
        return info

    def _installPerfMon(self):
        """実際に使っている時の 1 コマの速さを場面別に数えて、2 分ごとに性能ログへ（患者情報なし: 時間と設定だけ）。
        医局 PC で何が重いかを離れた所から確かめるため"""
        try:
            rw = self._view().renderWindow()
            reg = getattr(slicer, "_cvPerf", None)
            if reg and reg.get("rw") is rw: return
            if reg:
                for t in reg.get("tags", []):
                    try: reg["rw"].RemoveObserver(t)
                    except Exception: pass
                try: reg["timer"].stop()
                except Exception: pass
            st = {"rw": rw, "last": None, "t0": None, "b": {}}
            def start(c=None, e=None): st["t0"] = time.perf_counter()
            def end(c=None, e=None):
                t = time.perf_counter(); L = _cvCur()
                if L is None: return
                key = ("VR" if getattr(L, "vrOn", False) else "面") + "/" + str(getattr(L, "layoutKind", "3d")) + ("/切断" if L.cutAxis is not None else "")
                b = st["b"].setdefault(key, {"gap": [], "cpu": []})
                if st["last"] is not None and t - st["last"] < 1.0 and len(b["gap"]) < 5000: b["gap"].append((t - st["last"]) * 1000)
                if st["t0"] is not None and len(b["cpu"]) < 5000: b["cpu"].append((t - st["t0"]) * 1000)
                st["last"] = t
            st["tags"] = [rw.AddObserver(vtk.vtkCommand.StartEvent, start), rw.AddObserver(vtk.vtkCommand.EndEvent, end)]
            def flush():
                L = _cvCur()
                if L is None or not st["b"]: return
                out = {}
                for k, b in st["b"].items():
                    g = sorted(b["gap"]); cp = sorted(b["cpu"])
                    if len(g) < 10: continue
                    out[k] = dict(n=len(g), gap_med=round(g[len(g) // 2], 1), gap_p90=round(g[int(len(g) * 0.9)], 1),
                                  cpu_med=round(cp[len(cp) // 2], 1) if cp else None, cpu_max=round(cp[-1], 1) if cp else None)
                st["b"] = {}
                if not out: return
                vn = L._viewNode()
                rec = {"kind": "操作中のコマ時間(ms)", "scenes": out, "q": vn.GetVolumeRenderingQuality(), "os": vn.GetVolumeRenderingOversamplingFactor(),
                       "isd": getattr(L, "vrFastISD", None), "down": getattr(L, "vrDownUsed", None),
                       "ssao": bool(rw.GetRenderers().GetFirstRenderer().GetUseSSAO()), "size": list(rw.GetSize())}
                L._perfLog(rec)
            tm = qt.QTimer(); tm.setInterval(120000); tm.connect("timeout()", flush); tm.start()
            st["timer"] = tm; st["flush"] = flush
            slicer._cvPerf = st
        except Exception as e: print("perf mon:", e)

    def _perfLog(self, rec):
        """性能の記録（患者情報なし: GPU 名・描画時間だけ）。PC の中と、届けば NAS の logs にも残す（離れた所から調整できるように）"""
        import json
        pc = os.environ.get("COMPUTERNAME") or __import__("socket").gethostname()
        rec = dict(rec)                                                      # 呼んだ側の dict（self.perf など）は書き換えない
        if appVer(): rec.setdefault("ver", appVer())                          # どの版の記録か（更新が届いたかを離れた所から確かめる）
        line = time.strftime("%Y-%m-%d %H:%M ") + pc + " " + json.dumps(rec, ensure_ascii=False) + "\n"
        home = os.path.expanduser("~")
        for d in (home, self._nasLogDir()):
            if not d: continue
            t0 = time.time()
            try:
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "HUCViewS_performance.txt" if d == home else f"{pc}_performance.txt"), "a", encoding="utf-8") as f: f.write(line)
                if d != home and time.time() - t0 > 2.0: slicer._cvNasLog = (time.time(), None)      # 書くのに時間のかかる NAS は、しばらく休む（画面を止めない）
            except Exception:
                if d != home: slicer._cvNasLog = (time.time(), None)

    NAS_RETRY_S = 1800.0     # NAS に届かなかった・遅かった時、次に確かめるまでの時間（秒）

    def _nasLogDir(self):
        """性能の記録を置く NAS のフォルダ（届く時だけ）。届かない NAS の確かめは数秒〜数十秒戻らない（その間、画面が止まる）ので、
        結果を 30 分覚えておく（前は 2 分ごとの記録のたびに確かめていて、NAS の無い所で使うと 2 分おきに止まった）"""
        try:
            hv = os.environ.get("HEARTVIEW_HOME")
            if not hv: return None
            st = getattr(slicer, "_cvNasLog", None)
            if st and 0 <= time.time() - st[0] < self.NAS_RETRY_S: return st[1]
            src = None
            for enc in ("utf-8-sig", "cp932"):                               # 起動時の更新（heartview_start.py）と同じ読み方
                try: src = open(os.path.join(os.path.dirname(hv), "update_source.txt"), encoding=enc).read().strip(); break
                except Exception: pass
            d = None
            if src and not src.lower().startswith(("http://", "https://")):   # ネット（GitHub）から更新する PC には NAS が無い
                t0 = time.time(); ok = os.path.isdir(src); dt = time.time() - t0
                if dt > 2.0: print(f"[CardiacView] NAS の確かめに {dt:.0f} 秒かかりました（届く: {ok}）。しばらく確かめ直しません")
                d = os.path.join(src, "logs") if ok else None
            slicer._cvNasLog = (time.time(), d)
            return d
        except Exception: return None

    WEAK_GPU = ("T400", "T600", "T1000", "P400", "P600", "P620", "P1000", "GT 7", "GT 10", "MX", "UHD", "IRIS", "QUADRO K")

    @classmethod
    def _weakGpuName(cls, name):
        """GPU の名前が「弱い」の一覧に当たるか。型番（T600・P400 など）は、前後が英数字でない時だけ当たりとする
        （前は部分一致で、「P400」が Quadro P4000 に、「P600」が P6000 に当たって、強い GPU を弱いと決めていた）"""
        name = (name or "").upper()
        for k in cls.WEAK_GPU:
            if re.fullmatch(r"[TP]\d+", k):
                if re.search(r"(?<![A-Z0-9])" + k + r"(?!\d)", name): return True
            elif k in name: return True
        return False

    def _vrDownFactor(self):
        """VR の格子の粗さ（1 = そのまま、2 = 半分）。GPU が弱い（4GB 以下など）PC は 2。PC ごとに覚える"""
        st = qt.QSettings(); v = st.value("HUCViewS/vrDown")
        if v:
            try: return max(1, int(v))
            except Exception: pass
        info = self._gpuInfo(); name = (info.get("nvidia") or info.get("gl") or "").upper()
        mem = None
        try: mem = int(re.search(r"(\d+)\s*MIB", name).group(1))
        except Exception: pass
        weak = self._weakGpuName(name) or (mem is not None and mem <= 4096)
        f = 2 if weak else 1; st.setValue("HUCViewS/vrDown", f); return f

    def _tuneVR(self):
        """VR の止まった時の画質を、この PC で安全に決める。
        標準 → 最高 → 最高＋細かく、と軽い順に測り、1 コマが遅すぎたらそこで止める（2 秒を超えると Windows が GPU をリセットして強制終了するため）。
        結果は PC ごとに覚えて、次回からは測らない"""
        vn = self._viewNode(); st = qt.QSettings(); key = f"HUCViewS/vrTune3_d{int(getattr(self, 'vrDownUsed', 1) or 1)}"
        try: vn.SetExpectedFPS(20.0)
        except Exception: pass
        m = self._vrMapper()
        saved = st.value(key)
        if saved:
            try:
                f = str(saved).split(","); self.vrStillQ = max(1, int(f[0])); self.vrOversample = float(f[1]); self.vrFastISD = float(f[2]) if len(f) > 2 else 1.5
                vn.SetVolumeRenderingOversamplingFactor(self.vrOversample); vn.SetVolumeRenderingQuality(self.vrStillQ)
                if m is not None: m.AutoAdjustSampleDistancesOff(); m.SetImageSampleDistance(1.0)
                return
            except Exception: pass
        rec = dict(self._gpuInfo())
        vn.SetVolumeRenderingOversamplingFactor(1.0); vn.SetVolumeRenderingQuality(1)      # 「標準」から測る（最初の VR もこの画質なので安全）
        if m is not None: m.AutoAdjustSampleDistancesOff(); m.SetImageSampleDistance(1.0)
        tn = self._frameMs(1); rec["vr_normal_ms"] = round(tn, 1)
        q, osf = 1, 1.0
        if tn < 25:                                                       # 最高画質は標準の 15〜20 倍重い（実測）。2 秒を超えない見込みの時だけ試す
            vn.SetVolumeRenderingQuality(2); tm = self._frameMs(1); rec["vr_max_ms"] = round(tm, 1)
            if tm <= self.VR_STILL_MAX_MS: q = 2
            if tm < 150:
                vn.SetVolumeRenderingOversamplingFactor(2.0); t2 = self._frameMs(1); rec["vr_max_os2_ms"] = round(t2, 1)
                if t2 <= self.VR_STILL_MAX_MS: osf = 2.0
        isd = float(np.clip(round(2 * np.sqrt(max(tn, 1.0) / 30.0)) / 2, 1.0, 4.0))   # 動かす間は 1 コマ 30ms 前後になる粗さ
        self.vrStillQ, self.vrOversample, self.vrFastISD = q, osf, isd
        vn.SetVolumeRenderingOversamplingFactor(osf); vn.SetVolumeRenderingQuality(q)
        rec["vr_still"] = {1: "normal", 2: "max"}[q] + (" x2" if osf > 1 else ""); rec["vr_fast_isd"] = isd; rec["vr_down"] = int(getattr(self, "vrDownUsed", 1) or 1)
        if tn > 400 and rec["vr_down"] == 1:
            st.setValue("HUCViewS/vrDown", 2); rec["next"] = "次の VR から格子を 1/2 に"       # それでも重い PC は次回から粗くする
        st.setValue(key, f"{q},{osf},{isd}")
        perf = getattr(self, "perf", {}); perf.update(rec); self.perf = perf
        self._perfLog(rec); print("VR 性能:", rec)
