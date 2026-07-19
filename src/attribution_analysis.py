"""
转化率归因分析模块（核心模块）
----------------------------
包含：
5.1 整体趋势分析：流量与转化率双Y轴趋势图，计算相关系数
5.2 渠道维度下钻：各渠道流量占比饼图，各渠道转化率对比柱状图
5.3 用户维度下钻：新老用户转化率对比，复购率趋势图
5.4 品类维度下钻：各品类转化率排名，高流量低转化品类识别
5.5 漏斗分析：浏览→加购→购买各环节转化率
5.6 输出归因结论和3-5条优化建议
"""

import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from scipy import stats
from typing import Dict, Any, List, Optional, Tuple
from io import BytesIO
import base64

from config import DB_PATH, PLOTLY_FONT_CONFIG, PLOTLY_TITLE_FONT_CONFIG, CHINESE_FONT


class AttributionAnalyzer:
    """转化率归因分析器：多维度下钻分析转化率波动的原因。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        self.charts: Dict[str, str] = {}        # 图表名称 → Base64 HTML
        self.conclusions: List[str] = []
        self.recommendations: List[str] = []
        self.correlation_result: Dict[str, Any] = {}

    def _query(self, sql: str) -> pd.DataFrame:
        """执行 SQL 查询。"""
        conn = sqlite3.connect(self.db_path)
        try:
            return pd.read_sql(sql, conn)
        finally:
            conn.close()

    def _fig_to_base64(self, fig: go.Figure) -> str:
        """将 Plotly 图表转为 Base64 编码的 HTML img 标签。"""
        buf = BytesIO()
        fig.write_image(buf, format="png", width=1000, height=550, scale=1.5)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        return f'<img src="data:image/png;base64,{img_b64}" style="width:100%;height:auto;" />'

    def _create_figure_layout(self, fig: go.Figure, title: str, x_title: str = "", y_title: str = ""):
        """统一的图表布局设置，确保中文正常显示。"""
        fig.update_layout(
            title=dict(text=title, font=PLOTLY_TITLE_FONT_CONFIG, x=0.5),
            font=PLOTLY_FONT_CONFIG,
            plot_bgcolor="#fafafa",
            paper_bgcolor="white",
            margin=dict(l=60, r=40, t=60, b=50),
            hovermode="x unified",
            legend=dict(
                font=dict(family=CHINESE_FONT, size=11),
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e0e0e0",
                borderwidth=1,
            ),
        )
        if x_title:
            fig.update_xaxes(title_text=x_title, title_font=dict(family=CHINESE_FONT, size=12))
        if y_title:
            fig.update_yaxes(title_text=y_title, title_font=dict(family=CHINESE_FONT, size=12))

    # ============================================
    # 5.1 整体趋势分析
    # ============================================
    def analyze_trend(self) -> Dict[str, Any]:
        """整体趋势分析：流量与转化率双Y轴趋势图 + 皮尔逊相关系数。

        Returns:
            dict: 包含图表Base64和相关分析结果
        """
        print("\n  [归因-5.1] 整体趋势分析...")

        df_conv = self._query("SELECT * FROM dws_conversion_daily ORDER BY date")
        df_gmv = self._query("SELECT * FROM dws_gmv_daily ORDER BY date")

        if df_conv.empty:
            print("    ⚠️ 无转化数据，跳过趋势分析")
            return {"error": "无数据"}

        # 双Y轴图：PV（柱状）+ 整体转化率（折线）
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # 获取PV数据
        if "total_events" in df_conv.columns:
            pv_col = "total_events"
        else:
            pv_col = "view_count"

        fig.add_trace(
            go.Bar(
                x=df_conv["date"],
                y=df_conv[pv_col],
                name="PV（浏览量）",
                marker_color="rgba(79, 129, 189, 0.7)",
                marker_line_color="rgba(79, 129, 189, 1)",
                marker_line_width=0.5,
            ),
            secondary_y=False,
        )

        fig.add_trace(
            go.Scatter(
                x=df_conv["date"],
                y=df_conv["overall_conversion_rate"],
                name="整体转化率 (%)",
                mode="lines+markers",
                line=dict(color="#e74c3c", width=2.5),
                marker=dict(size=6, color="#e74c3c"),
            ),
            secondary_y=True,
        )

        fig.update_yaxes(title_text="PV（浏览量）", secondary_y=False)
        fig.update_yaxes(title_text="转化率 (%)", secondary_y=True)
        self._create_figure_layout(fig, "流量与转化率趋势（双Y轴）")

        self.charts["trend_dual_axis"] = self._fig_to_base64(fig)

        # 皮尔逊相关系数
        if len(df_conv) >= 3:
            pv_series = df_conv[pv_col].values.astype(float)
            cr_series = df_conv["overall_conversion_rate"].values.astype(float)
            corr, p_value = stats.pearsonr(pv_series, cr_series)

            corr_desc = "正相关" if corr > 0 else "负相关"
            corr_strength = "强" if abs(corr) > 0.7 else ("中等" if abs(corr) > 0.4 else "弱")
            sig = "显著" if p_value < 0.05 else "不显著"

            self.correlation_result = {
                "coefficient": round(corr, 4),
                "p_value": round(p_value, 4),
                "direction": corr_desc,
                "strength": corr_strength,
                "significance": sig,
                "interpretation": f"流量与转化率呈{corr_strength}{corr_desc}（r={corr:.3f}, p={p_value:.4f}），相关性{sig}。",
            }

            print(f"    皮尔逊相关系数: r={corr:.3f}, p={p_value:.4f} ({corr_strength}{corr_desc}, {sig})")
        else:
            self.correlation_result = {"error": "数据量不足，无法计算相关系数"}

        return {
            "chart": self.charts.get("trend_dual_axis", ""),
            "correlation": self.correlation_result,
        }

    # ============================================
    # 5.2 渠道维度下钻
    # ============================================
    def analyze_channel(self) -> Dict[str, Any]:
        """渠道维度下钻：各渠道流量占比饼图 + 各渠道转化率对比柱状图。

        Returns:
            dict: 包含两张图表
        """
        print("\n  [归因-5.2] 渠道维度下钻...")

        # 从 DWD 直接查询渠道数据
        df_channel = self._query("""
            SELECT
                channel,
                COUNT(*) as pv,
                SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) as purchases,
                ROUND(
                    CAST(SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) * 100,
                    2
                ) as conversion_rate
            FROM dwd_user_behavior_detail
            GROUP BY channel
            ORDER BY pv DESC
        """)

        if df_channel.empty:
            print("    ⚠️ 无渠道数据")
            return {"error": "无渠道数据"}

        # 饼图：渠道流量占比
        fig_pie = go.Figure(data=[
            go.Pie(
                labels=df_channel["channel"],
                values=df_channel["pv"],
                textinfo="label+percent",
                textfont=dict(family=CHINESE_FONT, size=11),
                hole=0.35,
                marker=dict(
                    colors=px.colors.qualitative.Set2[:len(df_channel)],
                    line=dict(color="white", width=1.5),
                ),
            )
        ])
        self._create_figure_layout(fig_pie, "各渠道流量占比")
        self.charts["channel_pie"] = self._fig_to_base64(fig_pie)

        # 柱状图：各渠道转化率对比
        colors = ["#e74c3c" if rate < df_channel["conversion_rate"].mean() else "#27ae60"
                  for rate in df_channel["conversion_rate"]]

        fig_bar = go.Figure(data=[
            go.Bar(
                x=df_channel["channel"],
                y=df_channel["conversion_rate"],
                text=df_channel["conversion_rate"].apply(lambda x: f"{x:.1f}%"),
                textposition="outside",
                textfont=dict(family=CHINESE_FONT, size=11),
                marker_color=colors,
                marker_line_color="rgba(0,0,0,0.1)",
                marker_line_width=0.5,
            )
        ])
        fig_bar.add_hline(
            y=df_channel["conversion_rate"].mean(),
            line_dash="dash",
            line_color="gray",
            annotation_text=f"平均: {df_channel['conversion_rate'].mean():.1f}%",
            annotation_font=dict(family=CHINESE_FONT, size=10),
        )
        self._create_figure_layout(fig_bar, "各渠道转化率对比", "渠道", "转化率 (%)")
        self.charts["channel_bar"] = self._fig_to_base64(fig_bar)

        # 识别低转化渠道
        low_conv_channels = df_channel[
            df_channel["conversion_rate"] < df_channel["conversion_rate"].mean()
        ]["channel"].tolist()

        return {
            "channel_data": df_channel.to_dict("records"),
            "low_conversion_channels": low_conv_channels,
        }

    # ============================================
    # 5.3 用户维度下钻
    # ============================================
    def analyze_user(self) -> Dict[str, Any]:
        """用户维度下钻：新老用户转化率对比 + 复购率趋势。

        Returns:
            dict: 含图表和分析结果
        """
        print("\n  [归因-5.3] 用户维度下钻...")

        # 获取用户数据
        df_user = self._query("SELECT * FROM dws_user_daily ORDER BY date")
        df_dwd = self._query("SELECT user_id, MIN(event_date) as first_date FROM dwd_user_behavior_detail GROUP BY user_id")

        if df_user.empty:
            print("    ⚠️ 无用户数据")
            return {"error": "无用户数据"}

        # 新老用户转化率对比
        # 新用户：首次活跃在当天
        # 老用户：之前已经活跃过
        df_daily_users = self._query("""
            SELECT event_date, user_id, event_type
            FROM dwd_user_behavior_detail
        """)

        if not df_daily_users.empty:
            df_daily_users["event_date"] = pd.to_datetime(df_daily_users["event_date"]).dt.date
            first_dates = df_daily_users.groupby("user_id")["event_date"].min().to_dict()
            df_daily_users["user_type"] = df_daily_users.apply(
                lambda r: "新用户" if first_dates.get(r["user_id"]) == r["event_date"] else "老用户",
                axis=1,
            )

            new_old_stats = df_daily_users.groupby(["event_date", "user_type"]).agg(
                total=("user_id", "count"),
                purchases=("event_type", lambda x: (x == "purchase").sum()),
            ).reset_index()
            new_old_stats["conversion_rate"] = round(
                new_old_stats["purchases"] / new_old_stats["total"] * 100, 2
            )

            # 新老用户转化率趋势图
            fig_user = go.Figure()
            for utype, color in [("新用户", "#3498db"), ("老用户", "#e67e22")]:
                subset = new_old_stats[new_old_stats["user_type"] == utype]
                fig_user.add_trace(go.Scatter(
                    x=subset["event_date"],
                    y=subset["conversion_rate"],
                    name=utype,
                    mode="lines+markers",
                    line=dict(color=color, width=2.5),
                    marker=dict(size=6),
                ))

            self._create_figure_layout(fig_user, "新老用户转化率对比", "日期", "转化率 (%)")
            self.charts["user_conversion"] = self._fig_to_base64(fig_user)
        else:
            self.charts["user_conversion"] = ""

        # 复购率趋势图
        fig_repurchase = go.Figure()
        fig_repurchase.add_trace(go.Scatter(
            x=df_user["date"],
            y=df_user["repurchase_rate"],
            name="复购率",
            mode="lines+markers",
            line=dict(color="#8e44ad", width=2.5),
            marker=dict(size=6, color="#8e44ad"),
            fill="tozeroy",
            fillcolor="rgba(142, 68, 173, 0.1)",
        ))
        self._create_figure_layout(fig_repurchase, "复购率趋势", "日期", "复购率 (%)")
        self.charts["repurchase_trend"] = self._fig_to_base64(fig_repurchase)

        avg_repurchase = df_user["repurchase_rate"].mean() if not df_user.empty else 0
        avg_retention = df_user["retention_rate_next_day"].mean() if not df_user.empty else 0

        return {
            "avg_repurchase_rate": round(avg_repurchase, 2),
            "avg_retention_rate": round(avg_retention, 2),
        }

    # ============================================
    # 5.4 品类维度下钻
    # ============================================
    def analyze_category(self) -> Dict[str, Any]:
        """品类维度下钻：各品类转化率排名 + 高流量低转化品类识别。

        Returns:
            dict: 含品类分析图表和数据
        """
        print("\n  [归因-5.4] 品类维度下钻...")

        df_cat = self._query("""
            SELECT
                category,
                SUM(total_events) as total,
                SUM(purchase_count) as purchases,
                SUM(gmv) as gmv,
                ROUND(CAST(SUM(purchase_count) AS FLOAT) / SUM(total_events) * 100, 2) as conversion_rate
            FROM dws_category_daily
            GROUP BY category
            ORDER BY total DESC
        """)

        if df_cat.empty:
            print("    ⚠️ 无品类数据")
            return {"error": "无品类数据"}

        # 各品类转化率排名柱状图
        df_cat_sorted = df_cat.sort_values("conversion_rate", ascending=True)

        fig_cat = go.Figure(data=[
            go.Bar(
                y=df_cat_sorted["category"],
                x=df_cat_sorted["conversion_rate"],
                text=df_cat_sorted["conversion_rate"].apply(lambda x: f"{x:.1f}%"),
                textposition="outside",
                textfont=dict(family=CHINESE_FONT, size=11),
                orientation="h",
                marker_color=[
                    "#e74c3c" if rate < df_cat["conversion_rate"].mean() else "#27ae60"
                    for rate in df_cat_sorted["conversion_rate"]
                ],
                marker_line_color="rgba(0,0,0,0.1)",
                marker_line_width=0.5,
            )
        ])
        self._create_figure_layout(fig_cat, "各品类转化率排名", "转化率 (%)", "品类")
        self.charts["category_ranking"] = self._fig_to_base64(fig_cat)

        # 高流量低转化品类识别
        pv_median = df_cat["total"].median()
        cr_median = df_cat["conversion_rate"].median()
        high_traffic_low_conv = df_cat[
            (df_cat["total"] > pv_median) & (df_cat["conversion_rate"] < cr_median)
        ]

        if not high_traffic_low_conv.empty:
            categories_str = ", ".join(high_traffic_low_conv["category"].tolist())
            self.conclusions.append(
                f"高流量低转化品类: {categories_str}，这些品类流量大但转化率低于中位数({cr_median:.1f}%)，"
                f"建议优化商品详情页或调整定价策略。"
            )

        return {
            "category_data": df_cat.to_dict("records"),
            "high_traffic_low_conversion": high_traffic_low_conv["category"].tolist(),
        }

    # ============================================
    # 5.5 漏斗分析
    # ============================================
    def analyze_funnel(self) -> Dict[str, Any]:
        """漏斗分析：浏览→加购→购买各环节转化率。

        Returns:
            dict: 含漏斗图和各环节数据
        """
        print("\n  [归因-5.5] 漏斗分析...")

        df_funnel = self._query("""
            SELECT
                SUM(CASE WHEN event_type='view' THEN 1 ELSE 0 END) as views,
                SUM(CASE WHEN event_type='cart' THEN 1 ELSE 0 END) as carts,
                SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) as purchases
            FROM dwd_user_behavior_detail
        """)

        if df_funnel.empty:
            print("    ⚠️ 无漏斗数据")
            return {"error": "无数据"}

        views = int(df_funnel["views"].iloc[0])
        carts = int(df_funnel["carts"].iloc[0])
        purchases = int(df_funnel["purchases"].iloc[0])

        # 各环节转化率
        v_to_c = round(carts / views * 100, 2) if views > 0 else 0
        c_to_p = round(purchases / carts * 100, 2) if carts > 0 else 0
        v_to_p = round(purchases / views * 100, 2) if views > 0 else 0

        # 漏斗图
        fig_funnel = go.Figure(data=[
            go.Funnel(
                y=["浏览 (View)", "加购 (Cart)", "购买 (Purchase)"],
                x=[views, carts, purchases],
                textinfo="value+percent previous",
                textfont=dict(family=CHINESE_FONT, size=14),
                marker=dict(
                    color=["#3498db", "#f39c12", "#e74c3c"],
                    line=dict(color="white", width=2),
                ),
                connector=dict(line=dict(color="gray", width=1, dash="dot")),
            )
        ])
        self._create_figure_layout(fig_funnel, "用户行为漏斗：浏览 → 加购 → 购买")
        self.charts["funnel"] = self._fig_to_base64(fig_funnel)

        funnel_data = {
            "views": views,
            "carts": carts,
            "purchases": purchases,
            "view_to_cart_rate": v_to_c,
            "cart_to_purchase_rate": c_to_p,
            "view_to_purchase_rate": v_to_p,
        }

        # 漏斗诊断
        if v_to_c < 5:
            self.conclusions.append(
                f"浏览→加购转化率仅 {v_to_c}%，严重偏低。可能是商品吸引力不足、价格不具竞争力、"
                f"或商品信息不完整（缺少图片、描述、评价）。"
            )
            self.recommendations.append(
                f"优化商品详情页——补充高质量图片、突出卖点描述、展示真实用户评价，目标将浏览→加购率提升至5%以上。"
            )

        if c_to_p < 30:
            self.conclusions.append(
                f"加购→购买转化率仅 {c_to_p}%，购物车放弃率偏高。可能存在结算流程复杂、运费过高、"
                f"或缺乏紧迫感（如限时优惠）。"
            )
            self.recommendations.append(
                f"简化结算流程——减少步骤、提供多种支付方式、设置购物车提醒和限时折扣，目标将加购→购买率提升至30%以上。"
            )

        return funnel_data

    # ============================================
    # 5.6 归因结论与建议
    # ============================================
    def generate_conclusions(self) -> Dict[str, Any]:
        """汇总所有分析结果，生成归因结论和优化建议。

        Returns:
            dict: 归因结论列表和建议列表
        """
        print("\n  [归因-5.6] 生成归因结论与优化建议...")

        # 加入相关系数结论
        if self.correlation_result and "coefficient" in self.correlation_result:
            corr = self.correlation_result
            if abs(corr["coefficient"]) > 0.4:
                self.conclusions.append(
                    f"流量与转化率呈{corr['strength']}{corr['direction']}（r={corr['coefficient']:.3f}），"
                    f"相关性{corr['significance']}。{corr['interpretation']}"
                )

        # 确保至少有 3 条建议
        default_recommendations = [
            "建立数据驱动运营体系——每日监控核心指标看板，设定转化率预警线，异常波动时自动触发归因分析。",
            "实施A/B测试——对关键页面（首页、商品详情页、购物车页）进行持续优化实验，数据验证后再全量上线。",
            "强化用户生命周期管理——针对新用户、活跃用户、沉默用户设计差异化触达策略，提升用户LTV。",
            "优化流量结构——分析各渠道ROI，加大对高转化渠道的投放，减少低效渠道的预算浪费。",
            "完善商品运营体系——建立爆款孵化机制，定期淘汰低效SKU，提升整体动销率和库存周转。",
        ]

        # 如果已有建议不足5条，从默认建议中补充
        existing_count = len(self.recommendations)
        for rec in default_recommendations:
            if len(self.recommendations) >= 5:
                break
            if rec not in self.recommendations:
                self.recommendations.append(rec)

        print(f"    生成 {len(self.conclusions)} 条结论, {len(self.recommendations)} 条建议")

        return {
            "conclusions": self.conclusions,
            "recommendations": self.recommendations,
        }

    # ============================================
    # 主入口
    # ============================================
    def run(self) -> Dict[str, Any]:
        """执行完整的转化率归因分析。

        Returns:
            dict: 包含所有图表Base64、数据和分析结论
        """
        print("\n" + "-" * 40)
        print("  Step 5: 转化率归因分析（核心模块）")
        print("-" * 40)

        results = {}

        try:
            # 5.1 整体趋势
            results["trend"] = self.analyze_trend()
        except Exception as e:
            print(f"    ❌ 趋势分析失败: {e}")
            results["trend"] = {"error": str(e)}

        try:
            # 5.2 渠道下钻
            results["channel"] = self.analyze_channel()
        except Exception as e:
            print(f"    ❌ 渠道分析失败: {e}")
            results["channel"] = {"error": str(e)}

        try:
            # 5.3 用户下钻
            results["user"] = self.analyze_user()
        except Exception as e:
            print(f"    ❌ 用户分析失败: {e}")
            results["user"] = {"error": str(e)}

        try:
            # 5.4 品类下钻
            results["category"] = self.analyze_category()
        except Exception as e:
            print(f"    ❌ 品类分析失败: {e}")
            results["category"] = {"error": str(e)}

        try:
            # 5.5 漏斗分析
            results["funnel"] = self.analyze_funnel()
        except Exception as e:
            print(f"    ❌ 漏斗分析失败: {e}")
            results["funnel"] = {"error": str(e)}

        try:
            # 5.6 归因结论
            results["attribution"] = self.generate_conclusions()
        except Exception as e:
            print(f"    ❌ 归因结论生成失败: {e}")
            results["attribution"] = {"conclusions": [], "recommendations": ["自动分析失败，请人工检查数据。"]}

        # 汇总
        results["charts"] = self.charts
        results["chart_count"] = len(self.charts)

        print(f"\n  ✅ 归因分析完成: 生成 {len(self.charts)} 张图表, {len(self.conclusions)} 条结论")
        return results
