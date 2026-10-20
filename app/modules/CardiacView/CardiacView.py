# -*- coding: utf-8 -*-
r"""
CardiacView — 3D Slicer scripted module（かんたんモード版）
HU 帯域ごとの等値面レイヤー ＋ スライダーで動かす切断面 ＋ 視点ボタン。
"""
import os, math, time, re, json
import numpy as np
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_LAYERS = [
    # name,        lo,    hi,   color,                 smooth, visible
    ("軟部組織",   -150,  170, (0.86, 0.66, 0.42), 2, False),
    ("血液・血管",  180, 3000, (0.93, 0.42, 0.50), 1, True),
]
BONE_COLOR = (0.88, 0.86, 0.80)
WALL_COLOR = (0.91, 0.80, 0.58)
EPI_COLOR  = (0.84, 0.72, 0.64)   # 心外膜（外側）: くすんだベージュ（黄色を抑える）
ENDO_COLOR = (0.94, 0.76, 0.72)   # 左心系の内膜: 淡いピンク（内腔は明るく＝空洞に見える）
ENDO_R_COLOR = (0.74, 0.80, 0.94) # 右心系の内膜: 淡い青
SYNTH_COLOR = (0.60, 0.61, 0.64)  # 補った壁（CT 値の裏付けなし）: 冷たいグレー
MYO_CUT_COLOR = (0.64, 0.17, 0.15)  # 心筋の切り口（実質）
MYO_COLOR = (0.55, 0.15, 0.14)    # 心筋（左室＋中隔＋右室自由壁）: 濃い筋肉の赤（実質＝詰まっている）   # 心筋・血管壁（Viewtify 風の黄色）
# 血管の色分け（TotalSegmentator のラベル名に含まれる文字列 → 色）
# 色は2系統だけ: 動脈血（赤系）と静脈血（青系）。彩度を落として落ち着かせる
VESSEL_GROUPS = [
    ("血管:大動脈系", ("aorta", "brachiocephalic trunk", "subclavian artery", "common carotid artery", "iliac artery"), (0.74, 0.14, 0.16)),
    ("血管:体静脈",   ("vena cava", "brachiocephalic vein", "subclavian vein", "jugular vein", "portal vein", "azygos", "iliac vena"), (0.24, 0.34, 0.60)),
    ("血管:肺静脈",   ("pulmonary vein",),                                     (0.84, 0.40, 0.36)),
    ("血管:心臓",     ("heart", "atrial appendage", "atrium", "ventricle", "myocardium"), (0.66, 0.28, 0.32)),
]
VESSEL_OTHER = ("血管:肺動脈ほか", (0.40, 0.52, 0.78))
LEGEND_WALL = [("外膜", (0.84, 0.72, 0.64)), ("左心系の内膜", (0.94, 0.76, 0.72)), ("右心系の内膜", (0.74, 0.80, 0.94)),
               ("補った壁（CT値の裏付けなし）", (0.60, 0.61, 0.64)), ("心筋（AIラベル）", (0.64, 0.17, 0.15))]
IMPLANT_COLOR = (0.80, 0.83, 0.90)  # 人工物（金属: 人工弁のリング・ステント・クリップなど）: 銀
CALC_COLOR = (1.00, 0.92, 0.55)     # 石灰化: 明るい黄白
WIRE_COLOR = (0.96, 0.56, 0.20)     # 胸骨ワイヤー（金属）: 銅色（骨の白と見分ける）
PATCH_COLOR = (0.95, 0.95, 0.92)    # パッチの範囲（自動）: 白（布・心膜のパッチらしく。石灰化の黄白・金属の銀とは別）
LEGEND = [("石灰化", CALC_COLOR), ("人工物(金属)", IMPLANT_COLOR), ("胸骨ワイヤー", WIRE_COLOR), ("パッチの範囲（自動）", PATCH_COLOR), ("大動脈", (0.74, 0.14, 0.16)), ("肺静脈", (0.84, 0.40, 0.36)), ("心腔", (0.66, 0.28, 0.32)),
          ("肺動脈", (0.40, 0.52, 0.78)), ("上下大静脈", (0.24, 0.34, 0.60)), ("心筋・壁", (0.91, 0.80, 0.58))]
# ---- 色合い（設定 → 見た目 → 色合い）。分け方（どの部屋・血管を何色の系統にするか）は同じで、色の濃さ・光沢だけ変える
#   リアル: 動脈血 = 深い赤、静脈血 = 濃い青、心外膜の脂肪 = 黄、骨 = アイボリー。光沢を強めにして立体感を出す（解剖図・シネマティック表示に近い色）
#   落ち着いた: これまでの色（彩度を落とした色）
PALETTES = {
    "リアル": dict(aorta=(0.78, 0.07, 0.08), sysvein=(0.20, 0.22, 0.56), pv=(0.84, 0.16, 0.14), heart=(0.72, 0.09, 0.11), pa=(0.26, 0.31, 0.70),
                 myo=(0.58, 0.07, 0.06), myocut=(0.66, 0.10, 0.08), epi=(0.92, 0.76, 0.40), endo=(0.86, 0.30, 0.26), endoR=(0.40, 0.45, 0.80),
                 bone=(0.96, 0.92, 0.84), calc=(1.00, 0.95, 0.66),
                 vr=[(0.82, 0.16, 0.14), (0.88, 0.28, 0.22), (0.86, 0.10, 0.10), (0.90, 0.24, 0.20), (0.88, 0.28, 0.22),
                     (0.28, 0.32, 0.74), (0.34, 0.40, 0.80), (0.26, 0.30, 0.72), (0.30, 0.35, 0.76)], vrN=(0.86, 0.50, 0.42),
                 spec=0.55, power=40.0, amb=0.18, dif=0.85),
    "落ち着いた": dict(aorta=(0.74, 0.14, 0.16), sysvein=(0.24, 0.34, 0.60), pv=(0.84, 0.40, 0.36), heart=(0.66, 0.28, 0.32), pa=(0.40, 0.52, 0.78),
                  myo=(0.55, 0.15, 0.14), myocut=(0.64, 0.17, 0.15), epi=(0.84, 0.72, 0.64), endo=(0.94, 0.76, 0.72), endoR=(0.74, 0.80, 0.94),
                  bone=(0.88, 0.86, 0.80), calc=(1.00, 0.92, 0.55),
                  vr=[(0.88, 0.44, 0.40), (0.95, 0.62, 0.50), (0.93, 0.30, 0.28), (0.95, 0.55, 0.45), (0.95, 0.62, 0.50),
                      (0.45, 0.58, 0.90), (0.58, 0.68, 0.93), (0.42, 0.50, 0.88), (0.50, 0.62, 0.92)], vrN=(0.88, 0.72, 0.62),
                  spec=0.40, power=35.0, amb=0.12, dif=0.82),
}
PALETTE_KEY = "HUCViewS/palette"
CUR_PALETTE = "リアル"
_VG_BASE = [(g[0], g[1]) for g in VESSEL_GROUPS]


def _setPalette(name):
    """モジュールの色（新しく作る面・凡例・壁の色表）を、選んだ色合いに置き換える"""
    global BONE_COLOR, EPI_COLOR, ENDO_COLOR, ENDO_R_COLOR, MYO_CUT_COLOR, MYO_COLOR, CALC_COLOR, VESSEL_GROUPS, VESSEL_OTHER, LEGEND, LEGEND_WALL, CUR_PALETTE
    if name not in PALETTES: name = "リアル"
    p = PALETTES[name]; CUR_PALETTE = name
    BONE_COLOR, EPI_COLOR, ENDO_COLOR, ENDO_R_COLOR = p["bone"], p["epi"], p["endo"], p["endoR"]
    MYO_CUT_COLOR, MYO_COLOR, CALC_COLOR = p["myocut"], p["myo"], p["calc"]
    VESSEL_GROUPS = [(nm, keys, p[k]) for (nm, keys), k in zip(_VG_BASE, ("aorta", "sysvein", "pv", "heart"))]
    VESSEL_OTHER = ("血管:肺動脈ほか", p["pa"])
    LEGEND = [("石灰化", CALC_COLOR), ("人工物(金属)", IMPLANT_COLOR), ("胸骨ワイヤー", WIRE_COLOR), ("パッチの範囲（自動）", PATCH_COLOR), ("大動脈", p["aorta"]), ("肺静脈", p["pv"]),
              ("心腔", p["heart"]), ("肺動脈", p["pa"]), ("上下大静脈", p["sysvein"]), ("心筋・壁", p["epi"])]
    LEGEND_WALL = [("外膜", p["epi"]), ("左心系の内膜", p["endo"]), ("右心系の内膜", p["endoR"]), ("補った壁（CT値の裏付けなし）", SYNTH_COLOR), ("心筋（AIラベル）", p["myocut"])]
    return p


try: _setPalette(str(qt.QSettings().value(PALETTE_KEY) or "リアル"))
except Exception: pass

CV_LAYOUT_CUT = 5711          # 3D（左・大）＋ 切っている面の断面（右）
CV_LAYOUT_CUT_XML = """
<layout type="horizontal" split="true">
 <item splitSize="600"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
 <item splitSize="420"><view class="vtkMRMLSliceNode" singletontag="Red"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">C</property><property name="viewcolor" action="default">#F39A33</property></view></item>
</layout>
"""
CV_LAYOUT_FOUR = 5712         # 4 画面（2×2 を必ず等分）: 左上 横断 / 右上 3D / 左下 矢状断 / 右下 冠状断
CV_LAYOUT_FOUR_XML = """
<layout type="vertical" split="true">
 <item splitSize="500"><layout type="horizontal" split="true">
  <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Red"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">R</property><property name="viewcolor" action="default">#F34A33</property></view></item>
  <item splitSize="500"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
 </layout></item>
 <item splitSize="500"><layout type="horizontal" split="true">
  <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Yellow"><property name="orientation" action="default">Sagittal</property><property name="viewlabel" action="default">Y</property><property name="viewcolor" action="default">#EDD54C</property></view></item>
  <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Green"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">G</property><property name="viewcolor" action="default">#6EB04B</property></view></item>
 </layout></item>
</layout>
"""
BONE_KEYWORDS = ("rib", "sternum", "vertebra", "clavicula", "scapula", "costal", "humerus", "hip", "sacrum")
MAX_TRIS = 400000          # 1レイヤーあたりの三角形数の上限（操作の軽さ優先）
CUT_MODES = [("切らない", None), ("画面の正面から", "VIEW"), ("前後（冠状断）", 1), ("左右（矢状断）", 0), ("上下（横断）", 2)]


