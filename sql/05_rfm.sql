-- 参照日来自全量订单的最后下单日的次日，和经营样本的筛选保持区分。
create or replace temp table rfm_user_base as
with ref as (select cast(max(try_cast(order_purchase_timestamp as timestamp)) as date)+1 as reference_date from orders)
select f.customer_unique_id, ref.reference_date,
       date_diff('day',cast(max(e.purchased_at) as date),ref.reference_date) as recency_days,
       count(*) as frequency, sum(f.gmv) as monetary
from order_facts f join eligible_orders e on f.order_id=e.order_id cross join ref
group by f.customer_unique_id, ref.reference_date;

-- 分位点采用连续线性插值；相同数值放同一档，档位人数不强求相等。
create or replace temp view rfm_cutoffs as
select min(reference_date) as reference_date,
       quantile_cont(recency_days,1.0/3) as r_q1, quantile_cont(recency_days,2.0/3) as r_q2,
       quantile_cont(monetary,1.0/3) as m_q1, quantile_cont(monetary,2.0/3) as m_q2,
       count(*) as buyers from rfm_user_base;

create or replace temp view rfm_users as
select b.*, case when b.recency_days<=c.r_q1 then 'recent' when b.recency_days<=c.r_q2 then 'middle' else 'dormant' end as r_band,
       case when b.frequency=1 then 'one' else 'repeat' end as f_band,
       case when b.monetary<=c.m_q1 then 'low' when b.monetary<=c.m_q2 then 'middle' else 'high' end as m_band
from rfm_user_base b cross join rfm_cutoffs c;

create or replace temp view rfm_frequency as
select frequency, count(*) as buyers, count(*)::double/(select count(*) from rfm_users) as buyer_share
from rfm_users group by frequency order by frequency;

create or replace temp view rfm_segments as
select r_band,f_band,m_band,count(*) as buyers,
       count(*)::double/(select count(*) from rfm_users) as buyer_share,
       sum(monetary) as gmv, sum(monetary)/(select sum(monetary) from rfm_users) as gmv_share,
       avg(recency_days) as mean_r_days,avg(frequency) as mean_f_orders,avg(monetary) as mean_m_brl,
       sum(monetary)/nullif(sum(frequency),0) as average_order_value
from rfm_users group by 1,2,3;
