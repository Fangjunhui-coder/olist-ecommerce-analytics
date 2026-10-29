"""阶段 3：订单粒度配送分析、统计检验和观察性逻辑回归。"""
import argparse
import duckdb
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, norm
from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint
import statsmodels.api as sm
import statsmodels.formula.api as smf
from stage1 import ROOT, RAW, OUT, FILES, raw_pandas, assert_keys, compare

EXTRA={'sellers':'olist_sellers_dataset.csv','order_reviews':'olist_order_reviews_dataset.csv'}


def load_sql(policy):
    con=duckdb.connect()
    for name,filename in {**FILES,**EXTRA}.items():
        path=str(RAW/filename).replace("'","''");con.execute(f"create view {name} as select * from read_csv('{path}', header=true, all_varchar=true)")
    for f in ['02_stage1_model.sql','07_delivery_analysis.sql','08_review_audit.sql']:
        sql=(ROOT/'sql'/f).read_text(encoding='utf8')
        if policy=='timestamp' and f=='07_delivery_analysis.sql':
            sql=sql.replace("cast(delivered_at as date)>cast(estimated_at as date)","delivered_at>estimated_at").replace("greatest(date_diff('day',cast(estimated_at as date),cast(delivered_at as date)),0)*86400","greatest(date_diff('second',estimated_at,delivered_at),0)").replace("cast(review_answer_at as date)<=cast(estimated_at as date)","review_answer_at<estimated_at")
        con.execute(sql)
    return con


