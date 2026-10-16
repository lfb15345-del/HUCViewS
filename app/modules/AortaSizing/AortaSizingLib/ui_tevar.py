# -*- coding: utf-8 -*-
"""大動脈サイジング: 3 計画 の画面の動き（真腔・仮想グラフト・範囲・SINE）
AortaSizingWidget の一部（TevarUIMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class TevarUIMixin:

    def _tvRef(self, s):
        """位置を「いちばん近い近位の分枝 + mm」で（無ければベースラインから）"""
        L = self.logic; best = None
        for m in L.markers:
            nm = m["name"].replace("（推定）", "")
            if nm in self.SHORT and m["s"] <= s + 0.5 and (best is None or m["s"] > best[1]): best = (nm, m["s"])
        return f"{self.SHORT[best[0]]} +{s - best[1]:.0f} mm" if best else f"{L.rel(s):+.0f} mm"

    def _tvEnter(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください"); return
        pl0 = getattr(L, "plan", None)
        if pl0 is not None and pl0.get("path") in L.frames and pl0["path"] != L.path:   # 計画を作った経路（右腸骨など）に戻す
            try: L.curS = float(pl0["p"]); self._busy(L.selectPath, pl0["path"], self._say); self._syncPathButtons()
            except Exception as e: print("tv path:", e)
        pl = L.planInit()
        try: self.osBtns[[0.0, 0.05, 0.10, 0.15, 0.20].index(round(pl["os"], 2))].checked = True
        except Exception: pass
        self.tlBtn.blockSignals(True); self.tlBtn.checked = bool(pl.get("tl")); self.tlBtn.blockSignals(False)
        self.flapBtns[{"chronic": 0, "acute": 1, "fixed": 2}.get(pl.get("flap", "chronic"), 0)].checked = True
        self.endBtns[1 if pl.get("ends") == "asis" else 0].checked = True
        self.axisBtns[0 if (pl.get("axis") or ("tl" if pl.get("tl") else "cl")) == "cl" else 1].checked = True
        L.showOverlay3D("aorta", self.ovAorta.checked); L.showOverlay3D("post", self.ovPost.checked)
        if not getattr(self, "_tvFitted", False):
            self._tvFitted = True
            try: qt.QTimer.singleShot(300, lambda: L.fit3DToGraft("lao"))
            except Exception: pass
        for sp, key in ((self.dpSpin, "dp"), (self.ddSpin, "dd")):
            sp.blockSignals(True); sp.value = int(pl.get(key) or 0); sp.blockSignals(False)
        self.tvShowBtn.blockSignals(True); self.tvShowBtn.checked = bool(pl.get("on", True)); self.tvShowBtn.blockSignals(False)
        self._busy(L.planDraw); self._tvRefresh()

    def _tvRefresh(self):
        L = self.logic
        if L.P is None or not hasattr(self, "tvRows"): return
        pl = L.planInit()
        if hasattr(self, "tvLen"): self._tvLenSet()
        try: (Dp, mp, ap), (Dd, md, ad) = L.planDiams()
        except Exception as e: print("tv:", e); return
        for key, s, D, mD, man in (("p", pl["p"], Dp, mp, ap), ("d", pl["d"], Dd, md, ad)):
            pos, dia = self.tvRows[key]; pos.setText(self._tvRef(s))
            tlt = ""
            if pl.get("tl") and L.tlValid():
                dq = L.tl["deq"][L._k(s)]; tlt = f"・真腔 {dq:.0f}" if np.isfinite(dq) else ""
            dia.setText(("—" if mD is None else f"{mD:.1f}") + tlt + " → " + ("—" if D is None else f"<b>{D:.0f} mm</b>") + ("（手入力）" if man else ""))
        if Dp and Dd:
            gr = getattr(L, "_graftRad", None); ft = ""; fd = getattr(L, "_planDrawn", None)
            if gr is not None and fd is not None and len(fd):
                ft = (f"。白い筒 = 広がった形の予測（{('慢性: フラップを押して広がる・ガターが残る' if gr['flap'] == 'chronic' else ('急性: 丸く広がる' if gr['flap'] == 'acute' else 'フラップは動かない: 術前の真腔の中だけ')) if gr['tl'] else '内腔の中で広がる'}）"
                      f" {np.nanmin(fd):.0f}〜{np.nanmax(fd):.0f} mm。断面の白い輪の数字 = 広がった径 / 名目の径")
            self.tvSummary.setText(f"長さ {pl['d'] - pl['p']:.0f} mm・径 {Dp:.0f} → {Dd:.0f} mm（{'テーパー' if abs(Dp - Dd) > 0.5 else 'ストレート'}）"
                                   f"・オーバーサイズ {pl['os'] * 100:.0f}%" + (ft or "　白い筒 = 計画（断面にも輪郭）"))
        self._sineRefresh()
        try: self._flText()
        except Exception: pass
        ac = getattr(L, "actual", None)
        post = {r["name"]: r for r in L.coverage(ac["lo"], ac["hi"])} if ac else {}
        rows = L.coverage(pl["p"], pl["d"]); t = self.covTable; t.setRowCount(len(rows)); self._covRows = rows
        col = {"cover": "#5fd36e", "edge": "#ffcc33", "open": "#ff6b6b", "block": "#ff6b6b", "ok": "#9cc9ff"}
        for i, rw in enumerate(rows):
            vals = [rw["name"], self._tvRef(rw["s"]), rw["text"], post.get(rw["name"], {}).get("text", "")]
            for j, v in enumerate(vals):
                it = qt.QTableWidgetItem(v)
                if j == 2: it.setForeground(qt.QBrush(qt.QColor(col[rw["state"]])))
                if j == 3 and rw["name"] in post: it.setForeground(qt.QBrush(qt.QColor(col[post[rw["name"]]["state"]])))
                t.setItem(i, j, it)
        t.resizeColumnsToContents()
        cmp_ = L.comparePost()
        if cmp_:
            vals = {("p", "plan"): self._tvRef(pl["p"]), ("p", "post"): self._tvRef(ac["lo"]), ("p", "diff"): f"{cmp_['dP']:+.0f} mm",
                    ("d", "plan"): self._tvRef(pl["d"]), ("d", "post"): self._tvRef(ac["hi"]), ("d", "diff"): f"{cmp_['dD']:+.0f} mm",
                    ("len", "plan"): f"{cmp_['planLen']:.0f} mm", ("len", "post"): f"{cmp_['realLen']:.0f} mm", ("len", "diff"): f"{cmp_['realLen'] - cmp_['planLen']:+.0f} mm"}
            if "Dreal" in cmp_:
                vals.update({("dia", "plan"): (f"{cmp_['Dplan']:.0f} mm（名目 {cmp_['Dnom']:.0f}）" if cmp_.get("Dnom") and cmp_["Dnom"] - cmp_["Dplan"] > 0.5 else f"{cmp_['Dplan']:.0f} mm"), ("dia", "post"): (f"{cmp_['Dreal']:.0f} mm（{cmp_['RealMaj']:.0f}×{cmp_['RealMin']:.0f}）" if "RealMaj" in cmp_ else f"{cmp_['Dreal']:.0f} mm（{cmp_['DrealMin']:.0f}〜{cmp_['DrealMax']:.0f}）"),
                             ("dia", "diff"): f"{round(cmp_['Dreal'] - cmp_['Dplan']) + 0:+.0f} mm",
                             ("off", "plan"): "広がりの予測" if getattr(L, "_graftRad", None) is not None else ("真腔の中心" if pl.get("tl") else "大動脈の中心"), ("off", "post"): f"中央値 {cmp_['offMed']:.0f} mm",
                             ("off", "diff"): f"最大 {cmp_['offMax']:.0f} mm（{self._tvRef(cmp_['offAt'])}）"})
            for k, v in vals.items(): self.cmpLab[k].setText(v)

    def onTLFix(self, on):
        L = self.logic
        if on and L.P is not None and not L.tlValid():
            if not self.tlBtn.checked: self.tlBtn.checked = True
            else: self._busy(L.extractTL, self._say)
        if on and not L.tlValid():
            self.tlFixBtn.blockSignals(True); self.tlFixBtn.checked = False; self.tlFixBtn.blockSignals(False); L.tlFixMode = False; return
        L.tlFixMode = bool(on); L.onTLClick = self._onTLClick
        if on:
            for b in (self.planEditBtn, self.entryBtn):
                if b.checked: b.checked = False
            self._say("断面（X）で、本当の真腔の中をクリック → その前後をたどり直します（緑の線）。Ctrl+Z で戻す。終わったらもう一度ボタンを押す。")

    def _onTLClick(self, k, uv):
        L = self.logic; res = []
        self._busy(lambda: res.append(L.fixTL(k, uv, self._say)))
        if not res or res[0] is None: self._say("そこからは真腔をたどれませんでした。造影されている所（明るい所）をクリックしてください。"); return
        self._afterTL(f"真腔をたどり直しました（{res[0]:.0f} mm の範囲）。まだずれていれば別の断面でもクリック。Ctrl+Z で戻す。")

    def _afterTL(self, msg):
        L = self.logic
        if self.flShowBtn.checked: self._busy(L.extractFL, self._say)
        self._busy(L.planDraw); self._tvRefresh()
        try: self._expRefresh()
        except Exception: pass
        L._showContour(exact=False)
        if L.tlValid():
            d = L.tl["deq"]; n = len(L.planInit().get("tlfix", []) or [])
            self.tlInfo.setText(f"真腔をたどりました（径 {np.nanmin(d):.0f}〜{np.nanmax(d):.0f} mm" + (f"・手直し {n} か所" if n else "") + "）。断面の緑の線で確認してください。")
        self._say(msg)

    def onTLFixReset(self):
        L = self.logic; L.planInit()["tlfix"] = []
        if L.P is None or not self.tlBtn.checked: self._say("真腔の手直しを消しました。"); return
        self._busy(L.extractTL, self._say); L._tlAfter(); self._afterTL("真腔の手直しを消して、自動でたどり直しました。")

    def onTL(self, on):
        L = self.logic; pl = L.planInit(); pl["tl"] = bool(on)
        def run():
            if on and not L.tlValid(): L.extractTL(self._say)
            L.planDraw()
        self._busy(run); self._tvRefresh()
        if on and L.tlValid():
            d = L.tl["deq"]; self.tlInfo.setText(f"真腔をたどりました。グラフトは真腔の中心に置いています（真腔の径 {np.nanmin(d):.0f}〜{np.nanmax(d):.0f} mm）。断面の緑の線で確認してください。")
        elif not on: self.tlInfo.setText("大動脈の中心線に沿わせています。")
        self._say(self.tlInfo.text)

    def _sineRefresh(self):
        L = self.logic
        try: si = L.sineIdx()
        except Exception as e: print("sine:", e); si = None
        sh = getattr(self, "sineShort", None)
        if not si:
            self.sineLab.setText("解離では「真腔に沿わせる」を押すと出ます。")
            if sh is not None: sh.setText("遠位端の SINE の目安: 「真腔に沿わせる」で出ます。")
            return
        ref = L.SINE_REF; g = "color:#9aa7b4; font-size:11px"
        def cell(v, rr):
            if v is None or not np.isfinite(v): return "<td align='right'>—</td>"
            col = "#5fd36e" if v < rr[0] else ("#ffcc33" if v < rr[1] else "#ff6b6b")
            return f"<td align='right' style='color:{col}; font-weight:bold'>{v:.2f}</td>"
        def refrow(r): return f"<tr><td style='{g}'>参考</td>" + "".join(f"<td align='right' style='{g}'>{r[k][0]:g}/{r[k][1]:g}</td>" for k in ("mean", "per", "area")) + "</tr>"
        a = si["tl"]
        h = (f"<b>遠位端の真腔</b>　短径 {a['short']:.1f}・長径 {a['long']:.1f} mm<br>周径 {a['per']:.0f} mm・面積 {a['area']:.0f} mm²<br>"
             f"<b>グラフト遠位</b>　{si['Dd']:.0f} mm（周径 {math.pi * si['Dd']:.0f}）<br>短径比 {si['pre']['short'] * 100:+.0f}%・長径比 {(si['Dd'] / a['long'] - 1) * 100:+.0f}%")
        if "gD" in si: h += f"<br><b>広がりの予測</b>　{si['gD']:.0f} mm（周径 {si['gper']:.0f}）" + (f"<br>ガター {si['gut']:.0f} mm²" if si.get("gut", 0) >= 5 else "")
        h += f"<table width='100%' cellspacing='0' cellpadding='2' style='margin-top:6px'><tr><td></td><td align='right' style='{g}'>平均径</td><td align='right' style='{g}'>周径</td><td align='right' style='{g}'>面積</td></tr>"
        p = si["pre"]; h += "<tr><td>オーバーサイズ</td>" + cell(p["mean"], ref["pre"]["mean"]) + cell(p["per"], ref["pre"]["per"]) + cell(p["area"], ref["pre"]["area"]) + "</tr>" + refrow(ref["pre"])
        if "emr" in si:
            e = si["emr"]; h += "<tr><td>ミスマッチ（予測）</td>" + cell(e["mean"], ref["emr"]["mean"]) + cell(e["per"], ref["emr"]["per"]) + cell(e["area"], ref["emr"]["area"]) + "</tr>" + refrow(ref["emr"])
        h += "</table>"
        self.sineLab.setText(h)
        if sh is not None:
            def c1(v, rr):
                if v is None or not np.isfinite(v): return "—"
                col = "#5fd36e" if v < rr[0] else ("#ffcc33" if v < rr[1] else "#ff6b6b")
                return f"<span style='color:{col}; font-weight:bold'>{v:.2f}</span>"
            t = f"<b>遠位端の SINE の目安</b>　オーバーサイズ {c1(p['mean'], ref['pre']['mean'])}"
            if "emr" in si: t += f"・ミスマッチ（予測） {c1(si['emr']['mean'], ref['emr']['mean'])}"
            sh.setText(t)
            sh.setToolTip(h + "<br><br>" + (self.sineLab.toolTip or ""))

    def _dropSameRange(self):
        b = getattr(self, "sameRangeBtn", None)
        if b is not None and b.checked: b.blockSignals(True); b.checked = False; b.blockSignals(False); self._keepPD = None

    def onTvHere(self, key):
        self._dropSameRange(); self.logic.planSet(**{key: float(self.logic.curS)}); self._tvRefresh()

    def _tvLenSet(self):
        L = self.logic; pl = L.planInit(); lg = L.planLengths()
        t = f"<span style='font-size:17px; font-weight:bold; color:#ffffff'>治療長 {pl['d'] - pl['p']:.0f} mm</span>"
        if lg: t += f"<br><span style='font-size:11px; color:#9aa7b4'>外弯 {lg['outer']:.0f}・内弯 {lg['inner']:.0f} mm</span>"
        self.tvLen.setTextFormat(qt.Qt.RichText); self.tvLen.setText(t)
        self.tvLen.setToolTip("治療長 = 近位端から遠位端までの中心線の長さ。外弯 / 内弯 = グラフト（名目の径）の筒の上で、いちばん長い / 短いすじの長さ（大弯側 / 小弯側）。"
                              "微調整: 近位端・遠位端の −/＋（1 mm・Shift で 5 mm）、または ストレッチ像の白い線をつかんで動かす")

    def onTvPick(self, on):
        L = self.logic; L.pickPD = "p" if on else None; L._pickP = None
        if on:
            for b in (getattr(self, "planEditBtn", None), getattr(self, "tlFixBtn", None), getattr(self, "entryBtn", None), self.tvRange):
                if b is not None and b.checked: b.checked = False
            self._say("ストレッチ像で 近位端 をクリック（断面を動かして Enter でも）。")
        L._drawGreen()

    def onTvEnter(self):
        """計画のページの Enter: 今の断面を 近位端 → 遠位端"""
        L = self.logic
        if not getattr(L, "pickPD", None):
            self.tvPick.blockSignals(True); self.tvPick.checked = True; self.tvPick.blockSignals(False); L.pickPD = "p"; L._pickP = None
        L._pickAt(float(L.curS))

    def onTvNudge(self, key, dl):
        L = self.logic; pl = L.planInit()
        if qt.QApplication.keyboardModifiers() & qt.Qt.ShiftModifier: dl *= 5.0
        pl[key] = float(np.clip(pl[key] + dl, 0.0, L.length - 1.0))
        if pl["d"] < pl["p"] + 10.0:
            if key == "p": pl["p"] = pl["d"] - 10.0
            else: pl["d"] = pl["p"] + 10.0
        self._dropSameRange(); L._queue(s=pl[key]); L._drawGreen()
        self.tvRows[key][0].setText(self._tvRef(pl[key])); self._tvLenSet()
        t = getattr(self, "_nudgeT", None)
        if t is None:
            t = self._nudgeT = qt.QTimer(); t.setSingleShot(True); t.timeout.connect(lambda: (self._busy(self.logic.planDraw), self._tvRefresh()))
        t.start(450)                                                        # 押し終わってから 1 回だけ描き直す

    def onTvRange(self, on):
        self.logic.rangeMode = bool(on)
        if on: self._say("ストレッチ像で、近位端から遠位端までドラッグしてください。")

    def onTvRound(self):
        L = self.logic; r = L.roundLanding()
        if r is None: self._say("左鎖骨下動脈の印が無いか、直下に正円の所が見つかりませんでした。断面で位置を合わせて「近位端 ここに」を使ってください。"); return
        self._dropSameRange(); self._busy(lambda: L.planSet(p=r["s"])); L.setPosition(r["s"]); self._tvRefresh()
        self._say(f"近位端を 左鎖骨下 +{r['s'] - r['lsca']:.1f} mm（真円度 {r['r']:.2f}・径 {r['deq']:.0f} mm）に置きました。正円の所はそこから約 {r['length']:.0f} mm 続きます。")

    def onFLShow(self, on):
        L = self.logic
        if on and not L.flValid(): self._busy(L.extractFL, self._say)
        m = slicer.mrmlScene.GetFirstNodeByName("TEVAR 偽腔")
        if m is not None and m.GetDisplayNode(): m.GetDisplayNode().SetVisibility(bool(on))
        self._flText()

    def _flText(self):
        L = self.logic
        if not L.flValid() or L.fl.get("start") is None: self.flInfo.setText(""); return
        pl = L.planInit(); st = L.fl["start"]; t = f"造影される偽腔は {self._tvRef(st)} から（紫）。"
        if pl["p"] <= st <= pl["d"]: t += f"グラフトはその {st - pl['p']:.0f} mm 近位から覆っています（入口側をふさぐ）。"
        elif st < pl["p"]: t += f"グラフトの近位端より {pl['p'] - st:.0f} mm 近位に偽腔があります（覆っていません）。"
        else: t += "グラフトより遠位です。"
        self.flInfo.setText(t); self.flShowBtn.setToolTip(t)

    def onTvEnds(self):
        v = "push" if self.endBtns[0].checked else "asis"
        self._busy(lambda: self.logic.planSet(ends=v)); self._tvRefresh()

    def onTvAxis(self):
        v = "cl" if self.axisBtns[0].checked else "tl"
        self._busy(lambda: self.logic.planSet(axis=v)); self._tvRefresh()

    def onFit3D(self):
        views = ("lao", "front", "left"); self._fitIdx = (getattr(self, "_fitIdx", -1) + 1) % 3
        self.logic.fit3DToGraft(views[self._fitIdx])
        self._say({"lao": "3D: 左前斜位", "front": "3D: 正面", "left": "3D: 左側面"}[views[self._fitIdx]])

    def onTvFlap(self):
        v = ("chronic", "acute", "fixed")[[b.checked for b in self.flapBtns].index(True)]
        self._busy(lambda: self.logic.planSet(flap=v)); self._tvRefresh()

    def onTvOversize(self):
        v = [0.0, 0.05, 0.10, 0.15, 0.20][[b.checked for b in self.osBtns].index(True)]
        self._busy(lambda: self.logic.planSet(os=v)); self._tvRefresh()

    def onTvDiam(self):
        self._busy(lambda: self.logic.planSet(dp=self.dpSpin.value or None, dd=self.ddSpin.value or None)); self._tvRefresh()

    def onTvShow(self, on):
        L = self.logic; L.planInit()["on"] = bool(on)
        if on: self._busy(L.planDraw)
        else: L.planShow(False)

    def onEntry(self, on):
        L = self.logic
        if not on: L._entryCb = None; return
        if self.tlFixBtn.checked: self.tlFixBtn.checked = False
        def done(ras):
            L._entryCb = None; name = L.addEntry(ras); self.entryBtn.blockSignals(True); self.entryBtn.checked = False; self.entryBtn.blockSignals(False)
            self._tvRefresh(); self._say(f"{name} を置きました（中心線 {self._tvRef(L.curS)}）。")
        L._entryCb = done; self._say("断面（X）でエントリーの穴をクリックしてください。")

    def onEntryDel(self):
        r = self.covTable.currentRow(); rows = getattr(self, "_covRows", [])
        if 0 <= r < len(rows) and rows[r]["kind"] == "entry": self.logic.removeEntry(rows[r]["name"]); self._tvRefresh()
        else: self._say("表でエントリーを選んでください")

    def onPlanEdit(self, on):
        L = self.logic; L.planEditMode = bool(on)
        if not on: L._cancelDrags()
        if on and self.tlFixBtn.checked: self.tlFixBtn.checked = False
        if on:
            L.alignMode = False; self.alignBtn.blockSignals(True); self.alignBtn.checked = False; self.alignBtn.blockSignals(False)
            self._say("断面の白い輪: 中をドラッグ = ずらす、ふちをドラッグ = 太さ（前後 2 cm がなめらかに）。Ctrl+Z で戻す。")

    def onPlanAdjReset(self):
        L = self.logic; L.planInit()["adj"] = []; self._busy(L.planDraw); self._tvRefresh(); self._say("シミュレーションの手直しを消しました。")
