#!/usr/bin/env python3
"""
================================================================================
 数据+AI驱动电商运营分析系统
================================================================================
 用户只需把 Excel 文件放入 data/ 文件夹，运行本脚本即可自动完成：
   1. 环境检查与数据发现
   2. 数据质量检查
   3. SQLite 数仓自动搭建
   4. 数据一致性校验
   5. 转化率归因分析（6张图表 + 3-5条建议）
   6. GMV异常波动检测与AI归因
   💬 交互式问答环节
   7. 生成专业HTML分析报告

 输出: output/analysis_report.html
================================================================================
"""

import sys
import os
import sqlite3
import traceback
from datetime import datetime

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
# 交互式问答模块
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
    """从 DWS 层提取关键数据，构建给 AI 的上下文。

    Returns:
        str: 结构化数据上下文文本
    """
    parts = ["## 当前电商数据概况\n"]

    # 1. GMV 汇总
    try:
        df = _query_dws(db_path, """
            SELECT date, gmv, order_count, asp, uv, arpu
            FROM dws_gmv_daily
            ORDER BY date
        """)
        if not df.empty:
            total_gmv = df["gmv"].sum()
            avg_daily_gmv = df["gmv"].mean()
            parts.append(f"### GMV数据")
            parts.append(f"- 总GMV: RMB {total_gmv:,.0f}")
            parts.append(f"- 日均GMV: RMB {avg_daily_gmv:,.0f}")
            parts.append(f"- 最近7天GMV趋势: {df['gmv'].tail(7).tolist()}")
            parts.append(f"- 客单价(A SP)均值: RMB {df['asp'].mean():.1f}")
    except Exception:
        pass

    # 2. 转化率数据
    try:
        df = _query_dws(db_path, """
            SELECT date, overall_conversion_rate, view_to_cart_rate,
                   cart_to_purchase_rate, view_to_purchase_rate
            FROM dws_conversion_daily
            ORDER BY date
        """)
        if not df.empty:
            parts.append(f"\n### 转化率数据")
            parts.append(f"- 整体转化率均值: {df['overall_conversion_rate'].mean():.2f}%")
            parts.append(f"- 浏览→加购率均值: {df['view_to_cart_rate'].mean():.2f}%")
            parts.append(f"- 加购→购买率均值: {df['cart_to_purchase_rate'].mean():.2f}%")
            parts.append(f"- 最近7天转化率趋势: {df['overall_conversion_rate'].tail(7).tolist()}")
    except Exception:
        pass

    # 3. 流量数据
    try:
        df = _query_dws(db_path, """
            SELECT date, pv, uv FROM dws_traffic_daily ORDER BY date
        """)
        if not df.empty:
            parts.append(f"\n### 流量数据")
            parts.append(f"- 总PV: {df['pv'].sum():,}")
            parts.append(f"- 日均PV: {df['pv'].mean():.0f}")
            parts.append(f"- 日均UV: {df['uv'].mean():.0f}")
            parts.append(f"- 最近7天PV趋势: {df['pv'].tail(7).tolist()}")
    except Exception:
        pass

    # 4. 品类数据
    try:
        df = _query_dws(db_path, """
            SELECT category,
                   SUM(total_events) as total,
                   SUM(gmv) as gmv,
                   ROUND(CAST(SUM(purchase_count) AS FLOAT) / SUM(total_events) * 100, 2) as conversion_rate
            FROM dws_category_daily
            GROUP BY category
            ORDER BY gmv DESC
        """)
        if not df.empty:
            parts.append(f"\n### 品类数据")
            for _, row in df.iterrows():
                parts.append(f"- {row['category']}: GMV RMB {row['gmv']:,.0f}, 转化率 {row['conversion_rate']:.1f}%")
    except Exception:
        pass

    # 5. GMV 异常检测结果
    anomalies = gmv_results.get("anomalies", [])
    if anomalies:
        parts.append(f"\n### GMV异常点 ({len(anomalies)}个)")
        for a in anomalies[:5]:
            parts.append(f"- {a['date']}: GMV RMB {a['gmv']:,.0f} ({a['type']}), "
                         f"偏差 {a['sigma_deviation']}σ, 日环比 {a['change_rate']}%")

    # 6. 归因结论
    attribution = attribution_results.get("attribution", {})
    conclusions = attribution.get("conclusions", [])
    if conclusions:
        parts.append(f"\n### 已有归因结论")
        for c in conclusions[:5]:
            parts.append(f"- {c}")

    return "\n".join(parts)


