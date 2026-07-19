"""
数据一致性校验模块
------------------
校验 ODS → DWD 行数一致性，DWD → DWS 汇总一致性，输出校验报告。
"""

import sqlite3
import pandas as pd
from typing import Dict, Any, Optional, List

from config import DB_PATH


class DataChecker:
    """数据一致性校验器：验证各层数据之间的一致性。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        self.checks: List[Dict[str, Any]] = []
        self.passed = 0
        self.failed = 0

    def _query(self, sql: str) -> pd.DataFrame:
        """执行 SQL 查询并返回 DataFrame。"""
        conn = sqlite3.connect(self.db_path)
        try:
            df = pd.read_sql(sql, conn)
            return df
        finally:
            conn.close()

    def _add_check(self, name: str, passed: bool, detail: str, expected: Any = None, actual: Any = None):
        """记录一条校验结果。"""
        status = "✅ 通过" if passed else "❌ 失败"
        self.checks.append({
            "name": name,
            "status": status,
            "passed": passed,
            "detail": detail,
            "expected": expected,
            "actual": actual,
        })
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        print(f"  [{status}] {name}: {detail}")

    def check_ods_vs_dwd(self) -> bool:
        """校验 ODS 行数与 DWD 行数。

        DWD 经过去重，行数应 ≤ ODS 行数。

        Returns:
            bool: 校验是否全部通过
        """
        print("\n  [校验] ODS ↔ DWD 行数校验...")

        try:
            ods_count = self._query("SELECT COUNT(*) as cnt FROM ods_user_behavior")["cnt"].iloc[0]
            dwd_count = self._query("SELECT COUNT(*) as cnt FROM dwd_user_behavior_detail")["cnt"].iloc[0]

            diff = ods_count - dwd_count
            self._add_check(
                "ODS→DWD行数",
                dwd_count <= ods_count,
                f"ODS: {ods_count:,} 行 → DWD: {dwd_count:,} 行 (差异: {diff:,} 行, 去重率: {diff/ods_count*100:.2f}%)" if ods_count > 0 else "数据为空",
                f"≤ {ods_count}",
                dwd_count,
            )
        except Exception as e:
            self._add_check("ODS→DWD行数", False, f"查询失败: {e}")

        # 校验必要列是否完整
        try:
            dwd_cols = self._query("PRAGMA table_info(dwd_user_behavior_detail)")
            required_cols = ["user_id", "product_id", "event_type", "price", "event_date"]
            actual_cols = dwd_cols["name"].tolist()
            missing = [c for c in required_cols if c not in actual_cols]
            self._add_check(
                "DWD必要列完整性",
                len(missing) == 0,
                f"缺少列: {missing}" if missing else f"列完整: {len(actual_cols)} 列",
            )
        except Exception as e:
            self._add_check("DWD必要列完整性", False, f"检查失败: {e}")

        return self.failed == 0

    def check_dwd_vs_dws(self) -> bool:
        """校验 DWD 明细汇总后与 DWS 各表的一致性。

        对每张 DWS 表的关键指标做交叉验证：
        1. 验证 DWS 表不为空
        2. 验证聚合指标在合理范围内
        3. 抽样校验 DWD 汇总值是否与 DWS 一致

        Returns:
            bool: 校验是否全部通过
        """
        print("\n  [校验] DWD ↔ DWS 汇总一致性...")

        # 验证各 DWS 表存在且不为空
        dws_tables = [
            "dws_traffic_daily",
            "dws_conversion_daily",
            "dws_user_daily",
            "dws_product_daily",
            "dws_category_daily",
            "dws_gmv_daily",
        ]

        for table in dws_tables:
            try:
                cnt = self._query(f"SELECT COUNT(*) as cnt FROM {table}")["cnt"].iloc[0]
                self._add_check(
                    f"{table} 非空检查",
                    cnt > 0,
                    f"{table}: {cnt} 行",
                    "> 0",
                    cnt,
                )
            except Exception as e:
                self._add_check(f"{table} 非空检查", False, f"查询失败: {e}")

        # 交叉验证：DWD purchase 事件汇总 GMV vs DWS GMV表汇总
        try:
            dwd_gmv = self._query("""
                SELECT ROUND(SUM(price * COALESCE(quantity, 1)), 2) as gmv
                FROM dwd_user_behavior_detail
                WHERE event_type = 'purchase'
            """)["gmv"].iloc[0] or 0

            dws_gmv = self._query("SELECT ROUND(SUM(gmv), 2) as gmv FROM dws_gmv_daily")["gmv"].iloc[0] or 0

            diff_pct = abs(dwd_gmv - dws_gmv) / dwd_gmv * 100 if dwd_gmv > 0 else 0
            passed = diff_pct < 1.0  # 允许 1% 误差
            self._add_check(
                "GMV交叉验证 (DWD vs DWS)",
                passed,
                f"DWD: ¥{dwd_gmv:,.2f} vs DWS: ¥{dws_gmv:,.2f} (差异: {diff_pct:.4f}%)",
                f"差异 < 1% (DWD: ¥{dwd_gmv:,.2f})",
                f"差异: {diff_pct:.4f}%",
            )
        except Exception as e:
            self._add_check("GMV交叉验证", False, f"校验失败: {e}")

        # 交叉验证：DWD 事件数 vs DWS 流量表 PV 汇总
        try:
            dwd_events = self._query("SELECT COUNT(*) as cnt FROM dwd_user_behavior_detail")["cnt"].iloc[0]
            dws_pv = self._query("SELECT SUM(pv) as pv FROM dws_traffic_daily")["pv"].iloc[0] or 0

            diff_pct = abs(dwd_events - dws_pv) / dwd_events * 100 if dwd_events > 0 else 0
            passed = diff_pct < 1.0
            self._add_check(
                "事件数交叉验证 (DWD vs DWS)",
                passed,
                f"DWD事件: {dwd_events:,} vs DWS PV汇总: {int(dws_pv):,} (差异: {diff_pct:.4f}%)",
                f"差异 < 1%",
                f"差异: {diff_pct:.4f}%",
            )
        except Exception as e:
            self._add_check("事件数交叉验证", False, f"校验失败: {e}")

        # 验证比率在合理范围
        try:
            conversion_check = self._query("""
                SELECT
                    MAX(view_to_cart_rate) as max_vc,
                    MAX(cart_to_purchase_rate) as max_cp,
                    MAX(view_to_purchase_rate) as max_vp
                FROM dws_conversion_daily
            """)
            max_vc = conversion_check["max_vc"].iloc[0] or 0
            max_cp = conversion_check["max_cp"].iloc[0] or 0
            max_vp = conversion_check["max_vp"].iloc[0] or 0

            rates_ok = (max_vc <= 100) and (max_cp <= 100) and (max_vp <= 100)
            self._add_check(
                "转化率范围验证",
                rates_ok,
                f"浏览→加购: {max_vc:.1f}%, 加购→购买: {max_cp:.1f}%, 浏览→购买: {max_vp:.1f}%",
                "所有转化率 ≤ 100%",
                f"max={max(max_vc, max_cp, max_vp):.1f}%",
            )
        except Exception as e:
            self._add_check("转化率范围验证", False, f"校验失败: {e}")

        return self.failed == 0

    def run(self) -> Dict[str, Any]:
        """执行完整的数据一致性校验。

        Returns:
            dict: 校验报告
        """
        print("\n" + "-" * 40)
        print("  Step 4: 数据一致性校验")
        print("-" * 40)

        try:
            self.check_ods_vs_dwd()
            self.check_dwd_vs_dws()

            total = self.passed + self.failed
            pass_rate = round(self.passed / total * 100, 1) if total > 0 else 0

            print(f"\n  🏆 校验结果: {self.passed}/{total} 通过 ({pass_rate}%)")

            return {
                "checks": self.checks,
                "passed": self.passed,
                "failed": self.failed,
                "total": total,
                "pass_rate": pass_rate,
                "overall_status": "✅ 全部通过" if self.failed == 0 else f"⚠️ {self.failed} 项未通过",
            }
        except Exception as e:
            print(f"  ❌ 数据校验异常: {e}")
            return {
                "checks": self.checks,
                "passed": self.passed,
                "failed": self.failed + 1,
                "total": self.passed + self.failed + 1,
                "pass_rate": 0,
                "overall_status": f"❌ 校验异常: {e}",
                "error": str(e),
            }
