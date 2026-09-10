#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_fund_managers.py — 基金体检卡「经理名搜索」数据管线（构建期）

为什么存在：天天基金无「经理名→在管基金」纯前端接口（m=9 只匹配基金名/股票名，
m=7 只给 MgrId；/manager/<id>.html 有完整在管列表但浏览器 CORS 拦、服务端可抓）。
故构建期服务端抓一次 → src/data/fund_managers.json → 前端只查本地 JSON，零跨域。

用法：python scripts/build_fund_managers.py           # 抓内置热门名单
      python scripts/build_fund_managers.py 李晓星     # 追加指定经理

维护：热门名单来自 2026-09-10 评论区痛点调研点名 + 市场共识；季度重跑一次即可。
"""
import sys, os, re, json, subprocess, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "src", "data", "fund_managers.json")

HOT_MANAGERS = [
    "刘彦春", "张坤", "朱少醒", "谢治宇", "葛兰", "周蔚文",
    "傅鹏博", "曹名长", "何帅", "萧楠", "杨金金", "冯明远",
    "陈皓", "王崇", "李晓星", "刘格菘",
]

SUGGEST = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def curl(url, timeout=15):
    r = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, url],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.stdout or ""


def manager_id(name):
    """m=7 按经理名精确匹配拿 MgrId（同名取第一条，公司附在 note 供人工复核）"""
    txt = curl(f"{SUGGEST}?m=7&key={urllib.parse.quote(name)}")
    try:
        d = json.loads(txt)
    except Exception:
        return None, None
    for x in d.get("Datas") or []:
        if x.get("MgrName") == name:
            return x.get("MgrId"), x.get("JJGS")
    return None, None


TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
ROW = re.compile(r'href="//fund\.eastmoney\.com/(\d{6})\.html">[^<]*</a></td>'
                 r'<td class="tdl"><a[^>]*>([^<]+)</a>')


def current_funds(mgr_id):
    """解析 /manager/<id>.html：现任 = 任职列含「~ 至今」；同名表重复行去重"""
    html = curl(f"https://fund.eastmoney.com/manager/{mgr_id}.html", 25)
    out, seen = [], set()
    for tr in TR.findall(html):
        if 'class="tdl"' not in tr or "~ 至今" not in tr:
            continue
        m = ROW.search(tr)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"code": m.group(1), "name": m.group(2).strip()})
    return out


def main():
    extra = [a for a in sys.argv[1:] if a.strip()]
    names = list(dict.fromkeys(HOT_MANAGERS + extra))
    data = {}
    fails = []
    for name in names:
        mid, corp = manager_id(name)
        if not mid:
            fails.append(name)
            print(f"  ✗ {name}: m=7 未命中 MgrId")
            continue
        funds = current_funds(mid)
        if not funds:
            fails.append(name)
            print(f"  ✗ {name}(id={mid}): 现任基金解析 0 只")
            continue
        data[name] = {"mgrId": mid, "company": corp, "funds": funds}
        print(f"  ✓ {name}（{corp}）{len(funds)} 只在管: " +
              "、".join(f"{f['code']} {f['name']}" for f in funds[:2]) +
              ("…" if len(funds) > 2 else ""))

    payload = {
        "updated": subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip(),
        "source": "天天基金 fund.eastmoney.com/manager（构建期服务端抓取，季度重跑）",
        "managers": data,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"\n✅ 写入 {os.path.normpath(OUT)}：{len(data)} 位经理" +
          (f"；失败 {len(fails)}: {'、'.join(fails)}" if fails else "；零失败"))
    # 断言：产出必须有内容，防静默产出空 JSON 把前端打死
    assert len(data) >= 10, f"仅 {len(data)} 位成功，低于预期 10，接口可能变了，勿直接部署"


if __name__ == "__main__":
    main()
