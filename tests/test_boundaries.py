"""针对真实 SQL 的延迟、RFM 和 90 天复购边界样本。"""
import unittest
from pathlib import Path
import duckdb

ROOT=Path(__file__).resolve().parents[1]


class TestBoundaries(unittest.TestCase):
    def test_delivery_calendar_boundaries(self):
        db=duckdb.connect()
        db.execute('create table eligible_orders(order_id varchar,customer_unique_id varchar,customer_state varchar,purchased_at timestamp)')
        db.execute('create table orders(order_id varchar,order_delivered_customer_date varchar,order_estimated_delivery_date varchar)')
        db.execute('create table order_reviews(order_id varchar,review_id varchar,review_score varchar,review_answer_timestamp varchar,review_creation_date varchar)')
        db.execute('create table order_items(order_id varchar,order_item_id varchar,price varchar,freight_value varchar,seller_id varchar,product_id varchar)')
        db.execute('create table sellers(seller_id varchar,seller_state varchar)')
        db.execute('create table products(product_id varchar,product_category_name varchar)')
        db.execute('create table translation(product_category_name varchar,product_category_name_english varchar)')
        db.execute("insert into sellers values ('s','SP')");db.execute("insert into products values ('p','c')");db.execute("insert into translation values ('c','cat')")
        # 同日不同时间为准时；1、3、4、7、8 天分别命中正确分组。
        days=[('same','2020-01-10 19:00:00'),('d1','2020-01-11 10:00:00'),('d3','2020-01-13 10:00:00'),('d4','2020-01-14 10:00:00'),('d7','2020-01-17 10:00:00'),('d8','2020-01-18 10:00:00')]
        for key,dt in days:
            db.execute("insert into eligible_orders values (?,?,'SP',timestamp '2020-01-01')",[key,key]);db.execute("insert into orders values (?,?,'2020-01-10 00:00:00')",[key,dt]);db.execute("insert into order_reviews values (?,?, '2','2020-02-01 00:00:00','2020-01-01 00:00:00')",[key,key]);db.execute("insert into order_items values (?,'1','10','2','s','p')",[key])
        db.execute((ROOT/'sql/07_delivery_analysis.sql').read_text())
        observed=dict(db.execute('select order_id,delay_band from analysis_orders').fetchall())
        self.assertEqual(observed,{'same':'on_time','d1':'1_to_3_days','d3':'1_to_3_days','d4':'4_to_7_days','d7':'4_to_7_days','d8':'over_7_days'})

    def test_rfm_frequency_and_tied_quantiles(self):
        db=duckdb.connect();db.execute('create table orders(order_purchase_timestamp varchar)');db.execute("insert into orders values ('2020-04-01 12:00:00')")
        db.execute('create table eligible_orders(order_id varchar,purchased_at timestamp)');db.execute('create table order_facts(order_id varchar,customer_unique_id varchar,gmv decimal(18,2))')
        # 大量 F=1 的并列值必须落在同一档，而非强行切分。
        for j in range(5):
            db.execute('insert into eligible_orders values (?,?)',[f'o{j}','2020-01-01 10:00:00']);db.execute('insert into order_facts values (?,?,?)',[f'o{j}',f'u{j}',10])
        db.execute("insert into eligible_orders values ('second','2020-02-01')");db.execute("insert into order_facts values ('second','u0',20)")
        db.execute((ROOT/'sql/05_rfm.sql').read_text());rows=db.execute('select customer_unique_id,f_band,r_band,m_band from rfm_users order by 1').fetchall()
        self.assertEqual(rows[0][1],'repeat');self.assertTrue(all(row[1]=='one' for row in rows[1:]));self.assertEqual(len({row[2:] for row in rows[1:]}),1)

    def test_90_day_repurchase_window(self):
        db=duckdb.connect();db.execute('create table orders(order_purchase_timestamp varchar)');db.execute("insert into orders values ('2020-03-31 23:59:59')")
        db.execute('create table eligible_orders(order_id varchar,customer_unique_id varchar,purchased_at timestamp)')
        db.executemany('insert into eligible_orders values (?,?,?)',[('a1','a','2020-01-01 00:00:00'),('a2','a','2020-03-31 23:00:00'),('b1','b','2019-12-31 00:00:00'),('b2','b','2020-03-31 00:00:00'),('c1','c','2020-01-02 00:00:00'),('d1','d','2020-01-01 00:00:00'),('d2','d','2020-01-01 00:00:00')])
        db.execute('create table eligible_items(order_id varchar,order_item_id varchar,price decimal(18,2))');db.execute('create table order_items(order_id varchar,order_item_id varchar,freight_value varchar)')
        db.execute((ROOT/'sql/04_supplementary_metrics.sql').read_text());self.assertEqual(db.execute('select eligible_buyers,repeat_buyers_90d from repeat_90').fetchone(),(3,1))


if __name__=='__main__':unittest.main()
