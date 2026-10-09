# -*- coding: utf-8 -*-
"""HUCViewS を GitHub に公開する（開発 PC の Slicer / Python で実行）。
  1. 開発中のソース（HeartView/app ＋ tools/CardiacView）をこのリポジトリの app/ にまとめる（内部のパス・NAS 名が無いか確認）
  2. dist/HUCViewS-app.zip と latest.json、Windows 用 exe（IExpress）を作る
  3. git commit / push、GitHub Release（v版）を作って添付
使い方: REL_NOTES = "変更点"; exec(open("<このリポジトリ>/tools/make_release.py", encoding="utf-8").read())
"""
import os, re, shutil, json, hashlib, zipfile, subprocess, time

DEV = globals().get("REL_DEV") or os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents", "CT_view")
REPO_DIR = os.path.join(DEV, "HUCViewS_repo")
REPO = "lfb15345-del/HUCViewS"
SRC_APP = os.path.join(DEV, "HeartView", "app")
SRC_CV = os.path.join(DEV, "tools", "CardiacView", "CardiacView.py")
DIST = os.path.join(REPO_DIR, "dist")
FORBID = [r"\\\\[A-Za-z0-9_-]+\\"]                       # 公開してはいけない内部情報（UNC パスなど）。個別の語は下の非公開ファイルに書く
try: FORBID += [l.strip() for l in open(os.path.join(REPO_DIR, ".private_forbid.txt"), encoding="utf-8") if l.strip()]
except Exception: pass
ENV = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
NOWIN = 0x08000000


def run(cmd, check=True):
    r = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV, creationflags=NOWIN)
    print("$", " ".join(cmd), "->", r.returncode, (r.stdout + r.stderr).strip()[-800:])
    if check and r.returncode != 0: raise RuntimeError(f"失敗: {' '.join(cmd)}")
    return r


def assemble(ver):
    app = os.path.join(REPO_DIR, "app")
    if os.path.exists(app): shutil.rmtree(app)
    shutil.copytree(SRC_APP, app, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "version.txt"))
    os.makedirs(os.path.join(app, "modules", "CardiacView"), exist_ok=True)
    shutil.copy2(SRC_CV, os.path.join(app, "modules", "CardiacView", "CardiacView.py"))
    open(os.path.join(app, "version.txt"), "w", encoding="ascii").write(ver + "\n")
    bad = []
    for root, dirs, files in os.walk(REPO_DIR):                       # リポジトリ全体を確認（.git・dist・非公開ファイルは除く）
        dirs[:] = [d for d in dirs if d not in (".git", "dist", "__pycache__")]
        for f in files:
            if f == ".private_forbid.txt" or not f.endswith((".py", ".ps1", ".bat", ".txt", ".md", ".sh", ".json")): continue
            t = open(os.path.join(root, f), encoding="utf-8", errors="ignore").read()
            for pat in FORBID:
                for m in re.finditer(pat, t):
                    line = t[:m.start()].count("\n") + 1
                    bad.append(f"{os.path.relpath(os.path.join(root, f), REPO_DIR)}:{line}: {pat}")
    if bad: raise RuntimeError("内部情報が含まれています:\n" + "\n".join(bad[:20]))
    return app


def build_zip(app, ver):
    os.makedirs(DIST, exist_ok=True)
    for f in os.listdir(DIST): os.remove(os.path.join(DIST, f))
    zp = os.path.join(DIST, "HUCViewS-app.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(app):
            for f in files:
                p = os.path.join(root, f); z.write(p, os.path.relpath(p, REPO_DIR).replace("\\", "/"))
    sha = hashlib.sha256(open(zp, "rb").read()).hexdigest()
    man = {"version": ver, "app_zip": f"https://github.com/{REPO}/releases/download/v{ver}/HUCViewS-app.zip",
           "sha256": sha, "min_slicer": "5.8", "published": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    json.dump(man, open(os.path.join(DIST, "latest.json"), "w", encoding="utf-8"), indent=2)
    for src, dst, eol in (("installer/windows/install.ps1", "install.ps1", b"\r\n"), ("installer/mac/install_mac.sh", "install_mac.sh", b"\n")):
        b = open(os.path.join(REPO_DIR, src), "rb").read().replace(b"\r\n", b"\n")       # Mac 用は LF、Windows 用は CRLF に必ずそろえる
        open(os.path.join(DIST, dst), "wb").write(b.replace(b"\n", eol))
    return man


def build_exe():
    """Windows 標準の IExpress で、install.ps1 を実行するだけの小さな exe を作る（署名なし）"""
    work = os.path.join(DIST, "_iexp"); os.makedirs(work, exist_ok=True)
    shutil.copy2(os.path.join(REPO_DIR, "installer", "windows", "install.ps1"), os.path.join(work, "install.ps1"))
    target = os.path.join(DIST, "HUCViewS_Windows.exe")
    sed = f"""[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=HUCViewS
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="install.ps1"
[SourceFiles]
SourceFiles0={work}\\
[SourceFiles0]
%FILE0%=
"""
    sp = os.path.join(work, "hucviews.sed"); open(sp, "w", encoding="mbcs").write(sed)
    iexp = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "iexpress.exe")
    r = subprocess.run([iexp, "/N", "/Q", sp], capture_output=True, text=True, env=ENV, creationflags=NOWIN, timeout=120)
    shutil.rmtree(work, ignore_errors=True)
    if not os.path.exists(target): raise RuntimeError(f"exe を作れませんでした: {r.returncode} {r.stdout} {r.stderr}")
    return target


def publish(ver, notes):
    run(["git", "add", "-A"])
    st = run(["git", "status", "--porcelain"], check=False).stdout.strip()
    if st: run(["git", "commit", "-m", f"HUCViewS {ver}"])
    run(["git", "push", "-u", "origin", "main"])
    assets = [os.path.join(DIST, f) for f in ("HUCViewS-app.zip", "latest.json", "install.ps1", "install_mac.sh", "HUCViewS_Windows.exe") if os.path.exists(os.path.join(DIST, f))]
    run(["gh", "release", "create", f"v{ver}", "--repo", REPO, "--title", f"HUCViewS {ver}", "--notes", notes or f"HUCViewS {ver}", "--latest"] + assets)


def main():
    ver = globals().get("REL_VERSION") or time.strftime("%Y%m%d-%H%M")
    notes = globals().get("REL_NOTES") or ""
    app = assemble(ver); man = build_zip(app, ver)
    try: build_exe()
    except Exception as e: print("exe:", e)
    print("version", ver, "sha256", man["sha256"][:12])
    if not globals().get("REL_DRYRUN"): publish(ver, notes)
    print("[release] 完了", ver)


main()
