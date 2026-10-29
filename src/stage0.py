"""阶段 0：原始数据画像、关系检查和保守清洗。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'results' / 'tables'
FILES = {
    'orders': 'olist_orders_dataset.csv', 'order_items': 'olist_order_items_dataset.csv',
    'order_payments': 'olist_order_payments_dataset.csv', 'order_reviews': 'olist_order_reviews_dataset.csv',
    'customers': 'olist_customers_dataset.csv', 'products': 'olist_products_dataset.csv',
    'sellers': 'olist_sellers_dataset.csv', 'geolocation': 'olist_geolocation_dataset.csv',
    'translation': 'product_category_name_translation.csv',
}
KEYS = {
    'orders': [('order_id',)], 'customers': [('customer_id',)], 'products': [('product_id',)],
    'sellers': [('seller_id',)], 'order_items': [('order_id', 'order_item_id')],
    'order_payments': [('order_id', 'payment_sequential')],
    'order_reviews': [('review_id',), ('order_id',), ('review_id', 'order_id')],
    'translation': [('product_category_name',)], 'geolocation': [('geolocation_zip_code_prefix',)],
}
FKS = [
    ('orders', 'customer_id', 'customers', 'customer_id'),
    ('order_items', 'order_id', 'orders', 'order_id'),
    ('order_items', 'product_id', 'products', 'product_id'),
    ('order_items', 'seller_id', 'sellers', 'seller_id'),
    ('order_payments', 'order_id', 'orders', 'order_id'),
    ('order_reviews', 'order_id', 'orders', 'order_id'),
    ('products', 'product_category_name', 'translation', 'product_category_name'),
    ('customers', 'customer_zip_code_prefix', 'geolocation', 'geolocation_zip_code_prefix'),
    ('sellers', 'seller_zip_code_prefix', 'geolocation', 'geolocation_zip_code_prefix'),
]


def main():
    missing = [name for name in FILES.values() if not (RAW / name).is_file()]
    if missing:
        print('缺少原始 CSV，请先将以下文件放入 data/raw/：\n' + '\n'.join(missing), file=sys.stderr)
        return 2
    import duckdb
    import pandas as pd
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    tables = {}
    for table, filename in FILES.items():
        # 邮编保留字符串以免丢失前导零；表名来自固定白名单。
        path = str(RAW / filename).replace("'", "''")
        con.execute(f"create view {table} as select * from read_csv('{path}', header=true, all_varchar=true)")
        tables[table] = con.execute(f'select * from {table}').df()
    # 先核对异常比例，超过 1% 直接停止。
    source_orders = tables['orders']
    delivered = source_orders['order_status'].eq('delivered')
    purchase = pd.to_datetime(source_orders['order_purchase_timestamp'], errors='coerce')
    delivery = pd.to_datetime(source_orders['order_delivered_customer_date'], errors='coerce')
    missing_delivery = delivered & delivery.isna()
    early_delivery = delivered & delivery.notna() & purchase.notna() & (delivery < purchase)
    n_delivered = int(delivered.sum())
    unknown_purchase = int((delivered & purchase.isna()).sum())
    invalid_n = int((missing_delivery | early_delivery).sum())
    if not n_delivered or unknown_purchase:
        raise ValueError('已送达订单的下单时间无效，或没有已送达订单，需人工核查')
    if invalid_n / n_delivered > 0.01:
        raise ValueError(f'送达时间异常 {invalid_n}/{n_delivered} 超过 1%，停止处理')
    pd.DataFrame([{'delivered_orders': n_delivered, 'delivery_missing_or_unparseable': int(missing_delivery.sum()), 'delivery_before_purchase': int(early_delivery.sum()), 'invalid_delivery_orders': invalid_n, 'invalid_share': invalid_n / n_delivered}]).to_csv(OUT / '00_delivery_time_check.csv', index=False)
    counts = []
    nulls = []
    keys = []
    for table, frame in tables.items():
        counts.append({'table': table, 'rows': len(frame), 'columns': len(frame.columns), 'exact_duplicate_rows': int(frame.duplicated().sum())})
        for col in frame:
            empty = frame[col].isna() | frame[col].astype('string').str.strip().eq('').fillna(False)
            nulls.append({'table': table, 'column': col, 'missing_rows': int(empty.sum()), 'rows': len(frame), 'missing_rate': float(empty.mean()) if len(frame) else None})
        for cols in KEYS.get(table, []):
            part = frame[list(cols)]
            absent = part.isna().any(axis=1) | part.astype('string').apply(lambda x: x.str.strip().eq('').fillna(False)).any(axis=1)
            valid = part.loc[~absent]
            keys.append({'table': table, 'key': ','.join(cols), 'key_role': '候选唯一键检查；邮编和评价键不预设唯一',
                         'rows': len(frame), 'null_key_rows': int(absent.sum()), 'duplicate_excess_rows': int(valid.duplicated().sum()),
                         'rows_in_duplicate_groups': int(valid.duplicated(keep=False).sum())})
    pd.DataFrame(counts).to_csv(OUT / '00_table_profile.csv', index=False)
    pd.DataFrame(nulls).to_csv(OUT / '00_missingness.csv', index=False)
    pd.DataFrame(keys).to_csv(OUT / '00_key_uniqueness.csv', index=False)
    relationships = []
    for child, col, parent, pk in FKS:
        child_values = tables[child][col].astype('string').str.strip()
        parent_values = set(tables[parent][pk].dropna().astype(str).str.strip())
        valid = child_values.notna() & child_values.ne('')
        matched = valid & child_values.isin(parent_values)
        relationships.append({'child': child, 'child_column': col, 'parent': parent, 'parent_column': pk,
                              'rows': len(child_values), 'null_fk_rows': int((~valid).sum()),
                              'nonnull_fk_rows': int(valid.sum()), 'matched_rows': int(matched.sum()),
                              'unmatched_nonnull_rows': int((valid & ~matched).sum()),
                              'match_rate_nonnull': float(matched.sum() / valid.sum()) if valid.sum() else None})
    pd.DataFrame(relationships).to_csv(OUT / '00_foreign_keys.csv', index=False)
    # SQL 按订单状态统计，另以可解析的下单时间描述全量范围。
    status_sql = 'select order_status, count(*) as order_rows from orders group by order_status order by order_rows desc'
    con.execute(status_sql).df().to_csv(OUT / '00_order_status.csv', index=False)
    con.execute('select min(try_cast(order_purchase_timestamp as timestamp)) as first_purchase, max(try_cast(order_purchase_timestamp as timestamp)) as last_purchase from orders').df().to_csv(OUT / '00_time_range.csv', index=False)
    # 面向后续分析的覆盖和评价粒度检查，SQL 留在项目中方便复跑。
    risk_sql = (ROOT / 'sql' / '01_stage0_risks.sql').read_text(encoding='utf-8')
    con.execute(risk_sql).df().to_csv(OUT / '00_analysis_risks.csv', index=False)
    con.execute('select min(try_cast(price as double)) as minimum, median(try_cast(price as double)) as median, quantile_cont(try_cast(price as double), 0.99) as p99, max(try_cast(price as double)) as maximum from order_items').df().to_csv(OUT / '00_price_distribution.csv', index=False)
    orders = tables['orders'].copy()
    steps = []
    def exclude(reason, bad):
        nonlocal orders
        before = len(orders)
        bad = bad.fillna(False)
        orders = orders.loc[~bad].copy()
        steps.append({'step': reason, 'before_rows': before, 'removed_rows': int(bad.sum()), 'after_rows': len(orders)})
    exclude('订单 ID 缺失', orders['order_id'].isna() | orders['order_id'].astype('string').str.strip().eq(''))
    purchase = pd.to_datetime(orders['order_purchase_timestamp'], errors='coerce')
    exclude('下单时间缺失或无法解析', purchase.isna())
    # 经营口径保留送达日期异常；另记录配送分析排除数。
    before = len(orders)
    steps.append({'step': '经营样本保留送达时间异常', 'before_rows': before, 'removed_rows': 0, 'after_rows': before})
    stage3_base = orders.loc[orders['order_status'].eq('delivered')].copy()
    d = pd.to_datetime(stage3_base['order_delivered_customer_date'], errors='coerce')
    p = pd.to_datetime(stage3_base['order_purchase_timestamp'], errors='coerce')
    pd.DataFrame([{'step': '配送分析：送达时间缺失或无法解析', 'before_rows': len(stage3_base), 'removed_rows': int(d.isna().sum()), 'after_rows': int(d.notna().sum())}, {'step': '配送分析：送达时间早于下单时间', 'before_rows': int(d.notna().sum()), 'removed_rows': int((d.notna() & (d < p)).sum()), 'after_rows': int((d.notna() & (d >= p)).sum())}]).to_csv(OUT / '00_delivery_exclusion_log.csv', index=False)
    # 商品行的价格与运费缺失、负值单独报告，不擅自删除或填零。
    items = tables['order_items']
    value_checks = []
    for col in ['price', 'freight_value']:
        values = pd.to_numeric(items[col], errors='coerce')
        value_checks.append({'column': col, 'rows': len(items), 'missing_or_invalid': int(values.isna().sum()), 'negative': int((values < 0).sum()), 'zero': int((values == 0).sum())})
    pd.DataFrame(value_checks).to_csv(OUT / '00_item_value_checks.csv', index=False)
    pd.DataFrame(steps).to_csv(OUT / '00_cleaning_log.csv', index=False)
    # 输出清洗后的订单视图，其他表仍保持原样；业务使用前须核对重复键。
    orders.to_csv(OUT / '00_clean_orders.csv', index=False)
    print(f'阶段 0 结果已写入 {OUT}。请先检查键、缺失和清洗记录。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
