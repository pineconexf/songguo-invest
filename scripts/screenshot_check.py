# -*- coding: utf-8 -*-
"""用 Edge headless 截图检查网站视觉"""
import subprocess, time, os

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
OUT_DIR = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots'
os.makedirs(OUT_DIR, exist_ok=True)

pages = [
    ('home', 'http://127.0.0.1:4321/'),
    ('philosophy', 'http://127.0.0.1:4321/philosophy/'),
    ('methodology', 'http://127.0.0.1:4321/methodology/'),
    ('macro', 'http://127.0.0.1:4321/macro/'),
    ('portfolio', 'http://127.0.0.1:4321/portfolio/'),
    ('tools', 'http://127.0.0.1:4321/tools/'),
]

# 清场
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1)

for name, url in pages:
    out = os.path.join(OUT_DIR, f'{name}.png')
    if os.path.exists(out):
        os.remove(out)
    profile = os.path.join(OUT_DIR, f'_profile_{name}')
    # 用独立 profile + 窗口尺寸 1440x900
    r = subprocess.run(
        [EDGE, '--headless=new', '--disable-gpu', f'--user-data-dir={profile}',
         '--window-size=1440,900', f'--screenshot={out}', url],
        capture_output=True, timeout=60,
    )
    # 轮询等待
    for _ in range(20):
        if os.path.exists(out) and os.path.getsize(out) > 0:
            break
        time.sleep(1)
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print(f'{name}: {"OK" if size > 0 else "MISSING"} ({size//1024}KB)')

print('done')
