# -*- coding: utf-8 -*-
"""大動脈サイジング: 共通（定数・テンプレート・小さな関数・描画の部品）。元の AortaSizing.py の最上位をそのまま移したもの。"""
import os, time, math, json
import numpy as np
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *

STEP = 0.5          # 中心線の刻み (mm)
HALF = 40.0         # ストレッチ像の半幅 (mm)
NEDIT = 24          # 輪郭の制御点の数
SMOOTH_MM = 3.0     # 中心線をならす強さ (mm)
LAYOUT_ID = 5603
LAYOUT_XML = """
<layout type="horizontal" split="true">
 <item splitSize="330"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
 <item splitSize="160"><view class="vtkMRMLSliceNode" singletontag="Green"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">S</property><property name="viewcolor" action="default">#6EB04B</property></view></item>
 <item splitSize="160"><view class="vtkMRMLSliceNode" singletontag="Orange"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">S2</property><property name="viewcolor" action="default">#E8A33D</property></view></item>
 <item splitSize="450">
  <layout type="vertical" split="true">
   <item splitSize="520"><view class="vtkMRMLSliceNode" singletontag="Red"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">X</property><property name="viewcolor" action="default">#F34A33</property></view></item>
   <item splitSize="260"><view class="vtkMRMLSliceNode" singletontag="Yellow"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">A</property><property name="viewcolor" action="default">#EDD54C</property></view></item>
   <item splitSize="220"><view class="vtkMRMLPlotViewNode" singletontag="PlotView1"><property name="viewlabel" action="default">P</property></view></item>
  </layout>
 </item>
</layout>
"""
FIX_LAYOUT_ID = 5604                 # 中心線を合わせる時の画面: 大きな軸位 ＋ 3D ＋ ストレッチ像
FIX_LAYOUT_XML = """
<layout type="horizontal" split="true">
 <item splitSize="700"><view class="vtkMRMLSliceNode" singletontag="Yellow"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">A</property><property name="viewcolor" action="default">#EDD54C</property></view></item>
 <item splitSize="300">
  <layout type="vertical" split="true">
   <item splitSize="500"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
   <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Green"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">S</property><property name="viewcolor" action="default">#6EB04B</property></view></item>
  </layout>
 </item>
</layout>
"""
LUMEN_KEYS = ("aorta", "iliac artery")
PATH_COLORS = {"大動脈→右腸骨": (1.0, 0.6, 0.2), "大動脈→左腸骨": (0.3, 0.85, 1.0), "大動脈": (1.0, 0.85, 0.2)}
PATH_EN = {"大動脈→右腸骨": "Aorta-R iliac", "大動脈→左腸骨": "Aorta-L iliac", "大動脈": "Aorta"}
BRANCHES = [("腕頭動脈", "BCA", ("brachiocephalic trunk",)), ("左総頸動脈", "LCCA", ("common carotid artery left",)),
            ("左鎖骨下動脈", "LSCA", ("subclavian artery left",))]
TEMPLATES = {
    "EVAR": ["最下位腎動脈", "ネック終端（瘤の始まり）", "瘤の最大径", "大動脈分岐", "右内腸骨起始", "左内腸骨起始", "右遠位（総大腿）", "左遠位（総大腿）"],
    "TEVAR": ["腕頭動脈", "左総頸動脈", "左鎖骨下動脈", "近位ランディング", "瘤 / エントリー", "遠位ランディング", "腹腔動脈"],
    "自由": ["マーカー"],
}


def _ensureDecimation():
    """VMTK の前処理が使う Decimation（Slicer 本体の CLI）。軽量化の設定で外れていたらその場で読み込む"""
    if hasattr(slicer.modules, "decimation"): return
    import glob, qt
    fm = slicer.app.moduleManager().factoryManager()
    try:
        ig = list(fm.modulesToIgnore)
        if "Decimation" in ig: ig.remove("Decimation"); fm.modulesToIgnore = ig
    except Exception as e: print("decimation ignore:", e)
    for exe in glob.glob(os.path.join(slicer.app.slicerHome, "lib", "Slicer-*", "cli-modules", "Decimation*")):
        if os.path.splitext(exe)[1].lower() in ("", ".exe"):
            try: fm.registerModule(qt.QFileInfo(exe)); fm.loadModules(["Decimation"])
            except Exception as e: print("decimation load:", e)
            break


