-- 配送分析排除关键时间无效、送达早于下单的已送达订单。
create or replace temp table delivery_orders as
with base as (
 select e.order_id,e.customer_unique_id,e.customer_state,e.purchased_at,
        try_cast(o.order_delivered_customer_date as timestamp) as delivered_at,
        try_cast(o.order_estimated_delivery_date as timestamp) as estimated_at
 from eligible_orders e join orders o using(order_id))
select *, case when cast(delivered_at as date)>cast(estimated_at as date) then 1 else 0 end as delayed,
       greatest(date_diff('day',cast(estimated_at as date),cast(delivered_at as date)),0)*86400 as late_seconds
from base where delivered_at is not null and estimated_at is not null and delivered_at>=purchased_at;

-- 按评价回复时间由新到旧排序，review_id 用于稳定排序。
create or replace temp table selected_reviews as
select order_id,try_cast(review_score as integer) as review_score,
       try_cast(review_answer_timestamp as timestamp) as review_answer_at,
       try_cast(review_creation_date as timestamp) as review_created_at
from order_reviews
qualify row_number() over(partition by order_id order by try_cast(review_answer_timestamp as timestamp) desc nulls last,review_id desc)=1;

-- 价格最高的商品作为订单主品类；同价按明细序号升序。
create or replace temp table item_features as
with items as (
 select d.order_id,cast(i.order_item_id as integer) as item_id,
        cast(i.price as decimal(18,2)) as price,cast(i.freight_value as decimal(18,2)) as freight,
        s.seller_state,d.customer_state,
        case when nullif(trim(p.product_category_name),'') is null then '[unknown]'
             when nullif(trim(t.product_category_name_english),'') is null then '[untranslated] '||p.product_category_name
             else t.product_category_name_english end as category
 from delivery_orders d join order_items i using(order_id) join sellers s using(seller_id)
 join products p using(product_id) left join translation t on p.product_category_name=t.product_category_name),
numbered as (select *,row_number() over(partition by order_id order by price desc,item_id asc) as position from items)
select order_id,sum(price) as product_gmv,sum(freight) as freight,count(*) as items,
       max(case when seller_state<>customer_state then 1 else 0 end) as cross_state,
       max(category) filter(where position=1) as category
from numbered group by order_id;

create or replace temp table analysis_orders as
select d.*,s.review_score,s.review_answer_at,s.review_created_at,
       case when s.review_score<=2 then 1 else 0 end as bad_review,
       case when d.delayed=0 then 'on_time' when d.late_seconds<=3*86400 then '1_to_3_days'
            when d.late_seconds<=7*86400 then '4_to_7_days' else 'over_7_days' end as delay_band,
       f.product_gmv,f.freight,f.items,f.cross_state,f.category
from delivery_orders d join selected_reviews s using(order_id) join item_features f using(order_id);

create or replace temp view delay_comparison as
select delayed,count(*) as orders,sum(bad_review) as bad_reviews,avg(bad_review) as bad_rate,avg(review_score) as mean_score
from analysis_orders group by delayed;

create or replace temp view delay_bands as
select delay_band,count(*) as orders,sum(bad_review) as bad_reviews,avg(bad_review) as bad_rate,avg(review_score) as mean_score
from analysis_orders group by delay_band;

-- 州和卖家延迟率使用时间有效的已送达订单，不要求有评价。
create or replace temp view delivery_state as
select customer_state as state,count(*) as orders,sum(delayed) as delayed_orders,avg(delayed) as delay_rate
from delivery_orders group by state having count(*)>=30;
create or replace temp view delivery_seller as
with seller_order as (select distinct d.order_id,d.delayed,i.seller_id from delivery_orders d join order_items i using(order_id))
select seller_id,count(*) as orders,sum(delayed) as delayed_orders,avg(delayed) as delay_rate
from seller_order group by seller_id having count(*)>=30;

-- 当评分早于实际送达时，最终延迟在评分发生时尚未知，单独检查时间顺序。
create or replace temp view review_timing as
select case when review_answer_at>=delivered_at then 'after_or_at_delivery'
            when cast(review_answer_at as date)<=cast(estimated_at as date) then 'before_estimate_and_delivery'
            else 'after_estimate_before_delivery' end as review_timing,
       delayed,count(*) as orders,sum(bad_review) as bad_reviews,avg(bad_review) as bad_rate
from analysis_orders group by 1,2;
