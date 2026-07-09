"""Copies packages relocated by .pth files into a flat site-packages tree,
so static analyzers (which don't process .pth files) can see them.

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
