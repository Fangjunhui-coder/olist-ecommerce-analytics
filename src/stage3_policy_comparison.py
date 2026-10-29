"""将日期主口径与时间戳敏感性对照汇总成整洁表。"""
import pandas as pd
from stage1 import OUT


def main():
 rows=[]
 for policy,suffix in [('calendar_date',''),('timestamp','_timestamp')]:
  def read(name):return pd.read_csv(OUT/f'{name}{suffix}.csv')
  a=read('03_delay_comparison').set_index('delayed');test=read('03_chi_square').iloc[0]
  mod=read('03_logistic_coefficients').set_index('term').loc['delayed'];sub=read('03_logistic_after_delivery_sensitivity').iloc[0]
  row={'policy':policy,'delayed_orders':int(a.loc[1,'orders']),'delayed_bad':int(a.loc[1,'bad_reviews']),'delayed_bad_rate':a.loc[1,'bad_rate'],
       'on_time_orders':int(a.loc[0,'orders']),'on_time_bad':int(a.loc[0,'bad_reviews']),'on_time_bad_rate':a.loc[0,'bad_rate'],
       'risk_difference':test.risk_difference,'risk_difference_ci_low':test.risk_difference_ci_low,'risk_difference_ci_high':test.risk_difference_ci_high,
       'chi_square':test.chi2,'chi_square_log10_p':test.log10_p_value,'phi':test.phi,
       'full_coefficient':mod.coefficient,'full_or':mod.odds_ratio,'full_or_ci_low':mod.ci_lower,'full_or_ci_high':mod.ci_upper,'full_log10_p':mod.log10_p_value,
       'after_delivery_orders':int(sub.sample_orders),'after_coefficient':sub.coefficient,'after_or':sub.odds_ratio,'after_or_ci_low':sub.ci_lower,'after_or_ci_high':sub.ci_upper,'after_log10_p':sub.log10_p_value}
  for r in read('03_delay_bands').itertuples():row[f'{r.delay_band}_orders']=int(r.orders);row[f'{r.delay_band}_bad_rate']=r.bad_rate
  rows.append(row)
 pd.DataFrame(rows).sort_index(axis=1).to_csv(OUT/'03_policy_comparison.csv',index=False)
 print('日期主口径和时间戳敏感性对照表已生成。')

if __name__=='__main__':main()
