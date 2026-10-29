"""将 18 个 RFM 单元归并为 6 个互斥运营人群，并独立复核。"""
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from stage1 import ROOT,RAW,OUT,FIG,FILES,raw_pandas,assert_keys,compare

LABELS={
 'high_value_repeat':('高金额复购','会员权益或专属服务；以随机对照比较 30 天再次购买率及权益成本'),
 'other_repeat':('其他复购','按历史购买商品测试相关品类推荐；比较 30 天再次购买率及退订率'),
 'recent_high_one':('较近高金额单次','测试非折扣权益和第二单推荐；比较 30 天第二单比例及权益成本'),
 'recent_other_one':('较近中低金额单次','测试门槛券或低成本品类提醒；比较 30 天第二单比例及每人优惠成本'),
 'less_recent_high_one':('较久高金额单次','按许可触达测试非折扣召回权益；比较 30 天再次购买率及每人触达成本'),
 'less_recent_other_one':('较久中低金额单次','小规模测试低成本召回消息；比较 30 天再次购买率、退订率及触达成本')}


def main():
 c=duckdb.connect()
 for name,file in FILES.items():
  path=str(RAW/file).replace("'","''");c.execute(f"create view {name} as select * from read_csv('{path}',header=true,all_varchar=true)")
 for f in ['02_stage1_model.sql','05_rfm.sql','06_operating_groups.sql']:c.execute((ROOT/'sql'/f).read_text(encoding='utf8'))
 sql=c.execute('select * from operating_summary').df()
 # 从原始订单和明细独立计算每个用户的 R、F、M 与分位点。
 d=raw_pandas();o=d['orders'];u=d['customers'];i=d['order_items']
 for x,cols in [(o,['order_id']),(u,['customer_id']),(i,['order_id','order_item_id'])]:assert_keys(x,cols)
 o['purchase']=pd.to_datetime(o.order_purchase_timestamp,errors='coerce'); ref=o.purchase.max().normalize()+pd.Timedelta(days=1)
 e=o.loc[o.order_status.eq('delivered') & o.purchase.notna() & o.order_id.str.strip().ne('')].merge(u[['customer_id','customer_unique_id']],on='customer_id',how='left',validate='many_to_one')
 if e.customer_unique_id.isna().any() or e.customer_unique_id.eq('').any():raise ValueError('用户 ID 无效')
 x=i.merge(e[['order_id','customer_unique_id','purchase']],on='order_id',validate='many_to_one');v=pd.to_numeric(x.price,errors='coerce')
 if v.isna().any() or (v<0).any() or not np.allclose(v*100,np.rint(v*100),rtol=0,atol=1e-6):raise ValueError('价格无效')
 if set(x.order_id)!=set(e.order_id):raise ValueError('订单缺少商品')
 x['cents']=np.rint(v*100).astype('int64'); by=x.groupby(['order_id','customer_unique_id','purchase'],as_index=False).agg(cents=('cents','sum'))
 u=by.groupby('customer_unique_id',as_index=False).agg(last=('purchase','max'),frequency=('order_id','size'),cents=('cents','sum'))
 u['recency_days']=(ref-u['last'].dt.normalize()).dt.days;u['monetary']=u.cents/100
 r1=u.recency_days.quantile(1/3);m2=u.monetary.quantile(2/3)
 conditions=[(u.frequency>=2)&(u.monetary>m2),(u.frequency>=2), (u.recency_days<=r1)&(u.monetary>m2), (u.recency_days<=r1),u.monetary>m2]
 u['operating_group']=np.select(conditions,['high_value_repeat','other_repeat','recent_high_one','recent_other_one','less_recent_high_one'],default='less_recent_other_one')
 p=u.groupby('operating_group',as_index=False).agg(buyers=('frequency','size'),cents=('cents','sum'),mean_r_days=('recency_days','mean'),mean_f_orders=('frequency','mean'),mean_m_brl=('monetary','mean'))
 p['gmv']=p.cents/100;p['buyer_share']=p.buyers/len(u);p['gmv_share']=p.cents/u.cents.sum()
 compare(sql,p,['operating_group'],['buyers','buyer_share','gmv','gmv_share','mean_r_days','mean_f_orders','mean_m_brl'],'运营人群')
 sql['group_name']=sql.operating_group.map(lambda k:LABELS[k][0]);sql['strategy_hypothesis']=sql.operating_group.map(lambda k:LABELS[k][1]);sql=sql.sort_values('buyers',ascending=False)
 sql.to_csv(OUT/'02_operating_groups.csv',index=False);pd.DataFrame([{'result':'operating_groups','validation':'passed','method':'independent pandas from raw CSV'}]).to_csv(OUT/'02_operating_groups_validation.csv',index=False)
 fig,ax=plt.subplots(figsize=(10,5));order=['High-value repeat','Other repeat','Recent high / one order','Recent other / one order','Less recent high / one order','Less recent other / one order'];keys=list(LABELS); chart=sql.set_index('operating_group').loc[keys]; y=np.arange(len(keys)); ax.barh(y-0.18,chart.buyer_share*100,.36,label='Buyer share',color='#276f8b');ax.barh(y+0.18,chart.gmv_share*100,.36,label='GMV share',color='#df9252');ax.set_yticks(y,order);ax.invert_yaxis();ax.set_xlabel('Share (%)');ax.set_title('Buyer share vs product GMV share');ax.legend();ax.grid(axis='x',alpha=.2);fig.tight_layout();FIG.mkdir(parents=True,exist_ok=True);fig.savefig(FIG/'02_operating_group_shares.png',dpi=180);plt.close(fig)
 print('六个人群与 pandas 独立复算一致。')

if __name__=='__main__':main()
