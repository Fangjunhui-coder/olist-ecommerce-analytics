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
    delivery,raw,_,_=independent_raw('date');sample=raw[raw.answer>=raw.order_delivered_customer_date].set_index('order_id');pairs=pd.read_csv(OUT/'05_matches.csv')
    assert not pairs.treated_id.duplicated().any() and not pairs.control_id.duplicated().any()
    assert set(pairs.treated_id).isdisjoint(pairs.control_id)
    assert sample.loc[pairs.treated_id,'delayed'].eq(1).all() and sample.loc[pairs.control_id,'delayed'].eq(0).all()
    np.testing.assert_equal(sample.loc[pairs.treated_id,'bad_review'].to_numpy(),pairs.treated_bad)
    np.testing.assert_equal(sample.loc[pairs.control_id,'bad_review'].to_numpy(),pairs.control_bad)
    meta=json.loads((OUT/'05_metadata.json').read_text());assert meta['pairs']==len(pairs) and meta['sample_n']==len(sample)
    assert (pairs.treated_logit-pairs.control_logit).abs().le(meta['caliper_logit']+1e-12).all()
    for col in ['treated_logit','control_logit']:assert pairs[col].between(*meta['support_logit']).all()
    # Independent time-aware seller features: searchsorted on purchase/completion
    # timestamps, never using final outcomes of orders still pending at purchase.
    primary=i.assign(price_number=pd.to_numeric(i.price),item_number=pd.to_numeric(i.order_item_id)).sort_values(['order_id','price_number','item_number'],ascending=[True,False,True]).drop_duplicates('order_id')[['order_id','seller_id']]
    history=primary.merge(d['orders'][['order_id','order_purchase_timestamp']],on='order_id',validate='one_to_one')
    history['purchased']=pd.to_datetime(history.order_purchase_timestamp,errors='coerce')
    completed=primary.merge(delivery[['order_id','order_delivered_customer_date','delayed']],on='order_id',validate='one_to_one')
    history_groups={k:g.purchased.dropna().sort_values().to_numpy() for k,g in history.groupby('seller_id')}
    completed_groups={k:g.sort_values('order_delivered_customer_date') for k,g in completed.groupby('seller_id')}
    sample=sample.join(primary.set_index('order_id').seller_id)
    expected=pd.DataFrame(index=sample.index)
    for seller,g in sample.groupby('seller_id'):
        times=g.order_purchase_timestamp.to_numpy();purchases=history_groups[seller]
        expected.loc[g.index,'seller_prior_orders']=np.searchsorted(purchases,times,side='left')
        c=completed_groups.get(seller)
        if c is None:
            counts=np.zeros(len(g),dtype=int);late=counts.copy()
        else:
            counts=np.searchsorted(c.order_delivered_customer_date.to_numpy(),times,side='left')
            late=np.r_[0,c.delayed.cumsum().to_numpy()][counts]
        expected.loc[g.index,'seller_completed_orders']=counts
        expected.loc[g.index,'seller_prior_late']=late
    expected['seller_history_delay_rate']=(expected.seller_prior_late/expected.seller_completed_orders.replace(0,np.nan)).fillna(0)
    expected['seller_no_history']=expected.seller_prior_orders.eq(0).astype(int)
    expected['seller_no_completed_history']=expected.seller_completed_orders.eq(0).astype(int)
    shipped_history=pd.read_csv(OUT/'05_seller_history.csv').set_index('order_id')
    for column in expected:
        np.testing.assert_allclose(expected[column],shipped_history.loc[expected.index,column],atol=1e-12)
    # pandas dummy encoding and means independently reproduce every SMD column.
    numeric=pd.DataFrame({'log_gmv':np.log1p(sample.product_gmv.astype(float)),'log_freight':np.log1p(sample.freight.astype(float)),'items':sample['items'].astype(float),'cross_state':sample.cross_state.astype(float),
        'expected_days':(sample.order_estimated_delivery_date.dt.normalize()-sample.order_purchase_timestamp.dt.normalize()).dt.days,
        'log_seller_prior_orders':np.log1p(expected.seller_prior_orders),
        'seller_history_delay_rate':expected.seller_history_delay_rate,'seller_no_history':expected.seller_no_history,'seller_no_completed_history':expected.seller_no_completed_history})
    categories=sample[['category','customer_state']].copy();categories['purchase_month']=sample.order_purchase_timestamp.dt.strftime('%Y-%m')
    for col in ['category','customer_state']:
        treated_counts=sample[sample.delayed.eq(1)][col].value_counts()
        categories[col]=categories[col].where(categories[col].map(treated_counts).fillna(0)>=20,'[other]')
    covariates=pd.concat([numeric,pd.get_dummies(categories,dtype=float)],axis=1)
    treated=covariates[sample.delayed.eq(1)];control=covariates[sample.delayed.eq(0)]
    denominator=((treated.var()+control.var())/2)**.5
    before=(treated.mean()-control.mean())/denominator
    after=(covariates.loc[pairs.treated_id].mean()-covariates.loc[pairs.control_id].mean())/denominator
    balance=pd.read_csv(OUT/'05_balance.csv').set_index('covariate')
    np.testing.assert_allclose(balance.smd_before.sort_index(),before.fillna(0).sort_index(),atol=1e-10)
    np.testing.assert_allclose(balance.smd_after.sort_index(),after.fillna(0).sort_index(),atol=1e-10)
    bootstrap_rng=np.random.default_rng(20261101)
    differences=(pairs.treated_bad-pairs.control_bad).to_numpy(float)
    bootstrap=np.array([bootstrap_rng.choice(differences,len(differences),replace=True).mean() for _ in range(1000)])
    ci_low,ci_high=np.quantile(bootstrap,[.025,.975])
    comparison=pd.read_csv(OUT/'05_method_comparison.csv').set_index('method')
    np.testing.assert_allclose(comparison.loc['PSM_matched_ATT',['estimate','ci_low','ci_high']].to_numpy(float),[differences.mean(),ci_low,ci_high],atol=1e-12)
    legacy=json.loads((OUT/'05_legacy_psm_metadata.json').read_text())
    result=dict(status='passed',monthly_rows=len(monthly),operating_orders=len(o),operating_buyers=o.customer_unique_id.nunique(),gmv=lines.cents.sum()/100,factor_max_residual=max_res,dimension_max_residual=dim_res,mix_rate_max_residual=float(drills.residual.abs().max()),causal_sample=len(sample),matched_pairs=len(pairs),att=float((pairs.treated_bad-pairs.control_bad).mean()),seller_history_rows_checked=len(expected),max_abs_smd_before=float(before.abs().max()),max_abs_smd_after=float(after.abs().max()),unbalanced_columns=int(after.abs().ge(.1).sum()),att_ci_low=float(ci_low),att_ci_high=float(ci_high),psm_legacy={'pairs':legacy['pairs'],'max_abs_smd_before':legacy['max_abs_smd_before'],'max_abs_smd_after':legacy['max_abs_smd_after'],'unbalanced_columns':legacy['unbalanced_after'],'att':float(comparison.loc['PSM_legacy_seller_onehot_unbalanced','estimate'])},single_order_buyers=int(o.groupby('customer_unique_id').size().eq(1).sum()),single_order_buyer_share=float(o.groupby('customer_unique_id').size().eq(1).mean()))
    (OUT/'04_05_validation.json').write_text(json.dumps(result,indent=2,default=int));print(result)
    import duckdb,sklearn,scipy,statsmodels
    provenance={'source':'Kaggle olist/brazilian-ecommerce; existing local raw CSV copy','python':platform.python_version(),'duckdb':duckdb.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__,'scipy':scipy.__version__,'statsmodels':statsmodels.__version__,'inputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(RAW.glob('*.csv'))}}
    (OUT/'04_05_provenance.json').write_text(json.dumps(provenance,indent=2))

if __name__=='__main__':main()
