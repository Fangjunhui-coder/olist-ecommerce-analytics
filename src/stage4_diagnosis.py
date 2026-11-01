"""月度 GMV 诊断：SQL 聚合，LMDI、替代法与件数 mix/rate 分解。"""
import json
import duckdb
import numpy as np
import pandas as pd
from stage1 import ROOT,RAW,OUT,FIG,FILES
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def lmdi(old,new):
    old=np.asarray(old,dtype=float);new=np.asarray(new,dtype=float)
    if (old<=0).any() or (new<=0).any(): raise ValueError('LMDI requires positive factors')
    a=old.prod();b=new.prod()
    weight=a if np.isclose(a,b,rtol=1e-12) else (b-a)/np.log(b/a)
    return weight*np.log(new/old)


def substitution(old,new):
    x=np.array(old,dtype=float);result=[]
    for i,value in enumerate(new):
        before=x.prod();x[i]=value;result.append(x.prod()-before)
    return np.array(result)


def mix_rate(old,new):
    # GMV = total units * unit share * mean unit price; carry counterpart price
    # for entering/exiting groups so undefined prices do not invent a rate effect.
    x=old.set_index('segment')[['gmv','units']].join(new.set_index('segment')[['gmv','units']],how='outer',lsuffix='_0',rsuffix='_1').fillna(0)
    q0=x.units_0.sum();q1=x.units_1.sum()
    r0=(x.gmv_0/x.units_0.replace(0,np.nan));r1=(x.gmv_1/x.units_1.replace(0,np.nan))
    r0=r0.fillna(r1);r1=r1.fillna(r0)
    s0=x.units_0/q0;s1=x.units_1/q1
    x['volume_effect']=(q1-q0)*s0*r0
    x['mix_effect']=q1*(s1-s0)*r0
    x['rate_effect']=q1*s1*(r1-r0)
    x['change']=x.gmv_1-x.gmv_0
    x['residual']=x.change-x[['volume_effect','mix_effect','rate_effect']].sum(axis=1)
    x['contribution_share']=x.change/x.change.sum() if x.change.sum()!=0 else np.nan
    return x.reset_index()


def main():
    con=duckdb.connect()
    for name,file in FILES.items():con.execute(f"create view {name} as select * from read_csv_auto('{RAW/file}',all_varchar=true)")
    con.execute((ROOT/'sql/02_stage1_model.sql').read_text());con.execute((ROOT/'sql/09_gmv_diagnosis.sql').read_text())
    m=con.execute('select * from diagnosis_monthly order by month').df();m['month']=pd.to_datetime(m.month)
    # Sparse start-up months and right-censored final month excluded from examples.
    m['eligible']=m.interior_month & m.month.between('2017-01-01','2018-07-01')
    m['change']=m.gmv.diff();m['mom']=m.gmv.pct_change();m['consecutive']=m.month.diff().dt.days.between(28,31)
    m['anomaly']=m.eligible & m.eligible.shift(fill_value=False) & m.consecutive & m.mom.abs().ge(.20)
    m.to_csv(OUT/'04_monthly.csv',index=False)
    d=con.execute('select * from diagnosis_dimensions').df();d.to_csv(OUT/'04_dimension_monthly.csv',index=False)
    cases=pd.concat([m[m.anomaly & m.mom.gt(0)].nlargest(1,'change'),m[m.anomaly & m.mom.lt(0)].nsmallest(1,'change')])
    if len(cases)!=2:raise ValueError('Rule did not produce both rise and fall; inspect before changing policy')
    factors=[];drills=[]
    for row in cases.itertuples():
        j=m.index[m.month.eq(row.month)][0];p=m.iloc[j-1]
        old=p[['buyers','orders_per_buyer','aov']].to_numpy(float);new=np.array([row.buyers,row.orders_per_buyer,row.aov])
        lm=lmdi(old,new);su=substitution(old,new)
        for k,name in enumerate(['buyers','orders_per_buyer','aov']):factors.append(dict(month=row.month,baseline=p.month,factor=name,lmdi=lm[k],substitution=su[k],actual_change=row.gmv-p.gmv,lmdi_residual=row.gmv-p.gmv-lm.sum(),substitution_residual=row.gmv-p.gmv-su.sum()))
        for dim,part in d.groupby('dimension'):
            x=mix_rate(part[part.month.eq(p.month)],part[part.month.eq(row.month)]);x['month']=row.month;x['dimension']=dim;drills.append(x)
    f=pd.DataFrame(factors);f.to_csv(OUT/'04_factors.csv',index=False);pd.concat(drills).to_csv(OUT/'04_drilldown.csv',index=False)
    FIG.mkdir(exist_ok=True)
    fig,ax=plt.subplots(figsize=(11,4));ax.plot(m.month,m.gmv/1e6,'o-');a=m[m.anomaly];ax.scatter(a.month,a.gmv/1e6,color='red',label='|MoM| >= 20% (eligible)');ax.set(ylabel='GMV (BRL million)',title='Delivered GMV; red = rule-flagged interior months');ax.legend();fig.autofmt_xdate();fig.tight_layout();fig.savefig(FIG/'04_monthly_trend.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4))
    for ax,(month,g) in zip(axes,f.groupby('month')):
        start=0
        for i,r in enumerate(g.itertuples()):ax.bar(i,r.lmdi,bottom=start,color='#26858a' if r.lmdi>=0 else '#c56b4a');ax.text(i,start+r.lmdi/2,f'{r.lmdi:,.0f}',ha='center');start+=r.lmdi
        ax.bar(3,start,color='#44546a');ax.set_xticks(range(4),['Buyers','Orders/buyer','AOV','Total']);ax.set_title(str(month)[:7]);ax.set_ylabel('GMV change (BRL)');ax.axhline(0,color='gray');totals=np.r_[0,g.lmdi.cumsum().to_numpy()];span=max(totals.max()-totals.min(),1);ax.set_ylim(totals.min()-.12*span,totals.max()+.12*span)
    fig.tight_layout();fig.savefig(FIG/'04_waterfall.png',dpi=160);plt.close(fig)
    print(f.to_string(index=False))

if __name__=='__main__':main()
