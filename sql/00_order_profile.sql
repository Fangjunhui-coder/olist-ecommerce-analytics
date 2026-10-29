-- 保留所有状态，先查看全量订单与时间范围，避免将交付订单误认为全体订单。
select order_status, count(*) as order_rows
from orders
group by order_status
order by order_rows desc;

select min(try_cast(order_purchase_timestamp as timestamp)) as first_purchase,
       max(try_cast(order_purchase_timestamp as timestamp)) as last_purchase
from orders;
