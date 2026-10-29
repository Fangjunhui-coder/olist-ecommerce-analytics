"""阶段 1：DuckDB SQL 输出，pandas 从原始数据独立复算并核验。"""
from pathlib import Path
import os
import tempfile
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw'
OUT = ROOT / 'results/tables'
FIG = ROOT / 'results/figures'
FILES = {'orders':'olist_orders_dataset.csv','order_items':'olist_order_items_dataset.csv',
         'customers':'olist_customers_dataset.csv','products':'olist_products_dataset.csv',
         'translation':'product_category_name_translation.csv'}
RESULTS = {'overall':'01_overall.csv','monthly':'01_monthly.csv','category_summary':'01_categories.csv',
           'category_status_summary':'01_category_translation_status.csv','state_summary':'01_states.csv',
           'monthly_category':'01_monthly_categories.csv','monthly_state':'01_monthly_states.csv'}


def raw_pandas():
    # pandas 直接重新读取 CSV，不使用 SQL 的订单/明细中间结果。
    return {k: pd.read_csv(RAW/v, dtype=str, keep_default_na=False) for k,v in FILES.items()}


def assert_keys(frame, cols):
    if frame[cols].eq('').any(axis=None) or frame.duplicated(cols).any():
        raise ValueError(f'候选键无效或重复: {cols}')


def compare(sql, expected, keys, fields, name):
    # 全部组与列逐一比较；金额允许极小浮点误差，比例容差 1e-10。
    left = sql.copy(); right = expected.copy()
    for key in keys:
        if key == 'month':
            left[key] = pd.to_datetime(left[key]).dt.strftime('%Y-%m-%d')
            right[key] = pd.to_datetime(right[key]).dt.strftime('%Y-%m-%d')
    both = left.merge(right, on=keys, how='outer', suffixes=('_sql','_pd'), indicator=True, validate='one_to_one') if keys else pd.concat([left.add_suffix('_sql'),right.add_suffix('_pd')],axis=1)
    if keys and not (both['_merge'] == 'both').all():
        raise AssertionError(f'{name}: 分组不一致')
    for col in fields:
        a=pd.to_numeric(both[col+'_sql'],errors='coerce').to_numpy(dtype=float)
        b=pd.to_numeric(both[col+'_pd'],errors='coerce').to_numpy(dtype=float)
        if not np.allclose(a,b,rtol=1e-10,atol=1e-8,equal_nan=True):
            raise AssertionError(f'{name}: {col} SQL 与 pandas 不一致')


