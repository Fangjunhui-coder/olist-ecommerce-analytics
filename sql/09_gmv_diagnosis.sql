-- Operating population includes delivered orders without a delivery timestamp.
create or replace temp view diagnosis_monthly as
with m as (
 select month, sum(gmv)::double gmv, count(*) orders,
 count(distinct customer_unique_id) buyers from order_facts group by month
), bounds as (select min(month) lo,max(month) hi from eligible_orders)
select cast(cal.month as date) as month,coalesce(m.gmv,0) gmv,coalesce(m.orders,0) orders,coalesce(m.buyers,0) buyers,lo,hi,
 m.orders::double/nullif(m.buyers,0) orders_per_buyer,m.gmv/nullif(m.orders,0) aov,
 cal.month>lo and cal.month<hi as interior_month
 from bounds cross join lateral generate_series(lo,hi,interval '1 month') cal(month) left join m on m.month=cal.month;
create or replace temp view diagnosis_dimensions as
with firsts as (select customer_unique_id,min(month) first_month from eligible_orders group by 1),
lines as (
 select i.*,case when i.month=f.first_month then 'new_observed' else 'returning_observed' end buyer_type
 from eligible_items i join firsts f using(customer_unique_id)
)
select month,'category' dimension,category segment,sum(price)::double gmv,count(*) units from lines group by all
union all
select month,'state',customer_state,sum(price)::double,count(*) from lines group by all
union all
select month,'buyer_type',buyer_type,sum(price)::double,count(*) from lines group by all;
