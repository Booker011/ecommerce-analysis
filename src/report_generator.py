"""
HTML报告生成模块
-----------------
将全部分析结果渲染为一份专业的HTML分析报告。
包含：封面、数据概况卡片、指标体系总览、转化率归因分析、GMV异常诊断、数据质量报告。
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from jinja2 import Template

from config import OUTPUT_DIR, CHINESE_FONT, AI_ENABLED


class ReportGenerator:
    """HTML报告生成器：将所有分析结果整合为专业报告。"""

    def __init__(self):
        self.output_path = OUTPUT_DIR / "analysis_report.html"

    def generate(
        self,
        summary: Dict[str, Any],
        quality_report: Dict[str, Any],
        dw_info: Dict[str, Any],
        checker_report: Dict[str, Any],
        attribution_results: Dict[str, Any],
        gmv_results: Dict[str, Any],
        data_loader_summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成完整的HTML分析报告。

        Args:
            summary: 数据概况
            quality_report: 数据质量报告
            dw_info: 数仓信息
            checker_report: 校验报告
            attribution_results: 归因分析结果
            gmv_results: GMV异常分析结果

        Returns:
            str: 生成的HTML文件路径
        """
        print("\n" + "-" * 40)
        print("  Step 7: 生成HTML分析报告")
        print("-" * 40)

        # 准备模板数据
        template_data = self._prepare_data(
            summary, quality_report, dw_info, checker_report,
            attribution_results, gmv_results
        )

        # 渲染HTML
        html_content = self._render_html(template_data)

        # 写入文件
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        file_size_kb = round(len(html_content) / 1024, 1)
        print(f"\n  ✅ 报告已生成: {self.output_path.resolve()}")
        print(f"     文件大小: {file_size_kb} KB")

        return str(self.output_path.resolve())

    def _prepare_data(self, summary, quality_report, dw_info, checker_report, attribution_results, gmv_results):
        """汇总所有数据为模板变量。"""
        # 计算关键指标
        total_gmv = summary.get("total_gmv", 0)
        total_orders = summary.get("order_count", 0)
        total_users = summary.get("user_count", 0)

        # 转化率（从归因分析获取或自行计算）
        funnel = attribution_results.get("funnel", {})
        conversion_rate = funnel.get("view_to_purchase_rate", 0)
        asp = summary.get("avg_price", 0)

        # 时间范围
        time_start = summary.get("time_start", "N/A")
        time_end = summary.get("time_end", "N/A")

        # 数据质量
        quality_score = quality_report.get("quality_score", 0)
        quality_grade = self._get_grade(quality_score) if isinstance(quality_score, (int, float)) else "N/A"

        # 校验结果
        check_status = checker_report.get("overall_status", "N/A")
        check_pass_rate = checker_report.get("pass_rate", 0)

        # 图表
        charts = attribution_results.get("charts", {})
        gmv_chart = gmv_results.get("chart", "")

        # 归因结论和建议
        attribution_data = attribution_results.get("attribution", {})
        conclusions = attribution_data.get("conclusions", [])
        recommendations = attribution_data.get("recommendations", [])

        # GMV异常
        anomalies = gmv_results.get("anomalies", [])
        attribution_paths = gmv_results.get("attribution_paths", [])
        ai_summary = gmv_results.get("ai_summary", "")
        ai_mode = gmv_results.get("ai_mode", "规则引擎")

        # 数据质量详情
        missing_report = quality_report.get("missing_report", {})
        anomaly_report = quality_report.get("anomaly_report", {})
        duplicate_report = quality_report.get("duplicate_report", {})

        # 数仓表信息
        tables = dw_info.get("tables", {})

        return {
            # 封面
            "report_title": "数据+AI驱动电商运营分析报告",
            "time_range": f"{time_start} ~ {time_end}",
            "gen_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ai_mode_label": "AI增强模式" if AI_ENABLED else "规则引擎模式",

            # 指标卡片
            "kpi_gmv": f"¥{total_gmv:,.0f}",
            "kpi_orders": f"{total_orders:,}",
            "kpi_users": f"{total_users:,}",
            "kpi_conversion": f"{conversion_rate:.2f}%",
            "kpi_asp": f"¥{asp:,.2f}",
            "kpi_quality": f"{quality_score}/100",

            # 数据概况
            "summary": summary,
            "quality_score": quality_score,
            "quality_grade": quality_grade,

            # 校验
            "check_status": check_status,
            "check_pass_rate": check_pass_rate,
            "check_details": checker_report.get("checks", []),

            # 数仓
            "dw_tables": tables,
            "dw_total_rows": dw_info.get("total_rows", 0),

            # 归因分析图表
            "chart_trend": charts.get("trend_dual_axis", ""),
            "chart_channel_pie": charts.get("channel_pie", ""),
            "chart_channel_bar": charts.get("channel_bar", ""),
            "chart_user_conversion": charts.get("user_conversion", ""),
            "chart_repurchase": charts.get("repurchase_trend", ""),
            "chart_category": charts.get("category_ranking", ""),
            "chart_funnel": charts.get("funnel", ""),
            "chart_gmv_anomaly": gmv_chart,

            # 漏斗数据
            "funnel": funnel,
            "funnel_views": funnel.get("views", 0),
            "funnel_carts": funnel.get("carts", 0),
            "funnel_purchases": funnel.get("purchases", 0),

            # 归因
            "conclusions": conclusions,
            "recommendations": recommendations,
            "correlation": attribution_results.get("trend", {}).get("correlation", {}),

            # GMV
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "attribution_paths": attribution_paths,
            "ai_summary": ai_summary.replace("\n", "<br>") if ai_summary else "",
            "ai_mode": ai_mode,

            # 数据质量详情
            "missing_columns": missing_report.get("per_column", {}),
            "anomaly_items": anomaly_report.get("anomaly_items", {}),
            "duplicate_info": duplicate_report,

            # 字体
            "font_family": CHINESE_FONT,
        }

    def _get_grade(self, score: float) -> str:
        """评分 → 等级。"""
        if score >= 95:
            return "A (优秀)"
        elif score >= 85:
            return "B (良好)"
        elif score >= 70:
            return "C (一般)"
        elif score >= 60:
            return "D (较差)"
        return "E (很差)"

    def _render_html(self, data: Dict[str, Any]) -> str:
        """使用 Jinja2 模板渲染HTML报告。"""
        template = Template(HTML_TEMPLATE)
        return template.render(**data)