def _ensureVMTK(status=print):
    """中心線の部品（SlicerVMTK 拡張）を用意する。無ければその場でダウンロードし、再起動せずに読み込む"""
    _ensureDecimation()
    try:
        import ExtractCenterline; return ExtractCenterline
    except Exception: pass
    import sys, glob
    em = slicer.app.extensionsManagerModel()
    if not em.isExtensionInstalled("SlicerVMTK"):
        status("初回だけ: 中心線の部品（SlicerVMTK）をダウンロードしています（10 秒ほど）…")
        try: em.interactive = False
        except Exception: pass
        ok = False
        try: ok = bool(em.installExtensionFromServer("SlicerVMTK", False))
        except Exception as e: print("vmtk install:", e)
        if not ok: raise RuntimeError("中心線の部品（SlicerVMTK）を入れられませんでした。ネットにつながる状態でもう一度押すか、Slicer の拡張機能から SlicerVMTK を入れてください。")
    base = em.extensionInstallPath("SlicerVMTK")
    for lib in glob.glob(os.path.join(base, "lib", "Slicer-*")):
        L = os.path.join(lib, "qt-loadable-modules"); S = os.path.join(lib, "qt-scripted-modules")
        for p in (L, os.path.join(L, "Python"), S):
            if os.path.isdir(p) and p not in sys.path: sys.path.insert(0, p)
        if os.path.isdir(L):
            try: os.add_dll_directory(L)
            except Exception: pass
            os.environ["PATH"] = L + os.pathsep + os.environ.get("PATH", "")
    try:
        import ExtractCenterline; return ExtractCenterline
    except Exception as e:
        raise RuntimeError(f"中心線の部品を入れました。Slicer を一度閉じて開き直してください（{e}）")


