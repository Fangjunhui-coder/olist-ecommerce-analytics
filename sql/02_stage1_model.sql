-- 订单先按 ID 关联客户，再与商品明细关联，避免把订单金额与支付分期相乘。
create or replace temp view eligible_orders as
select o.order_id, o.customer_id, c.customer_unique_id, c.customer_state,
       cast(o.order_purchase_timestamp as timestamp) as purchased_at,
       cast(date_trunc('month', cast(o.order_purchase_timestamp as timestamp)) as date) as month
from orders o join customers c on o.customer_id = c.customer_id
where o.order_status = 'delivered' and nullif(trim(o.order_id),'') is not null
  and try_cast(o.order_purchase_timestamp as timestamp) is not null;

-- 每个明细只关联一个品类；未翻译保留葡语名，原名缺失则归未知。
create or replace temp view eligible_items as
select e.order_id, e.customer_unique_id, e.customer_state, e.month,
       i.order_item_id, cast(i.price as decimal(18,2)) as price,
       case when nullif(trim(p.product_category_name), '') is null then 'unknown'
            when nullif(trim(t.product_category_name_english), '') is null then 'untranslated'
            else 'translated' end as category_status,
       case when nullif(trim(p.product_category_name), '') is null then 'Unknown category'
            when nullif(trim(t.product_category_name_english), '') is null then p.product_category_name
            else t.product_category_name_english end as category
from eligible_orders e join order_items i on e.order_id = i.order_id
left join products p on i.product_id = p.product_id
left join translation t on p.product_category_name = t.product_category_name;

-- 聚合到订单粒度后再计算客单价、复购，防止多商品订单重复计数。
create or replace temp view order_facts as
select e.order_id, e.customer_unique_id, e.customer_state, e.month,
       sum(i.price) as gmv, count(*) as item_count
from eligible_orders e join eligible_items i on e.order_id = i.order_id
group by e.order_id, e.customer_unique_id, e.customer_state, e.month;