def independent_raw(policy):
    d=raw_pandas();d.update({name:pd.read_csv(RAW/file,dtype=str,keep_default_na=False) for name,file in EXTRA.items()})
    o=d['orders']; c=d['customers']; i=d['order_items']; p=d['products']; s=d['sellers']; t=d['translation']; v=d['order_reviews']
    for x,cols in [(o,['order_id']),(c,['customer_id']),(i,['order_id','order_item_id']),(p,['product_id']),(s,['seller_id']),(t,['product_category_name']),(v,['review_id','order_id'])]:assert_keys(x,cols)
    for col in ['order_purchase_timestamp','order_delivered_customer_date','order_estimated_delivery_date']:o[col]=pd.to_datetime(o[col],errors='coerce')
    e=o[(o.order_status=='delivered') & o.order_purchase_timestamp.notna() & o.order_id.str.strip().ne('')].copy()
    e=e.merge(c[['customer_id','customer_unique_id','customer_state']],on='customer_id',how='left',validate='many_to_one',indicator=True)
    if not e['_merge'].eq('both').all() or e.customer_unique_id.eq('').any():raise ValueError('客户关联或用户 ID 无效')
    e=e.drop(columns='_merge');v['answer']=pd.to_datetime(v.review_answer_timestamp,errors='coerce');v['created']=pd.to_datetime(v.review_creation_date,errors='coerce')
    review_rows=v.merge(e[['order_id']],on='order_id',how='inner',validate='many_to_one'); counts=review_rows.groupby('order_id').size();multi=counts[counts>1];mr=review_rows[review_rows.order_id.isin(multi.index)].copy()
    review_stats={'delivered_orders':len(e),'no_review_orders':int(len(e)-e.order_id.isin(v.order_id).sum()),'multi_review_orders':len(multi),'multi_review_rows':len(mr),'multi_with_2':int((multi==2).sum()),'multi_with_3':int((multi==3).sum()),'multi_with_4plus':int((multi>=4).sum()),'multi_different_scores':int((mr.groupby('order_id').review_score.nunique()>1).sum()),'multi_answer_missing_rows':int(mr.answer.isna().sum()),'multi_creation_missing_rows':int(mr.created.isna().sum())}
    for col in ['answer','created']:
        mx=mr.groupby('order_id')[col].transform('max');top=mr[mr[col].eq(mx)]
        review_stats[f'{col}_latest_ties']=int((top.groupby('order_id').size()>1).sum())
        review_stats[f'{col}_latest_ties_different_scores']=int((top.groupby('order_id').review_score.nunique()>1).sum())
    if review_rows.answer.isna().any():raise ValueError('评价回复时间缺失，无法安全选取最新评价')
    max_answer=review_rows.groupby('order_id').answer.transform('max');ties=review_rows[review_rows.answer.eq(max_answer)].groupby('order_id').size()
    if (ties>1).any():raise ValueError('存在回复时间最新值并列的评价，需要确认处理规则')
    review_rows['score']=pd.to_numeric(review_rows.review_score,errors='coerce')
    if review_rows.score.isna().any() or not review_rows.score.isin([1,2,3,4,5]).all():raise ValueError('评价分数无效')
    latest=review_rows.sort_values(['order_id','answer','review_id'],ascending=[True,False,False]).drop_duplicates('order_id')
    earliest=review_rows.sort_values(['order_id','answer','review_id'],ascending=[True,True,True]).drop_duplicates('order_id')
    paired=latest[['order_id','score']].merge(earliest[['order_id','score']],on='order_id',suffixes=('_latest','_earliest'),validate='one_to_one')
    review_stats['multi_latest_vs_earliest_score_diff']=int((paired.score_latest!=paired.score_earliest).sum())
    review_stats['multi_latest_vs_earliest_bad_flag_diff']=int(((paired.score_latest<=2)!=(paired.score_earliest<=2)).sum())
    review_stats['estimate_missing_or_unparseable']=int(e.order_estimated_delivery_date.isna().sum())
    review_stats['delivery_missing_or_unparseable']=int(e.order_delivered_customer_date.isna().sum())
    review_stats['delivery_earlier_than_purchase']=int((e.order_delivered_customer_date.notna() & (e.order_delivered_customer_date<e.order_purchase_timestamp)).sum())
    dvalid=e[e.order_delivered_customer_date.notna() & e.order_estimated_delivery_date.notna() & (e.order_delivered_customer_date>=e.order_purchase_timestamp)].copy()
    if policy=='date':
        actual=dvalid.order_delivered_customer_date.dt.normalize(); estimated=dvalid.order_estimated_delivery_date.dt.normalize()
    else:
        actual=dvalid.order_delivered_customer_date;estimated=dvalid.order_estimated_delivery_date
    dvalid['delayed']=(actual>estimated).astype(int)
    dvalid['late_seconds']=(actual-estimated).dt.total_seconds().clip(lower=0)
    x=i.merge(dvalid[['order_id','customer_state']],on='order_id',how='inner',validate='many_to_one')
    if set(x.order_id)!=set(dvalid.order_id):raise ValueError('有效订单缺少商品明细')
    x=x.merge(s[['seller_id','seller_state']],on='seller_id',how='left',validate='many_to_one',indicator=True)
    if not x._merge.eq('both').all() or x.seller_state.eq('').any() or x.customer_state.eq('').any():raise ValueError('卖家或州缺失')
    x=x.drop(columns='_merge').merge(p[['product_id','product_category_name']],on='product_id',how='left',validate='many_to_one',indicator=True)
    if not x._merge.eq('both').all():raise ValueError('商品未匹配')
    x=x.drop(columns='_merge').merge(t[['product_category_name','product_category_name_english']],on='product_category_name',how='left',validate='many_to_one')
    for col in ['price','freight_value']:
        n=pd.to_numeric(x[col],errors='coerce')
        if n.isna().any() or (n<0).any() or not np.allclose(n*100,np.rint(n*100),rtol=0,atol=1e-6):raise ValueError('价格或运费无效')
        x[col+'_cents']=np.rint(n*100).astype('int64')
    x['cross_state']=(x.seller_state!=x.customer_state).astype(int)
    cat=x.product_category_name.fillna('').str.strip();eng=x.product_category_name_english.fillna('').str.strip()
    x['category']=np.where(cat.eq(''),'[unknown]',np.where(eng.eq(''),'[untranslated] '+cat,eng))
    x['item_number']=pd.to_numeric(x.order_item_id,errors='raise')
    primary=x.sort_values(['order_id','price_cents','item_number'],ascending=[True,False,True]).drop_duplicates('order_id')[['order_id','category']]
    features=x.groupby('order_id',as_index=False).agg(price_cents=('price_cents','sum'),freight_cents=('freight_value_cents','sum'),items=('item_number','size'),cross_state=('cross_state','max')).merge(primary,on='order_id',validate='one_to_one')
    features['product_gmv']=features.price_cents/100;features['freight']=features.freight_cents/100
    frame=dvalid.merge(latest[['order_id','score','answer','created']],on='order_id',how='inner',validate='one_to_one').merge(features,on='order_id',how='inner',validate='one_to_one')
    frame['bad_review']=(frame.score<=2).astype(int)
    frame['delay_band']=np.select([frame.delayed.eq(0),frame.late_seconds<=3*86400,frame.late_seconds<=7*86400],['on_time','1_to_3_days','4_to_7_days'],default='over_7_days')
    review_stats['estimate_at_midnight']=int(dvalid.order_estimated_delivery_date.dt.strftime('%H:%M:%S').eq('00:00:00').sum())
    review_stats['valid_delivery_late_orders']=int(dvalid.delayed.sum())
    review_stats['late_same_calendar_day']=int(((dvalid.order_delivered_customer_date>dvalid.order_estimated_delivery_date) & dvalid.order_delivered_customer_date.dt.normalize().eq(dvalid.order_estimated_delivery_date.dt.normalize())).sum())
    review_stats['valid_delivery_orders']=len(dvalid);review_stats['valid_delivery_no_review']=int((~dvalid.order_id.isin(latest.order_id)).sum())
    review_stats['analysis_orders']=len(frame);review_stats['review_before_delivery']=int((frame.answer<frame.order_delivered_customer_date).sum());review_stats['review_after_or_at_delivery']=int((frame.answer>=frame.order_delivered_customer_date).sum())
    return dvalid,frame,x,review_stats


