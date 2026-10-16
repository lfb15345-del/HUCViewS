# -*- coding: utf-8 -*-
r"""
AortaSizing — ステントグラフト（EVAR / TEVAR）サイジング（研究・教育用、非医療機器）
画面と操作は 3mensio Vascular の血管ワークフローを手本にしている:
  1. 血管抽出（AI ラベル + 鼠径部までの延長）  2. 中心線（自動 → 点のドラッグ / 追加 / 右クリック削除で修正）
  3. 計測: ストレッチ像のカーソル線 ⇔ 直交断面が連動、断面は自動輪郭（制御点で修正）、Dmax / Dmin / Deq、
     ベースライン（最下位腎動脈など）からの距離、マーカー、内弯 / 外弯の長さ、屈曲角、ネック計測、クロック位置
  4. EVAR / TEVAR のまとめとレポート
計算の土台: 中心線 = VMTK（ExtractCenterline）、断面 = 血管表面を中心線に直交する平面で切る（VMTK Cross-Section Analysis と同じ方式）
"""

import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)
for _k in [k for k in list(sys.modules) if k == "AortaSizingLib" or k.startswith("AortaSizingLib.")]:
    del sys.modules[_k]                               # 読み直し（Reload）の時も部品を新しく読む
from AortaSizingLib.common import *
from AortaSizingLib import ui_base, ui_build, ui_measure, ui_tevar, ui_postop, ui_output, logic_core, logic_section, logic_view, logic_input, logic_centerfix, logic_marker, logic_tevar, logic_dissection, logic_postop, logic_lengths, logic_report, logic_plaque, ui_research

# 部品の地図（どこに何があるか）
#   AortaSizingLib/ui_base.py — 画面の部品・共通（カード・ボタン・ページ切り替え・お知らせ）
#   AortaSizingLib/ui_build.py — 画面を組み立てる（setup）
#   AortaSizingLib/ui_measure.py — 1 中心線・2 計測 の画面の動き（テンプレート・印・手動計測・枝のチップ・長さ）
#   AortaSizingLib/ui_tevar.py — 3 計画 の画面の動き（真腔・仮想グラフト・範囲・SINE）
#   AortaSizingLib/ui_postop.py — 4 術後 の画面の動き（読み込み・比べる・広がり・重ね合わせの手直し）
#   AortaSizingLib/ui_output.py — 5 出力 の画面の動き（CSV・PDF・PNG）
#   AortaSizingLib/logic_core.py — 中心線の自動作成・経路・伸ばした画像
#   AortaSizingLib/logic_section.py — 断面の輪郭（外周・内腔）と径・径の推移
#   AortaSizingLib/logic_view.py — 画面のレイアウト・断面とストレッチ像の描画・表示の保存と復元
#   AortaSizingLib/logic_input.py — マウス・キーボード（断面・ストレッチ像・3D）
#   AortaSizingLib/logic_centerfix.py — 中心線を直す（クリック・合わせるモード・手で直す・中心に寄せる）
#   AortaSizingLib/logic_marker.py — 印（マーカー）・手動計測・ベースライン・クロック
#   AortaSizingLib/logic_tevar.py — TEVAR の計画: 仮想グラフト（広がりの予測）・SINE の目安・エントリー・治療長
#   AortaSizingLib/logic_dissection.py — 解離: 真腔・偽腔のたどり・らせん・解離の形の CSV
#   AortaSizingLib/logic_postop.py — 術後 CT: 読み込み・重ね合わせ・金属（ステント）・比べる・広がり
#   AortaSizingLib/logic_lengths.py — 長さ: 中心線・内弯・外弯、自動の目印、3D の定規
#   AortaSizingLib/logic_report.py — まとめ・画像・PDF・CSV・レポート
#   AortaSizingLib/ui_research.py — 6 研究（隠しタブ・Ctrl+Shift+R）: プラーク・解析用の CSV
#   AortaSizingLib/logic_plaque.py — 研究用: プラーク・壁在血栓（厚み・CT 値・番号・マスク）
#   AortaSizingLib/common.py — 定数・テンプレート・小さな関数・_Overlay



# ============================================================================ module
class AortaSizing(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "大動脈サイジング"
        parent.categories = ["HUCVS"]
        parent.dependencies = []
        parent.contributors = ["HUCVS"]
        parent.helpText = "ステントグラフト用の大動脈サイジング（研究・教育用）。3mensio Vascular の操作を手本にしている。"
        parent.acknowledgementText = "中心線: VMTK (SlicerVMTK)。"


class AortaSizingWidget(ui_base.WidgetBaseMixin, ui_build.WidgetBuildMixin, ui_measure.MeasureUIMixin, ui_tevar.TevarUIMixin, ui_postop.PostOpUIMixin, ui_output.OutputUIMixin, ui_research.ResearchUIMixin, ScriptedLoadableModuleWidget):
    """画面。中身は AortaSizingLib/ui_*.py"""


# ============================================================================ logic
class AortaSizingLogic(logic_core.CoreMixin, logic_section.SectionMixin, logic_view.ViewMixin, logic_input.InputMixin, logic_centerfix.CenterlineFixMixin, logic_marker.MarkerMixin, logic_tevar.TevarPlanMixin, logic_dissection.DissectionMixin, logic_postop.PostOpMixin, logic_lengths.LengthMixin, logic_report.ReportMixin, logic_plaque.PlaqueMixin, ScriptedLoadableModuleLogic):
    """計算。中身は AortaSizingLib/logic_*.py"""


for _m in (ui_base, ui_build, ui_measure, ui_tevar, ui_postop, ui_output, logic_core, logic_section, logic_view, logic_input, logic_centerfix, logic_marker, logic_tevar, logic_dissection, logic_postop, logic_lengths, logic_report, logic_plaque, ui_research):          # 部品の中から本体のクラスを名前で使えるように（setup で AortaSizingLogic() など）
    _m.AortaSizingLogic = AortaSizingLogic; _m.AortaSizingWidget = AortaSizingWidget; _m.AortaSizing = AortaSizing
