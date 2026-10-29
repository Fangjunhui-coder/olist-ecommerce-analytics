"""通过 Kaggle API 下载原始 CSV；没有凭证时提供手动操作提示。"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'data' / 'raw'
DATASET = 'olistbr/brazilian-ecommerce'


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    # 延迟导入：无凭证时 Kaggle 包可能在导入阶段报错。
    credentials = (os.getenv('KAGGLE_API_TOKEN') or
                   (os.getenv('KAGGLE_USERNAME') and os.getenv('KAGGLE_KEY')) or
                   (Path(os.getenv('KAGGLE_CONFIG_DIR', str(Path.home() / '.kaggle'))) / 'kaggle.json').is_file())
    if not credentials:
        print('未找到 Kaggle API 凭证。请从 https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce 下载并解压，')
        print(f'将 9 个 CSV 直接放入：{RAW}')
        return 2
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        api.dataset_download_files(DATASET, path=str(RAW), unzip=True, quiet=False)
    except Exception as exc:
        print(f'下载失败：{exc}\n请检查 API 凭证和数据集访问权限，或手动下载并解压到 {RAW}。', file=sys.stderr)
        return 1
    print(f'下载完成：{RAW}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