def aggregate(frame,group):
    a=frame.groupby(group,as_index=False).agg(orders=('order_id','size'),bad_reviews=('bad_review','sum'),bad_rate=('bad_review','mean'),mean_score=('score','mean'))
    return a


def validate(con,dvalid,frame,items,policy):
    # 把 SQL 构造的订单级分析变量与独立 pandas 逐单对账。
    time_counts=con.execute("select count(*) filter(where cast(estimated_at as time)=time '00:00:00') as midnight, sum(delayed) as late, count(*) filter(where delivered_at>estimated_at and cast(delivered_at as date)=cast(estimated_at as date)) as same_day from delivery_orders").fetchone()
    independent=(int(dvalid.order_estimated_delivery_date.dt.strftime('%H:%M:%S').eq('00:00:00').sum()),int(dvalid.delayed.sum()),int(((dvalid.order_delivered_customer_date>dvalid.order_estimated_delivery_date) & dvalid.order_delivered_customer_date.dt.normalize().eq(dvalid.order_estimated_delivery_date.dt.normalize())).sum()))
    if time_counts!=independent:raise AssertionError('预计送达时间或同日延迟检查不一致')
    s=con.execute('select * from analysis_orders').df()
    compare(s,frame,['order_id'],['delayed','late_seconds','review_score' if False else 'bad_review','items','cross_state','product_gmv','freight'],'订单级')
    j=s[['order_id','review_score','category','delay_band','customer_state','customer_unique_id']].merge(frame[['order_id','score','category','delay_band','customer_state','customer_unique_id']],on='order_id',validate='one_to_one',suffixes=('_sql','_pd'))
    for col in ['category','delay_band','customer_state','customer_unique_id']:
        if not j[col+'_sql'].eq(j[col+'_pd']).all():raise AssertionError(f'{col} 不一致')
    if not j.review_score.eq(j.score).all():raise AssertionError('评价分数不一致')
    for table,key in [('delay_comparison','delayed'),('delay_bands','delay_band')]:
        compare(con.execute(f'select * from {table}').df(),aggregate(frame,key),[key],['orders','bad_reviews','bad_rate','mean_score'],table)
    st=dvalid.groupby('customer_state',as_index=False).agg(orders=('order_id','size'),delayed_orders=('delayed','sum'),delay_rate=('delayed','mean')).rename(columns={'customer_state':'state'});st=st[st.orders>=30]
    compare(con.execute('select * from delivery_state').df(),st,['state'],['orders','delayed_orders','delay_rate'],'州延迟')
    si=items[['order_id','seller_id']].drop_duplicates().merge(dvalid[['order_id','delayed']],on='order_id',validate='many_to_one')
    sg=si.groupby('seller_id',as_index=False).agg(orders=('order_id','size'),delayed_orders=('delayed','sum'),delay_rate=('delayed','mean'));sg=sg[sg.orders>=30]
    compare(con.execute('select * from delivery_seller').df(),sg,['seller_id'],['orders','delayed_orders','delay_rate'],'卖家延迟')
    before_expected=(frame.answer.dt.normalize()<=frame.order_estimated_delivery_date.dt.normalize()) if policy=='date' else (frame.answer<frame.order_estimated_delivery_date)
    frame['review_timing']=np.select([frame.answer>=frame.order_delivered_customer_date,before_expected],['after_or_at_delivery','before_estimate_and_delivery'],default='after_estimate_before_delivery')
    timing=frame.groupby(['review_timing','delayed'],as_index=False).agg(orders=('order_id','size'),bad_reviews=('bad_review','sum'),bad_rate=('bad_review','mean'))
    compare(con.execute('select * from review_timing').df(),timing,['review_timing','delayed'],['orders','bad_reviews','bad_rate'],'评价时间顺序')
    return s