def _err(where):
    import traceback; tb = traceback.format_exc(); print("[AortaSizing]", where, tb)
    try:
        with open(os.path.join(os.path.expanduser("~"), "AortaSizing_error.log"), "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + where + "\n" + tb + "\n")
    except Exception: pass


def _norm(s): return s.lower().replace("_", " ")


def _match(name, key, exact=False):
    """ラベル名の照合（"left common iliac artery" ⇔ "iliac artery left" のように語の集合で比べる）"""
    n = _norm(name); k = _norm(key)
    if exact: return n == k
    nw, kw = set(n.split()), set(k.split())
    return kw <= nw and not ("vein" in nw and "vein" not in kw)


def _clock(x, y):
    """断面上の点 (x=右手方向, y=前方) → 時計の向き（12 時 = 前）"""
    ang = (math.degrees(math.atan2(x, y)) + 360) % 360
    h = ang / 30.0; hh = int(h) or 12; mm = int(round((h - int(h)) * 60 / 15) * 15)
    if mm == 60: hh, mm = (hh % 12) + 1, 0
    return f"{hh}:{mm:02d}"


STYLE = """
QWidget#saRoot { background:#15171c; }
QWidget#saRoot QLabel { color:#e6e8ec; background:transparent; }
QWidget#saRoot QLabel[role="muted"] { color:#8a909b; font-size:11px; }
QWidget#saRoot QLabel[role="h"] { color:#f2f4f7; font-size:13px; font-weight:bold; }
QWidget#saRoot QLabel[role="big"] { color:#ffffff; font-size:24px; font-weight:bold; }
QWidget#saRoot QLabel[role="val"] { color:#ffffff; font-size:16px; font-weight:bold; }
QWidget#saRoot QLabel[role="colh"] { color:#7d8590; font-size:10px; }
QFrame[role="card"] { background:#1e2128; border:1px solid #2b3039; border-radius:12px; }
QWidget#saRoot QPushButton { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:8px; padding:6px 10px; font-size:12px; }
QWidget#saRoot QPushButton:hover { background:#2e333e; border-color:#4a5263; }
QWidget#saRoot QPushButton:pressed { background:#363c49; }
QWidget#saRoot QPushButton:checked { background:#173f57; border:1px solid #4cc8f0; color:#ffffff; }
QWidget#saRoot QPushButton:disabled { color:#5d636e; border-color:#2a2e36; }
QWidget#saRoot QPushButton[kind="primary"] { background:#2f7bf6; border:1px solid #2f7bf6; color:white; font-weight:bold; padding:8px 12px; }
QWidget#saRoot QPushButton[kind="primary"]:hover { background:#4a8dff; }
QWidget#saRoot QPushButton[kind="ghost"] { background:transparent; border:none; color:#8a909b; padding:4px 6px; }
QWidget#saRoot QPushButton[kind="ghost"]:hover { color:#ffffff; }
QWidget#saRoot QPushButton[kind="step"] { background:transparent; border:none; border-bottom:2px solid #2b3039; border-radius:0; color:#8a909b; font-weight:bold; padding:8px 4px; }
QWidget#saRoot QPushButton[kind="step"]:checked { color:#ffffff; border-bottom:2px solid #4cc8f0; background:transparent; }
QWidget#saRoot QPushButton[kind="seg"] { border-radius:6px; padding:5px 8px; }
QWidget#saRoot QPushButton[kind="tool"] { padding:7px 4px; font-size:12px; }
QWidget#saRoot QTableWidget, QWidget#saRoot QListWidget, QWidget#saRoot QTextBrowser {
  background:#181b21; alternate-background-color:#1c2027; color:#e6e8ec; border:1px solid #2b3039; border-radius:8px;
  gridline-color:#232730; selection-background-color:#1f4d69; selection-color:#ffffff; font-size:12px; }
QWidget#saRoot QListWidget::item { padding:6px 6px; border-bottom:1px solid #22262e; }
QWidget#saRoot QListWidget::item:selected { background:#1f4d69; }
QWidget#saRoot QHeaderView::section { background:#181b21; color:#7d8590; border:none; border-bottom:1px solid #2b3039; padding:4px 6px; font-size:11px; }
QWidget#saRoot QScrollBar:vertical { background:transparent; width:8px; }
QWidget#saRoot QScrollBar::handle:vertical { background:#3a404c; border-radius:4px; min-height:24px; }
QWidget#saRoot QScrollBar::add-line, QWidget#saRoot QScrollBar::sub-line { height:0; }
QWidget#saRoot QComboBox { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:8px; padding:5px 8px; }
"""



MARK_EN = {"最下位腎動脈": "Low renal", "ネック終端（瘤の始まり）": "Neck end", "瘤の最大径": "Max sac", "大動脈分岐": "Bifurc",
           "右内腸骨起始": "R IIA", "左内腸骨起始": "L IIA", "右遠位（総大腿）": "R CFA", "左遠位（総大腿）": "L CFA",
           "腕頭動脈": "BCA", "左総頸動脈": "LCCA", "左鎖骨下動脈": "LSCA", "近位ランディング": "Prox LZ",
           "瘤 / エントリー": "Entry", "遠位ランディング": "Dist LZ", "腹腔動脈": "Celiac"}
MARK_EN.update({"上腸間膜動脈": "SMA", "右腎動脈": "R renal", "左腎動脈": "L renal"})
NPOLY = 96          # 輪郭の内部表現の点数


def _resample(xy, n=NPOLY):
    xy = np.asarray(xy, float)
    if len(xy) > 2 and np.linalg.norm(xy[0] - xy[-1]) < 1e-6: xy = xy[:-1]
    c = np.vstack([xy, xy[:1]])
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))]
    if d[-1] <= 0: return None
    t = np.linspace(0, d[-1], n, endpoint=False)
    out = np.c_[np.interp(t, d, c[:, 0]), np.interp(t, d, c[:, 1])]
    a = 0.5 * (np.dot(out[:, 0], np.roll(out[:, 1], -1)) - np.dot(out[:, 1], np.roll(out[:, 0], -1)))
    return out if a >= 0 else out[::-1]


def _inside(xy, p=(0.0, 0.0)):
    x, y = xy[:, 0], xy[:, 1]; x2, y2 = np.roll(x, -1), np.roll(y, -1)
    c = ((y > p[1]) != (y2 > p[1])) & (p[0] < (x2 - x) * (p[1] - y) / (y2 - y + 1e-12) + x)
    return bool(c.sum() % 2)


def _rasterPoly(xy, nu):
    """断面の輪郭 (u, v) mm → 伸ばした画像の格子（行 = N, 列 = B, 0.5 mm）の塗りつぶし"""
    px = np.c_[(xy[:, 0] + HALF) / STEP, (xy[:, 1] + HALF) / STEP]
    A = px; Bq = np.roll(px, -1, 0); m = np.zeros((nu, nu), bool); cols = np.arange(nu)
    for r in range(nu):
        c = (A[:, 1] <= r) != (Bq[:, 1] <= r)
        if not c.any(): continue
        x = np.sort(A[c, 0] + (r - A[c, 1]) * (Bq[c, 0] - A[c, 0]) / (Bq[c, 1] - A[c, 1]))
        for i in range(0, len(x) - 1, 2): m[r, (cols >= x[i]) & (cols <= x[i + 1])] = True
    return m