# ============================================
# HTML模板
# ============================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ report_title }}</title>
    <style>
        /* ===== 基础重置与字体 ===== */
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: "{{ font_family }}", "Microsoft YaHei", "PingFang SC", "Helvetica Neue", sans-serif;
            background: #f0f2f5;
            color: #333;
            line-height: 1.7;
        }

        /* ===== 封面区域 ===== */
        .cover {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 40%, #0f3460 100%);
            color: white;
            padding: 80px 40px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        .cover::before {
            content: "";
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 60%);
            animation: rotate 30s linear infinite;
        }
        @keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .cover h1 { font-size: 2.8em; font-weight: 700; margin-bottom: 16px; position: relative; z-index: 1; letter-spacing: 2px; }
        .cover .subtitle { font-size: 1.1em; opacity: 0.85; margin-bottom: 8px; position: relative; z-index: 1; }
        .cover .meta { font-size: 0.9em; opacity: 0.65; position: relative; z-index: 1; margin-top: 20px; }
        .cover .badge {
            display: inline-block; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3);
            padding: 6px 20px; border-radius: 20px; font-size: 0.85em; margin-top: 16px;
            position: relative; z-index: 1;
        }

        /* ===== 内容容器 ===== */
        .container { max-width: 1200px; margin: 0 auto; padding: 30px 20px; }

        /* ===== 章节标题 ===== */
        .section-title {
            font-size: 1.6em; font-weight: 700; color: #1a1a2e;
            margin: 48px 0 24px; padding-bottom: 12px;
            border-bottom: 3px solid #0f3460; display: flex; align-items: center; gap: 10px;
        }
        .section-title .icon { font-size: 1.2em; }
        .section-subtitle { font-size: 1.2em; font-weight: 600; color: #2c3e50; margin: 28px 0 14px; }

        /* ===== KPI 指标卡片 ===== */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 20px;
            margin-bottom: 32px;
        }
        .kpi-card {
            background: white;
            border-radius: 14px;
            padding: 24px 20px;
            text-align: center;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            position: relative;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .kpi-card:hover { transform: translateY(-3px); box-shadow: 0 6px 24px rgba(0,0,0,0.1); }
        .kpi-card::before {
            content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px;
        }
        .kpi-card:nth-child(1)::before { background: linear-gradient(90deg, #667eea, #764ba2); }
        .kpi-card:nth-child(2)::before { background: linear-gradient(90deg, #f093fb, #f5576c); }
        .kpi-card:nth-child(3)::before { background: linear-gradient(90deg, #4facfe, #00f2fe); }
        .kpi-card:nth-child(4)::before { background: linear-gradient(90deg, #43e97b, #38f9d7); }
        .kpi-card:nth-child(5)::before { background: linear-gradient(90deg, #fa709a, #fee140); }
        .kpi-card:nth-child(6)::before { background: linear-gradient(90deg, #a18cd1, #fbc2eb); }
        .kpi-card .label { font-size: 0.85em; color: #666; margin-bottom: 8px; }
        .kpi-card .value { font-size: 1.8em; font-weight: 700; color: #1a1a2e; }
        .kpi-card .unit { font-size: 0.6em; color: #999; }

        /* ===== 矩阵表格 ===== */
        .matrix-table {
            width: 100%; border-collapse: collapse; margin: 16px 0 28px;
            background: white; border-radius: 12px; overflow: hidden;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        }
        .matrix-table th {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: white; padding: 14px 16px; font-weight: 600; font-size: 0.9em;
            text-align: center;
        }
        .matrix-table td {
            padding: 12px 16px; text-align: center; border-bottom: 1px solid #f0f0f0;
            font-size: 0.9em;
        }
        .matrix-table tr:nth-child(even) td { background: #fafbfc; }
        .matrix-table tr:hover td { background: #eef2ff; }
        .matrix-table .cat-header {
            background: #f0f4ff; font-weight: 700; color: #0f3460;
            text-align: left; font-size: 0.95em;
        }

        /* ===== 图表容器 ===== */
        .chart-container {
            background: white; border-radius: 14px; padding: 24px;
            margin-bottom: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            text-align: center;
        }
        .chart-container img { max-width: 100%; height: auto; border-radius: 4px; }

        /* ===== 分析总结框 ===== */
        .insight-box {
            background: linear-gradient(135deg, #f8f9ff, #eef1ff);
            border-left: 4px solid #0f3460; border-radius: 10px;
            padding: 20px 24px; margin: 20px 0;
        }
        .insight-box h4 { color: #0f3460; margin-bottom: 10px; font-size: 1.1em; }
        .insight-box ul { list-style: none; padding: 0; }
        .insight-box li {
            padding: 6px 0; padding-left: 20px; position: relative;
            font-size: 0.95em; color: #444;
        }
        .insight-box li::before { content: "▸"; position: absolute; left: 0; color: #0f3460; }

        /* ===== 建议卡片 ===== */
        .recommendation-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 16px; margin: 16px 0 28px;
        }
        .rec-card {
            background: white; border-radius: 12px; padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            border-top: 4px solid #27ae60; position: relative;
        }
        .rec-card .rec-num {
            position: absolute; top: -14px; left: 16px;
            background: #27ae60; color: white; width: 28px; height: 28px;
            border-radius: 50%; display: flex; align-items: center; justify-content: center;
            font-weight: 700; font-size: 0.85em;
        }
        .rec-card p { margin-top: 8px; font-size: 0.9em; color: #444; line-height: 1.6; }

        /* ===== 异常表格 ===== */
        .anomaly-table {
            width: 100%; border-collapse: collapse; background: white;
            border-radius: 12px; overflow: hidden;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            margin: 16px 0 28px;
        }
        .anomaly-table th {
            background: #e74c3c; color: white; padding: 12px 14px;
            font-weight: 600; font-size: 0.85em; text-align: center;
        }
        .anomaly-table td {
            padding: 10px 14px; text-align: center; border-bottom: 1px solid #f0f0f0;
            font-size: 0.85em;
        }
        .anomaly-table tr:nth-child(even) td { background: #fef5f5; }
        .tag-high { background: #ffe0e0; color: #c0392b; padding: 3px 10px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }
        .tag-low { background: #fff3e0; color: #e67e22; padding: 3px 10px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }

        /* ===== AI分析框 ===== */
        .ai-box {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: #e0e0e0; border-radius: 14px; padding: 28px; margin: 20px 0;
            line-height: 1.8;
        }
        .ai-box h4 { color: #64b5f6; font-size: 1.15em; margin: 16px 0 8px; }
        .ai-box h4:first-child { margin-top: 0; }
        .ai-box strong { color: #ffd54f; }
        .ai-box blockquote {
            border-left: 3px solid #64b5f6; padding-left: 16px; margin: 12px 0;
            color: #b0bec5; font-style: italic;
        }
        .ai-mode-tag {
            display: inline-block; padding: 4px 14px; border-radius: 14px;
            font-size: 0.8em; font-weight: 600; margin-bottom: 12px;
        }
        .ai-mode-tag.ai { background: #1b5e20; color: #a5d6a7; }
        .ai-mode-tag.rule { background: #4a148c; color: #ce93d8; }

        /* ===== 数据质量卡片 ===== */
        .quality-cards {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px; margin: 16px 0 28px;
        }
        .quality-card {
            background: white; border-radius: 12px; padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        .quality-card h4 { font-size: 1em; color: #1a1a2e; margin-bottom: 10px; }
        .quality-item {
            display: flex; justify-content: space-between; padding: 6px 0;
            border-bottom: 1px dashed #eee; font-size: 0.85em;
        }
        .status-ok { color: #27ae60; }
        .status-warn { color: #e67e22; }
        .status-error { color: #e74c3c; }

        /* ===== 页脚 ===== */
        .footer {
            text-align: center; padding: 32px; color: #999; font-size: 0.8em;
            border-top: 1px solid #e0e0e0; margin-top: 48px;
        }

        /* ===== 响应式 ===== */
        @media (max-width: 768px) {
            .cover h1 { font-size: 1.8em; }
            .cover { padding: 48px 20px; }
            .kpi-grid { grid-template-columns: repeat(2, 1fr); }
            .recommendation-grid { grid-template-columns: 1fr; }
            .container { padding: 16px 10px; }
        }
    </style>
</head>
<body>

<!-- ===== 封面 ===== -->
<div class="cover">
    <h1>{{ report_title }}</h1>
    <div class="subtitle">分析周期：{{ time_range }}</div>
    <div class="meta">报告生成时间：{{ gen_time }}</div>
    <div class="badge">{{ ai_mode_label }}</div>
</div>

<div class="container">

<!-- ===== 第1章：数据概况 ===== -->
<div class="section-title"><span class="icon">📊</span> 数据概况</div>

<div class="kpi-grid">
    <div class="kpi-card">
        <div class="label">📦 总订单数</div>
        <div class="value">{{ kpi_orders }}</div>
    </div>
    <div class="kpi-card">
        <div class="label">💰 预估GMV</div>
        <div class="value">{{ kpi_gmv }}</div>
    </div>
    <div class="kpi-card">
        <div class="label">👥 用户数</div>
        <div class="value">{{ kpi_users }}</div>
    </div>
    <div class="kpi-card">
        <div class="label">📈 整体转化率</div>
        <div class="value">{{ kpi_conversion }}</div>
    </div>
    <div class="kpi-card">
        <div class="label">🛒 客单价</div>
        <div class="value">{{ kpi_asp }}</div>
    </div>
    <div class="kpi-card">
        <div class="label">✅ 数据质量</div>
        <div class="value">{{ kpi_quality }}</div>
    </div>
</div>

<!-- ===== 第2章：指标体系总览 ===== -->
<div class="section-title"><span class="icon">🎯</span> 指标体系总览（人-货-场）</div>

<table class="matrix-table">
    <thead>
        <tr>
            <th>维度</th>
            <th>一级指标</th>
            <th>二级指标</th>
            <th>数据表</th>
            <th>粒度</th>
        </tr>
    </thead>
    <tbody>
        <tr class="cat-header"><td colspan="5">🏪 场（流量与转化）</td></tr>
        <tr><td>流量</td><td>PV / UV</td><td>各渠道PV/UV、设备分布</td><td>dws_traffic_daily</td><td>日</td></tr>
        <tr><td>转化</td><td>转化率</td><td>浏览转化率、加购转化率、支付转化率</td><td>dws_conversion_daily</td><td>日</td></tr>
        <tr class="cat-header"><td colspan="5">👤 人（用户价值）</td></tr>
        <tr><td>用户增长</td><td>新增/活跃</td><td>新增用户、活跃用户、留存率</td><td>dws_user_daily</td><td>日</td></tr>
        <tr><td>用户价值</td><td>复购率</td><td>复购用户数、复购率、ARPU</td><td>dws_user_daily</td><td>日</td></tr>
        <tr class="cat-header"><td colspan="5">📦 货（商品效率）</td></tr>
        <tr><td>商品效率</td><td>动销率</td><td>曝光商品数、动销商品数、动销率</td><td>dws_product_daily</td><td>日</td></tr>
        <tr><td>品类结构</td><td>品类GMV</td><td>各品类销售额、销量、转化率</td><td>dws_category_daily</td><td>日</td></tr>
        <tr class="cat-header"><td colspan="5">💵 综合（收入健康度）</td></tr>
        <tr><td>收入</td><td>GMV</td><td>GMV、客单价、订单数、ARPU</td><td>dws_gmv_daily</td><td>日</td></tr>
    </tbody>
</table>

<!-- ===== 第3章：转化率归因分析 ===== -->
<div class="section-title"><span class="icon">🔍</span> 转化率归因分析</div>

{% if chart_trend %}
<div class="section-subtitle">📈 5.1 整体趋势：流量与转化率</div>
<div class="chart-container">{{ chart_trend }}</div>

{% if correlation and correlation.coefficient %}
<div class="insight-box">
    <h4>📊 相关性分析</h4>
    <p>流量与转化率的皮尔逊相关系数 <strong>r = {{ correlation.coefficient }}</strong>（p = {{ correlation.p_value }}），
    呈<strong>{{ correlation.strength }}{{ correlation.direction }}</strong>，相关性<strong>{{ correlation.significance }}</strong>。</p>
    <p>{{ correlation.interpretation }}</p>
</div>
{% endif %}
{% endif %}

{% if chart_channel_pie or chart_channel_bar %}
<div class="section-subtitle">📡 5.2 渠道维度下钻</div>
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
    {% if chart_channel_pie %}<div class="chart-container">{{ chart_channel_pie }}</div>{% endif %}
    {% if chart_channel_bar %}<div class="chart-container">{{ chart_channel_bar }}</div>{% endif %}
</div>
{% endif %}

{% if chart_user_conversion %}
<div class="section-subtitle">👤 5.3 用户维度下钻</div>
<div class="chart-container">{{ chart_user_conversion }}</div>
{% endif %}

{% if chart_repurchase %}
<div class="chart-container">{{ chart_repurchase }}</div>
{% endif %}

{% if chart_category %}
<div class="section-subtitle">🏷️ 5.4 品类维度下钻</div>
<div class="chart-container">{{ chart_category }}</div>
{% endif %}

{% if chart_funnel %}
<div class="section-subtitle">🔻 5.5 漏斗分析</div>
<div class="chart-container">{{ chart_funnel }}</div>

<div class="kpi-grid" style="grid-template-columns: repeat(3, 1fr);">
    <div class="kpi-card">
        <div class="label">浏览 → 加购</div>
        <div class="value">{{ funnel.view_to_cart_rate }}%</div>
    </div>
    <div class="kpi-card">
        <div class="label">加购 → 购买</div>
        <div class="value">{{ funnel.cart_to_purchase_rate }}%</div>
    </div>
    <div class="kpi-card">
        <div class="label">浏览 → 购买</div>
        <div class="value">{{ funnel.view_to_purchase_rate }}%</div>
    </div>
</div>
{% endif %}

{% if conclusions %}
<div class="section-subtitle">🧠 5.6 归因结论与优化建议</div>

<div class="insight-box">
    <h4>📋 归因结论</h4>
    <ul>
        {% for c in conclusions %}
        <li>{{ c }}</li>
        {% endfor %}
    </ul>
</div>

<div class="recommendation-grid">
    {% for r in recommendations %}
    <div class="rec-card">
        <div class="rec-num">{{ loop.index }}</div>
        <p>{{ r }}</p>
    </div>
    {% endfor %}
</div>
{% endif %}

<!-- ===== 第4章：GMV异常诊断 ===== -->
<div class="section-title"><span class="icon">⚠️</span> GMV异常波动诊断</div>

{% if chart_gmv_anomaly %}
<div class="chart-container">{{ chart_gmv_anomaly }}</div>
{% endif %}

{% if anomalies %}
<div class="section-subtitle">异常点明细</div>
<table class="anomaly-table">
    <thead>
        <tr>
            <th>日期</th>
            <th>GMV</th>
            <th>σ偏差</th>
            <th>日环比</th>
            <th>类型</th>
            <th>触发原因</th>
        </tr>
    </thead>
    <tbody>
        {% for a in anomalies %}
        <tr>
            <td><strong>{{ a.date }}</strong></td>
            <td>¥{{ "{:,.0f}".format(a.gmv) }}</td>
            <td>{{ a.sigma_deviation }}σ</td>
            <td>{{ a.change_rate }}%</td>
            <td><span class="{{ 'tag-high' if a.type == '异常高' else 'tag-low' }}">{{ a.type }}</span></td>
            <td style="text-align:left;font-size:0.8em;">{{ '; '.join(a.reasons) }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<div class="insight-box"><p>✅ 未检测到GMV异常波动，系统运行平稳。</p></div>
{% endif %}

{% if attribution_paths %}
<div class="section-subtitle">三层归因路径</div>
<table class="matrix-table">
    <thead>
        <tr><th>日期</th><th>流量端</th><th>转化端</th><th>客单价端</th><th>主因</th></tr>
    </thead>
    <tbody>
        {% for p in attribution_paths %}
        <tr>
            <td><strong>{{ p.date }}</strong></td>
            <td>{{ p.traffic_attribution.detail if p.traffic_attribution else 'N/A' }}</td>
            <td>{{ p.conversion_attribution.detail if p.conversion_attribution else 'N/A' }}</td>
            <td>{{ p.asp_attribution.detail if p.asp_attribution else 'N/A' }}</td>
            <td style="text-align:left;font-size:0.8em;">{{ p.primary_driver if p.primary_driver else 'N/A' }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endif %}

{% if ai_summary %}
<div class="section-subtitle">🤖 AI归因分析 <span class="ai-mode-tag {{ 'ai' if ai_mode == 'AI (DeepSeek)' else 'rule' }}">{{ ai_mode }}</span></div>
<div class="ai-box">{{ ai_summary|safe }}</div>
{% endif %}

<!-- ===== 第5章：数据质量报告 ===== -->
<div class="section-title"><span class="icon">🔬</span> 数据质量报告</div>

<div class="quality-cards">
    <div class="quality-card">
        <h4>📋 缺失值检查</h4>
        {% if missing_columns %}
            {% for col, info in missing_columns.items() %}
            <div class="quality-item">
                <span>{{ col }}</span>
                <span class="{{ 'status-ok' if info.status == '✅ 正常' else ('status-warn' if '警告' in info.status else 'status-error') }}">
                    {{ info.status }} ({{ info.percentage }}%)
                </span>
            </div>
            {% endfor %}
        {% else %}
            <p>✅ 所有字段完整</p>
        {% endif %}
    </div>

    <div class="quality-card">
        <h4>🔍 异常值检查</h4>
        {% if anomaly_items %}
            {% for key, info in anomaly_items.items() %}
            <div class="quality-item">
                <span>{{ info.description }}</span>
                <span class="status-error">{{ info.count }} 条</span>
            </div>
            {% endfor %}
        {% else %}
            <p>✅ 未发现异常值</p>
        {% endif %}
    </div>

    <div class="quality-card">
        <h4>📎 重复检查</h4>
        {% if duplicate_info %}
            <div class="quality-item"><span>完全重复行</span><span>{{ duplicate_info.full_duplicates }} 条</span></div>
            <div class="quality-item"><span>订单ID重复</span><span>{{ duplicate_info.order_id_duplicates }} 条</span></div>
            <div class="quality-item"><span>组合重复</span><span>{{ duplicate_info.combo_duplicates }} 条</span></div>
        {% else %}
            <p>✅ 无重复数据</p>
        {% endif %}
    </div>
</div>

<div class="kpi-grid" style="grid-template-columns: repeat(2, 1fr);">
    <div class="kpi-card">
        <div class="label">🏆 数据质量总分</div>
        <div class="value">{{ quality_score }}/100</div>
        <div class="unit">等级：{{ quality_grade }}</div>
    </div>
    <div class="kpi-card">
        <div class="label">🔗 数仓一致性</div>
        <div class="value">{{ check_pass_rate }}%</div>
        <div class="unit">{{ check_status }}</div>
    </div>
</div>

{% if check_details %}
<table class="matrix-table">
    <thead><tr><th>校验项</th><th>结果</th><th>详情</th></tr></thead>
    <tbody>
        {% for c in check_details %}
        <tr>
            <td>{{ c.name }}</td>
            <td>{{ c.status }}</td>
            <td style="text-align:left;font-size:0.8em;">{{ c.detail }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endif %}

</div><!-- /.container -->

<!-- ===== 页脚 ===== -->
<div class="footer">
    <p>{{ report_title }} · 生成时间：{{ gen_time }} · 分析模式：{{ ai_mode_label }}</p>
    <p>本报告由数据+AI驱动电商运营分析系统自动生成</p>
</div>

</body>
</html>"""


def generate_report(
    summary: Dict[str, Any],
    quality_report: Dict[str, Any],
    dw_info: Dict[str, Any],
    checker_report: Dict[str, Any],
    attribution_results: Dict[str, Any],
    gmv_results: Dict[str, Any],
) -> str:
    """快捷函数：生成HTML报告。

    Args:
        summary: 数据概况
        quality_report: 数据质量报告
        dw_info: 数仓信息
        checker_report: 校验报告
        attribution_results: 归因分析结果
        gmv_results: GMV异常分析结果

    Returns:
        str: 生成的HTML文件路径
    """
    generator = ReportGenerator()
    return generator.generate(
        summary, quality_report, dw_info, checker_report,
        attribution_results, gmv_results,
    )