def fit_model(frame, reference=None):
    df=frame.copy(); ref=frame if reference is None else reference
    cats=ref.category.value_counts();states=ref.customer_state.value_counts()
    df['category_model']=df.category.where(df.category.map(cats)>=500,'[other]')
    df['state_model']=df.customer_state.where(df.customer_state.map(states)>=300,'Other')
    df['log_product_gmv']=np.log1p(df.product_gmv.astype(float));df['log_freight']=np.log1p(df.freight.astype(float));df['items']=df['items'].astype(float)
    formula='bad_review ~ delayed + log_product_gmv + log_freight + items + cross_state + C(category_model) + C(state_model)'
    model=smf.glm(formula=formula,data=df,family=sm.families.Binomial()).fit(cov_type='cluster',cov_kwds={'groups':df.customer_unique_id},maxiter=100)
    if not model.converged:raise RuntimeError('逻辑回归未收敛')
    ci=model.conf_int();coef=model.params;out=pd.DataFrame({'term':coef.index,'coefficient':coef.values,'odds_ratio':np.exp(coef.values),'ci_lower':np.exp(ci[0].values),'ci_upper':np.exp(ci[1].values),'p_value':model.pvalues.values})
    out['log10_p_value']=(np.log(2)+norm.logsf(np.abs(model.tvalues.values)))/np.log(10)
    out.loc[out.p_value.eq(0),'p_value']=np.nan
    meta={'model_orders':int(model.nobs),'unique_buyers':int(df.customer_unique_id.nunique()),'events':int(df.bad_review.sum()),'category_levels':int(df.category_model.nunique()),'state_levels':int(df.state_model.nunique()),'converged':bool(model.converged),'covariance':'clustered by customer_unique_id','category_min_orders':500,'state_min_orders':300}
    return out,meta,df


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--policy',choices=['date','timestamp'],default='date');policy=parser.parse_args().policy
    con=load_sql(policy);dvalid,frame,items,review_stats=independent_raw(policy)
    audit_sql=con.execute('select * from review_audit_sql').df()
    compare(audit_sql,pd.DataFrame([review_stats]),[],list(audit_sql.columns),'多评价核查')
    model_data=validate(con,dvalid,frame,items,policy)
    table=con.execute('select * from delay_comparison order by delayed').df();bands=con.execute('select * from delay_bands').df()
    if set(table.delayed)!={0,1}:raise ValueError('对照组或延迟组为空')
    a=table.set_index('delayed');n0=int(a.loc[0,'orders']);n1=int(a.loc[1,'orders']);b0=int(a.loc[0,'bad_reviews']);b1=int(a.loc[1,'bad_reviews'])
    chi,p,dof,_=chi2_contingency([[b1,n1-b1],[b0,n0-b0]],correction=False)
    lo,hi=confint_proportions_2indep(b1,n1,b0,n0,method='newcomb',compare='diff')
    test=pd.DataFrame([{'delayed_orders':n1,'delayed_bad':b1,'on_time_orders':n0,'on_time_bad':b0,'risk_difference':b1/n1-b0/n0,'risk_difference_ci_low':lo,'risk_difference_ci_high':hi,'chi2':chi,'df':dof,'p_value':p if p>0 else np.nan,'log10_p_value':(np.log(2)+norm.logsf(np.sqrt(chi)))/np.log(10),'phi':np.sqrt(chi/(n0+n1))}])
    model,meta,model_frame=fit_model(model_data)
    # 若评价在交付之前给出，时间顺序限制解释；单独排除再拟合做敏感性对照。
    after=model_data[model_data.review_answer_at>=model_data.delivered_at].copy()
    sensitivity,sens_meta,_=fit_model(after, model_data)
    sens=sensitivity[sensitivity.term.eq('delayed')].copy();sens['sample_orders']=len(after);sens['unique_buyers']=sens_meta['unique_buyers']
    # 州和卖家的延迟分母为时间有效的全部已送达订单，不限定有评价。
    state=con.execute('select * from delivery_state order by delay_rate desc,orders desc,state').df()
    seller=con.execute('select * from delivery_seller order by delay_rate desc,orders desc,seller_id').df()
    for result in [state,seller]:
        low,high=proportion_confint(result.delayed_orders,result.orders,alpha=.05,method='wilson')
        result['delay_rate_ci_low']=low;result['delay_rate_ci_high']=high
    timing=con.execute('select * from review_timing order by review_timing,delayed').df()
    category_counts=model_frame.groupby('category_model',as_index=False).size().rename(columns={'size':'orders'})
    for name,df in [('03_review_audit.csv',pd.DataFrame([review_stats])),('03_review_timing.csv',timing),('03_delay_comparison.csv',table),('03_delay_bands.csv',bands),('03_chi_square.csv',test),('03_logistic_coefficients.csv',model),('03_logistic_model.csv',pd.DataFrame([meta])),('03_logistic_after_delivery_sensitivity.csv',sens),('03_delivery_states.csv',state),('03_delivery_sellers_min30.csv',seller),('03_model_category_counts.csv',category_counts)]:df.to_csv(OUT/(name if policy=='date' else name.replace('.csv','_timestamp.csv')),index=False)
    pd.DataFrame([{'check':x,'status':'passed','method':'pandas independently from raw CSV'} for x in ['review_audit','order_features','estimate_and_same_day','delay_comparison','delay_bands','review_timing','state_delay','seller_delay']]).to_csv(OUT/('03_validation.csv' if policy=='date' else '03_validation_timestamp.csv'),index=False)
    print(f'阶段 3 {policy} 口径的 SQL 与 pandas 对账、卡方与逻辑回归已完成。')

if __name__=='__main__':main()
