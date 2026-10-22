# -*- coding: utf-8 -*-
"""金额单位统一：亿元口径（2026-10-22）

## 为什么有这个模块
用户要求"所有出现的金额数字，精简到亿元单元"。原先金额单位散落在各层：
- stockscore_industry.py：行业总市值、自身总市值用「万元」
- stockscore_modules.py：总市值内部是万元、输出是亿元
- stockscore_facts.py：多数已是亿元
- 前端 stockscore-v3.js：num() 只做千分位，不认单位

口径不一会出现"6.4亿 / 640,000万"这种同一事实两种写法，读者要自己换算。

## 规则
- 返回值**始终带单位词**，调用方不要再拼单位（拼了会变成"6400 万元 亿元"）
- 全部金额统一「X.XX 亿元」；< 0.01 亿元保留 4 位小数（不回落万元/元）
- 已是亿元的值 → 原样，只做小数位处理
- 四舍五入保留 2 位小数

## 注意
这是**展示层**单位统一，不改任何计算口径。PE/PB/市值占比等比值不受影响。
"""


def fmt_yi(value, unit='亿元', nd=2):
    """把一个金额数格式化成「亿元」口径的可读字符串。

    unit 参数说明入参的单位：
      - '亿元' / '亿'：入参已经是亿元，原样输出
      - '万元' / '万'：入参是万元，除以 1e4 转亿元
      - '元'：入参是元，除以 1e8 转亿元
      - None / 未知：按元处理（最保守，宁可放大数量级也不写错单位）

    返回示例：'80.21 亿元' / '0.0064 亿元'
    """
    if value is None:
        return '—'
    try:
        f = float(value)
    except (TypeError, ValueError):
        return '—'
    if unit in ('万元', '万', 'w'):
        yi = f / 1e4
    elif unit in ('亿元', '亿', 'yi'):
        yi = f
    elif unit in ('元',):
        yi = f / 1e8
    else:
        yi = f / 1e8
    # 用户口径：所有金额一律亿元，不因金额小就回落万元/元。
    # 小额（< 0.01 亿元）保留 4 位小数，避免写成 0.00 亿元丢信息。
    if abs(yi) >= 0.01:
        return ('%.' + str(nd) + 'f') % yi + ' 亿元'
    txt = ('%.4f' % yi).rstrip('0').rstrip('.')
    if txt in ('', '-0'):
        txt = '0'
    return txt + ' 亿元'


def fmt_yi_unit(value, unit='亿元', nd=2):
    """同 fmt_yi，但把单位词一起返回（用于需要分别渲染数值和单位的场景）。"""
    s = fmt_yi(value, unit=unit, nd=nd)
    for u in ('亿元', '万元', '元'):
        if s.endswith(u):
            return s[:-len(u)], u
    return s, ''