def _call_ai_api(context: str, question: str) -> str:
    """调用 DeepSeek API 基于数据回答问题。

    Args:
        context: 数据上下文
        question: 用户问题

    Returns:
        str: AI 回答
    """
    try:
        from openai import OpenAI
    except ImportError:
        return ""  # 触发降级

    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        prompt = f"""你是一位资深的电商数据分析师。请基于以下真实数据，用中文回答用户的问题。

数据是绝对真实的，你必须严格基于数据回答，不要编造任何不在数据中的事实。
如果数据不足以回答某个问题，请诚实说明。

{context}

用户问题: {question}

请简洁专业地回答（控制在200字以内），如果涉及具体数字请引用数据。"""

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是电商数据分析专家，必须严格基于提供的数据回答问题，不编造事实。使用中文回复，保持简洁。"},
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


def _rule_engine_answer(question: str, db_path: str, attribution_results: dict, gmv_results: dict) -> str:
    """规则引擎：根据关键词匹配返回预设回答模板。

    Args:
        question: 用户问题
        db_path: 数据库路径
        attribution_results: 归因分析结果
        gmv_results: GMV分析结果

    Returns:
        str: 规则引擎生成的回答
    """
    q = question.lower()
    answers = []

    # === 转化率相关 ===
    if any(kw in q for kw in ["转化率", "转化", "conversion", "漏斗"]):
        try:
            df = _query_dws(db_path, """
                SELECT date, overall_conversion_rate, view_to_cart_rate,
                       cart_to_purchase_rate, view_to_purchase_rate
                FROM dws_conversion_daily ORDER BY date
            """)
            if not df.empty:
                df["month"] = pd.to_datetime(df["date"]).dt.month
                monthly = df.groupby("month")["overall_conversion_rate"].mean()
                answers.append("📊 **转化率分析**：")
                for m, rate in monthly.items():
                    answers.append(f"  · {m}月整体转化率: {rate:.2f}%")
                answers.append(f"  · 整体均值: {df['overall_conversion_rate'].mean():.2f}%")
                answers.append(f"  · 浏览→加购率: {df['view_to_cart_rate'].mean():.2f}%")
                answers.append(f"  · 加购→购买率: {df['cart_to_purchase_rate'].mean():.2f}%")

                # 趋势判断
                if len(monthly) >= 2:
                    first = monthly.iloc[0]
                    last = monthly.iloc[-1]
                    if last < first:
                        answers.append(f"  · ⚠️ 转化率呈下降趋势（{first:.1f}% → {last:.1f}%），需关注。")
            else:
                answers.append("📊 暂无转化率数据。")
        except Exception as e:
            answers.append(f"转化率数据查询失败: {e}")

    # === 渠道相关 ===
    if any(kw in q for kw in ["渠道", "channel", "抖音", "微信", "淘宝", "京东", "小红书", "organic"]):
        try:
            df = _query_dws(db_path, """
                SELECT channel, COUNT(*) as pv,
                       SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) as purchases,
                       ROUND(CAST(SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS FLOAT)/COUNT(*)*100, 2) as cr
                FROM dwd_user_behavior_detail
                GROUP BY channel ORDER BY pv DESC
            """)
            if not df.empty:
                answers.append("📡 **渠道分析**：")
                for _, row in df.iterrows():
                    answers.append(f"  · {row['channel']}: PV {row['pv']:,}, 转化率 {row['cr']:.1f}%")
                best = df.loc[df["cr"].idxmax()]
                answers.append(f"  · 🏆 转化率最高: {best['channel']} ({best['cr']:.1f}%)")
            else:
                answers.append("📡 暂无渠道数据。")
        except Exception as e:
            answers.append(f"渠道数据查询失败: {e}")

    # === GMV / 异常 / 下降 ===
    if any(kw in q for kw in ["gmv", "销售额", "收入", "异常", "下降", "下跌", "波动", "decline"]):
        try:
            df = _query_dws(db_path, "SELECT date, gmv, order_count, asp FROM dws_gmv_daily ORDER BY date")
            if not df.empty:
                total = df["gmv"].sum()
                avg = df["gmv"].mean()
                answers.append("💰 **GMV分析**：")
                answers.append(f"  · 总GMV: RMB {total:,.0f}")
                answers.append(f"  · 日均GMV: RMB {avg:,.0f}")
                answers.append(f"  · 日均订单数: {df['order_count'].mean():.0f}")
                answers.append(f"  · 客单价均值: RMB {df['asp'].mean():.1f}")

                df["month"] = pd.to_datetime(df["date"]).dt.month
                monthly_gmv = df.groupby("month")["gmv"].sum()
                if len(monthly_gmv) >= 2:
                    answers.append(f"  · 各月GMV: " + ", ".join([f"{m}月 RMB {v:,.0f}" for m, v in monthly_gmv.items()]))
        except Exception as e:
            answers.append(f"GMV数据查询失败: {e}")

        # 附上异常检测结果
        anomalies = gmv_results.get("anomalies", [])
        if anomalies:
            answers.append(f"\n⚠️ **异常检测**: 发现 {len(anomalies)} 个异常点：")
            for a in anomalies[:5]:
                answers.append(f"  · {a['date']}: {a['type']}, GMV RMB {a['gmv']:,.0f}")
        else:
            answers.append("\n✅ **异常检测**: 未发现明显异常。")

    # === 促销 ===
    if any(kw in q for kw in ["促销", "活动", "promo", "promotion", "6月15", "6月"]):
        answers.append("🎯 **促销活动分析（6月15-20日）**：")
        try:
            df = _query_dws(db_path, """
                SELECT date, pv, uv, event_view, event_cart, event_purchase
                FROM dws_traffic_daily
                WHERE date BETWEEN '2026-06-15' AND '2026-06-20'
                ORDER BY date
            """)
            if not df.empty:
                for _, row in df.iterrows():
                    answers.append(f"  · {row['date']}: PV {row.get('pv', 'N/A')}, UV {row.get('uv', 'N/A')}")

            # 促销转化率
            promo_conv = _query_dws(db_path, """
                SELECT AVG(overall_conversion_rate) as avg_cr
                FROM dws_conversion_daily
                WHERE date BETWEEN '2026-06-15' AND '2026-06-20'
            """)
            if not promo_conv.empty:
                answers.append(f"  · 促销期平均转化率: {promo_conv['avg_cr'].iloc[0]:.2f}%")

            # 对比促销前后
            before_conv = _query_dws(db_path, """
                SELECT AVG(overall_conversion_rate) as avg_cr
                FROM dws_conversion_daily
                WHERE date BETWEEN '2026-06-08' AND '2026-06-14'
            """)
            if not before_conv.empty:
                answers.append(f"  · 促销前一周转化率: {before_conv['avg_cr'].iloc[0]:.2f}%")
        except Exception as e:
            answers.append(f"促销数据查询失败: {e}")

        answers.append("  · 结论: 促销期间流量暴增但转化率骤降，可能存在「薅羊毛」流量或用户只浏览不购买。")

    # === 品类相关 ===
    if any(kw in q for kw in ["品类", "类目", "category", "服装", "数码", "食品", "美妆", "家居"]):
        try:
            df = _query_dws(db_path, """
                SELECT category,
                       SUM(total_events) as total,
                       SUM(gmv) as gmv,
                       SUM(purchase_count) as purchases,
                       ROUND(CAST(SUM(purchase_count) AS FLOAT)/SUM(total_events)*100, 2) as cr
                FROM dws_category_daily
                GROUP BY category ORDER BY gmv DESC
            """)
            if not df.empty:
                answers.append("🏷️ **品类分析**：")
                for _, row in df.iterrows():
                    answers.append(f"  · {row['category']}: GMV RMB {row['gmv']:,.0f}, "
                                   f"购买{int(row['purchases'])}次, 转化率 {row['cr']:.1f}%")
                best = df.loc[df["cr"].idxmax()]
                worst = df.loc[df["cr"].idxmin()]
                answers.append(f"  · 🏆 转化率最高: {best['category']} ({best['cr']:.1f}%)")
                answers.append(f"  · ⚠️ 转化率最低: {worst['category']} ({worst['cr']:.1f}%)")
        except Exception as e:
            answers.append(f"品类数据查询失败: {e}")

    # === 用户 / 复购 ===
    if any(kw in q for kw in ["用户", "复购", "留存", "user", "retention", "repurchase"]):
        try:
            df = _query_dws(db_path, """
                SELECT date, active_users, new_users, repurchase_rate, retention_rate_next_day
                FROM dws_user_daily ORDER BY date
            """)
            if not df.empty:
                answers.append("👤 **用户分析**：")
                answers.append(f"  · 日均活跃用户: {df['active_users'].mean():.0f}")
                answers.append(f"  · 日均新增用户: {df['new_users'].mean():.0f}")
                answers.append(f"  · 复购率均值: {df['repurchase_rate'].mean():.1f}%")
                answers.append(f"  · 次日留存率均值: {df['retention_rate_next_day'].mean():.1f}%")
        except Exception as e:
            answers.append(f"用户数据查询失败: {e}")

    # === 概览 / 总结 ===
    if any(kw in q for kw in ["概览", "总结", "summary", "整体", "概况", "全部"]) or not answers:
        if not answers:
            answers.append("📋 **数据概览**：")
        try:
            df_gmv = _query_dws(db_path, "SELECT SUM(gmv) as gmv, SUM(order_count) as orders FROM dws_gmv_daily")
            df_conv = _query_dws(db_path, "SELECT AVG(overall_conversion_rate) as cr FROM dws_conversion_daily")
            df_traffic = _query_dws(db_path, "SELECT SUM(pv) as pv, SUM(uv) as uv FROM dws_traffic_daily")

            if not df_gmv.empty:
                answers.append(f"  · 总GMV: RMB {df_gmv['gmv'].iloc[0]:,.0f}")
                answers.append(f"  · 总订单: {int(df_gmv['orders'].iloc[0]):,}")
            if not df_conv.empty:
                answers.append(f"  · 整体转化率: {df_conv['cr'].iloc[0]:.2f}%")
            if not df_traffic.empty:
                answers.append(f"  · 总PV: {int(df_traffic['pv'].iloc[0]):,}")
        except Exception as e:
            answers.append(f"数据查询失败: {e}")

        # 加归因结论
        attribution = attribution_results.get("attribution", {})
        conclusions = attribution.get("conclusions", [])
        if conclusions:
            answers.append(f"\n💡 **关键发现**：")
            for c in conclusions[:3]:
                answers.append(f"  · {c}")

    return "\n".join(answers) if answers else "抱歉，我没有理解你的问题。请尝试问关于转化率、渠道、GMV、品类、用户、促销等方面的问题。"


