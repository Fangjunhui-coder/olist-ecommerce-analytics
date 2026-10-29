"""根据运行结果生成阶段 2 中文分层说明，避免手工誊写数字。"""
import pandas as pd
from stage1 import ROOT, OUT


def main():
    cut=pd.read_csv(OUT/'02_rfm_cutoffs.csv').iloc[0]
    freq=pd.read_csv(OUT/'02_frequency_distribution.csv')
    rows=pd.read_csv(OUT/'02_rfm_strategies.csv')
    r={'recent':'较近','middle':'中间','dormant':'较久'}
    f={'one':'1 单','repeat':'2 单及以上'}
    m={'low':'低','middle':'中','high':'高'}
    parts=['# 阶段 2：RFM 用户分层与运营假设\n',
      f"本次以 `customer_unique_id` 为用户，分析 {int(cut.buyers):,} 名已送达订单买家。金额为商品金额，不含运费。\n",
      '## 先检查购买频次\n',
      '| 已送达订单数 | 用户数 | 用户占比 |\n|---:|---:|---:|']
    for z in freq.itertuples(index=False): parts.append(f'| {z.frequency} | {z.buyers:,} | {z.buyer_share:.4%} |')
    one=int(freq.loc[freq.frequency==1,'buyers'].sum()); repeat=int(freq.loc[freq.frequency>=2,'buyers'].sum())
    parts += [f'\n其中 1 单用户 {one:,} 人（{one/int(cut.buyers):.2%}），2 单及以上 {repeat:,} 人（{repeat/int(cut.buyers):.2%}）。F 大量并列在 1，标准五分位无法形成有意义且稳定的五档，因此按 1 单、2 单及以上二分。',
      '\n## 定义和分档\n',
      f"- 全部订单最后下单日的次日为 R 参照日：**{cut.reference_date}**。R 是参照日期减去用户最近一次已送达订单的下单日期，以自然日计；F 是已送达订单数；M 是这些订单的商品 GMV 之和。",
      f"- 全体用户 R 的三分位点是 {cut.r_q1:g}、{cut.r_q2:g} 天：R ≤ {cut.r_q1:g} 为较近，{cut.r_q1:g} < R ≤ {cut.r_q2:g} 为中间，R > {cut.r_q2:g} 为较久。",
      f"- 全体用户 M 的三分位点是 {cut.m_q1:.2f}、{cut.m_q2:.2f} 雷亚尔：M ≤ {cut.m_q1:.2f} 为低，{cut.m_q1:.2f} < M ≤ {cut.m_q2:.2f} 为中，M > {cut.m_q2:.2f} 为高。",
      '- 分位点使用线性插值；相同数值必须进入同一档，故各档人数不必完全相等。R 的远近和 M 高低均为本样本的相对标签，不是通用经营阈值。',
      '- R、F、M 的 3 × 2 × 3 个组合互斥，用户数和商品 GMV 可以加总。平均 M 是人均累计商品金额，平均客单价是本组 GMV 除以本组订单数，两者不同。',
      '\n## 各分层结果\n',
      '| R | F | M | 用户数 | 用户占比 | GMV 占比 | 平均 R（天） | 平均 F（单） | 平均 M（BRL） | 客单价（BRL） |\n|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    order={'recent':0,'middle':1,'dormant':2};ford={'one':0,'repeat':1};mord={'high':0,'middle':1,'low':2}
    records=sorted(rows.to_dict('records'),key=lambda x:(order[x['r_band']],ford[x['f_band']],mord[x['m_band']]))
    for z in records:
        parts.append(f"| {r[z['r_band']]} | {f[z['f_band']]} | {m[z['m_band']]} | {z['buyers']:,} | {z['buyer_share']:.2%} | {z['gmv_share']:.2%} | {z['mean_r_days']:.1f} | {z['mean_f_orders']:.2f} | {z['mean_m_brl']:.2f} | {z['average_order_value']:.2f} |")
    parts += ['\n## 各分层的策略假设\n','每条建议均为后续可以验证的方案，不代表项目已经开展运营或产生效果。所有组的共同衡量方式：按目标用户随机分组，比较分组后 30 天内有至少一笔已送达订单的用户占比，并监测每名目标用户的优惠成本和退订率；应设置相同观察窗口。触达、实验分组、成本和退订数据不在本数据集中，需在真实业务中另行采集。\n']
    for z in records:
        parts.append(f"- **{r[z['r_band']]} / {f[z['f_band']]} / {m[z['m_band']]}：**{z['strategy_hypothesis']}。")
    parts += ['\n## 局限\n','RFM 使用历史数据整段的累计金额，不是获客渠道、利润或终身价值；记录末段的已送达订单稀少，不应直接把“较久”理解为真实流失，也不能直接对当下用户执行触达。90 天复购覆盖限制见阶段 1 补充说明。']
    (ROOT/'docs/阶段2_RFM分层与策略.md').write_text('\n'.join(parts)+'\n',encoding='utf-8')
    print('已按实际输出生成阶段 2 中文结果与策略文档。')

if __name__=='__main__':main()
