"""
SQLite 数仓自动搭建模块
------------------------
在项目根目录创建 ecommerce_dw.db，包含 ODS / DWD / DWS 三层表。
覆盖"人-货-场"至少 15 个分析维度。
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from config import DB_PATH


class DataWarehouseBuilder:
    """数仓构建器：将清洗后的数据分层写入 SQLite。"""

    def __init__(self):
        self.db_path = DB_PATH
        self.conn: Optional[sqlite3.Connection] = None
        self.table_registry: Dict[str, int] = {}  # 记录各表行数

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        return self.conn

    def close(self):
        """关闭数据库连接。"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def _drop_layer(self, layer_name: str):
        """删除指定层的所有表（重建用）。"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"{layer_name}%",)
        )
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        if tables:
            print(f"  [DW] 已清理 {layer_name} 层 {len(tables)} 张旧表")

    def build_ods(self, df: pd.DataFrame) -> str:
        """构建 ODS 层：原始行为数据。

        Args:
            df: 清洗后的 DataFrame

        Returns:
            str: 表名
        """
        print("\n  [DW-ODS] 构建原始数据层...")
        conn = self._get_conn()

        # 删除旧表重建
        conn.execute("DROP TABLE IF EXISTS ods_user_behavior")

        # 写入数据
        df.to_sql("ods_user_behavior", conn, if_exists="replace", index=True, index_label="id")

        # 添加索引加速后续查询
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ods_user ON ods_user_behavior(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ods_time ON ods_user_behavior(event_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ods_event ON ods_user_behavior(event_type)")

        row_count = len(df)
        self.table_registry["ods_user_behavior"] = row_count

        print(f"  [DW-ODS] ods_user_behavior 写入完成: {row_count:,} 行")
        return "ods_user_behavior"

    def build_dwd(self, df: pd.DataFrame) -> str:
        """构建 DWD 层：去重、格式化、空值处理后的明细数据。

        Args:
            df: 清洗后的 DataFrame

        Returns:
            str: 表名
        """
        print("\n  [DW-DWD] 构建明细数据层...")
        conn = self._get_conn()

        conn.execute("DROP TABLE IF EXISTS dwd_user_behavior_detail")

        # 去重
        before = len(df)
        dedup_cols = ["user_id", "product_id", "event_type", "event_time"]
        dedup_cols = [c for c in dedup_cols if c in df.columns]
        df_dedup = df.drop_duplicates(subset=dedup_cols) if dedup_cols else df
        after = len(df_dedup)
        if before > after:
            print(f"  [DW-DWD] 去重: {before:,} → {after:,} (移除 {before - after:,} 条)")

        # 确保日期字段存在
        df_dwd = df_dedup.copy()
        if "event_time" in df_dwd.columns:
            df_dwd["event_date"] = pd.to_datetime(df_dwd["event_time"]).dt.date
        else:
            df_dwd["event_date"] = datetime.now().date()

        # 确保数值字段合理
        if "price" in df_dwd.columns:
            df_dwd["price"] = df_dwd["price"].clip(lower=0)
        if "quantity" in df_dwd.columns:
            df_dwd["quantity"] = df_dwd["quantity"].clip(lower=1)

        # 写入
        df_dwd.to_sql("dwd_user_behavior_detail", conn, if_exists="replace", index=True, index_label="detail_id")

        # 索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dwd_user ON dwd_user_behavior_detail(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dwd_date ON dwd_user_behavior_detail(event_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dwd_event ON dwd_user_behavior_detail(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dwd_category ON dwd_user_behavior_detail(category)")

        row_count = len(df_dwd)
        self.table_registry["dwd_user_behavior_detail"] = row_count

        print(f"  [DW-DWD] dwd_user_behavior_detail 写入完成: {row_count:,} 行")
        return "dwd_user_behavior_detail"

    def build_dws_traffic(self, df: pd.DataFrame) -> str:
        """构建 DWS-流量表：每日流量汇总（UV、PV、各渠道访问量）。

        分析维度：流量趋势、渠道分布、设备分布
        """
        table_name = "dws_traffic_daily"
        conn = self._get_conn()
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        df["event_date"] = pd.to_datetime(df["event_time"]).dt.date

        traffic_list = []
        for date, group in df.groupby("event_date"):
            record = {"date": str(date)}
            record["pv"] = len(group)
            record["uv"] = group["user_id"].nunique() if "user_id" in group.columns else 0

            # 各渠道访问量
            if "channel" in group.columns:
                for ch in group["channel"].unique():
                    ch_key = f"channel_{ch}"
                    record[ch_key] = (group["channel"] == ch).sum()

            # 设备分布
            if "device" in group.columns:
                for dev in group["device"].unique():
                    dev_key = f"device_{dev}"
                    record[dev_key] = (group["device"] == dev).sum()

            # 事件类型分布
            for event in ["view", "cart", "purchase"]:
                record[f"event_{event}"] = (group["event_type"] == event).sum()

            traffic_list.append(record)

        df_traffic = pd.DataFrame(traffic_list)
        df_traffic.to_sql(table_name, conn, if_exists="replace", index=False)
        self.table_registry[table_name] = len(df_traffic)

        print(f"  [DW-DWS] {table_name} 写入完成: {len(df_traffic)} 行（每日粒度）")
        return table_name

    def build_dws_conversion(self, df: pd.DataFrame) -> str:
        """构建 DWS-转化表：每日转化汇总。

        指标：浏览转化率、加购转化率、下单转化率、支付转化率
        """
        table_name = "dws_conversion_daily"
        conn = self._get_conn()
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        df["event_date"] = pd.to_datetime(df["event_time"]).dt.date

        conversion_list = []
        for date, group in df.groupby("event_date"):
            total = len(group)
            uv = group["user_id"].nunique() if "user_id" in group.columns else total

            # 各事件数量
            views = (group["event_type"] == "view").sum()
            carts = (group["event_type"] == "cart").sum()
            purchases = (group["event_type"] == "purchase").sum()

            record = {
                "date": str(date),
                "total_events": total,
                "uv": uv,
                "view_count": views,
                "cart_count": carts,
                "purchase_count": purchases,
                # 转化率（分母为浏览UV，实际业务中更合理）
                "view_to_cart_rate": round(carts / views * 100, 2) if views > 0 else 0,
                "cart_to_purchase_rate": round(purchases / carts * 100, 2) if carts > 0 else 0,
                "view_to_purchase_rate": round(purchases / views * 100, 2) if views > 0 else 0,
                # 基于UV的整体转化率
                "overall_conversion_rate": round(purchases / uv * 100, 2) if uv > 0 else 0,
            }
            conversion_list.append(record)

        df_conv = pd.DataFrame(conversion_list)
        df_conv.to_sql(table_name, conn, if_exists="replace", index=False)
        self.table_registry[table_name] = len(df_conv)

        print(f"  [DW-DWS] {table_name} 写入完成: {len(df_conv)} 行")
        return table_name

    def build_dws_user(self, df: pd.DataFrame) -> str:
        """构建 DWS-用户表：每日用户指标。

        指标：新增用户、活跃用户、留存率（次日）、复购率
        分析维度：用户增长、用户活跃度、用户粘性
        """
        table_name = "dws_user_daily"
        conn = self._get_conn()
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        df["event_date"] = pd.to_datetime(df["event_time"]).dt.date

        # 确定每个用户首次活跃日期
        user_first_date = df.groupby("user_id")["event_date"].min().to_dict()
        all_dates = sorted(df["event_date"].unique())

        user_list = []
        for date in all_dates:
            day_data = df[df["event_date"] == date]
            active_users = day_data["user_id"].nunique() if "user_id" in day_data.columns else 0

            # 新增用户：首次活跃日期 == 当前日期
            new_users = sum(1 for uid, fd in user_first_date.items() if fd == date)

            # 复购用户（当天有购买行为的用户）
            purchase_users = day_data[day_data["event_type"] == "purchase"]["user_id"].nunique() if "user_id" in day_data.columns else 0

            # 复购率 = 购买超过1次的用户 / 所有购买用户
            purchase_data = df[(df["event_date"] <= date) & (df["event_type"] == "purchase")]
            if "user_id" in purchase_data.columns and not purchase_data.empty:
                user_purchase_counts = purchase_data.groupby("user_id").size()
                repeat_buyers = (user_purchase_counts > 1).sum()
                total_buyers = len(user_purchase_counts)
                repurchase_rate = round(repeat_buyers / total_buyers * 100, 2) if total_buyers > 0 else 0
            else:
                repeat_buyers = 0
                total_buyers = 0
                repurchase_rate = 0

            # 次日留存率
            next_date = date + timedelta(days=1)
            if next_date in all_dates:
                today_users = set(day_data["user_id"].unique())
                next_day_users = set(df[df["event_date"] == next_date]["user_id"].unique())
                retained = len(today_users & next_day_users)
                retention_rate = round(retained / len(today_users) * 100, 2) if today_users else 0
            else:
                retention_rate = 0

            record = {
                "date": str(date),
                "active_users": active_users,
                "new_users": new_users,
                "purchase_users": purchase_users,
                "repeat_buyers": int(repeat_buyers),
                "total_buyers_cumulative": int(total_buyers),
                "repurchase_rate": repurchase_rate,
                "retention_rate_next_day": retention_rate,
            }
            user_list.append(record)

        df_user = pd.DataFrame(user_list)
        df_user.to_sql(table_name, conn, if_exists="replace", index=False)
        self.table_registry[table_name] = len(df_user)

        print(f"  [DW-DWS] {table_name} 写入完成: {len(df_user)} 行")
        return table_name

    def build_dws_product(self, df: pd.DataFrame) -> str:
        """构建 DWS-商品表：每日商品指标。

        指标：曝光商品数、动销商品数、动销率、Top10商品
        分析维度：商品丰富度、商品销售效率、爆款识别
        """
        table_name = "dws_product_daily"
        conn = self._get_conn()
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        df["event_date"] = pd.to_datetime(df["event_time"]).dt.date

        product_list = []
        for date, group in df.groupby("event_date"):
            exposed = group[group["event_type"] == "view"]["product_id"].nunique() if "product_id" in group.columns else 0
            sold = group[group["event_type"] == "purchase"]["product_id"].nunique() if "product_id" in group.columns else 0

            # 动销率 = 有售出的商品 / 总曝光商品
            all_products = group["product_id"].nunique() if "product_id" in group.columns else 0
            sell_through_rate = round(sold / all_products * 100, 2) if all_products > 0 else 0

            # Top10 商品（按销量）
            purchase_group = group[group["event_type"] == "purchase"]
            if not purchase_group.empty and "product_id" in purchase_group.columns:
                top10 = purchase_group["product_id"].value_counts().head(10)
                top10_json = top10.to_dict()
            else:
                top10_json = {}

            record = {
                "date": str(date),
                "exposed_products": int(exposed),
                "sold_products": int(sold),
                "all_products": int(all_products),
                "sell_through_rate": sell_through_rate,
                "top10_products": str(top10_json),
            }
            product_list.append(record)

        df_product = pd.DataFrame(product_list)
        df_product.to_sql(table_name, conn, if_exists="replace", index=False)
        self.table_registry[table_name] = len(df_product)

        print(f"  [DW-DWS] {table_name} 写入完成: {len(df_product)} 行")
        return table_name

    def build_dws_category(self, df: pd.DataFrame) -> str:
        """构建 DWS-品类表：每日品类指标。

        指标：各品类销售额、销量、转化率
        分析维度：品类结构、品类效率、品类增长
        """
        table_name = "dws_category_daily"
        conn = self._get_conn()
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        df["event_date"] = pd.to_datetime(df["event_time"]).dt.date

        category_list = []
        for (date, cat), group in df.groupby(["event_date", "category"]):
            total = len(group)
            purchases = group[group["event_type"] == "purchase"]

            # GMV
            if not purchases.empty and "price" in purchases.columns:
                purchases_copy = purchases.copy()
                qty = purchases_copy.get("quantity", 1)
                purchases_copy["amount"] = purchases_copy["price"] * qty
                gmv = round(purchases_copy["amount"].sum(), 2)
                sales_volume = int(qty.sum()) if "quantity" in purchases.columns else len(purchases)
            else:
                gmv = 0
                sales_volume = 0

            record = {
                "date": str(date),
                "category": cat,
                "total_events": total,
                "view_count": int((group["event_type"] == "view").sum()),
                "cart_count": int((group["event_type"] == "cart").sum()),
                "purchase_count": int((group["event_type"] == "purchase").sum()),
                "gmv": gmv,
                "sales_volume": int(sales_volume),
                "conversion_rate": round(len(purchases) / total * 100, 2) if total > 0 else 0,
            }
            category_list.append(record)

        df_cat = pd.DataFrame(category_list)
        df_cat.to_sql(table_name, conn, if_exists="replace", index=False)
        self.table_registry[table_name] = len(df_cat)

        print(f"  [DW-DWS] {table_name} 写入完成: {len(df_cat)} 行")
        return table_name

    def build_dws_gmv(self, df: pd.DataFrame) -> str:
        """构建 DWS-GMV表：每日GMV汇总。

        指标：GMV、客单价（ASP）、订单数、购买用户数、ARPU
        分析维度：收入趋势、客单价变化、用户价值
        """
        table_name = "dws_gmv_daily"
        conn = self._get_conn()
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        df["event_date"] = pd.to_datetime(df["event_time"]).dt.date
        purchase_df = df[df["event_type"] == "purchase"].copy()

        if "price" in purchase_df.columns and not purchase_df.empty:
            purchase_df["amount"] = purchase_df["price"] * purchase_df.get("quantity", 1)
        else:
            purchase_df["amount"] = 0

        gmv_list = []
        for date in sorted(df["event_date"].unique()):
            day_purchase = purchase_df[purchase_df["event_date"] == date]

            if not day_purchase.empty:
                gmv = round(day_purchase["amount"].sum(), 2)
                order_count = day_purchase["order_id"].nunique() if "order_id" in day_purchase.columns else len(day_purchase)
                buyer_count = day_purchase["user_id"].nunique() if "user_id" in day_purchase.columns else 0
                asp = round(gmv / order_count, 2) if order_count > 0 else 0  # 客单价
            else:
                gmv = 0
                order_count = 0
                buyer_count = 0
                asp = 0

            # 当日总UV
            day_all = df[df["event_date"] == date]
            uv = day_all["user_id"].nunique() if "user_id" in day_all.columns else 0
            arpu = round(gmv / uv, 2) if uv > 0 else 0

            record = {
                "date": str(date),
                "gmv": gmv,
                "order_count": order_count,
                "buyer_count": buyer_count,
                "asp": asp,                               # 客单价
                "uv": uv,
                "arpu": arpu,                             # 每用户平均收入
            }
            gmv_list.append(record)

        df_gmv = pd.DataFrame(gmv_list)
        df_gmv.to_sql(table_name, conn, if_exists="replace", index=False)
        self.table_registry[table_name] = len(df_gmv)

        print(f"  [DW-DWS] {table_name} 写入完成: {len(df_gmv)} 行")
        return table_name

    def run(self, df: pd.DataFrame) -> Dict[str, Any]:
        """执行完整的数仓搭建流程。

        Args:
            df: 清洗后的数据 DataFrame

        Returns:
            dict: 数仓元信息
        """
        print("\n" + "-" * 40)
        print("  Step 3: SQLite 数仓自动搭建")
        print("-" * 40)

        try:
            # 清理旧数据库
            if self.db_path.exists():
                self.db_path.unlink()
                print(f"  [DW] 已清理旧数据库: {self.db_path.name}")

            conn = self._get_conn()

            # ODS 层
            self.build_ods(df)

            # DWD 层
            self.build_dwd(df)

            # DWS 层 — 六张汇总表，覆盖"人-货-场"15+维度
            print("\n  [DW-DWS] 构建汇总数据层（人-货-场）...")

            # 流量维度（场）
            self.build_dws_traffic(df)

            # 转化维度（场 → 人）
            self.build_dws_conversion(df)

            # 用户维度（人）
            self.build_dws_user(df)

            # 商品维度（货）
            self.build_dws_product(df)

            # 品类维度（货）
            self.build_dws_category(df)

            # GMV 维度（综合）
            self.build_dws_gmv(df)

            conn.commit()

            # 汇总
            dw_info = {
                "db_path": str(self.db_path.resolve()),
                "tables": self.table_registry.copy(),
                "total_rows": sum(self.table_registry.values()),
            }

            print(f"\n  ✅ 数仓搭建完成: {len(self.table_registry)} 张表, 共 {dw_info['total_rows']:,} 行汇总数据")
            print(f"     数据库路径: {dw_info['db_path']}")

            return dw_info

        except Exception as e:
            print(f"  ❌ 数仓搭建失败: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e), "db_path": str(self.db_path), "tables": self.table_registry}