class CardiacView(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "Cardiac View"
        parent.categories = ["HUCVS"]
        parent.dependencies = []
        parent.contributors = ["HUCVS (with Claude)"]
        parent.helpText = "HU 帯域の等値面レイヤー、切断面、視点プリセット。研究・教育用。"
        parent.acknowledgementText = "Built on 3D Slicer, VMTK, TotalSegmentator."


CV_STYLE = """
QWidget#cvRoot { background:#15171c; }
QWidget#cvRoot QLabel { color:#e6e8ec; background:transparent; font-size:12px; }
QWidget#cvRoot QLabel[role="muted"] { color:#8a909b; font-size:11px; }
QWidget#cvRoot QLabel[role="h"] { color:#f2f4f7; font-size:12px; font-weight:bold; }
QWidget#cvRoot QLabel[role="title"] { color:#ffffff; font-size:16px; font-weight:bold; }
QWidget#cvRoot QLabel[role="accent"] { color:#4cc8f0; font-size:12px; font-weight:bold; }
QWidget#cvRoot QLabel[role="colh"] { color:#7d8590; font-size:10px; }
QWidget#cvRoot QFrame[role="card"] { background:#1e2128; border:1px solid #2b3039; border-radius:10px; }
QWidget#cvRoot QPushButton { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:7px; padding:5px 8px; font-size:12px; }
QWidget#cvRoot QPushButton:hover { background:#2e333e; border-color:#4a5263; }
QWidget#cvRoot QPushButton:pressed { background:#363c49; }
QWidget#cvRoot QPushButton:checked { background:#173f57; border:1px solid #4cc8f0; color:#ffffff; font-weight:bold; }
QWidget#cvRoot QPushButton:disabled { color:#5d636e; border-color:#2a2e36; }
QWidget#cvRoot QPushButton[kind="primary"] { background:#2f7bf6; border:1px solid #2f7bf6; color:white; font-weight:bold; padding:8px 12px; font-size:13px; }
QWidget#cvRoot QPushButton[kind="primary"]:hover { background:#4a8dff; }
QWidget#cvRoot QPushButton[kind="primary"]:disabled { background:#2a3a55; border-color:#2a3a55; color:#8a909b; }
QWidget#cvRoot QPushButton[kind="ghost"] { background:transparent; border:none; color:#8a909b; padding:4px 6px; }
QWidget#cvRoot QPushButton[kind="ghost"]:hover { color:#ffffff; }
QWidget#cvRoot QPushButton[kind="step"] { background:transparent; border:none; border-bottom:2px solid #2b3039; border-radius:0; color:#8a909b; font-weight:bold; padding:7px 2px; }
QWidget#cvRoot QPushButton[kind="step"]:hover { color:#cfd3da; }
QWidget#cvRoot QPushButton[kind="step"]:checked { color:#ffffff; border-bottom:2px solid #4cc8f0; background:transparent; }
QWidget#cvRoot QPushButton[kind="seg"] { border-radius:6px; padding:5px 4px; }
QWidget#cvRoot QPushButton[kind="tool"] { padding:6px 2px; }
QWidget#cvRoot QPushButton[kind="vr"] { padding:5px 4px; }
QWidget#cvRoot QPushButton[kind="vr"]:checked { background:#4a2a20; border:1px solid #e8916f; color:#ffffff; }
QWidget#cvRoot QPushButton[kind="play"] { font-weight:bold; font-size:13px; }
QWidget#cvRoot QPushButton[kind="play"]:checked { background:#2f7bf6; border:1px solid #2f7bf6; }
QWidget#cvRoot QCheckBox { color:#e6e8ec; background:transparent; spacing:6px; font-size:12px; }
QWidget#cvRoot QCheckBox:disabled { color:#5d636e; }
QWidget#cvRoot QCheckBox::indicator { width:14px; height:14px; border:1px solid #5a6273; border-radius:4px; background:#262a33; }
QWidget#cvRoot QCheckBox::indicator:hover { border-color:#4cc8f0; }
QWidget#cvRoot QCheckBox::indicator:checked { background:#2f7bf6; border:1px solid #4a8dff; }
QWidget#cvRoot QAbstractSpinBox::up-button, QWidget#cvRoot QAbstractSpinBox::down-button { subcontrol-origin:border; width:16px; background:#2e333e; border:none; }
QWidget#cvRoot QAbstractSpinBox::up-button { subcontrol-position:top right; border-top-right-radius:6px; }
QWidget#cvRoot QAbstractSpinBox::down-button { subcontrol-position:bottom right; border-bottom-right-radius:6px; }
QWidget#cvRoot QAbstractSpinBox::up-button:hover, QWidget#cvRoot QAbstractSpinBox::down-button:hover { background:#3a404c; }
QWidget#cvRoot QComboBox::drop-down { border:none; width:18px; }
QWidget#cvRoot QComboBox { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:7px; padding:4px 8px; font-size:12px; }
QWidget#cvRoot QComboBox QAbstractItemView { background:#1e2128; color:#e6e8ec; selection-background-color:#1f4d69; }
QWidget#cvRoot QSpinBox, QWidget#cvRoot QDoubleSpinBox, QWidget#cvRoot QLineEdit { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:6px; padding:2px 4px; selection-background-color:#1f4d69; font-size:12px; }
QWidget#cvRoot QSlider::groove:horizontal { height:4px; background:#343a46; border-radius:2px; }
QWidget#cvRoot QSlider::sub-page:horizontal { background:#2f7bf6; border-radius:2px; }
QWidget#cvRoot QSlider::handle:horizontal { background:#e6e8ec; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
QWidget#cvRoot QScrollBar:vertical { background:transparent; width:8px; }
QWidget#cvRoot QScrollBar::handle:vertical { background:#3a404c; border-radius:4px; min-height:24px; }
QWidget#cvRoot QScrollBar::add-line, QWidget#cvRoot QScrollBar::sub-line { height:0; }
"""

def _iconCSS():
    """スピン・コンボの矢印とチェックの印（SVG を一時フォルダに書いて使う）"""
    try:
        d = os.path.join(qt.QDir.tempPath(), "hucviews_ui"); os.makedirs(d, exist_ok=True)
        svg = {"up": "<path d='M1 6 L5 1 L9 6' stroke='#c3c8d1' stroke-width='1.6' fill='none'/>",
               "down": "<path d='M1 1 L5 6 L9 1' stroke='#c3c8d1' stroke-width='1.6' fill='none'/>",
               "check": "<path d='M2 6 L5 9 L10 2' stroke='#ffffff' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/>"}
        size = {"up": (10, 7), "down": (10, 7), "check": (12, 11)}
        u = {}
        for k, body in svg.items():
            w, h = size[k]; f = os.path.join(d, k + ".svg")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{body}</svg>")
            u[k] = f.replace("\\", "/")
        return (f"QWidget#cvRoot QAbstractSpinBox::up-arrow {{ image:url({u['up']}); width:10px; height:7px; }}\n"
                f"QWidget#cvRoot QAbstractSpinBox::down-arrow {{ image:url({u['down']}); width:10px; height:7px; }}\n"
                f"QWidget#cvRoot QComboBox::down-arrow {{ image:url({u['down']}); width:10px; height:7px; }}\n"
                f"QWidget#cvRoot QCheckBox::indicator:checked {{ image:url({u['check']}); }}\n")
    except Exception as e:
        print("ui icons:", e); return ""


SC_STYLE = ("QScrollArea{background:#15171c; border:none}"
            "QScrollBar:vertical{background:#15171c; width:10px; margin:0}"
            "QScrollBar::handle:vertical{background:#3a404c; border-radius:4px; min-height:30px; margin:2px}"
            "QScrollBar::handle:vertical:hover{background:#4a5263}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:none}")

HELP_TEXT = ("3D 画面の操作\n"
             "・左ドラッグ: 回転\n"
             "・右ドラッグ: 「右ドラッグ」で選んだ機能（拡大・ウィンドウ・移動・切る位置）\n"
             "・中ボタンドラッグ: 移動\n"
             "・ホイール: 切る位置（1 mm、Shift で 5 mm）。切っていない時は拡大縮小\n"
             "・Ctrl+ホイール: 拡大縮小\n"
             "・左右ボタン同時ドラッグ: VR のウィンドウ\n"
             "4画面\n"
             "・Shift+マウス移動: 3 断面の十字が追従\n"
             "・断面の左ドラッグ: ウィンドウ\n"
             "・ダブルクリック: 1 画面に拡大")


WL_PRESETS = [("心臓・血管（造影）", 800, 200), ("縦隔・軟部", 400, 40), ("石灰化・ステント", 1500, 450), ("骨", 2000, 500), ("肺", 1500, -600)]

TB_STYLE = """
QToolBar#HUCViewSToolBar { background:#15171c; border:none; border-bottom:1px solid #2b3039; spacing:1px; padding:3px 8px; }
QToolBar#HUCViewSToolBar::separator { background:#2b3039; width:1px; margin:6px 7px; }
QToolBar#HUCViewSToolBar QToolButton { color:#c9ced6; background:transparent; border:1px solid transparent; border-radius:7px; padding:3px 5px 2px 5px; font-size:11px; min-width:44px; }
QToolBar#HUCViewSToolBar QToolButton:hover { background:#232730; color:#ffffff; }
QToolBar#HUCViewSToolBar QToolButton:pressed { background:#2b303a; }
QToolBar#HUCViewSToolBar QToolButton:checked { background:#173f57; border:1px solid #4cc8f0; color:#ffffff; }
QToolBar#HUCViewSToolBar QToolButton::menu-indicator { image:none; width:0; }
QToolBar#HUCViewSToolBar QLabel#tbBrand { color:#ffffff; font-size:14px; font-weight:bold; padding:0 10px 0 2px; }
QMenu { background:#1e2128; color:#e6e8ec; border:1px solid #343a46; padding:4px; }
QMenu::item { padding:6px 18px 6px 12px; border-radius:5px; }
QMenu::item:selected { background:#1f4d69; }
QMenu::separator { height:1px; background:#2b3039; margin:4px 6px; }
"""

HELP_HTML = ("<div style='font-size:12px; line-height:150%'>"
             "<b style='color:#4cc8f0'>3D 画面</b><br>"
             "左ドラッグ：回転　／　中ドラッグ：移動<br>"
             "右ドラッグ：上のバーで選んだ機能（拡大・ウィンドウ・移動・切る位置）<br>"
             "ホイール：切る位置（1 mm、Shift で 5 mm）。切っていない時は拡大縮小<br>"
             "Ctrl＋ホイール：拡大縮小　／　左右ボタン同時ドラッグ：VR のウィンドウ<br><br>"
             "<b style='color:#4cc8f0'>断面</b><br>"
             "ホイール：スライス送り　／　左ドラッグ：ウィンドウ<br>"
             "Shift＋マウス：3 断面の十字が追従　／　ダブルクリック：1 画面に拡大<br>"
             "線の真ん中をドラッグ：位置　／　線の端の丸をドラッグ：斜めの断面<br><br>"
             "<b style='color:#4cc8f0'>計測</b><br>"
             "計測にマウスを乗せて Delete：1 つ消す　／　「消去」：すべて消す</div>")


def _toolIcons():
    """ツールバーのアイコン（線画の SVG を一時フォルダに書いて使う）"""
    s = "stroke='#d6dae1' stroke-width='1.7' fill='none' stroke-linecap='round' stroke-linejoin='round'"
    F = "#d6dae1"
    body = {
        "zoom": f"<circle cx='10.5' cy='10.5' r='6.2'/><path d='M15.2 15.2L20.5 20.5M8 10.5h5M10.5 8v5'/>",
        "window": f"<circle cx='12' cy='12' r='8'/><path d='M12 4a8 8 0 0 0 0 16z' fill='{F}'/>",
        "pan": "<path d='M12 3v18M3 12h18M9.5 5.5L12 3l2.5 2.5M9.5 18.5L12 21l2.5-2.5M5.5 9.5L3 12l2.5 2.5M18.5 9.5L21 12l-2.5 2.5'/>",
        "cut": "<path d='M3 15.5l5-4h13l-5 4z'/><path d='M12 9V3M9.8 5.2L12 3l2.2 2.2M12 17.5V21'/>",
        "line": f"<path d='M5.5 18.5l13-13'/><circle cx='5' cy='19' r='1.9' fill='{F}'/><circle cx='19' cy='5' r='1.9' fill='{F}'/>",
        "curve": f"<path d='M4 18c4.5 0 3.5-12 8-12s3.5 12 8 12'/><circle cx='4' cy='18' r='1.7' fill='{F}'/><circle cx='20' cy='18' r='1.7' fill='{F}'/>",
        "area": f"<path d='M5 9l6-4.5 8 4.5-2 10H7z' fill='{F}' fill-opacity='0.18'/>",
        "angle": "<path d='M4 19h16M4 19L14.5 5.5'/><path d='M10.5 19a6.5 6.5 0 0 0-2.4-5'/>",
        "clear": "<path d='M5 7h14M9.5 7V4.5h5V7M7 7l1 13h8l1-13M10.5 11v5.5M13.5 11v5.5'/>",
        "one": "<rect x='4' y='4' width='16' height='16' rx='2.5'/>",
        "two": "<rect x='4' y='4' width='16' height='16' rx='2.5'/><path d='M12 4v16'/>",
        "four": "<rect x='4' y='4' width='16' height='16' rx='2.5'/><path d='M12 4v16M4 12h16'/>",
        "fit": "<path d='M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5'/><rect x='8.5' y='8.5' width='7' height='7' rx='1.5'/>",
        "wl": f"<path d='M4 7h9M17 7h3M4 17h3M11 17h9'/><circle cx='15' cy='7' r='2.2'/><circle cx='9' cy='17' r='2.2'/>",
        "reset": "<path d='M4.5 12a7.5 7.5 0 1 0 2.3-5.4'/><path d='M4.5 4v4.5H9'/>",
        "camera": "<rect x='3' y='7' width='18' height='13' rx='2.5'/><path d='M8.5 7l1.8-3h3.4l1.8 3'/><circle cx='12' cy='13.5' r='3.5'/>",
        "help": f"<circle cx='12' cy='12' r='9'/><path d='M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.6'/><circle cx='12' cy='16.8' r='.8' fill='{F}'/>",
    }
    out = {}
    try:
        d = os.path.join(qt.QDir.tempPath(), "hucviews_ui"); os.makedirs(d, exist_ok=True)
        for k, b in body.items():
            f = os.path.join(d, f"tb_{k}.svg")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(f"<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'><g {s}>{b}</g></svg>")
            out[k] = f
    except Exception as e: print("tool icons:", e)
    return out


class _Hud:
    """画面の上の小さな表示（日本語・半透明の帯）。VTK の文字ではなく Qt のラベルで描く"""
    BOX = "QLabel{background:rgba(14,16,20,178); color:#e6e8ec; border-radius:6px; padding:3px 8px; font-size:12px;}"
    EDGE = "QLabel{background:transparent; color:rgba(245,205,95,230); font-size:13px; font-weight:bold; padding:0;}"

    def __init__(self):
        self.items = {}; self.on = True

    def _view(self, key):
        lm = slicer.app.layoutManager()
        if key == "3d": return lm.threeDWidget(0).threeDView()
        w = lm.sliceWidget(key); return w.sliceView() if w is not None else None

    def set(self, key, pos, html):
        lab = self.items.get((key, pos))
        if not html:
            if lab is not None:
                try: lab.setText(""); lab.hide()
                except Exception: self.items.pop((key, pos), None)
            return
        try:
            v = self._view(key)
            if v is None: return
            if lab is not None and lab.parentWidget() is not v:                # 画面割りを変えると断面の部品が作り直されることがある
                try: lab.hide(); lab.setParent(None); lab.deleteLater()
                except Exception: pass
                lab = None
            if lab is None:
                lab = qt.QLabel(v); lab.setAttribute(qt.Qt.WA_TransparentForMouseEvents, True); lab.setTextFormat(qt.Qt.RichText)
                lab.setStyleSheet(self.EDGE if len(pos) == 1 else self.BOX); self.items[(key, pos)] = lab
            if lab.text != html: lab.setText(html); lab.adjustSize()
            if self.on:
                if not lab.visible: lab.show()
                lab.raise_()
            self._place(pos, lab, key)
        except Exception: self.items.pop((key, pos), None)

    def _place(self, pos, lab, key=None):
        p = lab.parentWidget(); W, H = p.width, p.height; w, h = lab.width, lab.height; m = 8
        x, y = {"tl": (m, m), "tr": (W - w - m, m), "bl": (m, H - h - m), "br": (W - w - m, H - h - m),
                "L": (7, (H - h) // 2), "R": (W - w - 7, (H - h) // 2), "T": ((W - w) // 2, 6), "B": ((W - w) // 2, H - h - 30)}[pos]
        if pos == "T":                                                        # 左上の帯と重なる時は、その下へ
            tl = self.items.get((key, "tl"))
            try:
                if tl is not None and tl.visible and tl.x + tl.width + 4 > x: y = tl.y + tl.height + 3
            except Exception: pass
        lab.move(int(x), int(y))

    def placeAll(self):
        for (k, pos), lab in list(self.items.items()):
            try:
                if lab.visible: self._place(pos, lab, k)
            except Exception: self.items.pop((k, pos), None)

    def show(self, on):
        self.on = bool(on)
        for key, lab in list(self.items.items()):
            try: lab.setVisible(self.on and bool(lab.text))
            except Exception: self.items.pop(key, None)


def _hud():
    h = getattr(slicer, "_cvHud", None)
    if h is not None and not isinstance(h, _Hud):                        # モジュールを読み直した時は古い表示を片づけて作り直す
        try: h.show(False)
        except Exception: pass
        h = None
    if h is None: h = slicer._cvHud = _Hud()
    return h


# =============================================================================== Widget
class CardiacViewWidget(ScriptedLoadableModuleWidget):

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = CardiacViewLogic()
        self.layerRows = []
        app = getattr(slicer, "heartviewAppMode", False)
        B, Lb = self._btn, self._lab

        root = qt.QWidget(); root.setObjectName("cvRoot"); root.setStyleSheet(CV_STYLE + _iconCSS()); root.setAttribute(qt.Qt.WA_StyledBackground, True)
        _sc = qt.QScrollArea(); _sc.setWidgetResizable(True); _sc.setFrameShape(qt.QFrame.NoFrame); _sc.setWidget(root)
        _sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)                      # 横スクロールなし（はみ出さない配置にする）
        _sc.setStyleSheet(SC_STYLE)
        self.layout.addWidget(_sc); self.layout.setContentsMargins(0, 0, 0, 0)
        v = qt.QVBoxLayout(root); v.setContentsMargins(10, 8, 10, 10); v.setSpacing(8); self.root = root

        # ---------------- ヘッダー
        h = qt.QHBoxLayout(); h.setSpacing(4); v.addLayout(h)
        if app:
            back = B("‹ 入口", "ghost", "症例の読み込み（入口）へ戻る"); h.addWidget(back)
            back.connect("clicked()", lambda: slicer.util.selectModule("HeartView"))
        h.addWidget(Lb("CardiacView", "title")); h.addStretch(1)
        self.helpButton = B("？ 操作", "ghost", HELP_TEXT); h.addWidget(self.helpButton)
        self.helpButton.connect("clicked()", lambda: self._showHelp(self.helpButton)); self.helpButton.hide()      # 操作の一覧は上のバーへ
        if app:
            png = B("画像保存", "ghost", "今の画面を PNG で保存"); h.addWidget(png); png.hide()
            def _png():
                import HeartView
                p = HeartView.HeartViewLogic().savePNG(); self._status(f"画像を保存しました: {p}")
            png.connect("clicked()", _png)

        # ---------------- 症例（CT・作成・状態）
        card, c, _ = self._card(v)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r)
        r.addWidget(Lb("CT", "muted"))
        self.volumeSelector = slicer.qMRMLNodeComboBox()
        self.volumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.volumeSelector.addEnabled = False; self.volumeSelector.removeEnabled = False
        self.volumeSelector.noneEnabled = False; self.volumeSelector.showHidden = False
        self.volumeSelector.setMRMLScene(slicer.mrmlScene)
        self.volumeSelector.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Fixed); self.volumeSelector.setMinimumWidth(80)
        r.addWidget(self.volumeSelector, 1)
        self.loadButton = B("開く", None, "ファイルを開く（.nrrd / .nii / .mrb など）"); r.addWidget(self.loadButton)
        self.dicomButton = B("DICOM", None, "1シリーズ分の DICOM フォルダを選ぶ（院内 PC 内で読み込むだけ。外部送信なし）"); r.addWidget(self.dicomButton)
        self.quickButton = B("3D を自動で作る", "primary", "AI で心臓・血管を分けて 3D を作ります。初回 約5〜8分・2回目から約1分"); c.addWidget(self.quickButton)
        self.statusLabel = Lb("CT を選んで「3D を自動で作る」を押してください。", "muted"); self.statusLabel.setWordWrap(True); c.addWidget(self.statusLabel)
        if app:
            for b in (self.loadButton, self.dicomButton): b.hide()
            self.quickButton.setText("3D を作り直す（同じ CT）")

        # ---------------- 見たいもの（ワンクリック。最後に選んだものが次の症例の最初の表示）
        card, c, _ = self._card(v, "見たいもの", "次の症例もこの表示から"); self._sceneLay = c
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.sceneButtons = {}
        for key, text, tip in (("heart", "心臓", "四腔断面で心臓の中を見る"),
                               ("aorta", "大動脈", "大動脈（弓部分枝〜腸骨動脈、撮影範囲の分）を切らずに全体で。人工物・石灰化も表示"),
                               ("vessels", "全血管", "動脈・静脈・肺血管をすべて切らずに見る"),
                               ("body", "骨＋血管", "骨と血管を一緒に（位置関係・術前のオリエンテーション）")):
            b = B(text, "seg", tip, checkable=True); b.setMinimumHeight(30); r.addWidget(b, 1); self.sceneButtons[key] = b

        # ---------------- 4D（同じ撮影の位相が 2 つ以上ある時だけ出る）
        self.box4D, c, hd = self._card(v, "4D", None)
        self.phaseLabel = Lb("", "accent"); hd.addWidget(self.phaseLabel)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r)
        self.play4DButton = B("▶ 再生", "play", "位相を順に表示（VR と断面が動く）。もう一度押すと止まる。切る・回す・4画面はそのまま使える", checkable=True)
        self.play4DButton.setMinimumWidth(78); r.addWidget(self.play4DButton)
        self.phaseSlider = ctk.ctkSliderWidget(); self.phaseSlider.decimals = 0; self.phaseSlider.singleStep = 1; self.phaseSlider.minimum = 0; self.phaseSlider.maximum = 1
        try: self.phaseSlider.spinBoxVisible = False
        except Exception: pass
        self.phaseSlider.setToolTip("位相を 1 つずつ見る"); r.addWidget(self.phaseSlider, 1)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.mode4DButtons = {}; mg4 = qt.QButtonGroup(self.box4D); mg4.setExclusive(True)
        for key, lab, tip in (("blood", "造影", "造影された血液を明るく。心臓の外形や、切った時の内腔の大きさの変化を見る"),
                              ("tissue", "心内構造", "造影された血液を透明にして、弁・乳頭筋・壁の動きを見る。切って使うと見やすい")):
            b = B(lab, "vr", tip, checkable=True); mg4.addButton(b); r.addWidget(b); self.mode4DButtons[key] = b
        self.mode4DButtons["blood"].checked = True; self._mode4DGroup = mg4
        r.addStretch(1)
        self.fpsSpin = qt.QDoubleSpinBox(); self.fpsSpin.setRange(0.5, 30.0); self.fpsSpin.setSingleStep(1.0); self.fpsSpin.setDecimals(1); self.fpsSpin.setSuffix(" /秒")
        self.fpsSpin.setToolTip("再生の速さ（1 秒あたりの位相数）")
        try: self.fpsSpin.setValue(float(qt.QSettings().value("CardiacView/fps4D", 8.0)))
        except Exception: self.fpsSpin.setValue(8.0)
        r.addWidget(self.fpsSpin)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.wl4DButton = B("ウィンドウを戻す", None, "4D の VR と断面のウィンドウ（濃さ・コントラスト）を最初の値に戻す"); r.addWidget(self.wl4DButton); self.wl4DButton.hide()
        r.addStretch(1)
        self.end4DButton = B("4D を終了", None, "4D をやめて、AI で作った面・色分け VR の表示に戻る"); r.addWidget(self.end4DButton)
        self.box4D.hide()

        # ---------------- 右ドラッグ（マウスの機能）
        card, c, hd = self._card(v, "右ドラッグ", None)
        self.wlResetButton = B("ウィンドウを戻す", "ghost", "VR と断面のウィンドウ（濃さ・コントラスト）を最初の値に戻す"); hd.addWidget(self.wlResetButton)
        self.wlResetButton.connect("clicked()", lambda: self.logic.resetWindow())
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.rmodeButtons = {}; rg = qt.QButtonGroup(card); rg.setExclusive(True)
        rtips = {"zoom": "右ドラッグで拡大・縮小", "window": "右ドラッグでウィンドウ（横=幅、縦=中心）", "pan": "右ドラッグで画面を移動", "cut": "右ドラッグで切る位置を動かす"}
        for key, lab in CardiacViewLogic.RMODES:
            b = B(lab, "seg", rtips.get(key), checkable=True); rg.addButton(b); r.addWidget(b, 1); self.rmodeButtons[key] = b
        self.rmodeButtons["zoom"].checked = True; self._rmodeGroup = rg
        card.hide()                                                           # 右ドラッグの切り替えは画像の上のバーへ

        # ---------------- タブ
        tb = qt.QHBoxLayout(); tb.setSpacing(0); v.addLayout(tb)
        self.stack = qt.QWidget(); _stl = qt.QVBoxLayout(self.stack); _stl.setContentsMargins(0, 0, 0, 0); _stl.setSpacing(0); v.addWidget(self.stack)
        self.tabBtns = []; self.pages = []; tg = qt.QButtonGroup(root); tg.setExclusive(True); self._tabGroup = tg
        pages = {}
        self._hidden = qt.QWidget(); self._hidden.hide(); pages["計測"] = qt.QVBoxLayout(self._hidden)   # 計測は画像の上のバーへ（ここは使わない部品の置き場）
        for i, name in enumerate(("表示", "切る", "断面", "設定")):
            b = B(name, "step", None, checkable=True); tg.addButton(b, i); tb.addWidget(b, 1); self.tabBtns.append(b)
            b.connect("clicked()", lambda i=i: self._showTab(i))
            p = qt.QWidget(); pl = qt.QVBoxLayout(p); pl.setContentsMargins(0, 4, 0, 0); pl.setSpacing(8)
            _stl.addWidget(p); self.pages.append(p); p.hide(); pages[name] = pl

        # ===== 表示
        P = pages["表示"]
        card, c, _ = self._card(P, "視点")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.viewButtons = {}
        vtips = {"A": "正面から", "L": "左から", "R": "右から", "S": "頭側から", "P": "背側から", "SURG": "術者の視点（胸骨正中切開）"}
        for lab, key in [("前", "A"), ("左", "L"), ("右", "R"), ("上", "S"), ("後", "P"), ("術者", "SURG")]:
            b = B(lab, "tool", vtips[key]); r.addWidget(b, 1); self.viewButtons[key] = b

        card, c, _ = self._card(P, "描画")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.heartOnlyButton = B("色分け面", None, "心臓・血管を AI の面で表示（血液を部位ごとに色分け）"); r.addWidget(self.heartOnlyButton, 1)
        self.vrTissueButton = B("VR 心内", "vr", "元の CT をそのまま立体に（ボリュームレンダリング）。弁・乳頭筋・肉柱・中隔が見える。\n左右ボタン同時ドラッグでウィンドウを調整", checkable=True)
        self.vrBloodButton = B("VR 造影", "vr", "造影された血液を立体に（ボリュームレンダリング）", checkable=True)
        r.addWidget(self.vrTissueButton, 1); r.addWidget(self.vrBloodButton, 1)

        card, c, hdL = self._card(P, "レイヤー"); self._layerLay = c
        g = qt.QGridLayout(); g.setHorizontalSpacing(10); g.setVerticalSpacing(4); c.addLayout(g)
        self.layerChecks = {}
        for k, name in enumerate(("心臓壁", "心筋", "血液・血管", "軟部組織", "骨", "人工物・石灰化", "パッチ")):
            cb = qt.QCheckBox("心筋（AI）" if name == "心筋" else name); cb.checked = True; g.addWidget(cb, k // 2, k % 2); self.layerChecks[name] = cb
            if name == "心筋": cb.setToolTip("心筋は AI（TotalSegmentator）のラベルから作っています。欠損を塗りつぶすことがあるので、外すと CT 値だけの壁が見えます")
            if name == "人工物・石灰化": cb.setToolTip("金属（人工弁のリング・ステント・クリップ）= 銀、胸骨ワイヤー = 銅色、石灰化 = 黄白")
            if name == "パッチ": cb.setToolTip("術後の CT から自動で出したパッチの範囲（緑）。左室と右室の血液を 2 mm 以下の薄い仕切りだけで隔てている所（術前の CT があれば、術前の穴・術前から同じ所も区別）")
        _it = lambda n, cc: f'<span style="white-space:nowrap"><span style="color:rgb({int(cc[0]*255)},{int(cc[1]*255)},{int(cc[2]*255)})">■</span>{n}</span>'
        leg = " &nbsp;".join(_it(n, cc) for n, cc in LEGEND)
        leg2 = " &nbsp;".join(_it(n, cc) for n, cc in LEGEND_WALL)
        self.legend = Lb("血液: " + leg + "<br>断面: " + leg2, "muted"); self.legend.setWordWrap(True); c.addWidget(self.legend); self.legend.hide()
        self._makeLegend()
        lgb = B("色の見方", "ghost", "色分けの意味"); hdL.addWidget(lgb); lgb.connect("clicked()", lambda: self._popup(lgb, self._legendHtml))

        card, c, _ = self._card(P, "心筋・壁")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.vsdButton = B("心筋の断面", None, "心筋を断面で見る（VSD・中隔）"); r.addWidget(self.vsdButton, 1)
        self.fourChButton = B("四腔断面", None, "左室・右室・中隔・両心房が一度に見える面で切る"); r.addWidget(self.fourChButton, 1)
        self.lumenButton = B("内腔を見る", None, "壁だけ・中は空洞"); r.addWidget(self.lumenButton); self.lumenButton.hide()
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r); r.addWidget(Lb("濃さ", "muted"))
        self.capSlider = ctk.ctkSliderWidget(); self.capSlider.minimum = 0; self.capSlider.maximum = 100; self.capSlider.suffix = " %"
        self.capSlider.setToolTip("心筋の断面の濃さ")
        try: self.capSlider.value = float(qt.QSettings().value("CardiacView/capOpacityV2", 30))   # 初期値 30%
        except Exception: self.capSlider.value = 30
        r.addWidget(self.capSlider, 1)
        self.fillCheck = qt.QCheckBox("薄い壁の穴を補う"); self.fillCheck.checked = True
        self.fillCheck.setToolTip("ON: 部分容積で欠けた薄い壁（心房・大血管）を内腔の外側に約2.4mm足して閉じる。補った所はグレー。\n"
                                  "OFF: CT 値（-20〜175HU）だけで壁を作る。本物の欠損もアーチファクトの穴もそのまま見える。")
        c.addWidget(self.fillCheck)
        self.synthCheck = qt.QCheckBox("補った所をグレーで示す"); self.synthCheck.checked = True
        self.synthCheck.setToolTip("OFF にすると補った壁も同じ色で表示（見た目重視・発表用）。感染などの本物の穴との区別には ON で確認。")
        c.addWidget(self.synthCheck)

        # ===== 切る
        P = pages["切る"]
        card, c, _ = self._card(P, "切断面")
        f = qt.QFormLayout(); f.setHorizontalSpacing(8); f.setVerticalSpacing(6); c.addLayout(f)
        self.cutCombo = qt.QComboBox()
        for lab, _ in CUT_MODES: self.cutCombo.addItem(lab)
        f.addRow(Lb("向き", "muted"), self.cutCombo)
        self.cutSlider = ctk.ctkSliderWidget(); self.cutSlider.minimum = 0; self.cutSlider.maximum = 100; self.cutSlider.value = 50
        self.cutSlider.suffix = " %"
        f.addRow(Lb("位置", "muted"), self.cutSlider)
        self.cutStep = qt.QHBoxLayout(); self.cutStep.setSpacing(4)
        st = qt.QSettings()
        self.stepSpin = qt.QDoubleSpinBox(); self.stepSpin.setRange(0.5, 20.0); self.stepSpin.setSingleStep(0.5); self.stepSpin.setDecimals(1)
        self.stepSpin.setSuffix(" mm"); self.stepSpin.setToolTip("◀ ▶ で動かす幅")
        try: self.stepSpin.setValue(float(st.value("CardiacView/stepMM", 5.0)))
        except Exception: self.stepSpin.setValue(5.0)
        self.cutMinus = B("◀", "tool"); self.cutPlus = B("▶", "tool")
        for b in (self.cutMinus, self.cutPlus): b.setMinimumWidth(40)
        self.cutStep.addWidget(self.cutMinus); self.cutStep.addWidget(self.stepSpin); self.cutStep.addWidget(self.cutPlus); self.cutStep.addStretch(1)
        self.flipButton = B("反転", None, "残す側を反対にする"); self.cutStep.addWidget(self.flipButton)
        f.addRow(Lb("移動", "muted"), self.cutStep)
        self._updateStepLabels()
        self.lockCheck = qt.QCheckBox("この断面で固定")
        self.lockCheck.setToolTip("いい断面ができたらチェック。3D をくるくる回しても切る面は体に固定されたまま。ホイールで面に垂直に平行移動")
        c.addWidget(self.lockCheck)
        self.insetCheck = qt.QCheckBox("左下に全体図（どこを切っているか）"); self.insetCheck.checked = True
        self.insetCheck.setToolTip("左下の小さな図はいつも正面から。オレンジ枠 = 切断面、黄色い線 = 切り口、水色の矢印 = 今見ている向き")
        c.addWidget(self.insetCheck)
        hn = Lb("ホイール: 切る位置 1 mm（Shift 5 mm）", "muted"); hn.setWordWrap(True); c.addWidget(hn)

        card, c, _ = self._card(P, "パッチ（塗って色分け）")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.paintButton = B("パッチを塗る", "vr", "3D の面の上を左ドラッグで緑に塗る（Ctrl＋ドラッグで消す）。何もない所のドラッグはいつもどおり回転。\n"
                             "もう一度押すか Esc で終わり。先に切って中を見せてから塗ると楽です", checkable=True)
        r.addWidget(self.paintButton, 1)
        self.brushBtns = {}; bg = qt.QButtonGroup(card); bg.setExclusive(True); self._brushGroup = bg
        try: bmm = float(qt.QSettings().value("CardiacView/brushMM", 4.0))
        except Exception: bmm = 4.0
        for lab, mm in (("細", 2.5), ("中", 4.0), ("太", 7.0)):
            b = B(lab, "seg", f"筆の太さ（半径 {mm:g} mm）", checkable=True); bg.addButton(b); r.addWidget(b); self.brushBtns[mm] = b
            b.checked = abs(mm - bmm) < 0.01
            b.connect("clicked()", lambda mm=mm: self._setBrush(mm))
        if not any(b.checked for b in self.brushBtns.values()): self.brushBtns[4.0].checked = True
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.patchFaceButton = B("正面から見る", None, "塗ったパッチを正面に向けて、その手前を切る（パッチの面で切る）"); r.addWidget(self.patchFaceButton, 1)
        self.patchUndoButton = B("1つ戻す", None, "最後のひと塗りを取り消す"); r.addWidget(self.patchUndoButton)
        self.patchClearButton = B("全部消す", None, "塗ったパッチを全部消す"); r.addWidget(self.patchClearButton)
        self.redoMetalButton = B("胸骨ワイヤーを色分け（前に作った症例）", "ghost", "前に 3D を作った症例で、骨・胸骨ワイヤー・人工物・石灰化を作り直す（10〜30 秒）"); self._layerLay.addWidget(self.redoMetalButton)
        card.hide()                                                           # 手で塗る方式はやめる（恣意的になる）。CT の値で「似た所」をまとめて選ぶ方式に置き換える予定
        self.paintButton.connect("toggled(bool)", self._onPaint)
        self.patchFaceButton.connect("clicked()", self._onPatchFace)
        self.patchUndoButton.connect("clicked()", lambda: self._status(self.logic.patchUndo()))
        self.patchClearButton.connect("clicked()", lambda: self._status(self.logic.patchClear()))
        self.redoMetalButton.connect("clicked()", self._onRedoMetal)

        # ===== 断面（画面の分け方・MPR）
        P = pages["断面"]
        card, c, _ = self._card(P, "画面")
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.layoutButtons = {}; lg = qt.QButtonGroup(card); lg.setExclusive(True)
        for key, lab, tip in (("3d", "3D", "3D だけを大きく"),
                              ("four", "4画面", "3D ＋ 軸位・矢状断・冠状断（元の CT）。線をドラッグで位置・回して斜め断面。Shift＋マウスで 3 断面をその点へ。ダブルクリックで 1 画面に拡大"),
                              ("cut", "3D＋断面", "左に 3D、右に 3D で切っている面そのものの断面（元の CT）。どちらでホイールを回しても一緒に動く")):
            b = B(lab, "seg", tip, checkable=True); lg.addButton(b); r.addWidget(b, 1); self.layoutButtons[key] = b
        self.layoutButtons["3d"].checked = True; self._layoutGroup = lg
        self.scaleCheck = qt.QCheckBox("目盛り（平行投影）"); self.scaleCheck.checked = True; self.scaleCheck.setToolTip("3D を平行投影にして長さの目盛りを出す（断面にも）")
        c.addWidget(self.scaleCheck)
        card.hide()                                                           # 画面割りは画像の上のバーへ

        card, c, hd = self._card(P, "MPR")
        self.mprResetButton = B("リセット", "ghost", "斜めにした断面を、軸位・矢状断・冠状断に戻す"); hd.addWidget(self.mprResetButton)
        self.obliqueCheck = qt.QCheckBox("線で斜めに（端の丸をドラッグ）"); self.obliqueCheck.checked = True
        self.obliqueCheck.setToolTip("4画面の色つきの線をドラッグ: 真ん中 = 位置、端の丸 = 回して斜めの断面（好きな MPR）")
        c.addWidget(self.obliqueCheck)
        self.outlineCheck = qt.QCheckBox("3D の輪郭を重ねる"); self.outlineCheck.setToolTip("3D の面（心臓・血管）の切り口の線を断面に重ねる")
        c.addWidget(self.outlineCheck)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r); r.addWidget(Lb("MIP 厚さ", "muted"))
        self.slabCombo = qt.QComboBox()
        for lab in ("なし", "5 mm", "10 mm", "20 mm", "40 mm"): self.slabCombo.addItem(lab)
        self.slabCombo.setToolTip("断面に厚みを持たせて最大値投影（血管・冠動脈を追いやすい）"); r.addWidget(self.slabCombo); r.addStretch(1)

        card, c, _ = self._card(P, "斜めの微調整")
        self.rotView = qt.QComboBox()
        for lab in ("軸位の中で回す", "矢状断の中で回す", "冠状断の中で回す"): self.rotView.addItem(lab)
        self.rotView.setToolTip("選んだ断面の中で、ほかの断面の線（向き）を回す。断面の上で [ ] キーでも 1°（Shift で 5°）")
        c.addWidget(self.rotView)
        r = qt.QHBoxLayout(); r.setSpacing(4); c.addLayout(r)
        self.rotButtons = []
        for lab, deg in (("↺5°", 5.0), ("↺1°", 1.0), ("↻1°", -1.0), ("↻5°", -5.0)):
            b = B(lab, "tool"); r.addWidget(b, 1); self.rotButtons.append((b, deg))
        self.mprAngleLabel = Lb("0°", "accent"); self.mprAngleLabel.setWordWrap(True); c.addWidget(self.mprAngleLabel)

        # ===== 計測
        P = pages["計測"]
        card, c, hd = self._card(P, "計測")
        self.rulerClearButton = B("すべて消す", "ghost", "測った線・面積・角度をすべて消す（1 つだけ消す時は、その計測にマウスを乗せて Delete キー）"); hd.addWidget(self.rulerClearButton)
        g = qt.QGridLayout(); g.setHorizontalSpacing(4); g.setVerticalSpacing(4); c.addLayout(g)
        self.measureButtons = {}
        tips = {"line": "2 点クリックで長さ", "poly": "クリックで点を追加、右クリックで終了。折れ線の長さ",
                "curve": "クリックで点を追加、右クリックで終了。なめらかな曲線に沿った長さ（血管・弁輪など）",
                "area": "輪郭をクリックで囲み、右クリックで終了。面積と周長", "angle": "3 点クリックで角度"}
        for k, (key, lab, cls, pre) in enumerate(CardiacViewLogic.MEASURES):
            b = B(lab, "tool", tips[key]); g.addWidget(b, k // 3, k % 3); self.measureButtons[key] = b
        hn = Lb("3D の面・VR の上、または断面の上でクリック。1 つ消す: マウスを乗せて Delete", "muted"); hn.setWordWrap(True); c.addWidget(hn)

        card, c, _ = self._card(P, "大動脈")
        self.aortaButton = B("大動脈サイジングへ  ›", "primary", "中心線 → 径の表 → CSV（ステントグラフトのサイジング）"); c.addWidget(self.aortaButton)
        self.flyButton = B("大動脈の中に入る", None, "中心線に沿って大動脈の中から見る（先に大動脈サイジングで中心線を作る）"); c.addWidget(self.flyButton)
        r = qt.QHBoxLayout(); r.setSpacing(6); c.addLayout(r); r.addWidget(Lb("位置", "muted"))
        self.flySlider = ctk.ctkSliderWidget(); self.flySlider.minimum = 0; self.flySlider.maximum = 100; self.flySlider.value = 20
        self.flySlider.setToolTip("中心線上の位置"); r.addWidget(self.flySlider, 1)

        # ===== 設定
        P = pages["設定"]
        card, c, _ = self._card(P, "3D の作り方")
        f = qt.QFormLayout(); f.setHorizontalSpacing(8); c.addLayout(f)
        self.resSpin = qt.QDoubleSpinBox(); self.resSpin.setRange(0.4, 3.0); self.resSpin.setSingleStep(0.1); self.resSpin.value = 1.2; self.resSpin.suffix = " mm"
        f.addRow(Lb("メッシュ解像度", "muted"), self.resSpin)
        self.boneCheck = qt.QCheckBox("骨を別レイヤーにする"); self.boneCheck.checked = True
        self.boneCheck.setToolTip("TotalSegmentator の骨ラベルで骨を分ける"); c.addWidget(self.boneCheck)
        grid = qt.QGridLayout(); grid.setHorizontalSpacing(4); grid.setVerticalSpacing(3); c.addLayout(grid)
        for col, hh in enumerate(["", "名前", "下限 HU", "上限 HU", "色", "平滑"]):
            grid.addWidget(Lb(hh, "colh"), 0, col)
        for i, (name, lo, hi, col, sm, vis) in enumerate(DEFAULT_LAYERS):
            self._addLayerRow(grid, i + 1, name, lo, hi, col, sm, vis)
        grid.setColumnStretch(1, 1)
        self.buildButton = B("この設定で作り直す", None, "上のレイヤー設定で面を作り直す"); c.addWidget(self.buildButton)

        card, c, _ = self._card(P, "見た目"); self._lookLay = c
        f = qt.QFormLayout(); f.setHorizontalSpacing(8); f.setVerticalSpacing(6); c.addLayout(f)
        self.bgCombo = qt.QComboBox(); self.bgCombo.addItems(["黒", "濃いグレー", "白"]); f.addRow(Lb("背景", "muted"), self.bgCombo)
        self.paletteCombo = qt.QComboBox(); self.paletteCombo.addItems(["リアル（くっきり）", "落ち着いた（前の色）"])
        self.paletteCombo.setToolTip("面と VR の色合い。分け方は同じで、色の濃さと光沢だけ変わる")
        self.paletteCombo.currentIndex = 0 if CUR_PALETTE == "リアル" else 1; f.addRow(Lb("色合い", "muted"), self.paletteCombo)
        self.glossSlider = ctk.ctkSliderWidget(); self.glossSlider.minimum = 0; self.glossSlider.maximum = 100; self.glossSlider.value = 50; f.addRow(Lb("光沢", "muted"), self.glossSlider)
        self.opacitySlider = ctk.ctkSliderWidget(); self.opacitySlider.minimum = 0; self.opacitySlider.maximum = 100; self.opacitySlider.value = 100; f.addRow(Lb("血液の不透明度", "muted"), self.opacitySlider)
        self.fovSlider = ctk.ctkSliderWidget(); self.fovSlider.minimum = 15; self.fovSlider.maximum = 120; self.fovSlider.value = 30; f.addRow(Lb("視野角", "muted"), self.fovSlider)
        self.ssaoCheck = qt.QCheckBox("陰影で奥行きを出す（環境光遮蔽）"); self.ssaoCheck.checked = True; c.addWidget(self.ssaoCheck); self.ssaoCheck.hide()
        self.shadeCombo = qt.QComboBox(); self.shadeCombo.addItems(["なし", "ふつう", "強め"])
        self.shadeCombo.setToolTip("面: 環境光遮蔽（くぼみが暗くなる）と光の当たり方の差。VR: 環境光を下げてメリハリ。重い PC では自動で 1 段下げる")
        try: _lv = str(qt.QSettings().value("HUCViewS/shading") or "ふつう")
        except Exception: _lv = "ふつう"
        self.shadeCombo.currentIndex = {"なし": 0, "ふつう": 1, "強め": 2}.get(_lv, 1); f.addRow(Lb("陰影", "muted"), self.shadeCombo)

        card, c, _ = self._card(P, "その他"); self._otherLay = c
        self.freePlaneButton = B("自由な切断面を追加", None, "3D 上のハンドルで向き・位置を操作する切断面"); c.addWidget(self.freePlaneButton)
        r = qt.QHBoxLayout(); r.setSpacing(4); pages["計測"].addLayout(r)
        self.distButton = B("距離", "tool", "Slicer 標準の距離マーカー"); self.angleButton = B("角度", "tool", "Slicer 標準の角度マーカー"); self.curveButton = B("閉曲線", "tool", "Slicer 標準の閉曲線マーカー")
        for b in (self.distButton, self.angleButton, self.curveButton): r.addWidget(b, 1)
        self.saveButton = B("シーンを保存（.mrb）", None, "表示・計測をまとめて 1 ファイルに保存"); c.addWidget(self.saveButton)

        # ---- 置き場所の整理（同じものを 2 か所に置かない。専門的な設定は「設定」へ）
        r = qt.QHBoxLayout(); r.setSpacing(6); self._sceneLay.addLayout(r)
        self.aortaButton.setProperty("kind", ""); self.aortaButton.setText("大動脈サイジング  ›"); r.addWidget(self.aortaButton, 1)
        self.aortaButton.style().unpolish(self.aortaButton); self.aortaButton.style().polish(self.aortaButton)
        self._lookLay.addWidget(self.scaleCheck)
        card, c, _ = self._card(pages["設定"], "壁の補正"); c.addWidget(self.fillCheck); c.addWidget(self.synthCheck)
        self._otherLay.addWidget(self.flyButton)
        rr = qt.QHBoxLayout(); rr.setSpacing(6); rr.addWidget(Lb("中心線上の位置", "muted")); rr.addWidget(self.flySlider, 1); self._otherLay.addLayout(rr)
        self._otherLay.addWidget(self.saveButton)
        v.addStretch(1)
        try: t0 = int(qt.QSettings().value("CardiacView/tab", 0))
        except Exception: t0 = 0
        self._showTab(t0 if 0 <= t0 < len(self.pages) else 0)

        # ---- signals
        self.loadButton.connect("clicked()", self.onLoad)
        self.dicomButton.connect("clicked()", self.onLoadDicom)
        self.quickButton.connect("clicked()", self.onQuick)
        self.buildButton.connect("clicked()", self.onBuild)
        self.cutTimer = qt.QTimer(); self.cutTimer.setSingleShot(True); self.cutTimer.setInterval(60)
        self.cutTimer.connect("timeout()", self._applyCut)
        self.cutCombo.connect("currentIndexChanged(int)", lambda i: self._applyCut())
        self.cutSlider.connect("valueChanged(double)", lambda v: self.cutTimer.start())
        self.flipButton.connect("clicked()", lambda: (self.logic.flipCut(), None))
        self.lockCheck.connect("toggled(bool)", self._onLock)
        self.insetCheck.connect("toggled(bool)", lambda on: self.logic.setInsetVisible(on))
        self.cutMinus.connect("clicked()", lambda: self._nudge(-self.stepSpin.value))
        self.cutPlus.connect("clicked()", lambda: self._nudge(+self.stepSpin.value))
        self.stepSpin.connect("valueChanged(double)", self._onStepChanged)
        for key, b in self.viewButtons.items():
            b.connect("clicked()", lambda k=key: self.logic.setView(k, self.fovSlider.value))
        for name, cb in self.layerChecks.items():
            cb.connect("toggled(bool)", lambda v, n=name: self._onLayerCheck(n, v))
        self.heartOnlyButton.connect("clicked()", self.onHeartOnly)
        self.lumenButton.connect("clicked()", self.onLumen)
        self.vsdButton.connect("clicked()", self.onVSD)
        self.fourChButton.connect("clicked()", self.onFourChamber)
        for key, b in self.sceneButtons.items(): b.connect("clicked()", lambda key=key: self.onScene(key))
        self.capSlider.connect("valueChanged(double)", self._onCapChanged)
        self.fillCheck.connect("toggled(bool)", self._onFillToggled)
        self.synthCheck.connect("toggled(bool)", self._onSynthToggled)
        self.vrTissueButton.connect("clicked()", lambda: self._onVR("tissue"))
        for key, b in self.layoutButtons.items(): b.connect("clicked()", lambda k=key: self.logic.setLayout(k))
        self.obliqueCheck.connect("toggled(bool)", lambda on: self.logic.setObliqueHandles(on))
        self.slabCombo.connect("currentIndexChanged(int)", lambda i: self.logic.setSlab([0, 5, 10, 20, 40][i]))
        self.mprResetButton.connect("clicked()", lambda: self.logic.resetMPR())
        self.outlineCheck.connect("toggled(bool)", lambda on: self.logic.setOutlines2D(on))
        for b, deg in self.rotButtons:
            b.connect("clicked()", lambda deg=deg: self.logic.rotateMPR(("Red", "Yellow", "Green")[self.rotView.currentIndex], deg))
        for key, b in self.rmodeButtons.items(): b.connect("clicked()", lambda k=key: self.logic.setRightMode(k))
        self.scaleCheck.connect("toggled(bool)", lambda on: self.logic.setScale(on))
        msgs = {"line": "始点と終点をクリック", "poly": "点をクリックで追加、終わったら右クリック", "curve": "点をクリックで追加、終わったら右クリック",
                "area": "輪郭を囲むようにクリック、終わったら右クリック", "angle": "3 点クリック（2 点目が角の頂点）"}
        for key, b in self.measureButtons.items():
            b.connect("clicked()", lambda k=key: (self.logic.startMeasure(k), self._status(msgs[k] + "（3D の面・VR の上、または断面）")))
        self.rulerClearButton.connect("clicked()", self.logic.clearRulers)
        self.vrBloodButton.connect("clicked()", lambda: self._onVR("blood"))
        self.bgCombo.connect("currentIndexChanged(int)", lambda i: self.logic.setBackground(i))
        self.paletteCombo.connect("currentIndexChanged(int)", self.onPalette)
        self.shadeCombo.connect("currentIndexChanged(int)", self.onShade)
        self.glossSlider.connect("valueChanged(double)", lambda v: self.logic.setGloss(v / 100.0))
        self.opacitySlider.connect("valueChanged(double)", lambda v: self.logic.setLayerOpacity("血液・血管", v / 100.0))
        self.ssaoCheck.connect("toggled(bool)", lambda v: self.logic.studioLighting(self.bgCombo.currentIndex, ssao=v))
        self.fovSlider.connect("valueChanged(double)", lambda v: self.logic.setFov(v))
        self.freePlaneButton.connect("clicked()", lambda: self.logic.addFreePlane())
        self.flyButton.connect("clicked()", lambda: self.logic.flyAorta(self.flySlider.value / 100.0))
        self.flySlider.connect("valueChanged(double)", lambda v: self.logic.flyAorta(v / 100.0, onlyIfFlying=True))
        self.distButton.connect("clicked()", lambda: self.logic.placeMarkup("vtkMRMLMarkupsLineNode", "距離"))
        self.angleButton.connect("clicked()", lambda: self.logic.placeMarkup("vtkMRMLMarkupsAngleNode", "角度"))
        self.curveButton.connect("clicked()", lambda: self.logic.placeMarkup("vtkMRMLMarkupsClosedCurveNode", "閉曲線"))
        self.aortaButton.connect("clicked()", self.onAortaSizing)
        self.saveButton.connect("clicked()", self.onSave)
        self.play4DButton.connect("toggled(bool)", self._onPlay4D)
        self.phaseSlider.connect("valueChanged(double)", self._onPhase4D)
        self.fpsSpin.connect("valueChanged(double)", self._onFps4D)
        self.end4DButton.connect("clicked()", self._end4D)
        for key, b in self.mode4DButtons.items(): b.connect("clicked()", lambda k=key: (self.logic.show4D(True), self.logic.set4DMode(k), self._label4D()))
        self.wl4DButton.connect("clicked()", lambda: (self.logic.resetWindow(), self._status("ウィンドウを最初の値に戻しました")))
        self._t4D = qt.QTimer(); self._t4D.setInterval(100); self._t4D.connect("timeout()", self._tick4D)
        self._uiTimer = qt.QTimer(); self._uiTimer.setInterval(200); self._uiTimer.connect("timeout()", self._uiTick)
        self._buildToolbar()

    # ---------------------------------------------------------------- 4D
    # ---------------------------------------------------------------- 画像の上のツールバー（商用ビューアと同じく、よく使う操作は画像のすぐ上）
    def _buildToolbar(self):
        mw = slicer.util.mainWindow()
        for old in mw.findChildren(qt.QToolBar):
            if old.objectName == "HUCViewSToolBar":
                try: mw.removeToolBar(old); old.setParent(None); old.deleteLater()
                except Exception: pass
        tb = qt.QToolBar("HUCViewS"); tb.setObjectName("HUCViewSToolBar"); tb.setMovable(False); tb.setFloatable(False)
        tb.setIconSize(qt.QSize(22, 22)); tb.setStyleSheet(TB_STYLE); tb.setContextMenuPolicy(qt.Qt.PreventContextMenu)
        mw.addToolBarBreak(qt.Qt.TopToolBarArea); mw.addToolBar(qt.Qt.TopToolBarArea, tb); self.tb = tb; self.tbButtons = {}   # 1 段まるごと使う
        ic = _toolIcons()
        brand = qt.QLabel(getattr(slicer, "heartviewAppTitle", "HUCViewS")); brand.setObjectName("tbBrand"); tb.addWidget(brand)

        def add(key, text, tip, cb=None, checkable=False, group=None):
            b = qt.QToolButton(); b.setText(text); b.setToolTip(tip); b.setCheckable(checkable); b.setAutoRaise(True)
            if key in ic: b.setIcon(qt.QIcon(ic[key]))
            b.setToolButtonStyle(qt.Qt.ToolButtonTextUnderIcon); b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
            if group is not None: group.addButton(b)
            if cb is not None: b.connect("clicked()", cb)
            tb.addWidget(b); self.tbButtons[key] = b; return b

        g = qt.QButtonGroup(tb); g.setExclusive(True); self._tbModeGroup = g
        for key, (k, text, tip) in zip(("zoom", "window", "pan", "cut"),
                                       (("zoom", "拡大", "右ドラッグで拡大・縮小"), ("window", "ウィンドウ", "右ドラッグで濃さ（横=幅、縦=中心）。VR と断面"),
                                        ("pan", "移動", "右ドラッグで画面を動かす"), ("cut", "切る位置", "右ドラッグで切る面を前後に動かす"))):
            add("m_" + k, text, tip, lambda k=k: self._setMode(k), True, g).setIcon(qt.QIcon(ic.get(key, "")))
        tb.addSeparator()
        msgs = {"line": "始点と終点をクリック", "curve": "点をクリックで追加、終わったら右クリック",
                "area": "輪郭を囲むようにクリック、終わったら右クリック", "angle": "3 点クリック（2 点目が角の頂点）"}
        for k, text, tip in (("line", "直線", "2 点クリックで長さ"), ("curve", "カーブ", "曲線に沿った長さ（血管・弁輪など）"),
                             ("area", "面積", "囲んだ面積と周長"), ("angle", "角度", "3 点で角度")):
            add(k, text, tip, lambda k=k: (self.logic.startMeasure(k), self._status(msgs[k] + "（3D の面・VR の上、または断面）")))
        add("clear", "消去", "計測をすべて消す（1 つだけ消す時は、マウスを乗せて Delete）", self.logic.clearRulers)
        tb.addSeparator()
        lg = qt.QButtonGroup(tb); lg.setExclusive(True); self._tbLayoutGroup = lg
        for key, k, text, tip in (("one", "3d", "1画面", "3D だけを大きく"), ("two", "cut", "2画面", "左に 3D、右に今切っている面の断面"),
                                  ("four", "four", "4画面", "3D ＋ 軸位・矢状断・冠状断")):
            add("l_" + k, text, tip, lambda k=k: self._setLayoutTb(k), True, lg).setIcon(qt.QIcon(ic.get(key, "")))
        tb.addSeparator()
        add("fit", "全体表示", "見えているもの全体が画面に収まるように", lambda: (self.logic._fitParallel(recenter=True), self.logic._view().scheduleRender()))
        b = add("wl", "W/L", "断面のウィンドウをよく使う値に")
        m = qt.QMenu(b); m.setStyleSheet(TB_STYLE)
        for name, w, l in WL_PRESETS:
            a = m.addAction(f"{name}　　W {w} / L {l}")
            a.connect("triggered()", lambda w=w, l=l, name=name: (self.logic.applyWL(w, l), self._status(f"断面のウィンドウ: {name}（W {w} / L {l}）")))
        m.addSeparator(); a = m.addAction("最初の値に戻す"); a.connect("triggered()", self._wlReset)
        b.setMenu(m); b.setPopupMode(qt.QToolButton.InstantPopup)
        add("reset", "戻す", "VR と断面のウィンドウを最初の値に戻す", self._wlReset)
        sp = qt.QWidget(); sp.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred); tb.addWidget(sp)
        add("camera", "画像保存", "今の画面を PNG で保存", self._savePNG)
        add("help", "操作", "マウス・キーの操作の一覧", lambda: self._showHelp(self.tbButtons["help"]))
        tb.hide()

    def _setMode(self, k):
        self.logic.setRightMode(k)
        b = self.rmodeButtons.get(k)
        if b is not None: b.checked = True

    def _setLayoutTb(self, k):
        b = self.layoutButtons.get(k)
        if b is not None: b.checked = True
        self.logic.setLayout(k)

    def _wlReset(self):
        self.logic.resetWindow(); self._status("ウィンドウを最初の値に戻しました")

    def _savePNG(self):
        try:
            import HeartView
            p = HeartView.HeartViewLogic().savePNG(); self._status(f"画像を保存しました: {p}")
        except Exception as e:
            self._status(f"画像の保存に失敗しました: {e}")

    def _showHelp(self, anchor):
        self._popup(anchor, HELP_HTML)

    def _makeLegend(self):
        _sq = lambda cc: f"<span style='color:rgb({int(cc[0]*255)},{int(cc[1]*255)},{int(cc[2]*255)}); font-size:15px'>■</span>"
        _rows = lambda L: "".join(f"<tr><td>{_sq(cc)}</td><td style='padding-left:6px'>{n}</td></tr>" for n, cc in L)
        self._legendHtml = ("<div style='font-size:12px'><b style='color:#4cc8f0'>血液・血管の色</b><table>" + _rows(LEGEND) + "</table><br>"
                            "<b style='color:#4cc8f0'>断面（壁）の色</b><table>" + _rows(LEGEND_WALL) + "</table></div>")

    def onShade(self, i):
        lv = ("なし", "ふつう", "強め")[i]
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: msg = self.logic.setShading(lv)
        except Exception as e: import traceback; traceback.print_exc(); msg = ""
        finally: qt.QApplication.restoreOverrideCursor()
        if msg:
            self.shadeCombo.blockSignals(True); self.shadeCombo.currentIndex = ("なし", "ふつう", "強め").index(self.logic.shadeLevel); self.shadeCombo.blockSignals(False)
            try: self.statusLabel.setText(msg)
            except Exception: print(msg)

    def onPalette(self, i):
        name = "リアル" if i == 0 else "落ち着いた"
        try: qt.QSettings().setValue(PALETTE_KEY, name)
        except Exception: pass
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: self.logic.applyPalette(name)
        except Exception as e: import traceback; traceback.print_exc()
        finally: qt.QApplication.restoreOverrideCursor()
        self._makeLegend()

    def _popup(self, anchor, html):
        p = qt.QLabel(html); p.setWindowFlags(qt.Qt.Popup); p.setTextFormat(qt.Qt.RichText)
        p.setStyleSheet("QLabel{background:#1e2128; color:#e6e8ec; border:1px solid #343a46; border-radius:8px; padding:12px 14px;}")
        p.adjustSize()
        g = anchor.mapToGlobal(qt.QPoint(anchor.width, anchor.height + 4))
        p.move(max(0, g.x() - p.width), g.y()); p.show(); self._helpPop = p

    def _tbSync(self):
        """ツールバーの押された状態を、今のモード・画面割りに合わせる"""
        L = self.logic; tbb = getattr(self, "tbButtons", {})
        b = tbb.get("m_" + getattr(L, "rmode", "zoom"))
        if b is not None and not b.checked: b.checked = True
        b = tbb.get("l_" + getattr(L, "layoutKind", "3d"))
        if b is not None and not b.checked: b.checked = True

    def cleanup(self):
        """モジュールを読み直す時: タイマーを止め、ツールバーと画面上の表示を片づける"""
        for t in ("_uiTimer", "_t4D"):
            try: getattr(self, t).stop()
            except Exception: pass
        try: _hud().show(False)
        except Exception: pass
        try:
            mw = slicer.util.mainWindow(); mw.removeToolBar(self.tb); self.tb.setParent(None); self.tb.deleteLater()
        except Exception: pass

    def _uiTick(self):
        if getattr(self, "tb", None) is None: return
        try:
            if slicer.util.selectedModule() != "CardiacView": return
            self._tbSync(); self.logic._hudUpdate()
            L = self.logic; pn = L.layerModels.get("パッチ")                       # パッチの範囲を出している時は「推定したイメージ」と添える
            have = pn is not None and slicer.mrmlScene.IsNodePresent(pn) and pn.GetPolyData() is not None and pn.GetPolyData().GetNumberOfPoints() > 0
            on = bool(have and ((pn.GetDisplayNode() is not None and pn.GetDisplayNode().GetVisibility()) or getattr(L, "vrOn", False)))
            if getattr(self, "_patchNoteOn", None) != on:
                L._setUL("2_patch", "<span style='color:#f2f2ec'>白 = パッチの範囲</span>　<span style='color:#9aa7b4'>CT から推定した手術のイメージ（教育用・診断には使いません）</span>" if on else "")
                self._patchNoteOn = on
            sb = getattr(self, "_seqBar", None)
            if sb is None:
                sb = self._seqBar = next((t for t in slicer.util.mainWindow().findChildren(qt.QToolBar) if t.objectName == "SequenceBrowserToolBar"), False)
            if sb and sb.visible: sb.hide()
        except Exception as e:
            if "destroyed" in str(e): self._uiTimer.stop()                    # 古い画面（読み直し前）のタイマー
            else: print("ui tick:", e)

    def enter(self):
        try: self._sync4D()
        except Exception as e: print("4D sync:", e)
        try:
            if getattr(self, "tb", None) is not None: self.tb.show()
            _hud().show(True); self.logic._applyChrome()
            self._uiTimer.start(); self._uiTick()
        except Exception as e: print("ui enter:", e)

    def exit(self):
        try:                                                                  # ほかの画面（大動脈サイジングなど）へ行く時は 4D を終える（動く VR が残らない）
            if self.play4DButton.checked: self.play4DButton.checked = False
            if getattr(self.logic, "on4D", False): self.logic.show4D(False)
        except Exception: pass
        try:
            if getattr(self, "tb", None) is not None: self.tb.hide()
            self._uiTimer.stop(); _hud().show(False)
            if not getattr(slicer, "heartviewAppMode", False):                # Slicer の通常画面では 3D のバーを戻す
                slicer.app.layoutManager().threeDWidget(0).threeDController().setVisible(True)
        except Exception: pass

    def _sync4D(self):
        L = self.logic; n = L.n4D() if hasattr(L, "n4D") else 0
        self.box4D.setVisible(n >= 2)
        if n < 2: return
        self.phaseSlider.blockSignals(True); self.phaseSlider.maximum = n - 1; self.phaseSlider.value = max(0, L.phase4D()); self.phaseSlider.blockSignals(False)
        self._label4D()

    def _label4D(self):
        L = self.logic; i = max(0, L.phase4D()); n = L.n4D(); labs = getattr(L, "labels4D", []) or []
        lab = labs[i] if i < len(labs) and labs[i] else f"{i + 1}"
        self.phaseLabel.setText(f"{lab}  ({i + 1}/{n})")
        try:
            L._setUL("1_4d", f"<span style='color:#f5cd5f'><b>4D</b>　{lab}（{i + 1}/{n}）</span>" if getattr(L, "on4D", False) else "")
        except Exception: pass

    def _onLayerCheck(self, name, on):
        L = self.logic; L.setLayerVisible(name, on)
        if getattr(L, "on4D", False) and on and not any(k in L.STATIC_4D for k in L._namesFor(name)):
            self._status(f"4D 中は「{name}」の面は出しません（動く心臓と重なるため）。「面の 3D に戻る」で表示されます。骨・軟部組織・人工物は 4D でも一緒に出せます。")

    def _onPlay4D(self, on):
        L = self.logic
        if on:
            L.show4D(True); L.play4D(True, self.fpsSpin.value); self.play4DButton.setText("❚❚ 止める"); self._t4D.start()
            self._status("4D 再生中: 回す・切る・4画面はそのまま使えます。スライダーで 1 位相ずつ。")
        else:
            L.play4D(False); self.play4DButton.setText("▶ 再生"); self._t4D.stop(); self._sync4D()

    def _onPhase4D(self, v):
        L = self.logic
        if self.play4DButton.checked: self.play4DButton.checked = False
        L.show4D(True); L.set4DPhase(int(round(v))); self._label4D()

    def _onFps4D(self, v):
        qt.QSettings().setValue("CardiacView/fps4D", float(v))
        if self.play4DButton.checked: self.logic.play4D(True, v)

    def _tick4D(self):
        L = self.logic
        if not L.has4D(): self._t4D.stop(); return
        self.phaseSlider.blockSignals(True); self.phaseSlider.value = max(0, L.phase4D()); self.phaseSlider.blockSignals(False)
        self._label4D()

    def _end4D(self):
        if self.play4DButton.checked: self.play4DButton.checked = False
        self.logic.show4D(False); self._label4D(); self._status("面の 3D に戻しました")

    # ---------------------------------------------------------------- UI 部品（AortaSizing と同じ見た目）
    def _card(self, parent_layout, title=None, sub=None):
        f = qt.QFrame(); f.setProperty("role", "card"); lay = qt.QVBoxLayout(f); lay.setContentsMargins(10, 8, 10, 10); lay.setSpacing(6)
        h = None
        if title:
            h = qt.QHBoxLayout(); h.setSpacing(4); t = qt.QLabel(title); t.setProperty("role", "h"); h.addWidget(t); h.addStretch(1)
            if sub: s = qt.QLabel(sub); s.setProperty("role", "muted"); h.addWidget(s)
            lay.addLayout(h)
        parent_layout.addWidget(f); return f, lay, h

    def _btn(self, text, kind=None, tip=None, checkable=False):
        b = qt.QPushButton(text)
        if kind: b.setProperty("kind", kind)
        if tip: b.setToolTip(tip)
        b.setCheckable(checkable); b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
        b.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Fixed); return b

    def _lab(self, text, role=None):
        l = qt.QLabel(text)
        if role: l.setProperty("role", role)
        return l

    def _showTab(self, i):
        for j, p in enumerate(self.pages): p.setVisible(j == i)              # 見えているページの高さだけ取る（空白を作らない）
        self.tabBtns[i].checked = True
        try: qt.QSettings().setValue("CardiacView/tab", int(i))
        except Exception: pass

    # ---------------------------------------------------------------- helpers
    def _addLayerRow(self, grid, r, name, lo, hi, col, sm, vis):
        visCb = qt.QCheckBox(); visCb.checked = vis; grid.addWidget(visCb, r, 0)
        nameEdit = qt.QLineEdit(name); nameEdit.setMinimumWidth(50); nameEdit.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Fixed); nameEdit.setToolTip(name); grid.addWidget(nameEdit, r, 1)
        loSpin = qt.QSpinBox(); loSpin.setRange(-1024, 3000); loSpin.value = lo; loSpin.setMaximumWidth(62); grid.addWidget(loSpin, r, 2)
        hiSpin = qt.QSpinBox(); hiSpin.setRange(-1024, 3000); hiSpin.value = hi; hiSpin.setMaximumWidth(62); grid.addWidget(hiSpin, r, 3)
        colBtn = ctk.ctkColorPickerButton(); colBtn.color = qt.QColor.fromRgbF(*col); colBtn.displayColorName = False; colBtn.setMaximumWidth(34); grid.addWidget(colBtn, r, 4)
        smCombo = qt.QComboBox(); smCombo.addItems(["なし", "弱", "強"]); smCombo.currentIndex = sm; smCombo.setMaximumWidth(64); grid.addWidget(smCombo, r, 5)
        self.layerRows.append(dict(vis=visCb, name=nameEdit, lo=loSpin, hi=hiSpin, col=colBtn, sm=smCombo))

    def _layerSpecs(self):
        specs = []
        for row in self.layerRows:
            c = row["col"].color
            specs.append(dict(name=row["name"].text, lo=row["lo"].value, hi=row["hi"].value,
                              color=(c.redF(), c.greenF(), c.blueF()), smooth=row["sm"].currentIndex, visible=row["vis"].checked))
        return specs

    def _status(self, msg):
        self.statusLabel.text = msg; slicer.app.processEvents()

    def _applyCut(self):
        axis = CUT_MODES[self.cutCombo.currentIndex][1]
        if self.logic.cutAxis == "LOCK" and axis == "VIEW":                # 固定中はスライダーで固定した面を動かす
            self.logic.setCut("LOCK", self.cutSlider.value / 100.0); return
        if self.lockCheck.checked:
            self.lockCheck.blockSignals(True); self.lockCheck.checked = False; self.lockCheck.blockSignals(False); self.logic._lockN = None
        self.logic.setCut(axis, self.cutSlider.value / 100.0)

    def _onLock(self, on):
        L = self.logic
        if on:
            if L.cutAxis is None:                                           # まだ切っていなければ「画面の正面から」で切ってから固定
                self.cutCombo.setCurrentIndex(1); L.setCut("VIEW", self.cutSlider.value / 100.0)
            ok = L.lockCut(True)
            if ok:
                self.cutSlider.blockSignals(True); self.cutSlider.value = L.cutFrac * 100; self.cutSlider.blockSignals(False)
                self._status("断面を固定しました。左ドラッグで回しても切り口はそのまま。ホイールで面を平行移動。")
            else:
                self.lockCheck.blockSignals(True); self.lockCheck.checked = False; self.lockCheck.blockSignals(False)
        else:
            L.lockCut(False); self._status("固定を外しました（切る面はまた画面の正面に合わせます）。")

    def _updateStepLabels(self):
        mm = self.stepSpin.value
        self.cutMinus.setText("◀"); self.cutPlus.setText("▶")
        self.cutMinus.setToolTip(f"{mm:g} mm 戻す"); self.cutPlus.setToolTip(f"{mm:g} mm 進める")

    def _onStepChanged(self, v):
        self._updateStepLabels()
        qt.QSettings().setValue("CardiacView/stepMM", float(v))   # 次回も同じ刻みで

    def _onVR(self, mode):
        btn, other = (self.vrTissueButton, self.vrBloodButton) if mode == "tissue" else (self.vrBloodButton, self.vrTissueButton)
        on = btn.checked
        if on and getattr(self.logic, "on4D", False): self._end4D()
        other.blockSignals(True); other.checked = False; other.blockSignals(False)
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.logic.showVR(on, mode if on else None)
            self._status("VR 表示中: 左右ボタン同時ドラッグでウィンドウ調整（横=幅、縦=中心）。ホイールで切る位置。" if on else "面の表示に戻しました")
        except Exception as e:
            import traceback; traceback.print_exc(); btn.checked = False; self._status(f"VR エラー: {e}")
        finally:
            qt.QApplication.restoreOverrideCursor()

    def _onSynthToggled(self, on):
        self.logic.showSynth = bool(on)
        if self.logic.layerModels.get("心臓壁") is not None: self.logic.colorWallEpiEndo()

    def _onFillToggled(self, on):
        L = self.logic
        if L.layerModels.get("心臓壁") is None: return
        L.wallFill = bool(on)
        self._status("壁を作り直しています…（約5秒）"); slicer.app.processEvents()
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            L.rebuildWall()
            L._applyClipToModels(L.cutAxis is not None)
            if L.cutAxis is not None: L.setCut(L.cutAxis, getattr(L, "cutFrac", 0.5))
            L.setCapOpacity(self.capSlider.value / 100.0)
        finally:
            qt.QApplication.restoreOverrideCursor()
        self._status("壁の補完: " + ("ON（グレーが補った所）" if on else "OFF（CT 値だけの壁）"))

    def _onCapChanged(self, v):
        self.logic.setCapOpacity(v / 100.0)
        qt.QSettings().setValue("CardiacView/capOpacityV2", float(v))

    def _nudge(self, mm):
        frac = self.logic.nudgeCut(mm)
        if frac is not None:
            self.cutSlider.blockSignals(True); self.cutSlider.value = frac * 100; self.cutSlider.blockSignals(False)

    # ---------------------------------------------------------------- slots
    def onLoad(self):
        path = qt.QFileDialog.getOpenFileName(None, "CT を開く", "", "Volumes (*.nrrd *.nii *.nii.gz *.mha);;All (*)")
        if not path: return
        node = slicer.util.loadVolume(path)
        if node: self.volumeSelector.setCurrentNode(node)

    def onLoadDicom(self):
        d = qt.QFileDialog.getExistingDirectory(None, "DICOM フォルダ（1シリーズ）を選ぶ")
        if not d: return
        self._status("DICOM を読み込み中…"); slicer.app.processEvents()
        node = self.logic.loadDicomFolder(d)
        if node: self.volumeSelector.setCurrentNode(node); self._status(f"読み込みました: {node.GetName()}　→ ① を押してください")
        else: self._status("CT 画像が見つかりませんでした")

    def onQuick(self):
        vol = self.volumeSelector.currentNode()
        if not vol: self._status("CT を選んでください"); return
        try:
            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            specs = self._layerSpecs()
            rep = self.logic.autoPipeline(vol, specs, self.boneCheck.checked, self._status)
            self.resSpin.value = self.logic.lastSpacing
            for row in self.layerRows:                       # 自動で決めた閾値を詳細設定にも反映
                if row["name"].text == "血液・血管": row["lo"].value = int(self.logic.calib["blood_lo"])
            self.fillCheck.blockSignals(True); self.fillCheck.checked = True; self.fillCheck.blockSignals(False)
            self.logic.setCapOpacity(self.capSlider.value / 100.0)
            self.logic.updateInset()
            self.onScene(str(qt.QSettings().value("CardiacView/scene", "heart") or "heart"), remember=False)
            try:
                self.logic.setScale(self.scaleCheck.checked)
                key = next((k for k, b in self.rmodeButtons.items() if b.checked), "zoom"); self.logic.setRightMode(key)
            except Exception as e: print("scale/mode:", e)
            try:
                self.logic.tunePerformance()                 # この PC の速さに合わせて自動で軽くする
                self.ssaoCheck.blockSignals(True); self.ssaoCheck.checked = self.logic._view().renderWindow().GetRenderers().GetFirstRenderer().GetUseSSAO(); self.ssaoCheck.blockSignals(False)
            except Exception as e: print("tune:", e)
            self._status(rep)
        except Exception as e:
            import traceback; traceback.print_exc()
            self._status(f"エラー: {e}")
        finally:
            qt.QApplication.restoreOverrideCursor()

    def onBuild(self):
        self.onQuick()

    def _toSurfaces(self):
        """面の表示（色分け面・心筋の断面など）へ切り替える前に、VR と 4D を止める。
        VR が上に残ると、面の色分けも切り口も VR に隠れて「一部しか切れていない」ように見えるため"""
        L = self.logic
        try:
            if getattr(L, "on4D", False): self._end4D()
            if getattr(L, "vrOn", False): L.showVR(False)
            for b in (self.vrTissueButton, self.vrBloodButton): b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
            for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"):
                if d.GetVisibility(): d.SetVisibility(False)
            L._vrLabel()
        except Exception as e: print("toSurfaces:", e)

    # ---- パッチ（塗って色分け）・胸骨ワイヤー
    def _brushMM(self):
        for mm, b in self.brushBtns.items():
            if b.checked: return mm
        return 4.0

    def _setBrush(self, mm):
        qt.QSettings().setValue("CardiacView/brushMM", float(mm)); self.logic.paintR = float(mm)

    def _onPaint(self, on):
        L = self.logic
        if on:
            if getattr(L, "vrOn", False) or getattr(L, "on4D", False): self._toSurfaces()
            if not L._paintTargets():
                self.paintButton.blockSignals(True); self.paintButton.checked = False; self.paintButton.blockSignals(False)
                self._status("塗れる面がありません（先に 3D の面を出してください）"); return
            self._status("パッチ: 準備中…")
            L.paintStart(self._brushMM())
            cb = self.layerChecks.get("パッチ")
            if cb is not None: cb.blockSignals(True); cb.checked = True; cb.blockSignals(False)
            self._status("パッチ: 面の上を左ドラッグで塗る（Ctrl＋ドラッグで消す）。何もない所のドラッグは回転。終わりは Esc かボタン")
        else:
            self._status(L.paintEnd())

    def _onPatchFace(self):
        if self.paintButton.checked: self.paintButton.checked = False
        L = self.logic
        if not L.patchFace(): self._status("先に「パッチを塗る」で塗ってください"); return
        self.lockCheck.blockSignals(True); self.lockCheck.checked = True; self.lockCheck.blockSignals(False)
        self.cutCombo.blockSignals(True); self.cutCombo.currentIndex = 1; self.cutCombo.blockSignals(False)
        self.cutSlider.blockSignals(True); self.cutSlider.value = L.cutFrac * 100; self.cutSlider.blockSignals(False)
        self._status("パッチを正面に向けて、手前を切りました。ホイールで切る位置。「この断面で固定」を外すと元の切り方へ")

    def _onRedoMetal(self):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            msg = self.logic.redoMetal(self._status)
            cb = self.layerChecks.get("人工物・石灰化")
            if cb is not None: cb.blockSignals(True); cb.checked = True; cb.blockSignals(False)
            self._status(msg)
        except Exception as e:
            import traceback; traceback.print_exc(); self._status(f"作り直せませんでした: {e}")
        finally:
            qt.QApplication.restoreOverrideCursor()

    def _showOnly(self, names):
        for name, cb in self.layerChecks.items():
            on = name in names
            cb.blockSignals(True); cb.checked = on; cb.blockSignals(False)
            self.logic.setLayerVisible(name, on)

    def onVSD(self):
        # 心筋の切り口を塗り、内腔は空けておく（血液は出さない）
        self._toSurfaces()
        for k, b in getattr(self, "sceneButtons", {}).items(): b.setChecked(k == "heart")
        self.logic.capBlood = False; self.logic.capWall = True
        self._showOnly(("心臓壁", "心筋", "人工物・石灰化", "パッチ"))
        self.logic.setCapOpacity(self.capSlider.value / 100.0)
        self.logic.setView("A", self.fovSlider.value)
        self._applyCut()

    SCENES = {"aorta": ("血管:大動脈系", "人工物", "石灰化", "胸骨ワイヤー", "パッチ"),
              "vessels": ("血管:", "人工物", "石灰化", "胸骨ワイヤー", "パッチ"),
              "body": ("血管:", "骨", "人工物", "石灰化", "胸骨ワイヤー", "パッチ")}

    def onScene(self, key, remember=True):
        """見たいものをワンクリックで: 心臓（四腔断面）/ 大動脈 / 血管すべて / 骨と血管"""
        L = self.logic
        for k, b in self.sceneButtons.items(): b.setChecked(k == key)
        if remember: qt.QSettings().setValue("CardiacView/scene", key)
        if getattr(L, "on4D", False): self._end4D()
        if not L.layerModels: return
        if getattr(L, "vrOn", False): L.showVR(False)
        for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"): d.SetVisibility(False)   # 残っている VR も必ず消す
        for b in (self.vrTissueButton, self.vrBloodButton): b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        try: L._vrLabel()
        except Exception: pass
        if key == "heart":
            self.onFourChamber() if L._findChambers() is not None else self.onVSD()
            try: L.updateInset()
            except Exception: pass
            return
        L.capBlood = False
        if L.cutAxis == "LOCK" or self.lockCheck.checked:
            self.lockCheck.blockSignals(True); self.lockCheck.checked = False; self.lockCheck.blockSignals(False); L._lockN = None
        self.cutCombo.blockSignals(True); self.cutCombo.currentIndex = 0; self.cutCombo.blockSignals(False)
        L.setCut(None, getattr(L, "cutFrac", 0.5))                      # 切らずに全体
        want = self.SCENES[key]
        shown = []
        for k in list(L.layerModels.keys()):
            on = any(k == w or (w.endswith(":") and k.startswith(w)) for w in want)
            L.setLayerVisible(k, on)
            if on: shown.append(k)
        if key == "aorta" and "血管:大動脈系" not in L.layerModels:
            self._status("大動脈のモデルがありません（AI ラベルに大動脈がない撮影範囲です）")
        groups = {"血液・血管": any(k.startswith("血管") for k in shown), "骨": "骨" in shown, "人工物・石灰化": any(k in shown for k in ("人工物", "石灰化", "胸骨ワイヤー")), "パッチ": "パッチ" in shown}
        for name, cb in self.layerChecks.items():
            cb.blockSignals(True); cb.checked = bool(groups.get(name, False)); cb.blockSignals(False)
        L.setView("A", self.fovSlider.value)
        try: L.updateInset()
        except Exception: pass
        if key == "aorta": self._status("大動脈を表示しています。径を測るときは「大動脈サイジング」を使ってください。")

    def onFourChamber(self):
        self.onVSD()
        frac = self.logic.fourChamber()
        if frac is not None:
            self.cutCombo.blockSignals(True); self.cutCombo.currentIndex = 1; self.cutCombo.blockSignals(False)
            self.cutSlider.blockSignals(True); self.cutSlider.value = frac * 100; self.cutSlider.blockSignals(False)
        else:
            self._status("心腔モデルがないため四腔断面を計算できません")

    def onLumen(self):
        self._toSurfaces()
        self.logic.capBlood = False
        self._showOnly(("心臓壁",))
        self.logic.setView("A", self.fovSlider.value)
        self._applyCut()

    def onHeartOnly(self):
        self._toSurfaces()
        self.logic.capBlood = False
        self._showOnly(("血液・血管", "人工物・石灰化", "パッチ"))
        self.logic.setView("A", self.fovSlider.value)
        self._applyCut()

    def onAortaSizing(self):
        if hasattr(slicer.modules, "aortasizing"):                           # 新しい「大動脈サイジング」画面へ
            slicer.util.selectModule("AortaSizing"); return
        script = os.path.join(os.path.dirname(MODULE_DIR), "run_phase1.py")
        if not os.path.exists(script):
            self._status(f"run_phase1.py が見つかりません: {script}"); return
        self._status("大動脈サイジングを実行中…")
        exec(open(script, encoding="utf-8").read(), {"__name__": "__cardiacview_phase1__"})
        self._status("大動脈サイジング完了（CSV は slicer_input に出力）")

    def onSave(self):
        if getattr(self.logic, "on4D", False): self._end4D()                  # 4D 表示のまま保存すると、開いた時に面が隠れたままになる
        return self._onSave()

    def _onSave(self):
        path = qt.QFileDialog.getSaveFileName(None, "シーンを保存", "", "Medical Reality Bundle (*.mrb)")
        if path:
            if not path.lower().endswith(".mrb"): path += ".mrb"
            slicer.util.saveScene(path); self._status(f"保存: {path}")