def interactive_qa(db_path: str, attribution_results: dict, gmv_results: dict):
    """交互式问答环节：用户输入自然语言问题，系统基于数据回答。

    Args:
        db_path: SQLite 数据库路径
        attribution_results: 归因分析结果
        gmv_results: GMV异常检测结果
    """
    print("\n" + "=" * 60)
    print("  💬 交互式问答")
    print("=" * 60)
    print("  你可以问我关于这份数据的任何问题，例如：")
    print("    · 转化率为什么下降？")
    print("    · 哪个渠道表现最好？")
    print("    · 促销活动期间数据怎么样？")
    print("    · 各品类的GMV和转化率对比")
    print("    · 有哪些GMV异常点？")
    print("  输入 'exit' 或 'quit' 退出问答。")
    print("=" * 60)

    # 对话记录文件
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conv_file = OUTPUT_DIR / "conversation.txt"

    # 预加载数据上下文（供AI模式使用）
    data_context = ""
    if AI_ENABLED:
        try:
            data_context = _build_data_context(db_path, attribution_results, gmv_results)
        except Exception as e:
            print(f"  [警告] 数据上下文构建失败: {e}")

    round_num = 0
    while True:
        try:
            # 读取用户输入
            user_input = input(f"\n  🤔 你的问题 (exit 退出): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  问答结束。")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q", "退出"):
            print("  问答结束，继续生成报告...")
            break

        round_num += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 记录用户问题
        with open(conv_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] 用户: {user_input}\n")

        # 尝试 AI 模式
        answer = ""
        mode = ""

        if AI_ENABLED and data_context:
            print("  🤖 AI 思考中...")
            answer = _call_ai_api(data_context, user_input)
            if answer:
                mode = "AI (DeepSeek)"
            else:
                print("  ⚠️ AI 调用失败，降级为规则引擎...")

        # 降级为规则引擎
        if not answer:
            answer = _rule_engine_answer(user_input, db_path, attribution_results, gmv_results)
            mode = "规则引擎"

        # 输出回答
        print(f"\n  ┌─ {mode} ─────────────────────────────")
        for line in answer.split("\n"):
            print(f"  │ {line}")
        print(f"  └{'─' * 50}")

        # 记录AI回答
        with open(conv_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] AI ({mode}): {answer}\n")
            f.write("\n")

    print(f"\n  📝 对话记录已保存到: {conv_file.resolve()}")


