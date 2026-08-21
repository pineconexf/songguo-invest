# -*- coding: utf-8 -*-
"""
松果网站数据同步链路（Hermes → 网站）
======================================
作用：把投资体系的最新数据一键同步到网站数据目录
  - 宏观信号：shibor_weekly.csv → src/data/macro_signal.json
  - 历史选股：逐月选股档案 → src/data/history_records.json
  - 实盘记录：live_records.json（手工维护，脚本只校验存在性）

用法：
  python scripts/sync_site_data.py          # 全量同步 + 构建
  python scripts/sync_site_data.py --build  # 同步后自动构建
  python scripts/sync_site_data.py --only-macro  # 只同步宏观
"""
import sys, io, os, subprocess, json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SITE = r"D:\pineconeinvestfiles\松果投资体系网站\01_网站开发"
SCRIPTS = os.path.join(SITE, "scripts")

def run(cmd, cwd=None):
    print(f"  → {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd or SITE, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    ⚠️ 退出码 {r.returncode}: {r.stderr[-300:] if r.stderr else ''}")
        return False
    return True

def main():
    args = sys.argv[1:]
    only_macro = "--only-macro" in args
    do_build = "--build" in args or "build" in args

    print("=" * 60)
    print("松果网站数据同步")
    print("=" * 60)

    # 1. 宏观信号
    print("\n[1/3] 宏观信号 (macro_signal.json)")
    run(f'python "{os.path.join(SCRIPTS, "build_macro_signal.py")}"')

    if not only_macro:
        # 2. 历史选股（需要在松果纯多头策略目录运行，依赖其数据）
        print("\n[2/3] 历史选股档案 (history_records.json)")
        ok = run(f'python "{os.path.join(SCRIPTS, "build_history_records.py")}"',
                 cwd=r"D:\pineconeinvestfiles\松果纯多头策略")
        if not ok:
            print("    ⚠️ 历史选股同步失败（可能数据源未更新），跳过")

    # 3. 实盘记录校验
    print("\n[3/3] 实盘档案 (live_records.json)")
    live_path = os.path.join(SITE, "src", "data", "live_records.json")
    if os.path.exists(live_path):
        try:
            d = json.load(open(live_path, encoding='utf-8'))
            print(f"  ✅ 存在: {d.get('count', '?')} 期")
        except Exception as e:
            print(f"  ⚠️ 解析失败: {e}")
    else:
        print("  ⚠️ 不存在，请先整理实盘记录")

    # 4. 构建
    if do_build:
        print("\n[+] 构建网站")
        run("npm run build")

    print("\n✅ 同步完成")

if __name__ == "__main__":
    main()
