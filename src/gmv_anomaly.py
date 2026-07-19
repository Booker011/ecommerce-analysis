"""
GMV异常波动检测与AI归因模块
----------------------------
基于3-sigma和同比变化率自动检测GMV异常点，
构建"流量端→转化端→客单价"三层归因框架。
有 DeepSeek API Key → AI归因总结；无 → 规则引擎降级。
"""

import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from typing import Dict, Any, List, Optional
from io import BytesIO
import base64
import json

from config import (
    DB_PATH, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, AI_ENABLED,
    GMV_SIGMA_THRESHOLD, GMV_YOY_THRESHOLD,
    PLOTLY_FONT_CONFIG, PLOTLY_TITLE_FONT_CONFIG, CHINESE_FONT,
)


class GMVAnomalyDetector:
    """GMV异常检测器：检测异常点并做三层归因。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        self.anomalies: List[Dict[str, Any]] = []
        self.attribution_paths: List[Dict[str, Any]] = []
        self.ai_summary: str = ""
        self.ai_mode: str = "规则引擎"  # 实际使用的模式
        self.chart: str = ""

    def _query(self, sql: str) -> pd.DataFrame:
        """执行 SQL 查询。"""
        conn = sqlite3.connect(self.db_path)
        try:
            return pd.read_sql(sql, conn)
        finally:
            conn.close()

    def _fig_to_base64(self, fig: go.Figure) -> str:
        """Plotly 图 → Base64。"""
        buf = BytesIO()
        fig.write_image(buf, format="png", width=1000, height=500, scale=1.5)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        return f'<img src="data:image/png;base64,{img_b64}" style="width:100%;height:auto;" />'

    # ============================================
    # 6.1 异常检测
    # ============================================
    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """基于3-sigma和同比变化率检测GMV异常点。

        - 3-sigma：GMV偏离均值超过3个标准差
        - 同比变化率：GMV日环比变化超过阈值（默认30%）

        Returns:
            list: 异常点列表
        """
        print("\n  [GMV-6.1] 异常检测...")

        df = self._query("SELECT * FROM dws_gmv_daily ORDER BY date")
        if df.empty or len(df) < 3:
            print("    ⚠️ 数据量不足，无法进行异常检测")
            return []

        gmv_series = df["gmv"].values
        mean_gmv = np.mean(gmv_series)
        std_gmv = np.std(gmv_series)
        upper_bound = mean_gmv + GMV_SIGMA_THRESHOLD * std_gmv
        lower_bound = max(0, mean_gmv - GMV_SIGMA_THRESHOLD * std_gmv)

        print(f"    GMV均值: ¥{mean_gmv:,.0f}, σ: ¥{std_gmv:,.0f}")
        print(f"    3σ区间: [¥{lower_bound:,.0f}, ¥{upper_bound:,.0f}]")

        # 计算日环比变化率
        df["prev_gmv"] = df["gmv"].shift(1)
        df["change_rate"] = (df["gmv"] - df["prev_gmv"]) / df["prev_gmv"].replace(0, np.nan)
        df["change_rate"] = df["change_rate"].fillna(0)

        anomalies = []
        for _, row in df.iterrows():
            date = row["date"]
            gmv = row["gmv"]
            change_rate = row["change_rate"] if not pd.isna(row["change_rate"]) else 0

            reasons = []

            # 3-sigma检测
            if gmv > upper_bound:
                reasons.append(f"GMV ¥{gmv:,.0f} 超过上界 ¥{upper_bound:,.0f}（+{(gmv-mean_gmv)/std_gmv:.1f}σ）")
            elif gmv < lower_bound:
                reasons.append(f"GMV ¥{gmv:,.0f} 低于下界 ¥{lower_bound:,.0f}（{(gmv-mean_gmv)/std_gmv:.1f}σ）")

            # 同比变化率检测
            if abs(change_rate) > GMV_YOY_THRESHOLD:
                direction = "上涨" if change_rate > 0 else "下跌"
                reasons.append(f"日环比{direction} {abs(change_rate)*100:.1f}%（超过{GMV_YOY_THRESHOLD*100:.0f}%阈值）")

            if reasons:
                anomalies.append({
                    "date": date,
                    "gmv": round(gmv, 2),
                    "mean_gmv": round(mean_gmv, 2),
                    "std_gmv": round(std_gmv, 2),
                    "sigma_deviation": round((gmv - mean_gmv) / std_gmv, 2) if std_gmv > 0 else 0,
                    "change_rate": round(change_rate * 100, 2),
                    "reasons": reasons,
                    "type": "异常高" if gmv > mean_gmv else "异常低",
                })

        # 标记相邻异常日（可能是同一事件导致的连续异常）
        if len(anomalies) >= 2:
            for i in range(len(anomalies) - 1):
                if anomalies[i]["type"] == anomalies[i + 1]["type"]:
                    anomalies[i]["is_consecutive"] = True
                    anomalies[i + 1]["is_consecutive"] = True

        self.anomalies = anomalies
        print(f"    检测到 {len(anomalies)} 个异常点")

        # 生成异常检测图表
        self._create_anomaly_chart(df)

        return anomalies

    def _create_anomaly_chart(self, df: pd.DataFrame):
        """生成GMV异常检测可视化图表。"""
        mean_gmv = df["gmv"].mean()
        std_gmv = df["gmv"].std()
        upper = mean_gmv + GMV_SIGMA_THRESHOLD * std_gmv
        lower = max(0, mean_gmv - GMV_SIGMA_THRESHOLD * std_gmv)

        fig = go.Figure()

        # GMV曲线
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["gmv"],
            name="GMV",
            mode="lines+markers",
            line=dict(color="#2c3e50", width=2),
            marker=dict(size=7, color="#2c3e50"),
        ))

        # 均值线
        fig.add_trace(go.Scatter(
            x=df["date"], y=[mean_gmv] * len(df),
            name=f"均值 (¥{mean_gmv:,.0f})",
            mode="lines",
            line=dict(color="#3498db", width=1.5, dash="dash"),
        ))

        # 上界
        fig.add_trace(go.Scatter(
            x=df["date"], y=[upper] * len(df),
            name=f"3σ上界 (¥{upper:,.0f})",
            mode="lines",
            line=dict(color="#e74c3c", width=1, dash="dot"),
        ))

        # 下界
        fig.add_trace(go.Scatter(
            x=df["date"], y=[lower] * len(df),
            name=f"3σ下界 (¥{lower:,.0f})",
            mode="lines",
            line=dict(color="#e74c3c", width=1, dash="dot"),
        ))

        # 标注异常点
        anomaly_dates = [a["date"] for a in self.anomalies]
        anomaly_vals = [a["gmv"] for a in self.anomalies]
        anomaly_texts = [f"{a['date']}<br>GMV: ¥{a['gmv']:,.0f}<br>{'; '.join(a['reasons'])}" for a in self.anomalies]

        fig.add_trace(go.Scatter(
            x=anomaly_dates, y=anomaly_vals,
            name="异常点",
            mode="markers",
            marker=dict(size=14, color="#e74c3c", symbol="x", line=dict(width=2, color="darkred")),
            text=anomaly_texts,
            hoverinfo="text",
        ))

        fig.update_layout(
            title=dict(text="GMV异常波动检测（3σ + 同比变化率）", font=PLOTLY_TITLE_FONT_CONFIG, x=0.5),
            font=PLOTLY_FONT_CONFIG,
            plot_bgcolor="#fafafa",
            paper_bgcolor="white",
            margin=dict(l=60, r=40, t=60, b=50),
            hovermode="closest",
            legend=dict(font=dict(family=CHINESE_FONT, size=10)),
        )
        fig.update_xaxes(title_text="日期")
        fig.update_yaxes(title_text="GMV (¥)")

        self.chart = self._fig_to_base64(fig)

    # ============================================
    # 6.2 三层归因框架
    # ============================================
    def attribute_anomalies(self) -> List[Dict[str, Any]]:
        """三层归因框架：流量端 → 转化端 → 客单价。

        对每个异常点，对比其与前7日均值的差异：
        1. 流量端：UV变化、PV变化
        2. 转化端：整体转化率变化
        3. 客单价端：ASP变化

        Returns:
            list: 每个异常点的归因路径
        """
        print("\n  [GMV-6.2] 三层归因分析...")

        if not self.anomalies:
            print("    无异常点，跳过归因")
            return []

        # 获取基础数据
        df_gmv = self._query("SELECT * FROM dws_gmv_daily ORDER BY date")
        df_conv = self._query("SELECT * FROM dws_conversion_daily ORDER BY date")
        df_traffic = self._query("SELECT * FROM dws_traffic_daily ORDER BY date")

        df_gmv["date"] = pd.to_datetime(df_gmv["date"])
        if not df_conv.empty:
            df_conv["date"] = pd.to_datetime(df_conv["date"])
        if not df_traffic.empty:
            df_traffic["date"] = pd.to_datetime(df_traffic["date"])

        attribution_paths = []

        for anomaly in self.anomalies:
            anomaly_date = pd.to_datetime(anomaly["date"])
            path = {
                "date": anomaly["date"],
                "gmv": anomaly["gmv"],
                "gmv_deviation": anomaly["sigma_deviation"],
                "type": anomaly["type"],
            }

            # 前7天窗口（排除异常日本身）
            prev_mask = (df_gmv["date"] < anomaly_date) & (df_gmv["date"] >= anomaly_date - pd.Timedelta(days=8))
            prev_gmv = df_gmv[prev_mask]

            if not prev_gmv.empty:
                prev_avg_gmv = prev_gmv["gmv"].mean()
                path["prev_7d_avg_gmv"] = round(prev_avg_gmv, 2)
                path["gmv_change_vs_7d"] = round(
                    (anomaly["gmv"] - prev_avg_gmv) / prev_avg_gmv * 100, 2
                ) if prev_avg_gmv > 0 else 0

                # 1. 流量端归因
                traffic_impact = self._attribute_traffic(
                    df_traffic, anomaly_date, prev_mask, anomaly
                )
                path["traffic_attribution"] = traffic_impact

                # 2. 转化端归因
                conversion_impact = self._attribute_conversion(
                    df_conv, df_gmv, anomaly_date, prev_mask, anomaly
                )
                path["conversion_attribution"] = conversion_impact

                # 3. 客单价归因
                asp_impact = self._attribute_asp(
                    df_gmv, anomaly_date, prev_mask, anomaly
                )
                path["asp_attribution"] = asp_impact

                # 综合归因
                impacts = [
                    ("流量端", traffic_impact.get("contribution_pct", 0)),
                    ("转化端", conversion_impact.get("contribution_pct", 0)),
                    ("客单价端", asp_impact.get("contribution_pct", 0)),
                ]
                impacts.sort(key=lambda x: abs(x[1]), reverse=True)
                path["primary_driver"] = f"{impacts[0][0]}是主要驱动因素（贡献{impacts[0][1]:.1f}%），" \
                                         f"其次是{impacts[1][0]}（贡献{impacts[1][1]:.1f}%）"
                path["impacts_ranked"] = impacts

            attribution_paths.append(path)

        self.attribution_paths = attribution_paths
        print(f"    完成 {len(attribution_paths)} 个异常点的归因分析")
        return attribution_paths

    def _attribute_traffic(self, df_traffic, anomaly_date, prev_mask, anomaly) -> Dict[str, Any]:
        """流量端归因：UV和PV的变化。"""
        result = {"uv_change_pct": 0, "pv_change_pct": 0, "contribution_pct": 0, "detail": ""}

        if df_traffic.empty:
            return result

        curr_day = df_traffic[df_traffic["date"] == anomaly_date]
        prev_days = df_traffic[prev_mask] if not df_traffic.empty else pd.DataFrame()

        if curr_day.empty or prev_days.empty:
            return result

        curr_uv = curr_day["uv"].iloc[0] if "uv" in curr_day.columns else 0
        prev_avg_uv = prev_days["uv"].mean() if "uv" in prev_days.columns else 0
        if prev_avg_uv > 0:
            result["uv_change_pct"] = round((curr_uv - prev_avg_uv) / prev_avg_uv * 100, 2)

        curr_pv = curr_day["pv"].iloc[0] if "pv" in curr_day.columns else 0
        prev_avg_pv = prev_days["pv"].mean() if "pv" in prev_days.columns else 0
        if prev_avg_pv > 0:
            result["pv_change_pct"] = round((curr_pv - prev_avg_pv) / prev_avg_pv * 100, 2)

        # 流量贡献 ≈ UV变化率（简化的归因模型）
        result["contribution_pct"] = result["uv_change_pct"]
        uv_dir = "增长" if result["uv_change_pct"] > 0 else "下降"
        result["detail"] = f"UV较前7日均值{uv_dir} {abs(result['uv_change_pct']):.1f}%，" \
                           f"PV{uv_dir} {abs(result['pv_change_pct']):.1f}%"

        return result

    def _attribute_conversion(self, df_conv, df_gmv, anomaly_date, prev_mask, anomaly) -> Dict[str, Any]:
        """转化端归因：整体转化率变化。"""
        result = {"cr_change_pct": 0, "contribution_pct": 0, "detail": ""}

        if df_conv.empty:
            return result

        curr_day = df_conv[df_conv["date"] == anomaly_date]
        prev_days = df_conv[prev_mask] if not df_conv.empty else pd.DataFrame()

        if curr_day.empty or prev_days.empty:
            return result

        cr_col = "overall_conversion_rate"
        if cr_col not in curr_day.columns:
            return result

        curr_cr = curr_day[cr_col].iloc[0]
        prev_avg_cr = prev_days[cr_col].mean()

        if prev_avg_cr > 0:
            result["cr_change_pct"] = round((curr_cr - prev_avg_cr) / prev_avg_cr * 100, 2)

        result["contribution_pct"] = result["cr_change_pct"]
        cr_dir = "提升" if result["cr_change_pct"] > 0 else "下降"
        result["detail"] = f"整体转化率较前7日均值{cr_dir} {abs(result['cr_change_pct']):.1f}%" \
                           f"（{curr_cr:.1f}% vs {prev_avg_cr:.1f}%）"

        return result

    def _attribute_asp(self, df_gmv, anomaly_date, prev_mask, anomaly) -> Dict[str, Any]:
        """客单价归因：ASP（客单价）变化。"""
        result = {"asp_change_pct": 0, "contribution_pct": 0, "detail": ""}

        curr_day = df_gmv[df_gmv["date"] == anomaly_date]
        prev_days = df_gmv[prev_mask]

        if curr_day.empty or prev_days.empty:
            return result

        curr_asp = curr_day["asp"].iloc[0] if "asp" in curr_day.columns else 0
        prev_avg_asp = prev_days["asp"].mean() if "asp" in prev_days.columns else 0

        if prev_avg_asp > 0:
            result["asp_change_pct"] = round((curr_asp - prev_avg_asp) / prev_avg_asp * 100, 2)

        result["contribution_pct"] = result["asp_change_pct"]
        asp_dir = "上涨" if result["asp_change_pct"] > 0 else "下降"
        result["detail"] = f"客单价较前7日均值{asp_dir} {abs(result['asp_change_pct']):.1f}%" \
                           f"（¥{curr_asp:.2f} vs ¥{prev_avg_asp:.2f}）"

        return result

    # ============================================
    # 6.3 AI归因总结（或规则引擎降级）
    # ============================================
    def generate_ai_summary(self) -> str:
        """调用 DeepSeek API 生成AI归因总结，失败则降级为规则引擎。

        Returns:
            str: AI或规则引擎生成的分析总结
        """
        print("\n  [GMV-6.3] AI归因总结...")

        if not self.anomalies:
            summary = "未检测到GMV异常波动，系统运行平稳。"
            self.ai_summary = summary
            self.ai_mode = "无需分析"
            return summary

        # 构建归因数据摘要
        anomaly_summary = self._build_anomaly_summary_text()

        if AI_ENABLED:
            try:
                print("    🤖 调用 DeepSeek API 进行AI归因...")
                ai_result = self._call_deepseek_api(anomaly_summary)
                if ai_result:
                    self.ai_summary = ai_result
                    self.ai_mode = "AI (DeepSeek)"
                    print(f"    ✅ AI归因完成 ({self.ai_mode})")
                    return ai_result
            except Exception as e:
                print(f"    ⚠️ AI API调用失败: {e}，降级为规则引擎")

        # 规则引擎降级
        self.ai_mode = "规则引擎 (降级)"
        rule_summary = self._rule_engine_summary()
        self.ai_summary = rule_summary
        print(f"    ✅ 规则引擎归因完成")
        return rule_summary

    def _build_anomaly_summary_text(self) -> str:
        """构建异常数据摘要文本，供AI分析使用。"""
        parts = ["以下是一段电商GMV异常检测数据，请分析原因：\n"]

        parts.append(f"共检测到 {len(self.anomalies)} 个异常点：\n")
        for a in self.anomalies:
            parts.append(f"- {a['date']}: GMV ¥{a['gmv']:,.0f} ({a['type']})")
            parts.append(f"  偏差: {a['sigma_deviation']}σ, 日环比: {a['change_rate']}%")
            parts.append(f"  触发原因: {'; '.join(a['reasons'])}")

        parts.append("\n三层归因分析：")
        for p in self.attribution_paths[:5]:  # 最多5个
            parts.append(f"\n{p['date']}:")
            parts.append(f"  流量端: {p.get('traffic_attribution', {}).get('detail', 'N/A')}")
            parts.append(f"  转化端: {p.get('conversion_attribution', {}).get('detail', 'N/A')}")
            parts.append(f"  客单价端: {p.get('asp_attribution', {}).get('detail', 'N/A')}")
            parts.append(f"  主因: {p.get('primary_driver', 'N/A')}")

        return "\n".join(parts)

    def _call_deepseek_api(self, context: str) -> Optional[str]:
        """调用 DeepSeek API 进行AI归因分析。

        Args:
            context: 异常数据描述文本

        Returns:
            str or None: AI分析结果
        """
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
            )

            prompt = f"""你是一位资深的电商数据分析师。请基于以下数据，用中文对GMV异常波动做简洁的归因分析：

