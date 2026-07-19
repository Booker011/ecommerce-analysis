# 📊 数据+AI驱动电商运营分析系统

> **一键运行**：把 Excel 放入 `data/` → 运行 `python main.py` → 拿到专业 HTML 分析报告

## ✨ 功能特性

- 🔍 **智能数据发现**：自动扫描 Excel，中英文字段名智能识别与映射
- ✅ **数据质量检查**：缺失值、异常值、重复检测，输出百分制质量评分
- 🏗️ **SQLite 数仓自动搭建**：ODS → DWD → DWS 三层架构，6张汇总表覆盖"人-货-场"15+分析维度
- 📈 **转化率归因分析**：6张专业图表 + 多维度下钻 + 漏斗分析 + 优化建议
- ⚠️ **GMV异常检测**：3-sigma + 同比变化率双重检测 + 三层归因框架
- 🤖 **AI智能归因**：可选 DeepSeek API，自动降级为规则引擎
- 📄 **专业HTML报告**：渐变卡片、斑马纹表格、Base64嵌入图表、响应式布局

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备数据

将电商数据 Excel 文件（`.xlsx`）放入 `data/` 文件夹。

Excel 需包含以下字段（**支持中英文两种列名**）：

| 英文名 | 中文名 | 说明 |
|---|---|---|
| order_id | 订单ID | 订单编号 |
| user_id | 用户ID | 用户编号 |
| product_id | 商品ID | 商品编号 |
| category | 品类/商品类别 | 商品分类 |
| event_type | 事件类型 | view/cart/purchase 或 浏览/加购/购买 |
| price | 单价/价格 | 商品价格 |
| quantity | 数量 | 购买数量（可选，默认1） |
| event_time | 事件时间 | 行为发生时间 |
| channel | 渠道 | 流量来源（可选，默认organic） |
| device | 设备 | 设备类型（可选，默认unknown） |

### 3. （可选）配置 AI 归因

```bash
# 复制环境变量文件
cp .env.example .env

# 编辑 .env，填入你的 DeepSeek API Key
DEEPSEEK_API_KEY=sk-your-key-here
```

> 不配置 API Key 也可以正常运行，系统会自动降级为**规则引擎模式**。

### 4. 一键运行

```bash
python main.py
```

### 5. 查看报告

打开 `output/analysis_report.html`，用浏览器即可查看完整分析报告。

## 📁 项目结构

```
ecommerce_analysis/
├── main.py                  # 主入口，一键运行
├── config.py                # 全局配置、字体检测、字段映射
├── .env.example             # 环境变量示例
├── requirements.txt         # Python 依赖
├── README.md                # 本文件
├── src/
│   ├── __init__.py
│   ├── data_loader.py       # 数据加载与预处理
│   ├── data_quality.py      # 数据质量检查
│   ├── dw_builder.py        # SQLite数仓自动搭建
│   ├── data_checker.py      # 数据一致性校验
│   ├── attribution_analysis.py  # 转化率归因分析（核心）
│   ├── gmv_anomaly.py       # GMV异常检测与AI归因
│   └── report_generator.py  # HTML报告生成
├── data/                    # 放Excel文件的目录
│   └── .gitkeep
└── output/                  # 报告输出目录
    └── .gitkeep
```

## 📊 分析维度矩阵

| 维度 | 数据表 | 核心指标 |
|---|---|---|
| 🏪 场-流量 | dws_traffic_daily | PV、UV、渠道分布、设备分布 |
| 🏪 场-转化 | dws_conversion_daily | 浏览/加购/支付转化率 |
| 👤 人-增长 | dws_user_daily | 新增用户、活跃用户、留存率 |
| 👤 人-价值 | dws_user_daily | 复购率、ARPU |
| 📦 货-商品 | dws_product_daily | 动销率、Top10商品 |
| 📦 货-品类 | dws_category_daily | 品类GMV、品类转化率 |
| 💵 综合 | dws_gmv_daily | GMV、客单价、订单数 |

## 🛠️ 技术栈

- **数据处理**：pandas, numpy, scipy
- **数据库**：SQLite 3（零依赖，无需安装）
- **可视化**：plotly（Base64嵌入HTML，离线可查看）
- **报告模板**：jinja2
- **AI接口**：openai（兼容 DeepSeek API）
- **进度条**：tqdm

## ❓ 常见问题

**Q: 没有 AI API Key 怎么办？**
A: 不影响使用！系统会自动降级为规则引擎模式，同样会给出专业的归因分析。

**Q: 图表中文显示为方块？**
A: 系统会自动检测系统中文字体（Windows: Microsoft YaHei, Mac: PingFang SC），一般不需要手动配置。

**Q: 数据格式有要求吗？**
A: 只要 Excel 中包含必要字段（order_id, user_id, product_id, event_type, price, event_time），系统会自动识别中英文列名并做映射。

**Q: 报告太大打不开？**
A: 图表以 Base64 嵌入，文件通常为 1-5MB。如果数据量特别大，可能需要几秒渲染。
