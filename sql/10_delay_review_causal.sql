-- Highest-price item seller defines primary seller; ties use item number.
create or replace temp table causal_orders as
with primary_seller as (
 select order_id,seller_id from order_items
 qualify row_number() over(partition by order_id order by cast(price as decimal(18,2)) desc,cast(order_item_id as integer))=1
)
select a.*,p.seller_id,strftime(purchased_at,'%Y-%m') purchase_month,
 date_diff('day',cast(purchased_at as date),cast(estimated_at as date)) expected_days
from analysis_orders a join primary_seller p using(order_id)
where review_answer_at>=delivered_at;
