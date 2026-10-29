"""依据已验证结果写阶段 3 说明并生成差评率分组图。"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from stage1 import ROOT,OUT,FIG


def main():
    audit=pd.read_csv(OUT/'03_review_audit.csv').iloc[0]
    comp=pd.read_csv(OUT/'03_delay_comparison.csv').set_index('delayed');band=pd.read_csv(OUT/'03_delay_bands.csv').set_index('delay_band')
    chi=pd.read_csv(OUT/'03_chi_square.csv').iloc[0];logit=pd.read_csv(OUT/'03_logistic_coefficients.csv').set_index('term').loc['delayed'];sens=pd.read_csv(OUT/'03_logistic_after_delivery_sensitivity.csv').iloc[0]
    state=pd.read_csv(OUT/'03_delivery_states.csv');seller=pd.read_csv(OUT/'03_delivery_sellers_min30.csv')
    policies=pd.read_csv(OUT/'03_policy_comparison.csv').set_index('policy')
    timing=pd.read_csv(OUT/'03_review_timing.csv'); early=timing[(timing.review_timing=='after_estimate_before_delivery') & (timing.delayed==1)].iloc[0]
    groups=['on_time','1_to_3_days','4_to_7_days','over_7_days']; labels=['准时','延迟 1–3 天','延迟 4–7 天','延迟超过 7 天']
    lines=['# 阶段 3：配送延迟与差评的观察性分析\n',
    '本分析是历史订单的相关性研究，不能证明配送延迟造成差评。数据来自 Olist，且只观察有评价的已送达订单；配送延迟率拆解使用所有时间有效的已送达订单。\n',
    '## 评价与样本核查\n',
    f"- {int(audit.delivered_orders):,} 个已送达订单中，{int(audit.no_review_orders):,} 个没有评价，{int(audit.multi_review_orders):,} 个有多条评价（两条 {int(audit.multi_with_2)} 单、三条 {int(audit.multi_with_3)} 单）。多评价订单中 {int(audit.multi_different_scores)} 单出现不同评分；按评价创建日期选最新有 {int(audit.created_latest_ties)} 单并列，其中 {int(audit.created_latest_ties_different_scores)} 单的并列记录评分不同。按评价回复时间选择最新没有并列或缺失，故采用该规则；它不能证明最新一条评分更真实。",
    f"- 多评价订单中，最新和最早一条的评分不同有 {int(audit.multi_latest_vs_earliest_score_diff)} 单；差评标签不同有 {int(audit.multi_latest_vs_earliest_bad_flag_diff)} 单，说明选择规则会影响结果。",
    f"- 预计送达时间缺失或不可解析 {int(audit.estimate_missing_or_unparseable)} 单；实际送达时间缺失或不可解析 {int(audit.delivery_missing_or_unparseable)} 单，早于下单时间 {int(audit.delivery_earlier_than_purchase)} 单。依次排除时间无效订单后有 {int(audit.valid_delivery_orders):,} 单，其中无评价 {int(audit.valid_delivery_no_review):,} 单，最终差评分析 {int(audit.analysis_orders):,} 单。",
    '\n## 指标定义与时间口径\n',
    '- 主口径按自然日期判断：实际送达日期晚于预计送达日期为延迟，同日或更早为准时；评分 1–2 为差评。延迟天数为两个日期之差，依次分为 1–3 天、4–7 天和超过 7 天。',
    f"- 时间有效订单中，{int(audit.estimate_at_midnight):,} / {int(audit.valid_delivery_orders):,} 个预计送达时间恰为 00:00:00；{int(audit.late_same_calendar_day):,} 个订单在预计日期当天稍后送达。按自然日期主口径它们为准时；原时间戳敏感性口径则判为延迟。两种口径结果见 `03_policy_comparison.csv`。",
    '\n## 差评比较与分段\n',
    f"- 延迟：{int(comp.loc[1,'bad_reviews']):,} / {int(comp.loc[1,'orders']):,}，差评率 **{comp.loc[1,'bad_rate']:.2%}**，平均评分 {comp.loc[1,'mean_score']:.2f}；准时：{int(comp.loc[0,'bad_reviews']):,} / {int(comp.loc[0,'orders']):,}，差评率 **{comp.loc[0,'bad_rate']:.2%}**，平均评分 {comp.loc[0,'mean_score']:.2f}。",
    f"- 两组差评率差为 {100*chi.risk_difference:.2f} 个百分点，95% Newcombe 置信区间为 [{100*chi.risk_difference_ci_low:.2f}, {100*chi.risk_difference_ci_high:.2f}] 个百分点；Pearson 卡方 = {chi.chi2:.2f}，自由度 {int(chi.df)}，p < 1e-300，φ = {chi.phi:.3f}。p 值非常小，数据支持两组比例有差异，但不意味着因果。普通卡方和比例区间按订单独立计算，同一用户多次购买可能影响独立性。",
    '\n| 分组 | 订单数 | 差评数 | 差评率 | 平均评分 |\n|---|---:|---:|---:|---:|']
    for key,label in zip(groups,labels):
        row=band.loc[key];lines.append(f"| {label} | {int(row.orders):,} | {int(row.bad_reviews):,} | {row.bad_rate:.2%} | {row.mean_score:.2f} |")
    lines += ['\n上述分组的差评率随延迟天数递增，是分组描述，不代表每个个体都遵循这一趋势。\n',
    '## 两种延迟口径对照\n',
    '| 口径 | 延迟组差评率 | 准时组差评率 | 差评率差 | 卡方 | 全样本 OR（95% CI） | 送达后评价子样本 OR（95% CI） |\n|---|---:|---:|---:|---:|---:|---:|']
    for policy,label in [('calendar_date','自然日期（主口径）'),('timestamp','时间戳（敏感性）')]:
        z=policies.loc[policy]
        lines.append(f'| {label} | {z.delayed_bad_rate:.2%} | {z.on_time_bad_rate:.2%} | {100*z.risk_difference:.2f} 个百分点 | {z.chi_square:.2f} | {z.full_or:.2f}（{z.full_or_ci_low:.2f}–{z.full_or_ci_high:.2f}） | {z.after_or:.2f}（{z.after_or_ci_low:.2f}–{z.after_or_ci_high:.2f}） |')
    lines += [
    '## 逻辑回归与时间顺序限制\n',
    f"- 基准模型共 {int(audit.analysis_orders):,} 单，控制商品金额和运费的 `log(1+x)`、件数、是否有任一卖家跨州、订单主品类及客户州；延迟系数 **{logit.coefficient:.3f}**，优势比 OR **{logit.odds_ratio:.2f}**，95% 置信区间 [{logit.ci_lower:.2f}, {logit.ci_upper:.2f}]，p < 1e-300。OR 表示控制模型变量后差评优势的倍数，不是差评概率的倍数。置信区间按 `customer_unique_id` 聚类稳健标准误计算。",
    '- 订单主品类取商品金额最高的商品，金额相同取商品明细序号较小者。主品类少于 500 单、州少于 300 单的类别分别合并为其他类；多卖家订单只要有一个卖家州与客户州不同即视为跨州。该特征无法细分每个商品的配送过程。',
    f"- **时间顺序是重要限制：**{int(audit.review_before_delivery):,} 条评价回复早于最终实际送达；其中 {int(early.orders):,} 条发生在预计时间之后、最终送达之前，其差评率为 {early.bad_rate:.2%}。因此，对这些订单使用最终送达时间定义的延迟结果发生在评价之后，不能把全样本回归解释为延迟造成评分的证据。部分客户在评价时已经超过预计时间，因此可能知道订单尚未按期送达，但最终延迟时长当时尚未确定。",
    f"- 仅保留评价回复不早于实际送达的 {int(sens.sample_orders):,} 单，使用同一组变量和基准样本的品类、州合并规则，延迟 OR 为 **{sens.odds_ratio:.2f}**，95% 置信区间 [{sens.ci_lower:.2f}, {sens.ci_upper:.2f}]，p = {sens.p_value:.2g}。敏感性样本是按评价时间筛选的子集，可能产生选择偏差，也不能作因果解释；与全样本差异说明结果对时间顺序和样本选择敏感。",
    '\n## 延迟率较高的州与卖家\n',
    '以下分母是不要求有评价、时间有效的已送达订单；州为收货州，州与卖家均设置至少 30 单。排序是样本描述，未控制路线、品类和承运商差异；低订单量的率不稳定，排名不能作为责任认定。\n',
    '| 收货州 | 订单 | 延迟订单 | 延迟率 | 95% Wilson 区间 |\n|---|---:|---:|---:|---:|']
    for z in state.head(5).itertuples(): lines.append(f'| {z.state} | {z.orders:,} | {int(z.delayed_orders):,} | {z.delay_rate:.2%} | {z.delay_rate_ci_low:.2%}–{z.delay_rate_ci_high:.2%} |')
    lines += ['\n| 卖家 ID | 涉及该卖家的订单 | 延迟订单 | 延迟率 | 95% Wilson 区间 |\n|---|---:|---:|---:|---:|']
    for z in seller.head(5).itertuples(): lines.append(f'| `{z.seller_id}` | {z.orders:,} | {int(z.delayed_orders):,} | {z.delay_rate:.2%} | {z.delay_rate_ci_low:.2%}–{z.delay_rate_ci_high:.2%} |')
    lines += ['\n若订单包含多个卖家，会同时计入各卖家一次；订单级送达结果不能识别具体卖家的责任。建议以高延迟州与订单量较大的卖家为线索，进一步拆分路线、承运商、出库到揽收与揽收到送达时间，并核查预计送达时间是否准确；针对发现的问题试点改善并比较同口径延迟率和差评率。建议均为待验证假设。',
    '\n代码：`sql/07_delivery_analysis.sql`、`sql/08_review_audit.sql`、`src/stage3.py`；核查、对账和全部分组结果见 `results/tables/03_*.csv`。`p_value` 为缺失但 `log10_p_value` 为极小负数表示数值下溢，不表示 p 等于零。\n']
    (ROOT/'docs/阶段3_配送与差评.md').write_text('\n'.join(lines),encoding='utf8')
    data=band.loc[groups]; fig,ax=plt.subplots(figsize=(8,4.7)); bars=ax.bar(['On time','1–3 days','4–7 days','Over 7 days'],data.bad_rate*100,color=['#39758e','#659bb0','#dc9862','#c55544']);ax.set_ylim(0,100);ax.set_ylabel('1–2 star reviews (%)');ax.set_title('Review score by delivery delay');ax.grid(axis='y',alpha=.2)
    for b,rate,n in zip(bars,data.bad_rate,data.orders):ax.text(b.get_x()+b.get_width()/2,b.get_height()+2,f'{rate:.1%}\nn={int(n):,}',ha='center',va='bottom',fontsize=9)
    fig.tight_layout();FIG.mkdir(parents=True,exist_ok=True);fig.savefig(FIG/'03_delay_bad_review.png',dpi=180);plt.close(fig)
    print('已按实际结果写阶段 3 说明并生成分组图。')

if __name__=='__main__':main()
