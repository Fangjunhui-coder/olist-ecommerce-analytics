"""从原始 CSV 独立复算并与现有 SQL 结果对账；不一致时退出报错。"""
import sys
import tempfile
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
import stage1, stage1_supplement, stage2, stage2_groups, stage3, stage3_policy_comparison


def main():
    saved=ROOT/'results/tables'
    # 在临时目录计算，避免先覆盖旧结果、再误以为对账成功。
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp)/'tables';fig=Path(tmp)/'figures';out.mkdir();fig.mkdir()
        for mod in [stage1,stage1_supplement,stage2,stage2_groups,stage3,stage3_policy_comparison]:mod.OUT=out
        stage1.FIG=fig;stage1_supplement.FIG=fig;stage2_groups.FIG=fig
        stage1.main();stage1_supplement.main();stage2.main();stage2_groups.main()
        old_args=sys.argv[:]
        try:
            sys.argv=['stage3'];stage3.main()
            sys.argv=['stage3','--policy','timestamp'];stage3.main()
        finally:sys.argv=old_args
        stage3_policy_comparison.main()
        targets={
            '01_overall.csv':[], '01_monthly.csv':['month'],
            '01_category_translation_status.csv':['category_status'],
            '01_freight_comparison.csv':[], '01_repeat_90d.csv':[],
            '01_repeat_90d_sensitivity.csv':[], '02_rfm_segments.csv':['r_band','f_band','m_band'],
            '02_operating_groups.csv':['operating_group'],
            '03_delay_comparison.csv':['delayed'],'03_delay_bands.csv':['delay_band'],
            '03_policy_comparison.csv':['policy']}
        for name,keys in targets.items():
            if not (saved/name).exists():raise FileNotFoundError(f'结果文件不存在：{saved/name}；请先运行对应阶段。')
            actual=pd.read_csv(saved/name);expected=pd.read_csv(out/name)
            if keys:actual=actual.sort_values(keys).reset_index(drop=True);expected=expected.sort_values(keys).reset_index(drop=True)
            pd.testing.assert_frame_equal(actual,expected,check_dtype=False,check_exact=False,rtol=1e-9,atol=1e-8,obj=name)
            print(f'通过：{name}')
    print('全部核心结果已从原始数据独立复算，并与已保存结果核对一致。')


if __name__=='__main__': main()