# =============================================================================== Logic
class _Inset:
    """3D 画面の左下に「全体図」（いつも正面から）を出し、今の切断面がどこを切っているかを示す。
    枠 = 切断面（オレンジ）、黄色い線 = 心臓・血管の表面と交わる所、矢印 = 今どちらから見ているか"""
    def __init__(self, view):
        self.view = view; rw = view.renderWindow(); self.rw = rw
        old = getattr(slicer, "_cvInset", None)                              # アプリ全体で 1 つだけ
        if old is not None and old is not self:
            try: old.remove()
            except Exception: pass
        slicer._cvInset = self
        n = rw.GetNumberOfLayers(); rw.SetNumberOfLayers(n + 1)
        self.ren = vtk.vtkRenderer(); self.ren.SetLayer(n); self.ren.SetInteractive(0)
        self.ren.SetViewport(0.006, 0.01, 0.25, 0.33); self.ren.SetBackground(0.10, 0.11, 0.14); self.ren.SetPreserveColorBuffer(0)
        self.ren.SetUseDepthPeeling(0)
        rw.AddRenderer(self.ren)
        self.body = vtk.vtkActor(); self.bodyMap = vtk.vtkPolyDataMapper(); self.body.SetMapper(self.bodyMap)
        self.bodyMap.SetScalarModeToUsePointData(); self.bodyMap.SetColorModeToDirectScalars()
        p = self.body.GetProperty(); p.SetAmbient(0.35); p.SetDiffuse(0.75); p.SetSpecular(0.2)
        self.plane = vtk.vtkPlaneSource(); self.planeA = vtk.vtkActor(); m = vtk.vtkPolyDataMapper(); m.SetInputConnection(self.plane.GetOutputPort())
        self.planeA.SetMapper(m); pp = self.planeA.GetProperty(); pp.SetColor(1.0, 0.62, 0.15); pp.SetOpacity(0.18); pp.LightingOff()
        self.frame = vtk.vtkActor(); fm = vtk.vtkPolyDataMapper(); fe = vtk.vtkFeatureEdges(); fe.SetInputConnection(self.plane.GetOutputPort())
        fe.BoundaryEdgesOn(); fe.FeatureEdgesOff(); fe.ManifoldEdgesOff(); fe.NonManifoldEdgesOff(); fe.ColoringOff()
        fm.SetInputConnection(fe.GetOutputPort()); self.frame.SetMapper(fm)
        fp = self.frame.GetProperty(); fp.SetColor(1.0, 0.62, 0.15); fp.SetLineWidth(2.5); fp.LightingOff()
        self.cutLine = vtk.vtkActor(); self.cutMap = vtk.vtkPolyDataMapper(); self.cutLine.SetMapper(self.cutMap)
        cp = self.cutLine.GetProperty(); cp.SetColor(1.0, 0.95, 0.3); cp.SetLineWidth(3.0); cp.LightingOff()
        self.cutMap.SetResolveCoincidentTopologyToPolygonOffset()
        self.arrow = vtk.vtkActor(); self.arrowSrc = vtk.vtkArrowSource(); self.arrowSrc.SetTipResolution(16); self.arrowSrc.SetShaftResolution(12)
        self.arrowTf = vtk.vtkTransform(); af = vtk.vtkTransformPolyDataFilter(); af.SetInputConnection(self.arrowSrc.GetOutputPort()); af.SetTransform(self.arrowTf)
        am = vtk.vtkPolyDataMapper(); am.SetInputConnection(af.GetOutputPort()); self.arrow.SetMapper(am); self.arrow.GetProperty().SetColor(0.35, 0.85, 1.0)
        self.txt = []
        for s, pos in (("R", (6, 0)), ("L", (-14, 0))):
            t = vtk.vtkTextActor(); t.SetInput(s); tp = t.GetTextProperty(); tp.SetFontSize(13); tp.SetBold(True); tp.SetColor(0.75, 0.78, 0.84)
            t.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport(); t.SetPosition(0.04 if s == "R" else 0.90, 0.88)
            self.ren.AddActor2D(t); self.txt.append(t)
        for a in (self.body, self.planeA, self.frame, self.cutLine, self.arrow): self.ren.AddActor(a)
        self.planeA.SetVisibility(False); self.frame.SetVisibility(False); self.cutLine.SetVisibility(False); self.arrow.SetVisibility(False)
        self.pd = None; self.center = np.zeros(3); self.R = 100.0
        self._camTag = None

    def remove(self):
        try: self.rw.RemoveRenderer(self.ren)
        except Exception: pass
        if self._camTag is not None:
            try: self._camObj.RemoveObserver(self._camTag)
            except Exception: pass

    def setVisible(self, on):
        self.ren.SetDraw(1 if on else 0); self.view.scheduleRender()

    def setModels(self, nodes):
        app = vtk.vtkAppendPolyData(); k = 0
        for n in nodes:
            pd = n.GetPolyData(); d = n.GetDisplayNode()
            if pd is None or pd.GetNumberOfPoints() == 0 or d is None: continue
            g = vtk.vtkPolyData(); g.SetPoints(pd.GetPoints()); g.SetPolys(pd.GetPolys())     # 形だけ（色・法線の配列を外すと 10 倍速い）
            dec = vtk.vtkQuadricClustering(); dec.SetInputData(g)                    # 格子でまとめる間引き（小さな全体図には十分）
            dec.SetNumberOfDivisions(48, 48, 48); dec.AutoAdjustNumberOfDivisionsOff(); dec.Update()
            q = vtk.vtkPolyData(); q.ShallowCopy(dec.GetOutput())
            col = vtk.vtkUnsignedCharArray(); col.SetNumberOfComponents(3); col.SetName("rgb")
            c = [int(255 * x) for x in d.GetColor()]
            col.SetNumberOfTuples(q.GetNumberOfPoints())
            for i in range(3): col.FillComponent(i, c[i])
            q.GetPointData().SetScalars(col); app.AddInputData(q); k += 1
        if k == 0: return
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(app.GetOutputPort()); nm.SplittingOff(); nm.Update()
        self.pd = vtk.vtkPolyData(); self.pd.DeepCopy(nm.GetOutput()); self.bodyMap.SetInputData(self.pd)
        b = self.pd.GetBounds(); lo = np.array(b[0::2]); hi = np.array(b[1::2])
        self.center = (lo + hi) / 2; self.R = float(np.linalg.norm(hi - lo) / 2)
        cam = self.ren.GetActiveCamera(); cam.ParallelProjectionOn()
        cam.SetFocalPoint(*self.center); cam.SetPosition(*(self.center + np.array([0, 1.0, 0]) * self.R * 4)); cam.SetViewUp(0, 0, 1)
        self.half = (hi - lo) / 2.0
        vp = self.ren.GetViewport(); asp = 1.35                                    # 全体図の縦横比（だいたい）
        cam.SetParallelScale(float(max(self.half[2], self.half[0] / asp)) * 1.18); self.ren.ResetCameraClippingRange()
        self.view.scheduleRender()

    def setPlane(self, c, n):
        if self.pd is None: return
        n = np.array(n, float); n /= np.linalg.norm(n) + 1e-12; c = np.array(c, float)
        c = c - n * float((c - self.center) @ n) + n * float((c - self.center) @ n)     # 面上の点
        cc = self.center + n * float((c - self.center) @ n)                          # 体の中心に一番近い面上の点
        u = np.cross(n, [0, 0, 1.0]);
        if np.linalg.norm(u) < 1e-3: u = np.cross(n, [0, 1.0, 0])
        u /= np.linalg.norm(u); v = np.cross(n, u); h = float(np.max(self.half)) * 1.05
        self.plane.SetOrigin(*(cc - h * u - h * v)); self.plane.SetPoint1(*(cc + h * u - h * v)); self.plane.SetPoint2(*(cc - h * u + h * v)); self.plane.Update()
        pl = vtk.vtkPlane(); pl.SetOrigin(*cc); pl.SetNormal(*n)
        cut = vtk.vtkCutter(); cut.SetInputData(self.pd); cut.SetCutFunction(pl); cut.Update()
        self.cutMap.SetInputData(cut.GetOutput()); self.cutMap.ScalarVisibilityOff()
        for a in (self.planeA, self.frame, self.cutLine): a.SetVisibility(True)
        self.view.scheduleRender()

    def hidePlane(self):
        for a in (self.planeA, self.frame, self.cutLine): a.SetVisibility(False)
        self.view.scheduleRender()

    def setViewDir(self, dop):
        """今の 3D 画面の視線の向き（カメラ → 焦点）を矢印で示す（全体図の外から中心へ）"""
        if self.pd is None: return
        d = np.array(dop, float); d /= np.linalg.norm(d) + 1e-12
        start = self.center - d * float(np.max(self.half)) * 1.05; L = float(np.max(self.half)) * 0.42
        x = d; y = np.cross(x, [0, 0, 1.0])
        if np.linalg.norm(y) < 1e-3: y = np.cross(x, [0, 1.0, 0])
        y /= np.linalg.norm(y); z = np.cross(x, y)
        m = vtk.vtkMatrix4x4()
        for r in range(3):
            m.SetElement(r, 0, x[r] * L); m.SetElement(r, 1, y[r] * L); m.SetElement(r, 2, z[r] * L); m.SetElement(r, 3, start[r])
        self.arrowTf.SetMatrix(m); self.arrow.SetVisibility(True); self.view.scheduleRender()

    def followCamera(self, camNode):
        cam = camNode.GetCamera(); self._camObj = cam
        if self._camTag is not None:
            try: cam.RemoveObserver(self._camTag)
            except Exception: pass
        def upd(c=None, e=None):
            fp = np.array(cam.GetFocalPoint()); pos = np.array(cam.GetPosition()); self.setViewDir(fp - pos)
        self._camTag = cam.AddObserver(vtk.vtkCommand.ModifiedEvent, upd); upd()


class _MprMark:
    """4 画面の 3D に「3 断面が交わる点」の十字マーク（いつも手前に表示＝体の中でも見える）。アプリ全体で 1 つ"""
    COLS = {"Red": (0.95, 0.30, 0.20), "Yellow": (0.93, 0.84, 0.30), "Green": (0.43, 0.69, 0.29)}

    def __init__(self, view):
        old = getattr(slicer, "_cvMprMark", None)
        if old is not None:
            try: old.remove()
            except Exception: pass
        slicer._cvMprMark = self
        self.view = view; rw = view.renderWindow(); self.rw = rw
        main = rw.GetRenderers().GetFirstRenderer()
        n = rw.GetNumberOfLayers(); rw.SetNumberOfLayers(n + 1)
        self.ren = vtk.vtkRenderer(); self.ren.SetLayer(n); self.ren.SetInteractive(0); self.ren.SetActiveCamera(main.GetActiveCamera())
        rw.AddRenderer(self.ren)
        self.lines = {}
        for nm, col in self.COLS.items():
            src = vtk.vtkLineSource(); a = vtk.vtkActor(); m = vtk.vtkPolyDataMapper(); m.SetInputConnection(src.GetOutputPort()); a.SetMapper(m)
            pr = a.GetProperty(); pr.SetColor(*col); pr.SetLineWidth(5.0); pr.LightingOff(); pr.SetOpacity(1.0)
            self.ren.AddActor(a); self.lines[nm] = (src, a)
        self.ball = vtk.vtkSphereSource(); self.ball.SetThetaResolution(20); self.ball.SetPhiResolution(14)
        ba = vtk.vtkActor(); bm = vtk.vtkPolyDataMapper(); bm.SetInputConnection(self.ball.GetOutputPort()); ba.SetMapper(bm)
        ba.GetProperty().SetColor(1, 1, 1); ba.GetProperty().SetAmbient(0.6); self.ren.AddActor(ba); self.ballA = ba
        self.tags = []; self.on = False

    def remove(self):
        for o, t in self.tags:
            try: o.RemoveObserver(t)
            except Exception: pass
        self.tags = []
        try: self.rw.RemoveRenderer(self.ren)
        except Exception: pass

    def show(self, on):
        self.on = bool(on); self.ren.SetDraw(1 if on else 0)
        lm = slicer.app.layoutManager()
        if on and not self.tags:
            for nm in self.COLS:
                w = lm.sliceWidget(nm)
                if w is None: continue
                sn = w.mrmlSliceNode(); self.tags.append((sn, sn.AddObserver(vtk.vtkCommand.ModifiedEvent, lambda c, e: self.update())))
        if on: self.update()
        self.view.scheduleRender()

    def update(self):
        if not self.on: return
        lm = slicer.app.layoutManager(); N = {}; d = []
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            if w is None: return
            M = slicer.util.arrayFromVTKMatrix(w.mrmlSliceNode().GetSliceToRAS())
            n = M[:3, 2] / (np.linalg.norm(M[:3, 2]) + 1e-12); N[nm] = n; d.append(float(n @ M[:3, 3]))
        try: c = np.linalg.solve(np.array([N["Red"], N["Yellow"], N["Green"]]), np.array(d))
        except Exception: return
        Lg = _cvCur(); vb = Lg._visibleBounds() if Lg is not None and hasattr(Lg, "_visibleBounds") else None
        L = float(np.linalg.norm(np.array(vb[1]) - np.array(vb[0]))) * 0.10 if vb is not None else 25.0   # 体の大きさの 1 割
        L = float(np.clip(L, 15.0, 45.0))
        for nm in self.COLS:                                     # その断面に垂直な線（＝ほかの 2 断面が交わる線）をその断面の色で
            o = [k for k in self.COLS if k != nm]
            u = np.cross(N[o[0]], N[o[1]]); nu = np.linalg.norm(u)
            if nu < 1e-6: continue
            u /= nu; src, a = self.lines[nm]
            src.SetPoint1(*(c - u * L)); src.SetPoint2(*(c + u * L))
        self.ball.SetCenter(*c); self.ball.SetRadius(max(2.5, L * 0.12))
        self.view.scheduleRender()


def _cvCur():
    """今の画面（CardiacView のパネル）が使っているロジック。マウス操作は必ずここへ届ける（古い症例のロジックに横取りされない）"""
    try: return slicer.modules.cardiacview.widgetRepresentation().self().logic
    except Exception: return None


