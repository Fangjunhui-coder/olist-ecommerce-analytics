-- 商品 GMV 不含运费；补充运费与两者之和，避免误当成实收。
create or replace temp view supplementary_amounts as
select sum(e.price) as product_gmv,
       sum(cast(i.freight_value as decimal(18,2))) as freight_total,
       sum(e.price) + sum(cast(i.freight_value as decimal(18,2))) as gmv_with_freight
from eligible_items e join order_items i using (order_id, order_item_id);

create or replace temp table cached_orders as select * from eligible_orders;

-- 数据截止为全部订单的最晚下单时间。只有首单日期距截止日期至少 90 个自然日的用户进入分母。
-- 首单后严格大于首单时间、且日期不晚于首单日后第 90 天的已送达订单构成复购。
create or replace temp view repeat_90 as
with cutoff as (select max(try_cast(order_purchase_timestamp as timestamp)) as data_cutoff from orders),
first_order as (select customer_unique_id, min(purchased_at) as first_at from cached_orders group by customer_unique_id),
eligible as (select f.* from first_order f cross join cutoff c where cast(f.first_at as date) + 90 <= cast(c.data_cutoff as date)),
flags as (select e.customer_unique_id, count(o.order_id) filter (where o.purchased_at>e.first_at and cast(o.purchased_at as date)<=cast(e.first_at as date)+90) > 0 as repeated from eligible e left join cached_orders o on o.customer_unique_id=e.customer_unique_id group by e.customer_unique_id)
select (select data_cutoff from cutoff) as data_cutoff,
       (select count(*) from first_order) as total_buyers,
       count(*) as eligible_buyers, count(*) filter(where repeated) as repeat_buyers_90d,
       count(*) filter(where repeated)::double / nullif(count(*),0) as repeat_rate_90d
from flags;

-- 日历补齐 2017 年 11 月的每一天；当天无符合口径订单则记为 0。
create or replace temp view daily_2017_11 as
with calendar as (select cast(d as date) as day from generate_series(date '2017-11-01',date '2017-11-30', interval '1 day') t(d)),
counts as (select cast(purchased_at as date) as day, count(*) as orders from cached_orders where purchased_at >= timestamp '2017-11-01' and purchased_at < timestamp '2017-12-01' group by 1)
select c.day, coalesce(n.orders,0) as orders from calendar c left join counts n using(day) order by day;

-- 补充敏感性检查：以最后一笔已送达订单的下单时间为截点，不能据此证明之前的覆盖完整。
create or replace temp view repeat_90_sensitivity as
with cutoff as (select max(purchased_at) as data_cutoff from cached_orders),
first_order as (select customer_unique_id,min(purchased_at) as first_at from cached_orders group by 1),
eligible as (select f.* from first_order f cross join cutoff c where cast(f.first_at as date)+90<=cast(c.data_cutoff as date)),
flags as (select e.customer_unique_id,count(o.order_id) filter(where o.purchased_at>e.first_at and cast(o.purchased_at as date)<=cast(e.first_at as date)+90)>0 as repeated from eligible e left join cached_orders o on o.customer_unique_id=e.customer_unique_id group by e.customer_unique_id)
select (select data_cutoff from cutoff) as data_cutoff,count(*) as eligible_buyers,
       count(*) filter(where repeated) as repeat_buyers_90d,
       count(*) filter(where repeated)::double/nullif(count(*),0) as repeat_rate_90d from flags;

-- 标记按全量订单截止时点纳入、但 90 天窗口晚于最后已送达订单的买家数量。
create or replace temp view repeat_90_coverage as
with cutoff as (select max(try_cast(order_purchase_timestamp as timestamp)) as data_cutoff from orders),
last_delivered as (select max(purchased_at) as last_at from cached_orders),
f as (select customer_unique_id,min(purchased_at) as first_at from cached_orders group by 1)
select count(*) filter(where cast(f.first_at as date)+90<=cast(c.data_cutoff as date)) as eligible_buyers,
       count(*) filter(where cast(f.first_at as date)+90<=cast(c.data_cutoff as date) and cast(f.first_at as date)+90>cast(d.last_at as date)) as windows_after_last_delivered,
       min(d.last_at) as last_delivered_order_at
from f cross join cutoff c cross join last_delivered d;
