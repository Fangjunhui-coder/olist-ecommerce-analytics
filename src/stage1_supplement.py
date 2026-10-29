"""补充运费、90 天复购和日度趋势：SQL 计算并独立用 pandas 对账。"""
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from stage1 import ROOT, RAW, OUT, FIG, FILES, raw_pandas, compare, assert_keys


def main():
    con=duckdb.connect()
    for name, filename in FILES.items():
        path=str(RAW/filename).replace("'","''")
        con.execute(f"create view {name} as select * from read_csv('{path}', header=true, all_varchar=true)")
    con.execute((ROOT/'sql/02_stage1_model.sql').read_text(encoding='utf-8'))
    con.execute((ROOT/'sql/04_supplementary_metrics.sql').read_text(encoding='utf-8'))
    sql={k:con.execute(f'select * from {k}').df() for k in ['supplementary_amounts','repeat_90','daily_2017_11','repeat_90_sensitivity','repeat_90_coverage']}
    # 从原始 CSV 独立计算，金额以整数分累加；订单和客户均验证键唯一。
    d=raw_pandas(); o=d['orders'];c=d['customers'];i=d['order_items']
    assert_keys(o,['order_id']);assert_keys(c,['customer_id']);assert_keys(i,['order_id','order_item_id'])
    o['purchase']=pd.to_datetime(o.order_purchase_timestamp,errors='coerce'); cutoff=o.purchase.max()
    eligible=o.loc[o.order_status.eq('delivered') & o.order_id.str.strip().ne('') & o.purchase.notna()].merge(c[['customer_id','customer_unique_id']],on='customer_id',how='left',validate='many_to_one',indicator=True)
    if not eligible['_merge'].eq('both').all() or eligible.customer_unique_id.isna().any() or eligible.customer_unique_id.eq('').any(): raise ValueError('客户标识无效')
    x=i.merge(eligible[['order_id']],on='order_id',how='inner',validate='many_to_one')
    if set(x.order_id)!=set(eligible.order_id): raise ValueError('已送达订单缺少商品明细')
    cents={}
    for col in ['price','freight_value']:
        n=pd.to_numeric(x[col],errors='coerce')
        if n.isna().any() or (n<0).any() or not np.allclose(n*100,np.round(n*100),rtol=0,atol=1e-6): raise ValueError(f'{col} 无法安全转换成整数分')
        cents[col]=int(np.rint(n*100).astype('int64').sum())
    amounts=pd.DataFrame([{'product_gmv':cents['price']/100,'freight_total':cents['freight_value']/100,'gmv_with_freight':(cents['price']+cents['freight_value'])/100}])
    compare(sql['supplementary_amounts'],amounts,[],list(amounts.columns),'运费及含运费 GMV')
    first=eligible.groupby('customer_unique_id').purchase.min().rename('first_at')
    mature=first[first.dt.normalize()+pd.Timedelta(days=90)<=cutoff.normalize()]
    test=eligible.join(mature,on='customer_unique_id',how='inner')
    repeated=test.loc[(test.purchase>test.first_at)&(test.purchase.dt.normalize()<=test.first_at.dt.normalize()+pd.Timedelta(days=90)),'customer_unique_id'].nunique()
    exp=pd.DataFrame([{'total_buyers':len(first),'eligible_buyers':len(mature),'repeat_buyers_90d':repeated,'repeat_rate_90d':repeated/len(mature) if len(mature) else np.nan}])
    compare(sql['repeat_90'],exp,[],list(exp.columns),'90 天复购')
    if pd.Timestamp(sql['repeat_90'].data_cutoff.iloc[0])!=cutoff: raise AssertionError('截止时间不一致')
    conservative_cutoff=eligible.purchase.max()
    mature2=first[first.dt.normalize()+pd.Timedelta(days=90)<=conservative_cutoff.normalize()]
    test2=eligible.join(mature2,on='customer_unique_id',how='inner')
    rep2=test2.loc[(test2.purchase>test2.first_at)&(test2.purchase.dt.normalize()<=test2.first_at.dt.normalize()+pd.Timedelta(days=90)),'customer_unique_id'].nunique()
    sensitivity=pd.DataFrame([{'eligible_buyers':len(mature2),'repeat_buyers_90d':rep2,'repeat_rate_90d':rep2/len(mature2) if len(mature2) else np.nan}])
    compare(sql['repeat_90_sensitivity'],sensitivity,[],list(sensitivity.columns),'90 天复购敏感性检查')
    coverage=pd.DataFrame([{'eligible_buyers':len(mature),'windows_after_last_delivered':int((mature.dt.normalize()+pd.Timedelta(days=90)>conservative_cutoff.normalize()).sum())}])
    compare(sql['repeat_90_coverage'],coverage,[],list(coverage.columns),'90 天窗口覆盖')
    if pd.Timestamp(sql['repeat_90_sensitivity'].data_cutoff.iloc[0])!=conservative_cutoff or pd.Timestamp(sql['repeat_90_coverage'].last_delivered_order_at.iloc[0])!=conservative_cutoff: raise AssertionError('敏感性检查截止时间不一致')
    daily=eligible[(eligible.purchase >= '2017-11-01') & (eligible.purchase < '2017-12-01')].groupby(eligible.purchase.dt.normalize()).size().reindex(pd.date_range('2017-11-01','2017-11-30'),fill_value=0).rename_axis('day').reset_index(name='orders')
    a=sql['daily_2017_11'].copy();a['day']=pd.to_datetime(a.day); b=daily.copy()
    if a.day.dt.strftime('%Y-%m-%d').tolist()!=b.day.dt.strftime('%Y-%m-%d').tolist() or a.orders.tolist()!=b.orders.tolist(): raise AssertionError('日度订单数不一致')
    sql['supplementary_amounts'].to_csv(OUT/'01_freight_comparison.csv',index=False)
    sql['repeat_90'].to_csv(OUT/'01_repeat_90d.csv',index=False)
    sql['repeat_90_sensitivity'].to_csv(OUT/'01_repeat_90d_sensitivity.csv',index=False)
    sql['repeat_90_coverage'].to_csv(OUT/'01_repeat_90d_coverage.csv',index=False)
    sql['daily_2017_11'].to_csv(OUT/'01_2017_11_daily_orders.csv',index=False,date_format='%Y-%m-%d')
    pd.DataFrame([{'result':x,'validation':'passed'} for x in sql]).to_csv(OUT/'01_supplement_validation.csv',index=False)
    fig,ax=plt.subplots(figsize=(10,4.5));ax.bar(daily.day.dt.day,daily.orders,color='#236a86');ax.set(xlabel='Day of November 2017',ylabel='Delivered orders (by purchase date)',title='Daily orders in November 2017');ax.set_xticks(range(1,31,2));ax.grid(axis='y',alpha=.2);fig.tight_layout();FIG.mkdir(exist_ok=True,parents=True);fig.savefig(FIG/'01_2017_11_daily_orders.png',dpi=180);plt.close(fig)
    print('补充指标及日度订单量已通过 SQL 与 pandas 对账。')

if __name__=='__main__':main()
