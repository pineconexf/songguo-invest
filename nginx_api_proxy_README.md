# 个股体检 Stock Check 后端代理配置（待服务器上线时执行）

## 背景
前端 `stockcheck.astro` 的 `API_BASE` 已改为 `location.origin`（同源请求），即线上请求：
- GH Pages：`https://pineconexf.github.io/api/check`
- 云站：`https://pinecone-lab.cn/api/check`

后端实际运行在 `45.194.22.118:8080`。因此**必须**在云服务器 nginx 上把 `/api/` 反向代理到后端，否则 404。

前端在线上的表现：已加维护提示条（待服务器配置完成后恢复真实查询）。

## 需在服务器（47.104.103.33）做的配置

### 1. 确认后端已部署运行
```bash
# 服务器上应已有 uvicorn 在跑（后端路径参考 D:/pineconeinvestfiles/松果投资体系网站/01_网站开发/backend/api.py）
curl -s http://127.0.0.1:8080/api/health
# 期望: {"status":"ok","service":"songguo-stock-check"}
```

### 2. nginx 加 /api 反向代理（监听 80 或 443 的 server 块内）
在站点的 `server` 块中加：
```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8080/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

### 3. reload
```bash
nginx -t && systemctl reload nginx
```

## 验证
```bash
# 服务器上自测
curl -s http://127.0.0.1/api/health
# 公网验证（HTTPS 完成前用 http://47.104.103.33/api/health）
curl -s http://47.104.103.33/api/health
```

## 注意
- 混合内容修复后，页面从 `https://pineconexf.github.io` 请求 `https://pinecone-lab.cn/api/` 是**跨域 HTTPS→HTTPS**，但后端 CORS 已配 `allow_origins=['*']`（backend/api.py:26），无需再改后端。
- 等 ICP 备案完成、云站 HTTPS 上线后，页面会自然走云站同源路径。
- 本后端需持续运行：建议用 `nohup` 或 systemd 守护，`uvicorn api:app --host 0.0.0.0 --port 8080`。
