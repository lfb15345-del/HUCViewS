# -*- coding: utf-8 -*-
"""大動脈サイジング: 1 中心線・2 計測 の画面の動き（テンプレート・印・手動計測・枝のチップ・長さ）
AortaSizingWidget の一部（MeasureUIMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class MeasureUIMixin:

    # ---------------------------------------------------------------- TEVAR（仮想グラフト・術後との比較）
    SHORT = {"腕頭動脈": "腕頭", "左総頸動脈": "左総頸", "左鎖骨下動脈": "左鎖骨下", "腹腔動脈": "腹腔", "上腸間膜動脈": "SMA", "最下位腎動脈": "腎動脈"}
    BR_CHIPS = ("腕頭動脈", "左総頸動脈", "左鎖骨下動脈", "腹腔動脈", "上腸間膜動脈", "右腎動脈", "左腎動脈", "大動脈分岐")
    _BR_SHORT = {"右腎動脈": "右腎", "左腎動脈": "左腎", "大動脈分岐": "分岐"}

    def _chipRefresh(self):
        L = self.logic
        for nm, b in (getattr(self, "brChips", None) or {}).items():
            m = L._mk(nm); base = self.SHORT.get(nm) or self._BR_SHORT.get(nm, nm)
            if m is None: b.setText(base); b.setStyleSheet("padding:3px 4px; font-size:11px")
            elif m.get("auto"): b.setText(base + " ?"); b.setStyleSheet("padding:3px 4px; font-size:11px; color:#ffcc33")
            else: b.setText(base + " ✓"); b.setStyleSheet("padding:3px 4px; font-size:11px; color:#5fd36e")
            if getattr(self, "_chipSel", None) == nm: b.setStyleSheet(b.styleSheet + "; border:2px solid #ffcc33; font-weight:bold")

    def onBranchChip(self, nm):
        """枝の印: チップを押して選ぶ → 3D かストレッチ像で枝の口をクリック（今の断面でよければ Enter かもう一度押す）。Esc でやめる。
        ? の自動の印は、選ぶとその位置へ移動するので、合っていれば Enter（違えばクリックで置き直す）"""
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        if getattr(self, "_chipSel", None) == nm: self._placeChip(float(L.curS)); return      # 同じチップをもう一度 = 今の位置に
        self._chipSel = nm; L.branchPick = nm; L.onBranchPicked = self._placeChip; self._chipRefresh()
        m = L._mk(nm)
        if m is not None and L._onPath(m):
            L.setPosition(m["s"])
            self._say(f"{nm}{'（自動・?）' if m.get('auto') else ''}: 今の位置です。合っていれば Enter。違えば 3D かストレッチ像で枝の口をクリック。Esc でやめる。")
        else: self._say(f"{nm}: 3D かストレッチ像で枝の口をクリック（今の断面でよければ Enter）。Esc でやめる。")

    def _placeChip(self, s):
        L = self.logic; nm = getattr(self, "_chipSel", None)
        if not nm: return
        self._chipSel = None; L.branchPick = None
        m = L._mk(nm); same = m is not None and m.get("auto") and abs(m["s"] - s) <= 1.0
        L.addMarker(nm, float(s)); self.refreshLists()
        order = list(self.BR_CHIPS); j = order.index(nm) if nm in order else -1
        nxt = next((x for x in order[j + 1:] + order[:j + 1] if L._mk(x) is None or L._mk(x).get("auto")), None)   # 次（並びで後ろから）
        self._say((f"{nm} を確認しました（✓）。" if same else f"{nm} を {L.rel(s):+.0f} mm に置きました（Ctrl+Z で戻す）。")
                  + (f" 次は「{self.SHORT.get(nxt) or self._BR_SHORT.get(nxt, nxt)}」など、チップを押して続けられます。" if nxt else " 枝の印は全部そろいました。"))

    def _chipCancel(self, say=True):
        if getattr(self, "_chipSel", None):
            self._chipSel = None; self.logic.branchPick = None; self._chipRefresh()
            if say: self._say("枝の印をやめました。")

    # ---------------------------------------------------------------- 1 中心線
    def onAuto(self):
        def run():
            paths = self.logic.autoCenterline(self._say)
            first = "大動脈→右腸骨" if "大動脈→右腸骨" in paths else paths[0]
            self.logic.selectPath(first, self._say)
            self._syncPathButtons(); self.refreshReadout(); self.refreshLists()
            self._say(f"できました（全長 {self.logic.length:.0f} mm）。「2 計測」でテンプレートの順に置いていきます。")
            self.showStep(1); self.gotoStep(self._firstOpen())
        self._busy(run)

    def _pick(self, name):
        if name not in self.logic.curves: self._syncPathButtons(); return
        if self.editButton.checked: self.editButton.checked = False
        self._busy(lambda: (self.logic.selectPath(name, self._say), self.refreshReadout(), self.refreshLists()))
        self._syncPathButtons()

    def _fixChanged(self):
        n = len(getattr(self.logic, "pendingFix", []) or [])
        self.fixApply.setText(f"反映して作り直す（{n} 点）"); self.fixApply.enabled = n > 0; self.fixClear.enabled = n > 0
        self.fixRow.setVisible(self.fixButton.checked or n > 0)

    def onFix(self, on):
        L = self.logic
        if L.P is None:
            self.fixButton.blockSignals(True); self.fixButton.checked = False; self.fixButton.blockSignals(False); self._say("先に中心線を作ってください"); return
        if not on and (getattr(L, "pendingFix", None) or []): self._busy(L.applyFixes, self._say)     # 終わる時に残った点は反映
        L.setFixMode(on); self.fixHint.setVisible(on); self._fixChanged()
        self._busy(L.fixLayout, on)
        if on and self.editButton.checked: self.editButton.checked = False
        self._say("中心線を合わせるモード: 軸位（A）か断面（X）で真腔の中心をクリック → ホイールで次の高さへ → … → 「反映して作り直す」。" if on else "合わせるモードを終えました。")

    def onEdit(self, on):
        if self.logic.P is None:
            self.editButton.blockSignals(True); self.editButton.checked = False; self.editButton.blockSignals(False); self._say("先に中心線を作ってください"); return
        self.editHint.setVisible(on); self.editButton.setText("完了（中心線を作り直す）" if on else "中心線を手で直す（3 断面でクリック / ドラッグ）")
        self.addPtButton.setVisible(not on)
        self.logic.editMode(on, self.logic.path)
        if not on and self.logic.path:
            L = self.logic
            def fin():
                L._rebuildKeep(self._say)                                     # 直した所だけ作り直す（広ければ全部）
                L.showLayout(); L.setPosition(min(L.curS, L.length)); self.refreshReadout(); self.refreshLists()
            self._busy(fin)
            self._say("直した中心線で作り直しました。")
        else:
            self._say("3 断面のどこでも、中心線の近くをクリックするとそこへ動きます（押したままドラッグでずらす）。終わったら「完了」。")

    def onAddPoint(self):
        if not self.editButton.checked: self.editButton.checked = True
        self.logic.startAddPoint(self.logic.path, lambda: self._say("点を追加しました。終わったら「中心線を直す」をもう一度。"))
        self._say("通したい所（真腔の中など）を断面でクリックしてください。")

    def _recenter(self, whole):
        s0 = self.logic.curS
        self._busy(lambda: (self.logic.recenter(self.logic.path, None if whole else s0, self._say), self.logic.setPosition(min(s0, self.logic.length)), self.refreshReadout()))

    def _mode(self, m):
        self._busy(lambda: (self.logic.setMode(m), self.refreshReadout()))
        self.outerBtn.checked = (m == "outer"); self.lumenBtn.checked = (m == "lumen")

    def onResetWL(self):
        L = self.logic
        for vn in (L.vol, L.straight):
            d = vn.GetDisplayNode() if vn is not None else None
            if d is not None: d.SetAutoWindowLevel(False); d.SetWindowLevel(800, 200)
        self._say("ウィンドウを最初の値（W800 / L200）に戻しました。")

    def onContEdit(self, on):
        try: self.logic.setContourEdit(on)
        except Exception: _err("contEdit")
        self._say("断面の輪郭の点をドラッグして直します。終わったらもう一度押す。" if on else "輪郭の手直しを終えました。")

    # ---------------------------------------------------------------- 読み取り（毎フレーム、軽く）
    def refreshReadout(self):
        L = self.logic
        if L.P is None: return
        self.posLabel.setText(f"{L.rel(L.curS):+.1f} mm" + ("" if L.baseS is not None else "  "))
        self.posLabel.setToolTip("ベースラインからの距離" if L.baseS is not None else "起点からの距離（ベースライン未設定）")
        for key, m in (("outer", getattr(L, "_mO", None)), ("lumen", getattr(L, "_mL", None))):
            for f in ("dmax", "dmin", "deq", "area"):
                self.vals[(key, f)].setText("—" if not m else (f"{m[f]:.0f}" if f == "area" else f"{m[f]:.1f}"))

    # ---------------------------------------------------------------- 2 テンプレート
    def _tpl(self):
        for b in self.tplBtns:
            if b.checked: return b.text
        return list(TEMPLATES)[0]

    def onTemplate(self):
        self._step = self._firstOpen(); self.refreshLists()

    def _steps(self):
        return [] if self._tpl() == "自由" else TEMPLATES[self._tpl()]

    def _firstOpen(self):
        L = self.logic
        for i, nm in enumerate(self._steps()):
            m = L._mk(nm)
            if m is None or m.get("auto"): return i
        return max(0, len(self._steps()) - 1)

    def gotoStep(self, i):
        st = self._steps()
        if not st: return
        self._step = max(0, min(len(st) - 1, i)); nm = st[self._step]; L = self.logic
        path = L.stepPath(nm)
        sg = L.suggest(nm) if L.P is not None else None
        try:
            if sg is not None:
                s, p = sg; p = path or p
                if p and p != L.path and p in L.curves and s > getattr(L, "sharedLen", 0) + 2: L._switch(p, s)
                else: L.setPosition(s)
            elif path and path != L.path and path in L.curves: L._switch(path, L.curS)
        except Exception: _err("goto")
        self.refreshLists()

    def onPlace(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        if getattr(L, "_activeMeasure", None) is not None: L.finishMeasure(); return
        st = self._steps()
        if not st: name = L.addMarker("マーカー"); self._say(f"「{name}」を置きました。"); return
        nm = st[self._step]; L.addMarker(nm); self._say(f"「{nm}」を {L.rel(L.curS):+.1f} mm に置きました。")
        nxt = next((i for i in range(self._step + 1, len(st)) if (L._mk(st[i]) is None or L._mk(st[i]).get("auto"))), None)
        if nxt is not None: self.gotoStep(nxt)
        else: self.refreshLists(); self._say("テンプレートの項目が全部そろいました。「3 出力」でサイジングシートを作れます。")

    def onUnplace(self):
        st = self._steps()
        if st: self.logic.removeMarkerByName(st[self._step])

    def onPin(self):
        if self.logic.P is None: return
        nm = self.logic.pinSection(); self._say(f"「{nm}」として記録しました（マーカー表と出力に入ります）。")

    # ---------------------------------------------------------------- 手動計測
    def onTool(self, key):
        L = self.logic
        if not self.toolBtns[key].checked: L.cancelMeasure(); return
        for k, b in self.toolBtns.items(): b.checked = (k == key)
        L.startMeasure(key)
        self._say({"line": "2 点をクリック。", "angle": "3 点をクリック（真ん中が頂点）。"}.get(key, "点を順にクリック。右クリックか Enter で終わり。") + "  Esc で中止。")

    def _syncTools(self):
        if not self.logic._placing():
            for b in self.toolBtns.values(): b.checked = False
            if getattr(self.logic, "_activeMeasure", None) is not None: qt.QTimer.singleShot(0, self.logic.finishMeasure)

    def _measAt(self, r):
        rows = getattr(self, "_measRows", [])
        return rows[r]["node"] if 0 <= r < len(rows) else None

    def onMeasDel(self):
        for r in sorted({i.row() for i in self.measTable.selectedIndexes()}, reverse=True):
            n = self._measAt(r)
            if n is not None: self.logic.deleteMeasure(n)

    def onUndo(self):
        self._say(self.logic.undoLast())

    def onKey(self, cmd):
        if cmd == "align": self._afterAlign(); return
        if cmd == "planadj":
            L = self.logic; self._busy(L.planDraw); self._tvRefresh(); L._showContour(exact=False)
            self._say(f"シミュレーションを直しました（{len(L.plan.get('adj', []))} か所）。Ctrl+Z で戻す・「直しを消す」で元どおり。"); return
        if cmd == "adjundo":
            L = self.logic
            if getattr(L, "tlFixMode", False):
                if L.undoTLFix(): self._afterTL("真腔の手直しを 1 つ戻しました。")
                return
            if getattr(L, "alignMode", False) and getattr(L, "postManual", None): L.postManual.pop(); self._afterAlign()
            elif getattr(L, "planEditMode", False) and L.planInit().get("adj"): L.plan["adj"].pop(); self._busy(L.planDraw); self._tvRefresh(); L._showContour(exact=False); self._say("1 つ戻しました。")
            return
        if cmd == "tvplan":
            self._dropSameRange(); self.tvRange.blockSignals(True); self.tvRange.checked = False; self.tvRange.blockSignals(False)
            self.tvPick.blockSignals(True); self.tvPick.checked = False; self.tvPick.blockSignals(False)
            self._busy(self.logic.planDraw); self._tvRefresh(); pl = self.logic.plan
            lg = self.logic.planLengths(); lt = f"・外弯 {lg['outer']:.0f}・内弯 {lg['inner']:.0f} mm" if lg else ""
            self._say(f"治療長 {pl['d'] - pl['p']:.0f} mm（中心線{lt}）: {self._tvRef(pl['p'])} → {self._tvRef(pl['d'])}。−/＋ か白い線で微調整。"); return
        if cmd == "editdone":
            if self.editButton.checked: self.editButton.checked = False
            return
        if cmd == "fixapply": self._busy(self.logic.applyFixes, self._say); return
        if cmd == "fixexit": self.fixButton.checked = False; return
        if cmd == "enter" and self.stack.currentIndex == 2 and getattr(self.logic, "_tvMode", False): self.onTvEnter(); return
        if cmd == "esc" and getattr(self.logic, "pickPD", None): self.tvPick.checked = False; self._say("端の選びを取り消しました。"); return
        if cmd == "enter" and getattr(self, "_chipSel", None): self._placeChip(float(self.logic.curS)); return
        if cmd == "esc" and getattr(self, "_chipSel", None): self._chipCancel(); return
        if cmd == "enter": self.onPlace()
        elif cmd == "pin": self.onPin()
        elif cmd == "mode": self._mode("lumen" if self.logic.mode == "outer" else "outer")
        elif cmd == "undo": self.onUndo()
        elif cmd == "esc":
            self.logic.cancelMeasure()
            for b in self.toolBtns.values(): b.checked = False

    # ---------------------------------------------------------------- マーカー
    def onDelMark(self):
        for r in sorted({i.row() for i in self.markTable.selectedIndexes()}, reverse=True): self.logic.removeMarker(r)

    def onMeasure(self):
        rows = sorted({i.row() for i in self.markTable.selectedIndexes()})
        if len(rows) != 2: self._say("マーカー表で 2 つ選んでください（Ctrl＋クリック）。"); return
        self._showText(self.logic.between(rows[0], rows[1]))

    def _showText(self, txt):
        import html
        self.resultBox.setHtml("<div style='font-family:Consolas,\"Yu Gothic UI\"; font-size:12px; color:#e6e8ec; white-space:pre-wrap'>" + html.escape(txt) + "</div>")

    # ---------------------------------------------------------------- 一覧（変更があった時だけ）
    def refreshLists(self):
        L = self.logic; import html
        try: self._chipRefresh()
        except Exception as e: print("chips:", e)
        if getattr(self, "lenBtn", None) is not None and self.lenBtn.checked and not getattr(self, "_lenBusy", False):   # 印を置き直したら長さも
            self._lenBusy = True
            try: L.drawLengths(self._tpl() if self._tpl() != "自由" else "EVAR", True)
            except Exception as e: print("lengths:", e)
            finally: self._lenBusy = False
        if self.stack.currentIndex in (2, 3):
            try: self._tvRefresh()
            except Exception as e: print("tv refresh:", e)
        # テンプレートの手順
        st = self._steps(); self.stepList.clear()
        for i, nm in enumerate(st):
            m = L._mk(nm)
            if m is None: ic, col, val = "○", "#8a909b", ""
            elif m.get("auto"): ic, col, val = "◐", "#ffb547", f"{L.rel(m['s']):+.1f} mm  推定・確認して Enter"
            else:
                o = L._dia(m["s"], m["path"]) if m["path"] in L.frames else None
                ic, col, val = "✓", "#4ade80", f"{L.rel(m['s']):+.1f} mm" + (f"   Ø {o['dmax']:.1f}/{o['dmin']:.1f}" if o else "")
            it = qt.QListWidgetItem(f"{ic}  {i + 1}. {nm}" + (f"      {val}" if val else ""))
            it.setForeground(qt.QBrush(qt.QColor("#ffffff" if i == self._step else col)))
            if i == self._step: it.setBackground(qt.QBrush(qt.QColor("#1f4d69")))
            self.stepList.addItem(it)
        if st:
            nm = st[self._step]; side = {"大動脈→右腸骨": "（右の経路）", "大動脈→左腸骨": "（左の経路）"}.get(L.stepPath(nm), "")
            self.nextLabel.setText(f"{self._step + 1}/{len(st)}   {nm}{side}")
            m = L._mk(nm)
            self.nextHint.setText("自動で推定した位置に合わせました。断面とストレッチ像で確かめて Enter。" if (m and m.get("auto")) else
                                  ("置き済み。位置を変えるなら合わせて Enter（上書き）。" if m else "ストレッチ像のクリックか断面のホイールで位置を合わせて Enter。"))
            self.placeBtn.setText("ここに置く  ⏎")
        else:
            self.nextLabel.setText("自由: 好きな位置にマーカーを置く"); self.nextHint.setText("位置を合わせて Enter（番号付きで残ります）。"); self.placeBtn.setText("マーカーを置く  ⏎")
        for b in (self.skipBtn, self.prevBtn, self.unplaceBtn): b.enabled = bool(st)
        # 手動計測
        self._measRows = L.measureRows(); t = self.measTable; t.setRowCount(len(self._measRows))
        for r, row in enumerate(self._measRows):
            for c, val in enumerate((row["name"], row["value"], row["where"], row["pos"])): t.setItem(r, c, qt.QTableWidgetItem(val))
        t.resizeColumnsToContents()
        # マーカー
        t = self.markTable; rows = L._markerRows() if L.P is not None else []; t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            m = row["m"]; f = lambda q, k: f"{q[k]:.1f}" if q else ""
            vals = [m["name"] + (f"  {m['clock']}" if m.get("clock") else "") + ("  ?" if m.get("auto") else ""), row["side"], f"{L.rel(m['s']):+.1f}",
                    f(row["o"], "dmax"), f(row["o"], "dmin"), f(row["o"], "deq"), f(row["l"], "deq")]
            for c, val in enumerate(vals):
                it = qt.QTableWidgetItem(val)
                if m.get("auto"): it.setForeground(qt.QBrush(qt.QColor("#ffb547")))
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        # 結果（テンプレートのまとめ）
        if L.P is not None and self._tpl() != "自由":
            try:
                txt = L.summary(self._tpl()); out = []
                for line in txt.splitlines()[1:]:
                    if line.startswith("[全マーカー]"): break
                    if not line.strip(): continue
                    e = html.escape(line)
                    if line.startswith("["):
                        k = e.index("]") + 1; out.append(f"<div style='margin-top:4px'><b style='color:#59d0ff'>{e[:k]}</b>{e[k:]}</div>")
                    elif line.startswith("※"): out.append(f"<div style='color:#ffb547'>{e}</div>")
                    else: out.append(f"<div style='color:#c9ced6; margin-left:10px'>{e.strip()}</div>")
                self.resultBox.setHtml("<div style='font-size:12px; color:#e6e8ec'>" + ("".join(out) or "<span style='color:#8a909b'>マーカーを置くと、ここに径・長さ・角度がまとまります。</span>") + "</div>")
            except Exception: _err("summary")
        self.refreshReadout(); self._syncPathButtons()

    def onLengths(self, on):
        L = self.logic
        if L.P is None:
            self.lenBtn.blockSignals(True); self.lenBtn.checked = False; self.lenBtn.blockSignals(False); self._say("先に中心線を作ってください。"); return
        if not on: L.drawLengths(None, False); self.lenLab.hide(); return
        tpl = self._tpl() if self._tpl() != "自由" else "EVAR"
        put, note = (L.autoLandmarks() if tpl == "EVAR" else ([], []))
        self._lenBusy = True
        try: rows = L.drawLengths(tpl, True); self.refreshLists()
        finally: self._lenBusy = False
        if not rows: self.lenLab.setText("長さを出せる印がまだありません（" + ("、".join(note) or "テンプレートの印を置いてください") + "）"); self.lenLab.show(); return
        g = "color:#9aa7b4; font-size:11px"
        h = "<table width='100%' cellspacing='0' cellpadding='2'>" + "".join(
            f"<tr><td>{jp}</td><td align='right'><b>{cl:.0f} mm</b></td><td align='right' style='{g}'>内弯 {inn:.0f}・外弯 {o:.0f}</td></tr>" for _, jp, _, _, cl, inn, o, _k in rows) + "</table>"
        if put: h += f"<span style='{g}'>自動で置いた印（? つき・要確認）: {'、'.join(put)}</span><br>"
        if note: h += f"<span style='{g}'>{'。'.join(note)}</span><br>"
        if tpl == "EVAR": h += f"<span style='{g}'>反対側の脚は 3D でその脚の線をクリック → もう一度押す</span>"
        self.lenLab.setText(h); self.lenLab.show()
        try: self.logic.fit3D() if hasattr(self.logic, "fit3D") else None
        except Exception: pass
        self._say("長さを 3D に出しました（黄色の線と数字）。" + ("自動で置いた印は ? つき。違えば断面を動かして置き直してください。" if put else ""))
