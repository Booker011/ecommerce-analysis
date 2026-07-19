"""
数据质量检查模块
----------------
检查缺失值、异常值、重复订单，输出数据质量评分（百分制）。
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from datetime import datetime

from config import QUALITY_WEIGHTS


class DataQualityChecker:
    """数据质量检查器：评估数据完整性、合理性和唯一性。"""

    def __init__(self):
        self.report: Dict[str, Any] = {}
        self.quality_score: float = 0.0

    def check_missing_values(self, df: pd.DataFrame) -> Dict[str, Any]:
        """检查各字段的缺失值。

        Args:
            df: 数据 DataFrame

        Returns:
            dict: 缺失值报告
        """
        total = len(df)
        missing_report = {}

        for col in df.columns:
            missing_count = df[col].isna().sum()
            # 空字符串也算缺失
            if df[col].dtype == "object":
                empty_count = (df[col] == "").sum()
                missing_count += empty_count
            missing_pct = round(missing_count / total * 100, 2) if total > 0 else 0
            missing_report[col] = {
                "count": int(missing_count),
                "percentage": missing_pct,
                "status": "✅ 正常" if missing_pct < 5 else ("⚠️ 警告" if missing_pct < 20 else "❌ 严重"),
            }

        completeness_score = np.mean([
            100 - min(info["percentage"], 100)
            for info in missing_report.values()
        ])

        print(f"  [质量] 缺失值检查完成，完整度得分: {completeness_score:.1f}")

        return {
            "per_column": missing_report,
            "completeness_score": round(completeness_score, 1),
        }

    def check_anomalies(self, df: pd.DataFrame) -> Dict[str, Any]:
        """检查异常值（价格为负、数量为负或为零、事件类型非法等）。

        Args:
            df: 数据 DataFrame

        Returns:
            dict: 异常值报告
        """
        anomalies = {}
        total = len(df)
        anomaly_count = 0

        # 价格为负
        if "price" in df.columns:
            neg_price = (df["price"] < 0).sum()
            if neg_price > 0:
                anomalies["price_negative"] = {
                    "count": int(neg_price),
                    "description": "价格为负数",
                    "severity": "高",
                }
                anomaly_count += neg_price

        # 价格为零
        if "price" in df.columns:
            zero_price = (df["price"] == 0).sum()
            if zero_price > 0:
                anomalies["price_zero"] = {
                    "count": int(zero_price),
                    "description": "价格为零",
                    "severity": "中",
                }
                anomaly_count += zero_price

        # 数量为负
        if "quantity" in df.columns:
            neg_qty = (df["quantity"] < 0).sum()
            if neg_qty > 0:
                anomalies["quantity_negative"] = {
                    "count": int(neg_qty),
                    "description": "数量为负数",
                    "severity": "高",
                }
                anomaly_count += neg_qty

        # 数量为零
        if "quantity" in df.columns:
            zero_qty = (df["quantity"] == 0).sum()
            if zero_qty > 0:
                anomalies["quantity_zero"] = {
                    "count": int(zero_qty),
                    "description": "数量为零",
                    "severity": "中",
                }
                anomaly_count += zero_qty

        # 事件类型非法
        if "event_type" in df.columns:
            valid_types = {"view", "cart", "purchase"}
            invalid_events = (~df["event_type"].isin(valid_types)).sum()
            if invalid_events > 0:
                anomalies["invalid_event_type"] = {
                    "count": int(invalid_events),
                    "description": f"非法事件类型（允许: {valid_types}）",
                    "severity": "高",
                }
                anomaly_count += invalid_events

        # 时间异常（未来时间）
        if "event_time" in df.columns:
            future_events = (df["event_time"] > datetime.now()).sum()
            if future_events > 0:
                anomalies["future_time"] = {
                    "count": int(future_events),
                    "description": "事件时间为未来时间",
                    "severity": "中",
                }
                anomaly_count += future_events

        validity_score = max(0, 100 - (anomaly_count / total * 100)) if total > 0 else 100

        print(f"  [质量] 异常值检查完成，发现 {len(anomalies)} 类异常，有效度得分: {validity_score:.1f}")

        return {
            "anomaly_items": anomalies,
            "total_anomalies": int(anomaly_count),
            "validity_score": round(validity_score, 1),
        }

    def check_duplicates(self, df: pd.DataFrame) -> Dict[str, Any]:
        """检查重复订单。

        Args:
            df: 数据 DataFrame

        Returns:
            dict: 重复报告
        """
        total = len(df)

        # 检查完全重复行
        full_dupes = df.duplicated().sum()
        full_dupe_pct = round(full_dupes / total * 100, 2) if total > 0 else 0

        # 检查 order_id 重复
        order_dupes = 0
        if "order_id" in df.columns:
            order_dupes = df.duplicated(subset=["order_id"]).sum()

        # 组合重复（同一用户同一商品同一时间）
        combo_dupes = 0
        combo_cols = [c for c in ["user_id", "product_id", "event_time"] if c in df.columns]
        if len(combo_cols) >= 2:
            combo_dupes = df.duplicated(subset=combo_cols).sum()

        total_dupes = max(full_dupes, order_dupes, combo_dupes)
        uniqueness_score = max(0, 100 - (total_dupes / total * 100)) if total > 0 else 100

        print(f"  [质量] 重复检查完成，唯一性得分: {uniqueness_score:.1f}")

        return {
            "full_duplicates": int(full_dupes),
            "order_id_duplicates": int(order_dupes),
            "combo_duplicates": int(combo_dupes),
            "total_duplicates": int(total_dupes),
            "uniqueness_score": round(uniqueness_score, 1),
        }

    def calculate_quality_score(
        self,
        missing_report: Dict[str, Any],
        anomaly_report: Dict[str, Any],
        duplicate_report: Dict[str, Any],
    ) -> float:
        """计算综合数据质量评分（百分制）。

        评分公式 = 完整度×40% + 有效度×30% + 唯一性×30%

        Args:
            missing_report: 缺失值报告
            anomaly_report: 异常值报告
            duplicate_report: 重复报告

        Returns:
            float: 0-100 的质量评分
        """
        completeness = missing_report.get("completeness_score", 100)
        validity = anomaly_report.get("validity_score", 100)
        uniqueness = duplicate_report.get("uniqueness_score", 100)

        score = (
            completeness * QUALITY_WEIGHTS["completeness"] +
            validity * QUALITY_WEIGHTS["validity"] +
            uniqueness * QUALITY_WEIGHTS["uniqueness"]
        )

        score = round(score, 1)

        # 评分等级
        if score >= 95:
            grade = "A (优秀)"
        elif score >= 85:
            grade = "B (良好)"
        elif score >= 70:
            grade = "C (一般)"
        elif score >= 60:
            grade = "D (较差)"
        else:
            grade = "E (很差)"

        self.quality_score = score

        print(f"\n  🏆 数据质量总分: {score}/100 — 等级: {grade}")

        return score

    def run(self, df: pd.DataFrame) -> Dict[str, Any]:
        """执行完整的数据质量检查。

        Args:
            df: 清洗后的数据 DataFrame

        Returns:
            dict: 完整的数据质量报告
        """
        print("\n" + "-" * 40)
        print("  Step 2: 数据质量检查")
        print("-" * 40)

        try:
            missing_report = self.check_missing_values(df)
            anomaly_report = self.check_anomalies(df)
            duplicate_report = self.check_duplicates(df)
            score = self.calculate_quality_score(missing_report, anomaly_report, duplicate_report)

            self.report = {
                "missing_report": missing_report,
                "anomaly_report": anomaly_report,
                "duplicate_report": duplicate_report,
                "quality_score": score,
            }

            return self.report

        except Exception as e:
            print(f"  ❌ 数据质量检查失败: {e}")
            # 返回一个降级的报告
            self.report = {
                "missing_report": {"error": str(e)},
                "anomaly_report": {"error": str(e)},
                "duplicate_report": {"error": str(e)},
                "quality_score": 0,
                "error": str(e),
            }
            return self.report
