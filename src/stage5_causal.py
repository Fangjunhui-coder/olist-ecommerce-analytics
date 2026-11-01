"""Post-delivery review cohort: stratification, PSM and seller-within LPM."""
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from scipy.sparse import hstack
import statsmodels.api as sm
from stage1 import ROOT,OUT,FIG
from stage3 import load_sql,fit_model
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def smd(treated,control,scale=None):
    treated=np.asarray(treated,float);control=np.asarray(control,float)
    den=np.sqrt((treated.var(axis=0,ddof=1)+control.var(axis=0,ddof=1))/2) if scale is None else np.asarray(scale)
    diff=treated.mean(axis=0)-control.mean(axis=0)
    return np.divide(diff,den,out=np.where(abs(diff)<1e-12,0.,np.inf),where=den>0)


def match(logits,treatment,caliper):
    # Greedy nearest neighbour, no replacement, hardest/highest PS treated first.
    controls=np.flatnonzero(treatment==0);available=np.ones(len(controls),bool);pairs=[]
    low=max(logits[treatment==0].min(),logits[treatment==1].min());high=min(logits[treatment==0].max(),logits[treatment==1].max())
    for t in np.flatnonzero(treatment==1)[np.argsort(-logits[treatment==1],kind='stable')]:
        if not low<=logits[t]<=high:continue
        dist=np.where(available & (logits[controls]>=low) & (logits[controls]<=high),abs(logits[controls]-logits[t]),np.inf)
        j=dist.argmin()
        if dist[j]<=caliper:pairs.append((t,int(controls[j])));available[j]=False
    return np.array(pairs,dtype=int).reshape(-1,2),(low,high)


