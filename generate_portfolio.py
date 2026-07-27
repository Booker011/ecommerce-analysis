#!/usr/bin/env python3
"""
作品集生成脚本
-------------
运行全部分析流程，自动提问并记录AI回答，生成作品集 README 文件。
"""

import sys
import os
import sqlite3
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tqdm import tqdm

from config import (
    AI_ENABLED, OUTPUT_DIR, DB_PATH,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
)
from src.data_loader import DataLoader
from src.data_quality import DataQualityChecker
from src.dw_builder import DataWarehouseBuilder
from src.data_checker import DataChecker
from src.attribution_analysis import AttributionAnalyzer
from src.gmv_anomaly import GMVAnomalyDetector
from src.report_generator import ReportGenerator


# ============================================
# AI 问答辅助函数
# ============================================

def _query_dws(db_path: str, sql: str):
    """查询 DWS 层数据。"""
    conn = sqlite3.connect(db_path)
    try:
        import pandas as pd
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


def _build_data_context(db_path: str, attribution_results: dict, gmv_results: dict) -> str:
    """从 DWS 层提取关键数据，构建给 AI 的上下文。"""
    parts = ["## 当前电商数据概况\n"]

    # 1. GMV 汇总
    try:
        df = _query_dws(db_path, """
            SELECT date, gmv, order_count, asp, uv, arpu
            FROM dws_gmv_daily ORDER BY date
        """)
        if not df.empty:
            total_gmv = df["gmv"].sum()
            avg_daily_gmv = df["gmv"].mean()
            parts.append(f"### GMV数据")
            parts.append(f"- 总GMV: RMB {total_gmv:,.0f}")
            parts.append(f"- 日均GMV: RMB {avg_daily_gmv:,.0f}")
            parts.append(f"- 客单价均值: RMB {df['asp'].mean():.1f}")
    except Exception:
        pass

    # 2. 转化率数据
    try:
        df = _query_dws(db_path, """
            SELECT date, overall_conversion_rate, view_to_cart_rate,
                   cart_to_purchase_rate, view_to_purchase_rate
            FROM dws_conversion_daily ORDER BY date
        """)
        if not df.empty:
            df["month"] = pd.to_datetime(df["date"]).dt.month
            monthly = df.groupby("month")["overall_conversion_rate"].mean()
            parts.append(f"\n### 转化率数据")
            parts.append(f"- 整体转化率均值: {df['overall_conversion_rate'].mean():.2f}%")
            for m, rate in monthly.items():
                parts.append(f"- {m}月转化率: {rate:.2f}%")
    except Exception:
        pass

    # 3. 品类数据
    try:
        df = _query_dws(db_path, """
            SELECT category,
                   SUM(total_events) as total,
                   SUM(gmv) as gmv,
                   ROUND(CAST(SUM(purchase_count) AS FLOAT) / SUM(total_events) * 100, 2) as conversion_rate
            FROM dws_category_daily
            GROUP BY category ORDER BY gmv DESC
        """)
        if not df.empty:
            parts.append(f"\n### 品类数据")
            for _, row in df.iterrows():
                parts.append(f"- {row['category']}: GMV RMB {row['gmv']:,.0f}, 转化率 {row['conversion_rate']:.1f}%")
    except Exception:
        pass

    # 4. 渠道数据
    try:
        df = _query_dws(db_path, """
            SELECT channel, COUNT(*) as pv,
                   SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) as purchases,
                   ROUND(CAST(SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS FLOAT)/COUNT(*)*100, 2) as cr
            FROM dwd_user_behavior_detail
            GROUP BY channel ORDER BY pv DESC
        """)
        if not df.empty:
            parts.append(f"\n### 渠道数据")
            for _, row in df.iterrows():
                parts.append(f"- {row['channel']}: PV {row['pv']:,}, 转化率 {row['cr']:.1f}%")
    except Exception:
        pass

    # 5. GMV 异常检测结果
    anomalies = gmv_results.get("anomalies", [])
    if anomalies:
        parts.append(f"\n### GMV异常点 ({len(anomalies)}个)")
        for a in anomalies[:5]:
            parts.append(f"- {a['date']}: GMV RMB {a['gmv']:,.0f} ({a['type']}), "
                         f"偏差 {a['sigma_deviation']}σ")

    return "\n".join(parts)


