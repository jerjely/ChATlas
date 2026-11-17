"""Runs inside the freshly installed ChATlas environment: installs the bundled wheels
(no internet needed) and creates the shortcuts / app bundle.  `--uninstall` removes them."""
import glob
import os
import shutil
import subprocess
import sys
import zipfile

PREFIX = os.environ.get("PREFIX") or sys.prefix
APP_NAME = "ChATlas"


def log(msg):
    print(f"[ChATlas post-install] {msg}", flush=True)


def install_wheels():
    zf = os.path.join(PREFIX, "wheelhouse.zip")
    if not os.path.exists(zf):
        log("no wheelhouse.zip (already installed?)")
        return
    wh = os.path.join(PREFIX, "wheelhouse")
    with zipfile.ZipFile(zf) as z:
        z.extractall(wh)
    wheels = sorted(glob.glob(os.path.join(wh, "*.whl")))
    log(f"installing {len(wheels)} bundled wheels")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                           "--no-warn-script-location", "--disable-pip-version-check", *wheels])
    shutil.rmtree(wh, ignore_errors=True)
    os.remove(zf)


def asset(name):
    import chatlas
    return os.path.join(os.path.dirname(chatlas.__file__), "assets", name)


# ------------------------------------------------------------------ Windows
def _ps(cmd):
    subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd])


def windows(remove=False):
    if remove:
        _ps("foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) "
            "{ Remove-Item (Join-Path $d 'ChATlas.lnk') -ErrorAction SilentlyContinue }")
        return
    ico = os.path.join(PREFIX, "chatlas.ico")
    shutil.copy(asset("chatlas.ico"), ico)
    data = os.path.join(os.path.expanduser("~"), "ChATlas")
    os.makedirs(data, exist_ok=True)
    pyw = os.path.join(PREFIX, "pythonw.exe")
    _ps("$w = New-Object -ComObject WScript.Shell; "
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "$s = $w.CreateShortcut((Join-Path $d 'ChATlas.lnk')); "
        f"$s.TargetPath = '{pyw}'; $s.Arguments = '-m chatlas'; $s.IconLocation = '{ico}'; "
        f"$s.WorkingDirectory = '{data}'; $s.Description = 'ChATlas - retina connectome explorer'; $s.Save() }}")
    log("shortcuts created (desktop and Start menu)")


# ------------------------------------------------------------------ macOS
def _owner():
    st = os.stat(PREFIX)
    return st.st_uid, st.st_gid


def _home_of_prefix():
    import pwd
    return pwd.getpwuid(_owner()[0]).pw_dir


def mac(remove=False):
    targets = ["/Applications/ChATlas.app", os.path.join(_home_of_prefix(), "Applications", "ChATlas.app")]
    if remove:
        for t in targets:
            shutil.rmtree(t, ignore_errors=True)
        return
    for app in targets:
        try:
            os.makedirs(os.path.dirname(app), exist_ok=True)
            shutil.rmtree(app, ignore_errors=True)
            os.makedirs(os.path.join(app, "Contents", "MacOS"))
            os.makedirs(os.path.join(app, "Contents", "Resources"))
            break
        except OSError:
            continue
    else:
        log("could not create ChATlas.app")
        return
    import chatlas
    data = os.path.join(_home_of_prefix(), "ChATlas")
    os.makedirs(data, exist_ok=True)
    shutil.copy(asset("chatlas.icns"), os.path.join(app, "Contents", "Resources", "chatlas.icns"))
    exe = os.path.join(app, "Contents", "MacOS", "ChATlas")
    with open(exe, "w") as f:
        f.write(f'#!/bin/bash\ncd "{data}"\nexec "{os.path.join(PREFIX, "bin", "python")}" -m chatlas\n')
    os.chmod(exe, 0o755)
    with open(os.path.join(app, "Contents", "Info.plist"), "w") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>ChATlas</string>
  <key>CFBundleDisplayName</key><string>ChATlas</string>
  <key>CFBundleIdentifier</key><string>hu.pte.chatlas</string>
  <key>CFBundleExecutable</key><string>ChATlas</string>
  <key>CFBundleIconFile</key><string>chatlas</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{chatlas.__version__}</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
""")
    if os.geteuid() == 0:                      # pkg scripts may run as root: give the app to the user
        uid, gid = _owner()
        for root, dirs, files in os.walk(app):
            for p in [root] + [os.path.join(root, x) for x in dirs + files]:
                os.chown(p, uid, gid)
        os.chown(data, uid, gid)
    subprocess.call(["touch", app])
    log(f"created {app}")


# ------------------------------------------------------------------ Linux (desktop entry)
def linux(remove=False):
    d = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
    f = os.path.join(d, "chatlas.desktop")
    if remove:
        if os.path.exists(f):
            os.remove(f)
        return
    os.makedirs(d, exist_ok=True)
    with open(f, "w") as fh:
        fh.write(f"[Desktop Entry]\nType=Application\nName=ChATlas\nComment=Retina connectome explorer\n"
                 f"Exec={os.path.join(PREFIX, 'bin', 'python')} -m chatlas\nIcon={asset('logo_256.png')}\nTerminal=false\n"
                 f"Categories=Science;\n")
    log(f"created {f}")


def main():
    remove = "--uninstall" in sys.argv
    if not remove:
        install_wheels()
    try:
        {"win32": windows, "darwin": mac}.get(sys.platform, linux)(remove=remove)
    except Exception as e:                       # never fail the installation because of a shortcut
        log(f"shortcut step skipped: {e}")


if __name__ == "__main__":
    main()
