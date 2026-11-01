-- Primary seller uses highest-price item; ties use item number.
create or replace temp table seller_history_orders as
with primary_seller as (
 select order_id,seller_id from order_items
 qualify row_number() over(partition by order_id order by cast(price as decimal(18,2)) desc,cast(order_item_id as integer))=1
)
select p.*,try_cast(o.order_purchase_timestamp as timestamp) purchased_at,
 d.delivered_at,d.delayed
from primary_seller p join orders o using(order_id)
left join delivery_orders d using(order_id);

-- Build seller timelines once. ASOF uses a strict inequality so events at the
-- same timestamp as the current purchase are excluded, including purchase ties.
create or replace temp table seller_history_timeline as
with events as (
 select seller_id,purchased_at event_at,1 orders,0 completed,0 late
 from seller_history_orders where purchased_at is not null
 union all
 select seller_id,delivered_at,0,1,delayed from seller_history_orders where delivered_at is not null
), grouped as (
 select seller_id,event_at,sum(orders) orders,sum(completed) completed,sum(late) late
 from events group by all
)
select seller_id,event_at,
 sum(orders) over w seller_prior_orders,
 sum(completed) over w seller_completed_orders,
 sum(late) over w seller_prior_late
from grouped window w as (partition by seller_id order by event_at rows unbounded preceding);

create or replace temp table causal_orders as
with base as (
 select a.*,p.seller_id,strftime(a.purchased_at,'%Y-%m') purchase_month,
 date_diff('day',cast(a.purchased_at as date),cast(a.estimated_at as date)) expected_days
 from analysis_orders a join seller_history_orders p using(order_id)
 where review_answer_at>=a.delivered_at
), counts as (
 select a.*,coalesce(h.seller_prior_orders,0) seller_prior_orders,
 coalesce(h.seller_completed_orders,0) seller_completed_orders,
 coalesce(h.seller_prior_late,0) seller_prior_late
 from base a asof left join seller_history_timeline h
 on a.seller_id=h.seller_id and a.purchased_at>h.event_at
)
select *,coalesce(seller_prior_late::double/nullif(seller_completed_orders,0),0) seller_history_delay_rate,
 (seller_prior_orders=0)::integer seller_no_history,
 (seller_completed_orders=0)::integer seller_no_completed_history from counts;