# ============================================
# 主流程
# ============================================

def main():
    """主执行流程：依次执行 6 步自动分析 → 交互式问答 → 第 7 步报告生成。"""
    print("\n" + "=" * 60)
    print("  🚀 数据+AI驱动电商运营分析系统 v1.0")
    print("=" * 60)
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  AI模式:   {'🤖 DeepSeek AI 已启用' if AI_ENABLED else '📏 规则引擎模式'}")
    print("=" * 60)

    results = {}
    errors = []

    # ============================================
    # 前 6 步：自动分析（进度条）
    # ============================================
    with tqdm(total=6, desc="自动分析", unit="step", ncols=80,
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]") as pbar:

        # --- Step 1 ---
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [1/6] 环境检查与数据发现")
        tqdm.write("─" * 50)

        df = None
        summary = {}
        try:
            loader = DataLoader()
            df, summary = loader.run()
            results["summary"] = summary
            results["df"] = df
            tqdm.write(f"  ✅ Step 1 完成 — {summary['total_rows']:,} 行数据加载成功")
        except Exception as e:
            tqdm.write(f"  ❌ Step 1 失败: {e}")
            errors.append(f"Step 1: {e}")
            traceback.print_exc()
            _exit_with_error("数据加载失败，请检查 data/ 目录下是否有合法的 .xlsx 文件。")
        pbar.update(1)

        # --- Step 2 ---
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [2/6] 数据质量检查")
        tqdm.write("─" * 50)

        try:
            quality_checker = DataQualityChecker()
            quality_report = quality_checker.run(df)
            results["quality_report"] = quality_report
            tqdm.write(f"  ✅ Step 2 完成 — 数据质量评分: {quality_report.get('quality_score', 'N/A')}/100")
        except Exception as e:
            tqdm.write(f"  ❌ Step 2 失败: {e}")
            errors.append(f"Step 2: {e}")
            results["quality_report"] = {
                "quality_score": 0, "error": str(e),
                "missing_report": {}, "anomaly_report": {}, "duplicate_report": {},
            }
        pbar.update(1)

        # --- Step 3 ---
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [3/6] SQLite 数仓自动搭建")
        tqdm.write("─" * 50)

        dw_builder = DataWarehouseBuilder()
        try:
            dw_info = dw_builder.run(df)
            results["dw_info"] = dw_info
            table_count = len(dw_info.get("tables", {}))
            tqdm.write(f"  ✅ Step 3 完成 — {table_count} 张表已创建")
        except Exception as e:
            tqdm.write(f"  ❌ Step 3 失败: {e}")
            errors.append(f"Step 3: {e}")
            traceback.print_exc()
            results["dw_info"] = {"error": str(e), "tables": {}}
        pbar.update(1)

        # --- Step 4 ---
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [4/6] 数据一致性校验")
        tqdm.write("─" * 50)

        try:
            checker = DataChecker()
            checker_report = checker.run()
            results["checker_report"] = checker_report
            tqdm.write(f"  ✅ Step 4 完成 — {checker_report.get('pass_rate', 0)}% 通过")
        except Exception as e:
            tqdm.write(f"  ❌ Step 4 失败: {e}")
            errors.append(f"Step 4: {e}")
            results["checker_report"] = {
                "passed": 0, "failed": 1, "pass_rate": 0,
                "overall_status": f"校验异常: {e}", "checks": [], "error": str(e),
            }
        pbar.update(1)

        # --- Step 5 ---
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [5/6] 转化率归因分析（核心模块）")
        tqdm.write("─" * 50)

        try:
            attributor = AttributionAnalyzer()
            attribution_results = attributor.run()
            results["attribution_results"] = attribution_results
            chart_count = attribution_results.get("chart_count", 0)
            tqdm.write(f"  ✅ Step 5 完成 — {chart_count} 张图表已生成")
        except Exception as e:
            tqdm.write(f"  ❌ Step 5 失败: {e}")
            errors.append(f"Step 5: {e}")
            traceback.print_exc()
            results["attribution_results"] = {
                "charts": {}, "chart_count": 0,
                "attribution": {"conclusions": [], "recommendations": []},
                "error": str(e),
            }
        pbar.update(1)

        # --- Step 6 ---
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [6/6] GMV异常波动检测与AI归因")
        tqdm.write("─" * 50)

        try:
            gmv_detector = GMVAnomalyDetector()
            gmv_results = gmv_detector.run()
            results["gmv_results"] = gmv_results
            anomaly_count = gmv_results.get("anomaly_count", 0)
            ai_mode = gmv_results.get("ai_mode", "未知")
            tqdm.write(f"  ✅ Step 6 完成 — {anomaly_count} 个异常点, 归因: {ai_mode}")
        except Exception as e:
            tqdm.write(f"  ❌ Step 6 失败: {e}")
            errors.append(f"Step 6: {e}")
            traceback.print_exc()
            results["gmv_results"] = {
                "anomalies": [], "anomaly_count": 0,
                "attribution_paths": [], "ai_summary": "", "ai_mode": "失败",
                "chart": "", "error": str(e),
            }
        pbar.update(1)

    # ============================================
    # 交互式问答（进度条之外）
    # ============================================
    try:
        interactive_qa(
            db_path=str(DB_PATH),
            attribution_results=results.get("attribution_results", {}),
            gmv_results=results.get("gmv_results", {}),
        )
    except Exception as e:
        print(f"\n  ⚠️ 交互式问答环节异常（不影响报告生成）: {e}")
        traceback.print_exc()

    # ============================================
    # Step 7: 生成HTML报告
    # ============================================
    print("\n" + "─" * 50)
    print("  [7/7] 生成HTML分析报告")
    print("─" * 50)

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
        print(f"  ✅ Step 7 完成 — 报告路径: {output_path}")
    except Exception as e:
        print(f"  ❌ Step 7 失败: {e}")
        errors.append(f"Step 7: {e}")
        traceback.print_exc()
        results["output_path"] = ""

    # ============================================
    # 完成
    # ============================================
    print("\n" + "=" * 60)
    print("  🎉 分析完成！")
    print("=" * 60)

    if errors:
        print(f"  ⚠️  {len(errors)} 个步骤出现异常（已降级处理）:")
        for err in errors:
            print(f"     - {err}")

    output_path = results.get("output_path", "")
    if output_path and os.path.exists(output_path):
        print(f"\n  📄 报告路径: {output_path}")
        print(f"  💡 用浏览器打开即可查看完整分析报告。")
        try:
            import webbrowser
            webbrowser.open(f"file:///{output_path}")
            print(f"  🌐 已尝试在浏览器中自动打开报告。")
        except Exception:
            pass
    else:
        print(f"\n  ⚠️ 报告生成失败。请检查上方错误信息。")

    if not AI_ENABLED:
        print(f"\n  💡 提示：配置 DEEPSEEK_API_KEY 到 .env 文件可启用AI归因分析功能。")

    print("\n" + "=" * 60)
    return results


def _exit_with_error(message: str):
    """打印错误信息并退出。"""
    print(f"\n{'='*60}")
    print(f"  ❌ 致命错误: {message}")
    print(f"{'='*60}")
    print(f"  请检查:")
    print(f"  1. data/ 文件夹中是否存在 .xlsx 文件")
    print(f"  2. Excel 文件是否包含必要的中/英文字段")
    print(f"  3. 依赖是否已安装: pip install -r requirements.txt")
    sys.exit(1)


if __name__ == "__main__":
    main()
