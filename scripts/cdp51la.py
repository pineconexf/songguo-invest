#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 驱动 Edge(9223) 操作 51LA 后台——通用 helper + 域名匹配设置入口探测"""
import json, sys, time, urllib.request
import websocket

CDP_HTTP = "http://localhost:9223"

def http_json(path, method="GET", data=None):
    req = urllib.request.Request(CDP_HTTP + path, method=method)
    if data is not None:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

def new_tab(url):
    # PUT /json/new?url= 需要 urlencode
    return http_json("/json/new?%s" % urllib.request.quote(url, safe=""), method="PUT")

def ws_cmd(ws, method, params=None, mid=None):
    _id = mid or int(time.time() * 1000) % 100000
    ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            return msg

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "probe"
    tab = new_tab("about:blank")
    ws_url = tab["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=30)
    ws_cmd(ws, "Page.enable")
    ws_cmd(ws, "Runtime.enable")
    if action == "open":
        url = sys.argv[2]
        ws_cmd(ws, "Page.navigate", {"url": url})
        time.sleep(6)
        # 读标题 + 正文前若干文本
        r = ws_cmd(ws, "Runtime.evaluate", {"expression": "document.title + '|||' + (document.body?document.body.innerText.slice(0,800):'NOBODY')", "returnByValue": True})
        print(r["result"]["result"].get("value", ""))
    elif action == "eval":
        expr = sys.argv[2]
        r = ws_cmd(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
        print(json.dumps(r["result"].get("result", {}), ensure_ascii=False)[:3000])
    ws.close()

if __name__ == "__main__":
    main()