def _radAt(Rth, rows, ang):
    """半径の輪 Rth[row, 72]（角度 = B 軸から N 軸へ）を、角度 ang で読む（線形補間）"""
    n = Rth.shape[1]; f = (np.mod(ang, 2 * np.pi) / (2 * np.pi)) * n; i0 = np.floor(f).astype(int) % n; i1 = (i0 + 1) % n; w = f - np.floor(f)
    return Rth[rows, i0] * (1 - w) + Rth[rows, i1] * w


def _fitEllipse(x, y):
    """点 (x, y) に楕円を当てはめる（Fitzgibbon の直接法）→ (中心, 長径, 短径, 長軸の角度 rad)。だめなら None"""
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 8: return None
    mx, my = x.mean(), y.mean(); x = x - mx; y = y - my
    D = np.c_[x * x, x * y, y * y, x, y, np.ones_like(x)]; S = D.T @ D; C = np.zeros((6, 6)); C[0, 2] = C[2, 0] = 2; C[1, 1] = -1
    try:
        ev, V = np.linalg.eig(np.linalg.solve(S, C)); V = np.real(V)
    except Exception: return None
    a = None
    for i in range(6):
        if 4 * V[0, i] * V[2, i] - V[1, i] ** 2 > 0: a = V[:, i]; break
    if a is None: return None
    A, B, Cc, Dd, E, F = a
    M = np.array([[A, B / 2], [B / 2, Cc]])
    try: c0 = np.linalg.solve(2 * M, [-Dd, -E])
    except Exception: return None
    Fc = F + 0.5 * (Dd * c0[0] + E * c0[1]); w, U = np.linalg.eigh(M)
    if np.any(w * (-Fc) <= 0): return None
    ax = np.sqrt(-Fc / w); i = int(np.argmax(ax))
    return (c0[0] + mx, c0[1] + my), 2 * float(ax.max()), 2 * float(ax.min()), math.atan2(U[1, i], U[0, i])


def _polyMetrics(xy):
    xy = np.asarray(xy, float)
    if xy is None or len(xy) < 3 or np.isnan(xy).any(): return None
    x, y = xy[:, 0], xy[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    D = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)); i, j = np.unravel_index(np.argmax(D), D.shape)
    ang = np.deg2rad(np.arange(0, 180, 1.0)); dirs = np.c_[np.cos(ang), np.sin(ang)]
    proj = xy @ dirs.T; w = proj.max(0) - proj.min(0); a = int(np.argmin(w))
    dvec = dirs[a]; cen = xy.mean(0)
    pmin = cen + dvec * (proj[:, a].min() - cen @ dvec); pmax = cen + dvec * (proj[:, a].max() - cen @ dvec)
    return dict(area=float(area), deq=2 * math.sqrt(area / math.pi), dmax=float(D[i, j]), dmin=float(w[a]),
                maxLine=(xy[i], xy[j]), minLine=(pmin, pmax), centroid=cen)


def _angle(a, b):
    a = a / (np.linalg.norm(a) + 1e-12); b = b / (np.linalg.norm(b) + 1e-12)
    return math.degrees(math.acos(float(np.clip(a @ b, -1, 1))))


