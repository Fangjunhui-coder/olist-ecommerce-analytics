"""阶段 2：RFM 分层及 pandas 独立复算。"""
import duckdb
import numpy as np
import pandas as pd
from stage1 import ROOT, RAW, OUT, FILES, raw_pandas, assert_keys, compare


def main():
    con=duckdb.connect()
    for name, filename in FILES.items():
        path=str(RAW/filename).replace("'","''")
        con.execute(f"create view {name} as select * from read_csv('{path}', header=true, all_varchar=true)")
    for file in ['02_stage1_model.sql','05_rfm.sql']:
        con.execute((ROOT/'sql'/file).read_text(encoding='utf-8'))
    sql={k:con.execute(f'select * from {k}').df() for k in ['rfm_cutoffs','rfm_frequency','rfm_segments']}
    # pandas 从原始文件独立构造用户订单与金额，不读 SQL 结果或 SQL 用户分层。
    d=raw_pandas();o=d['orders'];c=d['customers'];i=d['order_items']
    assert_keys(o,['order_id']);assert_keys(c,['customer_id']);assert_keys(i,['order_id','order_item_id'])
    o['purchased_at']=pd.to_datetime(o.order_purchase_timestamp,errors='coerce')
    ref=o.purchased_at.max().normalize()+pd.Timedelta(days=1)
    eligible=o.loc[(o.order_status=='delivered') & o.order_id.str.strip().ne('') & o.purchased_at.notna()].merge(c[['customer_id','customer_unique_id']],on='customer_id',how='left',validate='many_to_one',indicator=True)
    if not eligible['_merge'].eq('both').all() or eligible.customer_unique_id.isna().any() or eligible.customer_unique_id.eq('').any():raise ValueError('客户关联或用户 ID 无效')
    x=i.merge(eligible[['order_id','customer_unique_id','purchased_at']],on='order_id',how='inner',validate='many_to_one')
    if set(x.order_id)!=set(eligible.order_id): raise ValueError('存在没有明细的已送达订单')
    values=pd.to_numeric(x.price,errors='coerce')
    if values.isna().any() or (values<0).any() or not np.allclose(values*100,np.round(values*100),rtol=0,atol=1e-6):raise ValueError('价格数据无效')
    x['cents']=np.rint(values*100).astype('int64')
    by_order=x.groupby(['order_id','customer_unique_id','purchased_at'],as_index=False).agg(cents=('cents','sum'))
    u=by_order.groupby('customer_unique_id',as_index=False).agg(last=('purchased_at','max'),frequency=('order_id','size'),cents=('cents','sum'))
    u['recency_days']=(ref-u['last'].dt.normalize()).dt.days
    u['monetary']=u.cents/100
    rq1,rq2=u.recency_days.quantile([1/3,2/3],interpolation='linear')
    mq1,mq2=u.monetary.quantile([1/3,2/3],interpolation='linear')
    cut=pd.DataFrame([{'r_q1':rq1,'r_q2':rq2,'m_q1':mq1,'m_q2':mq2,'buyers':len(u)}])
    compare(sql['rfm_cutoffs'],cut,[],list(cut.columns),'RFM 分位点')
    if pd.Timestamp(sql['rfm_cutoffs'].reference_date.iloc[0]) != ref:raise AssertionError('R 参照日不一致')
    u['r_band']=np.select([u.recency_days<=rq1,u.recency_days<=rq2],['recent','middle'],default='dormant')
    u['f_band']=np.where(u.frequency==1,'one','repeat')
    u['m_band']=np.select([u.monetary<=mq1,u.monetary<=mq2],['low','middle'],default='high')
    freq=u.groupby('frequency',as_index=False).agg(buyers=('customer_unique_id','size'));freq['buyer_share']=freq.buyers/len(u)
    compare(sql['rfm_frequency'],freq,['frequency'],['buyers','buyer_share'],'购买频次分布')
    seg=u.groupby(['r_band','f_band','m_band'],as_index=False).agg(buyers=('customer_unique_id','size'),cents=('cents','sum'),mean_r_days=('recency_days','mean'),mean_f_orders=('frequency','mean'),mean_m_brl=('monetary','mean'),orders=('frequency','sum'))
    seg['gmv']=seg.cents/100;seg['buyer_share']=seg.buyers/len(u);seg['gmv_share']=seg.cents/u.cents.sum();seg['average_order_value']=seg.gmv/seg.orders
    compare(sql['rfm_segments'],seg,['r_band','f_band','m_band'],['buyers','buyer_share','gmv','gmv_share','mean_r_days','mean_f_orders','mean_m_brl','average_order_value'],'RFM 各层')
    if int(seg.buyers.sum())!=len(u) or not np.isclose(seg.gmv.sum(),u.cents.sum()/100):raise AssertionError('用户数或 GMV 无法对账')
    # 策略是可验证的运营假设，不声称产生实际效果。
    strategies=[]
    for row in sql['rfm_segments'].itertuples(index=False):
        if row.r_band=='dormant': action='通过可触达渠道测试分批召回，设置有效期和不打扰频次'
        elif row.r_band=='middle': action='测试基于历史购买品类的再次购买提醒，控制推送频次'
        else: action='在购买后适当时间测试相关品类或补充商品推荐'
        action+= '；' + ('对复购客户优先测试会员权益' if row.f_band=='repeat' else '对单次购买客户测试第二单激励')
        action+= '；' + {'high':'高金额客户优先测试非折扣权益并控制成本','middle':'中等金额客户测试有门槛的轻量优惠','low':'低金额客户测试低成本个性化推荐'}[row.m_band]
        measure='主指标：分组后 30 天内有至少一笔已送达订单的目标用户占比；护栏：每名目标用户优惠成本、退订率；按随机分组比较'
        strategies.append({'r_band':row.r_band,'f_band':row.f_band,'m_band':row.m_band,'strategy_hypothesis':action,'measurement':measure})
    sql['rfm_cutoffs'].to_csv(OUT/'02_rfm_cutoffs.csv',index=False,date_format='%Y-%m-%d')
    sql['rfm_frequency'].sort_values('frequency').to_csv(OUT/'02_frequency_distribution.csv',index=False)
    segments=sql['rfm_segments'].sort_values(['r_band','f_band','m_band'])
    segments.to_csv(OUT/'02_rfm_segments.csv',index=False)
    pd.DataFrame(strategies).merge(segments,on=['r_band','f_band','m_band'],validate='one_to_one').sort_values(['r_band','f_band','m_band']).to_csv(OUT/'02_rfm_strategies.csv',index=False)
    pd.DataFrame([{'result':s,'validation':'passed','method':'independent pandas from raw CSV'} for s in ['rfm_cutoffs','rfm_frequency','rfm_segments']]).to_csv(OUT/'02_validation.csv',index=False)
    print('RFM 频次、分位点和全部分层结果已通过独立 pandas 对账。')

if __name__=='__main__': main()
