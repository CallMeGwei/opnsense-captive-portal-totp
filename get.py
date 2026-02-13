#!/usr/bin/env python3
"""Bootstrap installer for captive-portal-totp.

Downloads the project files to a temp directory and runs install.py.

Usage:
    curl -sL https://raw.githubusercontent.com/CallMeGwei/captive-portal-totp/main/get.py | python3
    curl -sL ... | python3 - --remove
    curl -sL ... | python3 - --gen-secret
"""

import os
import sys
import tempfile
import urllib.request

REPO = "CallMeGwei/captive-portal-totp"
BRANCH = "main"
BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

FILES = [
    "install.py",
    "SharedTOTP.php",
    "portal/index.html",
    "portal/css/signin.css",
]


def main():
    workdir = tempfile.mkdtemp(prefix="captive-portal-totp-")
    print(f"Downloading to {workdir} ...")

    for path in FILES:
        dest = os.path.join(workdir, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        urllib.request.urlretrieve(f"{BASE}/{path}", dest)
        print(f"  {path}")

    print()
    os.execvp(sys.executable, [sys.executable, os.path.join(workdir, "install.py")] + sys.argv[1:])


if __name__ == "__main__":
    main()