def independently_validate(sql):
    d=raw_pandas(); o=d['orders']; c=d['customers']; i=d['order_items']; p=d['products']; t=d['translation']
    for f,keys in [(o,['order_id']),(c,['customer_id']),(i,['order_id','order_item_id']),
                   (p,['product_id']),(t,['product_category_name'])]: assert_keys(f,keys)
    o=o[(o.order_status=='delivered') & o.order_id.str.strip().ne('')].copy()
    o['purchased_at']=pd.to_datetime(o.order_purchase_timestamp,errors='coerce')
    o=o[o.purchased_at.notna()].copy()
    o=o.merge(c[['customer_id','customer_unique_id','customer_state']],on='customer_id',how='left',validate='many_to_one',indicator=True)
    if not o['_merge'].eq('both').all() or o.customer_unique_id.isna().any() or o.customer_unique_id.eq('').any():
        raise ValueError('订单客户未匹配或用户 ID 缺失')
    o=o.drop(columns='_merge'); o['month']=o.purchased_at.dt.to_period('M').dt.to_timestamp()
    x=i.merge(o[['order_id','customer_unique_id','customer_state','month']],on='order_id',how='inner',validate='many_to_one')
    if set(x.order_id)!=set(o.order_id): raise ValueError('已送达订单缺少商品行，需先决定口径')
    x=x.merge(p[['product_id','product_category_name']],on='product_id',how='left',validate='many_to_one',indicator=True)
    if not x['_merge'].eq('both').all(): raise ValueError('商品 ID 未匹配，不能当成空品类')
    x=x.drop(columns='_merge').merge(t[['product_category_name','product_category_name_english']],on='product_category_name',how='left',validate='many_to_one')
    price=pd.to_numeric(x.price,errors='coerce')
    if price.isna().any() or (price<0).any() or not np.allclose(price*100,np.round(price*100),rtol=0,atol=1e-6):
        raise ValueError('商品价格缺失、为负或精度超出分，需先核查')
    # 金额转为整数分独立计算，避免 SQL 和 pandas 同时共享浮点加总。
    x['cents']=np.rint(price*100).astype('int64')
    cat=x.product_category_name.fillna('').str.strip(); en=x.product_category_name_english.fillna('').str.strip()
    x['category_status']=np.select([cat.eq(''), en.eq('')],['unknown','untranslated'],default='translated')
    x['category']=np.where(cat.eq(''),'Unknown category',np.where(en.eq(''),cat,en))
    o['customer_state']=o.customer_state.fillna('').str.strip().replace('','Unknown')
    x['customer_state']=x.customer_state.fillna('').str.strip().replace('','Unknown')
    order=x.groupby(['order_id','customer_unique_id','customer_state','month'],as_index=False,dropna=False).agg(cents=('cents','sum'),items=('cents','size'))
    u=order.groupby('customer_unique_id').size(); total=order.cents.sum()/100; n=len(order); items=len(x); buyers=len(u); rep=int((u>=2).sum())
    overall=pd.DataFrame([dict(gmv=total,orders=n,items=items,buyers=buyers,repeat_buyers=rep,average_order_value=total/n,average_item_price=total/items,repeat_rate=rep/buyers)])
    compare(sql['overall'],overall,[],list(overall.columns),'overall')
    mu=order.groupby(['month','customer_unique_id']).size().rename('count').reset_index()
    mb=mu.groupby('month').agg(buyers=('count','size'),repeat_buyers=('count',lambda s:(s>=2).sum()))
    month=order.groupby('month').agg(cents=('cents','sum'),orders=('order_id','size'),items=('items','sum')).join(mb)
    month=month.reindex(pd.date_range(month.index.min(),month.index.max(),freq='MS'),fill_value=0).rename_axis('month').reset_index()
    month['gmv']=month.cents/100; month['average_order_value']=month.gmv/month.orders.replace(0,np.nan)
    month['average_item_price']=month.gmv/month['items'].replace(0,np.nan); month['repeat_rate']=month.repeat_buyers/month.buyers.replace(0,np.nan)
    month['gmv_mom']=month.gmv.div(month.gmv.shift().replace(0,np.nan))-1
    month['orders_mom']=month.orders.div(month.orders.shift().replace(0,np.nan))-1
    for col in ['buyers','average_order_value','average_item_price','repeat_rate']:
        month[col+'_mom']=month[col].div(month[col].shift().replace(0,np.nan))-1
    month['repeat_rate_pp_change']=100*(month.repeat_rate-month.repeat_rate.shift())
    compare(sql['monthly'],month,['month'],['gmv','orders','buyers','items','repeat_buyers','average_order_value','average_item_price','repeat_rate','gmv_mom','orders_mom','buyers_mom','average_order_value_mom','average_item_price_mom','repeat_rate_mom','repeat_rate_pp_change'],'monthly')
    cat=x.groupby(['category_status','category'],as_index=False).agg(cents=('cents','sum'),items=('cents','size'),orders=('order_id','nunique'),buyers=('customer_unique_id','nunique'))
    cat=cat.sort_values(['cents','category_status','category'],ascending=[False,True,True]).reset_index(drop=True)
    cat['gmv']=cat.cents/100; cat['gmv_rank']=np.arange(1,len(cat)+1); cat['cumulative_gmv']=cat.cents.cumsum()/100
    cat['total_gmv']=total; cat['gmv_share']=cat.cents/cat.cents.sum(); cat['cumulative_share']=cat.cents.cumsum()/cat.cents.sum()
    cat['in_top_80pct']=(cat.cents.cumsum()-cat.cents)/cat.cents.sum()<.8
    cat['average_order_value']=cat.gmv/cat.orders; cat['average_item_price']=cat.gmv/cat['items']
    compare(sql['category_summary'],cat,['category_status','category'],['gmv','items','orders','buyers','gmv_rank','cumulative_gmv','total_gmv','gmv_share','cumulative_share','in_top_80pct','average_order_value','average_item_price'],'categories')
    cat_status=x.groupby('category_status',as_index=False).agg(cents=('cents','sum'),items=('cents','size'))
    cat_status['gmv']=cat_status.cents/100; cat_status['gmv_share']=cat_status.gmv/total
    compare(sql['category_status_summary'],cat_status,['category_status'],['items','gmv','gmv_share'],'category status')
    st=order.groupby('customer_state',as_index=False).agg(cents=('cents','sum'),items=('items','sum'),orders=('order_id','size'),buyers=('customer_unique_id','nunique')).rename(columns={'customer_state':'state'})
    st['gmv']=st.cents/100;st['gmv_share']=st.gmv/total;st['average_order_value']=st.gmv/st.orders;st['average_item_price']=st.gmv/st['items']
    compare(sql['state_summary'],st,['state'],['gmv','items','orders','buyers','gmv_share','average_order_value','average_item_price'],'states')
    mc=x.groupby(['month','category_status','category'],as_index=False).agg(cents=('cents','sum'),items=('cents','size'),orders=('order_id','nunique'),buyers=('customer_unique_id','nunique'))
    mc['gmv']=mc.cents/100;mc['average_order_value']=mc.gmv/mc.orders;mc['average_item_price']=mc.gmv/mc['items']
    compare(sql['monthly_category'],mc,['month','category_status','category'],['gmv','items','orders','buyers','average_order_value','average_item_price'],'monthly category')
    ms=order.groupby(['month','customer_state'],as_index=False).agg(cents=('cents','sum'),items=('items','sum'),orders=('order_id','size'),buyers=('customer_unique_id','nunique')).rename(columns={'customer_state':'state'})
    ms['gmv']=ms.cents/100;ms['average_order_value']=ms.gmv/ms.orders;ms['average_item_price']=ms.gmv/ms['items']
    compare(sql['monthly_state'],ms,['month','state'],['gmv','items','orders','buyers','average_order_value','average_item_price'],'monthly state')
    return pd.DataFrame([{'result':name,'validation':'passed','method':'independent pandas from raw CSV; monetary aggregation in integer cents'} for name in RESULTS])


