-- 检查已送达订单的明细与评价覆盖，避免静默丢单。
select 'delivered_without_items' as check_name, count(*) as value from orders o where order_status='delivered' and not exists(select 1 from order_items i where i.order_id=o.order_id)
union all select 'delivered_without_review', count(*) from orders o where order_status='delivered' and not exists(select 1 from order_reviews v where v.order_id=o.order_id)
union all select 'delivered_missing_unique_id', count(*) from orders o join customers c using (customer_id) where order_status='delivered' and (customer_unique_id is null or trim(customer_unique_id)='')
union all select 'delivered_items_unknown_category', count(*) from order_items i join orders o using(order_id) left join products p using(product_id) left join translation t on p.product_category_name=t.product_category_name where o.order_status='delivered' and t.product_category_name is null
union all select 'delivered_orders_multi_review', count(*) from (select o.order_id from orders o join order_reviews v using(order_id) where o.order_status='delivered' group by o.order_id having count(*)>1)
union all select 'invalid_review_score', count(*) from order_reviews where try_cast(review_score as integer) is null or try_cast(review_score as integer) not between 1 and 5;
