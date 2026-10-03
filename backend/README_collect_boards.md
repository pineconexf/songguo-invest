# 概念板块每日快照采集器（collect_board_snapshot.py）

个股打分卡 ⑥「概念景气」维的**概念20日位次**子项需要连续 21 个交易日的
板块涨跌幅序列。东财 `push2/clist` 是高危接口（2-3 次即触发 IP 级 RST，
10+ 分钟不恢复），因此**绝不允许打分卡请求链路实时调用它**——唯一入口
是本脚本，每日落盘一份 JSON，引擎只读文件。

## 数据契约

```
backend/data/board_snapshots/boards_YYYYMMDD.json
{"BK0590": 1.23, "BK0665": -0.45, ...}   # 概念板块代码 → 当日涨跌幅%
```

- 文件名即日期，天然按交易日隔离；非交易日自动跳过不产文件。
- 原子写入（.tmp → rename），cron 中断不会留半截文件。
- 幂等：同日重跑直接跳过；`--force` 仅允许覆盖**当日**。
- 引擎侧（stockscore.py `load_board_returns`）需 ≥21 个文件才启用该子项，
  在此之前 ⑥ 维自动走降级路径（flag 明示"快照不足20交易日"），不填 0 分。

## 用法

```bash
cd D:/pineconeinvestfiles/松果投资体系网站/01_网站开发/backend
.venv/Scripts/python.exe collect_board_snapshot.py            # 采今日
.venv/Scripts/python.exe collect_board_snapshot.py --date 2026-10-09   # 补采指定交易日
.venv/Scripts/python.exe collect_board_snapshot.py --force    # 覆盖重采（仅当日）
.venv/Scripts/python.exe collect_board_snapshot.py --status   # 积累进度
```

退出码：`0` 成功/已存在/非交易日；`1` 全部重试失败；`2` 环境错误。
日志：`backend/data/collect_boards.log`。

## 退避策略（高危区铁律）

抓取失败按 `30s → 2min → 10min` 三级退避重试，全失败退出码 1，**每日总调用
不超过 1 轮**（1 轮内含分页约 6-7 个请求，页间隔 1.5s）。不要在脚本外并发
打 push2，不要写循环补采历史（历史日无法用 clist 补，涨跌幅是当日快照值）。

## Cron 配置

**Linux/华纳云（推荐部署位）**——收盘后 16:10 采集，工作日均跑（脚本内部自动
判交易日）：

```cron
10 16 * * 1-5 cd /opt/songguo/backend && ./.venv/bin/python collect_board_snapshot.py >> data/cron_boards.log 2>&1
```

**Windows 任务计划程序（本机开发位）**：

```bat
schtasks /Create /TN "songguo-boardsnap" /SC DAILY /ST 16:10 ^
 /TR "cmd /c cd /d D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\backend && .venv\Scripts\python.exe collect_board_snapshot.py"
```

**Hermes cron（如果用 Hermes 调度）**：每交易日 16:10 执行
`D:/pineconeinvestfiles/松果投资体系网站/01_网站开发/backend/.venv/Scripts/python.exe D:/pineconeinvestfiles/松果投资体系网站/01_网站开发/backend/collect_board_snapshot.py`，
失败不自动重试（退避已在脚本内，重复跑只会白耗 push2 配额），次日缺采人工
`--date` 补当日之前的最新交易日一份即可。

## 验证积累进度

```bash
.venv/Scripts/python.exe collect_board_snapshot.py --status
# 已积累 N 个交易日快照（引擎启用阈值 21）
```

N ≥ 21 后，打分卡 ⑥ 维会出现「所属概念20日涨幅中位数·位次」指标，
无需改任何代码（引擎探测文件数自动启用）。

## 已知边界

- clist 返回的涨跌幅是**当日**值；20 日涨幅由引擎连乘 21 个日点位求得，
  中途缺一天该板块即被剔除（引擎侧 `ok=False` 分支），不会污染位次。
- 板块数 <100 视为抓取失败（正常概念板块约 400+），防接口半残时落脏数据。