{context}

请按以下结构回复（每条要点控制在2-3句话以内）：

## 异常概述
[1-2句话概括异常情况]

## 根因分析
1. **[根因1]**：[具体分析]
2. **[根因2]**：[具体分析]
3. **[根因3]**：[具体分析（如有）]

## 行动建议
1. [建议1]
2. [建议2]
3. [建议3]"""

            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是电商数据分析专家，主要提供GMV异常归因分析。请使用中文回复，保持简洁专业。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
            )

            result = response.choices[0].message.content
            return result.strip() if result else None

        except ImportError:
            print("    [警告] openai 库未安装，无法调用 API")
            return None
        except Exception as e:
            print(f"    [警告] DeepSeek API 调用异常: {e}")
            return None

    def _rule_engine_summary(self) -> str:
        """规则引擎生成归因总结（AI降级方案）。"""
        if not self.anomalies:
            return "## 异常概述\n未检测到GMV异常波动，系统运行平稳。"

        lines = [
            "## 异常概述",
            f"系统共检测到 {len(self.anomalies)} 个GMV异常波动点。"
            f"以下为基于规则引擎的自动分析结果：\n",
            "## 根因分析",
        ]

        # 汇总各端贡献
        traffic_impact_total = sum(
            abs(p.get("traffic_attribution", {}).get("contribution_pct", 0))
            for p in self.attribution_paths
        )
        conversion_impact_total = sum(
            abs(p.get("conversion_attribution", {}).get("contribution_pct", 0))
            for p in self.attribution_paths
        )
        asp_impact_total = sum(
            abs(p.get("asp_attribution", {}).get("contribution_pct", 0))
            for p in self.attribution_paths
        )

        total_impact = traffic_impact_total + conversion_impact_total + asp_impact_total
        if total_impact > 0:
            traffic_pct = traffic_impact_total / total_impact * 100
            conv_pct = conversion_impact_total / total_impact * 100
            asp_pct = asp_impact_total / total_impact * 100

            lines.append(f"1. **流量端影响**：贡献了约 {traffic_pct:.0f}% 的GMV波动。"
                        f"流量是电商的命脉，UV的波动直接影响整体收入。")
            lines.append(f"2. **转化端影响**：贡献了约 {conv_pct:.0f}% 的GMV波动。"
                        f"转化率的变化反映出用户购买意愿或商品竞争力的变化。")
            lines.append(f"3. **客单价影响**：贡献了约 {asp_pct:.0f}% 的GMV波动。"
                        f"客单价变化可能源于促销活动、品类结构变化或用户购买行为变化。")

        # 按异常类型给出建议
        high_anomalies = [a for a in self.anomalies if a["type"] == "异常高"]
        low_anomalies = [a for a in self.anomalies if a["type"] == "异常低"]

        lines.append("\n## 行动建议")

        if low_anomalies:
            lines.append("1. **排查低GMV日原因**：检查对应日期是否有技术故障、营销活动空档、"
                        "竞品大促等外部因素影响。")
            lines.append("2. **加强流量储备**：建立多渠道流量矩阵，减少对单一渠道的依赖，"
                        "降低流量波动对GMV的冲击。")
        else:
            lines.append("1. **复盘高GMV日**：分析高GMV日的成功因素（促销力度、商品组合、"
                        "流量来源），提炼可复用的运营策略。")

        lines.append("3. **建立预警机制**：当UV或转化率较前7日均值下降超过20%时，"
                     "自动触发预警通知运营团队介入。")

        # 标注为规则引擎模式
        lines.append(f"\n> 💡 *本分析由规则引擎自动生成（AI模式未启用或调用失败）。"
                     f"如需更深入的AI分析，请在 .env 文件中配置 DEEPSEEK_API_KEY。*")

        return "\n".join(lines)

    # ============================================
    # 主入口
    # ============================================
    def run(self) -> Dict[str, Any]:
        """执行完整的GMV异常检测与归因流程。

        Returns:
            dict: 包含异常列表、归因路径、AI总结和图表
        """
        print("\n" + "-" * 40)
        print("  Step 6: GMV异常波动检测与AI归因")
        print("-" * 40)

        results = {}

        try:
            results["anomalies"] = self.detect_anomalies()
        except Exception as e:
            print(f"    ❌ 异常检测失败: {e}")
            results["anomalies"] = []
            results["error"] = str(e)

        try:
            results["attribution_paths"] = self.attribute_anomalies()
        except Exception as e:
            print(f"    ❌ 归因分析失败: {e}")
            results["attribution_paths"] = []

        try:
            results["ai_summary"] = self.generate_ai_summary()
            results["ai_mode"] = self.ai_mode
        except Exception as e:
            print(f"    ❌ AI总结失败: {e}")
            results["ai_summary"] = "归因分析生成失败，请检查数据。"
            results["ai_mode"] = "失败"

        results["chart"] = self.chart
        results["anomaly_count"] = len(self.anomalies)

        print(f"\n  ✅ GMV分析完成: {len(self.anomalies)} 个异常点, 归因模式: {self.ai_mode}")
        return results
