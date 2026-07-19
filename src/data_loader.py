"""
数据加载与预处理模块
--------------------
负责扫描 data/ 文件夹、读取 Excel、自动识别中英文字段名并映射、
填充默认值，输出数据概况。
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, Dict, Any

from config import DATA_DIR, COLUMN_MAPPING, EVENT_TYPE_MAPPING


class DataLoader:
    """数据加载器：负责 Excel 发现、读取、字段映射与预处理。"""

    def __init__(self):
        self.raw_df: Optional[pd.DataFrame] = None
        self.file_path: Optional[Path] = None
        self.mapped_columns: Dict[str, str] = {}
        self.summary: Dict[str, Any] = {}

    def find_excel_file(self) -> Path:
        """扫描 data/ 文件夹，返回第一个 .xlsx 文件路径。

        Returns:
            Path: 找到的 Excel 文件路径

        Raises:
            FileNotFoundError: 如果没有找到 .xlsx 文件
        """
        xlsx_files = sorted(DATA_DIR.glob("*.xlsx"))
        if not xlsx_files:
            raise FileNotFoundError(
                f"在 {DATA_DIR.resolve()} 中没有找到 .xlsx 文件！\n"
                f"请将电商数据 Excel 文件放入 data/ 文件夹后重试。"
            )

        # 优先选择非临时文件（不以 ~ 开头）
        for f in xlsx_files:
            if not f.name.startswith("~"):
                self.file_path = f
                break
        else:
            self.file_path = xlsx_files[0]

        print(f"[DataLoader] 发现数据文件: {self.file_path.name}")
        return self.file_path

    def read_excel(self, file_path: Optional[Path] = None) -> pd.DataFrame:
        """读取 Excel 文件为 DataFrame。

        Args:
            file_path: Excel 文件路径，不传则自动扫描

        Returns:
            pd.DataFrame: 原始数据
        """
        if file_path is None:
            file_path = self.find_excel_file()
        else:
            self.file_path = file_path

        try:
            # 尝试用 openpyxl 读取，处理日期列
            self.raw_df = pd.read_excel(
                file_path,
                engine="openpyxl",
                dtype=str,  # 先全部读为字符串，后续再转换类型
            )
            print(f"[DataLoader] 成功读取: {len(self.raw_df)} 行 × {len(self.raw_df.columns)} 列")
        except Exception as e:
            raise ValueError(f"读取 Excel 文件失败: {e}") from e

        return self.raw_df

    def map_columns(self, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """自动识别中英文字段名并映射为英文标准名称。

        Args:
            df: 原始 DataFrame

        Returns:
            pd.DataFrame: 列名已标准化的 DataFrame
        """
        if df is None:
            df = self.raw_df
        if df is None:
            raise ValueError("请先调用 read_excel() 读取数据")

        df = df.copy()

        # 去除列名前后的空白字符
        df.columns = [str(c).strip() for c in df.columns]

        rename_map = {}
        self.mapped_columns = {}

        for col in df.columns:
            # 先尝试精确匹配
            if col in COLUMN_MAPPING:
                target = COLUMN_MAPPING[col]
                rename_map[col] = target
                self.mapped_columns[col] = target
            # 再尝试不区分大小写的匹配
            elif col.lower() in {k.lower(): k for k in COLUMN_MAPPING}:
                original_key = {k.lower(): k for k in COLUMN_MAPPING}[col.lower()]
                target = COLUMN_MAPPING[original_key]
                rename_map[col] = target
                self.mapped_columns[col] = target
            # 部分匹配（列名包含关键词）
            else:
                matched = False
                for key, target in COLUMN_MAPPING.items():
                    if key.lower() in col.lower():
                        rename_map[col] = target
                        self.mapped_columns[col] = target
                        matched = True
                        break
                if not matched:
                    print(f"  [警告] 未识别的列: '{col}'，保留原名")

        df.rename(columns=rename_map, inplace=True)

        # 验证必要字段
        required_fields = ["order_id", "user_id", "product_id", "event_type", "price", "event_time"]
        missing = [f for f in required_fields if f not in df.columns]
        if missing:
            raise ValueError(
                f"缺少必要字段: {missing}\n"
                f"可用列: {list(df.columns)}\n"
                f"请确保 Excel 中包含对应的中英文列名。"
            )

        print(f"[DataLoader] 字段映射完成，标准化列: {list(df.columns)}")
        return df

    def fill_defaults(self, df: pd.DataFrame) -> pd.DataFrame:
        """自动填充缺失的可选字段。

        - 没有 channel 字段 → 填充 "organic"
        - 没有 device 字段 → 填充 "unknown"
        - 没有 category 字段 → 填充 "未分类"
        - 没有 quantity 字段 → 填充 1

        Args:
            df: 标准化后的 DataFrame

        Returns:
            pd.DataFrame: 已填充默认值的 DataFrame
        """
        df = df.copy()

        if "channel" not in df.columns:
            df["channel"] = "organic"
            print("[DataLoader] 未检测到 channel 字段，自动填充 'organic'")
        else:
            df["channel"] = df["channel"].fillna("organic").replace("", "organic")

        if "device" not in df.columns:
            df["device"] = "unknown"
            print("[DataLoader] 未检测到 device 字段，自动填充 'unknown'")
        else:
            df["device"] = df["device"].fillna("unknown").replace("", "unknown")

        if "category" not in df.columns:
            df["category"] = "未分类"
            print("[DataLoader] 未检测到 category 字段，自动填充 '未分类'")
        else:
            df["category"] = df["category"].fillna("未分类").replace("", "未分类")

        if "quantity" not in df.columns:
            df["quantity"] = "1"
            print("[DataLoader] 未检测到 quantity 字段，自动填充 1")
        else:
            df["quantity"] = df["quantity"].fillna("1").replace("", "1")

        return df

    def clean_and_convert(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据清洗与类型转换。

        - event_type 统一为小写英文
        - price / quantity 转为数值型
        - event_time 转为 datetime
        - 去除首尾空白

        Args:
            df: DataFrame

        Returns:
            pd.DataFrame: 清洗后的 DataFrame
        """
        df = df.copy()

        # 字符串列去除首尾空白
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].str.strip()

        # 事件类型映射（中文 → 英文）
        if "event_type" in df.columns:
            df["event_type"] = df["event_type"].map(
                lambda x: EVENT_TYPE_MAPPING.get(str(x), str(x).lower())
            )

        # 价格转为数值
        if "price" in df.columns:
            df["price"] = pd.to_numeric(df["price"], errors="coerce")

        # 数量转为整数
        if "quantity" in df.columns:
            df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(1).astype(int)

        # 事件时间转为 datetime
        if "event_time" in df.columns:
            df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")

        print("[DataLoader] 数据类型转换完成")
        return df

    def generate_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """生成数据概况摘要。

        Args:
            df: 清洗后的 DataFrame

        Returns:
            dict: 包含总行数、时间范围、用户数、商品数、事件分布等信息
        """
        summary = {
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "file_name": self.file_path.name if self.file_path else "未知",
        }

        # 时间范围
        if "event_time" in df.columns and df["event_time"].notna().any():
            valid_times = df["event_time"].dropna()
            summary["time_start"] = valid_times.min().strftime("%Y-%m-%d")
            summary["time_end"] = valid_times.max().strftime("%Y-%m-%d")
            summary["time_days"] = (valid_times.max() - valid_times.min()).days + 1
        else:
            summary["time_start"] = "未知"
            summary["time_end"] = "未知"
            summary["time_days"] = 0

        # 用户数
        summary["user_count"] = df["user_id"].nunique() if "user_id" in df.columns else 0
        # 商品数
        summary["product_count"] = df["product_id"].nunique() if "product_id" in df.columns else 0
        # 订单数
        summary["order_count"] = df["order_id"].nunique() if "order_id" in df.columns else 0
        # 品类数
        summary["category_count"] = df["category"].nunique() if "category" in df.columns else 0

        # 事件类型分布
        if "event_type" in df.columns:
            event_dist = df["event_type"].value_counts().to_dict()
            summary["event_distribution"] = event_dist
            summary["view_count"] = event_dist.get("view", 0)
            summary["cart_count"] = event_dist.get("cart", 0)
            summary["purchase_count"] = event_dist.get("purchase", 0)
        else:
            summary["event_distribution"] = {}

        # 渠道分布
        if "channel" in df.columns:
            summary["channel_count"] = df["channel"].nunique()
        else:
            summary["channel_count"] = 0

        # GMV 估算（purchase 事件的 price * quantity 之和）
        purchase_df = df[df["event_type"] == "purchase"] if "event_type" in df.columns else pd.DataFrame()
        if not purchase_df.empty and "price" in purchase_df.columns:
            purchase_df = purchase_df.copy()
            purchase_df["amount"] = purchase_df["price"] * purchase_df.get("quantity", 1)
            summary["total_gmv"] = round(purchase_df["amount"].sum(), 2)
            summary["avg_price"] = round(purchase_df["price"].mean(), 2)
            summary["buyer_count"] = purchase_df["user_id"].nunique() if "user_id" in purchase_df.columns else 0
        else:
            summary["total_gmv"] = 0
            summary["avg_price"] = 0
            summary["buyer_count"] = 0

        self.summary = summary
        print(f"[DataLoader] 数据概况生成完成")
        self._print_summary(summary)
        return summary

    def _print_summary(self, summary: Dict[str, Any]):
        """打印数据概况到控制台。"""
        print("\n" + "=" * 50)
        print("  📊 数据概况")
        print("=" * 50)
        print(f"  文件名:    {summary['file_name']}")
        print(f"  总行数:    {summary['total_rows']:,}")
        print(f"  时间范围:  {summary['time_start']} ~ {summary['time_end']} ({summary['time_days']} 天)")
        print(f"  用户数:    {summary['user_count']:,}")
        print(f"  商品数:    {summary['product_count']:,}")
        print(f"  订单数:    {summary['order_count']:,}")
        print(f"  品类数:    {summary['category_count']}")
        print(f"  渠道数:    {summary['channel_count']}")

        if summary.get("event_distribution"):
            print(f"  事件分布:")
            for event, cnt in summary["event_distribution"].items():
                pct = cnt / summary["total_rows"] * 100 if summary["total_rows"] else 0
                print(f"    - {event}: {cnt:,} ({pct:.1f}%)")

        print(f"  预估GMV:   ¥{summary['total_gmv']:,.2f}")
        print("=" * 50 + "\n")

    def run(self) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """执行完整的数据加载与预处理流程。

        Returns:
            tuple: (清洗后的 DataFrame, 数据概况字典)
        """
        print("\n" + "-" * 40)
        print("  Step 1: 环境检查与数据发现")
        print("-" * 40)

        self.find_excel_file()
        self.read_excel(self.file_path)
        df = self.map_columns()
        df = self.fill_defaults(df)
        df = self.clean_and_convert(df)
        summary = self.generate_summary(df)

        return df, summary
