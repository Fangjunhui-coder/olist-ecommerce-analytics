-- 在已送达订单上独立检查多评价记录、最新时间并列与评分差异。
create or replace temp view review_audit_sql as
with r as (
 select v.order_id,v.review_id,try_cast(v.review_score as integer) as score,
        try_cast(v.review_answer_timestamp as timestamp) as answer,
        try_cast(v.review_creation_date as timestamp) as created
 from order_reviews v join eligible_orders e using(order_id)),
multi_ids as (select order_id,count(*) as n,count(distinct score) as distinct_scores from r group by 1 having count(*)>1),
multi_rows as (select r.*,m.n,m.distinct_scores,max(answer) over(partition by r.order_id) as max_answer,
 max(created) over(partition by r.order_id) as max_created from r join multi_ids m using(order_id)),
top_answer as (select order_id,count(*) as n,count(distinct score) as scores from multi_rows where answer=max_answer group by 1),
top_created as (select order_id,count(*) as n,count(distinct score) as scores from multi_rows where created=max_created group by 1),
first_last as (select distinct order_id,
 first_value(score) over(partition by order_id order by answer asc,review_id asc) as earliest_score,
 first_value(score) over(partition by order_id order by answer desc,review_id desc) as latest_score from multi_rows)
select (select count(*) from eligible_orders) as delivered_orders,
 (select count(*) from eligible_orders e where not exists(select 1 from r where r.order_id=e.order_id)) as no_review_orders,
 (select count(*) from multi_ids) as multi_review_orders,
 (select count(*) from multi_rows) as multi_review_rows,
 (select count(*) from multi_ids where n=2) as multi_with_2,
 (select count(*) from multi_ids where n=3) as multi_with_3,
 (select count(*) from multi_ids where n>=4) as multi_with_4plus,
 (select count(*) from multi_ids where distinct_scores>1) as multi_different_scores,
 (select count(*) from multi_rows where answer is null) as multi_answer_missing_rows,
 (select count(*) from multi_rows where created is null) as multi_creation_missing_rows,
 (select count(*) from top_answer where n>1) as answer_latest_ties,
 (select count(*) from top_answer where scores>1) as answer_latest_ties_different_scores,
 (select count(*) from top_created where n>1) as created_latest_ties,
 (select count(*) from top_created where scores>1) as created_latest_ties_different_scores,
 (select count(*) from first_last where earliest_score<>latest_score) as multi_latest_vs_earliest_score_diff,
 (select count(*) from first_last where (earliest_score<=2)<>(latest_score<=2)) as multi_latest_vs_earliest_bad_flag_diff;
