# Olist 电商经营指标、用户分层与配送体验分析

## 项目背景与业务问题

这是一个面向数据分析、数据运营和产品运营实习求职的公开数据分析项目。项目使用历史匿名订单，回答：已送达交易的经营规模和品类、地区结构如何；在低复购条件下如何构建可解释的用户分层；配送延迟与差评有何关联，哪些区域或卖家值得进一步排查。

代码编写和文档整理由 **AI 辅助完成**。所有结论来自实际运行；项目没有开展真实运营干预、上线实验或产生可归因的业务提升。

## 数据来源与许可

- 数据：[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)，包含订单、商品、支付、评价、客户、卖家、地理位置及品类翻译等九张表。
- Kaggle 数据集页面标注 **CC BY-NC-SA 4.0**。请在使用、修改或分享数据时核对并遵守许可，特别是署名、非商业和相同方式共享条款。
- 原始 CSV 及其压缩文件不纳入 Git；本项目还忽略可能与原始订单逐行一致的清洗副本。公开数据的匿名 ID 不代表本项目获得了任何联系或触达权限。

## 指标与分析口径

- 经营指标限定 `order_status = delivered`，按下单时间归属月份；买家用 `customer_unique_id`。商品 GMV 为商品明细金额，不含运费；运费总额与含运费 GMV 单独列示。它们不是实收或净收入。
- 保留送达时间异常订单用于经营指标；配送分析排除实际／预计送达时间无效或送达时间早于下单时间的记录。
- 原名存在但没有英文翻译时保留葡语名；原名缺失时归为未知。州取客户表，不直接连接邮编不唯一的地理位置表。
- 累计复购率为观察期内至少两单买家 / 全部买家；90 天复购率仅包含首单日期距全量数据截止日期至少 90 个自然日的买家。两者口径不同，且样本末段覆盖存在限制。
- RFM：R 的参照日为全量订单最后下单日的次日；F 分 1 单和 2 单及以上；R 和 M 按全体用户的三分位分档，同值不拆分。18 个组合合并成六个互斥运营人群。
- 评价按每单回复时间最新的一条；无评价订单排除。配送延迟主口径按自然日期比较，原时间戳口径保留为敏感性对照。逻辑回归的主品类取订单金额最高的商品，多卖家订单只要有一个卖家与客户跨州即记为跨州。

## 核心结论

1. **经营规模：**已送达订单 96,478 单、买家 93,358 人，商品 GMV 13,221,498.11 雷亚尔；前 18 个品类累计贡献 81.29%。该结果不是实收，且已送达筛选不代表全部下单交易。
2. **用户分层：**全观察期累计复购率 3.00%；首单后 90 天复购率 1.90%（1,608 / 84,462）。历史末段已送达订单覆盖不足；较早截止时点的敏感性对照为 2.01%。较久高金额单次用户占 20.79%，贡献 GMV 43.38%，但不能据此认定当前流失或实际运营效果。
3. **配送与评价：**自然日期口径下延迟组差评率 62.42%，准时组 9.27%；差异为 53.15 个百分点，95% 区间 51.94–54.35。全样本调整后 OR 为 16.80，而只保留评价不早于送达的子样本 OR 为 2.38；两者均为观察性关联，时间顺序和样本选择限制因果解释。

详见 [业务报告](docs/report.md)、[阶段 3 结果](docs/阶段3_配送与差评.md)和[面试笔记](docs/interview_notes.md)。

## 项目结构

```text
data/raw/                  手动或 Kaggle 下载的原始数据（不提交）
sql/                       按模块编号的 DuckDB SQL
src/                       数据检查、计算、独立对账和文档生成
notebooks/                 从头运行的 notebook
docs/                      口径、阶段结果、业务报告和面试提纲
results/tables/            可供 Tableau 导入的汇总 CSV
results/figures/           关键图表
tests/                     合成数据的边界测试
download_data.py           Kaggle API 下载脚本
validate.py                从原始数据重新计算并与现有结果对账
requirements.txt           依赖版本
```

## 从头运行

需要 Python 3.12。以下命令在项目根目录执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python download_data.py
```

若没有 Kaggle 凭证，下载脚本会提示从数据集页面下载 ZIP；解压后将全部九个 CSV **直接放入 `data/raw/`**。若地理位置数据为 `.csv.gz`，先解压为 `olist_geolocation_dataset.csv`。不要将凭证或原始数据提交到仓库。

```bash
python src/stage0.py
python src/stage1.py
python src/stage1_supplement.py
python src/stage2.py
python src/stage2_groups.py
python src/write_stage2_notes.py
python src/stage3.py
python src/stage3.py --policy timestamp
python src/stage3_policy_comparison.py
python src/write_stage3_notes.py
python validate.py
python -m unittest discover -s tests -v
```

或者运行 `jupyter lab`，打开 `notebooks/olist_end_to_end.ipynb` 并从头运行。`validate.py` 重新从原始数据构造 pandas 结果，与 SQL 和已保存结果比较，任何不一致都会报错。`docs/report.md`、`docs/interview_notes.md` 与部分说明中的数字是基于本次数据的静态文字；更换数据或规则并重跑后必须重新审查更新，不能假定自动同步。

各汇总 CSV 中比例通常存为小数，例如 0.1 表示 10%；特别地，`repeat_rate_pp_change` 的单位是百分点。按月品类表未出现的组合不等于真实业务为零，跨品类订单数和用户数不可直接加总。
