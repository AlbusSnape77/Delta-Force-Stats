# -*- coding: utf-8 -*-
"""一键打包工具：把当前代码打成一个可双击运行的 exe，并按你给的版本名命名。

用法（任选其一）：
  * 双击 打包.bat，按提示输入版本名（如 v1.1）
  * 命令行: python build_exe.py v1.1

输出: dist/三角洲战绩分析器-<版本名>/三角洲战绩分析器-<版本名>.exe
（不填版本名则不带后缀。整个文件夹可拷给任何 Windows 电脑使用。）
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "三角洲战绩分析器"


def main():
    ver = sys.argv[1].strip() if len(sys.argv) > 1 else input("版本名(如 v1.1，直接回车则不带版本): ").strip()
    name = f"{BASE}-{ver}" if ver else BASE
    print(f"\n开始打包 -> dist/{name}/  （约 1-2 分钟，请稍候…）\n")

    env = {**os.environ, "DF_APP_NAME": name}
    t0 = time.monotonic()
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "dfstats_app.spec"],
        cwd=ROOT, env=env,
    )
    if r.returncode != 0:
        print("\n❌ 打包失败——往上翻 PyInstaller 的报错信息。")
        sys.exit(r.returncode)

    exe = os.path.join(ROOT, "dist", name, f"{name}.exe")
    print(f"\n✅ 打包完成（{time.monotonic() - t0:.0f} 秒）")
    print(f"   {exe}")
    print("   双击即用：自动启动并打开浏览器；数据存在 exe 旁边的 data/ 里。")

    # every build is KEPT — list what's in dist/ so versions are easy to track
    dist = os.path.join(ROOT, "dist")
    vers = sorted(d for d in os.listdir(dist) if os.path.isdir(os.path.join(dist, d))) if os.path.isdir(dist) else []
    if vers:
        print(f"\n现有版本（共 {len(vers)} 个，都保留着）：")
        for d in vers:
            print(f"   • dist/{d}/")


if __name__ == "__main__":
    main()
