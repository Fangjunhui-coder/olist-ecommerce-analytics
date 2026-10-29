-- 依次匹配互斥规则：先区分复购用户，再按近期与金额分开单次用户。
create or replace temp view operating_users as
select *, case
 when f_band='repeat' and m_band='high' then 'high_value_repeat'
 when f_band='repeat' then 'other_repeat'
 when r_band='recent' and m_band='high' then 'recent_high_one'
 when r_band='recent' then 'recent_other_one'
 when m_band='high' then 'less_recent_high_one'
 else 'less_recent_other_one' end as operating_group
from rfm_users;
create or replace temp view operating_summary as
select operating_group,count(*) as buyers,
 count(*)::double/(select count(*) from operating_users) as buyer_share,
 sum(monetary) as gmv, sum(monetary)/(select sum(monetary) from operating_users) as gmv_share,
 avg(recency_days) as mean_r_days,avg(frequency) as mean_f_orders,avg(monetary) as mean_m_brl
from operating_users group by operating_group;
