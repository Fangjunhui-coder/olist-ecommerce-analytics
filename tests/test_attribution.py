import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import unittest
import numpy as np
import pandas as pd
from stage4_diagnosis import lmdi,substitution,mix_rate
from stage5_causal import smd,match

class AttributionTests(unittest.TestCase):
    def test_lmdi_equal_and_opposing_changes(self):
        for old,new in [([10,2,5],[20,3,4]),([10,2,5],[20,1,5]),([10,2,5],[10,2,5])]:
            delta=np.prod(new)-np.prod(old)
            self.assertAlmostEqual(lmdi(old,new).sum(),delta)
            self.assertAlmostEqual(substitution(old,new).sum(),delta)
        with self.assertRaises(ValueError):lmdi([0,1],[2,1])
    def test_mix_rate_entry_exit(self):
        a=pd.DataFrame({'segment':['a','b'],'gmv':[100,200],'units':[10,10]})
        b=pd.DataFrame({'segment':['b','c'],'gmv':[240,50],'units':[12,5]})
        x=mix_rate(a,b)
        np.testing.assert_allclose(x[['volume_effect','mix_effect','rate_effect']].sum(axis=1),x.change)
        self.assertAlmostEqual(x.change.sum(),-10)
        self.assertAlmostEqual(x.contribution_share.sum(),1)
    def test_psm_balance_and_caliper(self):
        self.assertEqual(smd([[0],[1]],[[0],[1]])[0],0)
        self.assertGreater(abs(smd([[2],[3]],[[0],[1]])[0]),.1)
        lp=np.array([0.,.5,.01,.49,-1.,1.]);t=np.array([1,1,0,0,0,0])
        pairs,_=match(lp,t,.1)
        self.assertEqual(len(pairs),2);self.assertEqual(len(set(pairs[:,1])),2)
        self.assertTrue((abs(lp[pairs[:,0]]-lp[pairs[:,1]])<=.1).all())

    def test_seller_history_excludes_future_outcomes_and_purchase_ties(self):
        import duckdb
        con=duckdb.connect()
        con.execute("create table order_items(order_id varchar,seller_id varchar,price varchar,order_item_id varchar)")
        con.execute("insert into order_items values ('known','s','1','1'),('pending','s','1','1'),('tie','s','1','1'),('current','s','1','1')")
        con.execute("create table orders(order_id varchar,order_purchase_timestamp varchar)")
        con.execute("insert into orders values ('known','2017-01-01'),('pending','2017-01-02'),('tie','2017-01-03 12:00:00'),('current','2017-01-03 12:00:00')")
        con.execute("create table delivery_orders(order_id varchar,delivered_at timestamp,delayed integer)")
        con.execute("insert into delivery_orders values ('known','2017-01-02',1),('pending','2017-01-04',0),('current','2017-01-10',0)")
        con.execute("create table analysis_orders(order_id varchar,purchased_at timestamp,estimated_at timestamp,delivered_at timestamp,review_answer_at timestamp)")
        con.execute("insert into analysis_orders values ('current','2017-01-03 12:00:00','2017-01-10','2017-01-10','2017-01-11')")
        con.execute((Path(__file__).resolve().parents[1]/'sql/10_delay_review_causal.sql').read_text())
        row=con.execute('select seller_prior_orders,seller_completed_orders,seller_history_delay_rate from causal_orders').fetchone()
        self.assertEqual(row,(2,1,1.0))
