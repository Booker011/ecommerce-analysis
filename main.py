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
   7. 生成专业HTML分析报告

 输出: output/analysis_report.html
================================================================================
"""

import sys
import os
import traceback
from datetime import datetime

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tqdm import tqdm

from config import AI_ENABLED, OUTPUT_DIR
from src.data_loader import DataLoader
from src.data_quality import DataQualityChecker
from src.dw_builder import DataWarehouseBuilder
from src.data_checker import DataChecker
from src.attribution_analysis import AttributionAnalyzer
from src.gmv_anomaly import GMVAnomalyDetector
from src.report_generator import ReportGenerator


def main():
    """主执行流程：依次执行7个步骤。"""
    print("\n" + "=" * 60)
    print("  🚀 数据+AI驱动电商运营分析系统 v1.0")
    print("=" * 60)
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  AI模式:   {'🤖 DeepSeek AI 已启用' if AI_ENABLED else '📏 规则引擎模式'}")
    print("=" * 60)

    # 各步骤结果容器
    results = {}
    errors = []

    # 总进度条（7个步骤）
    with tqdm(total=7, desc="总体进度", unit="step", ncols=80,
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]") as pbar:

        # ========================================
        # Step 1: 环境检查与数据发现
        # ========================================
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [1/7] 环境检查与数据发现")
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
            # 无法继续，直接退出
            _exit_with_error("数据加载失败，请检查 data/ 目录下是否有合法的 .xlsx 文件。")

        pbar.update(1)

        # ========================================
        # Step 2: 数据质量检查
        # ========================================
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [2/7] 数据质量检查")
        tqdm.write("─" * 50)

        try:
            quality_checker = DataQualityChecker()
            quality_report = quality_checker.run(df)
            results["quality_report"] = quality_report
            tqdm.write(f"  ✅ Step 2 完成 — 数据质量评分: {quality_report.get('quality_score', 'N/A')}/100")
        except Exception as e:
            tqdm.write(f"  ❌ Step 2 失败: {e}")
            errors.append(f"Step 2: {e}")
            # 降级：使用空报告继续
            results["quality_report"] = {
                "quality_score": 0,
                "error": str(e),
                "missing_report": {},
                "anomaly_report": {},
                "duplicate_report": {},
            }

        pbar.update(1)

        # ========================================
        # Step 3: SQLite 数仓自动搭建
        # ========================================
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [3/7] SQLite 数仓自动搭建")
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

        # ========================================
        # Step 4: 数据一致性校验
        # ========================================
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [4/7] 数据一致性校验")
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

        # ========================================
        # Step 5: 转化率归因分析
        # ========================================
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [5/7] 转化率归因分析（核心模块）")
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

        # ========================================
        # Step 6: GMV异常检测与AI归因
        # ========================================
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [6/7] GMV异常波动检测与AI归因")
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

        # ========================================
        # Step 7: 生成HTML报告
        # ========================================
        tqdm.write("\n" + "─" * 50)
        tqdm.write("  [7/7] 生成HTML分析报告")
        tqdm.write("─" * 50)

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
            tqdm.write(f"  ✅ Step 7 完成 — 报告路径: {output_path}")
        except Exception as e:
            tqdm.write(f"  ❌ Step 7 失败: {e}")
            errors.append(f"Step 7: {e}")
            traceback.print_exc()
            results["output_path"] = ""

        pbar.update(1)

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

        # 尝试自动打开
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
