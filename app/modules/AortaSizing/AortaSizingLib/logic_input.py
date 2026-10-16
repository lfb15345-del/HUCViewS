# -*- coding: utf-8 -*-
"""大動脈サイジング: マウス・キーボード（断面・ストレッチ像・3D）
AortaSizingLogic の一部（InputMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class InputMixin:

    def _abort(self, it):
        for i, tag in self._iTags:
            if i is it:
                try: it.GetCommand(tag).SetAbortFlag(1)
                except Exception: pass

    def _queue(self, s=None, rot=None):
        if s is not None: self._pending = s
        if rot is not None: self._pendingRot = rot
        if not self._timer.isActive(): self._timer.start()

    def _flush(self):
        try:
            if self._pendingRot is not None:
                r = self._pendingRot; self._pendingRot = None; self.setRotation(r)
            if self._pending is not None:
                s = self._pending; self._pending = None; self.setPosition(s)
        except Exception: _err("flush")

    def _wheelRed(self, it, d):
        if self.P is None or self._editing: return
        step = 5.0 if it.GetShiftKey() else 1.0
        self._queue(s=float(np.clip((self._pending if self._pending is not None else self.curS) + d * step, 0, self.length)))
        self._abort(it)

    def _keyAny(self, it):
        key = it.GetKeySym() or ""; ctrl = bool(it.GetControlKey())
        if ctrl and key in ("z", "Z") and (getattr(self, "alignMode", False) or getattr(self, "planEditMode", False) or getattr(self, "tlFixMode", False)):
            cb = getattr(self, "onKey", None)
            if cb: qt.QTimer.singleShot(0, lambda: cb("adjundo"))
            self._abort(it); return
        cmd = None
        if getattr(self, "fixMode", False) and key in ("Return", "KP_Enter", "BackSpace", "Delete", "Escape"):
            cmd = {"Return": "fixapply", "KP_Enter": "fixapply", "BackSpace": "undo", "Delete": "undo", "Escape": "fixexit"}[key]
            try: getattr(self, "onKey", lambda c: None)(cmd)
            except Exception: _err("key")
            self._abort(it); return
        if key in ("Return", "KP_Enter"): cmd = "enter"
        elif key in ("p", "P") and not ctrl: cmd = "pin"
        elif key in ("l", "L") and not ctrl: cmd = "mode"
        elif key in ("z", "Z") and ctrl: cmd = "undo"
        elif key == "Escape": cmd = "esc"
        if cmd is None: return
        try: getattr(self, "onKey", lambda c: None)(cmd)
        except Exception: _err("key")
        if cmd != "esc": self._abort(it)

    def _keyRed(self, it):
        key = it.GetKeySym() or ""
        d = {"Up": -1, "Down": 1, "Prior": -5, "Next": 5}.get(key)
        if d is not None and self.P is not None:
            self._queue(s=float(np.clip(self.curS + d, 0, self.length))); self._abort(it)

    def _uvRed(self, it):
        k = self._k(); r = self._rasAt(it, "Red") - self.P[k]; return k, np.array([r @ self.B[k], r @ self.N[k]])

    def _moveRed(self, it):
        d = getattr(self, "_alDrag", None)
        if d is not None and d[0] == "xy":
            k, uv = self._uvRed(it); dd = (uv - d[1])[0] * self.B[k] + (uv - d[1])[1] * self.N[k]
            self._alDrag = (d[0], d[1], dd, d[3]); self._abort(it)
            if time.time() - getattr(self, "_lastMv", 0.0) > 0.08: self._lastMv = time.time(); self._showContour(exact=False)
            return
        p = getattr(self, "_pdDrag", None)
        if p is not None:
            k, uv = self._uvRed(it)
            if p["kind"] == "move": p["d"] = uv - p["uv0"]
            else: p["sc"] = float(np.clip(np.linalg.norm(uv - p["c"]) / max(p["r0"], 1.0), 0.5, 1.5))
            st = getattr(self, "onStatus", None)
            msg = f"シミュレーション: ずらす {np.linalg.norm(p['d']):.1f} mm" if p["kind"] == "move" else f"シミュレーション: 太さ {(p['sc'] - 1) * 100:+.0f}%"
            self._abort(it)
            if time.time() - getattr(self, "_lastMv", 0.0) > 0.08:
                self._lastMv = time.time(); self._showContour(exact=False)
                if st: st(msg + f"（離すと前後 {self.ADJ_SOFT:.0f} mm がなめらかについてきます）")

    def _releaseRed(self, it):
        cb = getattr(self, "onKey", None)
        d = getattr(self, "_alDrag", None)
        if d is not None and d[0] == "xy":
            self._alDrag = None; self._abort(it)
            if np.linalg.norm(d[2]) > 0.2:
                self.__dict__.setdefault("postManual", []).append((d[3], -np.asarray(d[2])))
                if cb: qt.QTimer.singleShot(0, lambda: cb("align"))
            return
        p = getattr(self, "_pdDrag", None)
        if p is not None:
            self._pdDrag = None; self._abort(it); pl = self.plan
            if (p["kind"] == "move" and np.linalg.norm(p["d"]) > 0.2) or (p["kind"] == "size" and abs(p["sc"] - 1) > 0.01):
                du, dv = (p["d"] if p["kind"] == "move" else (0.0, 0.0)); sc = p["sc"] if p["kind"] == "size" else 1.0
                pl.setdefault("adj", []).append((p["s0"], float(du), float(dv), float(sc)))
                if cb: qt.QTimer.singleShot(0, lambda: cb("planadj"))

    def _clickRed(self, it):
        if getattr(self, "alignMode", False) and getattr(self, "actual", None) is not None and self.P is not None:   # 術後の重ね合わせを手で直す
            k, uv = self._uvRed(it); self._alDrag = ("xy", uv, np.zeros(3), float(self.s[k])); self._abort(it); return
        if getattr(self, "tlFixMode", False) and self.P is not None and self.tlValid():          # 真腔を手で直す: クリックした所が本当の真腔
            k, uv = self._uvRed(it); self._abort(it); cb = getattr(self, "onTLClick", None)
            if cb: qt.QTimer.singleShot(0, lambda: cb(k, uv))
            return
        gr = getattr(self, "_graftRad", None)
        if getattr(self, "planEditMode", False) and gr is not None and gr["path"] == self.path and self.P is not None:   # シミュレーションを手で直す
            k, uv = self._uvRed(it)
            if gr["ks"][0] <= k <= gr["ks"][-1]:
                i = k - gr["ks"][0]; c = np.array([gr["cu"][i], gr["cv"][i]]); dvec = uv - c; r = float(np.linalg.norm(dvec))
                Rt = float(_radAt(gr["Rth"], np.array([i]), np.array([math.atan2(dvec[1], dvec[0])]))[0])
                if abs(r - Rt) <= 2.5: self._pdDrag = dict(kind="size", c=c, r0=r, sc=1.0, d=np.zeros(2), s0=float(self.s[k])); self._abort(it); return
                if r < Rt: self._pdDrag = dict(kind="move", uv0=uv, d=np.zeros(2), sc=1.0, c=c, r0=r, s0=float(self.s[k])); self._abort(it); return
        if getattr(self, "_entryCb", None) is not None and self.P is not None:      # TEVAR: エントリーを断面のクリックで置く
            x, y = it.GetEventPosition(); sn = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceNode()
            M = sn.GetXYToRAS(); ras = np.array([sum(M.GetElement(r, c) * v for c, v in enumerate((x, y, 0, 1))) for r in range(3)])
            cb = self._entryCb; self._entryCb = None
            try: cb(ras)
            except Exception as e: print("entry:", e)
            self._abort(it); return
        if self.P is not None and (it.GetControlKey() or getattr(self, "fixMode", False)) and self._clockCb is None and not self._editing and not self._placing():
            p = self._rasAt(it, "Red"); k = self._k()                    # Ctrl+クリック: この断面の中心をクリックした所へ
            self._abort(it)
            if getattr(self, "fixMode", False) and not it.GetControlKey(): self.queueFix(k, p); return
            qt.QTimer.singleShot(0, lambda: self._ctrlMove(k, p)); return
        if self._clockCb is None or self.P is None: return
        x, y = it.GetEventPosition(); sn = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceNode()
        M = sn.GetXYToRAS(); ras = np.array([sum(M.GetElement(r, c) * v for c, v in enumerate((x, y, 0, 1))) for r in range(3)])
        cb = self._clockCb; self._clockCb = None
        try: cb(self._setClock(ras))
        except Exception as e: print("clock:", e)
        self._abort(it)

    def _wheelGreen(self, it, d):
        if self.P is None: return
        base = self._pendingRot if self._pendingRot is not None else self.rot
        self._queue(rot=(base + d * (15.0 if it.GetShiftKey() else 5.0)) % 360.0); self._abort(it)

    def _rasAt(self, it, nm):
        x, y = it.GetEventPosition(); M = slicer.app.layoutManager().sliceWidget(nm).mrmlSliceNode().GetXYToRAS()
        return np.array([sum(M.GetElement(r, c) * v for c, v in enumerate((x, y, 0, 1))) for r in range(3)])

    def _sGreen(self, it, nm="Green"):
        return float(np.clip(-self._rasAt(it, nm)[2], 0, self.length))

    def _pressGreen(self, it, nm="Green"):
        if self.P is None or self._placing() or self._editing: return
        if getattr(self, "alignMode", False) and getattr(self, "actual", None) is not None:     # 術後を頭尾方向にずらす
            sC = self._sGreen(it, nm); ac = self.actual; self._alDrag = ("s", sC, 0.0, sC, ac["lo"], ac["hi"]); self._abort(it); return
        if it.GetControlKey() or getattr(self, "fixMode", False):         # Ctrl+クリック（合わせるモードではクリック）: その高さの中心線を、クリックした所へ動かす
            q = self._rasAt(it, nm); s = float(np.clip(-q[2], 0, self.length)); k = self._k(s)
            p = self.P[k] + q[0] * self.B[k] + q[1] * self.N[k]
            self._abort(it)
            if getattr(self, "fixMode", False) and not it.GetControlKey(): self.queueFix(k, p); return
            qt.QTimer.singleShot(0, lambda: self._ctrlMove(k, p)); return
        if it.GetShiftKey(): return
        pl = getattr(self, "plan", None)
        if getattr(self, "_tvMode", False) and getattr(self, "pickPD", None):  # TEVAR: クリックで 近位端 → 遠位端
            self._pickAt(self._sGreen(it, nm)); self._abort(it); return
        if getattr(self, "_tvMode", False) and pl is not None and pl.get("path") == self.path:   # TEVAR: 範囲をドラッグ / 白い線（近位・遠位端）をつかんで動かす
            sC = self._sGreen(it, nm)
            if getattr(self, "rangeMode", False): self._tvDrag = ("range", sC); pl["p"] = pl["d"] = sC; self._drawGreen(); self._abort(it); return
            near = min((("p", abs(sC - pl["p"])), ("d", abs(sC - pl["d"]))), key=lambda t: t[1])
            if near[1] <= 4.0: self._tvDrag = (near[0], sC); self._abort(it); return
        self._drag = True; self._queue(s=self._sGreen(it, nm)); self._abort(it)

    def _moveGreen(self, it, nm="Green"):
        d = getattr(self, "_alDrag", None)
        if d is not None and d[0] == "s":
            ds = self._sGreen(it, nm) - d[1]; self._alDrag = (d[0], d[1], ds, d[3], d[4], d[5])
            self.actual["lo"], self.actual["hi"] = d[4] + ds, d[5] + ds; self._drawGreen()
            st = getattr(self, "onStatus", None)
            if st: st(f"術後を頭尾方向に {ds:+.1f} mm（＋ = 足側）。離すと金属を拾い直します。")
            self._abort(it); return
        td = getattr(self, "_tvDrag", None)
        if td is not None:
            sC = self._sGreen(it, nm); pl = self.plan
            if td[0] == "range": pl["p"], pl["d"] = min(td[1], sC), max(td[1], sC)
            else: pl[td[0]] = sC
            st = getattr(self, "onStatus", None)
            if st: st(f"範囲: {self.rel(pl['p']):.0f} → {self.rel(pl['d']):.0f} mm（長さ {pl['d'] - pl['p']:.0f} mm）。離すとグラフトを描きます。")
            self._drawGreen(); self._abort(it); return
        if self._drag: self._queue(s=self._sGreen(it, nm)); self._abort(it); return
        if self.P is not None:                                           # マウスを乗せた所の径をその場で表示（クリック不要）
            self._hoverS = self._sGreen(it, nm); self._drawGreen()

    def _leaveGreen(self, it):
        self._hoverS = None
        if getattr(self, "_tvDrag", None) is not None or getattr(self, "_alDrag", None) is not None: self._releaseGreen(it); return
        self._drawGreen()

    def _pickAt(self, s):
        """端を決める: 1 回目 = 近位端、2 回目 = 遠位端 → グラフトを描く"""
        s = float(np.clip(s, 0.0, self.length)); st = getattr(self, "onStatus", None); pl = self.planInit()
        self._queue(s=s)                                                    # その断面も出す
        if getattr(self, "pickPD", None) != "d" or getattr(self, "_pickP", None) is None:
            self._pickP = s; self.pickPD = "d"; self._drawGreen()
            if st: st("近位端を決めました（黄色の線 P）。次に遠位端をクリック（または断面を動かして Enter）。Esc で取り消し。")
            return
        p, d = sorted((self._pickP, s))
        if d < p + 10.0: d = min(p + 10.0, self.length - 1.0)
        self._pickP = None; self.pickPD = None; pl["p"], pl["d"] = p, d; pl["path"] = self.path
        cb = getattr(self, "onKey", None)
        if cb: qt.QTimer.singleShot(0, lambda: cb("tvplan"))

    def _releaseGreen(self, it):
        d = getattr(self, "_alDrag", None)
        if d is not None and d[0] == "s":
            self._alDrag = None; self.actual["lo"], self.actual["hi"] = d[4], d[5]; self._abort(it)
            if abs(d[2]) > 0.2:
                self.__dict__.setdefault("postManual", []).append(("s", float(d[2])))                              # 中心線に沿って全体を滑らせる
                cb = getattr(self, "onKey", None)
                if cb: qt.QTimer.singleShot(0, lambda: cb("align"))
            return
        if getattr(self, "_tvDrag", None) is not None:
            self._tvDrag = None; self.rangeMode = False; pl = self.plan
            if pl["d"] < pl["p"] + 10.0: pl["d"] = min(pl["p"] + 10.0, self.length - 1.0)
            self._abort(it); cb = getattr(self, "onKey", None)
            if cb: qt.QTimer.singleShot(0, lambda: cb("tvplan"))
            return
        if self._drag: self._drag = False; self._abort(it)

    def _press3D(self, it): self._p3 = it.GetEventPosition()

    def _release3D(self, it):
        p0 = getattr(self, "_p3", None); p1 = it.GetEventPosition()
        if p0 is None or abs(p0[0] - p1[0]) + abs(p0[1] - p1[1]) > 3 or self.P is None or self._editing or self._placing(): return
        v3 = slicer.app.layoutManager().threeDWidget(0).threeDView(); ren = v3.renderWindow().GetRenderers().GetFirstRenderer()
        x, y = p1; W = []
        for z in (0.0, 1.0):
            ren.SetDisplayPoint(x, y, z); ren.DisplayToWorld(); w = ren.GetWorldPoint(); W.append(np.array(w[:3]) / (w[3] or 1.0))
        d = W[1] - W[0]; d /= np.linalg.norm(d) + 1e-9
        best = (1e9, None, None)
        for name, c in self.curves.items():
            pts = slicer.util.arrayFromMarkupsCurvePoints(c, world=True)
            dist = np.linalg.norm(np.cross(pts - W[0], d), axis=1)
            s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
            i = int(np.argmin(dist))
            if dist[i] < best[0]: best = (float(dist[i]), name, float(s[i]))
        dist, name, s = best
        if name is None or dist > 15: return
        if name != self.path and getattr(self, "_tvMode", False): return              # TEVAR: 計画の経路のまま
        if getattr(self, "_tvMode", False) and getattr(self, "pickPD", None): self._pickAt(s); return
        if name != self.path and s > getattr(self, "sharedLen", 0) + 2:
            qt.QTimer.singleShot(0, lambda: self._switch(name, s))
        else: self._queue(s=s)

    def _switch(self, name, s):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.curS = s; self.selectPath(name)
        except Exception: _err("switch")
        finally: qt.QApplication.restoreOverrideCursor()