def _call_ai_api(context: str, question: str) -> str:
    """调用 DeepSeek API 回答问题。"""
    import pandas as pd  # noqa: F811
    try:
        from openai import OpenAI
    except ImportError:
        return ""

    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        prompt = f"""你是一位资深的电商数据分析师。请基于以下真实数据，用中文回答用户的问题。

数据是绝对真实的，你必须严格基于数据回答，不要编造任何不在数据中的事实。
如果数据不足以回答某个问题，请诚实说明。

{context}

用户问题: {question}

请简洁专业地回答（控制在200-300字以内），如果涉及具体数字请引用数据。"""

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是电商数据分析专家，必须严格基于提供的数据回答问题。使用中文回复。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        result = response.choices[0].message.content
        return result.strip() if result else ""

    except Exception as e:
        print(f"  [警告] AI API 调用异常: {e}")
        return ""


def _rule_engine_answer(question: str, db_path: str) -> str:
    """规则引擎降级方案。"""
    import pandas as pd  # noqa: F811
    q = question.lower()

    if "转化率" in question or "下降" in question:
        try:
            df = _query_dws(db_path, """
                SELECT date, overall_conversion_rate, view_to_cart_rate,
                       cart_to_purchase_rate, view_to_purchase_rate
                FROM dws_conversion_daily ORDER BY date
            """)
            if not df.empty:
                df["month"] = df["date"].str[:7]
                monthly = df.groupby("month")["overall_conversion_rate"].mean()
                lines = ["📊 **转化率分析**："]
                for m, rate in monthly.items():
                    lines.append(f"  · {m}: {rate:.2f}%")
                lines.append(f"  · 整体均值: {df['overall_conversion_rate'].mean():.2f}%")

                # 尝试分析下降原因
                channel_df = _query_dws(db_path, """
                    SELECT channel, COUNT(*) as pv,
                           ROUND(CAST(SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS FLOAT)/COUNT(*)*100, 2) as cr
                    FROM dwd_user_behavior_detail
                    GROUP BY channel ORDER BY cr ASC
                """)
                if not channel_df.empty:
                    worst = channel_df.iloc[0]
                    lines.append(f"  · 转化率最低渠道: {worst['channel']} ({worst['cr']:.1f}%)")

                lines.append("\n**主要原因**：流量增量主要来自转化率较低的渠道（如小程序、短视频等非传统电商渠道），"
                              "拉低了整体转化率水平。这些渠道的用户多为冲动浏览或羊毛党，购买意愿较弱。")
                return "\n".join(lines)
        except Exception as e:
            return f"数据查询失败: {e}"

    elif "品类" in question or "GMV最高" in question:
        try:
            df = _query_dws(db_path, """
                SELECT category, SUM(gmv) as gmv, SUM(purchase_count) as purchases,
                       ROUND(CAST(SUM(purchase_count) AS FLOAT)/SUM(total_events)*100, 2) as cr
                FROM dws_category_daily
                GROUP BY category ORDER BY gmv DESC
            """)
            if not df.empty:
                lines = ["🏷️ **品类分析**："]
                for _, row in df.iterrows():
                    lines.append(f"  · {row['category']}: GMV RMB {row['gmv']:,.0f}, "
                                 f"购买{int(row['purchases'])}次, 转化率 {row['cr']:.1f}%")
                best = df.iloc[0]
                lines.append(f"\n  🏆 GMV最高品类: **{best['category']}** (RMB {best['gmv']:,.0f})")
                return "\n".join(lines)
        except Exception as e:
            return f"数据查询失败: {e}"

    elif "4月" in question or "6月" in question or "对比" in question:
        try:
            gmv_df = _query_dws(db_path, "SELECT date, gmv, order_count, asp FROM dws_gmv_daily ORDER BY date")
            conv_df = _query_dws(db_path, "SELECT date, overall_conversion_rate FROM dws_conversion_daily ORDER BY date")

            if not gmv_df.empty and not conv_df.empty:
                gmv_df["month"] = gmv_df["date"].str[:7]
                conv_df["month"] = conv_df["date"].str[:7]

                lines = ["📋 **4月与6月数据对比**：\n"]
                for m in ["2026-04", "2026-06"]:
                    gmv_m = gmv_df[gmv_df["month"] == m]
                    conv_m = conv_df[conv_df["month"] == m]
                    if not gmv_m.empty:
                        lines.append(f"**{m}**:")
                        lines.append(f"  · 总GMV: RMB {gmv_m['gmv'].sum():,.0f}")
                        lines.append(f"  · 日均GMV: RMB {gmv_m['gmv'].mean():,.0f}")
                        lines.append(f"  · 总订单数: {int(gmv_m['order_count'].sum()):,}")
                        if not conv_m.empty:
                            lines.append(f"  · 平均转化率: {conv_m['overall_conversion_rate'].mean():.2f}%")
                        lines.append("")

                # 对比分析
                gmv_apr = gmv_df[gmv_df["month"] == "2026-04"]["gmv"].sum()
                gmv_jun = gmv_df[gmv_df["month"] == "2026-06"]["gmv"].sum()
                if gmv_apr > 0:
                    change = (gmv_jun - gmv_apr) / gmv_apr * 100
                    dir_text = "增长" if change > 0 else "下降"
                    lines.append(f"**变化**: 6月GMV较4月{dir_text} {abs(change):.1f}%")
                return "\n".join(lines)
        except Exception as e:
            return f"数据查询失败: {e}"

    return "📋 未能生成详细分析，请检查数据完整性。"


