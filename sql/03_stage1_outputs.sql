-- 月度复购以当月用户为分母；先按用户汇总，再按月份汇总。
create or replace temp view month_users as
select month, customer_unique_id, count(*) as user_orders from order_facts group by month, customer_unique_id;
create or replace temp view monthly as
with bounds as (select min(month) as first_month, max(month) as last_month from order_facts),
calendar as (select cast(m as date) as month from bounds, generate_series(first_month,last_month,interval '1 month') s(m)),
metrics as (select month, sum(gmv) as gmv, count(*) as orders, sum(item_count) as items from order_facts group by month),
users as (select month, count(*) as buyers, count(*) filter (where user_orders >= 2) as repeat_buyers from month_users group by month),
base as (select c.month, coalesce(m.gmv,0) as gmv, coalesce(m.orders,0) as orders, coalesce(m.items,0) as items,
                coalesce(u.buyers,0) as buyers, coalesce(u.repeat_buyers,0) as repeat_buyers
         from calendar c left join metrics m using(month) left join users u using(month)),
lagged as (select *, lag(gmv) over(order by month) as previous_gmv, lag(orders) over(order by month) as previous_orders,
 lag(buyers) over(order by month) as previous_buyers,
 lag(gmv / nullif(orders,0)) over(order by month) as previous_aov,
 lag(gmv / nullif(items,0)) over(order by month) as previous_item_price,
 lag(repeat_buyers::double / nullif(buyers,0)) over(order by month) as previous_repeat_rate from base)
select month, gmv, orders, buyers, items, repeat_buyers,
       gmv / nullif(orders,0) as average_order_value, gmv / nullif(items,0) as average_item_price,
       repeat_buyers::double / nullif(buyers,0) as repeat_rate,
       (gmv-previous_gmv) / nullif(previous_gmv,0) as gmv_mom,
       (orders-previous_orders)::double / nullif(previous_orders,0) as orders_mom,
       (buyers-previous_buyers)::double / nullif(previous_buyers,0) as buyers_mom,
       (gmv/nullif(orders,0)-previous_aov)/nullif(previous_aov,0) as average_order_value_mom,
       (gmv/nullif(items,0)-previous_item_price)/nullif(previous_item_price,0) as average_item_price_mom,
       (repeat_buyers::double/nullif(buyers,0)-previous_repeat_rate)/nullif(previous_repeat_rate,0) as repeat_rate_mom,
       100 * (repeat_buyers::double/nullif(buyers,0)-previous_repeat_rate) as repeat_rate_pp_change
from lagged;

create or replace temp view overall as
with u as (select customer_unique_id, count(*) as n from order_facts group by customer_unique_id),
m as (select sum(gmv) as gmv, count(*) as orders, sum(item_count) as items from order_facts),
b as (select count(*) as buyers, count(*) filter(where n>=2) as repeat_buyers from u)
select m.*, b.*, gmv/nullif(orders,0) as average_order_value, gmv/nullif(items,0) as average_item_price,
       repeat_buyers::double/nullif(buyers,0) as repeat_rate from m cross join b;

create or replace temp view category_summary as
with base as (select category_status, category, sum(price) as gmv, count(*) as items,
                     count(distinct order_id) as orders, count(distinct customer_unique_id) as buyers
              from eligible_items group by category_status,category),
 ranked as (select *, row_number() over(order by gmv desc,category_status,category) as gmv_rank,
             sum(gmv) over(order by gmv desc,category_status,category rows unbounded preceding) as cumulative_gmv,
             sum(gmv) over() as total_gmv from base)
select *, gmv/total_gmv as gmv_share, cumulative_gmv/total_gmv as cumulative_share,
       (cumulative_gmv-gmv)/total_gmv < 0.8 as in_top_80pct,
       gmv/nullif(orders,0) as average_order_value, gmv/nullif(items,0) as average_item_price
from ranked;

create or replace temp view category_status_summary as
select category_status, count(*) as items, sum(price) as gmv,
       sum(price)/(select sum(price) from eligible_items) as gmv_share
from eligible_items group by category_status;

create or replace temp view state_summary as
select coalesce(nullif(trim(customer_state),''),'Unknown') as state, sum(gmv) as gmv,
       count(*) as orders, count(distinct customer_unique_id) as buyers, sum(item_count) as items,
       sum(gmv)/nullif(count(*),0) as average_order_value, sum(gmv)/nullif(sum(item_count),0) as average_item_price,
       sum(gmv)/(select sum(gmv) from order_facts) as gmv_share
from order_facts group by 1;

create or replace temp view monthly_category as
select month, category_status, category, sum(price) as gmv, count(*) as items,
       count(distinct order_id) as orders, count(distinct customer_unique_id) as buyers,
       sum(price)/nullif(count(distinct order_id),0) as average_order_value,
       sum(price)/nullif(count(*),0) as average_item_price
from eligible_items group by month,category_status,category;

create or replace temp view monthly_state as
select month, coalesce(nullif(trim(customer_state),''),'Unknown') as state, sum(gmv) as gmv,
       count(*) as orders, count(distinct customer_unique_id) as buyers, sum(item_count) as items,
       sum(gmv)/nullif(count(*),0) as average_order_value, sum(gmv)/nullif(sum(item_count),0) as average_item_price
from order_facts group by 1,2;
