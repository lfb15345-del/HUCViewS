# -*- coding: utf-8 -*-
"""大動脈サイジング: 中心線を直す（クリック・合わせるモード・手で直す・中心に寄せる）
AortaSizingLogic の一部（CenterlineFixMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class CenterlineFixMixin:

    # ---- 中心線を合わせる（軸位でクリック / 赤い点をドラッグ）
    def setFixMode(self, on):
        self.fixMode = bool(on)
        try: self._drawAxialCenters()
        except Exception: pass

    def _axNodes(self):
        YEL = "vtkMRMLSliceNodeYellow"
        a = self._node("vtkMRMLMarkupsFiducialNode", "SA 軸位の中心線", (YEL,), (0.3, 0.9, 1.0), glyph=3.2)
        g = self._node("vtkMRMLMarkupsFiducialNode", "SA 移動先", (YEL,), (1.0, 0.9, 0.2), glyph=3.0)
        return a, g

    def _drawAxialCenters(self):
        """軸位の今の高さを中心線が通る所（水色の点）。赤い点 = 今の位置"""
        if self.P is None: return
        a, g = self._axNodes(); fix = getattr(self, "fixMode", False)
        z = self._axZ() if fix else self.P[self._k()][2]
        wasMod = a.StartModify(); a.RemoveAllControlPoints()
        for p in self._crossings(z):
            if not fix and np.linalg.norm(p - self.P[self._k()]) < 3: continue
            a.AddControlPoint(vtk.vtkVector3d(*p))
        a.EndModify(wasMod)

    def _crossings(self, z):
        dz = self.P[:, 2] - z; idx = np.where(np.sign(dz[:-1]) != np.sign(dz[1:]))[0]; out = []
        for i in idx:
            t = dz[i] / (dz[i] - dz[i + 1] + 1e-9); out.append(self.P[i] + t * (self.P[i + 1] - self.P[i]))
        return out

    def _axZ(self):
        return float(slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode().GetSliceOffset())

    def fixLayout(self, on):
        """合わせるモードの画面: 大きな軸位で、上から順にクリックしていく"""
        lm = slicer.app.layoutManager()
        if on:
            ln = lm.layoutLogic().GetLayoutNode()
            if not ln.IsLayoutDescription(FIX_LAYOUT_ID): ln.AddLayoutDescription(FIX_LAYOUT_ID, FIX_LAYOUT_XML)
            lm.setLayout(FIX_LAYOUT_ID); slicer.app.processEvents()
            yw = lm.sliceWidget("Yellow"); yn = yw.mrmlSliceNode(); yn.SetOrientationToAxial(); yw.sliceController().setVisible(False)
            cn = yw.sliceLogic().GetSliceCompositeNode(); cn.SetBackgroundVolumeID(self.vol.GetID()); cn.SetForegroundVolumeID(None); cn.SetLabelVolumeID(None)
            fov = yn.GetFieldOfView(); r = fov[1] / max(fov[0], 1e-6); yn.SetFieldOfView(170.0, 170.0 * r, fov[2])
            self._fixDir = -1.0; self.fixStep = getattr(self, "fixStep", 10.0)
            p = self.P[self._k()]; yn.JumpSliceByCentering(p[0], p[1], p[2])
            if getattr(self, "posNode", None) is not None: self.posNode.GetDisplayNode().SetVisibility(False)
            self._watch(); self._drawAxialCenters(); self._fixHud(True)
        else:
            self._fixHud(False)
            if getattr(self, "posNode", None) is not None: self.posNode.GetDisplayNode().SetVisibility(True)
            self.showLayout()
            try: self.setPosition(self.curS)
            except Exception: pass

    def _fixHud(self, on):
        lab = getattr(self, "_fixLab", None)
        if not on:
            if lab is not None:
                try: lab.hide(); lab.setParent(None); lab.deleteLater()
                except Exception: pass
            self._fixLab = None; return
        try:
            v = slicer.app.layoutManager().sliceWidget("Yellow").sliceView()
            if lab is None:
                lab = qt.QLabel(v); lab.setAttribute(qt.Qt.WA_TransparentForMouseEvents, True); lab.setTextFormat(qt.Qt.RichText)
                lab.setStyleSheet("QLabel{background:rgba(14,16,20,190); color:#e6e8ec; border-radius:8px; padding:8px 12px; font-size:13px;}")
                self._fixLab = lab
            n = len(getattr(self, "pendingFix", []) or [])
            lab.setText(f"<b style='color:#ffd84d'>真腔の中心をクリック</b>　→ 自動で {getattr(self, 'fixStep', 10.0):.0f} mm {'足側' if self._fixDir < 0 else '頭側'}へ<br>"
                        f"<span style='color:#9aa3ad'>水色の点 = 今の中心線　ホイール: 上下に移動（Shift で 1 cm）<br>"
                        f"Enter: 反映して作り直す　Backspace: 1 つ戻す　Esc: 終わる</span><br><b>置いた点: {n}</b>")
            lab.adjustSize(); lab.move(10, 10); lab.show(); lab.raise_()
        except Exception as e: print("fix hud:", e)

    def _wheelAx(self, it, d):
        if not getattr(self, "fixMode", False): self._wheelRed(it, -d); return
        yn = slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode()
        step = 10.0 if it.GetShiftKey() else max(1.0, float(self.vol.GetSpacing()[2]))
        yn.SetSliceOffset(yn.GetSliceOffset() + d * step); self._fixDir = 1.0 if d > 0 else -1.0
        self._drawAxialCenters(); self._fixHud(True); self._abort(it)

    def _fixAdvance(self, near):
        """クリックしたら、同じ向きへ少し進めて、次の中心を画面の真ん中に"""
        yn = slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode()
        z = self._axZ() + self._fixDir * getattr(self, "fixStep", 10.0); pts = self._crossings(z)
        if pts:
            c = min(pts, key=lambda q: np.linalg.norm(q[:2] - near[:2])); yn.JumpSliceByCentering(c[0], c[1], z)
        else: yn.SetSliceOffset(z)
        self._drawAxialCenters(); self._fixHud(True)

    def _nearestK(self, p):
        near = np.where(np.abs(self.P[:, 2] - p[2]) < 2.0)[0]
        if len(near) == 0: return int(np.argmin(np.linalg.norm(self.P - p, axis=1)))
        return int(near[np.argmin(np.linalg.norm(self.P[near, :2] - p[:2], axis=1))])

    def _pressAx(self, it):
        if self.P is None or self._placing() or self._editing: return
        if not (it.GetControlKey() or getattr(self, "fixMode", False)): return
        self._axPress = (it.GetEventPosition(), self._rasAt(it, "Yellow")); self._abort(it)

    def _moveAx(self, it):
        pr = getattr(self, "_axPress", None)
        if pr is None: return
        q = self._rasAt(it, "Yellow"); _, g = self._axNodes()
        if g.GetNumberOfControlPoints() < 1: g.AddControlPoint(vtk.vtkVector3d(*q))
        else: g.SetNthControlPointPosition(0, *q)
        self._abort(it)

    def _releaseAx(self, it):
        pr = getattr(self, "_axPress", None)
        if pr is None: return
        self._axPress = None; (x0, y0), p0 = pr; x1, y1 = it.GetEventPosition(); p1 = self._rasAt(it, "Yellow")
        _, g = self._axNodes(); g.RemoveAllControlPoints()
        drag = math.hypot(x1 - x0, y1 - y0) > 6
        k = self._nearestK(p0 if drag else p1)                          # ドラッグ: つかんだ所の中心線を離した所へ / クリック: いちばん近い中心線をそこへ
        self._abort(it)
        if getattr(self, "fixMode", False) and not it.GetControlKey():
            self.queueFix(k, p1); self._fixAdvance(p1); return
        def go():
            s0 = float(self.s[k]); self._ctrlMove(k, p1)
            try: self.setPosition(s0)
            except Exception: pass
        qt.QTimer.singleShot(0, go)

    def _ctrlMove(self, k, p):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: self.moveCenterTo(k, p, getattr(self, "onStatus", None) or print)
        except Exception: _err("ctrlMove")
        finally: qt.QApplication.restoreOverrideCursor()

    def moveCenterTo(self, k, p, status=print):
        """中心線のその位置（k）を点 p へ動かして作り直す。回転・位置はそのまま"""
        c = self.curves.get(self.path)
        if c is None or self.P is None: return
        k = int(np.clip(k, 0, len(self.P) - 1)); P0 = self.P[k]; off = np.asarray(p, float) - P0
        if np.linalg.norm(off) > 45: status("中心から遠すぎます（血管の中をクリック）"); return
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        self._hist = getattr(self, "_hist", []); self._hist.append(("center", (self.path, cps.copy())))
        self._softMove(c, [(k, off)])
        self._rebuildKeep(status)
        status(f"中心線を {np.linalg.norm(off):.1f} mm 動かしました（Ctrl+Z で戻す）")

    def _softMove(self, c, fixes, sigma=12.0):
        """中心線を直す: クリックした点だけを横へ引っぱると、近くの制御点との間で折れ曲がってループする。
        そこで ① ずらしは断面の面内だけ（頭尾方向には動かさない）② 前後の制御点もなめらかに一緒にずらす（ガウス、幅 12 mm〜）
        ③ 修正点そのものを通る制御点を置く ④ 前へ進まない点・近すぎる点（ループの元）は除く"""
        from scipy.spatial import cKDTree
        P, T, S = self.P, self.T, self.s
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True).astype(float)
        if len(cps) < 2 or not fixes: return
        # 制御点の中心線上の位置（前後の順を守るため、順番に近い所を探す）
        _, ki = cKDTree(P).query(cps); ki = np.maximum.accumulate(ki); si = S[ki]
        F = []
        for k, o in fixes:
            k = int(np.clip(k, 0, len(P) - 1)); o = np.asarray(o, float); o = o - (o @ T[k]) * T[k]; F.append((k, o))
        num = np.zeros_like(cps); den = np.zeros(len(cps)); wmax = np.zeros(len(cps))
        for k, o in F:
            sg = max(sigma, 1.5 * float(np.linalg.norm(o))); w = np.exp(-0.5 * ((si - S[k]) / sg) ** 2)
            num += w[:, None] * o; den += w; wmax = np.maximum(wmax, w)
        disp = num / np.maximum(den, 1e-9)[:, None] * wmax[:, None]
        disp -= np.einsum("ij,ij->i", disp, T[ki])[:, None] * T[ki]          # 面内だけ
        pts = [(float(si[i]), cps[i] + disp[i], i in (0, len(cps) - 1)) for i in range(len(cps))]
        for k, o in F: pts.append((float(S[k]), P[k] + o, True))             # 修正点（必ず通す）
        pts.sort(key=lambda t: t[0]); out = []
        for sv, x, keep in pts:
            if out:
                ps, px, pk = out[-1]; kk = int(np.clip(round(0.5 * (sv + ps) / STEP), 0, len(T) - 1))
                bad = (sv - ps < 4.0) or float(np.dot(x - px, T[kk])) <= 0.0
                if bad:
                    if keep and not pk: out[-1] = (sv, x, keep)                   # 修正点を優先
                    continue
            out.append((sv, x, keep))
        wasMod = c.StartModify(); c.RemoveAllControlPoints()
        for _, x, _ in out: c.AddControlPoint(vtk.vtkVector3d(*x))
        c.EndModify(wasMod)

    def _offsetCurve(self, c, P0, off):
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        d = np.linalg.norm(cps - P0, axis=1); i = int(np.argmin(d))
        if d[i] < 3: c.SetNthControlPointPositionWorld(i, *(cps[i] + off))
        else:
            best, bi = 1e9, 0
            for j in range(len(cps) - 1):
                a, b = cps[j], cps[j + 1]; ab = b - a; t = np.clip((P0 - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                dd = np.linalg.norm(a + t * ab - P0)
                if dd < best: best, bi = dd, j
            c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*(P0 + off)))

    # ---- 合わせるモード: クリックは「修正点」を置くだけ（すぐ計算しない）。「反映」でまとめて 1 回作り直す
    def queueFix(self, k, p, status=None):
        status = status or getattr(self, "onStatus", None) or print
        k = int(np.clip(k, 0, len(self.P) - 1)); p = np.asarray(p, float); off = p - self.P[k]
        if np.linalg.norm(off) > 60: status("今の中心線から 6 cm 以上離れています（大動脈の中をクリック）"); return
        pend = self.__dict__.setdefault("pendingFix", [])
        sk = float(self.s[k]); pend[:] = [q for q in pend if abs(q[2] - sk) > 4.0]          # 近い高さの点は置き換え
        pend.append((k, p, sk)); self._drawPending()
        if getattr(self, "_fixLab", None) is not None: self._fixHud(True)
        status(f"修正点 {len(pend)} 個（まだ計算していません）。ホイールで次の高さへ → クリック … 最後に「反映」")
        cb = getattr(self, "onFixChanged", None)
        if cb: cb()

    def clearFixes(self):
        self.pendingFix = []; self._drawPending()
        if getattr(self, "_fixLab", None) is not None: self._fixHud(True)
        cb = getattr(self, "onFixChanged", None)
        if cb: cb()

    def applyFixes(self, status=print):
        pend = list(getattr(self, "pendingFix", []) or [])
        c = self.curves.get(self.path)
        if not pend or c is None: return 0
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        self._hist = getattr(self, "_hist", []); self._hist.append(("center", (self.path, cps.copy())))
        self._softMove(c, [(k, p - self.P[k]) for k, p, sk in pend])
        self.pendingFix = []; self._drawPending()
        s0 = self.curS
        try: self._rebuildKeep(status)
        finally:
            cb = getattr(self, "onFixChanged", None)
            if cb: cb()
        try: self.setPosition(min(s0, self.length))
        except Exception: pass
        if getattr(self, "fixMode", False): self._drawAxialCenters(); self._fixHud(True)
        status(f"修正点 {len(pend)} 個で中心線を作り直しました（Ctrl+Z で戻す）")
        return len(pend)

    def _drawPending(self):
        n = self._node("vtkMRMLMarkupsFiducialNode", "SA 修正点", ("vtkMRMLViewNode1", "vtkMRMLSliceNodeYellow", "vtkMRMLSliceNodeRed"), (1.0, 0.85, 0.15), glyph=3.0)
        wasMod = n.StartModify(); n.RemoveAllControlPoints()
        for i, (k, p, sk) in enumerate(getattr(self, "pendingFix", []) or []):
            j = n.AddControlPoint(vtk.vtkVector3d(*p)); n.SetNthControlPointLabel(j, "")
        n.EndModify(wasMod)

    def _rebuildKeep(self, status=print):
        rot0, s0 = self.rot, self.curS
        try: done = self._rebuildLocal(self.path, status)
        except Exception: _err("rebuildLocal"); done = False
        if not done: self.rebuild(self.path, status); self.curS = min(s0, self.length)
        self.setRotation(rot0)
        self._drawMarkers(); self._listsChanged()

    def _rebuildLocal(self, name, status=print):
        """中心線の一部だけ直した時の作り直し（数秒）。変わった範囲だけ切り出し・断面を計算し、それ以外は前の結果を使う。
        下流のねじれ（フレームの回転）は修正範囲の中で少しずつ吸収して、下流は前と同じフレームのまま"""
        c = self.curves.get(name); old = self.frames.get(name); vol = self.straight
        if c is None or old is None or vol is None or self.path != name or self.prof is None or self.arr is None: return False
        cp = slicer.util.arrayFromMarkupsCurvePoints(c, world=True).astype(float)
        new = self._frames(cp)
        Po, Pn = old["P"], new["P"]; Ko, Kn = len(Po), len(Pn); shift = Kn - Ko; m = min(Ko, Kn)
        bad = np.nonzero(np.linalg.norm(Pn[:m] - Po[:m], axis=1) > 0.05)[0]
        a = int(bad[0]) if len(bad) else m
        j = np.arange(Kn); jo = j - shift; ok = (jo >= 0) & (jo < Ko)
        dd = np.full(Kn, np.inf); dd[ok] = np.linalg.norm(Pn[ok] - Po[jo[ok]], axis=1)
        far = np.nonzero(dd > 0.35)[0]
        b = int(far[-1]) if len(far) else a
        a = max(0, a - 8); b = min(Kn - 1, max(b, a) + 8)
        if b - a > 0.6 * Kn or (b + 1 < Kn and b + 1 - shift < 0): return False
        status("直した所だけ作り直しています…")
        P, T, N, B = Pn.copy(), new["T"].copy(), new["N"].copy(), new["B"].copy()
        if b + 1 < Kn:
            ko = b + 1 - shift; n1, n0 = N[b + 1], old["N"][ko]
            phi = math.atan2(np.cross(n1, n0) @ T[b + 1], n1 @ n0)
            for k in range(a, b + 1):
                f = phi * (k - a) / (b + 1 - a); Nk = N[k] * math.cos(f) + np.cross(T[k], N[k]) * math.sin(f)
                N[k] = Nk / np.linalg.norm(Nk); B[k] = np.cross(T[k], N[k])
            for arr, src in ((P, Po), (T, old["T"]), (N, old["N"]), (B, old["B"])): arr[b + 1:] = src[ko:]
        new.update(P=P, T=T, N=N, B=B)
        oldArr = slicer.util.arrayFromVolume(vol).copy()
        out = np.empty((Kn,) + oldArr.shape[1:], np.int16)
        out[:a] = oldArr[:a]; out[a:b + 1] = self._straightArr(P[a:b + 1], N[a:b + 1], B[a:b + 1])
        if b + 1 < Kn: out[b + 1:] = oldArr[b + 1 - shift:]
        oldProf = self.prof
        def remap(d):
            r = {}
            for key, v in d.items():
                if isinstance(key, tuple) and len(key) >= 3 and name in key[:3] and isinstance(key[-1], (int, np.integer)):
                    k = int(key[-1])
                    if k < a: r[key] = v
                    elif k + shift > b: r[key[:-1] + (k + shift,)] = v
                else: r[key] = v
            return r
        self.cache = remap(self.cache); self.override = remap(self.override)
        ds = shift * STEP; lim = b * STEP
        for mk in self.markers:
            if mk.get("path") == name and mk["s"] > lim: mk["s"] += ds
        if self.baseS is not None and self.baseS > lim: self.baseS += ds
        if self.curS > lim: self.curS += ds
        self.frames[name] = new; self._use(name)
        d0 = vol.GetDisplayNode(); wl = (d0.GetWindow(), d0.GetLevel()) if d0 is not None else None
        self.straight = self._straightNode(name, out)
        if wl: self.straight.GetDisplayNode().SetWindowLevel(*wl)              # 見ていたウィンドウはそのまま
        self._built[name] = dict(n=c.GetNumberOfControlPoints(), cp=slicer.util.arrayFromMarkupsControlPoints(c, world=True), frames=new, vol=self.straight)
        self.sharedLen = self._sharedLength()
        status("断面を計算中…")
        self._profile(reuse=(oldProf, a, b, shift))
        self.curS = float(np.clip(self.curS, 0, self.length))
        return True

    # ---------------------------------------------------------------- 中心線の修正
    def recenter(self, name, s=None, status=print):
        c = self.curves.get(name)
        if c is None or self.prof is None: return
        def offsetAt(k):
            m = self._metK(k, "outer")
            if m is None: return None
            cx, cy = m["centroid"]
            if math.hypot(cx, cy) > 20: return None
            return cx * self.B[k] + cy * self.N[k]
        if s is not None:
            k = self._k(s); off = offsetAt(k)
            if off is None: raise RuntimeError("この断面では輪郭が取れません")
            cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
            d = np.linalg.norm(cps - self.P[k], axis=1); i = int(np.argmin(d))
            if d[i] < 6: c.SetNthControlPointPositionWorld(i, *(cps[i] + off))
            else:
                best, bi = 1e9, 0
                for j in range(len(cps) - 1):
                    a, b = cps[j], cps[j + 1]; ab = b - a; t = np.clip((self.P[k] - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                    dd = np.linalg.norm(a + t * ab - self.P[k])
                    if dd < best: best, bi = dd, j
                c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*(self.P[k] + off)))
        else:
            from scipy import ndimage
            ts = np.arange(0, self.length, 5.0); ks = [self._k(t) for t in ts]
            offs = np.array([offsetAt(k) if offsetAt(k) is not None else np.full(3, np.nan) for k in ks], float)
            ok = ~np.isnan(offs[:, 0])
            if ok.sum() < 3: raise RuntimeError("輪郭が取れず、中心を合わせられません")
            for i in range(3): offs[:, i] = np.interp(ts, ts[ok], offs[ok, i])
            offs = ndimage.median_filter(offs, size=(5, 1), mode="nearest"); offs = ndimage.gaussian_filter1d(offs, sigma=2, axis=0, mode="nearest")
            c.RemoveAllControlPoints()
            for t, k, o in zip(ts, ks, offs):
                if t % 10 < 1e-6 or t == ts[-1]: c.AddControlPoint(vtk.vtkVector3d(*(self.P[k] + o)))
        self.rebuild(name, status)

    def editMode(self, on, name):
        lm = slicer.app.layoutManager(); c = self.curves.get(name)
        if on:
            self._editing = True
            for n in (getattr(self, 'contNode', None), getattr(self, 'cursorNode', None), getattr(self, 'clockNode', None)):
                if n is not None: n.GetDisplayNode().SetVisibility(False)
            for ln in (self.dLines or []): ln.GetDisplayNode().SetVisibility(False)
            lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
            slicer.util.setSliceViewerLayers(background=self.vol, foreground=None, label=None, fit=True)
            for nm in ("Red", "Green", "Yellow"):
                w = lm.sliceWidget(nm); sn = w.mrmlSliceNode()
                sn.SetOrientation({"Red": "Axial", "Green": "Coronal", "Yellow": "Sagittal"}[nm]); w.sliceController().setVisible(True)
                io = w.sliceView().interactorObserver()
                for act in (io.BrowseSlice, io.AdjustWindowLevelBackground): io.SetActionEnabled(act, True)
            for it, tag in self._iTags:
                try: it.RemoveObserver(tag)
                except Exception: pass
            self._iTags = []
            for k, cc in self.curves.items():
                d = cc.GetDisplayNode(); d.RemoveAllViewNodeIDs(); d.SetVisibility(k == name); cc.SetLocked(True)   # つまみは Slicer に触らせない（下の自前の操作で動かす）
                if k == name: d.SetLineThickness(0.6); d.SetGlyphScale(2.2); d.SetPointLabelsVisibility(False)
            if c is not None and c.GetNumberOfControlPoints():
                p = self.P[self._k()] if self.P is not None else [0, 0, 0]
                slicer.modules.markups.logic().JumpSlicesToLocation(p[0], p[1], p[2], True)
            self._editTags = []
            for nm in ("Red", "Green", "Yellow"):
                it = lm.sliceWidget(nm).sliceView().interactor()
                self._editTags.append((it, it.AddObserver(vtk.vtkCommand.RightButtonPressEvent, lambda cl, e, nm=nm: self._rightDelete(cl, nm), 1.0)))
                E = vtk.vtkCommand
                self._editTags.append((it, it.AddObserver(E.LeftButtonPressEvent, lambda cl, e, nm=nm: self._edPress(cl, nm), 2.0)))
                self._editTags.append((it, it.AddObserver(E.MouseMoveEvent, lambda cl, e, nm=nm: self._edMove(cl, nm), 2.0)))
                self._editTags.append((it, it.AddObserver(E.LeftButtonReleaseEvent, lambda cl, e, nm=nm: self._edRelease(cl, nm), 2.0)))
                self._editTags.append((it, it.AddObserver(E.KeyPressEvent, lambda cl, e: self._edKey(cl), 2.0)))
            self._edHist = []; self._edDrag = None; self._edAnchors = set()
            for m in slicer.util.getNodesByClass("vtkMRMLModelNode"):          # TEVAR の筒の輪郭は 3 断面では出さない（まぎらわしい）
                if m.GetName().startswith("TEVAR ") and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility2D(False)
            self._edShadow(c)                                                   # 矢状断・冠状断に中心線の全体をうすく出す
            for ov in ("ovRed", "ovGreen", "ovOrange"):                      # 計測用の線・文字は消す（3 断面では意味がない）
                o = getattr(self, ov, None)
                if o is not None:
                    try: o.set([], [])
                    except Exception: pass
            p = self.P[self._k()] if self.P is not None else np.zeros(3)
            for nm, fw in (("Red", 160.0), ("Green", 300.0), ("Yellow", 300.0)):   # 今の位置を真ん中に、見やすい大きさで
                w = lm.sliceWidget(nm); sn = w.mrmlSliceNode()
                try: w.sliceView().cornerAnnotation().ClearAllTexts()
                except Exception: pass
                fov = sn.GetFieldOfView(); r = fov[1] / max(fov[0], 1e-6)
                sn.SetFieldOfView(fw, fw * r, fov[2]); sn.JumpSliceByCentering(float(p[0]), float(p[1]), float(p[2]))
        else:
            for it, tag in getattr(self, "_editTags", []):
                try: it.RemoveObserver(tag)
                except Exception: pass
            self._editTags = []
            for cc in self.curves.values():
                cc.SetLocked(True)
                try: cc.GetDisplayNode().SetSliceProjection(False)
                except Exception: pass
            self._editing = False; self._edDrag = None
            self._edShadow(None)

    def _edShadow(self, c):
        """中心線の全体の通り道を、矢状断・冠状断にうすく描く（編集した点にすぐついていく）"""
        old = getattr(self, "_shadowTag", None)
        if old is not None:
            try: old[0].RemoveObserver(old[1])
            except Exception: pass
            self._shadowTag = None
        for o in getattr(self, "_edOv", []) or []:
            try: o.remove()
            except Exception: pass
        self._edOv = []
        if c is None: return
        from vtk.util.numpy_support import vtk_to_numpy
        self._edOv = [_Overlay(nm) for nm in ("Green", "Yellow") if slicer.app.layoutManager().sliceWidget(nm) is not None]
        def sync(caller=None, ev=None):
            try:
                cp = c.GetCurvePointsWorld()
                if cp is None or cp.GetNumberOfPoints() < 2: return
                pts = vtk_to_numpy(cp.GetData()).astype(float)
                for o in self._edOv: o.set([(pts, (1.0, 0.72, 0.25), False)])
            except Exception as e: print("shadow:", e)
        sync(); self._shadowTag = (c, c.AddObserver(vtk.vtkCommand.ModifiedEvent, sync))

    def _edAbort(self, it):
        for tt, tag in getattr(self, "_editTags", []):
            if tt is it:
                try: it.GetCommand(tag).SetAbortFlag(1)
                except Exception: pass

    def _edPress(self, it, nm):
        """クリック = 近くの中心線をそこへ。押したままドラッグ = ずらす。中心線から遠い所は普段どおり（ウィンドウ）"""
        c = self.curves.get(self.path)
        if c is None or it.GetShiftKey() or it.GetControlKey(): return
        from vtk.util.numpy_support import vtk_to_numpy
        sn = slicer.app.layoutManager().sliceWidget(nm).mrmlSliceNode(); ras = self._rasAt(it, nm)
        M = sn.GetSliceToRAS(); n = np.array([M.GetElement(i, 2) for i in range(3)]); n /= np.linalg.norm(n) + 1e-9
        cp = c.GetCurvePointsWorld()
        if cp is None or cp.GetNumberOfPoints() < 2: return
        pts = vtk_to_numpy(cp.GetData()).astype(float)
        off = (pts - ras) @ n; inpl = pts - np.outer(off, n)
        axial = sn.GetOrientation() == "Axial"
        cand = np.where(np.abs(off) < 6.0)[0] if axial else np.arange(len(pts))     # 矢状断・冠状断は、見えている線（全体）のどこでもつかめる
        if len(cand) == 0: return
        d = np.linalg.norm(inpl[cand] - ras, axis=1); j = int(cand[np.argmin(d)])
        if d.min() > (40.0 if axial else 20.0): return
        q = pts[j]; cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        anc = self.__dict__.setdefault("_edAnchors", set())
        self._edHist.append((cps.copy(), [k for k in range(len(cps)) if c.GetNthControlPointID(k) in anc]))
        dc = np.linalg.norm(cps - q, axis=1); i = int(np.argmin(dc))
        if dc[i] > 6.0:                                                              # 近くに点が無ければ、そこに点を足す
            best, bi = 1e9, 0
            for t_ in range(len(cps) - 1):
                a, b = cps[t_], cps[t_ + 1]; ab = b - a; tt = np.clip((q - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                dd = np.linalg.norm(a + tt * ab - q)
                if dd < best: best, bi = dd, t_
            c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*q)); i = bi + 1
        keep = 0.0 if axial else float((q - ras) @ n)                                 # 矢状断・冠状断では奥行きはそのまま（見えている線を横にずらす）
        base = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        w = self._edWeights(c, base, i)                                               # まわりの点もなめらかについてくる（自分で置いた点は動かさない）
        anc.add(c.GetNthControlPointID(i))
        self._edDrag = (i, nm, keep, n, base, w); self._edApply(c, ras + keep * n); self._edAbort(it)

    SOFT_MM = 22.0          # 動かした点のまわりが、どのくらいの長さ一緒についてくるか

    def _edWeights(self, c, base, i):
        """動かす点 i のまわりの点の「ついてくる割合」。自分で置いた点（アンカー）で止まり、その間はなめらかに減る"""
        n = len(base); a = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(base, axis=0), axis=1))]
        anc = getattr(self, "_edAnchors", set()); isA = np.array([c.GetNthControlPointID(k) in anc for k in range(n)])
        w = np.zeros(n); w[i] = 1.0; sig = self.SOFT_MM
        for side in (-1, 1):
            rng = range(i - 1, -1, -1) if side < 0 else range(i + 1, n)
            stop = next((k for k in rng if isA[k]), None)
            span = abs(a[stop] - a[i]) if stop is not None else None
            for k in (range(i - 1, -1, -1) if side < 0 else range(i + 1, n)):
                if stop is not None and (k <= stop if side < 0 else k >= stop): break
                dist = abs(a[k] - a[i])
                if span is not None and span < 2.5 * sig: w[k] = 0.5 * (1 + math.cos(math.pi * min(dist / span, 1.0)))
                else: w[k] = math.exp(-(dist / sig) ** 2)
                if w[k] < 0.01: break
        w[0] = 0.0 if i != 0 else 1.0; w[-1] = 0.0 if i != n - 1 else 1.0          # 両端（起始・末梢）は動かさない
        return w

    def _edApply(self, c, target):
        i, _, keep, n, base, w = self._edDrag
        off = np.asarray(target, float) - base[i]
        wasMod = c.StartModify()
        for k in np.nonzero(w > 0)[0]: c.SetNthControlPointPositionWorld(int(k), *(base[k] + w[k] * off))
        c.EndModify(wasMod)

    def _edMove(self, it, nm):
        dr = getattr(self, "_edDrag", None)
        if dr is None or dr[1] != nm: return
        keep, n = dr[2], dr[3]; c = self.curves.get(self.path); self._edApply(c, self._rasAt(it, nm) + keep * n); self._edAbort(it)

    def _edRelease(self, it, nm):
        if getattr(self, "_edDrag", None) is None: return
        self._edDrag = None; self._edAbort(it)
        st = getattr(self, "onStatus", None)
        if st: st(f"中心線を動かしました（{len(self._edHist)} 回）。続けてクリック / ドラッグ。終わったら「完了」か Enter。Ctrl+Z で戻す。")

    def _edKey(self, it):
        key = it.GetKeySym() or ""
        if (key in ("z", "Z") and it.GetControlKey()) or key in ("BackSpace",):
            if self._edHist:
                c = self.curves.get(self.path); cps, ai = self._edHist.pop()
                wasMod = c.StartModify(); c.RemoveAllControlPoints()
                for q in cps: c.AddControlPoint(vtk.vtkVector3d(*q))
                c.EndModify(wasMod)
                self._edAnchors = {c.GetNthControlPointID(k) for k in ai if k < c.GetNumberOfControlPoints()}
            self._edAbort(it)
        elif key in ("Return", "KP_Enter", "Escape"):
            cb = getattr(self, "onKey", None)
            if cb: qt.QTimer.singleShot(0, lambda: cb("editdone"))
            self._edAbort(it)

    def _rightDelete(self, it, nm):
        c = self.curves.get(self.path)
        if c is None: return
        x, y = it.GetEventPosition(); sn = slicer.app.layoutManager().sliceWidget(nm).mrmlSliceNode()
        M = sn.GetXYToRAS(); ras = np.array([sum(M.GetElement(r, cc) * v for cc, v in enumerate((x, y, 0, 1))) for r in range(3)])
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        if len(cps) < 4: return
        d = np.linalg.norm(cps - ras, axis=1); i = int(np.argmin(d))
        fov = sn.GetFieldOfView(); dims = sn.GetDimensions(); mmpp = fov[0] / max(dims[0], 1)
        if d[i] < 10 * mmpp + 1.0:
            c.RemoveNthControlPoint(i)
            for tt, tag in self._editTags:
                if tt is it:
                    try: it.GetCommand(tag).SetAbortFlag(1)
                    except Exception: pass

    def startAddPoint(self, name, done=lambda: None):
        c = self.curves.get(name)
        if c is None: return
        tmp = slicer.mrmlScene.GetFirstNodeByName("SA 追加点") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "SA 追加点")
        tmp.RemoveAllControlPoints()
        def onDefined(caller, ev):
            if tmp.GetNumberOfControlPoints() == 0: return
            p = [0, 0, 0]; tmp.GetNthControlPointPositionWorld(0, p); p = np.array(p)
            cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
            best, bi = 1e9, 0
            for i in range(len(cps) - 1):
                a, b = cps[i], cps[i + 1]; ab = b - a; t = np.clip((p - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                d = np.linalg.norm(a + t * ab - p)
                if d < best: best, bi = d, i
            c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*p))
            tmp.RemoveObserver(self._addTag); tmp.RemoveAllControlPoints()
            slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)
            done()
        self._addTag = tmp.AddObserver(slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, onDefined)
        sel = slicer.app.applicationLogic().GetSelectionNode(); sel.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode")
        sel.SetActivePlaceNodeID(tmp.GetID())
        slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)