def main():
    con=load_sql('date');con.execute((ROOT/'sql/10_delay_review_causal.sql').read_text());d=con.execute('select * from causal_orders order by order_id').df()
    fig,ax=plt.subplots(figsize=(12,5));ax.set_axis_off()
    nodes={'C':(.15,.75),'D':(.45,.75),'M':(.7,.75),'Y':(.9,.4),'U':(.45,.15),'S':(.7,.15)}
    labels={'C':'Baseline: category, seller, state,\nmonth, amount, freight, promise','D':'Delay','M':'Dissatisfaction / service response','Y':'Bad review','U':'Unobserved quality / expectations','S':'Review observed after delivery'}
    for key,(x0,y0) in nodes.items():ax.text(x0,y0,labels[key],ha='center',va='center',fontsize=9,zorder=3,bbox=dict(boxstyle='round',facecolor='#eef4f7'))
    for a,b in [('C','D'),('C','Y'),('D','M'),('M','Y'),('D','Y'),('U','D'),('U','Y'),('D','S'),('U','S')]:
        ax.annotate('',xy=nodes[b],xytext=nodes[a],zorder=1,arrowprops=dict(arrowstyle='->',alpha=.45,shrinkA=25,shrinkB=25))
    ax.set_title('Assumed DAG: conditioning on S may induce selection bias')
    fig.tight_layout();fig.savefig(FIG/'05_dag.png',dpi=160);plt.close(fig)
    comparisons=[]
    for name,frame in [('raw_all_reviews',con.execute('select * from analysis_orders').df()),('raw_after_delivery',d)]:
        means=frame.groupby('delayed').bad_review.mean();comparisons.append(dict(method=name,estimand='risk_difference',estimate=means[1]-means[0],n=len(frame)))
    strata=[]
    for dim in ['category','customer_state']:
        for key,g in d.groupby(dim):
            if g.delayed.nunique()!=2:continue
            t=g[g.delayed.eq(1)];c=g[g.delayed.eq(0)];strata.append(dict(dimension=dim,segment=key,treated=len(t),controls=len(c),treated_rate=t.bad_review.mean(),control_rate=c.bad_review.mean(),difference=t.bad_review.mean()-c.bad_review.mean()))
        tab=pd.DataFrame([x for x in strata if x['dimension']==dim]);comparisons.append(dict(method='stratified_'+dim,estimand='treated_weighted_risk_difference',estimate=np.average(tab.difference,weights=tab.treated),n=int(tab.treated.sum()+tab.controls.sum())))
    pd.DataFrame(strata).to_csv(OUT/'05_strata.csv',index=False)
    dose=d.groupby('delay_band').agg(n=('order_id','size'),bad=('bad_review','sum'),rate=('bad_review','mean')).reset_index();dose.to_csv(OUT/'05_dose_response.csv',index=False)
    # Baseline covariates only; actual transit duration is not controlled.
    num=pd.DataFrame({'log_gmv':np.log1p(d.product_gmv.astype(float)),'log_freight':np.log1p(d.freight.astype(float)),'items':d['items'].astype(float),'cross_state':d.cross_state.astype(float),'expected_days':d.expected_days.astype(float)})
    ps_num=num.assign(log_seller_prior_orders=np.log1p(d.seller_prior_orders),
        seller_history_delay_rate=d.seller_history_delay_rate,
        seller_no_history=d.seller_no_history,seller_no_completed_history=d.seller_no_completed_history)
    cats=d[['category','customer_state','purchase_month']].astype(str).copy()
    levels=[]
    for column in ['category','customer_state']:
        counts=d[d.delayed.eq(1)][column].value_counts()
        for level in sorted(d[column].unique()):
            levels.append(dict(dimension=column,level=level,treated_orders=int(counts.get(level,0)),pooled=counts.get(level,0)<20))
        cats[column]=cats[column].where(cats[column].map(counts).fillna(0)>=20,'[other]')
    pd.DataFrame(levels).to_csv(OUT/'05_level_pooling.csv',index=False)
    history_cols=['order_id','seller_id','seller_prior_orders','seller_completed_orders','seller_prior_late','seller_history_delay_rate','seller_no_history','seller_no_completed_history']
    d[history_cols].to_csv(OUT/'05_seller_history.csv',index=False)
    enc=OneHotEncoder(handle_unknown='ignore',sparse_output=True);dummy=enc.fit_transform(cats)
    x=hstack([StandardScaler().fit_transform(ps_num),dummy]).tocsr();t=d.delayed.to_numpy(int)
    ps=LogisticRegression(C=1,solver='lbfgs',max_iter=1000,tol=1e-7).fit(x,t)
    if ps.n_iter_.max()>=1000:raise RuntimeError('PS model did not converge')
    lp=ps.decision_function(x);caliper=.2*lp.std(ddof=1);pairs,support=match(lp,t,caliper)
    if len(pairs)==0:raise ValueError('No matches')
    balance_x=hstack([ps_num.to_numpy(),dummy]).toarray();names=list(ps_num)+list(enc.get_feature_names_out())
    scale=np.sqrt((balance_x[t==1].var(axis=0,ddof=1)+balance_x[t==0].var(axis=0,ddof=1))/2)
    before=smd(balance_x[t==1],balance_x[t==0],scale);after=smd(balance_x[pairs[:,0]],balance_x[pairs[:,1]],scale)
    balance=pd.DataFrame({'covariate':names,'smd_before':before,'smd_after':after});balance['balanced']=balance.smd_after.abs()<.1;balance.to_csv(OUT/'05_balance.csv',index=False)
    pair=pd.DataFrame({'treated_id':d.order_id.iloc[pairs[:,0]].to_numpy(),'control_id':d.order_id.iloc[pairs[:,1]].to_numpy(),'treated_logit':lp[pairs[:,0]],'control_logit':lp[pairs[:,1]],'treated_bad':d.bad_review.iloc[pairs[:,0]].to_numpy(),'control_bad':d.bad_review.iloc[pairs[:,1]].to_numpy()});pair.to_csv(OUT/'05_matches.csv',index=False)
    diff=(pair.treated_bad-pair.control_bad).to_numpy(float);rng=np.random.default_rng(20261101);boot=np.array([rng.choice(diff,len(diff),replace=True).mean() for _ in range(1000)]);lo,hi=np.quantile(boot,[.025,.975]);comparisons.append(dict(method='PSM_matched_ATT',estimand='matched_treated_risk_difference',estimate=diff.mean(),ci_low=lo,ci_high=hi,n=2*len(pair)))
    legacy=pd.read_csv(OUT/'05_legacy_method_comparison.csv');old=legacy[legacy.method.eq('PSM_matched_ATT')].iloc[0].to_dict();old['method']='PSM_legacy_seller_onehot_unbalanced';comparisons.append(old)
    # Seller fixed effects LPM via within transformation. Cluster SE by seller.
    small=pd.get_dummies(d[['category','customer_state','purchase_month']].astype(str),drop_first=True,dtype=float)
    design=pd.concat([d[['delayed']].astype(float),num,small],axis=1)
    within=design-design.groupby(d.seller_id).transform('mean');y=d.bad_review-d.bad_review.groupby(d.seller_id).transform('mean')
    within=within.loc[:,within.var()>1e-12]
    fe=sm.OLS(y,within).fit(cov_type='cluster',cov_kwds={'groups':d.seller_id});ci=fe.conf_int().loc['delayed'];comparisons.append(dict(method='seller_FE_LPM',estimand='within_seller_adjusted_risk_difference',estimate=fe.params['delayed'],ci_low=ci.iloc[0],ci_high=ci.iloc[1],n=len(d)))
    full=con.execute('select * from analysis_orders').df()
    for frame,label in [(full,'logistic_all_reviews'),(d,'logistic_after_delivery')]:
        model,model_meta,_=fit_model(frame,full)
        r=model[model.term.eq('delayed')].iloc[0]
        comparisons.append(dict(method=label,estimand='adjusted_odds_ratio_stage3',estimate=r.odds_ratio,ci_low=r.ci_lower,ci_high=r.ci_upper,n=len(frame)))
    pd.DataFrame(comparisons).to_csv(OUT/'05_method_comparison.csv',index=False)
    meta=dict(sample_n=len(d),treated=int(t.sum()),pairs=len(pair),retained_treated_fraction=len(pair)/int(t.sum()),caliper_logit=caliper,support_logit=list(support),max_abs_smd_before=float(abs(before).max()),max_abs_smd_after=float(abs(after).max()),unbalanced_after=int((abs(after)>=.1).sum()),covariates=len(names),bootstrap='1000 fixed-pair resamples, seed 20261101; conditional descriptive CI, not full matching uncertainty',ps_iterations=int(ps.n_iter_.max()),seller_features='strict purchase-before and delivery-before current purchase; zero rate with missing-history indicators',rare_level_min_treated=20,exact_category_matching=False,unbalanced_columns=balance.loc[~balance.balanced,'covariate'].tolist())
    (OUT/'05_metadata.json').write_text(json.dumps(meta,indent=2))
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for treatment,label in [(0,'On time'),(1,'Delayed')]:
        axes[0].hist(lp[t==treatment],bins=40,density=True,alpha=.5,label=label)
        axes[1].hist(lp[pairs[:,1-treatment]],bins=40,density=True,alpha=.5,label=label)
    for ax in axes:ax.axvline(support[0],ls='--',color='gray');ax.axvline(support[1],ls='--',color='gray');ax.set_xlabel('Logit propensity');ax.legend()
    axes[0].set_title('Before matching');axes[1].set_title('Matched');fig.tight_layout();fig.savefig(FIG/'05_common_support.png',dpi=160);plt.close(fig)
    show=balance.assign(size=balance.smd_before.abs()).nlargest(25,'size');fig,ax=plt.subplots(figsize=(9,7));ax.scatter(show.smd_before.abs(),range(len(show)),label='Before');ax.scatter(show.smd_after.abs(),range(len(show)),label='After');ax.axvline(.1,ls='--',color='gray');ax.set_yticks(range(len(show)),show.covariate);ax.legend();ax.set_xlabel('|SMD|, fixed pre-match SD');fig.tight_layout();fig.savefig(FIG/'05_balance.png',dpi=160);plt.close(fig)
    print(json.dumps(meta));print(pd.DataFrame(comparisons).to_string(index=False))

if __name__=='__main__':main()