class CardiacViewLogic(ScriptedLoadableModuleLogic):

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.layerModels = {}
        self.planes = []          # 自由平面
        self.cutPlane = None      # スライダー駆動の平面
        self.clip = None
        self.cutAxis = None
        self.cutFrac = 0.5
        self._viewObsTag = None
        self.cutSign = 1.0
        self.flying = False
        self.workVolume = None
        self.folderItem = None
        self.bounds = None
        self.visible = {}

    # ---------------------------------------------------------------- scene helpers
    def _folder(self):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        if self.folderItem is None or not sh.GetItemName(self.folderItem):
            self.folderItem = sh.CreateFolderItem(sh.GetSceneItemID(), "CardiacView")
        return self.folderItem

    def _put(self, node):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        sh.SetItemParent(sh.GetItemByDataNode(node), self._folder())

    def _view(self):
        return slicer.app.layoutManager().threeDWidget(0).threeDView()

    def _viewNode(self):
        return self._view().mrmlViewNode()

    def _camera(self):
        return slicer.modules.cameras.logic().GetViewActiveCameraNode(self._viewNode())

    # ---------------------------------------------------------------- layers
    def buildLayers(self, vol, specs, spacing, boneLayer, status=lambda m: None):
        t0 = time.time()
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
        for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"): d.SetVisibility(False)
        for s in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            if s.GetDisplayNode(): s.GetDisplayNode().SetVisibility(False)

        status("再サンプリング中…")
        work = self._resample(vol, spacing); self.workVolume = work
        segNode = self._findSegmentation()
        boneMask = None
        if boneLayer and segNode:
            status("骨ラベルを取得中…"); boneMask = self._boneMaskArray(segNode, work)

        self.removeFreePlanes(); self._clearCuts()
        for n in list(self.layerModels.values()):
            if n: slicer.mrmlScene.RemoveNode(n)
        self.layerModels.clear()
        self._strokes = []; self._pMask = {}; self._pMaskKey = {}

        arr = slicer.util.arrayFromVolume(work)
        status("体の範囲を抽出中…")
        body = self._bodyMask(arr)
        for sp in specs:
            status(f"レイヤー「{sp['name']}」を生成中…")
            binary = ((arr >= sp["lo"]) & (arr <= sp["hi"])).astype(np.uint8)
            if boneMask is not None: binary[boneMask] = 0
            if body is not None: binary[~body] = 0
            binary = self._cleanBinary(binary, spacing)
            if sp["name"] == "血液・血管" and segNode is not None:
                try:
                    from scipy import ndimage
                    # 骨の縁を広めに除外
                    if boneMask is not None:
                        binary[ndimage.binary_dilation(boneMask, iterations=2)] = 0
                    # ラベル付き血管につながる成分だけ残す（骨片・ノイズ除去）
                    allv = self._segmentMaskArray(segNode, work, tuple(k for _, keys, _ in VESSEL_GROUPS for k in keys))
                    if allv is not None:
                        lab, nlab = ndimage.label(binary, structure=np.ones((3, 3, 3)))
                        hit = np.unique(lab[allv & (binary > 0)])
                        keep = np.zeros(nlab + 1, bool); keep[hit] = True; keep[0] = False
                        before = int(binary.sum()); binary = keep[lab].astype(np.uint8)
                        status(f"  血管につながらない塊を除去: {before - int(binary.sum())} ボクセル")
                except Exception as e:
                    print("vessel cleanup:", e)
                # ラベルで色分けした複数モデルに分ける。ラベルの外側 2.5mm 以内の血液（ラベルより少し太い造影部分）は
                # 一番近いラベルの仲間にする（別の薄い殻にすると大動脈の表面とちらついて縞模様になる）
                from scipy import ndimage
                gmask = {}; labmap = np.zeros(binary.shape, np.int8)
                for gi, (gname, keys, col) in enumerate(VESSEL_GROUPS, start=1):
                    mk = self._segmentMaskArray(segNode, work, keys)
                    if mk is None: continue
                    gmask[gname] = mk; labmap[(labmap == 0) & mk] = gi
                if (labmap > 0).any():
                    dist, ind = ndimage.distance_transform_edt(labmap == 0, return_indices=True)
                    near = labmap[tuple(ind)]
                    rim = (binary > 0) & (labmap == 0) & (dist * spacing <= 2.5)
                    for gi, (gname, keys, col) in enumerate(VESSEL_GROUPS, start=1):
                        if gname in gmask: gmask[gname] = gmask[gname] | (rim & (near == gi))
                    del dist, ind, near
                remaining = binary.copy()
                for gname, keys, col in VESSEL_GROUPS:
                    mask = gmask.get(gname)
                    if mask is None: continue
                    part = (remaining > 0) & mask
                    if part.sum() < 50: continue
                    model = self._surfaceFromBinary(part.astype(np.uint8), work, gname, col, sp["smooth"])
                    model.GetDisplayNode().SetVisibility(sp["visible"]); self.layerModels[gname] = model; self.visible[gname] = sp["visible"]
                    remaining[part] = 0
                    status(f"  {gname} 完了")
                if remaining.sum() > 50:
                    gname, col = VESSEL_OTHER
                    model = self._surfaceFromBinary(remaining, work, gname, col, sp["smooth"])
                    model.GetDisplayNode().SetVisibility(sp["visible"]); self.layerModels[gname] = model; self.visible[gname] = sp["visible"]
                continue
            model = self._surfaceFromBinary(binary, work, sp["name"], sp["color"], sp["smooth"])
            model.GetDisplayNode().SetVisibility(sp["visible"]); self.layerModels[sp["name"]] = model; self.visible[sp["name"]] = sp["visible"]
            if sp["name"] == "軟部組織":
                # 他の組織を覆い隠さないよう半透明・控えめな色に
                d = model.GetDisplayNode(); d.SetOpacity(0.18); d.SetColor(0.80, 0.72, 0.66); d.SetSpecular(0.05)
        if boneMask is not None:
            status("レイヤー「骨」・胸骨ワイヤーを生成中…")
            self._buildBone(arr, work, spacing, segNode, boneMask, body)
        if segNode is not None:
            try:
                status("人工物（人工弁・ステントなど）と石灰化を探しています…")
                self.buildImplantsCalc(arr, work, spacing, segNode, boneMask)
            except Exception as e:
                import traceback; traceback.print_exc(); print("implants/calc:", e)
        if segNode is not None:
            try:
                status("レイヤー「心臓壁」を生成中…")
                self.visible["心臓壁"] = False
                self.rebuildWall()
                status("レイヤー「心筋」を生成中…")
                self.buildMyocardium()
            except Exception as e:
                import traceback; traceback.print_exc()
                print("wall layer:", e)
        self._updateBounds()
        self.studioLighting(0, ssao=True)   # 環境光遮蔽で奥行きを出す（GPU 負荷は小さい）
        self.setView("A", 30)
        status(f"完了（{time.time()-t0:.0f} 秒）")

    # ================================================================ 人工物・石灰化
    METAL_HU = 2000.0

    @staticmethod
    def _bbox(m, mg=0):
        r = [np.nonzero(m.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
        return tuple(slice(max(0, int(q.min()) - mg), min(m.shape[i], int(q.max()) + 1 + mg)) for i, q in enumerate(r))

    @staticmethod
    def _boxVol(src, oi, oj, ok):
        """元の CT の一部（箱）の位置を持った「面を作るための入れ物」"""
        S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S); I = vtk.vtkMatrix4x4(); I.DeepCopy(S)
        for r in range(3): I.SetElement(r, 3, S.GetElement(r, 3) + S.GetElement(r, 0) * oi + S.GetElement(r, 1) * oj + S.GetElement(r, 2) * ok)
        class _Box:
            def GetIJKToRASMatrix(self, m): m.DeepCopy(I)
            def GetRASToIJKMatrix(self, m): m.DeepCopy(I); m.Invert()
        return _Box()

    def _srcSub(self, work, nearW):
        """作業画像のマスク nearW のまわりを、元の CT（細かい画素）から切り出す。細い金属は作業画像だと消えるため。
        返り値: (元 CT, 切り出した CT, その中の nearW, 箱の位置 (i0, j0, k0), 拡大率, ずれ) / None"""
        if nearW is None or not nearW.any(): return None
        src = getattr(self, "sourceVolume", None) or work
        sarr = slicer.util.arrayFromVolume(src)
        W = vtk.vtkMatrix4x4(); work.GetRASToIJKMatrix(W); S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S)
        Mw = np.array([[W.GetElement(r, c) for c in range(4)] for r in range(4)]); Ms = np.array([[S.GetElement(r, c) for c in range(4)] for r in range(4)])
        M = Mw @ Ms
        if np.abs(M[:3, :3] - np.diag(np.diag(M[:3, :3]))).max() > 1e-3:
            src, sarr, M = work, slicer.util.arrayFromVolume(work), np.eye(4)
        sh = nearW.shape
        zz, yy, xx = np.nonzero(nearW.any(axis=(1, 2)))[0], np.nonzero(nearW.any(axis=(0, 2)))[0], np.nonzero(nearW.any(axis=(0, 1)))[0]
        lo_w = np.array([xx.min(), yy.min(), zz.min()]) - 1; hi_w = np.array([xx.max(), yy.max(), zz.max()]) + 1
        sc = np.diag(M[:3, :3]); off = M[:3, 3]
        b1 = (lo_w - off) / sc; b2 = (hi_w - off) / sc
        lo_s = np.maximum(np.floor(np.minimum(b1, b2)).astype(int), 0); hi_s = np.minimum(np.ceil(np.maximum(b1, b2)).astype(int) + 1, np.array(sarr.shape[::-1]))
        i0, j0, k0 = (int(v) for v in lo_s); i1, j1, k1 = (int(v) for v in hi_s)
        if i1 <= i0 or j1 <= j0 or k1 <= k0: return None
        sub = sarr[k0:k1, j0:j1, i0:i1]
        ix = np.clip(np.rint(sc[0] * np.arange(i0, i1) + off[0]).astype(int), 0, sh[2] - 1)
        jy = np.clip(np.rint(sc[1] * np.arange(j0, j1) + off[1]).astype(int), 0, sh[1] - 1)
        kz = np.clip(np.rint(sc[2] * np.arange(k0, k1) + off[2]).astype(int), 0, sh[0] - 1)
        nearS = nearW[kz[:, None, None], jy[None, :, None], ix[None, None, :]]
        return src, sub, nearS, (i0, j0, k0), sc, off

    def findWires(self, work, segNode):
        """胸骨のまわり（AI の胸骨ラベル + 8 mm）で 2000 HU 以上 = 胸骨ワイヤー。細いので元の CT（細かい画素）で探す。
        返り値 dict(mask=元 CT の箱の中のワイヤー, at=箱の位置, src=元 CT, workMask=作業画像で 2.5 mm 太らせたワイヤー（骨から抜く）, n=かたまりの数, mm3=体積) / None"""
        from scipy import ndimage
        if segNode is None: return None
        st = self._segmentMaskArray(segNode, work, ("sternum",))
        if st is None or not st.any(): return None
        sp = np.array(work.GetSpacing(), float)[::-1]                        # (z, y, x)
        box = self._bbox(st, int(np.ceil(10.0 / sp.min())))
        nearW = np.zeros(st.shape, bool)
        nearW[box] = ndimage.distance_transform_edt(~st[box], sampling=sp) <= 8.0
        cut = self._srcSub(work, nearW)
        if cut is None: return None
        src, sub, nearS, (i0, j0, k0), sc, off = cut
        wire = (sub >= self.METAL_HU) & nearS
        if not wire.any(): return None
        vox = float(np.prod(src.GetSpacing()))
        lab, n = ndimage.label(wire, structure=np.ones((3, 3, 3)))
        sizes = np.bincount(lab.ravel(), minlength=n + 1) * vox
        keep = sizes >= 2.0; keep[0] = False
        wire = keep[lab]
        if not wire.any(): return None
        kk, jj, ii = np.nonzero(wire); sh = nearW.shape
        ix = np.clip(np.rint(sc[0] * (ii + i0) + off[0]).astype(int), 0, sh[2] - 1)
        jy = np.clip(np.rint(sc[1] * (jj + j0) + off[1]).astype(int), 0, sh[1] - 1)
        kz = np.clip(np.rint(sc[2] * (kk + k0) + off[2]).astype(int), 0, sh[0] - 1)
        wW = np.zeros(sh, bool); wW[kz, jy, ix] = True
        b2 = self._bbox(wW, int(np.ceil(3.5 / sp.min())) + 1)
        wW[b2] = ndimage.binary_dilation(wW[b2], iterations=max(1, int(round(2.5 / sp.min()))))   # ワイヤーのにじみ（金属のまわりの明るい所）も骨にしない
        return dict(mask=wire, at=(i0, j0, k0), src=src, workMask=wW, n=int(keep.sum()), mm3=round(float(wire.sum() * vox)))

    def _buildBone(self, arr, work, spacing, segNode, boneMask, body):
        """骨の面。胸骨ワイヤー（金属）は骨から抜いて、別の色（銅色）の面にする（骨の中に埋もれて見えなくなるため）"""
        from scipy import ndimage
        # AI の骨ラベルは 3mm 格子でカクカク → 形は CT 値（≥200HU）で取り、ラベルは「どこが骨か」の目印にだけ使う
        near = ndimage.distance_transform_edt(~boneMask, sampling=spacing) <= 3.0
        bm = (arr >= 200) & near
        if body is not None: bm &= body
        if segNode is not None:
            vv = self._segmentMaskArray(segNode, work, ("aorta", "vena cava", "pulmonary", "heart", "atrial appendage", "brachiocephalic", "subclavian", "carotid", "iliac", "kidney"))
            if vv is not None: bm &= ~ndimage.binary_dilation(vv, iterations=1)
        wires = None
        try: wires = self.findWires(work, segNode)
        except Exception as e:
            import traceback; traceback.print_exc(); print("wires:", e)
        if wires is not None: bm &= ~wires["workMask"]
        bm = ndimage.binary_closing(bm, iterations=1)
        bm = self._cleanBinary(bm.astype(np.uint8), spacing, minVox=150)
        self.layerModels["骨"] = self._surfaceFromBinary(bm, work, "骨", BONE_COLOR, 2); self.visible["骨"] = True
        old = slicer.mrmlScene.GetFirstNodeByName("CV 胸骨ワイヤー")
        if old: slicer.mrmlScene.RemoveNode(old)
        self.layerModels.pop("胸骨ワイヤー", None); self.wireStats = dict(n=0, mm3=0)
        if wires is not None:
            m = wires["mask"]; sl = self._bbox(m, 4); i0, j0, k0 = wires["at"]
            if max(wires["src"].GetSpacing()) > 1.25:                             # 厚いスライス（2〜5mm）では細い線が面にならず消える → 1 画素ふくらませる
                m = m.copy(); m[sl] = ndimage.binary_dilation(m[sl], iterations=1)
            model = self._surfaceFromBinary(np.ascontiguousarray(m[sl]).astype(np.uint8), self._boxVol(wires["src"], i0 + sl[2].start, j0 + sl[1].start, k0 + sl[0].start),
                                            "胸骨ワイヤー", WIRE_COLOR, 1, keepSmall=True)
            d = model.GetDisplayNode(); d.SetSpecular(0.9); d.SetPower(70); d.SetAmbient(0.25)
            self.layerModels["胸骨ワイヤー"] = model; self.visible["胸骨ワイヤー"] = True
            self.wireStats = dict(n=wires["n"], mm3=wires["mm3"])
        print("胸骨ワイヤー:", self.wireStats)

    def redoMetal(self, status=lambda m: None):
        """前に作った症例で、骨・胸骨ワイヤー・人工物・石灰化だけ作り直す（保存してある AI ラベルを使う）"""
        work = getattr(self, "workVolume", None); segNode = self._findSegmentation()
        if work is None or work.GetImageData() is None or segNode is None:
            raise RuntimeError("AI のラベルか作業用の画像がありません。「3D を自動で作る」からやり直してください")
        arr = slicer.util.arrayFromVolume(work); spacing = float(min(work.GetSpacing()))
        boneVis = bool(self.visible.get("骨", False))
        status("骨のラベルを取得中…"); boneMask = self._boneMaskArray(segNode, work)
        if boneMask is not None:
            status("骨・胸骨ワイヤーを作り直しています…"); slicer.app.processEvents()
            self._buildBone(arr, work, spacing, segNode, boneMask, self._bodyMask(arr))
        status("人工物・石灰化を探しています…"); slicer.app.processEvents()
        self.buildImplantsCalc(arr, work, spacing, segNode, boneMask)
        for k in ("骨", "胸骨ワイヤー", "人工物", "石灰化"):
            n = self.layerModels.get(k)
            if n is None or n.GetDisplayNode() is None: continue
            on = boneVis if k == "骨" else True
            self.visible[k] = on; n.GetDisplayNode().SetVisibility(on)
        self._updateBounds()
        if self.cutAxis is not None: self._applyClipToModels(True)
        try: self.updateInset()
        except Exception: pass
        w = getattr(self, "wireStats", None) or {}; s = getattr(self, "implantStats", None) or {}
        return (f"作り直しました: 胸骨ワイヤー {w.get('n', 0)} 個（銅色）・人工物 {s.get('metal_n', 0)} 個（銀）・石灰化 {s.get('calc_n', 0)} 個（黄白）"
                + ("" if w.get("n") else "。胸骨ワイヤーは見つかりませんでした"))

    def buildImplantsCalc(self, arr, work, spacing, segNode, boneMask=None):
        """心臓・大血管のまわりで、金属（人工弁のリング・ステント・クリップ・ワイヤー）と石灰化を CT 値から見つけて、別の色の面にする。
        - 金属: 2000 HU 以上
        - 石灰化: その症例の造影血液より 250 HU 以上高い所（最低 650 HU）。金属のまわりのにじみは除く
        - 骨（胸骨のワイヤーを含む）と、造影剤が濃いまま流れ込む静脈（上大静脈・腕頭静脈・鎖骨下静脈）の中は除く
        パッチや人工血管（布・ePTFE）は CT 値では見分けられないので対象外（将来 AI で）"""
        from scipy import ndimage
        c = self._cal(); blood = float(c.get("blood") or (c.get("blood_lo", 180) + 150))
        calcT = max(650.0, blood + 250.0)
        vv = self._segmentMaskArray(segNode, work, ("heart", "aorta", "pulmonary", "atrial appendage", "brachiocephalic trunk", "subclavian artery",
                                                    "common carotid", "iliac artery", "coronary", "vena cava"))
        if vv is None or not vv.any(): return
        near = ndimage.distance_transform_edt(~vv, sampling=spacing) <= 6.0
        if boneMask is not None and boneMask.any():
            near &= ~(ndimage.distance_transform_edt(~boneMask, sampling=spacing) <= 2.0)
        try:                                                                 # 心腔・大血管の内側（縁から 2 mm より内）は造影剤のむら（右心系への流入など）なので石灰化にしない
            hc = self._findChambers()
            inner = self._segmentMaskArray(hc, work, ("ventricle", "atrium", "pulmonary artery")) if hc is not None else None
            v2 = self._segmentMaskArray(segNode, work, ("vena cava", "atrium"))
            inner = v2 if inner is None else (inner if v2 is None else inner | v2)
            if inner is not None and inner.any():
                near &= ~ndimage.binary_erosion(inner, iterations=max(1, int(round(2.0 / float(np.min(spacing) if np.ndim(spacing) else spacing)))))
        except Exception as e: print("calc inner:", e)
        veins = self._segmentMaskArray(segNode, work, ("superior vena cava", "brachiocephalic vein", "subclavian vein", "jugular vein"))
        if veins is not None and veins.any(): near &= ~ndimage.binary_dilation(veins, iterations=1)
        # 作業用画像（0.8mm・ぼかし済み）では小さな石灰化や細いワイヤーが消えるので、元の CT（0.3〜0.5mm）で探す
        src = getattr(self, "sourceVolume", None) or work
        sarr = slicer.util.arrayFromVolume(src)
        W = vtk.vtkMatrix4x4(); work.GetRASToIJKMatrix(W); S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S)
        Mw = np.array([[W.GetElement(r, c) for c in range(4)] for r in range(4)]); Ms = np.array([[S.GetElement(r, c) for c in range(4)] for r in range(4)])
        M = Mw @ Ms                                              # 元CT の IJK → 作業画像の IJK
        sh = near.shape                                         # (z, y, x)
        if np.abs(M[:3, :3] - np.diag(np.diag(M[:3, :3]))).max() > 1e-3:
            src, sarr, M = work, arr, np.eye(4)                  # 向きが違う時は作業画像で（まれ）
        # 心臓・血管の近く（作業画像の箱）だけ元CTから切り出す
        zz, yy, xx = np.nonzero(near.any(axis=(1, 2)))[0], np.nonzero(near.any(axis=(0, 2)))[0], np.nonzero(near.any(axis=(0, 1)))[0]
        lo_w = np.array([xx.min(), yy.min(), zz.min()]) - 1; hi_w = np.array([xx.max(), yy.max(), zz.max()]) + 1
        sc = np.diag(M[:3, :3]); off = M[:3, 3]
        b1 = (lo_w - off) / sc; b2 = (hi_w - off) / sc
        lo_s = np.maximum(np.floor(np.minimum(b1, b2)).astype(int), 0); hi_s = np.minimum(np.ceil(np.maximum(b1, b2)).astype(int) + 1, np.array(sarr.shape[::-1]))
        i0, j0, k0 = lo_s; i1, j1, k1 = hi_s
        sub = sarr[k0:k1, j0:j1, i0:i1]
        ix = np.clip(np.rint(sc[0] * np.arange(i0, i1) + off[0]).astype(int), 0, sh[2] - 1)
        jy = np.clip(np.rint(sc[1] * np.arange(j0, j1) + off[1]).astype(int), 0, sh[1] - 1)
        kz = np.clip(np.rint(sc[2] * np.arange(k0, k1) + off[2]).astype(int), 0, sh[0] - 1)
        nearS = near[kz[:, None, None], jy[None, :, None], ix[None, None, :]]
        metal = (sub >= self.METAL_HU) & nearS
        calc = (sub >= calcT) & (sub < self.METAL_HU) & nearS
        del nearS
        if metal.any() and calc.any():                           # 金属（ステントの線など）につながっている「石灰化」は、厚いスライスでぼけた金属 → 人工物にまとめる
            lc, nc = ndimage.label(calc, structure=np.ones((3, 3, 3)))
            touch = np.unique(lc[ndimage.binary_dilation(metal, iterations=2) & calc]); touch = touch[touch > 0]
            if len(touch):
                mv = np.isin(lc, touch); metal |= mv; calc &= ~mv
            del lc
        if metal.any():                                          # 金属のにじみ（ハレーション）は石灰化にしない（金属のまわりの箱だけで計算＝速い）
            for sl in ndimage.find_objects(ndimage.label(metal)[0]):
                sl = tuple(slice(max(0, q.start - 4), q.stop + 4) for q in sl)
                calc[sl] &= ~ndimage.binary_dilation(metal[sl], iterations=3)
        vox = float(np.prod(src.GetSpacing()))
        def bbox(m, mg=0):
            r = [np.nonzero(m.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
            return tuple(slice(max(0, q.min() - mg), min(m.shape[i], q.max() + 1 + mg)) for i, q in enumerate(r))
        def clean(m, min_mm3):
            sl = bbox(m); sm = m[sl]                              # 候補のある範囲だけで数える（速い）
            lab, n = ndimage.label(sm, structure=np.ones((3, 3, 3)))
            sizes = np.bincount(lab.ravel(), minlength=n + 1) * vox
            keep = sizes >= min_mm3; keep[0] = False
            out = np.zeros_like(m); out[sl] = keep[lab]
            return out, int(keep.sum())
        metal, nM = clean(metal, 3.0) if metal.any() else (metal, 0)
        calc, nC = clean(calc, 2.0) if calc.any() else (calc, 0)
        self.implantStats = dict(metal_mm3=round(float(metal.sum() * vox)), metal_n=nM, calc_mm3=round(float(calc.sum() * vox)), calc_n=nC, calcT=round(calcT))
        # 切り出した箱の位置を持った「面を作るための入れ物」（見つかった所のまわりだけで面を作る＝速い）
        def boxAt(oi, oj, ok):
            I = vtk.vtkMatrix4x4(); I.DeepCopy(S)
            for r in range(3): I.SetElement(r, 3, S.GetElement(r, 3) + S.GetElement(r, 0) * oi + S.GetElement(r, 1) * oj + S.GetElement(r, 2) * ok)
            class _Box:
                def GetIJKToRASMatrix(self, m): m.DeepCopy(I)
                def GetRASToIJKMatrix(self, m): m.DeepCopy(I); m.Invert()
            return _Box()
        for name, m, col in (("人工物", metal, IMPLANT_COLOR), ("石灰化", calc, CALC_COLOR)):
            old = slicer.mrmlScene.GetFirstNodeByName(f"CV {name}")
            if old: slicer.mrmlScene.RemoveNode(old)
            self.layerModels.pop(name, None)
            if not m.any(): continue
            sl = bbox(m, 4)
            model = self._surfaceFromBinary(np.ascontiguousarray(m[sl]).astype(np.uint8), boxAt(i0 + sl[2].start, j0 + sl[1].start, k0 + sl[0].start),
                                            name, col, 1, keepSmall=True)
            d = model.GetDisplayNode()
            if name == "人工物": d.SetSpecular(0.9); d.SetPower(70); d.SetAmbient(0.25)          # 金属らしく光らせる
            else: d.SetSpecular(0.5); d.SetPower(30); d.SetAmbient(0.3)
            self.layerModels[name] = model; self.visible[name] = True
        print("人工物・石灰化:", self.implantStats)

    # ================================================================ 全自動（他の画像でも同じ手順で）
    DEFAULT_CAL = dict(wall_lo=-20.0, wall_hi=175.0, blood_lo=180.0, blood_hi=900.0)

    def _cal(self):
        c = dict(self.DEFAULT_CAL); c.update(getattr(self, "calib", {}) or {}); return c

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

    def _runTS(self, vol, kind, status):
        import TotalSegmentator
        tsl = TotalSegmentator.TotalSegmentatorLogic()
        tsl.logCallback = lambda t: slicer.app.processEvents()      # AI 計算中も画面（進捗表示）を止めない
        try:
            import torch, totalsegmentator                           # noqa: F401  新しく入れた PC では初回だけ AI の部品を入れる
        except Exception:
            status("初回だけ AI の部品（PyTorch・TotalSegmentator）を入れています。数分〜十数分かかります…"); slicer.app.processEvents()
            tsl.setupPythonRequirements()
        seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"{vol.GetName()} {kind}")
        seg.SetReferenceImageGeometryParameterFromVolumeNode(vol)
        try:
            if kind == "total":
                tsl.process(vol, seg, quality="fast", task="total")
            else:
                tsl.process(vol, seg, task="heartchambers_highres")
        except Exception:
            slicer.mrmlScene.RemoveNode(seg); raise
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
        t0 = time.time()
        self.sourceVolume = vol; self.calib = {}
        if self._segFor(vol, "total") is None:
            status("1/4 臓器を自動認識中（TotalSegmentator・約2〜4分）…"); slicer.app.processEvents()
            self._runTS(vol, "total", status)
        if self._segFor(vol, "heartchambers") is None:
            status("2/4 心腔を自動認識中（約4分）…"); slicer.app.processEvents()
            try: self._runTS(vol, "heartchambers", status)
            except Exception as e: print("heartchambers:", e)
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
        status("4/4 3D を作成中…"); slicer.app.processEvents()
        self.wallFill = True
        self.buildLayers(vol, specs, spacing, boneLayer, status)
        return self.qualityReport(vol, c, time.time() - t0)

    def adoptScene(self):
        """保存した症例（.mrb）を開いたあと、シーン中の CV モデルを引き継ぐ"""
        import json
        self.layerModels = {}; self.visible = {}
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            nm = n.GetName()
            if not nm.startswith("CV ") or nm == "CV 心筋断面": continue
            key = nm[3:]; self.layerModels[key] = n
            d = n.GetDisplayNode(); self.visible[key] = bool(d.GetVisibility()) if d else False
        if "心筋" in self.layerModels: self.visible["心筋"] = True
        self.workVolume = None; self.sourceVolume = None
        for v in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"):
            if v.GetAttribute("CardiacView.calib") is not None or "_cv" in v.GetName():
                self.workVolume = v
                try: self.calib = json.loads(v.GetAttribute("CardiacView.calib") or "{}")
                except Exception: self.calib = {}
                src = v.GetAttribute("CardiacView.source") or v.GetName().split("_cv")[0]
                self.sourceVolume = slicer.mrmlScene.GetFirstNodeByName(src)
                break
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
        self._updateBounds()
        try: self.studioLighting(0, ssao=True)
        except Exception: pass
        try: self.applyPalette(CUR_PALETTE, rebuildVR=False)               # 保存した症例も、今の色合いで
        except Exception as e: print("palette:", e)
        return len(self.layerModels)

    def _resample(self, vol, spacing):
        cur = vol.GetSpacing()
        if max(abs(cur[i] - spacing) for i in range(3)) < 0.05: return vol
        name = f"{vol.GetName()}_cv{spacing:.1f}mm"
        out = slicer.mrmlScene.GetFirstNodeByName(name)
        if out and out.GetImageData(): return out
        out = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
        p = {"InputVolume": vol.GetID(), "OutputVolume": out.GetID(),
             "outputPixelSpacing": f"{spacing},{spacing},{spacing}", "interpolationType": "bspline"}
        slicer.cli.runSync(slicer.modules.resamplescalarvolume, None, p)
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

    def _segFor(self, vol, kind):
        """vol に対応するセグメンテーション。kind: "total" / "heartchambers" """
        if vol is None: return None
        want = [f"{vol.GetName()} {kind}"] + ([f"{vol.GetName()} segmentation"] if kind == "total" else [])
        cands = []
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            sg = n.GetSegmentation()
            names = [sg.GetNthSegment(i).GetName().lower() for i in range(sg.GetNumberOfSegments())]
            isHC = any("left ventricle" in x for x in names)
            ok = isHC if kind == "heartchambers" else (len(names) > 20 and not isHC)
            if not ok: continue
            if n.GetName() in want: return n
            r = n.GetNodeReference("referenceImageGeometryRef")
            if r is not None and r.GetID() == vol.GetID(): cands.append(n)
        return cands[0] if cands else None

    def _findSegmentation(self):
        src = getattr(self, "sourceVolume", None)
        if src is not None: return self._segFor(src, "total")
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            if n.GetSegmentation().GetNumberOfSegments() > 20: return n
        return None

    def _segmentMaskArray(self, segNode, refVol, keywords):
        sg = segNode.GetSegmentation()
        ids = vtk.vtkStringArray(); sg.GetSegmentIDs(ids)
        sel = vtk.vtkStringArray()
        for k in range(ids.GetNumberOfValues()):
            sid = ids.GetValue(k)
            nm = sg.GetSegment(sid).GetName().lower().replace("_", " ")
            if any(t.replace("_", " ") in nm for t in keywords): sel.InsertNextValue(sid)
        if sel.GetNumberOfValues() == 0: return None
        lab = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "cv_tmpLabel")
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(segNode, sel, lab, refVol)
        mask = slicer.util.arrayFromVolume(lab) > 0
        slicer.mrmlScene.RemoveNode(lab)
        return mask

    def _boneMaskArray(self, segNode, refVol):
        sg = segNode.GetSegmentation()
        ids = vtk.vtkStringArray(); sg.GetSegmentIDs(ids)
        sel = vtk.vtkStringArray()
        for k in range(ids.GetNumberOfValues()):
            sid = ids.GetValue(k)
            if any(t in sg.GetSegment(sid).GetName().lower() for t in BONE_KEYWORDS): sel.InsertNextValue(sid)
        if sel.GetNumberOfValues() == 0: return None
        lab = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "cv_boneLabel")
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(segNode, sel, lab, refVol)
        mask = slicer.util.arrayFromVolume(lab) > 0
        slicer.mrmlScene.RemoveNode(lab)
        return mask

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

    def _cleanBinary(self, binary, spacing, minVox=60):
        """CT 寝台（薄く広い板）と微小な粒を除く"""
        try:
            from scipy import ndimage
        except Exception:
            return binary
        lab, n = ndimage.label(binary)
        if n == 0: return binary
        sizes = ndimage.sum(binary, lab, range(1, n + 1))
        objs = ndimage.find_objects(lab)
        dims = np.array(binary.shape, float)
        keep = np.zeros(n + 1, bool)
        for i, sl in enumerate(objs, start=1):
            sz = sizes[i - 1]
            if sz < minVox: continue
            ext = np.array([s_.stop - s_.start for s_ in sl], float)
            big = (ext / dims) > 0.7
            thin = (ext * spacing) < 30.0
            if big.sum() >= 2 and thin.sum() >= 1 and sz > 3000: continue   # 寝台
            keep[i] = True
        return keep[lab].astype(np.uint8)

    def _surfaceFromBinary(self, binary, vol, name, color, smooth, keepSmall=False):
        from vtk.util.numpy_support import numpy_to_vtk
        img = vtk.vtkImageData(); img.SetDimensions(binary.shape[2], binary.shape[1], binary.shape[0])
        img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(binary.ravel()), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        src = img
        if smooth >= 1:
            cast = vtk.vtkImageCast(); cast.SetInputData(img); cast.SetOutputScalarTypeToFloat(); cast.Update()
            gs = vtk.vtkImageGaussianSmooth(); gs.SetInputConnection(cast.GetOutputPort())
            sd = 0.8 if smooth == 1 else 1.3
            gs.SetStandardDeviations(sd, sd, sd); gs.SetRadiusFactors(2, 2, 2); gs.Update(); src = gs.GetOutput()
        mc = vtk.vtkFlyingEdges3D(); mc.SetInputData(src); mc.SetValue(0, 0.5)
        mc.ComputeNormalsOff(); mc.ComputeScalarsOff(); mc.ComputeGradientsOff(); mc.Update()
        pd = mc.GetOutput()
        def sinc(p, it, pb):
            ws = vtk.vtkWindowedSincPolyDataFilter(); ws.SetInputData(p); ws.SetNumberOfIterations(it)
            ws.SetPassBand(pb); ws.BoundarySmoothingOff(); ws.FeatureEdgeSmoothingOff(); ws.NonManifoldSmoothingOn(); ws.NormalizeCoordinatesOn(); ws.Update()
            return ws.GetOutput()
        if smooth >= 1 and pd.GetNumberOfPoints() > 0:          # 先になめらかにしてから間引く（間引きの角が出ない）
            pd = sinc(pd, 60 if smooth == 1 else 80, 0.01)          # 段々（等高線のような縞）が消えるまで。形は縮まない
        if pd.GetNumberOfPolys() > MAX_TRIS:
            dec = vtk.vtkQuadricDecimation(); dec.SetInputData(pd); dec.SetTargetReduction(1.0 - MAX_TRIS / pd.GetNumberOfPolys()); dec.Update(); pd = dec.GetOutput()
            if smooth >= 1: pd = sinc(pd, 10, 0.08)
        m = vtk.vtkMatrix4x4(); vol.GetIJKToRASMatrix(m)
        tr = vtk.vtkTransform(); tr.SetMatrix(m)
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputData(pd); tp.SetTransform(tr); tp.Update()
        # 法線の向きを部品ごとに決める: AutoOrient は閉じた内側の面（心内膜）を外向きにしてしまい逆になる。
        # 各部品で「法線の裏側が組織（binary=1）、表側が組織外」になっているかを実際のマスクで確かめ、逆なら反転する。
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(tp.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOff(); nm.Update()
        result = nm.GetOutput()
        try:                                                   # 浮いた小さなかけら（ノイズ）を消す（石灰化・人工物は小さくても残す）
            if keepSmall: raise StopIteration
            cf = vtk.vtkPolyDataConnectivityFilter(); cf.SetInputData(result); cf.SetExtractionModeToAllRegions(); cf.Update()
            sizes = [cf.GetRegionSizes().GetValue(i) for i in range(cf.GetNumberOfExtractedRegions())]
            if len(sizes) > 1:
                thr = max(120, 0.01 * max(sizes))
                keepIds = [i for i, n in enumerate(sizes) if n >= thr]
                if len(keepIds) < len(sizes):
                    cf2 = vtk.vtkPolyDataConnectivityFilter(); cf2.SetInputData(result); cf2.SetExtractionModeToSpecifiedRegions()
                    for i in keepIds: cf2.AddSpecifiedRegion(i)
                    cf2.Update(); cl = vtk.vtkCleanPolyData(); cl.SetInputData(cf2.GetOutput()); cl.Update()
                    result = cl.GetOutput()
                    print(f"{name}: 小さなかけら {len(sizes) - len(keepIds)} 個を除去")
        except StopIteration: pass
        except Exception as e:
            print("debris:", e)
        try:
            result = self._orientByMask(result, binary, vol)
        except Exception as e:
            print("orient:", e)
        old = slicer.mrmlScene.GetFirstNodeByName(f"CV {name}")
        if old: slicer.mrmlScene.RemoveNode(old)
        model = slicer.modules.models.logic().AddModel(result)
        model.SetName(f"CV {name}")
        self._styleDisplay(model.GetDisplayNode(), color)
        self._put(model)
        return model

    def _orientByMask(self, pd, binary, vol, dmm=1.0):
        """頂点ごとに法線を「組織の外向き」にそろえる（ぼかしたマスクを法線の前後で比べる）。
        閉じた内側の面（心内膜）や非多様体のつなぎ目で向きが逆になるのを防ぐ。"""
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk, numpy_to_vtkIdTypeArray
        from scipy import ndimage
        out = vtk.vtkPolyData(); out.DeepCopy(pd)
        if out.GetNumberOfPoints() == 0: return pd
        if out.GetPointData().GetNormals() is None:
            nf = vtk.vtkPolyDataNormals(); nf.SetInputData(out); nf.SplittingOff(); nf.ConsistencyOn(); nf.AutoOrientNormalsOff(); nf.Update(); out.DeepCopy(nf.GetOutput())
        P = vtk_to_numpy(out.GetPoints().GetData()).astype(float)
        N = vtk_to_numpy(out.GetPointData().GetNormals()).astype(np.float32).copy()
        M = vtk.vtkMatrix4x4(); vol.GetRASToIJKMatrix(M); A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        sm = ndimage.gaussian_filter(binary.astype(np.float32), 0.8)
        def samp(Q):
            H = (np.c_[Q, np.ones(len(Q))] @ A.T)[:, :3]      # i, j, k
            return ndimage.map_coordinates(sm, [H[:, 2], H[:, 1], H[:, 0]], order=1, mode="constant", cval=0.0)
        score = samp(P - N * dmm) - samp(P + N * dmm)          # 正しい向きなら > 0
        flipV = score < -0.02
        N[flipV] *= -1
        na = numpy_to_vtk(N, deep=True); na.SetName("Normals"); out.GetPointData().SetNormals(na)
        polys = out.GetPolys()
        conn = vtk_to_numpy(polys.GetConnectivityArray()).copy(); offs = vtk_to_numpy(polys.GetOffsetsArray())
        if len(offs) > 1 and np.all(np.diff(offs) == 3):
            tri = conn.reshape(-1, 3)
            # 三角形の巻き順も、頂点法線の平均と合うように直す（裏面色のため）
            g = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
            nmean = N[tri[:, 0]] + N[tri[:, 1]] + N[tri[:, 2]]
            fc = np.sum(g * nmean, axis=1) < 0
            tri[fc] = tri[fc][:, [0, 2, 1]]
            ca = vtk.vtkCellArray(); ca.SetData(numpy_to_vtkIdTypeArray(offs.astype(np.int64), deep=True), numpy_to_vtkIdTypeArray(tri.ravel().astype(np.int64), deep=True))
            out.SetPolys(ca)
        print(f"法線: {int(flipV.sum())}/{len(P)} 頂点を外向きに修正")
        return out

    def _styleDisplay(self, d, color, opacity=1.0):
        d.SetScalarVisibility(False); d.SetColor(*color); d.SetOpacity(opacity)
        d.SetVisibility2D(True); d.SetSliceIntersectionThickness(2)
        d.SetBackfaceCulling(False); d.SetAmbient(0.12); d.SetDiffuse(0.82); d.SetSpecular(0.4); d.SetPower(35)
        try: d.SetBackfaceColorHSVOffset(0.0, -0.05, -0.22)   # 内側は同じ色のやや暗いトーン
        except Exception: pass
        try: d.SetInterpolation(d.PhongInterpolation)
        except Exception: pass

    def _updateBounds(self):
        B = [n.GetPolyData().GetBounds() for n in self.layerModels.values() if n and n.GetPolyData() and n.GetPolyData().GetNumberOfPoints()]
        if not B:
            self.bounds = None; return
        A = np.array(B); self.bounds = (A[:, 0::2].min(0), A[:, 1::2].max(0))

    def _namesFor(self, name):
        if name == "人工物・石灰化": return ["人工物", "石灰化", "胸骨ワイヤー"]
        if name == "血液・血管":
            return [k for k in self.layerModels if k == name or k.startswith("血管")]
        return [name]

    def updateMyoCap(self):
        """心筋の切り口だけを正しく塗る（内腔の穴は空けたまま）。vtkCutter + vtkContourTriangulator"""
        my = self.layerModels.get("心筋")
        capNode = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
        if getattr(self, "on4D", False) or getattr(self, "vrOn", False):   # 4D・VR の表示中は切り口の塗りを出さない（VR の上にかぶる）
            if capNode is not None and capNode.GetDisplayNode() is not None: capNode.GetDisplayNode().SetVisibility(False)
            return
        show = (my is not None and self.visible.get("心筋", False) and self.cutAxis is not None and self.cutPlane is not None)
        # 切っている間は心筋の「外形」は隠す（心臓壁の内膜と重なってチラつき、内腔がべた塗りに見えるため）。
        # 心筋は切り口（実質）だけを塗る。切らないときは外形を半透明で出す。
        if my is not None and my.GetDisplayNode():
            my.GetDisplayNode().SetVisibility(bool(self.visible.get("心筋", False)) and self.cutAxis is None)
        if not show:
            if capNode and capNode.GetDisplayNode(): capNode.GetDisplayNode().SetVisibility(False)
            return
        o = [0, 0, 0]; n = [0, 0, 0]; self.cutPlane.GetCenter(o); self.cutPlane.GetNormal(n)
        n = np.array(n, float); n /= np.linalg.norm(n)
        plane = vtk.vtkPlane(); plane.SetOrigin(*o); plane.SetNormal(*n)
        cut = vtk.vtkCutter(); cut.SetInputData(my.GetPolyData()); cut.SetCutFunction(plane)
        strip = vtk.vtkStripper(); strip.SetInputConnection(cut.GetOutputPort()); strip.JoinContiguousSegmentsOn()
        tri = vtk.vtkContourTriangulator(); tri.SetInputConnection(strip.GetOutputPort()); tri.Update()
        pd = vtk.vtkPolyData(); pd.DeepCopy(tri.GetOutput())
        # カメラ側に 0.2mm ずらして、壁の面とのちらつきを防ぐ
        sign = 1.0 if self.cutSign > 0 else -1.0
        tf = vtk.vtkTransform(); tf.Translate(*(n * 0.8 * sign))   # 切り口の三角形のはみ出し(~1mm)より手前に
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputData(pd); tp.SetTransform(tf); tp.Update()
        out = tp.GetOutput()
        from vtk.util.numpy_support import numpy_to_vtk
        vpn = np.array(self._camera().GetCamera().GetViewPlaneNormal(), float)
        # 三角形の巻き順と法線をそろえてカメラ向きにする（バラバラだと SSAO/両面ライティングで黒ずむ）
        from vtk.util.numpy_support import vtk_to_numpy
        P = vtk_to_numpy(out.GetPoints().GetData()).astype(float) if out.GetNumberOfPoints() else np.zeros((0, 3))
        if out.GetNumberOfPolys():
            conn = vtk_to_numpy(out.GetPolys().GetConnectivityArray()).reshape(-1, 3).copy()
            gn = np.cross(P[conn[:, 1]] - P[conn[:, 0]], P[conn[:, 2]] - P[conn[:, 0]])
            bad = (gn @ vpn) < 0
            conn[bad] = conn[bad][:, [0, 2, 1]]
            ca = vtk.vtkCellArray()
            from vtk.util.numpy_support import numpy_to_vtkIdTypeArray
            off = numpy_to_vtkIdTypeArray(np.arange(0, 3 * len(conn) + 1, 3, dtype=np.int64), deep=True)
            cn = numpy_to_vtkIdTypeArray(conn.ravel().astype(np.int64), deep=True)
            ca.SetData(off, cn); out.SetPolys(ca)
        nrm = np.tile(vpn, (out.GetNumberOfPoints(), 1)).astype(np.float32)
        na = numpy_to_vtk(nrm, deep=True); na.SetName("Normals"); out.GetPointData().SetNormals(na)
        if capNode is None:
            capNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "CV 心筋断面")
            capNode.CreateDefaultDisplayNodes(); self._put(capNode)
        capNode.SetAndObservePolyData(out)
        d = capNode.GetDisplayNode()
        d.SetScalarVisibility(False); d.SetColor(*MYO_CUT_COLOR); d.SetBackfaceCulling(False)
        d.SetAmbient(0.85); d.SetDiffuse(0.20); d.SetSpecular(0.0)   # 切り口はフラットな面として均一に
        d.SetOpacity(getattr(self, "capOpacity", 1.0)); d.SetVisibility(True); d.SetVisibility2D(False)

    def setCapOpacity(self, op):
        """心筋の濃さ: 切り口の塗りと、心筋そのものの不透明度を一緒に変える"""
        self.capOpacity = float(op)
        m = self.layerModels.get("心臓壁")
        if m and m.GetDisplayNode(): m.GetDisplayNode().SetClippingCapOpacity(self.capOpacity)
        my = self.layerModels.get("心筋")
        if my and my.GetDisplayNode():
            my.GetDisplayNode().SetOpacity(max(0.15, self.capOpacity))
        self.updateMyoCap()

    def _maskPointsRAS(self, mask, maxPts=20000):
        idx = np.argwhere(mask)
        if len(idx) == 0: return None
        if len(idx) > maxPts: idx = idx[np.random.default_rng(0).choice(len(idx), maxPts, replace=False)]
        M = vtk.vtkMatrix4x4(); self.workVolume.GetIJKToRASMatrix(M)
        A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        ijk1 = np.c_[idx[:, 2], idx[:, 1], idx[:, 0], np.ones(len(idx))]
        return (ijk1 @ A.T)[:, :3]

    def fourChamber(self):
        """左室の長軸と右室中心を含む面（四腔断面）で切り、その面を正面から見る。戻り値は切断位置(0..1)"""
        hc = self._findChambers()
        if hc is None or self.workVolume is None: return None
        lv = self._maskPointsRAS(self._segmentMaskArray(hc, self.workVolume, ("left ventricle",)))
        la = self._maskPointsRAS(self._segmentMaskArray(hc, self.workVolume, ("left atrium",)))
        rv = self._maskPointsRAS(self._segmentMaskArray(hc, self.workVolume, ("right ventricle",)))
        if lv is None or la is None or rv is None: return None
        lac = la.mean(0); lvc = lv.mean(0); rvc = rv.mean(0)
        apex = lv[np.argmax(np.linalg.norm(lv - lac, axis=1))]
        axis = apex - lac; axis /= np.linalg.norm(axis)
        n = np.cross(axis, rvc - lvc); n /= np.linalg.norm(n)
        if n[1] < 0: n = -n                       # カメラは前（anterior）側
        center = (lvc + rvc + lac) / 3.0
        vb = self._visibleBounds()                 # 見えている心臓の大きさで距離を決める（体幹全体の CT でも心臓が小さくならない）
        r = float(np.linalg.norm(vb[1] - vb[0]) / 2) if vb is not None else self._sceneRadius()
        cn = self._camera()
        cn.SetFocalPoint(*center); cn.SetPosition(*(center + n * r * 2.2)); cn.SetViewUp(*(-axis))
        try: self._fitParallel()                                               # 画面の縦横比に合わせて心臓全体を収める
        except Exception as e: print('fit:', e)
        cn.GetCamera().SetViewAngle(30); cn.ResetClippingRange()
        lo, hi = self._visibleBounds()
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        proj = corners @ n; dmin, dmax = proj.min(), proj.max()
        frac = float(np.clip((dmax - center @ n) / max(dmax - dmin, 1e-6), 0, 1))
        self.setCut("VIEW", frac)
        self._view().forceRender()
        return frac

    def rebuildWall(self):
        """心臓壁を作り直す。心腔ラベルがあれば、内腔（右心系の造影不良な血液も含む）を壁から除外する"""
        segNode = self._findSegmentation(); hc = self._findChambers()
        if segNode is None or self.workVolume is None: return False
        from scipy import ndimage
        work = self.workVolume; arr = slicer.util.arrayFromVolume(work); sp = float(min(work.GetSpacing()))
        # 壁を作る範囲: 心臓の外形は高解像度の心腔ラベル（心腔＋心筋）、大血管は全身ラベル。
        # 全身ラベルの「心臓」は 3mm 格子でカクカクなので、心腔ラベルがあればそちらを使う。範囲は本当の距離で 4mm 外まで（なめらか）
        hcAll = self._segmentMaskArray(hc, work, ("ventricle", "atrium", "myocardium", "aorta", "pulmonary artery")) if hc is not None else None
        hvv = self._segmentMaskArray(segNode, work, ("atrial appendage", "aorta", "pulmonary vein", "vena cava", "brachiocephalic trunk", "pulmonary artery"))
        hv0 = hcAll if hcAll is not None else self._segmentMaskArray(segNode, work, ("heart",))
        hv = hv0 if hvv is None else (hvv if hv0 is None else (hv0 | hvv))
        if hv is None: return False
        hv = ndimage.gaussian_filter(hv.astype(np.float32), 1.2 / sp) > 0.5
        region = ndimage.distance_transform_edt(~hv, sampling=work.GetSpacing()[::-1]) <= (4.0 if hcAll is not None else 2.4)
        c = self._cal()
        wall = (arr >= c["wall_lo"]) & (arr <= c["wall_hi"]) & region
        cav = None
        if hc is not None:
            cav = self._segmentMaskArray(hc, work, ("left ventricle", "left atrium", "right ventricle", "right atrium", "aorta", "pulmonary artery"))
            if cav is not None: wall &= ~cav
        # 薄い壁（左房・右房・大血管 1〜2mm）は部分容積で CT 値帯から外れ、穴になる。
        #   血液側: 造影血液と平均されて >175HU、脂肪側: 脂肪と平均されて <-20HU。
        # → 内腔ラベルの外側に必ず 2 ボクセル（約2.4mm）の殻を足して、壁を閉じる。
        lumen = self._segmentMaskArray(segNode, work, ("atrial appendage", "aorta", "pulmonary vein", "vena cava", "brachiocephalic trunk", "pulmonary artery"))
        lumen = np.zeros_like(wall) if lumen is None else lumen.astype(bool)   # "heart"（心臓全体）は内腔ではないので入れない
        if cav is not None: lumen |= cav
        # AI の全身ラベルは 3mm 格子で作られていてカクカク → ラベル由来の内腔は強めに（約1.8mm）ならす
        lumen = ndimage.gaussian_filter(lumen.astype(np.float32), 1.8 / sp) > 0.5
        # ラベルの切れ目（大動脈基部・バルサルバ洞、LVOT など）も内腔として扱う: 心臓まわりで造影された血液
        bl = (arr >= c["blood_lo"]) & (arr <= 3000) & region
        bl = ndimage.gaussian_filter(bl.astype(np.float32), 0.8 / sp) > 0.5
        nLab = int(lumen.sum()); lumen |= bl
        print(f"内腔: ラベル {nLab} + 造影血液（ラベル外）{int(lumen.sum()) - nLab} ボクセル")
        if cav is not None: wall &= ~lumen
        nIt = max(1, int(round(2.4 / sp)))
        shell = ndimage.binary_dilation(lumen, iterations=nIt) & ~lumen
        print(f"壁: CT値帯 {int(wall.sum())} + 内腔の殻 {int((shell & ~wall).sum())} ボクセル")
        self._wallEvidence = wall.copy()            # CT 値で裏付けのある壁
        self._wallSynth = shell & ~wall             # 補った壁
        if getattr(self, "wallFill", True):
            wall |= shell
        wall = self._cleanBinary(wall.astype(np.uint8), sp, minVox=200)
        old = self.layerModels.get("心臓壁")
        vis = self.visible.get("心臓壁", True)
        if old: slicer.mrmlScene.RemoveNode(old)
        m = self._surfaceFromBinary(wall, work, "心臓壁", EPI_COLOR, 1)
        self.layerModels["心臓壁"] = m; self.visible["心臓壁"] = vis; m.GetDisplayNode().SetVisibility(vis)
        self.colorWallEpiEndo()
        return True

    def buildMyocardium(self):
        """心腔モデルの myocardium から、中隔を含む心筋のモデルを作る"""
        hcNode = self._findChambers()
        if hcNode is None or self.workVolume is None: return False
        mask = self._segmentMaskArray(hcNode, self.workVolume, ("myocardium",))
        if mask is None or mask.sum() < 100: return False
        # 右室の自由壁を足す: 右室内腔のまわり ~5mm の殻で、筋肉の CT 値（-20〜175HU）のところ
        try:
            from scipy import ndimage
            arr = slicer.util.arrayFromVolume(self.workVolume)
            sp = float(min(self.workVolume.GetSpacing()))
            rv = self._segmentMaskArray(hcNode, self.workVolume, ("right ventricle",))
            leftc = self._segmentMaskArray(hcNode, self.workVolume, ("left ventricle", "left atrium", "aorta", "right atrium", "pulmonary artery"))
            if rv is not None:
                it = max(2, int(round(3.5 / sp)))   # 右室自由壁は薄い（3〜4mm）
                shell = ndimage.binary_dilation(rv, iterations=it) & ~rv
                c = self._cal(); rvwall = shell & (arr >= c["wall_lo"]) & (arr <= c["wall_hi"])
                if leftc is not None: rvwall &= ~leftc
                lab, n = ndimage.label(rvwall)
                if n:
                    sizes = ndimage.sum(rvwall, lab, range(1, n + 1))
                    keep = np.zeros(n + 1, bool); keep[1:] = sizes >= 150
                    rvwall = keep[lab]
                mask = mask | rvwall
                print(f"右室自由壁を追加: {int(rvwall.sum())} ボクセル")
        except Exception as e:
            print("rv wall:", e)
        m = self._surfaceFromBinary(mask.astype(np.uint8), self.workVolume, "心筋", MYO_COLOR, 1)
        self.layerModels["心筋"] = m; self.visible["心筋"] = False; m.GetDisplayNode().SetVisibility(False)
        return True

    def _findChambers(self):
        src = getattr(self, "sourceVolume", None)
        if src is not None: return self._segFor(src, "heartchambers")
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            sg = n.GetSegmentation()
            if any("left ventricle" in sg.GetNthSegment(i).GetName().lower() for i in range(sg.GetNumberOfSegments())):
                return n
        return None

    def colorWallEpiEndo(self):
        """心臓壁の各頂点を 外膜 / 左心系の内膜 / 右心系の内膜 に塗り分ける（法線方向の CT 値と心腔ラベルで判定）"""
        m = self.layerModels.get("心臓壁")
        if m is None or self.workVolume is None: return
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
        vol = self.workVolume; arr = slicer.util.arrayFromVolume(vol)
        c = self._cal(); blood = (arr >= c["blood_lo"]) & (arr <= c["blood_hi"])
        hcNode = self._findChambers()
        left = right = None
        if hcNode is not None:
            left = self._segmentMaskArray(hcNode, vol, ("left atrium", "left ventricle", "aorta"))
            right = self._segmentMaskArray(hcNode, vol, ("right atrium", "right ventricle", "pulmonary artery"))
        pd = m.GetPolyData()
        if pd.GetPointData().GetNormals() is None:
            nf = vtk.vtkPolyDataNormals(); nf.SetInputData(pd); nf.SplittingOff(); nf.AutoOrientNormalsOn(); nf.Update(); pd.DeepCopy(nf.GetOutput())
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        N = vtk_to_numpy(pd.GetPointData().GetNormals()).astype(float)
        M = vtk.vtkMatrix4x4(); vol.GetRASToIJKMatrix(M)
        A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        nz, ny, nx = arr.shape
        endo = np.zeros(len(P)); lh = np.zeros(len(P)); rh = np.zeros(len(P))
        steps = (1.0, 2.0, 3.5)
        for dmm in steps:
            H = np.c_[P + N * dmm, np.ones(len(P))] @ A.T
            ijk = np.rint(H[:, :3]).astype(int)
            i, j, k = ijk[:, 0], ijk[:, 1], ijk[:, 2]
            ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny) & (k >= 0) & (k < nz)
            def look(mask):
                h = np.zeros(len(P), bool); h[ok] = mask[k[ok], j[ok], i[ok]]; return h
            b = look(blood)
            if left is not None:
                l = look(left); r = look(right); lh += l; rh += r; b = b | l | r
            endo += b
        isEndo = endo / len(steps) >= 0.34
        cls = np.zeros(len(P), np.int8)                    # 0 = 外膜, 1 = 左心系, 2 = 右心系
        cls[isEndo] = 1
        if left is not None: cls[isEndo & (rh > lh)] = 2
        # まだら（外膜に内膜色の点が散る）を防ぐ: メッシュの近所で多数決
        try:
            from scipy import sparse
            from vtk.util.numpy_support import vtk_to_numpy as _v2n
            tri0 = _v2n(pd.GetPolys().GetConnectivityArray()).reshape(-1, 3)
            e0 = np.r_[tri0[:, [0, 1]], tri0[:, [1, 2]], tri0[:, [2, 0]]]
            W0 = sparse.coo_matrix((np.ones(len(e0) * 2, np.float32), (np.r_[e0[:, 0], e0[:, 1]], np.r_[e0[:, 1], e0[:, 0]])), shape=(len(P), len(P))).tocsr()
            W0 = W0 + sparse.identity(len(P), dtype=np.float32, format="csr"); deg0 = np.asarray(W0.sum(1)).ravel()
            F = np.stack([(cls == q).astype(np.float32) for q in range(3)], 1)
            for _ in range(5): F = (W0 @ F) / deg0[:, None]
            cls = np.argmax(F, axis=1).astype(np.int8)
        except Exception as ex:
            print("class smooth:", ex)
        val = np.zeros(len(P), np.float32)                 # 0 = 外膜
        val[cls == 1] = 1/3                                 # 1/3 = 左心系（または判定不能の内膜）
        val[cls == 2] = 2/3                                 # 2/3 = 右心系
        # 補った壁（CT 値の裏付けなし）: 面の内側（組織側）を覗いて、補完マスクにしかない所
        syn = getattr(self, "_wallSynth", None); ev = getattr(self, "_wallEvidence", None)
        if getattr(self, "wallFill", True) and syn is not None and ev is not None and syn.shape == arr.shape:
            sh = np.zeros(len(P)); eh = np.zeros(len(P))
            for dmm in (0.6, 1.2, 1.8):
                H = np.c_[P - N * dmm, np.ones(len(P))] @ A.T
                ijk = np.rint(H[:, :3]).astype(int); i, j, k = ijk[:, 0], ijk[:, 1], ijk[:, 2]
                ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny) & (k >= 0) & (k < nz)
                a1 = np.zeros(len(P), bool); a1[ok] = syn[k[ok], j[ok], i[ok]]; sh += a1
                a2 = np.zeros(len(P), bool); a2[ok] = ev[k[ok], j[ok], i[ok]]; eh += a2
            raw = ((sh >= 2) & (eh == 0)).astype(np.float32)
            # まだらにならないよう、メッシュ上で近所の多数決（数回の平均化）で領域としてまとめる
            try:
                from scipy import sparse
                from vtk.util.numpy_support import vtk_to_numpy as _v2n
                tri = _v2n(pd.GetPolys().GetConnectivityArray()).reshape(-1, 3)
                e = np.r_[tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]
                W = sparse.coo_matrix((np.ones(len(e) * 2, np.float32), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(len(P), len(P))).tocsr()
                W = W + sparse.identity(len(P), dtype=np.float32, format="csr")
                deg = np.asarray(W.sum(1)).ravel()
                f = raw
                for _ in range(4): f = (W @ f) / deg
                isSyn = f >= 0.5
            except Exception as ex:
                print("syn smooth:", ex); isSyn = raw > 0.5
            if getattr(self, "showSynth", True): val[isSyn] = 1.0   # 1.0 = 補った壁（グレー）。隠すときは内外の色のまま
            print(f"補った壁の頂点: {isSyn.mean()*100:.1f}%")
        va = numpy_to_vtk(val, deep=True); va.SetName("WallClass")
        pd.GetPointData().AddArray(va)
        old = slicer.mrmlScene.GetFirstNodeByName("CV EpiEndo")
        if old: slicer.mrmlScene.RemoveNode(old)
        ct = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode", "CV EpiEndo")
        ct.SetTypeToUser(); ct.SetNumberOfColors(256); ct.SetNamesInitialised(True)
        for t in range(256):
            x = t / 255.0
            c = EPI_COLOR if x < 1/6 else (ENDO_COLOR if x < 0.5 else (ENDO_R_COLOR if x < 5/6 else (SYNTH_COLOR if getattr(self, "showSynth", True) else EPI_COLOR)))
            ct.SetColor(t, f"c{t}", c[0], c[1], c[2], 1.0)
        d = m.GetDisplayNode()
        d.SetActiveScalarName("WallClass"); d.SetAndObserveColorNodeID(ct.GetID())
        d.SetScalarRangeFlag(d.UseManualScalarRange); d.SetScalarRange(0.0, 1.0); d.SetScalarVisibility(True)
        m.Modified()
        return hcNode is not None

    STATIC_4D = ("骨", "軟部組織", "人工物", "胸骨ワイヤー")                                 # 4D でも一緒に出せる面（心臓と一緒に動かないもの）

    def setLayerVisible(self, name, vis):
        if getattr(self, "on4D", False):                                    # 4D 表示中: 動かない骨・軟部組織・人工物だけ面を出す（心臓・血管の面は動く VR と重なるので戻った時に）
            for k in self._namesFor(name):
                self.visible[k] = bool(vis)
                n = self.layerModels.get(k)
                if k in self.STATIC_4D and n and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(bool(vis))
            try: self._clipSync()
            except Exception: pass
            self._view().scheduleRender()
            return
        for k in self._namesFor(name):
            self.visible[k] = bool(vis)
            src = self.layerModels.get(k)
            if src and src.GetDisplayNode(): src.GetDisplayNode().SetVisibility(vis)
        if name == "心筋":
            self.updateMyoCap()

    def setLayerOpacity(self, name, op):
        for k in self._namesFor(name):
            n = self.layerModels.get(k)
            if n and n.GetDisplayNode(): n.GetDisplayNode().SetOpacity(op)

    def applyPalette(self, name, rebuildVR=True):
        """色合いを変える: 今ある面の色・光沢、壁の色表、心筋の切り口、VR の色（VR を出していれば作り直す）"""
        p = _setPalette(name)
        cmap = {"血管:大動脈系": p["aorta"], "血管:体静脈": p["sysvein"], "血管:肺静脈": p["pv"], "血管:心臓": p["heart"], "血管:肺動脈ほか": p["pa"],
                "骨": p["bone"], "石灰化": p["calc"], "心筋": p["myo"]}
        for k, col in cmap.items():
            n = self.layerModels.get(k); d = n.GetDisplayNode() if n else None
            if d is None: continue
            d.SetColor(*col)
            if k.startswith("血管") or k == "心筋": d.SetSpecular(p["spec"]); d.SetPower(p["power"]); d.SetAmbient(p["amb"]); d.SetDiffuse(p["dif"])
        w_ = self.layerModels.get("心臓壁")
        if w_ is not None and w_.GetDisplayNode(): d = w_.GetDisplayNode(); d.SetSpecular(p["spec"]); d.SetPower(p["power"]); d.SetAmbient(p["amb"]); d.SetDiffuse(p["dif"])
        ct = slicer.mrmlScene.GetFirstNodeByName("CV EpiEndo")
        if ct is not None:
            for tt in range(256):
                x = tt / 255.0
                c = EPI_COLOR if x < 1/6 else (ENDO_COLOR if x < 0.5 else (ENDO_R_COLOR if x < 5/6 else (SYNTH_COLOR if getattr(self, "showSynth", True) else EPI_COLOR)))
                ct.SetColor(tt, f"c{tt}", c[0], c[1], c[2], 1.0)
        cap = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
        if cap is not None and cap.GetDisplayNode(): cap.GetDisplayNode().SetColor(*MYO_CUT_COLOR)
        self.VR_GROUPS = [(g[0], g[1], c, g[3]) for g, c in zip(type(self).VR_GROUPS, p["vr"])]; self.VR_NEUTRAL = p["vrN"]
        if rebuildVR and getattr(self, "vrOn", False) and getattr(self, "vrDisplay", None) is not None:
            try:
                self.vrDisplay.SetVisibility(False); self.vrDisplay = None; self.showVR(True, getattr(self, "vrMode", None))
            except Exception as e: print("palette VR:", e)
        else:
            if getattr(self, "vrDisplay", None) is not None and not getattr(self, "vrOn", False):
                self.vrDisplay = None                                         # 次に VR を出す時に新しい色で作る
        try: self._view().scheduleRender()
        except Exception: pass

    def setGloss(self, g):
        for n in list(self.layerModels.values()):
            d = n.GetDisplayNode() if n else None
            if d: d.SetSpecular(0.1 + 0.6 * g); d.SetPower(8 + 60 * g)

    # ---------------------------------------------------------------- パッチ（3D の面の上で塗って色分け）
    PATCH_KEY = "パッチ"
    PATCH_OFFSET = 0.35                                                       # 面から浮かせる距離 mm（重なってちらつかないように）

    def _paintTargets(self):
        """塗れる面: 見えているレイヤー（パッチ自身は除く）"""
        out = {}
        for k, n in self.layerModels.items():
            if k == self.PATCH_KEY or n is None: continue
            d = n.GetDisplayNode(); pd = n.GetPolyData()
            if d is None or not d.GetVisibility() or pd is None or pd.GetNumberOfPoints() == 0 or pd.GetNumberOfPolys() == 0: continue
            out[k] = n
        return out

    def _pcache(self, k, n):
        """面ごとの探し物用データ（点の KD 木・三角形の探索・頂点番号・法線）。面が作り直されたら作り直す"""
        from scipy.spatial import cKDTree
        from vtk.util.numpy_support import vtk_to_numpy
        c = self.__dict__.setdefault("_pc", {})
        pd = n.GetPolyData(); key = (n.GetID(), pd.GetNumberOfPoints(), pd.GetNumberOfPolys(), pd.GetPoints().GetMTime())
        e = c.get(k)
        if e is not None and e["key"] == key: return e
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(np.float64)
        polys = pd.GetPolys()
        try:
            off = vtk_to_numpy(polys.GetOffsetsArray()); con = vtk_to_numpy(polys.GetConnectivityArray())
            ok = len(off) > 1 and bool(np.all(np.diff(off) == 3))
        except Exception: ok = False
        if not ok:
            tf = vtk.vtkTriangleFilter(); tf.SetInputData(pd); tf.PassVertsOff(); tf.PassLinesOff(); tf.Update(); polys = tf.GetOutput().GetPolys()
            con = vtk_to_numpy(polys.GetConnectivityArray())
        T = con.reshape(-1, 3).astype(np.int64)
        ds = vtk.vtkPolyData(); ds.SetPoints(pd.GetPoints()); ds.SetPolys(polys)
        loc = vtk.vtkStaticCellLocator(); loc.SetDataSet(ds); loc.BuildLocator()
        nr = pd.GetPointData().GetNormals()
        if nr is None or nr.GetNumberOfTuples() != len(P):
            nm = vtk.vtkPolyDataNormals(); nm.SetInputData(ds); nm.SplittingOff(); nm.ComputePointNormalsOn(); nm.Update(); nr = nm.GetOutput().GetPointData().GetNormals()
        N = vtk_to_numpy(nr).astype(np.float64) if nr is not None and nr.GetNumberOfTuples() == len(P) else None
        e = dict(key=key, P=P, tree=cKDTree(P), loc=loc, ds=ds, T=T, N=N); c[k] = e
        return e

    def _paintPick(self, x, y):
        """画面の (x, y) の下にある、塗れる面の一番手前の点 → (面の名前, 点) / None。切って取り除いた側は通り抜ける"""
        ren = self._view().renderWindow().GetRenderers().GetFirstRenderer()
        def w(z):
            ren.SetDisplayPoint(float(x), float(y), z); ren.DisplayToWorld(); q = ren.GetWorldPoint()
            return np.array(q[:3], float) / (q[3] if abs(q[3]) > 1e-12 else 1.0)
        p0, p1 = w(0.0), w(1.0)
        planes = [(np.array(c, float), np.array(nn, float)) for c, nn in self._activePlanes()[0]]
        best = None; pts = vtk.vtkPoints(); ids = vtk.vtkIdList()
        for k, n in self._paintTargets().items():
            e = self._pcache(k, n); pts.Reset(); ids.Reset()
            e["loc"].IntersectWithLine(p0.tolist(), p1.tolist(), 1e-4, pts, ids)
            for i in range(pts.GetNumberOfPoints()):
                q = np.array(pts.GetPoint(i)); dist = float(np.linalg.norm(q - p0))
                if best is not None and dist >= best[0]: continue
                if planes and not any(float((q - c) @ nn) >= -0.05 for c, nn in planes): continue   # 切って消えている所
                best = (dist, k, q)
        return None if best is None else (best[1], best[2])

    def paintStart(self, r):
        self.paintOn = True; self.paintR = float(r); self._painting = False
        self.__dict__.setdefault("_strokes", [])
        for k, n in self._paintTargets().items(): self._pcache(k, n)          # 最初のひと塗りで待たないように先に準備
        self._patchSync()

    def paintEnd(self):
        was = getattr(self, "paintOn", False); self.paintOn = False; self._painting = False
        if was: self._patchBuild(); self._patchSave()
        a = float(getattr(self, "_patchAreaV", 0.0) or 0.0)
        return f"パッチを塗り終わりました（塗った広さ 約 {a / 100:.1f} cm²）" if a > 0 else "パッチ: 塗った所はありません"

    def _patchSync(self):
        """塗った記録（体の座標の筆の跡）と、面ごとの「塗った点」がずれていたら作り直す（面を作り直した時・開き直した時）"""
        pm = self.__dict__.setdefault("_pMask", {}); pk = self.__dict__.setdefault("_pMaskKey", {})
        for s in getattr(self, "_strokes", None) or []:
            n = self.layerModels.get(s[1])
            if n is None or n.GetPolyData() is None or n.GetPolyData().GetNumberOfPoints() == 0: continue
            e = self._pcache(s[1], n)
            if pm.get(s[1]) is None or pk.get(s[1]) != e["key"]: self._patchReplay(); return

    def _patchReplay(self):
        self._pMask = {}; self._pMaskKey = {}
        for sid, k, x, y, z, r, er in getattr(self, "_strokes", None) or []:
            n = self.layerModels.get(k)
            if n is None or n.GetPolyData() is None or n.GetPolyData().GetNumberOfPoints() == 0: continue
            self._dabMask(k, n, (x, y, z), r, er)

    def _dabMask(self, k, n, p, r, erase):
        e = self._pcache(k, n)
        pm = self.__dict__.setdefault("_pMask", {}); pk = self.__dict__.setdefault("_pMaskKey", {})
        m = pm.get(k)
        if m is None or len(m) != len(e["P"]) or pk.get(k) != e["key"]:
            m = pm[k] = np.zeros(len(e["P"]), bool); pk[k] = e["key"]
        idx = e["tree"].query_ball_point(np.asarray(p, float), float(r))
        if len(idx): m[np.asarray(idx, np.int64)] = not erase

    def _paintPress(self, it):
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place: return False      # 計測を置いている時は塗らない
        x, y = it.GetEventPosition(); hit = self._paintPick(x, y)
        if hit is None: return False
        st = self.__dict__.setdefault("_strokes", [])
        self._sid = max([s[0] for s in st], default=0) + 1
        self._painting = True; self._paintErase = bool(it.GetControlKey()); self._lastDab = None
        self._patchSync(); self._paintAt(hit)
        return True

    def _paintMove(self, it):
        x, y = it.GetEventPosition(); hit = self._paintPick(x, y)
        if hit is not None: self._paintAt(hit)

    def _paintRelease(self):
        self._painting = False; self._lastDab = None
        t = getattr(self, "_ptTimer", None)
        if t is not None: t.stop()
        self._patchBuild(); self._patchSave()

    def _paintAt(self, hit):
        k, p = hit; n = self.layerModels.get(k); p = np.asarray(p, float)
        r = float(getattr(self, "paintR", 4.0)); er = 1 if getattr(self, "_paintErase", False) else 0
        last = getattr(self, "_lastDab", None); seq = [p]
        if last is not None and last[0] == k:                                  # 速く動かしても途切れないように間を埋める
            d = float(np.linalg.norm(p - last[1]))
            if 0.5 * r < d < 60.0:
                m = int(np.ceil(d / (0.5 * r))); seq = [last[1] + (p - last[1]) * (i / m) for i in range(1, m + 1)]
        for q in seq:
            self._dabMask(k, n, q, r, er)
            self._strokes.append([self._sid, k, round(float(q[0]), 2), round(float(q[1]), 2), round(float(q[2]), 2), r, er])
        self._lastDab = (k, p)
        t = getattr(self, "_ptTimer", None)
        if t is None:
            t = self._ptTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(60); t.connect("timeout()", self._patchBuild)
        if not t.isActive(): t.start()

    def _patchBuild(self):
        """塗った点から「CV パッチ」の面を作る（塗った三角形を、面の表と裏へ少し浮かせて 2 枚）"""
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        app = vtk.vtkAppendPolyData(); cnt = 0; area = 0.0
        for k, m in list((getattr(self, "_pMask", None) or {}).items()):
            n = self.layerModels.get(k)
            if n is None or m is None or not m.any() or n.GetPolyData() is None: continue
            e = self._pcache(k, n)
            if len(m) != len(e["P"]): continue
            T = e["T"]; sel = m[T].all(axis=1)
            if not sel.any(): continue
            Ts = T[sel]; used = np.unique(Ts); remap = np.full(len(e["P"]), -1, np.int64); remap[used] = np.arange(len(used))
            Pu = e["P"][used]; Nu = e["N"][used] if e["N"] is not None else None; Tr = remap[Ts]
            area += 0.5 * float(np.linalg.norm(np.cross(Pu[Tr[:, 1]] - Pu[Tr[:, 0]], Pu[Tr[:, 2]] - Pu[Tr[:, 0]]), axis=1).sum())
            cells = np.ascontiguousarray(np.hstack([np.full((len(Tr), 1), 3, np.int64), Tr]).ravel())
            for sg in ((1.0, -1.0) if Nu is not None else (0.0,)):
                Q = np.ascontiguousarray(Pu + sg * self.PATCH_OFFSET * Nu) if Nu is not None else np.ascontiguousarray(Pu)
                pts = vtk.vtkPoints(); pts.SetData(numpy_to_vtk(Q, deep=True))
                ca = vtk.vtkCellArray(); ca.SetCells(len(Tr), numpy_to_vtkIdTypeArray(cells, deep=True))
                pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetPolys(ca); app.AddInputData(pd); cnt += 1
        self._patchAreaV = area
        node = self.layerModels.get(self.PATCH_KEY)
        if node is not None and not slicer.mrmlScene.IsNodePresent(node): node = None
        if node is None: node = slicer.mrmlScene.GetFirstNodeByName("CV パッチ")
        if cnt == 0:
            if node is not None: node.SetAndObservePolyData(vtk.vtkPolyData())
            self._view().scheduleRender(); return
        app.Update()
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(app.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOff(); nm.AutoOrientNormalsOff(); nm.Update()
        out = vtk.vtkPolyData(); out.DeepCopy(nm.GetOutput())
        if node is None:
            node = slicer.modules.models.logic().AddModel(out); node.SetName("CV パッチ")
            d = node.GetDisplayNode(); self._styleDisplay(d, PATCH_COLOR); d.SetSpecular(0.35); d.SetPower(25); d.SetAmbient(0.22)
            self._put(node)
        else:
            node.SetAndObservePolyData(out)
        self.layerModels[self.PATCH_KEY] = node; self.visible[self.PATCH_KEY] = True
        d = node.GetDisplayNode()
        if d is not None:
            if not d.GetVisibility(): d.SetVisibility(True)
            if self.cutAxis is not None and d.GetAttribute("CV.clipWant") != "1": self._applyClipToModels(True)
        self._view().scheduleRender()

    def _patchSave(self):
        """塗った記録を「CV パッチ」に持たせる（症例を保存すると一緒に残り、開き直しても続きを塗れる・戻せる）"""
        node = self.layerModels.get(self.PATCH_KEY)
        if node is not None and slicer.mrmlScene.IsNodePresent(node):
            node.SetAttribute("CV.patchStrokes", json.dumps(getattr(self, "_strokes", None) or [], ensure_ascii=False))

    def patchToSheet(self, step=2):
        """自動で出した「パッチの範囲」（閉じた塊＝袋のように見える）を、左室と右室の血液のちょうど真ん中の 1 枚の面にする。
        本物のパッチは中隔に縫い付けた 1 枚なので。開いた時に 1 回だけ（約 2 秒）。元の塊は隠したモデルに残す"""
        from scipy import ndimage
        from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
        node = self.layerModels.get(self.PATCH_KEY); src = getattr(self, "sourceVolume", None); hc = self._findChambers()
        pd = node.GetPolyData() if node is not None else None
        if pd is None or pd.GetNumberOfPolys() == 0 or src is None or hc is None: return False
        fe0 = vtk.vtkFeatureEdges(); fe0.SetInputData(pd); fe0.BoundaryEdgesOn(); fe0.FeatureEdgesOff(); fe0.NonManifoldEdgesOff(); fe0.ManifoldEdgesOff(); fe0.Update()
        if fe0.GetOutput().GetNumberOfCells() > 0.02 * pd.GetNumberOfPolys():
            node.SetAttribute("CV.patchSheet", "1"); return False                 # もともと 1 枚（縁がある）
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M); A = slicer.util.arrayFromVTKMatrix(M)
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        ijk = (np.linalg.inv(A) @ np.c_[P, np.ones(len(P))].T)[:3].T
        dims = np.array(src.GetImageData().GetDimensions()); sp = np.array(src.GetSpacing())
        mg = np.ceil(10.0 / sp).astype(int)
        lo = np.maximum(np.floor(ijk.min(0)).astype(int) - mg, 0); hi = np.minimum(np.ceil(ijk.max(0)).astype(int) + mg, dims - 1)
        hu = slicer.util.arrayFromVolume(src)[lo[2]:hi[2] + 1:step, lo[1]:hi[1] + 1:step, lo[0]:hi[0] + 1:step].astype(np.float32)
        nz, ny, nx = hu.shape
        G = A @ np.array([[step, 0, 0, lo[0]], [0, step, 0, lo[1]], [0, 0, step, lo[2]], [0, 0, 0, 1.0]])
        spc = np.array([np.linalg.norm(G[:3, 2]), np.linalg.norm(G[:3, 1]), np.linalg.norm(G[:3, 0])])   # (z, y, x) mm
        def vm(X):
            m = vtk.vtkMatrix4x4()
            for r in range(4):
                for c_ in range(4): m.SetElement(r, c_, X[r, c_])
            return m
        ref = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "cv_tmpRef")
        img = vtk.vtkImageData(); img.SetDimensions(nx, ny, nz); img.AllocateScalars(vtk.VTK_SHORT, 1); ref.SetAndObserveImageData(img); ref.SetIJKToRASMatrix(vm(G))
        try:
            LV = self._segmentMaskArray(hc, ref, ("left ventricle",)); RV = self._segmentMaskArray(hc, ref, ("right ventricle",))
        finally:
            slicer.mrmlScene.RemoveNode(ref)
        if LV is None or RV is None or not LV.any() or not RV.any(): return False
        tf = vtk.vtkTransform(); tf.SetMatrix(vm(np.linalg.inv(G)))
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputData(pd); tp.SetTransform(tf); tp.Update()
        stn = vtk.vtkPolyDataToImageStencil(); stn.SetInputConnection(tp.GetOutputPort()); stn.SetOutputOrigin(0, 0, 0); stn.SetOutputSpacing(1, 1, 1)
        stn.SetOutputWholeExtent(0, nx - 1, 0, ny - 1, 0, nz - 1); stn.Update()
        one = vtk.vtkImageData(); one.SetDimensions(nx, ny, nz); one.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1); one.GetPointData().GetScalars().Fill(1)
        sti = vtk.vtkImageStencil(); sti.SetInputData(one); sti.SetStencilConnection(stn.GetOutputPort()); sti.ReverseStencilOff(); sti.SetBackgroundValue(0); sti.Update()
        blob = vtk_to_numpy(sti.GetOutput().GetPointData().GetScalars()).reshape(nz, ny, nx) > 0
        if not blob.any(): return False
        c = self._cal(); thr = 0.5 * (float(c.get("myo", 80)) + float(c.get("blood", 350)))
        blood = ndimage.median_filter(hu, 3) > thr                                  # 造影された血液を、近い方の部屋（左室・右室）に分ける
        dLl = ndimage.distance_transform_edt(~LV, sampling=spc); dRl = ndimage.distance_transform_edt(~RV, sampling=spc)
        bL = blood & (dLl < dRl) & (dLl < 6); bR = blood & (dRl <= dLl) & (dRl < 6)
        if not bL.any() or not bR.any(): return False
        f = (ndimage.distance_transform_edt(~bL, sampling=spc) - ndimage.distance_transform_edt(~bR, sampling=spc)).astype(np.float32)
        def im_(a, name):
            im = vtk.vtkImageData(); im.SetDimensions(nx, ny, nz); v = numpy_to_vtk(np.ascontiguousarray(a.ravel()), deep=True); v.SetName(name); im.GetPointData().SetScalars(v); return im
        fe = vtk.vtkFlyingEdges3D(); fe.SetInputData(im_(f, "f")); fe.SetValue(0, 0.0); fe.ComputeNormalsOff(); fe.ComputeScalarsOff(); fe.Update()   # 左右の血液のちょうど真ん中
        pr = vtk.vtkProbeFilter(); pr.SetInputConnection(fe.GetOutputPort()); pr.SetSourceData(im_(ndimage.gaussian_filter(blob.astype(np.float32), 1.0), "blob")); pr.Update()
        o = pr.GetOutput(); o.GetPointData().SetActiveScalars("blob")
        cl = vtk.vtkClipPolyData(); cl.SetInputData(o); cl.SetValue(0.5); cl.Update()                                 # 塊の中だけ
        if cl.GetOutput().GetNumberOfPolys() == 0: return False
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(cl.GetOutputPort()); sm.SetNumberOfIterations(20); sm.SetPassBand(0.05)
        sm.BoundarySmoothingOn(); sm.FeatureEdgeSmoothingOff(); sm.NonManifoldSmoothingOn(); sm.NormalizeCoordinatesOn(); sm.Update()
        tr = vtk.vtkTransform(); tr.SetMatrix(vm(G)); tp2 = vtk.vtkTransformPolyDataFilter(); tp2.SetInputConnection(sm.GetOutputPort()); tp2.SetTransform(tr); tp2.Update()
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(tp2.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOff(); nm.ComputePointNormalsOn(); nm.Update()
        sheet = vtk.vtkPolyData(); sheet.DeepCopy(nm.GetOutput()); sheet.GetPointData().SetScalars(None)
        keep = slicer.mrmlScene.GetFirstNodeByName("CV パッチの範囲（元の塊）")
        if keep is None:
            keep = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "CV パッチの範囲（元の塊）"); keep.SetHideFromEditors(True)
            cp = vtk.vtkPolyData(); cp.DeepCopy(pd); keep.SetAndObservePolyData(cp)
        node.SetAndObservePolyData(sheet); node.SetAttribute("CV.patchSheet", "1")
        d = node.GetDisplayNode()
        if d is not None: d.SetBackfaceCulling(False); d.SetFrontfaceCulling(False)
        self._view().scheduleRender()
        return True

    def patchUndo(self):
        st = getattr(self, "_strokes", None) or []
        if not st: return "戻すものがありません"
        last = max(s[0] for s in st); self._strokes = [s for s in st if s[0] != last]
        self._patchReplay(); self._patchBuild(); self._patchSave()
        return "ひと塗り戻しました"

    def patchClear(self):
        if not (getattr(self, "_strokes", None) or []): return "塗ったパッチはありません"
        self._strokes = []; self._pMask = {}; self._pMaskKey = {}; self._patchBuild(); self._patchSave()
        return "塗ったパッチを全部消しました（「1つ戻す」では戻りません）"

    def patchFace(self, gap=4.0):
        """塗ったパッチを正面に向けて、パッチの少し手前（gap mm）から手前を切る（体に固定）"""
        from vtk.util.numpy_support import vtk_to_numpy
        node = self.layerModels.get(self.PATCH_KEY)
        pd = node.GetPolyData() if node is not None else None
        if pd is None or pd.GetNumberOfPoints() < 3: return False
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        c = P.mean(0); _, _, Vt = np.linalg.svd(P - c, full_matrices=False); n = Vt[2] / np.linalg.norm(Vt[2])
        nr = pd.GetPointData().GetNormals()
        if nr is not None and nr.GetNumberOfTuples() == len(P):                 # 曲がった 1 枚のパッチ: 法線の向きの平均（表裏は問わない）が正面
            N = vtk_to_numpy(nr).astype(float); w_, V_ = np.linalg.eigh(N.T @ N); n = V_[:, -1] / np.linalg.norm(V_[:, -1])
        cn = self._camera(); cam = cn.GetCamera()
        pos = np.array(cam.GetPosition()); fp = np.array(cam.GetFocalPoint())
        if float((pos - c) @ n) < 0: n = -n                                   # 今見ている側から
        dist = float(np.linalg.norm(pos - fp)) or 300.0
        up = np.array(cam.GetViewUp(), float); up = up - n * float(up @ n)
        if np.linalg.norm(up) < 1e-3: up = np.array([0.0, 0.0, 1.0]) - n * n[2]
        up /= np.linalg.norm(up); rt = np.cross(up, n)
        half = float(max(np.abs((P - c) @ up).max(), np.abs((P - c) @ rt).max(), 8.0))
        self.flying = False
        cn.SetFocalPoint(*c); cn.SetPosition(*(c + n * dist)); cn.SetViewUp(*up)
        if cam.GetParallelProjection(): cam.SetParallelScale(max(30.0, 2.2 * half))
        lo, hi = self._visibleBounds()
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        proj = corners @ n; dmin, dmax = float(proj.min()), float(proj.max())
        s_ = float(c @ n + max(0.0, float(((P - c) @ n).max())) + gap)
        if getattr(self, "vrOn", False): s_ = float(c @ n)                 # VR は血液が詰まって見えるので、パッチの真ん中で切る（パッチは切らずに出す）
        self._lockN = n.tolist(); self._lockPrev = "VIEW"
        self.setCut("LOCK", float(np.clip((dmax - s_) / max(dmax - dmin, 1e-6), 0, 1)))
        cn.ResetClippingRange(); self._view().forceRender(); self._syncCutUI()
        return True

    # ---------------------------------------------------------------- cut (clip node: 再計算なし・即時)
    def _clipNode(self):
        if self.clip is None or not slicer.mrmlScene.IsNodePresent(self.clip):
            self.clip = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLClipNode", "CV clip")
            self.clip.SetClipType(self.clip.ClipIntersection)
            try: self.clip.SetClippingMethod(self.clip.WholeCells)   # Straight だと頂点色（内膜/外膜）が消える
            except Exception: pass
            self._put(self.clip)
        return self.clip

    def _applyClipToModels(self, enable):
        clip = self._clipNode()
        for n in self.layerModels.values():
            d = n.GetDisplayNode() if n else None
            if not d: continue
            if enable:
                d.SetAndObserveClipNodeID(clip.GetID()); d.SetAttribute("CV.clipWant", "1")
                isVessel = n.GetName().startswith("CV 血管")
                isWall = n.GetName() in ("CV 心臓壁", "CV 心筋")
                cap = (isWall and getattr(self, "capWall", True)) or (isVessel and getattr(self, "capBlood", False))
                if n.GetName() == "CV 心臓壁" and self.layerModels.get("心筋") is not None:
                    cap = False
                if n.GetName() == "CV 心筋":
                    cap = False   # Slicer 標準の蓋は穴（内腔）まで塗ってしまうので、自前の断面（updateMyoCap）を使う
                d.SetAttribute("CV.cap", "1" if cap else "0")
                try:
                    d.SetClippingCapSurface(bool(cap)); d.SetClippingCapOpacity(getattr(self, "capOpacity", 0.5) if isWall else 1.0); d.SetClippingOutline(False)
                    if n.GetName() == "CV 心臓壁": d.SetClippingCapColorHSVOffset(-0.04, 0.30, -0.25)
                    if n.GetName() == "CV 心筋": d.SetClippingCapColorHSVOffset(0.0, 0.0, 0.0)   # 切り口は濃いアンバー（切った心筋）
                except Exception: pass
            else:
                d.SetAttribute("CV.clipWant", "0"); d.SetClipping(False)
        lay = set(n for n in self.layerModels.values() if n is not None)
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):             # ほかの画面の面（大動脈サイジング・研究・読み込んだ面）も、見えていれば一緒に切る
            if n in lay: continue
            d = n.GetDisplayNode(); nm = n.GetName()
            if d is None or nm == "CV 心筋断面" or nm.endswith("Volume Slice"): continue
            if enable:
                if d.GetVisibility():
                    d.SetAndObserveClipNodeID(clip.GetID()); d.SetClipping(True); d.SetAttribute("CV.clipOther", "1")
            elif d.GetAttribute("CV.clipOther") == "1":
                d.SetClipping(False); d.SetAttribute("CV.clipOther", "0")
        self._installVRClip()
        try: self._clipSync()
        except Exception as e: print("clip sync:", e)
        self._view().scheduleRender()

    def setCut(self, axis, frac):
        """axis: None=切らない, 0=x(左右), 1=y(前後), 2=z(上下). frac: 0..1"""
        self.cutAxis = axis; self.cutFrac = frac
        if axis is None:
            self._clearCuts(); return
        vb = self._visibleBounds() if hasattr(self, "_visibleBounds") else self.bounds
        if vb is None: return
        lo, hi = vb
        if axis in ("VIEW", "LOCK"):
            # 画面の正面から: 法線＝カメラの視線方向。0% で何も切らず、100% で全部切る
            # LOCK: 決めた断面を体に固定（回しても切り口はそのまま）
            if axis == "LOCK" and getattr(self, "_lockN", None) is not None: n = np.array(self._lockN, float)
            else: n = np.array(self._camera().GetCamera().GetViewPlaneNormal(), float)
            n /= np.linalg.norm(n)
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            proj = corners @ n; dmin, dmax = proj.min(), proj.max()
            c = (lo + hi) / 2.0
            c = c + n * ((dmax - frac * (dmax - dmin)) - float(c @ n))
        else:
            c = (lo + hi) / 2.0
            c[axis] = lo[axis] + frac * (hi[axis] - lo[axis])
            n = np.zeros(3); n[axis] = 1.0
        if self.cutPlane is None or not slicer.mrmlScene.IsNodePresent(self.cutPlane):
            self.cutPlane = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "切断面")
            try: self.cutPlane.SetSizeMode(self.cutPlane.SizeModeAbsolute)
            except Exception: pass
            self.cutPlane.SetSize(600, 600)
            self.cutPlane.GetDisplayNode().SetVisibility(False)
            self._put(self.cutPlane)
        wm = self.cutPlane.StartModify()
        self.cutPlane.SetCenter(*c); self.cutPlane.SetNormal(*n)
        self.cutPlane.EndModify(wm)
        clip = self._clipNode()
        if not clip.HasClippingNodeID(self.cutPlane.GetID()):
            clip.AddAndObserveClippingNodeID(self.cutPlane.GetID())
        # 実測: ClipNegativeSpace で法線側（カメラ側）が取り除かれる
        state = clip.ClipNegativeSpace if self.cutSign > 0 else clip.ClipPositiveSpace
        clip.SetClippingNodeState(self.cutPlane, state)
        self._applyClipToModels(True)
        self.updateMyoCap()
        self._ensureViewObserver()
        self.installMouse()
        self._syncCutSlice()
        if getattr(self, "inset", None) is not None and self.inset.pd is not None: self._insetPlane()
        elif getattr(self, "insetOn", True) and getattr(self, "bounds", None) is not None: self.updateInset()
        self._view().scheduleRender()

    INSET_SKIP = ("CV 軟部組織", "CV 骨", "CV 胸骨ワイヤー")

    def updateInset(self):
        """左下の全体図を作り直す（モデルを作った後に呼ぶ）"""
        if not getattr(self, "insetOn", True): return
        try:
            ins = getattr(self, "inset", None)
            if ins is None or getattr(slicer, "_cvInset", None) is not ins: ins = self.inset = _Inset(self._view())
            nodes = [n for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith("CV ") and n.GetName() not in self.INSET_SKIP
                     and n.GetDisplayNode() is not None and n.GetDisplayNode().GetVisibility()]
            if not nodes: nodes = [n for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith(("CV 心臓壁", "CV 血管"))]
            ins.setModels(nodes); ins.followCamera(self._camera()); ins.setVisible(True); ins._autoHidden = False
            self._lastSize = None                                             # 画面が狭ければ次の描画でまた隠す
            self._insetPlane()
        except Exception as e: print("inset:", e)

    def _insetPlane(self):
        ins = getattr(self, "inset", None)
        if ins is None: return
        if self.cutAxis is None or self.cutPlane is None: ins.hidePlane()
        else: ins.setPlane(self.cutPlane.GetCenter(), self.cutPlane.GetNormal())

    def setInsetVisible(self, on):
        self.insetOn = bool(on)
        if on: self.updateInset()
        elif getattr(self, "inset", None) is not None: self.inset.setVisible(False)

    def lockCut(self, on):
        """今の切断面を体に固定する（回転しても切り口が動かない）。戻り値: 固定できたか"""
        if on:
            if self.cutAxis is None or self.cutPlane is None: return False
            if self.cutAxis == "LOCK": return True
            n = np.array(self.cutPlane.GetNormal(), float); n /= np.linalg.norm(n)
            c = np.array(self.cutPlane.GetCenter(), float)
            lo, hi = self._visibleBounds() if hasattr(self, "_visibleBounds") else self.bounds
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            proj = corners @ n; dmin, dmax = proj.min(), proj.max()
            self._lockN = n.tolist(); self._lockPrev = self.cutAxis
            self.setCut("LOCK", float(np.clip((dmax - c @ n) / max(dmax - dmin, 1e-6), 0, 1))); self._syncCutUI()
            return True
        if self.cutAxis == "LOCK":
            prev = getattr(self, "_lockPrev", "VIEW"); self._lockN = None
            self.setCut(prev if prev != "LOCK" else "VIEW", getattr(self, "cutFrac", 0.5)); self._syncCutUI()
        return False

    def _ensureViewObserver(self):
        """回転が終わったら「画面の正面から」の切断面を追従させる（アプリ全体で 1 つ。今のロジックへ届ける）"""
        try:
            inter = self._view().interactor()
            reg = getattr(slicer, "_cvViewObs", None)
            if reg and reg[0] is inter: return
            if reg:
                try: reg[0].RemoveObserver(reg[1])
                except Exception: pass
            def cb(c=None, e=None):
                L = _cvCur()
                if L is not None:
                    try: L._onViewInteractionEnd()
                    except Exception as ex: print("view end:", ex)
            slicer._cvViewObs = (inter, inter.AddObserver(vtk.vtkCommand.EndInteractionEvent, cb))
        except Exception as e:
            print("observer:", e)

    def _onViewInteractionEnd(self, caller=None, event=None):
        if self.cutAxis == "VIEW" and not self.flying:
            self.setCut("VIEW", getattr(self, "cutFrac", 0.5))
        elif self.cutAxis is not None:
            self.updateMyoCap()   # 断面の陰影をカメラの向きに合わせ直す

    def nudgeCut(self, mm):
        if self.cutAxis is None or self.bounds is None: return None
        lo, hi = self._visibleBounds() if hasattr(self, "_visibleBounds") else self.bounds
        if self.cutAxis in ("VIEW", "LOCK"):
            n = np.array(self._lockN if self.cutAxis == "LOCK" else self._camera().GetCamera().GetViewPlaneNormal(), float); n /= np.linalg.norm(n)
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            proj = corners @ n; span = max(proj.max() - proj.min(), 1e-6)
            frac = float(np.clip(getattr(self, "cutFrac", 0.5) + mm / span, 0, 1))
        else:
            span = max(hi[self.cutAxis] - lo[self.cutAxis], 1e-6)
            frac = float(np.clip(getattr(self, "cutFrac", 0.5) + mm / span, 0, 1))
        self.setCut(self.cutAxis, frac); return frac

    def flipCut(self):
        self.cutSign *= -1.0
        clip = self._clipNode()
        if self.cutAxis is not None and self.cutPlane is not None:
            self.setCut(self.cutAxis, self.cutFrac)
        for p in self.planes:
            st = clip.GetClippingNodeState(p)
            clip.SetClippingNodeState(p, clip.ClipPositiveSpace if st == clip.ClipNegativeSpace else clip.ClipNegativeSpace)

    def addFreePlane(self):
        plane = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", f"自由切断面 {len(self.planes)+1}")
        c = self._sceneCenter()
        n = np.array(self._camera().GetCamera().GetViewPlaneNormal())
        plane.SetCenter(*c); plane.SetNormal(*(-n)); plane.SetSize(250, 250)
        try: plane.SetSizeMode(plane.SizeModeAbsolute)
        except Exception: pass
        dp = plane.GetDisplayNode()
        dp.SetHandlesInteractive(True); dp.SetTranslationHandleVisibility(True); dp.SetRotationHandleVisibility(True); dp.SetScaleHandleVisibility(False)
        dp.SetOpacity(0.12); dp.SetVisibility2D(False)
        self._put(plane); self.planes.append(plane)
        clip = self._clipNode()
        clip.AddAndObserveClippingNodeID(plane.GetID()); clip.SetClippingNodeState(plane, clip.ClipNegativeSpace)
        self._applyClipToModels(True)

    def removeFreePlanes(self):
        clip = self._clipNode()
        for p in self.planes:
            if clip.HasClippingNodeID(p.GetID()): clip.RemoveClippingNodeID(p.GetID())
            slicer.mrmlScene.RemoveNode(p)
        self.planes = []

    def _clearCuts(self):
        clip = self._clipNode()
        if self.cutPlane is not None and clip.HasClippingNodeID(self.cutPlane.GetID()):
            clip.RemoveClippingNodeID(self.cutPlane.GetID())
        if clip.GetNumberOfClippingNodes() == 0:
            self._applyClipToModels(False)
        self.updateMyoCap()
        self._insetPlane()

    # ---------------------------------------------------------------- VR（ボリュームレンダリング）: 心内構造を見る
    VR_MODES = {"tissue": "心内構造（弁・乳頭筋・中隔）", "blood": "造影（血液の鋳型）"}
    # 部屋ごとの色（左心系 = 暖色、右心系 = 寒色）。右心系は造影の目盛りも別に持つ
    VR_GROUPS = [("hc", ("left ventricle", "myocardium"), (0.88, 0.44, 0.40), "L"),
                 ("hc", ("left atrium",), (0.95, 0.62, 0.50), "L"),
                 ("hc", ("aorta",), (0.93, 0.30, 0.28), "L"),
                 ("tot", ("pulmonary vein",), (0.95, 0.55, 0.45), "L"),
                 ("tot", ("atrial appendage left",), (0.95, 0.62, 0.50), "L"),
                 ("hc", ("right ventricle",), (0.45, 0.58, 0.90), "R"),
                 ("hc", ("right atrium",), (0.58, 0.68, 0.93), "R"),
                 ("hc", ("pulmonary artery",), (0.42, 0.50, 0.88), "R"),
                 ("tot", ("vena cava",), (0.50, 0.62, 0.92), "R")]
    VR_NEUTRAL = (0.88, 0.72, 0.62)

    def _gridNode(self, src, lo, hi, step):
        """src の一部（lo..hi, ijk = z,y,x）を step 倍の粗さで覆う空の参照ボリューム（ラベルの書き出し先）"""
        shp = [int(np.ceil((h - l) / step)) for l, h in zip(lo, hi)]
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "cv_vrgrid")
        img = vtk.vtkImageData(); img.SetDimensions(shp[2], shp[1], shp[0]); img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        node.SetAndObserveImageData(img)
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M)
        G = vtk.vtkMatrix4x4(); G.DeepCopy(M)
        o = [sum(M.GetElement(r, c) * v for c, v in enumerate((lo[2], lo[1], lo[0], 1))) for r in range(3)]
        for r in range(3):
            for c in range(3): G.SetElement(r, c, M.GetElement(r, c) * step)
            G.SetElement(r, 3, o[r])
        node.SetIJKToRASMatrix(G)
        return node, shp

    def _applyVRTints(self, rgb, src, lo, step):
        """VR の色に「範囲の色」を重ねる。self.vrTints = [dict(mask=配列 (z,y,x), ijkToRAS=4x4, color=(r,g,b)), ...]
        範囲の各点を VR の粗い格子へ写して塗る（範囲だけ計算するので速い）"""
        tints = list(getattr(self, "vrTints", None) or [])
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            tc = n.GetAttribute("CV.vrTint"); pd = n.GetPolyData()
            if not tc or pd is None or pd.GetNumberOfPoints() == 0: continue
            from vtk.util.numpy_support import vtk_to_numpy
            tints.append(dict(points=vtk_to_numpy(pd.GetPoints().GetData()).astype(float), color=tuple(float(x) for x in tc.split(","))))
        if not tints: return
        from scipy import ndimage
        S = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(S); Ms = slicer.util.arrayFromVTKMatrix(S)
        G = Ms @ np.array([[step, 0, 0, lo[2]], [0, step, 0, lo[1]], [0, 0, step, lo[0]], [0, 0, 0, 1.0]])   # 粗い格子 (i, j, k) → RAS
        Gi = np.linalg.inv(G); sh = rgb.shape[:3]
        for t in tints:
            if t.get("points") is not None:
                ras = np.c_[t["points"], np.ones(len(t["points"]))].T
            else:
                m = t.get("mask")
                if m is None or not m.any(): continue
                idx = np.argwhere(m)                                               # (z, y, x)
                ras = t["ijkToRAS"] @ np.c_[idx[:, ::-1], np.ones(len(idx))].T
            g = np.rint((Gi @ ras)[:3]).astype(int)                                  # (i, j, k)
            ok = (g[0] >= 0) & (g[0] < sh[2]) & (g[1] >= 0) & (g[1] < sh[1]) & (g[2] >= 0) & (g[2] < sh[0])
            hit = np.zeros(sh, bool); hit[g[2][ok], g[1][ok], g[0][ok]] = True
            hit = ndimage.binary_dilation(hit, iterations=1)
            rgb[hit] = np.array(t.get("color", (0.15, 0.85, 0.35)), np.float32)

    def setupVR(self, status=lambda m: None):
        """心臓まわりだけ切り出した元の CT を、部屋ごとに色分け・造影の目盛りをそろえた RGBA の VR にする"""
        from scipy import ndimage
        src = getattr(self, "sourceVolume", None)
        seg = self._findSegmentation(); hc = self._findChambers()
        if src is None or seg is None: raise RuntimeError("先に「3D を自動で作る」を行ってください")
        status("VR を準備中（心臓まわりの切り出し・色分け）…")
        vkeys = ("atrial appendage", "aorta", "pulmonary vein", "vena cava", "pulmonary artery", "brachiocephalic trunk")
        region = self._segmentMaskArray(seg, src, vkeys)
        h2 = self._segmentMaskArray(hc, src, ("ventricle", "atrium", "aorta", "pulmonary artery", "myocardium")) if hc is not None else None
        if h2 is None: h2 = self._segmentMaskArray(seg, src, ("heart",))     # 心腔ラベルが無いときだけ全身ラベル（3mm）
        if h2 is not None: region = h2 if region is None else (region | h2)
        if region is None or region.sum() < 1000: raise RuntimeError("心臓のラベルがありません")
        sp = np.array(src.GetSpacing())[::-1]                       # (z, y, x) mm
        rr = [np.nonzero(region.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
        m = np.ceil(10.0 / sp).astype(int)
        lo = np.maximum(np.array([q.min() for q in rr]) - m, 0); hi = np.minimum(np.array([q.max() for q in rr]) + m + 1, region.shape)
        crop = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi)); full = tuple(int(b - a) for a, b in zip(lo, hi))
        # 重い計算（距離・ぼかし）は 2 倍粗い格子で行う。弱い GPU（ds=2）はその格子のまま VR にする（細かくしてから粗くする無駄をしない）
        ds = self._vrDownFactor()
        if ds == 1 and float(np.prod(full)) > 30e6: ds = 2          # 細かすぎる CT（0.3mm 級）をそのまま VR にすると GPU/メモリが足りず落ちる（実測）→ 0.6〜0.8mm で十分
        self.vrDownUsed = ds
        step = 2; gsp = sp * step
        cs = tuple(slice(int(a), int(b), step) for a, b in zip(lo, hi))
        grid, gshape = self._gridNode(src, lo, hi, step)
        try:
            status("VR を準備中（縁をなめらかに）…")
            # 切り出しの縁は「ばっさり」ではなく 3mm かけて薄くする（縁が段々・細かい線にならない）
            rs = ndimage.gaussian_filter(region[cs].astype(np.float32), 2.5 / gsp) > 0.5   # ラベルの段々（スライス方向）を丸める
            del region
            dreg = ndimage.distance_transform_edt(~rs, sampling=gsp)
            wgt = np.clip((8.0 - dreg) / 3.0, 0.0, 1.0).astype(np.float32)    # 5mm までは 1、8mm で 0（ゆっくり消す）
            wgt = ndimage.gaussian_filter(wgt, 1.0 / gsp)
            del dreg, rs
            bone = self._boneMaskArray(seg, grid)
            if bone is not None and bone.any():
                db = ndimage.distance_transform_edt(~bone, sampling=gsp)
                wgt *= np.clip((db - 1.0) / 2.0, 0.0, 1.0); del db               # 骨の 1〜3mm でなめらかに消す
            del bone
            # ---- 部屋ラベル（粗い格子）
            status("VR を準備中（部屋の色分け）…")
            lab = np.zeros(gshape, np.int8)
            for gi, (which, gkeys, col, side) in enumerate(self.VR_GROUPS, start=1):
                node = hc if which == "hc" else seg
                if node is None: continue
                mk = self._segmentMaskArray(node, grid, gkeys)
                if mk is not None: lab[(lab == 0) & mk] = gi
        finally:
            slicer.mrmlScene.RemoveNode(grid)
        c = dict(self._cal())
        if "myo" not in c or "blood" not in c:                   # 古い症例など: 心筋・血液の CT 値をラベルから測る
            try:
                hu0 = slicer.util.arrayFromVolume(src)[crop]
                g2, _ = self._gridNode(src, lo, hi, 1)
                def med(node, keys):
                    mk = self._segmentMaskArray(node, g2, keys) if node is not None else None
                    if mk is None or mk.sum() < 200: return None
                    from scipy import ndimage as _nd
                    mk2 = _nd.binary_erosion(mk, iterations=1); mk = mk2 if mk2.sum() > 100 else mk
                    return float(np.median(hu0[mk]))
                vm = med(hc, ("myocardium",)); vb = med(hc, ("left ventricle",)) or med(seg, ("aorta",)); vr = med(hc, ("right ventricle",))
                slicer.mrmlScene.RemoveNode(g2)
                if vm is not None: c["myo"] = vm
                if vb is not None: c["blood"] = vb
                if vr is not None: c["rv"] = vr
                if "fat" not in c: c["fat"] = -80.0
                self._calVR = c; print("VR 用に CT 値を測定:", {k: round(v) for k, v in c.items() if isinstance(v, float)})
            except Exception as e: print("VR calib:", e)
        myo = float(c.get("myo", 80.0)); bL = float(c.get("blood", 350.0)); bR = float(c.get("rv", bL))
        bR = max(bR, myo + 25.0)
        cols = np.array([self.VR_NEUTRAL] + [g[2] for g in self.VR_GROUPS], np.float32)
        isR = np.array([False] + [g[3] == "R" for g in self.VR_GROUPS])
        if (lab > 0).any():
            dist, ind = ndimage.distance_transform_edt(lab == 0, sampling=gsp, return_indices=True)
            near = lab[tuple(ind)]; near[dist > 15.0] = 0; del dist, ind
        else:
            near = lab
        rgb = cols[near]                                              # (z, y, x, 3)
        for k in range(3): rgb[..., k] = ndimage.gaussian_filter(rgb[..., k], 1.5 / gsp)   # 境目をぼかす
        try: self._applyVRTints(rgb, src, lo, step)                       # 部屋の色の上に、決めた範囲（パッチなど）を別の色で塗る（ぼかした後: 白が薄まらないように）
        except Exception as e: print("VR tint:", e)
        bloc = np.where(isR[near], bR, bL).astype(np.float32)
        bloc = ndimage.gaussian_filter(bloc, 4.0 / gsp)               # 左右の目盛りを 4mm かけてつなぐ
        del near, lab
        status("VR を準備中（造影の目盛り）…")
        s0 = float(getattr(self, "vrSigma", 0.7))
        sig_mm = np.array([max(s0, 0.4 * sp[0]), s0, s0])                  # スライスが厚いほど z を強めにならす（5mm → 2mm）
        hu = slicer.util.arrayFromVolume(src)[crop].astype(np.float32)
        hu = ndimage.gaussian_filter(hu, sigma=sig_mm / sp)                 # ノイズ（細かい線・ザラつき）と段差を抑える（細かい格子で＝折り返しが出ない）
        if ds == step:
            hu = hu[::step, ::step, ::step]                                # 粗い格子のまま使う
            if hu.shape != rgb.shape[:3]: hu = hu[:rgb.shape[0], :rgb.shape[1], :rgb.shape[2]]
        else:
            ds = 1; self.vrDownUsed = 1
            def up2(a):                                                    # 2 倍に直線補間（scipy の zoom より 10 倍速く、メモリも少ない）
                for ax in range(3):
                    n = a.shape[ax]
                    b = np.empty(a.shape[:ax] + (2 * n,) + a.shape[ax + 1:], np.float32)
                    i0 = [slice(None)] * 3; i1 = [slice(None)] * 3; i0[ax] = slice(0, None, 2); i1[ax] = slice(1, None, 2)
                    b[tuple(i0)] = a
                    lo_ = [slice(None)] * 3; hi_ = [slice(None)] * 3; lo_[ax] = slice(0, n - 1); hi_[ax] = slice(1, n)
                    o1 = [slice(None)] * 3; o1[ax] = slice(1, 2 * n - 2, 2)
                    b[tuple(o1)] = (a[tuple(lo_)] + a[tuple(hi_)]) * 0.5
                    last = [slice(None)] * 3; last[ax] = slice(2 * n - 1, 2 * n); src_ = [slice(None)] * 3; src_[ax] = slice(n - 1, n)
                    b[tuple(last)] = a[tuple(src_)]
                    a = b; del b
                return a[:full[0], :full[1], :full[2]]
            out = np.empty(full + (4,), np.uint8)
            for k in range(3):                                             # 色は 1 色ずつ（大きな配列を同時に持たない）
                out[..., k] = np.clip(up2(rgb[..., k]) * 255.0, 0, 255).astype(np.uint8)
            del rgb
            bloc = up2(bloc); wgt = up2(wgt)
            t = (hu - myo) / np.maximum(bloc - myo, 25.0); del hu, bloc
            t = np.clip(100.0 + 100.0 * t, 0, 255); t *= wgt; del wgt   # 縁では値を下げて透明へ（なめらか）
            out[..., 3] = t.astype(np.uint8); del t
        if ds == step:
            t = (hu - myo) / np.maximum(bloc - myo, 25.0)
            v = np.clip(100.0 + 100.0 * t, 0, 255) * wgt                     # 縁では値を下げて透明へ（なめらか）
            out = np.empty(hu.shape + (4,), np.uint8)
            out[..., :3] = np.clip(rgb * 255.0, 0, 255).astype(np.uint8); out[..., 3] = v.astype(np.uint8)
            del hu, t, v, rgb, bloc, wgt
        spz = sp[0] * ds
        zf = int(round(sp[0] / (1.0 * ds))) if sp[0] > 1.5 else 1      # 厚いスライス（2〜5mm）は z を 1mm（粗い格子は 2mm）に曲線補間（板状の段差を消す）
        if zf > 1:
            nz = out.shape[0]
            vz = ndimage.zoom(out[..., 3].astype(np.float32), (zf, 1, 1), order=3)
            rgbz = ndimage.zoom(out[..., :3], (zf, 1, 1, 1), order=1)
            out = np.concatenate([rgbz, np.clip(vz, 0, 255).astype(np.uint8)[..., None]], axis=-1); del vz, rgbz
            zscale = (nz - 1) / max(out.shape[0] - 1, 1)                  # 新しい z 間隔 = 元 × zscale
        else:
            zscale = 1.0
        node = slicer.mrmlScene.GetFirstNodeByName("CV VR")
        if node is not None and not node.IsA("vtkMRMLVectorVolumeNode"):
            slicer.mrmlScene.RemoveNode(node); node = None
        if node is None:
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "CV VR"); self._put(node)
        slicer.util.updateVolumeFromArray(node, out)
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M)
        o = [sum(M.GetElement(r, cc) * vv for cc, vv in enumerate((lo[2], lo[1], lo[0], 1))) for r in range(3)]
        for r in range(3): M.SetElement(r, 3, o[r]); M.SetElement(r, 2, M.GetElement(r, 2) * zscale)
        if ds > 1:
            for r in range(3):
                for cc in range(3): M.SetElement(r, cc, M.GetElement(r, cc) * ds)
        node.SetIJKToRASMatrix(M)
        vrl = slicer.modules.volumerendering.logic()
        dn = vrl.GetFirstVolumeRenderingDisplayNode(node) or vrl.CreateDefaultVolumeRenderingNodes(node)
        dn.SetVisibility(False)
        try:
            vn = self._viewNode()
            # 最初は安全な「標準」画質（弱い GPU で最高画質をいきなり描くと 2 秒を超えて Windows が GPU をリセットし、強制終了になる）
            vn.SetVolumeRenderingQuality(1)
            vn.SetVolumeRenderingOversamplingFactor(1.0); vn.SetVolumeRenderingSurfaceSmoothing(True)
        except Exception as e: print("VR quality:", e)
        try:
            # VR の切断は GPU の「切り取り面」で行う。Slicer 標準の切り取り（ClipNode）は面を動かすたびに
            # ボリューム全体を CPU で塗りつぶして GPU に送り直すので、1 コマ 0.7 秒（開発 PC）〜数秒かかっていた
            dn.SetClipping(False)
        except Exception as e: print("VR clip:", e)
        self._installVRClip()
        self.vrNode, self.vrDisplay = node, dn
        self.vrScale = (myo, bL)                                     # 表示用: 目盛り → 左心系の HU 相当
        if getattr(self, "vrMode", None) is None: self.vrMode = "tissue"
        self.vrWin = None
        self.setVRWindow()
        status("VR の準備ができました")
        return dn

    def _installVRClip(self):
        """3D 画面を描く直前に、切断面（と自由切断面）を VR の GPU 切り取り面へ写す（アプリ全体で 1 つ）"""
        try:
            rw = self._view().renderWindow()
            reg = getattr(slicer, "_cvVRClip", None)
            if reg and reg[0] is rw: return
            if reg:
                try: reg[0].RemoveObserver(reg[1])
                except Exception: pass
            def cb(c=None, e=None):
                L = _cvCur()
                if L is not None:
                    try: L._clipSync()
                    except Exception as ex: print("clip sync:", ex)
            slicer._cvVRClip = (rw, rw.AddObserver(vtk.vtkCommand.StartEvent, cb))
        except Exception as e: print("vr clip install:", e)

    def _activePlanes(self):
        """いま効いている切断面: [(中心, 残す側の法線)]"""
        planes = []
        clip = self.clip if (self.clip is not None and slicer.mrmlScene.IsNodePresent(self.clip)) else None
        if clip is None: return planes, None
        for i in range(clip.GetNumberOfClippingNodes()):
            nd = slicer.mrmlScene.GetNodeByID(clip.GetNthClippingNodeID(i))
            if nd is None or not hasattr(nd, "GetNormal"): continue
            st = clip.GetClippingNodeState(nd)
            if st == clip.ClipOff: continue
            c = [0.0, 0.0, 0.0]; n = [0.0, 0.0, 1.0]
            try: nd.GetOriginWorld(c)
            except Exception: c = list(nd.GetCenter())
            try: nd.GetNormalWorld(n)
            except Exception: n = list(nd.GetNormal())
            sgn = -1.0 if st == clip.ClipNegativeSpace else 1.0           # ClipNegativeSpace = 法線側を取り除く（実測）→ 残すのは逆側
            planes.append((tuple(round(x, 3) for x in c), tuple(round(sgn * x, 5) for x in n)))
        return planes, clip

    def _noPlanes(self):
        e = getattr(self, "_emptyPlanes", None)                  # 空の入れ物（None を渡すと vtk の引数が曖昧でエラーになる）
        if e is None: e = self._emptyPlanes = vtk.vtkPlaneCollection()
        return e

    def _planeColl(self, attr, planes):
        coll = getattr(self, attr, None)
        if coll is None: coll = vtk.vtkPlaneCollection(); setattr(self, attr, coll)
        key = tuple(planes)
        if getattr(self, attr + "Key", None) != key or coll.GetNumberOfItems() != len(planes):
            coll.RemoveAllItems()
            for c, n in planes:
                pl = vtk.vtkPlane(); pl.SetOrigin(*c); pl.SetNormal(*n); coll.AddItem(pl)
            setattr(self, attr + "Key", key)
        return coll

    def _clipSync(self):
        """切断面 1 枚の時は、VR も面も GPU の「切り取り面」で切る（面を動かしても CPU で作り直さない＝なめらか）。
        2 枚以上（自由切断面を足した時）は Slicer 標準（交わった所だけ切る）に任せる。切り口の蓋を塗るレイヤーも Slicer 標準"""
        planes, clip = self._activePlanes()
        gpu = len(planes) == 1
        # ---- VR
        dn = getattr(self, "vrDisplay", None)
        if dn is not None and getattr(self, "vrOn", False):
            m = self._vrMapper()
            if gpu or not planes:
                if dn.GetClipping(): dn.SetClipping(False)
                if m is not None:
                    if planes:
                        coll = self._planeColl("_vrPlanes", planes)
                        if m.GetClippingPlanes() is not coll: m.SetClippingPlanes(coll)
                    elif m.GetClippingPlanes() is not None and m.GetClippingPlanes().GetNumberOfItems(): m.SetClippingPlanes(self._noPlanes())
            else:
                if m is not None and m.GetClippingPlanes() is not None and m.GetClippingPlanes().GetNumberOfItems(): m.SetClippingPlanes(self._noPlanes())
                if clip is not None and not dn.GetClipping():
                    dn.SetAndObserveClipNodeID(clip.GetID()); dn.SetClipping(True)
        # ---- 4D の VR（1 枚なら GPU で切る）
        d4 = getattr(self, "vr4D", None)
        if d4 is not None and getattr(self, "on4D", False):
            m4 = self._mapperOf(d4)
            if gpu or not planes:
                if d4.GetClipping(): d4.SetClipping(False)
                if m4 is not None:
                    want = self._planeColl("_vr4Planes", planes) if planes else self._noPlanes()
                    if m4.GetClippingPlanes() is not want: m4.SetClippingPlanes(want)
            elif clip is not None:
                if m4 is not None: m4.SetClippingPlanes(self._noPlanes())
                if not d4.GetClipping(): d4.SetAndObserveClipNodeID(clip.GetID()); d4.SetClipping(True)
        # ---- 面のレイヤー
        try: dm = self._view().displayableManagerByClassName("vtkMRMLModelDisplayableManager")
        except Exception: dm = None
        coll = self._planeColl("_mdPlanes", planes) if gpu else None
        pn = self.layerModels.get(self.PATCH_KEY) if getattr(self, "vrOn", False) else None
        for n in list(self.layerModels.values()):
            d = n.GetDisplayNode() if n else None
            if d is None: continue
            want = d.GetAttribute("CV.clipWant") == "1" and bool(planes) and n is not pn   # VR の時、パッチは切らずに切り口の上に出す
            useGpu = want and gpu and d.GetAttribute("CV.cap") != "1"
            slicerClip = want and not useGpu
            if bool(d.GetClipping()) != slicerClip: d.SetClipping(slicerClip)
            a = dm.GetActorByID(d.GetID()) if dm is not None else None
            mp = a.GetMapper() if a is not None else None
            if mp is None: continue
            if useGpu:
                if mp.GetClippingPlanes() is not coll: mp.SetClippingPlanes(coll)
            elif mp.GetClippingPlanes() is not None and mp.GetClippingPlanes().GetNumberOfItems():
                mp.SetClippingPlanes(self._noPlanes())

    def _vrDefaults(self, mode):
        c = getattr(self, "_calVR", None) or self._cal(); myo = float(c.get("myo", 80.0)); fat = float(c.get("fat", -80.0)); bL = float(c.get("blood", 350.0))
        vfat = 100.0 + 100.0 * (fat - myo) / max(bL - myo, 25.0)
        if mode == "blood": return 150.0, 60.0                        # 心筋と血液の中間から上を不透明に
        a = (vfat + 100.0) / 2.0; b = 150.0                           # 脂肪と心筋の中間 〜 心筋と血液の中間
        return (a + b) / 2.0, b - a

    def _vrHU(self, v):
        myo, bL = getattr(self, "vrScale", (80.0, 350.0))
        return myo + (v - 100.0) / 100.0 * (bL - myo)

    def resetWindow(self):
        """ウィンドウを最初の値に戻す: VR は部屋ごとの標準、断面は心臓用（脂肪〜造影血液が見える幅）"""
        if getattr(self, "vrDisplay", None) is not None:
            self.vrWin = None; self.setVRWindow()
        if getattr(self, "on4D", False):
            self.win4DMap = {}; self._tf4D()
            try:
                d = self.proxy4D.GetDisplayNode(); c = self._cal(); lo = float(c.get("fat", -80)) - 60; hi = float(c.get("blood", 350)) + 250
                d.SetAutoWindowLevel(False); d.SetWindowLevel(hi - lo, (hi + lo) / 2)
            except Exception: pass
        src = getattr(self, "sourceVolume", None)
        d = src.GetDisplayNode() if src is not None else None
        if d is not None:
            try:
                c = self._cal(); lo = float(c.get("fat", -80)) - 60; hi = float(c.get("blood", 350)) + 250
                d.SetAutoWindowLevel(False); d.SetWindowLevel(hi - lo, (hi + lo) / 2)
            except Exception: d.SetAutoWindowLevel(True)
        try: self._vrLabel()
        except Exception: pass
        self._view().scheduleRender()

    def setVRWindow(self, center=None, width=None):
        dn = getattr(self, "vrDisplay", None)
        if dn is None: return
        mode = getattr(self, "vrMode", "tissue")
        if self.vrWin is None: self.vrWin = self._vrDefaults(mode)
        c0, w0 = self.vrWin
        c0 = c0 if center is None else float(center); w0 = max(6.0, w0 if width is None else float(width))
        self.vrWin = (c0, w0)
        vp = dn.GetVolumePropertyNode().GetVolumeProperty()
        a, b = c0 - w0 / 2, c0 + w0 / 2; e = max(3.0, 0.15 * w0)
        if mode == "blood": pts = [(0, 0), (max(1, a), 0), (min(254, b), 0.85), (255, 0.9)]
        else: pts = [(0, 0), (max(1, a - e), 0), (a + e, 0.8), (b - e, 0.8), (min(254, b + e), 0), (255, 0)]
        xs = []                                                   # x が重なると点が減るので、必ず少しずつ増やす
        for x, y in pts: xs.append(max(float(x), xs[-1] + 0.01) if xs else float(x))
        pts = [(x, y) for x, (_, y) in zip(xs, pts)]
        otf = vp.GetScalarOpacity()
        if getattr(self, "_vrOtfProp", None) is vp and getattr(self, "_vrOtfMode", None) == mode and otf is not None and otf.GetSize() == len(pts):
            # ドラッグ中は今ある関数の点だけ動かす（作り直すと描画のしくみごと作り直しになり 3 倍重い）
            for i, (x, y) in enumerate(pts): otf.SetNodeValue(i, [x, y, 0.5, 0.0])
        else:
            vp.IndependentComponentsOff()
            otf = vtk.vtkPiecewiseFunction()
            for x, y in pts: otf.AddPoint(x, y)
            vp.SetScalarOpacity(otf)
            vp.ShadeOn(); vp.SetInterpolationTypeToLinear()
            sh = self._shade(); vp.SetAmbient(sh["vamb"]); vp.SetDiffuse(sh["vdif"]); vp.SetSpecular(sh["vspec"]); vp.SetSpecularPower(25)   # 陰影の設定どおり
            self._vrOtfProp, self._vrOtfMode = vp, mode
        self._vrLabel()

    def _vrLabel(self):
        if getattr(self, "on4D", False): return                               # 4D の時は 4D のウィンドウを出している
        try:
            v = self._view(); ca = v.cornerAnnotation()
            if getattr(self, "vrOn", False) and self.vrWin is not None:
                c0, w0 = self.vrWin
                lo, hi = self._vrHU(c0 - w0 / 2), self._vrHU(c0 + w0 / 2)
                self._setUR(f"<b>VR</b>　W {hi - lo:.0f} / L {(lo + hi) / 2:.0f}\n<span style='color:#9aa3ad'>{lo:.0f} – {hi:.0f} HU</span>")
            else: self._setUR("")
            ca.GetTextProperty().SetColor(1, 0.9, 0.5); v.scheduleRender()
        except Exception: pass

    def showVR(self, on, mode=None):
        first = on and getattr(self, "vrDisplay", None) is None
        if first:                                                             # 初めての VR で Slicer がカメラを戻してしまうので、今の向き・大きさを保つ
            c = self._camera(); st = (c.GetPosition(), c.GetFocalPoint(), c.GetViewUp(), c.GetParallelScale())
            self.setupVR()
            def _back(c=c, st=st):
                try: c.SetPosition(*st[0]); c.SetFocalPoint(*st[1]); c.SetViewUp(*st[2]); c.SetParallelScale(st[3]); c.ResetClippingRange()
                except Exception: pass
            _back(); qt.QTimer.singleShot(0, _back); qt.QTimer.singleShot(150, _back)
        if mode is not None and mode != getattr(self, "vrMode", None):
            self.vrMode = mode; self.vrWin = None; self.setVRWindow()
        self.vrOn = bool(on)
        if getattr(self, "vrDisplay", None) is not None: self.vrDisplay.SetVisibility(self.vrOn)
        if self.vrOn:
            self._vrSaved = {k: self.visible.get(k, False) for k in self.layerModels}
            keep = ("パッチ",)                                                # パッチは VR の中でも面で出す（VR は CT 値で透けるので、薄い布が見えなくなる）
            for k, n in self.layerModels.items():
                if n and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(bool(k in keep and self._vrSaved.get(k)))
            cap = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
            if cap and cap.GetDisplayNode(): cap.GetDisplayNode().SetVisibility(False)
        else:
            for k, vis in getattr(self, "_vrSaved", {}).items():
                n = self.layerModels.get(k)
                if n and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(vis)
            self.updateMyoCap()
        try:
            ren = self._view().renderWindow().GetRenderers().GetFirstRenderer(); vs = ren.GetVolumes(); vs.InitTraversal()
            for _ in range(vs.GetNumberOfItems()): vs.GetNextVolume().GetMapper().SetUseJittering(True)   # OFF だと木目状の細かい線が出る
        except Exception: pass
        try: self._applyVRShade()
        except Exception as e: print("VR shade:", e)
        if on and (first or getattr(self, "vrStillQ", None) is None):
            try: self._tuneVR()
            except Exception as e: print("tuneVR:", e)
        self.installMouse(); self._installPerfMon(); self._vrLabel(); self._view().forceRender()

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
        line = time.strftime("%Y-%m-%d %H:%M ") + (os.environ.get("COMPUTERNAME") or __import__("socket").gethostname()) + " " + json.dumps(rec, ensure_ascii=False) + "\n"
        for d in (os.path.expanduser("~"), self._nasLogDir()):
            if not d: continue
            try:
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "HUCViewS_performance.txt" if d == os.path.expanduser("~") else f"{os.environ.get('COMPUTERNAME') or __import__('socket').gethostname()}_performance.txt"), "a", encoding="utf-8") as f: f.write(line)
            except Exception: pass

    def _nasLogDir(self):
        try:
            hv = os.environ.get("HEARTVIEW_HOME")
            if not hv: return None
            src = open(os.path.join(os.path.dirname(hv), "update_source.txt"), encoding="utf-8-sig").read().strip()
            return os.path.join(src, "logs") if src and os.path.isdir(src) else None
        except Exception: return None

    WEAK_GPU = ("T400", "T600", "T1000", "P400", "P600", "P620", "P1000", "GT 7", "GT 10", "MX", "UHD", "IRIS", "QUADRO K")

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
        weak = any(k in name for k in self.WEAK_GPU) or (mem is not None and mem <= 4096)
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

    # ---------------------------------------------------------------- 一般的なビューアの機能: スケール・右ドラッグ切替・マルチビュー
    RMODES = [("zoom", "拡大"), ("window", "ウィンドウ"), ("pan", "移動"), ("cut", "切る位置")]

    def setScale(self, on=True):
        """3D を平行投影にして目盛りを出す（画面のどこでも同じ縮尺）。断面にも目盛り"""
        self.scaleOn = bool(on)
        vn = self._viewNode()
        vn.SetRenderMode(vn.Orthographic if on else vn.Perspective)
        vn.SetRulerType(vn.RulerTypeThin if on else vn.RulerTypeNone); vn.SetRulerColor(vn.RulerColorWhite)
        for sn in slicer.util.getNodesByClass("vtkMRMLSliceNode"):
            try: sn.SetRulerType(sn.RulerTypeThin if on else sn.RulerTypeNone); sn.SetRulerColor(sn.RulerColorWhite)
            except Exception: pass
        self._fitParallel(); self._view().forceRender()

    def _fitParallel(self, margin=1.08, recenter=False):
        """画面の縦横比を考えて、見えているもの全体を収める（細い画面でも横が切れない）。形の点を画面の向きに投影して測る"""
        vn = self._viewNode(); cam = self._camera().GetCamera()
        P = self._shownPoints()
        if P is None: return
        W, H = self._view().renderWindow().GetSize(); asp = (W / float(H)) if (W > 10 and H > 10) else 1.0
        fp = np.array(cam.GetFocalPoint()); p = np.array(cam.GetPosition()); dop = fp - p; dop = dop / (float(np.linalg.norm(dop)) or 1.0)
        up = np.array(cam.GetViewUp()); up = up - dop * np.dot(up, dop); up = up / (np.linalg.norm(up) or 1.0); rt = np.cross(dop, up)
        X = P - fp; u = X @ up; r = X @ rt
        if recenter:                                                           # 画面の真ん中へ（奥行き方向は動かさない）
            d = up * (u.max() + u.min()) / 2 + rt * (r.max() + r.min()) / 2; fp = fp + d; p = p + d
            cam.SetFocalPoint(*fp); cam.SetPosition(*p); u = u - (u.max() + u.min()) / 2; r = r - (r.max() + r.min()) / 2
        hu = float(np.max(np.abs(u))); hr = float(np.max(np.abs(r)))
        need = max(hu, hr / asp) * margin * (1.15 if getattr(self, "on4D", False) else 1.0)   # 4D は心臓のまわりも少し描くので余白を多めに
        if vn.GetRenderMode() == vn.Orthographic:
            cam.SetParallelScale(need)
        elif recenter:
            ang = math.radians(cam.GetViewAngle()); D = need / math.tan(ang / 2) + float(np.max(np.abs((P - fp) @ dop)))
            cam.SetPosition(*(fp - dop * D))
        try: self._view().renderWindow().GetRenderers().GetFirstRenderer().ResetCameraClippingRange()
        except Exception: pass
        self._lastSize = None

    def _shownPoints(self, maxPts=40000):
        """今 3D に出ている形の点（間引き）。隠した骨・軟部組織は入れない。VR・4D の時は心臓・血管"""
        from vtk.util.numpy_support import vtk_to_numpy
        vr = getattr(self, "vrOn", False) or getattr(self, "on4D", False); arrs = []
        heart = [k for k in self.layerModels if "心臓壁" in k] or [k for k in self.layerModels if not any(x in k for x in ("軟部", "骨", "人工物"))]
        for name, n in self.layerModels.items():                              # VR・4D は心臓のまわりだけを描くので、心臓の範囲で合わせる
            try:
                pd = n.GetPolyData() if n else None; d = n.GetDisplayNode() if n else None
                if pd is None or d is None or not pd.GetNumberOfPoints(): continue
                if (vr and name in heart) or (not vr and d.GetVisibility()): arrs.append(vtk_to_numpy(pd.GetPoints().GetData()))
            except Exception: pass
        if not arrs:
            vb = self._visibleBounds()
            if vb is None: return None
            lo, hi = vb; return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
        n = sum(len(a) for a in arrs); k = max(1, n // maxPts)
        return np.concatenate([a[::k] for a in arrs]).astype(float)

    def _shownBounds(self):
        """今 3D に出ているものの範囲（隠した骨・軟部組織は入れない。VR・4D の時は心臓・血管の範囲）"""
        B = []; vr = getattr(self, "vrOn", False) or getattr(self, "on4D", False)
        for name, n in self.layerModels.items():
            try:
                pd = n.GetPolyData() if n else None; d = n.GetDisplayNode() if n else None
                if pd is None or d is None or not pd.GetNumberOfPoints(): continue
                if d.GetVisibility() or (vr and not any(k in name for k in ("軟部", "骨", "人工物"))): B.append(pd.GetBounds())
            except Exception: pass
        if not B: return self._visibleBounds()
        A = np.array(B); return (A[:, 0::2].min(0), A[:, 1::2].max(0))

    def _setUL(self, key, text):
        """左上の表示（4D の位相・一言メッセージ）をまとめて出す"""
        d = self.__dict__.setdefault("_ulTexts", {}); d[key] = text or ""
        _hud().set("3d", "tl", "<br>".join(t for k, t in sorted(d.items()) if t))
        try: self._view().cornerAnnotation().SetText(2, "")
        except Exception: pass

    def _setUR(self, text):
        """右上の表示（ウィンドウの値）"""
        _hud().set("3d", "tr", (text or "").replace("\n", "<br>"))
        try: self._view().cornerAnnotation().SetText(3, ""); self._view().scheduleRender()
        except Exception: pass

    SLICE_JA = {"Red": "軸位", "Yellow": "矢状断", "Green": "冠状断"}

    def applyWL(self, w, l):
        """断面のウィンドウを決まった値に（いま断面に出ている CT すべて）"""
        lm = slicer.app.layoutManager(); done = set()
        vols = [getattr(self, "sourceVolume", None)]
        for nm in lm.sliceViewNames():
            try:
                cn = lm.sliceWidget(nm).mrmlSliceCompositeNode(); vols.append(slicer.mrmlScene.GetNodeByID(cn.GetBackgroundVolumeID() or ""))
            except Exception: pass
        for v in vols:
            d = v.GetDisplayNode() if v is not None else None
            if d is None or d.GetID() in done: continue
            d.SetAutoWindowLevel(False); d.SetWindowLevel(float(w), float(l)); done.add(d.GetID())
        self._mprWL = True

    def _applyChrome(self):
        """断面の上の Slicer のバー（細かい数字・ピン）を隠し、日本語の小さな表示に置き換える"""
        lm = slicer.app.layoutManager()
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            if w is not None:
                try: w.sliceController().setVisible(False)
                except Exception: pass
        try: lm.threeDWidget(0).threeDController().setVisible(False)
        except Exception: pass
        try:                                                                  # 4D の再生は左のパネルで操作するので、Slicer の再生バーは隠す
            for t in slicer.util.mainWindow().findChildren(qt.QToolBar):
                if t.objectName == "SequenceBrowserToolBar": t.hide()
        except Exception: pass
        self._hudUpdate()

    def _hudUpdate(self):
        h = _hud(); lm = slicer.app.layoutManager(); kind = getattr(self, "layoutKind", "3d")
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            vis = w is not None and kind in ("four", "cut") and w.isVisible()
            if not vis:
                for pos in ("tl", "L", "R", "T", "B"): h.set(nm, pos, None)
                continue
            try:
                M = w.mrmlSliceNode().GetSliceToRAS()
                x = np.array([M.GetElement(i, 0) for i in range(3)]); y = np.array([M.GetElement(i, 1) for i in range(3)])
                name = "切断面" if (kind == "cut" and nm == "Red") else self.SLICE_JA[nm]
                if kind == "four" and (np.abs(x).max() < 0.995 or np.abs(y).max() < 0.995): name += "（斜め）"
                wl = ""
                cn = w.mrmlSliceCompositeNode(); vol = slicer.mrmlScene.GetNodeByID(cn.GetBackgroundVolumeID() or "")
                d = vol.GetDisplayNode() if vol is not None else None
                if d is not None: wl = f"　<span style='color:#9aa3ad'>W {d.GetWindow():.0f} / L {d.GetLevel():.0f}</span>"
                slab = getattr(self, "slabMM", 0) or 0
                if slab: wl += f"　<span style='color:#9aa3ad'>MIP {slab:g} mm</span>"
                h.set(nm, "tl", f"<b>{name}</b>{wl}")
                let = lambda v: ("RL", "AP", "SI")[int(np.argmax(np.abs(v)))][0 if v[int(np.argmax(np.abs(v)))] > 0 else 1]
                h.set(nm, "R", let(x)); h.set(nm, "L", let(-x)); h.set(nm, "T", let(y)); h.set(nm, "B", let(-y))
            except Exception as e: print("hud:", e)
        h.placeAll()


    def _viewSizeWatch(self):
        """3D 画面の大きさが変わったら（画面割り・パネルの開閉・ウィンドウの大きさ）: 細い向きの見える範囲を保ち、全体図と文字を画面に合わせる"""
        try: ren = self._view().renderWindow().GetRenderers().GetFirstRenderer()
        except Exception: return
        old = getattr(slicer, "_cvSizeTag", None)
        if old is not None:
            if old[0] is ren and old[2] is self: return
            try: old[0].RemoveObserver(old[1])
            except Exception: pass
        self._lastSize = None
        slicer._cvSizeTag = (ren, ren.AddObserver("StartEvent", self._onViewStart), self)

    def _onViewStart(self, caller=None, ev=None):
        try:
            v = self._view(); W, H = v.renderWindow().GetSize()
            if W < 20 or H < 20: return
            last = getattr(self, "_lastSize", None)
            if last == (W, H): return
            self._lastSize = (W, H)
            if last is not None:
                a0 = min(1.0, last[0] / float(last[1])); a1 = min(1.0, W / float(H))
                if abs(a0 - a1) > 1e-3:                                           # 細くなったら引いて、太くなったら戻す（横が切れない）
                    cam = self._camera().GetCamera(); f = a0 / a1
                    if cam.GetParallelProjection(): cam.SetParallelScale(cam.GetParallelScale() * f)
                    else:
                        fp = np.array(cam.GetFocalPoint()); p = np.array(cam.GetPosition()); cam.SetPosition(*(fp + (p - fp) * f))
                    caller.ResetCameraClippingRange()
            self._layoutOverlay(W, H)
        except Exception as e: print("view size:", e)

    def _layoutOverlay(self, W, H):
        v = self._view()
        try: dpr = max(1.0, W / float(max(1, v.width)))
        except Exception: dpr = 1.0
        ins = getattr(self, "inset", None)
        if ins is not None and getattr(slicer, "_cvInset", None) is ins:          # 全体図はピクセルで決めた大きさ（画面が狭いと出さない）
            w = min(0.26 * W, 220 * dpr); h = w / 1.35
            if h > 0.34 * H: h = 0.34 * H; w = h * 1.35
            m = 6 * dpr
            ins.ren.SetViewport(m / W, m / H, (m + w) / W, (m + h) / H)
            small = W < 330 * dpr or H < 240 * dpr
            if small:
                if ins.ren.GetDraw(): ins.ren.SetDraw(0); ins._autoHidden = True
            elif getattr(ins, "_autoHidden", False):
                ins._autoHidden = False
                if getattr(self, "insetOn", True): ins.ren.SetDraw(1)
        try:
            ca = v.cornerAnnotation(); ca.SetMaximumFontSize(int(13 * dpr)); ca.SetMinimumFontSize(0)   # 大きい画面でも文字が大きくなりすぎない（狭い画面では自動で小さく）
            ca.SetLinearFontScaleFactor(5); ca.SetNonlinearFontScaleFactor(0.35)
        except Exception: pass

    def setRightMode(self, mode):
        self.rmode = mode
        self._modeLabel()

    def _modeLabel(self):
        try:
            names = dict(self.RMODES); ca = self._view().cornerAnnotation()
            ca.SetText(1, "")
            self._setUL("2_rmode", "")                                          # 今の機能は上のバーで分かるので画面には出さない（すっきり）
        except Exception: pass

    def _pan(self, x0, y0, x1, y1, cam0):
        ren = self._view().renderWindow().GetRenderers().GetFirstRenderer()
        fp, pos = np.array(cam0[0]), np.array(cam0[1])
        ren.SetWorldPoint(*fp, 1.0); ren.WorldToDisplay(); z = ren.GetDisplayPoint()[2]
        def w(x, y):
            ren.SetDisplayPoint(x, y, z); ren.DisplayToWorld(); p = ren.GetWorldPoint(); return np.array(p[:3]) / (p[3] or 1.0)
        d = w(x0, y0) - w(x1, y1)
        cam = self._camera(); cam.SetFocalPoint(*(fp + d)); cam.SetPosition(*(pos + d))

    def setLayout(self, kind):
        """kind: "3d" / "four"（3D ＋ 軸位・矢状断・冠状断の MPR）/ "cut"（3D ＋ 切っている面の断面）"""
        lm = slicer.app.layoutManager(); self.layoutKind = kind; self._maxPrev = None
        src = getattr(self, "sourceVolume", None)
        try:                                                                  # 大動脈サイジングの線・マウス操作が残っていたら引っ込める
            if hasattr(slicer.modules, "aortasizing"): slicer.modules.aortasizing.widgetRepresentation().self().logic.suspend()
        except Exception: pass
        for nm in ("Red", "Yellow", "Green"):                                 # 3D に断面の板は出さない。4 画面だけ位置の枠線を出す（線は断面どうしの交線表示にも必要）
            try: lm.sliceWidget(nm).mrmlSliceNode().SetSliceVisible(kind == "four")
            except Exception: pass
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if n.GetName().endswith("Volume Slice") and n.GetDisplayNode() is not None:
                try: n.GetDisplayNode().SetVisibility3D(False)
                except Exception: pass
        if kind == "3d":
            lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
            try:
                ch = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode"); ch.SetCrosshairMode(ch.NoCrosshair)   # 3D だけの時は十字を出さない
            except Exception: pass
            self.setObliqueHandles(getattr(self, "obliqueOn", True))
        elif kind == "four":
            ln = lm.layoutLogic().GetLayoutNode()
            if not ln.IsLayoutDescription(CV_LAYOUT_FOUR): ln.AddLayoutDescription(CV_LAYOUT_FOUR, CV_LAYOUT_FOUR_XML)
            lm.setLayout(CV_LAYOUT_FOUR)
            self._equalSplit(); qt.QTimer.singleShot(120, self._equalSplit)        # 画面の大きさが決まってからもう一度そろえる
        else:
            ln = lm.layoutLogic().GetLayoutNode()
            if not ln.IsLayoutDescription(CV_LAYOUT_CUT): ln.AddLayoutDescription(CV_LAYOUT_CUT, CV_LAYOUT_CUT_XML)
            lm.setLayout(CV_LAYOUT_CUT)
        if kind != "3d" and src is not None:
            slicer.util.setSliceViewerLayers(background=src, foreground=None, label=None, fit=False)
            d = src.GetDisplayNode()
            if d is not None and not getattr(self, "_mprWL", False):
                c = self._cal(); lo = float(c.get("fat", -80)) - 60; hi = float(c.get("blood", 350)) + 250
                d.SetAutoWindowLevel(False); d.SetWindowLevel(hi - lo, (hi + lo) / 2); self._mprWL = True
            if kind == "four": self.resetMPR(render=False); qt.QTimer.singleShot(150, lambda: self.resetMPR())   # 画面割りが決まってから大きさをそろえる
            self.setOutlines2D(getattr(self, "outlines2D", False))
            for nm in ("Red", "Yellow", "Green"):
                w = lm.sliceWidget(nm)
                if w is not None: w.sliceController().setVisible(False)
            self._sliceInteraction(kind)
        try:                                                                  # 4 画面の 3D に 3 断面の交点（今細かく見ている所）
            mk = getattr(slicer, "_cvMprMark", None)
            if kind == "four" and (mk is None or mk.view is not self._view()): mk = _MprMark(self._view())
            if mk is not None: mk.show(kind == "four")
        except Exception as e: print("mpr mark:", e)
        self.setScale(getattr(self, "scaleOn", True))
        if kind == "cut":
            if self.cutAxis is None: self.setCut("VIEW", getattr(self, "cutFrac", 0.5)); self._syncCutUI()
            self._syncCutSlice()
            try:
                w = lm.sliceWidget("Red"); sn = w.mrmlSliceNode(); sn.SetFieldOfView(*self._cutFov(), 1.0)
            except Exception: pass
        reg = getattr(slicer, "_cvMouse", None)
        if reg: reg["v"] = 0                                                  # 断面ビューが増えたので付け直す
        self.installMouse(); self._installPerfMon()
        self._viewSizeWatch()
        qt.QTimer.singleShot(250, lambda: (self._fitParallel(recenter=True), self._view().scheduleRender(), self._hudUpdate()))

    def _cutFov(self):
        lo, hi = self._visibleBounds() if self.bounds is not None else (np.zeros(3), np.ones(3) * 200)
        r = float(np.max(hi - lo)) * 1.05; return r, r

    def _sliceInteraction(self, kind):
        """断面をふつうの DICOM ビューアと同じ操作に戻す（大動脈サイジングで止めた操作もここで戻す）。
        ホイール = スライス送り / 左ドラッグ = ウィンドウ / 右ドラッグ = 上で選んだ機能 / 中ドラッグ = 移動 / Shift＋マウス = 3 断面をその点へ"""
        lm = slicer.app.layoutManager()
        for nm in ("Red", "Yellow", "Green"):
            w = lm.sliceWidget(nm)
            if w is None: continue
            sv = w.sliceView(); io = sv.interactorObserver()
            for act in (io.BrowseSlice, io.AdjustWindowLevelBackground, io.AdjustWindowLevelForeground):
                try: io.SetActionEnabled(act, True)
                except Exception: pass
            try:
                siw = sv.displayableManagerByClassName("vtkMRMLCrosshairDisplayableManager").GetSliceIntersectionWidget()
                for act in (siw.ActionBrowseSlice, siw.ActionTranslateSliceIntersection, siw.ActionRotateSliceIntersection, siw.ActionSetCrosshairPosition):
                    siw.SetActionEnabled(act, True)
            except Exception: pass
        for cn in slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode"):   # 断面どうしを連動させない（ホイールで全部が動かない）
            try: cn.SetLinkedControl(False); cn.SetHotLinkedControl(False)
            except Exception: pass
        try:
            ch = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode")
            ch.SetCrosshairMode(ch.ShowSmallBasic if kind == "four" else ch.NoCrosshair); ch.SetCrosshairBehavior(ch.OffsetJumpSlice)   # 十字は 4 画面だけ。Shift＋マウスで 3 断面をその点へ
        except Exception: pass
        self.setObliqueHandles(kind == "four" and getattr(self, "obliqueOn", True))

    def setObliqueHandles(self, on):
        """4 画面の色つきの線（ほかの断面との交線）を出し、ドラッグで位置・回転（斜め MPR）できるようにする"""
        self.obliqueOn = bool(on) if getattr(self, "layoutKind", "") == "four" else getattr(self, "obliqueOn", True)
        show = getattr(self, "layoutKind", "") == "four"
        for dn in slicer.util.getNodesByClass("vtkMRMLSliceDisplayNode"):
            for f, v in (("SetIntersectingSlicesVisibility", show), ("SetIntersectingSlicesInteractive", show and on),
                         ("SetIntersectingSlicesTranslationEnabled", show and on), ("SetIntersectingSlicesRotationEnabled", show and on)):
                try: getattr(dn, f)(bool(v))
                except Exception: pass
            try: dn.SetIntersectingSlicesInteractiveHandlesVisibilityMode(dn.AlwaysVisible if (show and on) else dn.NeverVisible)   # 線の端に回す丸・真ん中に動かす丸を常に出す
            except Exception as e: print("handles:", e)
            try: dn.SetIntersectingSlicesLineThicknessMode(1)
            except Exception: pass

    def resetMPR(self, render=True):
        """斜めにした断面を、軸位・矢状断・冠状断に戻す（いまの十字の位置・心臓の中心で）"""
        lm = slicer.app.layoutManager()
        c = self._sceneCenter()
        try:
            ch = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode"); p = [0.0, 0.0, 0.0]; ch.GetCrosshairRAS(p)
            if np.linalg.norm(np.array(p)) > 1e-3 and getattr(self, "_mprCentered", False): c = np.array(p)
        except Exception: pass
        self._mprCentered = True
        r = float(np.max(self._visibleBounds()[1] - self._visibleBounds()[0])) * 1.1 if self.bounds is not None else 250.0
        for nm, ori in (("Red", "Axial"), ("Yellow", "Sagittal"), ("Green", "Coronal")):
            w = lm.sliceWidget(nm)
            if w is None: continue
            sn = w.mrmlSliceNode(); sn.SetOrientation(ori); sn.JumpSliceByCentering(*c)
            dims = sn.GetDimensions(); asp = dims[1] / max(dims[0], 1)
            sn.SetFieldOfView(r, r * asp, sn.GetFieldOfView()[2])
        try: ch.SetCrosshairRAS(*c)
        except Exception: pass
        self.mprAngle = {}
        try: slicer.modules.cardiacview.widgetRepresentation().self().mprAngleLabel.setText("0°")
        except Exception: pass

    def setOutlines2D(self, on):
        """断面に 3D の面の切り口（輪郭線）を出すか。ふつうの MPR は出さない（CT だけ）"""
        self.outlines2D = bool(on)
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if n.GetName().startswith("CV ") and n.GetDisplayNode() is not None:
                n.GetDisplayNode().SetVisibility2D(bool(on))
        for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            d = n.GetDisplayNode()
            if d is not None: d.SetVisibility2D(bool(on))

    def _mprCenter(self):
        """3 断面が交わる点"""
        lm = slicer.app.layoutManager(); N = []; d = []
        for nm in ("Red", "Yellow", "Green"):
            M = slicer.util.arrayFromVTKMatrix(lm.sliceWidget(nm).mrmlSliceNode().GetSliceToRAS())
            n = M[:3, 2] / (np.linalg.norm(M[:3, 2]) + 1e-12); N.append(n); d.append(float(n @ M[:3, 3]))
        try: return np.linalg.solve(np.array(N), np.array(d))
        except Exception: return self._sceneCenter()

    def rotateMPR(self, view, deg):
        """view の断面の中で、ほかの 2 つの断面の線を deg 度回す（= 斜め MPR の微調整）。交点を中心に回す"""
        lm = slicer.app.layoutManager()
        if lm.sliceWidget(view) is None: return
        c = self._mprCenter()
        n = slicer.util.arrayFromVTKMatrix(lm.sliceWidget(view).mrmlSliceNode().GetSliceToRAS())[:3, 2]; n = n / (np.linalg.norm(n) + 1e-12)
        t = math.radians(deg); K = np.array([[0, -n[2], n[1]], [n[2], 0, -n[0]], [-n[1], n[0], 0]])
        R = np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)
        for nm in ("Red", "Yellow", "Green"):
            if nm == view: continue
            sn = lm.sliceWidget(nm).mrmlSliceNode(); M = slicer.util.arrayFromVTKMatrix(sn.GetSliceToRAS())
            M[:3, :3] = R @ M[:3, :3]; M[:3, 3] = c + R @ (M[:3, 3] - c)
            vm = sn.GetSliceToRAS()
            for r in range(3):
                for k in range(4): vm.SetElement(r, k, float(M[r, k]))
            sn.UpdateMatrices()
        self.mprAngle = getattr(self, "mprAngle", {}); self.mprAngle[view] = self.mprAngle.get(view, 0.0) + deg
        try:
            w = slicer.modules.cardiacview.widgetRepresentation().self()
            w.mprAngleLabel.setText("  ".join(f"{dict(Red='軸', Yellow='矢', Green='冠')[k]} {v:+.0f}°" for k, v in self.mprAngle.items() if abs(v) > 0.01) or "0°")
        except Exception: pass

    def setSlab(self, mm):
        """断面に厚み（最大値投影 MIP）。0 = なし"""
        self.slabMM = mm
        for nm in ("Red", "Yellow", "Green"):
            w = slicer.app.layoutManager().sliceWidget(nm)
            if w is None: continue
            sn = w.mrmlSliceNode()
            try:
                sn.SetSlabReconstructionEnabled(mm > 0)
                if mm > 0: sn.SetSlabReconstructionThickness(float(mm)); sn.SetSlabReconstructionType(vtk.VTK_IMAGE_SLAB_MAX)
            except Exception as e: print("slab:", e)

    def _equalSplit(self):
        """4 画面の仕切りを等分に（縦も横も半分ずつ）"""
        try:
            vp = slicer.app.layoutManager().viewport()
            for sp in vp.findChildren(qt.QSplitter):
                g = lambda a: a() if callable(a) else a
                n = int(g(sp.count))
                if n < 2: continue
                tot = int(g(sp.width) if g(sp.orientation) == qt.Qt.Horizontal else g(sp.height))
                sp.setSizes([max(1, tot // n)] * n)
        except Exception as e: print("equal split:", e)

    def _toggleMaximize(self, which):
        """ダブルクリック: その画面だけを大きく ⇔ 元の分割に戻す"""
        lm = slicer.app.layoutManager(); L = slicer.vtkMRMLLayoutNode
        prev = getattr(self, "_maxPrev", None)
        if prev is not None:
            self._maxPrev = None; lm.setLayout(prev)
            if prev == CV_LAYOUT_FOUR: self._equalSplit(); qt.QTimer.singleShot(120, self._equalSplit)
            return
        if getattr(self, "layoutKind", "3d") == "3d": return
        self._maxPrev = lm.layout
        lm.setLayout({"Red": L.SlicerLayoutOneUpRedSliceView, "Yellow": L.SlicerLayoutOneUpYellowSliceView,
                      "Green": L.SlicerLayoutOneUpGreenSliceView}.get(which, L.SlicerLayoutOneUp3DView))

    def _syncCutSlice(self):
        """3D で切っている面を、左（Red）の断面にそのまま出す（向きも画面と同じ）"""
        if getattr(self, "layoutKind", "3d") != "cut" or self.cutPlane is None or self.cutAxis is None: return
        w = slicer.app.layoutManager().sliceWidget("Red")
        if w is None: return
        c = [0.0, 0.0, 0.0]
        try: self.cutPlane.GetCenterWorld(c)
        except Exception: self.cutPlane.GetCenter(c)
        c = np.array(c)
        cam = self._camera().GetCamera()
        n = np.array(cam.GetViewPlaneNormal(), float) if self.cutAxis == "VIEW" else np.array(self.cutPlane.GetNormal(), float)   # LOCK は固定した面
        up = np.array(cam.GetViewUp(), float); up -= (up @ n) * n
        if np.linalg.norm(up) < 1e-6: up = np.array([0, 0, 1.0]) - n[2] * n
        up /= np.linalg.norm(up); x = np.cross(up, n)
        sn = w.mrmlSliceNode(); M = sn.GetSliceToRAS()
        for r in range(3): M.SetElement(r, 0, x[r]); M.SetElement(r, 1, up[r]); M.SetElement(r, 2, n[r]); M.SetElement(r, 3, c[r])
        sn.UpdateMatrices()

    MEASURES = [("line", "直線", "vtkMRMLMarkupsLineNode", "L"), ("poly", "連続点", "vtkMRMLMarkupsCurveNode", "P"),
                ("curve", "カーブ", "vtkMRMLMarkupsCurveNode", "C"), ("area", "面積", "vtkMRMLMarkupsClosedCurveNode", "A"),
                ("angle", "角度", "vtkMRMLMarkupsAngleNode", "Ang")]

    def startMeasure(self, kind="line"):
        """計測: 直線 / 連続点（折れ線）/ カーブ / 面積（閉曲線）/ 角度。3D（面・VR の上）でも断面でもクリックで置く"""
        self.rulers = [n for n in getattr(self, "rulers", []) if slicer.mrmlScene.IsNodePresent(n)]
        key, lab, cls, pre = next(m for m in self.MEASURES if m[0] == kind)
        num = 1 + sum(1 for n in self.rulers if n.GetAttribute("CV.measure") == kind)
        n = slicer.mrmlScene.AddNewNodeByClass(cls, f"{pre}{num}")                 # 3D の文字は英数字だけ表示できる
        n.SetAttribute("CV.measure", kind)
        if kind == "poly": n.SetCurveTypeToLinear()
        if kind in ("line", "poly", "curve"):
            try: n.GetMeasurement("length").SetEnabled(True)
            except Exception: pass
        if kind == "angle":
            try: n.GetMeasurement("angle").SetEnabled(True)
            except Exception: pass
        if kind == "area":                                  # Slicer 標準の面積は 0 のままになるので、自前で計算して名前に出す
            try: n.GetMeasurement("area").SetEnabled(False); n.GetMeasurement("length").SetEnabled(True)
            except Exception: pass
            base = n.GetName()
            def upd(caller=None, ev=None, n=n, base=base):
                try:
                    P = slicer.util.arrayFromMarkupsCurvePoints(n, world=True)
                    if P is None or len(P) < 3: return
                    c = P.mean(0); _, _, vt = np.linalg.svd(P - c, full_matrices=False)
                    q = (P - c) @ vt[:2].T; x, y = q[:, 0], q[:, 1]
                    a = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))   # 当てはめた平面の上の面積（mm2）
                    nm = f"{base}: {a / 100.0:.2f} cm2"
                    if n.GetName() != nm: n.SetName(nm)
                except Exception as e: print("area:", e)
            for evn in (slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                        slicer.vtkMRMLMarkupsNode.PointRemovedEvent, slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent):
                n.AddObserver(evn, upd)
        d = n.GetDisplayNode()
        col = {"line": (1.0, 0.85, 0.2), "poly": (0.4, 1.0, 0.6), "curve": (0.4, 0.9, 1.0), "area": (1.0, 0.55, 0.9), "angle": (1.0, 0.7, 0.3)}[kind]
        d.SetSelectedColor(*col); d.SetColor(*col); d.SetActiveColor(1.0, 1.0, 1.0)
        d.SetTextScale(3.0); d.SetGlyphScale(1.4); d.SetLineThickness(0.3); d.SetPointLabelsVisibility(False)
        try: d.SetPropertiesLabelVisibility(True); d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.5)
        except Exception: pass
        self._put(n); self.rulers.append(n)
        sel = slicer.app.applicationLogic().GetSelectionNode()
        sel.SetReferenceActivePlaceNodeClassName(cls); sel.SetActivePlaceNodeID(n.GetID())
        inter = slicer.app.applicationLogic().GetInteractionNode()
        inter.SetPlaceModePersistence(1 if kind in ("poly", "curve", "area") else 0)   # 多点は右クリックで終了
        inter.SetCurrentInteractionMode(inter.Place)
        return n

    def startRuler(self):
        return self.startMeasure("line")

    def clearRulers(self):
        for n in getattr(self, "rulers", []):
            if slicer.mrmlScene.IsNodePresent(n): slicer.mrmlScene.RemoveNode(n)
        self.rulers = []

    # ---------------------------------------------------------------- マウス（Zio 風）
    def installMouse(self):
        """マウス操作（アプリ全体で 1 組）。どのロジックが作っても、届け先は今の画面のロジック。
        3D: 左右同時ドラッグ = VR のウィンドウ／ホイール = 切る位置／右ドラッグ = 選んだ機能
        断面（2D）: 右ドラッグ = 選んだ機能（拡大・ウィンドウ・移動・切る位置＝スライス送り）"""
        lm = slicer.app.layoutManager()
        it = self._view().interactor()
        reg = getattr(slicer, "_cvMouse", None)
        if reg and reg.get("it") is it and reg.get("v") == 4: return
        if reg:
            for i, t in reg.get("tags", []):
                try: i.RemoveObserver(t)
                except Exception: pass
        tags = []; E = vtk.vtkCommand
        def add(itr, ev, name, *a):
            def cb(c, e, name=name, a=a):
                L = _cvCur()
                if L is None or not hasattr(L, name): return
                try: getattr(L, name)(c, *a)
                except Exception: import traceback; traceback.print_exc()
            tags.append((itr, itr.AddObserver(ev, cb, 2.0)))
        add(it, E.LeftButtonPressEvent, "_mPress", "L"); add(it, E.RightButtonPressEvent, "_mPress", "R")
        add(it, E.LeftButtonReleaseEvent, "_mRelease", "L"); add(it, E.RightButtonReleaseEvent, "_mRelease", "R")
        add(it, E.MouseMoveEvent, "_mMove")
        add(it, E.MiddleButtonPressEvent, "_mMid", True); add(it, E.MiddleButtonReleaseEvent, "_mMid", False)
        add(it, E.MouseWheelForwardEvent, "_mWheel", +1); add(it, E.MouseWheelBackwardEvent, "_mWheel", -1)
        for nm in ("Red", "Yellow", "Green"):
            try: sit = lm.sliceWidget(nm).sliceView().interactor()
            except Exception: continue
            add(sit, E.RightButtonPressEvent, "_sPress", nm); add(sit, E.MouseMoveEvent, "_sMove"); add(sit, E.RightButtonReleaseEvent, "_sRelease")
            add(sit, E.MouseWheelForwardEvent, "_sWheel", nm, +1); add(sit, E.MouseWheelBackwardEvent, "_sWheel", nm, -1)
            add(sit, E.LeftButtonPressEvent, "_dbl", nm)
            add(sit, E.KeyPressEvent, "_sKey", nm)
            add(sit, E.KeyPressEvent, "_delKey", nm)
        add(it, E.LeftButtonPressEvent, "_dbl", "3D")
        add(it, E.KeyPressEvent, "_delKey", "3D")
        slicer._cvMouse = dict(it=it, tags=tags, v=4)

    def _mMid(self, it, down):
        if down: self._vrFast(True)
        else: self._vrSettle()

    def _flash(self, msg):
        """3D 画面の上に一言だけ出す（2 秒）"""
        try:
            self._setUL("3_flash", msg)
            t = getattr(self, "_flashTimer", None)
            if t is None:
                t = self._flashTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(2200)
                t.connect("timeout()", lambda: self._setUL("3_flash", ""))
            t.start()
        except Exception: pass

    def _mine(self):
        if _cvCur() is not self: return False
        try: return slicer.util.selectedModule() in ("CardiacView", "HeartView")
        except Exception: return True

    def _mAbort(self, it):
        for i, t in (getattr(slicer, "_cvMouse", None) or {}).get("tags", []):
            if i is it:
                try: it.GetCommand(t).SetAbortFlag(1)
                except Exception: pass

    # ================================================================ 4D（動く心臓）
    # 同じ撮影の各位相（心電図同期の 0〜95% など）を、心臓のまわりだけ切り出して少し粗くし、Sequence にして再生する。
    # 3D の面・色分け VR は 1 位相（3D を作った CT）のまま。4D では元の CT 値の VR と断面が動く。
    @staticmethod
    def _ramBytes():
        try:
            import psutil; return float(psutil.virtual_memory().total)
        except Exception: pass
        try:
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("t", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong),
                            ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return float(m.t)
        except Exception: return 16e9

    def setup4D(self, phases, status=lambda m: None, budget=None):
        """phases: [(ラベル, ボリューム または 読み込む関数)]。関数なら 1 位相ずつ読み込んで、使い終わったら消す（メモリを食わない）。
        budget = 全位相合計のメモリ上限（バイト。既定は PC のメモリの 1/24、0.4〜1.6 GB）"""
        from scipy import ndimage
        if budget is None: budget = min(1.6e9, max(0.4e9, self._ramBytes() / 24.0))
        src = getattr(self, "sourceVolume", None); seg = self._findSegmentation(); hc = self._findChambers()
        if src is None or seg is None: raise RuntimeError("先に 3D を作ってください")
        if len(phases) < 2: raise RuntimeError("位相が 1 つしかありません")
        self.clear4D()
        status(f"4D（{len(phases)} 位相）を準備中: 心臓の範囲…")
        region = self._segmentMaskArray(hc, src, ("ventricle", "atrium", "aorta", "pulmonary artery", "myocardium")) if hc is not None else None
        r2 = self._segmentMaskArray(seg, src, ("heart", "atrial appendage", "aorta", "pulmonary vein", "pulmonary artery", "superior vena cava"))
        if r2 is not None: region = r2 if region is None else (region | r2)
        if region is None or region.sum() < 1000: raise RuntimeError("心臓のラベルがありません")
        sp = np.array(src.GetSpacing())[::-1]                                     # (z, y, x) mm
        rr = [np.nonzero(region.any(axis=ax))[0] for ax in ((1, 2), (0, 2), (0, 1))]
        m = np.ceil(15.0 / sp).astype(int)                                        # 心臓は動くので 15 mm 余裕
        lo = np.maximum(np.array([q.min() for q in rr]) - m, 0); hi = np.minimum(np.array([q.max() for q in rr]) + m + 1, region.shape)
        f = np.maximum(1, np.round(0.55 / sp)).astype(int)                         # まず 0.5〜0.6 mm 程度に
        per = budget / len(phases) / 2.0
        while np.prod(np.ceil((hi - lo) / f)) > per:                              # メモリに収まるまで、いちばん細かい向きから粗く
            f[int(np.argmin(sp * f))] += 1
        hi = lo + ((hi - lo) // f) * f
        crop = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi)); shp = tuple(int(x) for x in (hi - lo) // f)
        def pool(a):
            a = a[crop].reshape(shp[0], f[0], shp[1], f[1], shp[2], f[2])
            return a.mean(axis=(1, 3, 5), dtype=np.float32)
        # 心臓の外を消す重み（骨は 1〜3 mm で消す）
        gsp = sp * f
        rs = pool(region.astype(np.float32)) > 0.3; del region
        d = ndimage.distance_transform_edt(~rs, sampling=gsp)
        wgt = np.clip((11.0 - d) / 4.0, 0.0, 1.0).astype(np.float32); del d, rs      # ラベル + 7 mm は残し、11 mm で消す（動く分の余裕）
        bone = self._boneMaskArray(seg, src)
        if bone is not None and bone.any():
            bp = pool(bone.astype(np.float32)) > 0.3; del bone
            if bp.any(): wgt *= np.clip((ndimage.distance_transform_edt(~bp, sampling=gsp) - 1.0) / 2.0, 0.0, 1.0).astype(np.float32)
        M = vtk.vtkMatrix4x4(); src.GetIJKToRASMatrix(M); A = slicer.util.arrayFromVTKMatrix(M)
        fx = f[::-1].astype(float); o = lo[::-1] + (fx - 1) / 2.0                      # (i, j, k) の順
        A2 = A.copy(); A2[:3, :3] = A[:3, :3] * fx[None, :]; A2[:3, 3] = (A @ np.r_[o, 1.0])[:3]
        M2 = slicer.util.vtkMatrixFromArray(A2)
        seq = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "CV 4D 位相")
        seq.SetIndexName("phase"); seq.SetIndexUnit(""); seq.SetIndexType(seq.NumericIndex)
        labels = []
        for i, (lab, vol) in enumerate(phases):
            status(f"4D を準備中: 位相 {i + 1}/{len(phases)}（{lab}）…")
            tmp = None; loaded = None; arr = None
            if callable(vol): vol = loaded = vol()
            if isinstance(vol, np.ndarray):                                   # 配列で渡された（3D を作った CT と同じ格子）
                arr, vol, loaded = vol, src, None
            same = (vol.GetImageData() is not None and tuple(vol.GetImageData().GetDimensions()) == tuple(src.GetImageData().GetDimensions())
                    and np.allclose(vol.GetSpacing(), src.GetSpacing(), atol=1e-3) and np.allclose(vol.GetOrigin(), src.GetOrigin(), atol=1e-2))
            if not same:
                tmp = slicer.modules.volumes.logic().ResampleVolumeToReferenceVolume(vol, src); vol = tmp
            a = pool(arr if arr is not None else slicer.util.arrayFromVolume(vol)); arr = None
            out = np.clip(-1024.0 + (a + 1024.0) * wgt, -1024, 3071).astype(np.int16); del a
            if tmp is not None: slicer.mrmlScene.RemoveNode(tmp)
            if loaded is not None and loaded is not src: slicer.mrmlScene.RemoveNode(loaded)
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", f"CV 4D {lab}")
            node.SetIJKToRASMatrix(M2); slicer.util.updateVolumeFromArray(node, out)
            seq.SetDataNodeAtValue(node, str(i)); slicer.mrmlScene.RemoveNode(node); labels.append(str(lab))
            slicer.app.processEvents()
        seq.SetAttribute("CV.4D.labels", "|".join(labels))
        br = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "CV 4D 再生")
        br.SetAndObserveMasterSequenceNodeID(seq.GetID()); br.SetPlaybackLooped(True); br.SetPlaybackRateFps(8.0)
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(br)
        proxy = br.GetProxyNode(seq); proxy.SetName("CV 4D")
        proxy.CreateDefaultDisplayNodes()
        self._adopt4D(br)
        self.vr4D.SetVisibility(False)
        status(f"4D（{len(phases)} 位相・{gsp[2]:.2f}×{gsp[1]:.2f}×{gsp[0]:.2f} mm）の準備ができました")
        return len(phases)

    def _adopt4D(self, br=None):
        """4D の部品（再生・位相・表示）を引き継ぐ。保存した症例を開いた時も"""
        br = br or slicer.mrmlScene.GetFirstNodeByName("CV 4D 再生")
        if br is None or not br.IsA("vtkMRMLSequenceBrowserNode"):
            self.br4D = self.seq4D = self.proxy4D = self.vr4D = None; return False
        self.br4D = br; self.seq4D = br.GetMasterSequenceNode(); self.proxy4D = br.GetProxyNode(self.seq4D)
        self.labels4D = (self.seq4D.GetAttribute("CV.4D.labels") or "").split("|")
        vrl = slicer.modules.volumerendering.logic()
        dn = vrl.GetFirstVolumeRenderingDisplayNode(self.proxy4D)
        if dn is None:
            c = self._camera(); st = (c.GetPosition(), c.GetFocalPoint(), c.GetViewUp(), c.GetParallelScale())   # Slicer がカメラを戻さないように
            dn = vrl.CreateDefaultVolumeRenderingNodes(self.proxy4D)
            def _back(c=c, st=st):
                try: c.SetPosition(*st[0]); c.SetFocalPoint(*st[1]); c.SetViewUp(*st[2]); c.SetParallelScale(st[3]); c.ResetClippingRange()
                except Exception: pass
            _back(); qt.QTimer.singleShot(0, _back); qt.QTimer.singleShot(150, _back)
        dn.RemoveAllViewNodeIDs(); dn.AddViewNodeID(self._viewNode().GetID())
        self.vr4D = dn; self._tf4D()
        try: slicer.modules.sequences.setToolBarVisible(False)                # 再生は CardiacView の欄で（Slicer 標準の再生バーは出さない）
        except Exception: pass
        return True

    def _base4D(self, mode):
        """4D の VR の標準の範囲（HU）。blood: 心筋の少し下〜造影血液の上、tissue: 心筋の少し下〜心筋と血液の中間"""
        c = self._cal(); myo = float(c.get("myo", 80.0)); bl = float(c.get("blood", 350.0)); mid = (myo + bl) / 2
        return (myo - 60, mid + 15) if mode == "tissue" else (myo - 50, bl + 150)

    def _win4D(self):
        mode = getattr(self, "mode4D", "blood"); w = (getattr(self, "win4DMap", None) or {}).get(mode)
        if w is None:
            lo, hi = self._base4D(mode); w = ((lo + hi) / 2, hi - lo)
        return w

    def set4DWindow(self, center=None, width=None):
        mode = getattr(self, "mode4D", "blood"); c0, w0 = self._win4D()
        c0 = c0 if center is None else float(center); w0 = max(20.0, w0 if width is None else float(width))
        self.win4DMap = dict(getattr(self, "win4DMap", None) or {}); self.win4DMap[mode] = (c0, w0)
        self._tf4D()

    def _tf4D(self, mode=None):
        """4D の VR の色と透明度。blood: 心筋は赤、造影された血液は明るい肌色（外から見た形・内腔）。
        tissue: 造影された血液を透明にして、弁・乳頭筋・壁の動きを見る。脂肪・肺はどちらも透明。
        ウィンドウ（右ドラッグ「ウィンドウ」や左右同時ドラッグ）で範囲をずらす・広げる"""
        if mode is not None: self.mode4D = mode
        mode = getattr(self, "mode4D", "blood")
        b0, b1 = self._base4D(mode); c0, w0 = self._win4D(); lo, hi = c0 - w0 / 2, c0 + w0 / 2
        X = lambda t: lo + (t - b0) / max(b1 - b0, 1.0) * (hi - lo)               # 標準の範囲 → 今のウィンドウ
        c = self._cal(); myo = float(c.get("myo", 80.0)); bl = float(c.get("blood", 350.0)); mid = (myo + bl) / 2
        vp = self.vr4D.GetVolumePropertyNode().GetVolumeProperty()
        if mode == "tissue":
            pts = [(-1024, 0), (X(myo - 60), 0), (X(myo), 0.55), (X(mid - 25), 0.75), (X(mid + 15), 0), (max(X(mid + 15) + 1, bl + 400), 0), (max(X(mid + 15) + 2, bl + 401), 0.6), (3071, 0.8)]
        else:
            pts = [(-1024, 0), (X(myo - 50), 0), (X(myo + 10), 0.25), (X(mid), 0.6), (X(bl + 150), 0.85), (3071, 0.9)]
        cols = [(-1024, (0, 0, 0)), (X(myo - 50), (0.45, 0.1, 0.08)), (X(myo + 10), (0.75, 0.3, 0.24)), (X(mid), (0.95, 0.6, 0.5)),
                (X(bl + 100), (1.0, 0.9, 0.82)), (max(X(bl + 100) + 1, 1500), (1, 1, 1)), (3071, (1, 1, 1))]
        def mono(p):                                                          # x が重なると点が減るので必ず少し増やす
            out = []
            for x, y in p: out.append((max(float(x), out[-1][0] + 0.01) if out else float(x), y))
            return out
        otf = vp.GetScalarOpacity(); ctf = vp.GetRGBTransferFunction()
        if otf is None or getattr(self, "_otf4D", None) is not otf:
            otf = vtk.vtkPiecewiseFunction(); ctf = vtk.vtkColorTransferFunction(); vp.SetScalarOpacity(otf); vp.SetColor(ctf)
            vp.ShadeOn(); vp.SetInterpolationTypeToLinear(); vp.SetAmbient(0.25); vp.SetDiffuse(0.8); vp.SetSpecular(0.3); vp.SetSpecularPower(20)
            self._otf4D = otf
        otf.RemoveAllPoints(); ctf.RemoveAllPoints()
        for x, y in mono(pts): otf.AddPoint(x, y)
        for x, col in mono(cols): ctf.AddRGBPoint(x, *col)
        try:
            if getattr(self, "on4D", False):
                self._setUR(f"<b>4D</b>　W {w0:.0f} / L {c0:.0f}\n<span style='color:#9aa3ad'>{lo:.0f} – {hi:.0f} HU</span>")
        except Exception: pass

    def set4DMode(self, mode):
        if getattr(self, "vr4D", None) is None: return
        self._tf4D(mode); self._view().scheduleRender()

    def has4D(self):
        return getattr(self, "br4D", None) is not None and slicer.mrmlScene.IsNodePresent(self.br4D)

    def n4D(self):
        return self.seq4D.GetNumberOfDataNodes() if self.has4D() else 0

    def clear4D(self):
        self.show4D(False)
        for cls in ("vtkMRMLSequenceBrowserNode", "vtkMRMLSequenceNode", "vtkMRMLScalarVolumeNode"):
            for n in list(slicer.util.getNodesByClass(cls)):
                if n.GetName() not in ("CV 4D 再生", "CV 4D 位相", "CV 4D"): continue
                try:
                    if hasattr(n, "GetNumberOfDisplayNodes"):
                        for d in [n.GetNthDisplayNode(i) for i in range(n.GetNumberOfDisplayNodes())]:
                            if d is not None: slicer.mrmlScene.RemoveNode(d)
                    slicer.mrmlScene.RemoveNode(n)
                except Exception: pass
        self.br4D = self.seq4D = self.proxy4D = self.vr4D = None

    def show4D(self, on):
        """on: 3D の面・色分け VR を隠して、動く VR と断面に切り替える。off: 元に戻す"""
        on = bool(on) and self.has4D()
        if on == bool(getattr(self, "on4D", False)): return
        lm = slicer.app.layoutManager()
        if on:
            st = dict(vr=bool(getattr(self, "vrOn", False)), models={}, bg={})
            if getattr(self, "vrDisplay", None) is not None: self.vrDisplay.SetVisibility(False)
            for k, n in self.layerModels.items():
                d = n.GetDisplayNode() if n else None
                if d is not None: d.SetVisibility(k in self.STATIC_4D and bool(self.visible.get(k, False)))
            cap = slicer.mrmlScene.GetFirstNodeByName("CV 心筋断面")
            if cap and cap.GetDisplayNode(): cap.GetDisplayNode().SetVisibility(False)
            for nm in ("Red", "Yellow", "Green"):
                w = lm.sliceWidget(nm)
                if w is None: continue
                cn = w.sliceLogic().GetSliceCompositeNode(); st["bg"][nm] = cn.GetBackgroundVolumeID(); cn.SetBackgroundVolumeID(self.proxy4D.GetID())
            try:
                d = self.proxy4D.GetDisplayNode(); s0 = self.sourceVolume.GetDisplayNode()
                if d is not None and s0 is not None: d.SetAutoWindowLevel(False); d.SetWindowLevel(s0.GetWindow(), s0.GetLevel())
            except Exception: pass
            self._st4D = st; self.vr4D.SetVisibility(True); self.on4D = True
            try: self._tf4D()                                                 # 右上に 4D のウィンドウを出す
            except Exception: pass
        else:
            self.play4D(False)
            st = getattr(self, "_st4D", None) or {}
            if getattr(self, "vr4D", None) is not None: self.vr4D.SetVisibility(False)
            for k, n in self.layerModels.items():                            # 面は「見せたい状態」（self.visible）に戻す
                if n and n.GetDisplayNode(): n.GetDisplayNode().SetVisibility(bool(self.visible.get(k, False)))
            if st.get("vr") and getattr(self, "vrDisplay", None) is not None: self.vrDisplay.SetVisibility(True)
            for nm, vid in st.get("bg", {}).items():
                w = lm.sliceWidget(nm)
                if w is not None: w.sliceLogic().GetSliceCompositeNode().SetBackgroundVolumeID(vid)
            self.on4D = False
            try: self.updateMyoCap(); self._vrLabel()
            except Exception: pass
        try: self._clipSync()
        except Exception: pass
        self._view().scheduleRender()

    def play4D(self, on, fps=None):
        if not self.has4D(): return
        if fps is not None: self.br4D.SetPlaybackRateFps(float(fps))
        self.br4D.SetPlaybackActive(bool(on))

    def set4DPhase(self, i):
        if not self.has4D(): return
        self.br4D.SetPlaybackActive(False); self.br4D.SetSelectedItemNumber(int(i))

    def phase4D(self):
        return self.br4D.GetSelectedItemNumber() if self.has4D() else -1

    def _mapperOf(self, dn):
        """その VR 表示の GPU マッパー（4D 表示中は、見えている VR が 4D のもの）"""
        try:
            dm = self._view().displayableManagerByClassName("vtkMRMLVolumeRenderingDisplayableManager")
            a = dm.GetVolumeActor(dn) if hasattr(dm, "GetVolumeActor") else None
            if a is not None and a.GetMapper() is not None: return a.GetMapper()
        except Exception: pass
        try:
            ren = self._view().renderWindow().GetRenderers().GetFirstRenderer(); vs = ren.GetVolumes(); vs.InitTraversal()
            dims = tuple(self.proxy4D.GetImageData().GetDimensions()) if getattr(self, "proxy4D", None) is not None else None
            for _ in range(vs.GetNumberOfItems()):
                v = vs.GetNextVolume(); m = v.GetMapper()
                if m is None or not v.GetVisibility(): continue
                try:
                    inp = m.GetInput()
                    if dims is not None and inp is not None and tuple(inp.GetDimensions()) != dims: continue
                except Exception: pass
                return m
        except Exception: pass
        return None

    def _vrMapper(self):
        try:
            ren = self._view().renderWindow().GetRenderers().GetFirstRenderer(); vs = ren.GetVolumes(); vs.InitTraversal()
            for _ in range(vs.GetNumberOfItems()):
                m = vs.GetNextVolume().GetMapper()
                if m is not None and m.IsA("vtkGPUVolumeRayCastMapper"): return m
        except Exception: pass
        return None

    def _vrFast(self, fast=True):
        """VR は動かしている間だけ「描く点を粗く」（解像度だけ下げる）、止まったら細かく。
        自動画質（Adaptive）は動かす時と止まった時で光の通り方が変わって、離した瞬間に暗く見えるので使わない"""
        if not getattr(self, "vrOn", False) or not self._mine(): return
        vn = self._viewNode(); still = max(1, int(getattr(self, "vrStillQ", None) or 1))
        q = 1 if fast else still
        if vn.GetVolumeRenderingQuality() != q: vn.SetVolumeRenderingQuality(q)
        m = self._vrMapper()
        if m is not None:
            isd = float(getattr(self, "vrFastISD", 1.5) or 1.5) if fast else 1.0
            if m.GetAutoAdjustSampleDistances(): m.AutoAdjustSampleDistancesOff()
            if abs(m.GetImageSampleDistance() - isd) > 1e-3: m.SetImageSampleDistance(isd)

    def _vrSettle(self):
        if not getattr(self, "vrOn", False): return
        t = getattr(self, "_vrTimer", None)
        if t is None:
            t = self._vrTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(300)
            t.connect("timeout()", lambda: (self._vrFast(False), self._view().scheduleRender()))
        t.start()

    def _winGet(self):
        return self._win4D() if getattr(self, "on4D", False) else getattr(self, "vrWin", None)

    def _winSet(self, win0, dx, dy):
        """横 = 幅、縦 = 中心。4D は HU で直接、色分け VR は 0〜255 の目盛り（1 = 約 2.7 HU）"""
        c0, w0 = win0
        if getattr(self, "on4D", False): self.set4DWindow(center=c0 - dy * 1.5, width=w0 + dx * 2.0)
        else: self.setVRWindow(center=c0 - dy * 0.4, width=w0 + dx * 0.6)

    def _mPress(self, it, b):
        if not self._mine(): return
        if not hasattr(self, "_btn"): self._btn = {"L": False, "R": False}; self._wl = None
        if b == "L" and getattr(self, "paintOn", False) and not it.GetShiftKey():   # パッチを塗る（面の上を押した時だけ。何もない所はいつもの回転）
            try:
                if self._paintPress(it): self._mAbort(it); return
            except Exception:
                import traceback; traceback.print_exc(); self._painting = False
        self._vrFast(True)
        self._btn[b] = True
        mode = getattr(self, "rmode", "zoom")
        inter = slicer.app.applicationLogic().GetInteractionNode()
        placing = inter.GetCurrentInteractionMode() == inter.Place
        if b == "R" and mode == "window" and not (getattr(self, "vrOn", False) or getattr(self, "on4D", False)):
            self._flash("ウィンドウは VR か断面で使えます"); mode = "zoom"          # 面の表示にはウィンドウが無い → いつもの拡大
        if b == "R" and mode == "cut" and self.cutAxis is None and not placing:
            self.setCut("VIEW", 0.0); self._syncCutUI()                          # まだ切っていなければ「正面から」で切り始める
        if b == "R" and not self._btn["L"] and mode != "zoom" and not placing:          # 右ドラッグの機能（ボタンで切替）
            cam = self._camera()
            self._rdrag = (mode, it.GetEventPosition(), (cam.GetFocalPoint(), cam.GetPosition()), self._winGet(), getattr(self, "cutFrac", 0.5))
            self._mAbort(it); return
        if self._btn["L"] and self._btn["R"] and (getattr(self, "vrOn", False) or getattr(self, "on4D", False)) and self._mine():
            self._wl = (it.GetEventPosition(), self._winGet())
            self._mAbort(it)

    def _mRelease(self, it, b):
        if not self._mine(): return
        if not hasattr(self, "_btn"): self._btn = {"L": False, "R": False}; self._wl = None
        self._btn[b] = False
        if b == "L" and getattr(self, "_painting", False):
            self._paintRelease(); self._mAbort(it); return
        if b == "R" and getattr(self, "_rdrag", None) is not None:
            self._rdrag = None; self._mAbort(it); self._vrSettle(); return
        if not (self._btn["L"] or self._btn["R"]): self._vrSettle()
        if self._wl is not None:
            if not (self._btn["L"] or self._btn["R"]): self._wl = None
            if b == "R": self._mAbort(it)

    def _mMove(self, it):
        if getattr(self, "_painting", False) and self._mine():
            try: self._paintMove(it)
            except Exception:
                import traceback; traceback.print_exc(); self._painting = False
            self._mAbort(it); return
        rd = getattr(self, "_rdrag", None)
        if rd is not None and self._mine():
            mode, (x0, y0), cam0, win0, frac0 = rd; x, y = it.GetEventPosition()
            if mode == "window" and win0 is not None and (getattr(self, "vrOn", False) or getattr(self, "on4D", False)):
                self._winSet(win0, x - x0, y - y0)
            elif mode == "pan":
                self._pan(x0, y0, x, y, cam0)
            elif mode == "cut" and self.cutAxis is not None:
                lo, hi = self._visibleBounds(); span = float(np.linalg.norm(hi - lo))
                f = float(np.clip(frac0 + (y - y0) * 0.25 / max(span, 1.0), 0.0, 1.0))
                self.setCut(self.cutAxis, f)
                try:
                    sl = slicer.modules.cardiacview.widgetRepresentation().self().cutSlider
                    sl.blockSignals(True); sl.value = f * 100; sl.blockSignals(False)
                except Exception: pass
            self._view().scheduleRender(); self._mAbort(it); return
        if getattr(self, "_wl", None) is None or not self._mine(): return
        (x0, y0), win0 = self._wl; x, y = it.GetEventPosition()
        if win0 is not None: self._winSet(win0, x - x0, y - y0)
        self._view().scheduleRender(); self._mAbort(it)

    def _syncCutUI(self):
        try:
            w = slicer.modules.cardiacview.widgetRepresentation().self()
            idx = next((i for i, (_, a) in enumerate(CUT_MODES) if a == self.cutAxis), None)
            if self.cutAxis == "LOCK": idx = 1
            if idx is not None: w.cutCombo.blockSignals(True); w.cutCombo.setCurrentIndex(idx); w.cutCombo.blockSignals(False)
            w.cutSlider.blockSignals(True); w.cutSlider.value = getattr(self, "cutFrac", 0.5) * 100; w.cutSlider.blockSignals(False)
            w.lockCheck.blockSignals(True); w.lockCheck.checked = (self.cutAxis == "LOCK"); w.lockCheck.blockSignals(False)   # 固定中は必ずチェックを見せる（外せば画面の正面に戻る）
        except Exception: pass

    # ---- 断面（2D）の右ドラッグ: DICOM ビューアと同じ感覚
    def _sPress(self, it, nm):
        if not self._mine(): return
        mode = getattr(self, "rmode", "zoom")
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if mode == "zoom" or inter.GetCurrentInteractionMode() == inter.Place: return
        sw = slicer.app.layoutManager().sliceWidget(nm); sn = sw.mrmlSliceNode()
        cn = sw.sliceLogic().GetSliceCompositeNode(); vol = slicer.mrmlScene.GetNodeByID(cn.GetBackgroundVolumeID() or "")
        dn = vol.GetDisplayNode() if vol is not None else None
        wl = (dn.GetWindow(), dn.GetLevel()) if dn is not None and hasattr(dn, "GetWindow") else None
        isCut = (nm == "Red" and getattr(self, "layoutKind", "") == "cut" and self.cutAxis is not None)
        self._sdrag = dict(nm=nm, mode=mode, p0=it.GetEventPosition(), last=it.GetEventPosition(), wl=wl, dn=dn,
                           M0=slicer.util.arrayFromVTKMatrix(sn.GetSliceToRAS()), X0=slicer.util.arrayFromVTKMatrix(sn.GetXYToRAS()),
                           off0=sn.GetSliceOffset(), isCut=isCut)
        self._mAbort(it)

    def _sMove(self, it):
        d = getattr(self, "_sdrag", None)
        if d is None: return
        sw = slicer.app.layoutManager().sliceWidget(d["nm"]); sn = sw.mrmlSliceNode()
        (x0, y0), (x, y) = d["p0"], it.GetEventPosition()
        if d["mode"] == "window" and d["wl"] is not None:
            d["dn"].SetAutoWindowLevel(False)
            d["dn"].SetWindowLevel(max(1.0, d["wl"][0] + (x - x0) * 2.0), d["wl"][1] - (y - y0) * 2.0)   # 横 = 幅、縦 = 中心
        elif d["mode"] == "pan":
            X = d["X0"]; a = X @ np.array([x0, y0, 0, 1.0]); b = X @ np.array([x, y, 0, 1.0])
            M = d["M0"].copy(); M[:3, 3] += (a - b)[:3]
            vm = vtk.vtkMatrix4x4()
            for r in range(4):
                for c in range(4): vm.SetElement(r, c, float(M[r, c]))
            sn.GetSliceToRAS().DeepCopy(vm); sn.UpdateMatrices()
        elif d["mode"] == "cut":
            if d["isCut"]:                                                       # 3D の切断面を表示している断面 → 切る位置そのものを動かす
                dy = y - d["last"][1]
                if dy: self.nudgeCut(dy * 0.5); self._syncCutUI()
            else: sn.SetSliceOffset(d["off0"] + (y - y0) * 0.5)                   # ふつうの断面 → スライス送り（0.5 mm / ピクセル）
        d["last"] = (x, y)
        self._mAbort(it)

    def _delKey(self, it, nm):
        """Delete / BackSpace = 計測を 1 つ丸ごと消す（心臓・大動脈どちらの画面でも）。
        マウスを乗せている計測 → それ。描いている途中 → それ。どれでもなければ最後に触った計測"""
        if (it.GetKeySym() or "") == "Escape" and getattr(self, "paintOn", False):   # Esc = パッチを塗り終わる
            try: slicer.modules.cardiacview.widgetRepresentation().self().paintButton.checked = False
            except Exception: self.paintEnd()
            return
        if (it.GetKeySym() or "") not in ("Delete", "BackSpace"): return
        cands = [n for n in slicer.util.getNodesByClass("vtkMRMLMarkupsNode")
                 if n.GetAttribute("CV.measure") or n.GetAttribute("SA.measure")]
        if not cands: return
        target = None
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place:
            pid = slicer.app.applicationLogic().GetSelectionNode().GetActivePlaceNodeID()
            target = next((n for n in cands if n.GetID() == pid), None)
            inter.SetCurrentInteractionMode(inter.ViewTransform)
        if target is None:
            for n in cands:
                d = n.GetDisplayNode()
                try:
                    if d is not None and d.GetActiveComponentType() != d.ComponentNone: target = n; break
                except Exception: pass
        if target is None: target = max(cands, key=lambda n: n.GetMTime())
        name = target.GetName()
        sa = None
        if target.GetAttribute("SA.measure"):
            try: sa = slicer.modules.aortasizing.widgetRepresentation().self().logic
            except Exception: sa = None
        if sa is not None and hasattr(sa, "deleteMeasure"): sa.deleteMeasure(target)
        else: slicer.mrmlScene.RemoveNode(target)
        self.rulers = [n for n in getattr(self, "rulers", []) if slicer.mrmlScene.IsNodePresent(n)]
        self._flash(f"消しました：{name}")
        try:
            for i, t in (getattr(slicer, "_cvMouse", None) or {}).get("tags", []):
                if i is it:
                    try: it.GetCommand(t).SetAbortFlag(1)
                    except Exception: pass
        except Exception: pass

    def _sKey(self, it, nm):
        """4 画面: マウスを乗せた断面で [ ] = 線を 1° 回す（Shift で 5°）"""
        if not self._mine() or getattr(self, "layoutKind", "") != "four": return
        k = it.GetKeySym() or ""
        if k in ("bracketleft", "bracketright", "braceleft", "braceright"):
            self.rotateMPR(nm, (5.0 if it.GetShiftKey() else 1.0) * (1 if k in ("bracketleft", "braceleft") else -1)); self._mAbort(it)

    def _dbl(self, it, nm):
        if not self._mine() or it.GetRepeatCount() < 1: return
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place: return
        qt.QTimer.singleShot(0, lambda: self._toggleMaximize(nm)); self._mAbort(it)

    def _sWheel(self, it, nm, d):
        """3D の切断面を映している断面（3D＋切断面の左）では、ホイール = 切る位置（3D と一緒に動く。別の所へ飛ばない）"""
        if not self._mine() or it.GetControlKey(): return
        if nm == "Red" and getattr(self, "layoutKind", "") == "cut" and self.cutAxis is not None:
            self.nudgeCut(d * (5.0 if it.GetShiftKey() else 1.0)); self._syncCutUI(); self._mAbort(it)

    def _sRelease(self, it):
        if getattr(self, "_sdrag", None) is not None:
            self._sdrag = None; self._mAbort(it)

    def _mWheel(self, it, d):
        if not self._mine(): return
        self._vrFast(True); self._vrSettle()
        if it.GetControlKey() or self.cutAxis is None: return
        step = 5.0 if it.GetShiftKey() else 1.0                       # ホイール 1 目盛 = 1mm、Shift で 5mm
        frac = self.nudgeCut(d * step)
        try:
            sl = slicer.modules.cardiacview.widgetRepresentation().self().cutSlider
            if frac is not None: sl.blockSignals(True); sl.value = frac * 100; sl.blockSignals(False)
        except Exception: pass
        self._mAbort(it)

    # ---------------------------------------------------------------- look
    # VR の「光の回り込み」（全体照明）は、この PC で止まるほど重かったので使わない。VR は光の当て方（環境光・拡散・つや）だけで陰影を変える
    SHADE = {"なし": dict(ssao=False, rad=10.0, ker=32, k2f=2.2, k2h=3.5, vamb=0.30, vdif=0.75, vspec=0.25),
             "ふつう": dict(ssao=True, rad=10.0, ker=32, k2f=3.0, k2h=4.0, vamb=0.18, vdif=0.88, vspec=0.35),
             "強め": dict(ssao=True, rad=14.0, ker=32, k2f=4.5, k2h=5.0, k2b=3.0, vamb=0.08, vdif=1.00, vspec=0.45)}
    # 重さの約束: どの段階も 1 コマの計算量は前と同じ（SSAO の点の数は 32 まで）。違うのは光の当て方・つやだけ。動かしている間に増える計算はない
    SHADE_KEY = "HUCViewS/shading"

    def _shade(self):
        lv = getattr(self, "shadeLevel", None)
        if lv is None:
            try: lv = str(qt.QSettings().value(self.SHADE_KEY) or "ふつう")
            except Exception: lv = "ふつう"
            self.shadeLevel = lv if lv in self.SHADE else "ふつう"
        return self.SHADE[self.shadeLevel]

    def _applyVRShade(self):
        """VR の陰影: 環境光を下げて拡散・つやを上げる（重さは変わらない）"""
        s = self._shade()
        for dn in (getattr(self, "vrDisplay", None), getattr(self, "vr4D", None)):
            if dn is None or not hasattr(dn, "GetVolumePropertyNode"): continue
            pn = dn.GetVolumePropertyNode(); vp = pn.GetVolumeProperty() if pn is not None else None
            if vp is None: continue
            vp.ShadeOn(); vp.SetAmbient(s["vamb"]); vp.SetDiffuse(s["vdif"]); vp.SetSpecular(s["vspec"])

    def setShading(self, level, measure=True):
        """陰影: なし／ふつう／強め。面 = 環境光遮蔽の強さと光の向きのコントラスト、VR = 光の回り込み。重すぎる PC は 1 段下げる"""
        self.shadeLevel = level if level in self.SHADE else "ふつう"
        try: qt.QSettings().setValue(self.SHADE_KEY, self.shadeLevel)
        except Exception: pass
        self.studioLighting(getattr(self, "_bgIndex", 0), ssao=True); self._applyVRShade()
        msg = ""
        if measure and self.shadeLevel != "なし":
            ms = self._frameMs(4)
            if ms > 2.5 * self.PERF_TARGET_MS:                                 # 1 コマ 75 ms を超える（13 fps 未満）→ 1 段下げる
                down = {"強め": "ふつう", "ふつう": "なし"}[self.shadeLevel]
                self.shadeLevel = down; self.studioLighting(getattr(self, "_bgIndex", 0), ssao=True); self._applyVRShade()
                msg = f"この PC では重かったので「{down}」にしました（1 コマ {ms:.0f} ms）"
        self._view().forceRender(); return msg

    def studioLighting(self, bgIndex=0, ssao=False):
        v = self._view(); vn = self._viewNode()
        vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
        self.setBackground(bgIndex)
        try:
            ren = v.renderWindow().GetRenderers().GetFirstRenderer()
            ren.RemoveAllLights()
            s = self._shade(); self._bgIndex = bgIndex
            lk = vtk.vtkLightKit(); lk.SetKeyLightIntensity(0.95); lk.SetKeyLightWarmth(0.6); lk.SetFillLightWarmth(0.4)
            lk.SetKeyToFillRatio(s["k2f"]); lk.SetKeyToHeadRatio(s["k2h"]); lk.SetKeyToBackRatio(s.get("k2b", 4.0))      # 陰影の段階で、明るい面と暗い面の差を変える
            lk.SetKeyLightAzimuth(25); lk.SetKeyLightElevation(45)
            lk.AddLightsToRenderer(ren)
            ssao = bool(ssao) and s["ssao"]
            ren.SetUseSSAO(ssao)
            if ssao: ren.SetSSAORadius(s["rad"]); ren.SetSSAOBias(0.5); ren.SetSSAOKernelSize(s["ker"]); ren.SetSSAOBlur(True)
        except Exception as e:
            print("lighting:", e)
        v.forceRender()

    def setBackground(self, i):
        vn = self._viewNode()
        col = [(0, 0, 0), (0.16, 0.17, 0.19), (1, 1, 1)][i]
        vn.SetBackgroundColor(*col); vn.SetBackgroundColor2(*col)

    # ---------------------------------------------------------------- camera
    def _sceneCenter(self):
        if self.bounds is None: self._updateBounds()
        if self.bounds is None: return np.array([0, 0, 0.0])
        lo, hi = self.bounds; return (lo + hi) / 2

    def _sceneRadius(self):
        if self.bounds is None: return 200.0
        lo, hi = self.bounds; return float(np.linalg.norm(hi - lo) / 2)

    def _visibleBounds(self):
        B = [n.GetPolyData().GetBounds() for name, n in self.layerModels.items()
             if n and n.GetPolyData() and n.GetPolyData().GetNumberOfPoints() and self.visible.get(name, True) and name != "胸骨ワイヤー"]
        if not B: return self.bounds
        A = np.array(B); return (A[:, 0::2].min(0), A[:, 1::2].max(0))

    def setView(self, key, fov=30):
        self.flying = False
        vb = self._visibleBounds()
        if vb is None: return
        lo, hi = vb; c = (lo + hi) / 2; r = float(np.linalg.norm(hi - lo) / 2); D = float(np.max(hi - lo)) / 2 / math.tan(math.radians(fov / 2)) * 1.12
        dirs = {"A": (0, 1, 0), "P": (0, -1, 0), "L": (-1, 0, 0), "R": (1, 0, 0), "S": (0, 0, 1), "SURG": (0.35, 0.80, 0.50)}
        d = np.array(dirs.get(key, (0, 1, 0)), float); d /= np.linalg.norm(d)
        up = (0, 1, 0) if key == "S" else (0, 0, 1)
        cam = self._camera()
        cam.SetPosition(*(c + d * D)); cam.SetFocalPoint(*c); cam.SetViewUp(*up)
        cam.GetCamera().SetViewAngle(fov); cam.ResetClippingRange()
        self._fitParallel()
        if self.cutAxis == "VIEW": self.setCut("VIEW", self.cutFrac)
        self._view().forceRender()

    def setFov(self, fov):
        cam = self._camera()
        if cam: cam.GetCamera().SetViewAngle(fov); self._view().forceRender()

    def _centerline(self):
        best = None
        for n in slicer.util.getNodesByClass("vtkMRMLMarkupsCurveNode"):
            if n.GetNumberOfControlPoints() > 20 and (best is None or n.GetNumberOfControlPoints() > best.GetNumberOfControlPoints()): best = n
        return best

    def flyAorta(self, frac, onlyIfFlying=False):
        if onlyIfFlying and not self.flying: return
        cl = self._centerline()
        if cl is None: slicer.util.warningDisplay("中心線がありません。先に「大動脈サイジング」を実行してください。"); return
        pts = slicer.util.arrayFromMarkupsCurvePoints(cl, world=True)
        n = len(pts); i = int(np.clip(frac * (n - 1), 0, n - 12)); j = min(i + 10, n - 1)
        self.flying = True
        self.setLayerVisible("血液・血管", False)  # 血管の全グループ
        cam = self._camera()
        cam.SetPosition(*pts[i]); cam.SetFocalPoint(*pts[j]); cam.SetViewUp(0, 0, 1)
        cam.GetCamera().SetViewAngle(100); cam.ResetClippingRange(); self._view().forceRender()

    # ---------------------------------------------------------------- measure
    def placeMarkup(self, cls, name):
        node = slicer.mrmlScene.AddNewNodeByClass(cls, name)
        self._put(node)
        try: node.GetDisplayNode().SetPropertiesLabelVisibility(True)
        except Exception: pass
        slicer.modules.markups.logic().SetActiveList(node)
        slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)
