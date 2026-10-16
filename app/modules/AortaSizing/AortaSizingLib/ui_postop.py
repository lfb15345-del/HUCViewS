# -*- coding: utf-8 -*-
"""大動脈サイジング: 4 術後 の画面の動き（読み込み・比べる・広がり・重ね合わせの手直し）
AortaSizingWidget の一部（PostOpUIMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class PostOpUIMixin:

    def onPostLoad(self):
        d = qt.QFileDialog.getExistingDirectory(None, "術後 CT の DICOM フォルダを選ぶ")
        if not d: return
        n = self._busy(self.logic.loadPostFolder, d, self._say)
        if n is not None:
            sp = n.GetSpacing(); self.postInfo.setText(f"術後 CT: {slicer.util.arrayFromVolume(n).shape[0]} 枚・スライス間隔 {sp[2]:.1f} mm。「比べる」を押してください。")

    def onPostCompare(self):
        L = self.logic
        if getattr(L, "post", None) is None or not slicer.mrmlScene.IsNodePresent(L.post):
            self.onPostLoad()
            if getattr(L, "post", None) is None: return
        def run():
            M, rms = L.registerPost(self._say)
            L.extractStent(status=self._say)
            pl_ = L.planInit()
            if pl_.get("tl") and not L.tlValid(): L.extractTL(self._say)
            try: L.refinePost(self._say)
            except Exception as e: print("refine:", e)
            return rms
        rms = self._busy(run)
        if rms is None: return
        zr = L.post.GetSpacing()[2]
        ps = getattr(L, "postShift", None); pst = ""
        if ps is not None: pst = f"。そのあと大動脈の外形で合わせ直し（ずれ 中央値 {np.median(ps['mag']):.1f}・最大 {ps['mag'].max():.1f} mm）"
        self.postInfo.setText(f"重ね合わせ（背骨）の誤差 {rms:.1f} mm{pst}・術後 CT のスライス間隔 {zr:.1f} mm（端の位置はおよそ ±{max(zr / 2, rms):.0f} mm）")
        if self.postStretchBtn.checked: self._busy(L.postStraight); L.showPostStretch(True)
        if not self.ovPost.checked: self.ovPost.checked = True
        L.showOverlay3D("post", True)
        self._tvRefresh()
        c = L.comparePost()
        self._expRefresh()
        if c: self._say(f"術後のグラフト: 近位端 {c['dP']:+.0f} mm・遠位端 {c['dD']:+.0f} mm（計画との差。＋ = 遠位へ）")

    def _expRefresh(self):
        L = self.logic
        try: ex = L.expansionReport()
        except Exception as e: print("expansion:", e); ex = None
        if not ex: self.expLab.setText("「比べる」のあとに出ます（解離では「真腔に沿わせる」も）。"); return
        g = "color:#9aa7b4; font-size:11px"
        pc = lambda r: f"<b>{(r - 1) * 100:+.0f}%</b>"
        h = (f"<table width='100%' cellspacing='0' cellpadding='2'><tr><td></td><td align='right' style='{g}'>長径</td><td align='right' style='{g}'>短径</td>"
             f"<td align='right' style='{g}'>面積</td><td align='right' style='{g}'>周径</td></tr>")
        for key, name in (("prox", "近位 2 cm"), ("mid", "中央"), ("dist", "遠位 2 cm"), ("all", "全体")):
            r = ex["reg"].get(key)
            if not r: continue
            h += (f"<tr><td>{name}</td><td align='right'>{pc(r['r_long'])}</td><td align='right'>{pc(r['r_short'])}</td><td align='right'>{pc(r['r_area'])}</td><td align='right'>{pc(r['r_per'])}</td></tr>"
                  f"<tr><td style='{g}'></td><td align='right' style='{g}'>{r['tl_long']:.0f}→{r['maj']:.0f}</td><td align='right' style='{g}'>{r['tl_short']:.0f}→{r['min']:.0f}</td>"
                  f"<td align='right' style='{g}'>短/長 {r['ratio']:.2f}</td><td></td></tr>")
            if r.get("d_flap") is not None and key != "prox":
                h += f"<tr><td style='{g}'></td><td colspan='4' style='{g}'>偽腔側（フラップ）{r['d_flap']:+.0f} mm・壁側 {r['d_wall']:+.0f} mm</td></tr>"
        h += (f"</table><span style='{g}'>中央値・mm。実際 = 術後の金属に楕円を当てはめた値（{len(ex['rows'])} 断面）。"
              "偽腔側・壁側 = 術前の真腔の縁から、ステントがどちらへどれだけ広がったか。</span>")
        self.expLab.setText(h)

    def onExpCsv(self):
        L = self.logic
        if not getattr(L, "expansion", None): self._expRefresh()
        fn = L.saveExpansionCSV()
        if fn: self._done(os.path.dirname(fn), "広がりの表")
        else: self._say("先に「比べる」を押してください。")

    def onAlignMode(self, on):
        L = self.logic
        if not on: L._cancelDrags()
        if on and getattr(L, "actual", None) is None:
            self.alignBtn.blockSignals(True); self.alignBtn.checked = False; self.alignBtn.blockSignals(False); self._say("先に「比べる」を押してください"); return
        L.alignMode = bool(on)
        if on:
            L.planEditMode = False; self.planEditBtn.blockSignals(True); self.planEditBtn.checked = False; self.planEditBtn.blockSignals(False)
            L.showOverlay3D("post", True); self._say("断面で金色の点をドラッグ（その高さの前後 3 cm）、ストレッチ像で上下にドラッグ（頭尾方向）。Ctrl+Z で戻す。")

    def _afterAlign(self):
        L = self.logic
        def run():
            L._restent(self._say)
            if self.postStretchBtn.checked: L.postStraight()
        self._busy(run)
        if self.postStretchBtn.checked: L.showPostStretch(True)
        self._tvRefresh(); self._expRefresh(); L._showContour(exact=False)
        n = len(getattr(L, "postManual", []) or []); self._say(f"重ね合わせを手で直しました（{n} か所）。Ctrl+Z で戻す・「手直しを消す」で自動に戻る。")

    def onAlignReset(self):
        self.logic.postManual = []; self._afterAlign()

    def onSameRange(self, on):
        L = self.logic; ac = getattr(L, "actual", None); pl = L.planInit()
        if on:
            if ac is None:
                self.sameRangeBtn.blockSignals(True); self.sameRangeBtn.checked = False; self.sameRangeBtn.blockSignals(False)
                self._say("先に「比べる」を押してください"); return
            self._keepPD = (pl["p"], pl["d"]); self._busy(lambda: L.planSet(p=ac["lo"], d=ac["hi"]))
            L.showOverlay3D("post", True); self.ovPost.blockSignals(True); self.ovPost.checked = True; self.ovPost.blockSignals(False)
            self._say("実際と同じ範囲に置き直しました。断面: 白 = シミュレーション、金色の点 = 実際の金属。もう一度押すと元の計画に戻ります。")
        else:
            kp = getattr(self, "_keepPD", None)
            if kp: self._busy(lambda: L.planSet(p=kp[0], d=kp[1])); self._say("元の計画に戻しました。")
        self._tvRefresh()

    def onPostStretch(self, on):
        L = self.logic
        if on and getattr(L, "postT", None) is None:
            self.postStretchBtn.blockSignals(True); self.postStretchBtn.checked = False; self.postStretchBtn.blockSignals(False)
            self._say("先に「比べる」を押してください"); return
        if on: self._busy(L.postStraight)
        L.orangeOff = 0.0 if on else 90.0; L.showPostStretch(on); L.setRotation(L.rot)
