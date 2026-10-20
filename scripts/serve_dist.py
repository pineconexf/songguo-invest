#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地预览已构建的 Astro 站点（适配 base 子路径部署）。

为什么要它（2026-10-20）：
  astro.config.mjs 里 base='/songguo-invest/'（GitHub Pages 子路径部署），
  产物里资源路径写死成 /songguo-invest/_astro/...，
  但 dist/ 目录结构是扁平的（dist/_astro/...），没有 songguo-invest/ 这一层。
  所以 `python -m http.server --directory dist` 访问 /songguo-invest/tools/... 直接 404，
  页面渲染不出来（astro-island 挂不上，#root 是空 div）。

  本脚本把请求路径的 base 前缀 strip 掉再映射到 dist 下的真实文件，
  行为与线上 GitHub Pages 一致（线上是 gh-pages 仓库根 = /songguo-invest/）。

用法：
  python scripts/serve_dist.py [port]        # 默认 4321
  python scripts/serve_dist.py 4321 dist
"""
import os
import sys
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE = os.environ.get('ASTRO_BASE', '/songguo-invest/').rstrip('/')
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4321
DIST = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(ROOT, 'dist')

if not os.path.isdir(DIST):
    sys.exit('❌ 找不到构建产物目录: %s（先跑 npm run build）' % DIST)


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # strip base 前缀：/songguo-invest/tools/x -> /tools/x
        p = path.split('?', 1)[0].split('#', 1)[0]
        if BASE and p.startswith(BASE):
            p = p[len(BASE):]
        p = p.lstrip('/')
        full = os.path.join(DIST, p.replace('/', os.sep))
        # 目录 -> index.html
        if os.path.isdir(full):
            full = os.path.join(full, 'index.html')
        return full

    def end_headers(self):
        # 本地预览禁用缓存，改完源码重跑 build 就能看到
        self.send_header('Cache-Control', 'no-store')
        SimpleHTTPRequestHandler.end_headers(self)

    def log_message(self, fmt, *args):
        pass  # 静默


if __name__ == '__main__':
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), functools.partial(Handler, directory=DIST))
    print('✓ 本地预览: http://127.0.0.1:%d%s/  (dist=%s)' % (PORT, BASE, DIST))
    print('  深分分析: http://127.0.0.1:%d%s/tools/stockscore/deep/' % (PORT, BASE))
    print('  对话:     http://127.0.0.1:%d%s/tools/stockscore/talk/' % (PORT, BASE))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
