"""Flatten sys.path extras into a site-packages copy, for editor IntelliSense.

Some packages (e.g. rerun-sdk) install a .pth file that appends a
subdirectory of site-packages to sys.path at interpreter start. Python
itself resolves this at runtime, but static analyzers (basedpyright,
Pyrefly, ...) reading a plain copy of site-packages from .stubs/ don't
process .pth files, so they never see those subdirectories.

Rather than parsing .pth files by hand (which only handles the exact
patterns we've seen so far), this asks the real interpreter what its
resolved sys.path actually is -- that covers .pth files with a single
path, .pth files with executable "import ..." lines, and anything else
site.py knows how to do -- then replays the same relative layout inside
a *copy* of site-packages (e.g. the one mirrored into .stubs/python for
the host-side editor). Any future dependency that redirects its import
root the same way is handled automatically, with no changes needed here.

Usage: python flatten_sys_path.py <path-to-site-packages-copy>
"""

import os
import shutil
import site
import sys


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-site-packages-copy>", file=sys.stderr)
        raise SystemExit(1)
    target_site_packages = sys.argv[1]

    real_site_packages = site.getsitepackages()[0]
    extras = [
        p
        for p in sys.path
        if p and p != real_site_packages and p.startswith(real_site_packages + os.sep)
    ]

    for extra in extras:
        if not os.path.isdir(extra):
            continue
        relative = os.path.relpath(extra, real_site_packages)
        target_extra = os.path.join(target_site_packages, relative)
        if not os.path.isdir(target_extra):
            continue
        for name in os.listdir(target_extra):
            src = os.path.join(target_extra, name)
            dst = os.path.join(target_site_packages, name)
            if os.path.exists(dst):
                continue
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            print(f"flattened {src} -> {dst}")


if __name__ == "__main__":
    main()