class _Overlay:
    """断面の画面に直接描く軽い線と文字（マーカー部品より 100 倍速い。スクロールが滑らか）"""
    def __init__(self, sliceName):
        w = slicer.app.layoutManager().sliceWidget(sliceName)
        self.sv = w.sliceView(); self.sn = w.mrmlSliceNode()
        self.ren = self.sv.renderWindow().GetRenderers().GetFirstRenderer()
        self.pd = vtk.vtkPolyData(); self.mapper = vtk.vtkPolyDataMapper2D(); self.mapper.SetInputData(self.pd)
        self.mapper.SetScalarModeToUseCellData(); self.mapper.SetColorModeToDirectScalars()
        self.actor = vtk.vtkActor2D(); self.actor.SetMapper(self.mapper); self.actor.GetProperty().SetLineWidth(2.0)
        self.ren.AddActor2D(self.actor)
        self.texts = []; self.lines = []; self.labels = []
        self._tag = self.sn.AddObserver(vtk.vtkCommand.ModifiedEvent, lambda c, e: self._project())
        reg = getattr(slicer, "_saOverlays", None)                      # 1 つのビューに 1 つだけ（作り直し・再読み込みで古いものが残らない）
        if reg is None: reg = slicer._saOverlays = {}
        old = reg.get(sliceName)
        if old is not None and old is not self: old.remove()
        reg[sliceName] = self

    def remove(self):
        try: self.sn.RemoveObserver(self._tag)
        except Exception: pass
        try:
            self.ren.RemoveActor2D(self.actor)
            for t in self.texts: self.ren.RemoveActor2D(t)
            self.texts = []
        except Exception: pass

    def set(self, lines, labels=()):
        """lines: [(ras Nx3, (r,g,b), closed)], labels: [(ras 3, text, (r,g,b), size)]"""
        self.lines = list(lines); self.labels = list(labels); self._project()

    def _xy(self, ras):
        M = vtk.vtkMatrix4x4(); M.DeepCopy(self.sn.GetXYToRAS()); M.Invert()
        A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        ras = np.atleast_2d(np.asarray(ras, float))
        return (np.c_[ras, np.ones(len(ras))] @ A.T)[:, :2]

    def _project(self):
        pts = vtk.vtkPoints(); cells = vtk.vtkCellArray(); cols = vtk.vtkUnsignedCharArray(); cols.SetNumberOfComponents(3)
        n = 0
        for ras, col, closed in self.lines:
            xy = self._xy(ras)
            if len(xy) < 2: continue
            ids = list(range(n, n + len(xy))) + ([n] if closed else [])
            for x, y in xy: pts.InsertNextPoint(float(x), float(y), 0.0)
            cells.InsertNextCell(len(ids))
            for i in ids: cells.InsertCellPoint(i)
            cols.InsertNextTuple3(*[int(255 * c) for c in col]); n += len(xy)
        self.pd.SetPoints(pts); self.pd.SetLines(cells); self.pd.GetCellData().SetScalars(cols); self.pd.Modified()
        while len(self.texts) < len(self.labels):
            t = vtk.vtkTextActor(); tp = t.GetTextProperty(); tp.SetFontFamilyToArial(); tp.BoldOn(); tp.ShadowOn()
            self.ren.AddActor2D(t); self.texts.append(t)
        for i, t in enumerate(self.texts):
            if i < len(self.labels):
                ras, txt, col, size = self.labels[i]; x, y = self._xy(ras)[0]
                t.SetInput(txt); t.GetTextProperty().SetColor(*col); t.GetTextProperty().SetFontSize(int(size))
                t.SetDisplayPosition(int(x) + 6, int(y) + 4); t.SetVisibility(True)
            else: t.SetVisibility(False)
        self.sv.scheduleRender()


_CT_PROTO_CACHE = {}


def _ctProtocol(vol):
    """解析用: CT の撮影・再構成の条件（DICOM から自動）。[(列名, 値)]。読めなければ空欄"""
    keys = [("CT 機種", None), ("管電圧 kV", "0018,0060"), ("再構成関数", "0018,1210"), ("スライス厚 mm", "0018,0050"), ("スライス間隔 mm", None),
            ("画素 mm", "0028,0030"), ("造影剤（DICOM）", "0018,0010"), ("管電流 mA", "0018,1151")]
    if vol is None: return [(k, "") for k, _ in keys]
    ck = (vol.GetID(), vol.GetName())
    if ck in _CT_PROTO_CACHE: return _CT_PROTO_CACHE[ck]
    val = {}
    try:
        db = slicer.dicomDatabase; uids = (vol.GetAttribute("DICOM.instanceUIDs") or "").split()
        f = db.fileForInstance(uids[len(uids) // 2]) if (db is not None and uids) else ""
        if f:
            g = lambda t: (db.fileValue(f, t) or "").strip()
            val["CT 機種"] = " ".join(x for x in (g("0008,0070"), g("0008,1090")) if x)
            for k, t in keys:
                if t: val[k] = g(t)
            px = val.get("画素 mm", "")
            if px: val["画素 mm"] = "×".join(f"{float(x):.3f}" for x in px.split("\\") if x)
    except Exception as e: print("ct protocol:", e)
    try: val["スライス間隔 mm"] = f"{vol.GetSpacing()[2]:.3f}"
    except Exception: pass
    out = [(k, val.get(k, "")) for k, _ in keys]
    _CT_PROTO_CACHE[ck] = out
    return out


__all__ = [n for n in list(globals()) if not n.startswith("__")]   # 部品から * で全部（_ で始まる名前も）使えるように