def charts(sql):
    FIG.mkdir(parents=True,exist_ok=True)
    m=sql['monthly'].copy(); m['month']=pd.to_datetime(m.month)
    fig,ax=plt.subplots(figsize=(11,4.8));ax.plot(m.month,m.gmv/1e6,marker='o',lw=1.8,color='#236a86');ax.set(xlabel='Order month',ylabel='Product GMV (BRL million)',title='Delivered orders: monthly product GMV');ax.grid(axis='y',alpha=.25);fig.autofmt_xdate();fig.tight_layout();fig.savefig(FIG/'01_monthly_gmv.png',dpi=180);plt.close(fig)
    c=sql['category_summary'].sort_values('gmv_rank');fig,ax=plt.subplots(figsize=(10,4.8));ax.bar(c.gmv_rank,c.gmv/1e6,color=np.where(c.in_top_80pct,'#236a86','#c8d6dd'),width=1);ax.set(xlabel='Category rank (highest GMV first)',ylabel='Product GMV (BRL million)',title='Category GMV and cumulative contribution');a2=ax.twinx();a2.plot(c.gmv_rank,100*c.cumulative_share,color='#d77335',linewidth=2);a2.axhline(80,color='#777',ls='--',lw=1);a2.set_ylabel('Cumulative GMV share (%)');a2.set_ylim(0,105);fig.tight_layout();fig.savefig(FIG/'01_category_pareto.png',dpi=180);plt.close(fig)
    s=sql['state_summary'].sort_values('gmv',ascending=False).head(10).sort_values('gmv');fig,ax=plt.subplots(figsize=(8,4.8));ax.barh(s.state,s.gmv/1e6,color='#236a86');ax.set(xlabel='Product GMV (BRL million)',ylabel='Customer state',title='Top 10 customer states by GMV');fig.tight_layout();fig.savefig(FIG/'01_top_states.png',dpi=180);plt.close(fig)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect()
    for name, filename in FILES.items():
        path=str(RAW/filename).replace("'","''")
        con.execute(f"create view {name} as select * from read_csv('{path}', header=true, all_varchar=true)")
    for file in ['02_stage1_model.sql','03_stage1_outputs.sql']:
        con.execute((ROOT/'sql'/file).read_text(encoding='utf8'))
    results={name:con.execute(f'select * from {name}').df() for name in RESULTS}
    # 核验完成后才写出文件，避免将错误结果当作最终交付。
    validation=independently_validate(results)
    # 边界月和无已送达订单月份显式标记；此标记不代表其余月份已确认数据完整。
    month_df=results['monthly']
    month_df['period_note']=np.where(month_df.orders.eq(0),'no_delivered_orders',
        np.where(month_df.month.isin([month_df.month.min(),month_df.month.max()]),'edge_of_delivered_range','observed'))
    for name,file in RESULTS.items(): results[name].to_csv(OUT/file,index=False,date_format='%Y-%m-%d')
    results['category_summary'].loc[results['category_summary'].in_top_80pct].sort_values('gmv_rank').to_csv(OUT/'01_pareto_80.csv',index=False)
    validation.to_csv(OUT/'01_validation.csv',index=False)
    charts(results)
    print('阶段 1 SQL 输出与独立 pandas 复算全部一致。')

if __name__=='__main__': main()
