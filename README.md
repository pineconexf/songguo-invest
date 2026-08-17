# 松果投资体系网站

数据权威站：用 14 年真实回测数据建立信任，靠信任变现。对标格林布拉特「神奇公式」网站。
定位红线：数据权威站，不是荐股站（无证券投资咨询牌照）。

## 技术栈

- **Astro 7**（静态站，零服务器成本）
- **ECharts 6**（数据可视化，按需引入）
- 部署目标：Cloudflare Pages / GitHub Pages（免费）

## 目录结构

```
01_网站开发/
├── src/
│   ├── data/strategy.json      # 回测数据（脚本自动生成，勿手改）
│   ├── layouts/Layout.astro    # 全局布局（导航/页脚）
│   ├── components/Chart.astro  # ECharts 容器组件
│   ├── scripts/charts.ts       # 图表初始化脚本（按需引入 ECharts）
│   ├── styles/global.css       # 全局样式（深蓝 #1E2761 + 金 #C8A24B）
│   └── pages/
│       ├── index.astro         # 首页：核心指标 + 净值曲线
│       ├── methodology.astro   # 方法论：11步筛选/双因子/空仓保险
│       ├── backtest.astro      # 回测验证：净值/年度/回撤/审计记录
│       ├── ranking.astro       # 月度榜单：V31 vs 沪深300 逐月
│       └── about.astro         # 合规声明：数据来源/审计/免责
├── scripts/
│   └── build_strategy_data.py  # 数据管线：归档 CSV → strategy.json
├── astro.config.mjs
└── package.json
```

## 常用命令

```bash
npm run dev       # 本地开发预览 (localhost:4321)
npm run build     # 构建静态站 → dist/
npm run preview   # 预览构建产物
npm run data      # 重新生成 strategy.json（改回测数据后跑）
```

## 数据管线

`scripts/build_strategy_data.py` 从定稿归档读 CSV（`D:\pineconeinvestfiles\V31版本归档\V31_资金增强定稿\`、`V32版本归档\`、`V27.2版本归档\hs300_monthly_full20.csv`），
生成 `src/data/strategy.json`（净值/回撤/年度/月度对比/核心指标），输出前自动校验与定稿口径一致。

## 合规红线（发布必查）

- ❌ 不写"推荐买入"、不承诺收益、不做代客理财、不收费荐股
- ✅ 表述口径："历史回测展示""方法论研究""不构成投资建议"
- ✅ 月度榜单不展示个股，只展示策略月度收益
- ✅ 数据为含成本口径，审计记录公开

## 部署

1. 注册域名（约 ¥60/年）
2. 推送到 GitHub → GitHub Pages，或 Cloudflare Pages 直连 Git 仓库
3. 域名 CNAME 指向部署平台
4. `astro.config.mjs` 中 site 改为实际域名
