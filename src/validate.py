"""阶段 4–5 的原始 CSV pandas 独立核验；不读取 SQL 中间表。"""
import hashlib,json,platform
import numpy as np
import pandas as pd
from stage1 import ROOT,RAW,OUT,raw_pandas
from stage3 import independent_raw


def main():
    d=raw_pandas();o=d['orders'];o=o[o.order_status.eq('delivered')].copy();o['month']=pd.to_datetime(o.order_purchase_timestamp).dt.to_period('M').dt.to_timestamp()
    o=o.merge(d['customers'][['customer_id','customer_unique_id','customer_state']],on='customer_id',validate='many_to_one')
    i=d['order_items'].copy();i['cents']=np.rint(pd.to_numeric(i.price)*100).astype('int64')
    lines=i.merge(o[['order_id','month','customer_unique_id','customer_state']],on='order_id',validate='many_to_one').merge(d['products'][['product_id','product_category_name']],on='product_id',validate='many_to_one').merge(d['translation'],on='product_category_name',how='left',validate='many_to_one')
    lines['category']=np.where(lines.product_category_name.eq(''),'Unknown category',lines.product_category_name_english.fillna(lines.product_category_name))
    first=o.groupby('customer_unique_id').month.min();lines['buyer_type']=np.where(lines.month.eq(lines.customer_unique_id.map(first)),'new_observed','returning_observed')
    monthly=o.groupby('month').agg(orders=('order_id','size'),buyers=('customer_unique_id','nunique'));monthly['gmv']=lines.groupby('month').cents.sum()/100;monthly=monthly.reindex(pd.date_range(monthly.index.min(),monthly.index.max(),freq='MS'),fill_value=0);monthly.index.name='month';monthly['orders_per_buyer']=monthly.orders/monthly.buyers.replace(0,np.nan);monthly['aov']=monthly.gmv/monthly.orders.replace(0,np.nan)
    shipped=pd.read_csv(OUT/'04_monthly.csv',parse_dates=['month']).set_index('month')
    for c in monthly:np.testing.assert_allclose(monthly[c],shipped.loc[monthly.index,c],atol=1e-8,rtol=1e-10)
    f=pd.read_csv(OUT/'04_factors.csv',parse_dates=['month','baseline']);max_res=0.
    for (month,base),g in f.groupby(['month','baseline']):
        before=monthly.loc[base];after=monthly.loc[month];change=after.gmv-before.gmv;weight=change/np.log(after.gmv/before.gmv)
        expected=[weight*np.log(after[r.factor]/before[r.factor]) for r in g.itertuples()]
        np.testing.assert_allclose(g.lmdi,expected,atol=1e-7)
        for method in ['lmdi','substitution']:
            residual=abs(g[method].sum()-change);assert residual<1e-7;max_res=max(max_res,residual)
    drills=pd.read_csv(OUT/'04_drilldown.csv',parse_dates=['month']);dim_res=0.
    for (month,dimension),g in drills.groupby(['month','dimension']):
        base=month-pd.offsets.MonthBegin(1);column={'category':'category','state':'customer_state','buyer_type':'buyer_type'}[dimension]
        old=lines[lines.month.eq(base)].groupby(column).cents.sum()/100;new=lines[lines.month.eq(month)].groupby(column).cents.sum()/100
        delta=new.subtract(old,fill_value=0);np.testing.assert_allclose(g.set_index('segment').change.reindex(delta.index),delta,atol=1e-7)
        residual=abs(g.change.sum()-(monthly.loc[month,'gmv']-monthly.loc[base,'gmv']));dim_res=max(dim_res,residual);assert residual<1e-7
        np.testing.assert_allclose(g[['volume_effect','mix_effect','rate_effect']].sum(axis=1),g.change,atol=1e-7)
    _,raw,_,_=independent_raw('date');sample=raw[raw.answer>=raw.order_delivered_customer_date].set_index('order_id');pairs=pd.read_csv(OUT/'05_matches.csv')
    assert not pairs.treated_id.duplicated().any() and not pairs.control_id.duplicated().any()
    assert set(pairs.treated_id).isdisjoint(pairs.control_id)
    assert sample.loc[pairs.treated_id,'delayed'].eq(1).all() and sample.loc[pairs.control_id,'delayed'].eq(0).all()
    np.testing.assert_equal(sample.loc[pairs.treated_id,'bad_review'].to_numpy(),pairs.treated_bad)
    np.testing.assert_equal(sample.loc[pairs.control_id,'bad_review'].to_numpy(),pairs.control_bad)
    meta=json.loads((OUT/'05_metadata.json').read_text());assert meta['pairs']==len(pairs) and meta['sample_n']==len(sample)
    assert (pairs.treated_logit-pairs.control_logit).abs().le(meta['caliper_logit']+1e-12).all()
    for col in ['treated_logit','control_logit']:assert pairs[col].between(*meta['support_logit']).all()
    result=dict(status='passed',monthly_rows=len(monthly),operating_orders=len(o),operating_buyers=o.customer_unique_id.nunique(),gmv=lines.cents.sum()/100,factor_max_residual=max_res,dimension_max_residual=dim_res,mix_rate_max_residual=float(drills.residual.abs().max()),causal_sample=len(sample),matched_pairs=len(pairs),att=float((pairs.treated_bad-pairs.control_bad).mean()))
    (OUT/'04_05_validation.json').write_text(json.dumps(result,indent=2,default=int));print(result)
    import duckdb,sklearn,scipy,statsmodels
    provenance={'source':'Kaggle olist/brazilian-ecommerce; existing local raw CSV copy','python':platform.python_version(),'duckdb':duckdb.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__,'scipy':scipy.__version__,'statsmodels':statsmodels.__version__,'inputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(RAW.glob('*.csv'))}}
    (OUT/'04_05_provenance.json').write_text(json.dumps(provenance,indent=2))

if __name__=='__main__':main()