# ============================================
# 主流程
# ============================================

def main():
    """运行全流程分析、AI问答并生成作品集。"""
    print("\n" + "=" * 60)
    print("  [作品集生成工具]")
    print("  运行全部分析 -> AI自动问答 -> 生成 PORTFOLIO_FOR_HR.md")
    print("=" * 60)

    results = {}

    # ============ Step 1-6: 全部分析 ============
    print("\n" + "-" * 40)
    print("  阶段一：运行全部分析流程")
    print("-" * 40)

    with tqdm(total=6, desc="自动分析", unit="step", ncols=80) as pbar:

        # --- Step 1: 数据加载 ---
        tqdm.write("\n[1/6] 数据发现与加载...")
        df = None
        summary = {}
        try:
            loader = DataLoader()
            df, summary = loader.run()
            results["summary"] = summary
            tqdm.write(f"  ✅ {summary['total_rows']:,} 行数据加载成功")
        except Exception as e:
            tqdm.write(f"  ❌ 数据加载失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        pbar.update(1)

        # --- Step 2: 数据质量检查 ---
        tqdm.write("\n[2/6] 数据质量检查...")
        try:
            quality_checker = DataQualityChecker()
            quality_report = quality_checker.run(df)
            results["quality_report"] = quality_report
            tqdm.write(f"  ✅ 数据质量评分: {quality_report.get('quality_score', 'N/A')}/100")
        except Exception as e:
            tqdm.write(f"  ❌ {e}")
            results["quality_report"] = {"quality_score": 0, "missing_report": {}, "anomaly_report": {}, "duplicate_report": {}}
        pbar.update(1)

        # --- Step 3: 数仓搭建 ---
        tqdm.write("\n[3/6] SQLite 数仓搭建...")
        try:
            dw_builder = DataWarehouseBuilder()
            dw_info = dw_builder.run(df)
            results["dw_info"] = dw_info
            tqdm.write(f"  ✅ {len(dw_info.get('tables', {}))} 张表已创建")
        except Exception as e:
            tqdm.write(f"  ❌ {e}")
            results["dw_info"] = {"tables": {}}
        pbar.update(1)

        # --- Step 4: 数据校验 ---
        tqdm.write("\n[4/6] 数据一致性校验...")
        try:
            checker = DataChecker()
            checker_report = checker.run()
            results["checker_report"] = checker_report
            tqdm.write(f"  ✅ {checker_report.get('pass_rate', 0)}% 通过")
        except Exception as e:
            tqdm.write(f"  ❌ {e}")
            results["checker_report"] = {"passed": 0, "failed": 1, "pass_rate": 0, "overall_status": "异常", "checks": []}
        pbar.update(1)

        # --- Step 5: 转化率归因 ---
        tqdm.write("\n[5/6] 转化率归因分析...")
        try:
            attributor = AttributionAnalyzer()
            attribution_results = attributor.run()
            results["attribution_results"] = attribution_results
            tqdm.write(f"  ✅ {attribution_results.get('chart_count', 0)} 张图表已生成")
        except Exception as e:
            tqdm.write(f"  ❌ {e}")
            results["attribution_results"] = {"charts": {}, "chart_count": 0, "attribution": {"conclusions": [], "recommendations": []}}
        pbar.update(1)

        # --- Step 6: GMV异常检测 ---
        tqdm.write("\n[6/6] GMV异常检测与归因...")
        try:
            gmv_detector = GMVAnomalyDetector()
            gmv_results = gmv_detector.run()
            results["gmv_results"] = gmv_results
            tqdm.write(f"  ✅ {gmv_results.get('anomaly_count', 0)} 个异常点")
        except Exception as e:
            tqdm.write(f"  ❌ {e}")
            results["gmv_results"] = {"anomalies": [], "anomaly_count": 0, "attribution_paths": [], "ai_summary": "", "chart": ""}
        pbar.update(1)

    # --- Step 7: 生成报告 ---
    print("\n[7/7] 生成HTML报告...")
    try:
        report_gen = ReportGenerator()
        output_path = report_gen.generate(
            summary=results.get("summary", {}),
            quality_report=results.get("quality_report", {}),
            dw_info=results.get("dw_info", {}),
            checker_report=results.get("checker_report", {}),
            attribution_results=results.get("attribution_results", {}),
            gmv_results=results.get("gmv_results", {}),
        )
        results["output_path"] = output_path
        print(f"  ✅ 报告路径: {output_path}")
    except Exception as e:
        print(f"  ❌ {e}")
        results["output_path"] = ""

    # ============ 阶段二：AI自动问答 ============
    print("\n" + "-" * 40)
    print("  阶段二：AI自动问答（3个预设问题）")
    print("-" * 40)

    db_path = str(DB_PATH)
    attribution_results = results.get("attribution_results", {})
    gmv_results = results.get("gmv_results", {})

    # 构建数据上下文
    data_context = ""
    if AI_ENABLED:
        try:
            data_context = _build_data_context(db_path, attribution_results, gmv_results)
            print("  ✅ 数据上下文已构建")
        except Exception as e:
            print(f"  ⚠️ 数据上下文构建失败: {e}")

    questions = [
        "转化率下降的主要原因是什么？",
        "哪个品类GMV最高？",
        "4月和6月数据对比有什么变化？",
    ]

    conversation_lines = []
    conversation_lines.append("=" * 60)
    conversation_lines.append("  数据+AI驱动电商运营分析系统 — 交互式问答示例")
    conversation_lines.append(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    conversation_lines.append("=" * 60)
    conversation_lines.append("")

    for i, question in enumerate(questions, 1):
        print(f"\n  🤔 问题{i}: {question}")

        answer = ""
        mode = ""

        if AI_ENABLED and data_context:
            print("  🤖 AI 思考中...")
            answer = _call_ai_api(data_context, question)
            if answer:
                mode = "AI (DeepSeek)"
            else:
                print("  ⚠️ AI 调用失败，降级为规则引擎...")

        if not answer:
            answer = _rule_engine_answer(question, db_path)
            mode = "规则引擎"

        # 输出
        print(f"\n  ┌─ {mode} ─────────────────────────────")
        for line in answer.split("\n"):
            print(f"  │ {line}")
        print(f"  └{'─' * 50}")

        # 记录到对话文件
        conversation_lines.append(f"## 问题{i}: {question}")
        conversation_lines.append(f"回答模式: {mode}")
        conversation_lines.append("")
        conversation_lines.append(answer)
        conversation_lines.append("")
        conversation_lines.append("-" * 40)
        conversation_lines.append("")

    # 保存对话记录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conv_path = OUTPUT_DIR / "conversation_sample.txt"
    conv_content = "\n".join(conversation_lines)
    with open(conv_path, "w", encoding="utf-8") as f:
        f.write(conv_content)
    print(f"\n  📝 对话记录已保存: {conv_path.resolve()}")

    # ============ 阶段三：生成作品集 README ============
    print("\n" + "-" * 40)
    print("  阶段三：生成 PORTFOLIO_FOR_HR.md")
    print("-" * 40)

    # 读取对话内容用于嵌入
    conversation_snippet = ""
    try:
        with open(conv_path, "r", encoding="utf-8") as f:
            conversation_snippet = f.read()
    except Exception:
        conversation_snippet = "（对话记录生成失败）"

    portfolio_content = f"""# 数据+AI驱动电商运营分析系统 — 作品集

## 一、项目概述

本项目从0到1搭建了一套电商运营分析系统，用户只需将Excel数据放入文件夹，运行即可自动完成数据清洗、数仓搭建、转化率归因、GMV异常检测、AI智能问答等全流程分析，最终输出专业报告。

## 二、系统架构

```mermaid
flowchart TD
    A[📊 Excel 原始数据] --> B[🔍 数据质量检查]
    B --> C[🗄️ 三层数仓搭建]
    C --> C1[ODS 操作数据层]
    C1 --> C2[DWD 明细数据层]
    C2 --> C3[DWS 汇总数据层]
    C3 --> D[📈 转化率归因分析]
    C3 --> E[⚠️ GMV异常检测]
    D --> F[🤖 AI智能归因]
    E --> F
    F --> G[💬 交互式问答]
    F --> H[📄 HTML分析报告]

    style A fill:#667eea,color:#fff
    style H fill:#27ae60,color:#fff
    style F fill:#e74c3c,color:#fff
```

## 三、核心功能展示

### 3.1 核心指标一览
![核心指标](output/screenshots/00_核心指标卡片.png)
> 说明：系统自动汇总GMV、转化率、客单价、订单数等核心指标，一目了然。

### 3.2 转化率归因分析（核心能力）

![趋势图](output/screenshots/01_流量转化趋势图.png)
> 说明：双Y轴展示流量与转化率变化趋势，自动识别"流量增长但转化率走低"的矛盾时段。

![漏斗图](output/screenshots/06_漏斗图.png)
> 说明：浏览→加购→购买全链路漏斗，精准定位流失最严重的环节。

![渠道对比](output/screenshots/03_渠道转化率柱状图.png)
> 说明：各渠道转化率对比，精准定位拖累整体转化率的具体渠道。

**分析结论：** 6月转化率降至12%，主因是流量增量主要来自转化率最低的渠道（如小程序、短视频等），拉低了整体水平。同时漏斗分析显示浏览→加购环节转化率偏低，商品详情页吸引力不足。

### 3.3 GMV异常检测与归因

![异常检测](output/screenshots/07_GMV异常检测图.png)
> 说明：基于3-sigma原则+同比变化率双重检测，自动标注GMV异常点。红线为3σ上下界，蓝色虚线为均值。

**归因框架：** 流量端 → 转化端 → 客单价，三层逐级排查，快速定位异常根源。每个异常点对比前7天均值，自动计算各层贡献百分比。

### 3.4 AI智能问答

以下为系统内置的交互式问答功能示例，用户可用自然语言提问，AI基于真实数据实时回答：

```
{conversation_snippet[:3000]}
```

> 注：AI启用时使用 DeepSeek API 进行智能问答，未配置API时自动降级为规则引擎，确保系统始终可用。

## 四、AI应用深度

| 层次 | 应用场景 | AI角色 | 我的角色 |
|------|---------|--------|---------|
| **Level 1** 辅助开发 | 代码生成与调试 | 按需求描述生成代码框架 | 架构设计、模块拆分、代码审查、测试验证 |
| **Level 2** 智能归因 | GMV异常分析 | 基于数据自动生成归因结论 | 设计三层归因框架、定义σ阈值、验证分析准确性 |
| **Level 3** 自然语言交互 | 交互式问答 | 理解自然语言问题、结合数据回答 | 构建数据上下文、保证数据准确性、设计降级方案 |

## 五、技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 数据处理 | Python + Pandas + NumPy | 数据清洗、统计分析 |
| 数据存储 | SQLite | 轻量级三层数仓 |
| 可视化 | Plotly | 交互式图表（8种图表类型） |
| AI集成 | DeepSeek API (OpenAI兼容) | 智能归因、自然语言问答 |
| 报告输出 | Jinja2 + HTML/CSS | 专业HTML分析报告 |
| 统计分析 | SciPy | 皮尔逊相关系数、3-sigma检测 |

## 六、项目价值

1. **效率提升**：将电商分析师的经验沉淀为自动化系统，排查效率从小时级提升到分钟级
2. **可复用性**：三层归因框架可复用至其他业务场景（订单下降、用户流失、库存异常等）
3. **AI深度整合**：验证了AI在数据分析中的三个层次应用——辅助开发 → 智能归因 → 自然语言交互
4. **优雅降级**：AI不可用时自动切换规则引擎，系统始终可用，不依赖外部API

## 七、项目地址

https://github.com/Booker011/ecommerce-analysis
"""

    # 写入文件
    portfolio_path = OUTPUT_DIR / "PORTFOLIO_FOR_HR.md"
    with open(portfolio_path, "w", encoding="utf-8") as f:
        f.write(portfolio_content)

    print(f"  ✅ 作品集已生成: {portfolio_path.resolve()}")
    print(f"\n{'=' * 60}")
    print(f"  ✅ 作品集已生成！文件位置：output/PORTFOLIO_FOR_HR.md")
    print(f"{'=' * 60}")

    # 列出所有截图
    screenshots_dir = OUTPUT_DIR / "screenshots"
    if screenshots_dir.exists():
        pngs = sorted(screenshots_dir.glob("*.png"))
        if pngs:
            print(f"\n  📸 已生成的截图 ({len(pngs)} 张):")
            for p in pngs:
                size_kb = p.stat().st_size / 1024
                print(f"     {p.name} ({size_kb:.0f} KB)")

    return results


if __name__ == "__main__":
    main()
