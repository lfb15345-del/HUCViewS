# -*- coding: utf-8 -*-
"""大動脈サイジング: 解離: 真腔・偽腔のたどり・らせん・解離の形の CSV
AortaSizingLogic の一部（DissectionMixin）。元の AortaSizing.py の中身をそのまま移したもの。"""
from .common import *


class DissectionMixin:

    def helixMetrics(self, step=2.0, thrFrac=0.6):
        """解離のらせん: 断面ごとに 大動脈（壁の内側）の中心 → 真腔の重心 の向きを見て、遠位へ進む間に何度回るか。
        中心線のフレームはねじれのない平行移動（RMF）なので、回転は真腔そのものの回り方。
        右巻き = 頭側から見下ろして、遠位へ進むと真腔が時計回りに回る（中心線の向き T まわりに右ねじ）"""
        from scipy import ndimage
        if not self.tlValid(): return None
        tl = self.tl; S, rows = [], []
        bif = self._mk("大動脈分岐"); sEnd = float(bif["s"]) if bif is not None and self._onPath(bif) else float(self.length)   # 解析は 基部 〜 大動脈分岐（腸骨は別に見る）
        ilio = None
        if bif is not None and self._onPath(bif):                                # 腸骨（この経路の側）への進展: 分岐の 5〜30 mm 先で真腔が大動脈（腸骨）の一部しかない
            fr_ = []
            for x in np.arange(sEnd + 5.0, min(sEnd + 30.0, self.length), step):
                k = self._k(x); E = self._aortaIn(k, self.path)
                if E is None or (E > 0).sum() < 20: continue
                fr_.append((tl["masks"][k] & (E > 0)).sum() / (E > 0).sum())
            ilio = (bool(np.median(fr_) < thrFrac) if fr_ else None)
        for x in np.arange(0.0, sEnd + 1e-6, step):
            k = self._k(x); E = self._aortaIn(k, self.path)
            if E is None: continue
            A = E > 0; Tm = tl["masks"][k] & A
            if A.sum() < 50 or Tm.sum() < 10: continue
            ca = np.argwhere(A).mean(0); ct = np.argwhere(Tm).mean(0); d = (ct - ca) * STEP           # (行 = N, 列 = B) mm
            rows.append((x, k, Tm.sum() / A.sum(), d[1], d[0], 2 * math.sqrt(A.sum() * STEP * STEP / math.pi)))
        if len(rows) < 10: return None
        R_ = np.array(rows); fr = ndimage.median_filter(R_[:, 2], 5); dis = fr < thrFrac
        if not dis.any(): return dict(dissected=False, sEnd=sEnd, iliac=ilio)
        lab, n = ndimage.label(dis); sz = np.bincount(lab.ravel())[1:]; j = int(np.argmax(sz)) + 1; idx = np.where(lab == j)[0]   # いちばん長い解離の区間
        seg = R_[idx]
        if len(seg) < 5: return dict(dissected=False, sEnd=sEnd, iliac=ilio)
        u = ndimage.gaussian_filter1d(seg[:, 3], 5.0 / step); v = ndimage.gaussian_filter1d(seg[:, 4], 5.0 / step)   # 10 mm ほどでならす
        th = np.unwrap(np.arctan2(v, u)); sgn = -1.0 if np.mean(np.einsum("ij,ij->i", np.cross(self.B[seg[:, 1].astype(int)], self.N[seg[:, 1].astype(int)]), self.T[seg[:, 1].astype(int)])) < 0 else 1.0
        rot = sgn * np.degrees(th - th[0])                                    # B→N の回転は (B×N) まわり → T まわり（右ねじ）を正に直す
        L_ = float(seg[-1, 0] - seg[0, 0]); net = float(rot[-1]); tot = float(np.abs(np.diff(rot)).sum())
        def clock(i):                                                         # 足側から見た時計（前 = 12 時、患者の左 = 3 時）
            k = int(seg[i, 1]); w = u[i] * self.B[k] + v[i] * self.N[k]; w = w - (w @ self.T[k]) * self.T[k]
            ant = w @ np.array([0.0, 1.0, 0.0]); lef = w @ np.array([-1.0, 0.0, 0.0])
            a = (math.degrees(math.atan2(lef, ant)) + 360) % 360; return a, (a / 30.0) or 12.0
        c0, c1 = clock(0), clock(len(seg) - 1)
        return dict(dissected=True, s0=float(seg[0, 0]), s1=float(seg[-1, 0]), length=L_, net=net, total=tot, perCm=net / max(L_, 1e-6) * 10.0,
                    hand=("右巻き" if net > 30 else ("左巻き" if net < -30 else "ほぼ回らない")), clock0=c0[1], clock1=c1[1], maxAbs=float(np.abs(rot).max()),
                    tlFrac=float(np.median(seg[:, 2])), offMax=float(np.hypot(u, v).max()), Dmax=float(seg[:, 5].max()), sEnd=sEnd, iliac=ilio,
                    zones=self._zoneRot(seg[:, 0], rot),
                    curve=list(zip(seg[:, 0].tolist(), rot.tolist())))

    def _appVersion(self):
        try:                                                                  # app/version.txt（この部品のフォルダから上へ探す）
            d = os.path.dirname(os.path.abspath(__file__))
            for _ in range(5):
                f = os.path.join(d, "version.txt")
                if os.path.exists(f): return open(f, encoding="utf-8").read().strip()
                d = os.path.dirname(d)
        except Exception: pass
        return "?"

    def tlQC(self):
        """真腔のたどりの確かさ: 遠位から逆向きにもたどり、上からの結果と食い違う断面（Dice < 0.7）を「要確認」に"""
        if not self.tlValid(): return None
        a = slicer.util.arrayFromVolume(self.straight); K, nu, _ = a.shape; c0 = nu // 2; tl = self.tl
        thr = tl.get("thr") or max(120.0, float(self.thr) - 20.0); fw = tl["masks"]
        bw = np.zeros(a.shape, bool); prev = (c0, c0); prevM = None; lastK = 10 ** 9; hist = []
        for k in range(K - 1, -1, -1):
            ref = float(np.median(hist[-40:])) if len(hist) >= 10 else None
            comp = self._tlSlice(a[k], thr, [(c0, c0), prev], prevM if lastK - k <= 4 else None, ref)
            if comp is None or not comp.any(): continue
            bw[k] = comp; r_, c_ = np.nonzero(comp); prev = (r_.mean(), c_.mean()); prevM = comp; lastK = k; hist.append(comp.sum())
        i = (fw & bw).reshape(K, -1).sum(1); u = fw.reshape(K, -1).sum(1) + bw.reshape(K, -1).sum(1)
        dice = np.where(u > 0, 2 * i / np.maximum(u, 1), 1.0)
        tl["qc"] = dice; return dice

    def dissectionTable(self, step=2.0):
        """断面ごと（2 mm）: 大動脈・真腔の面積、真腔の割合、大動脈の中心 → 真腔の重心（mm・向き・回転・時計）、要確認"""
        h = self.helixMetrics(step=step)
        if not self.tlValid(): return None
        qc = self.tl.get("qc")
        if qc is None: qc = self.tlQC()
        tl = self.tl; rows = []; rot = dict((round(a, 3), b) for a, b in (h.get("curve") or [])) if h else {}
        for x in np.arange(0.0, self.length, step):
            k = self._k(x); E = self._aortaIn(k, self.path)
            if E is None: continue
            A = E > 0; Tm = tl["masks"][k] & A
            if A.sum() < 50: continue
            ca = np.argwhere(A).mean(0); aa = A.sum() * STEP * STEP; ta = Tm.sum() * STEP * STEP
            if Tm.sum() >= 10:
                ct = np.argwhere(Tm).mean(0); d = (ct - ca) * STEP; w = d[1] * self.B[k] + d[0] * self.N[k]; w = w - (w @ self.T[k]) * self.T[k]
                off = float(np.hypot(d[0], d[1])); clk = ((math.degrees(math.atan2(w @ np.array([-1.0, 0, 0]), w @ np.array([0, 1.0, 0]))) + 360) % 360) / 30.0 or 12.0
            else: off, clk = float("nan"), float("nan")
            prof = self.prof[k] if self.prof is not None else [np.nan] * 4
            rows.append(dict(s=float(x), rel=float(self.rel(x)), aArea=aa, aDeq=2 * math.sqrt(aa / math.pi), Dmax=float(prof[2]), Dmin=float(prof[3]),
                             tArea=ta, tFrac=ta / max(aa, 1e-6), off=off, clock=clk, rot=rot.get(round(float(x), 3), float("nan")),
                             qc=("要確認" if qc[k] < 0.7 else "")))
        return rows

    def saveDissectionCSV(self, d=None):
        """解離の形: 断面ごとの表（症例のフォルダ）＋ 1 行の要約（解離らせん_一覧.csv に追記）。版・設定・手直しも一緒に残す"""
        import csv
        rows = self.dissectionTable()
        if rows is None: return None
        d = d or self.outDir()
        fn = os.path.join(d, "解離_断面ごと.csv")
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["位置 mm（中心線）", "基準からの位置 mm", "大動脈 面積 mm2（壁の内側）", "大動脈 Deq", "外周 Dmax", "外周 Dmin", "真腔 面積 mm2", "真腔/大動脈",
                        "真腔の重心のずれ mm", "真腔の位置（時、足側から）", "真腔の回転 度（解離の始まりから）", "要確認"])
            g = lambda v, n=1: "" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{round(v, n) + 0.0:.{n}f}"
            for r in rows:
                w.writerow([g(r["s"]), g(r["rel"]), g(r["aArea"], 0), g(r["aDeq"]), g(r["Dmax"]), g(r["Dmin"]), g(r["tArea"], 0), g(r["tFrac"], 2),
                            g(r["off"]), g(r["clock"]), g(r["rot"], 0), r["qc"]])
        allfn = self.saveHelixCSV()
        return fn, allfn

    def _zoneRot(self, S, rot):
        """区間ごとの回転（度）: 弓部〜左鎖骨下・左鎖骨下〜腹腔動脈・腹腔動脈〜最下位腎動脈・最下位腎動脈〜分岐（解離の中の部分だけ。印が無ければ空）"""
        names = [("弓部〜左鎖骨下", None, "左鎖骨下動脈"), ("左鎖骨下〜腹腔動脈", "左鎖骨下動脈", "腹腔動脈"),
                 ("腹腔動脈〜最下位腎動脈", "腹腔動脈", "最下位腎動脈"), ("最下位腎動脈〜分岐", "最下位腎動脈", "大動脈分岐")]
        out = []
        for lab, a, b in names:
            ma = self._mk(a) if a else None; mb = self._mk(b)
            sa = (ma["s"] if ma is not None and self._onPath(ma) else (S[0] if a is None else None)); sb = mb["s"] if mb is not None and self._onPath(mb) else None
            if a == "左鎖骨下動脈" and sb is None:                                # 腹腔動脈の印が無い時: 左鎖骨下〜最下位腎動脈 でまとめる
                mr = self._mk("最下位腎動脈"); sb = mr["s"] if mr is not None and self._onPath(mr) else None; lab = "左鎖骨下〜最下位腎動脈" if sb is not None else lab
            if a == "腹腔動脈" and sa is None: out.append((lab, None)); continue
            if sa is None or sb is None: out.append((lab, None)); continue
            lo, hi = max(sa, S[0]), min(sb, S[-1])
            out.append((lab, float(np.interp(hi, S, rot) - np.interp(lo, S, rot)) if hi - lo >= 10.0 else None))
        return out

    def helixRow(self):
        h = self.helixMetrics()
        vn = self.vol.GetName() if getattr(self, "vol", None) is not None else ""
        base = [("保存日時", time.strftime("%Y-%m-%d %H:%M")), ("画像（シリーズ）", vn), ("研究 ID（手で記入）", ""), ("経路", self.path or "")]
        if not h: return None
        qc = self.tl.get("qc") if self.tlValid() else None
        nq = 0
        if qc is not None and h.get("dissected"):
            ks = np.arange(self._k(h["s0"]), self._k(h["s1"]) + 1); nq = int((qc[ks] < 0.7).sum() * STEP)
        nfix = len([q for q in ((getattr(self, "plan", None) or {}).get("tlfix") or []) if q.get("path") == self.path])
        ncl = len([q for q in (getattr(self, "_hist", []) or []) if q and q[0] == "center"])
        audit = [("ソフトの版", self._appVersion()), ("真腔の閾値 HU", f"{(self.tl.get('thr') if self.tlValid() else 0) or 0:.0f}"), ("真腔の手直し（クリック数）", str(nfix)),
                 ("中心線の手直し（この作業中の回数）", str(ncl)), ("要確認の長さ mm（上下のたどりが食い違う）", str(nq) if qc is not None else "未確認")] + _ctProtocol(getattr(self, "vol", None))
        rng = [("解析範囲", "基部〜大動脈分岐" if self._mk("大動脈分岐") is not None else "基部〜経路の終わり（分岐の印なし）"),
               ("腸骨への進展（この側）", {True: "あり", False: "なし", None: "不明"}[h.get("iliac")])]
        zcols = ["回転 弓部〜左鎖骨下", "回転 左鎖骨下〜腹腔動脈（印が無ければ〜腎）", "回転 腹腔動脈〜最下位腎動脈", "回転 最下位腎動脈〜分岐"]
        if not h.get("dissected"): return base + rng + [("解離", "なし")] + [(k, "") for k in ("解離の始まり mm", "解離の終わり mm", "解離の長さ mm", "真腔の回転（正味）度", "真腔の回転（合計）度", "最大のずれ 度", "1 cm あたり 度", "巻き", "始まりの真腔の位置（時）", "終わりの真腔の位置（時）", "真腔/大動脈 面積比（中央値）", "真腔の偏り 最大 mm", "大動脈の最大径 mm（区間内）")] + [(z, "") for z in zcols] + audit
        f = lambda x, n=1: f"{x:.{n}f}"
        zr = [(z, "" if v is None else f"{v:.0f}") for z, (_, v) in zip(zcols, h.get("zones") or [(None, None)] * 4)]
        return base + rng + [("解離", "あり"), ("解離の始まり mm", f(self.rel(h["s0"]))), ("解離の終わり mm", f(self.rel(h["s1"]))), ("解離の長さ mm", f(h["length"])),
                       ("真腔の回転（正味）度", f(h["net"], 0)), ("真腔の回転（合計）度", f(h["total"], 0)), ("最大のずれ 度", f(h["maxAbs"], 0)), ("1 cm あたり 度", f(h["perCm"], 1)), ("巻き", h["hand"]),
                       ("始まりの真腔の位置（時）", f(h["clock0"])), ("終わりの真腔の位置（時）", f(h["clock1"])),
                       ("真腔/大動脈 面積比（中央値）", f(h["tlFrac"], 2)), ("真腔の偏り 最大 mm", f(h["offMax"])), ("大動脈の最大径 mm（区間内）", f(h["Dmax"]))] + zr + audit

    def saveHelixCSV(self, d=None):
        row = self.helixRow()
        if not row: return None
        import csv
        hdr = [k for k, _ in row]; val = [v for _, v in row]
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例"); os.makedirs(base, exist_ok=True)
        allfn = os.path.join(base, "解離らせん_一覧.csv")
        if os.path.exists(allfn):
            try: old = open(allfn, encoding="utf-8-sig").readline().strip()
            except Exception: old = ""
            if old != ",".join(hdr): allfn = os.path.join(base, "解離らせん_一覧_" + time.strftime("%Y%m%d") + ".csv")
        new = not os.path.exists(allfn)
        with open(allfn, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
            w = csv.writer(fh)
            if new: w.writerow(hdr)
            w.writerow(val)
        return allfn

    # ================================================================ 真腔（解離）: 伸ばした画像の各断面で、中心線から造影された内腔をたどる（フラップで止まる）
    def tlValid(self):
        tl = getattr(self, "tl", None)
        return tl is not None and tl.get("path") == self.path and tl.get("K") == len(self.P) and tl.get("vol") is self.straight

    def _tlSlice(self, im, thr, seeds, prevMask, ref):
        """1 断面の真腔。seeds = 種の (行, 列) の候補（先が優先）。prevMask = 隣の断面の真腔。ref = 近くの真腔の面積（画素）"""
        from scipy import ndimage
        nu = im.shape[0]; rr, cc = np.mgrid[-2:3, -2:3]; disk = (rr ** 2 + cc ** 2) <= 4
        cl = lambda x: int(min(max(round(float(x)), 2), nu - 3))
        seeds = [(cl(r), cl(c)) for r, c in seeds]
        cv = None
        for r, c in seeds:
            v = float(np.median(im[r - 2:r + 3, c - 2:c + 3]))
            if v >= thr: cv = v; break
        if cv is None: return None
        hasPrev = prevMask is not None and prevMask.any(); comp = None
        for f in (0.7, 0.8, 0.88):                                           # 真腔の明るさの 7 割で区切る（フラップの部分容積で漏れない）。急に広がったら上げる
            m = im > max(thr, f * cv)
            lab, n = ndimage.label(ndimage.binary_opening(m, structure=disk))
            if n == 0: break
            cand = []
            for r, c in seeds:
                if lab[r, c] and lab[r, c] not in cand: cand.append(lab[r, c])
            if hasPrev and len(cand) > 1: cand.sort(key=lambda l: -np.count_nonzero((lab == l) & prevMask))   # 中心線が偽腔に入っても、前の断面の真腔と重なる方
            l = cand[0] if cand else 0
            if not l:
                idx = np.argwhere(lab > 0); d = ((idx - seeds[0]) ** 2).sum(1); j = int(np.argmin(d))
                if d[j] > (10.0 / STEP) ** 2: break
                l = lab[tuple(idx[j])]
            comp = ndimage.binary_fill_holes(ndimage.binary_dilation(lab == l, structure=disk) & m)
            if ref is None or comp.sum() < 1.8 * ref: return comp
        if comp is None or not comp.any(): return None
        if ref is not None and comp.sum() >= 1.8 * ref:                     # フラップの穴（エントリー）で偽腔とつながった: 隣の断面の真腔の形を引き継ぐ（0.5 mm ずつしか広げない）
            if hasPrev: g = ndimage.binary_dilation(prevMask, structure=np.ones((3, 3), bool))
            else:
                r0, c0 = seeds[0]; Rr = 1.3 * math.sqrt(ref / math.pi); yy, xx = np.ogrid[:nu, :nu]; g = (yy - r0) ** 2 + (xx - c0) ** 2 <= Rr * Rr
            c2 = ndimage.binary_fill_holes(comp & g)
            if c2.any():
                lab, n = ndimage.label(c2)
                if n > 1: c2 = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
                comp = c2
        return comp

    def extractTL(self, status=print):
        """真腔: 断面ごとに、中心線の点から造影された内腔を広げる。細いすき間は 1 mm の「開き」で切る。
        フラップの穴で偽腔とつながった断面は、隣の断面の真腔の形を引き継ぐ。手で直した所（plan["tlfix"]）はたどり直す"""
        if self.straight is None: raise RuntimeError("先に中心線を作ってください")
        a = slicer.util.arrayFromVolume(self.straight); K, nu, _ = a.shape; c0 = nu // 2
        thr = max(120.0, float(self.thr) - 20.0)
        masks = np.zeros(a.shape, bool); prev = (c0, c0); prevM = None; lastK = -99; t0 = time.time(); hist = []
        for k in range(K):
            ref = float(np.median(hist[-40:])) if len(hist) >= 10 else None
            comp = self._tlSlice(a[k], thr, [(c0, c0), prev], prevM if k - lastK <= 4 else None, ref)
            if comp is None or not comp.any(): continue
            masks[k] = comp; r_, c_ = np.nonzero(comp); prev = (r_.mean(), c_.mean()); prevM = comp; lastK = k; hist.append(comp.sum())
            if k % 200 == 0: status(f"真腔をたどっています… {100 * k // K}%")
        self.tl = dict(path=self.path, K=K, vol=self.straight, masks=masks, cen2=None, C=None, deq=None, thr=thr)
        self._tlUndo = []
        nfix = 0
        for sd in list((getattr(self, "plan", None) or {}).get("tlfix", []) or []):    # 手で直した所をもう一度
            if sd.get("path") != self.path: continue
            k, uv = self._tlSeedAt(sd)
            if k is not None and self._tlRetrace(a, k, ((uv[1] + HALF) / STEP, (uv[0] + HALF) / STEP)) is not None: nfix += 1
        self._tlFinish()
        status(f"真腔をたどりました（{time.time() - t0:.0f} 秒" + (f"・手で直した {nfix} か所を反映" if nfix else "") + "）。緑の線 = 断面の真腔")
        self._drawTL(); self._showContour(exact=False)
        return self.tl

    def _tlFinish(self):
        """真腔のマスクから、中心（なめらか）・3D の中心・等価径を出し直す"""
        from scipy import ndimage
        tl = self.tl; masks = tl["masks"]; K, nu, _ = masks.shape
        cnt = masks.reshape(K, -1).sum(1); ok = cnt > 0
        if ok.sum() < 10: raise RuntimeError("真腔が見つかりませんでした（中心線が真腔を通っているか確認）")
        ar = np.arange(nu, dtype=float)
        cen = np.c_[(masks.sum(2) @ ar) / np.maximum(cnt, 1), (masks.sum(1) @ ar) / np.maximum(cnt, 1)]
        for j in range(2): cen[:, j] = ndimage.gaussian_filter1d(np.interp(np.arange(K), np.where(ok)[0], cen[ok, j]), 3.0 / STEP)
        u = cen[:, 1] * STEP - HALF; v = cen[:, 0] * STEP - HALF
        deq = np.sqrt(4 * cnt * STEP * STEP / np.pi); deq[~ok] = np.nan
        tl.update(cen2=cen, C=self.P + u[:, None] * self.B + v[:, None] * self.N, deq=deq, ver=tl.get("ver", 0) + 1); tl["_xy"] = {}

    def _tlSeedAt(self, sd):
        """手で直した点（3D）→ いまの中心線の断面 k と (u, v)"""
        ras = np.asarray(sd["ras"], float); k0 = self._k(sd["s"]); w = int(40.0 / STEP)
        ks = np.arange(max(0, k0 - w), min(len(self.P), k0 + w + 1))
        if not len(ks): return None, None
        k = int(ks[np.argmin(np.abs(np.einsum("ij,ij->i", ras - self.P[ks], self.T[ks])))])
        d = ras - self.P[k]; uv = np.array([d @ self.B[k], d @ self.N[k]])
        if np.abs(uv).max() >= HALF: return None, None
        return k, uv

    def _tlRetrace(self, a, k0, seed, maxmm=150.0):
        """断面 k0 の seed（行, 列）から真腔をたどり直す（前後へ。元の真腔と 6 断面続けて重なったら止める）。→ (始まりの k, 元のマスク)"""
        tl = self.tl; masks = tl["masks"]; K = len(masks); thr = tl.get("thr") or max(120.0, float(self.thr) - 20.0)
        cnt = masks.reshape(K, -1).sum(1); w = cnt[max(0, k0 - 60):k0 + 61]; w = w[w > 0]; ref = float(np.median(w)) if len(w) else None
        sr, sc = int(round(seed[0])), int(round(seed[1]))
        pm = None                                                           # 穴の断面: 近くの「ふつうの大きさ」で種を含む真腔の形を手がかりに
        for dk in sorted(range(-20, 21), key=abs):
            kk = k0 + dk
            if dk == 0 or not (0 <= kk < K) or not cnt[kk] or (ref and cnt[kk] >= 1.8 * ref): continue
            if masks[kk][max(sr - 2, 0):sr + 3, max(sc - 2, 0):sc + 3].any(): pm = masks[kk]; break
        c0m = self._tlSlice(a[k0], thr, [seed], pm, ref)
        if c0m is None or not c0m.any(): return None
        new = {k0: c0m}; lo = hi = k0
        for step in (1, -1):
            prevM = c0m; r_, c_ = np.nonzero(c0m); prev = (r_.mean(), c_.mean()); same = miss = 0; hist = [c0m.sum()]
            k = k0 + step
            while 0 <= k < K and abs(k - k0) * STEP <= maxmm:
                rf = float(np.median(hist[-40:])) if len(hist) >= 10 else ref
                comp = self._tlSlice(a[k], thr, [prev], prevM, rf)
                if comp is None or not comp.any():
                    miss += 1
                    if miss > 6: break
                    k += step; continue
                miss = 0; old = masks[k]; un = np.count_nonzero(comp | old)
                iou = np.count_nonzero(comp & old) / un if un else 1.0
                new[k] = comp; lo = min(lo, k); hi = max(hi, k)
                same = same + 1 if iou > 0.8 else 0
                if same >= 6: break
                r_, c_ = np.nonzero(comp); prev = (r_.mean(), c_.mean()); prevM = comp; hist.append(comp.sum()); k += step
        oldM = masks[lo:hi + 1].copy()
        for k, m in new.items(): masks[k] = m
        return lo, oldM

    def fixTL(self, k, uv, status=print):
        """断面 k の (u, v) が本当の真腔: そこから前後をたどり直す。→ 直した長さ mm（だめなら None）"""
        if not self.tlValid(): self.extractTL(status)
        a = slicer.util.arrayFromVolume(self.straight); nu = a.shape[1]
        seed = ((uv[1] + HALF) / STEP, (uv[0] + HALF) / STEP)
        if not (2 <= seed[0] < nu - 2 and 2 <= seed[1] < nu - 2): return None
        r = self._tlRetrace(a, k, seed)
        if r is None: return None
        ras = self.P[k] + uv[0] * self.B[k] + uv[1] * self.N[k]
        self.planInit().setdefault("tlfix", []).append(dict(path=self.path, s=float(self.s[k]), ras=[float(x) for x in ras]))
        self.__dict__.setdefault("_tlUndo", []).append(r); self._tlAfter()
        return len(r[1]) * STEP

    def undoTLFix(self):
        u = getattr(self, "_tlUndo", None)
        if not u or not self.tlValid(): return False
        lo, old = u.pop(); self.tl["masks"][lo:lo + len(old)] = old
        tf = self.planInit().get("tlfix")
        if tf: tf.pop()
        self._tlAfter(); return True

    def _tlAfter(self):
        self._tlFinish(); self.__dict__.get("_depCache", {}).clear(); self.fl = None; self.tl.pop("qc", None)
        self._drawTL(); self._showContour(exact=False)

    def _tlXY(self, k):
        """断面 k の真腔の輪郭（中心からの放射でふち）。(u, v) mm"""
        tl = self.tl; cache = tl.setdefault("_xy", {})
        if k in cache: return cache[k]
        m = tl["masks"][k]
        if not m.any(): cache[k] = None; return None
        r0, c0 = tl["cen2"][k] if np.isfinite(tl["cen2"][k][0]) else np.argwhere(m).mean(0)
        if not (0 <= int(r0) < m.shape[0] and 0 <= int(c0) < m.shape[1]) or not m[int(r0), int(c0)]:
            r0, c0 = np.argwhere(m).mean(0)
        th = np.linspace(0, 2 * np.pi, 96, endpoint=False); dr, dc = np.sin(th)[:, None], np.cos(th)[:, None]
        ss = np.arange(0.0, 2 * m.shape[0], 0.5)[None, :]                  # 中心から 0.5 画素ずつ外へ。最初に真腔を出た所がふち
        rr = np.rint(r0 + dr * (ss + 0.5)).astype(int); cc = np.rint(c0 + dc * (ss + 0.5)).astype(int)
        ok = (rr >= 0) & (rr < m.shape[0]) & (cc >= 0) & (cc < m.shape[1])
        ins = ok & m[np.clip(rr, 0, m.shape[0] - 1), np.clip(cc, 0, m.shape[1] - 1)]
        first = np.where((~ins).any(1), np.argmax(~ins, 1), ins.shape[1]); s_ = first * 0.5
        out = np.c_[(c0 + np.cos(th) * s_) * STEP - HALF, (r0 + np.sin(th) * s_) * STEP - HALF]
        cache[k] = out
        return out

    def extractFL(self, status=print):
        """造影される偽腔: 伸ばした画像で、大動脈の壁の内側・真腔の外にある造影された所"""
        from scipy import ndimage
        if not self.tlValid(): self.extractTL(status)
        a = slicer.util.arrayFromVolume(self.straight); K, nu, _ = a.shape
        thr = max(120.0, float(self.thr) - 20.0); fl = np.zeros(a.shape, bool); area = np.zeros(K)
        for k in range(K):
            E = self._aortaIn(k, self.path)
            if E is None: continue
            m = (a[k] > thr) & (E > 0) & ~ndimage.binary_dilation(self.tl["masks"][k], iterations=2)
            if m.sum() < 16: continue
            lab, n = ndimage.label(ndimage.binary_opening(m))
            if n == 0: continue
            sz = np.bincount(lab.ravel()); keep = np.where(sz >= 16)[0]; keep = keep[keep > 0]
            fl[k] = np.isin(lab, keep); area[k] = fl[k].sum() * STEP * STEP
            if k % 300 == 0: status(f"偽腔をたどっています… {100 * k // K}%")
        on = area >= 20.0; run = np.convolve(on.astype(int), np.ones(6, int), "same") >= 6
        st = int(np.argmax(run)) if run.any() else None
        self.fl = dict(path=self.path, K=K, vol=self.straight, masks=fl, area=area, start=(float(self.s[max(st - 3, 0)]) if st is not None else None))
        self._drawMask(fl, "TEVAR 偽腔", (0.72, 0.42, 0.95), 0.3)
        return self.fl

    def flValid(self):
        fl = getattr(self, "fl", None)
        return fl is not None and fl.get("path") == self.path and fl.get("K") == len(self.P) and fl.get("vol") is self.straight

    def _drawMask(self, masks, name, color, opacity):
        from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        from scipy import ndimage
        m = ndimage.binary_closing(masks, iterations=1).astype(np.uint8)
        img = vtk.vtkImageData(); K, nu, _ = m.shape; img.SetDimensions(nu, nu, K)
        img.GetPointData().SetScalars(numpy_to_vtk(m.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        fe = vtk.vtkDiscreteFlyingEdges3D(); fe.SetInputData(img); fe.SetValue(0, 1); fe.Update()
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(fe.GetOutputPort()); sm.SetNumberOfIterations(25); sm.SetPassBand(0.05); sm.NormalizeCoordinatesOn(); sm.Update()
        pd = sm.GetOutput()
        if pd.GetNumberOfPoints() == 0: return
        X = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        kf = np.clip(X[:, 2], 0, K - 1); k0 = np.floor(kf).astype(int); k1 = np.minimum(k0 + 1, K - 1); f = (kf - k0)[:, None]
        lerp = lambda A: A[k0] * (1 - f) + A[k1] * f
        Q = lerp(self.P) + (X[:, 0] * STEP - HALF)[:, None] * lerp(self.B) + (X[:, 1] * STEP - HALF)[:, None] * lerp(self.N)
        pd.GetPoints().SetData(numpy_to_vtk(np.ascontiguousarray(Q), deep=True))
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOn(); nm.Update()
        self._model(name, nm.GetOutput(), color, opacity, spec=0.2)

    def _drawTL(self):
        """真腔の 3D（うすい水色）"""
        tl = getattr(self, "tl", None)
        if tl is None: return
        from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        from scipy import ndimage
        m = ndimage.binary_closing(tl["masks"], iterations=1).astype(np.uint8)
        img = vtk.vtkImageData(); K, nu, _ = m.shape; img.SetDimensions(nu, nu, K)
        img.GetPointData().SetScalars(numpy_to_vtk(m.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        fe = vtk.vtkDiscreteFlyingEdges3D(); fe.SetInputData(img); fe.SetValue(0, 1); fe.Update()
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(fe.GetOutputPort()); sm.SetNumberOfIterations(25); sm.SetPassBand(0.05); sm.NormalizeCoordinatesOn(); sm.Update()
        pd = sm.GetOutput()
        if pd.GetNumberOfPoints() == 0: return
        X = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)          # (列, 行, k) → 3D
        kf = np.clip(X[:, 2], 0, K - 1); k0 = np.floor(kf).astype(int); k1 = np.minimum(k0 + 1, K - 1); f = (kf - k0)[:, None]
        lerp = lambda A: A[k0] * (1 - f) + A[k1] * f
        Q = lerp(self.P) + (X[:, 0] * STEP - HALF)[:, None] * lerp(self.B) + (X[:, 1] * STEP - HALF)[:, None] * lerp(self.N)
        pd.GetPoints().SetData(numpy_to_vtk(np.ascontiguousarray(Q), deep=True))
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOn(); nm.Update()
        self._model("TEVAR 真腔", nm.GetOutput(), (0.35, 0.75, 1.0), 0.35, spec=0.2)
