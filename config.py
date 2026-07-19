"""
配置文件
------
项目全局配置、路径管理和中文字体自动检测。
"""

import os
import sys
import platform
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

# ============================================
# 项目路径配置
# ============================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "ecommerce_dw.db"

# 确保必要目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================
# AI API 配置（可选）
# ============================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
# 标记是否有 AI 能力
AI_ENABLED = bool(DEEPSEEK_API_KEY)

# ============================================
# 中文字体自动检测
# ============================================
SYSTEM_PLATFORM = platform.system()

# Windows / macOS / Linux 常见中文字体优先级列表
_FONT_CANDIDATES = {
    "Windows": ["Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "FangSong"],
    "Darwin": ["PingFang SC", "PingFang HK", "Heiti SC", "STHeiti", "Apple LiGothic"],
    "Linux": ["WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Noto Sans CJK SC", "Source Han Sans SC"],
}

# 尝试导入 matplotlib 检测可用字体（如果已安装）
def _detect_chinese_font() -> str:
    """自动检测系统中可用的中文字体，返回字体名称。"""
    candidates = _FONT_CANDIDATES.get(SYSTEM_PLATFORM, _FONT_CANDIDATES["Windows"])

    # 方法1：通过 matplotlib 字体列表检测
    try:
        from matplotlib.font_manager import FontManager
        fm = FontManager()
        available_fonts = {f.name for f in fm.ttflist}
        for font in candidates:
            if font in available_fonts:
                return font
    except ImportError:
        pass

    # 方法2：通过系统字体目录检测
    if SYSTEM_PLATFORM == "Windows":
        font_dir = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
    elif SYSTEM_PLATFORM == "Darwin":
        font_dir = Path("/System/Library/Fonts")
    else:
        font_dir = Path("/usr/share/fonts")

    # 尝试部分匹配
    partial_map = {
        "Microsoft YaHei": ["msyh", "yahei"],
        "SimHei": ["simhei"],
        "PingFang SC": ["PingFang", "pingfang"],
        "WenQuanYi Micro Hei": ["wqy-microhei", "wenquanyi"],
    }
    if font_dir.exists():
        for font_file in font_dir.rglob("*.ttf") if font_dir.is_dir() else []:
            fname = font_file.stem.lower()
            for font_name, keywords in partial_map.items():
                if any(kw in fname for kw in keywords):
                    return font_name

    # 兜底：返回候选列表第一个
    return candidates[0]


CHINESE_FONT = _detect_chinese_font()

# Plotly 图表通用布局配置
PLOTLY_FONT_CONFIG = dict(
    family=CHINESE_FONT,
    size=13,
    color="#333333",
)
PLOTLY_TITLE_FONT_CONFIG = dict(
    family=CHINESE_FONT,
    size=18,
    color="#1a1a2e",
)

# ============================================
# Excel 列名映射（中文 → 英文）
# ============================================
COLUMN_MAPPING = {
    # 订单ID
    "订单ID": "order_id",
    "订单编号": "order_id",
    "订单号": "order_id",
    "order_id": "order_id",
    # 用户ID
    "用户ID": "user_id",
    "用户编号": "user_id",
    "会员ID": "user_id",
    "user_id": "user_id",
    # 商品ID
    "商品ID": "product_id",
    "商品编号": "product_id",
    "产品ID": "product_id",
    "product_id": "product_id",
    # 品类
    "品类": "category",
    "商品类别": "category",
    "类目": "category",
    "分类": "category",
    "category": "category",
    # 事件类型
    "事件类型": "event_type",
    "行为类型": "event_type",
    "event_type": "event_type",
    # 价格
    "单价": "price",
    "价格": "price",
    "售价": "price",
    "price": "price",
    # 数量
    "数量": "quantity",
    "件数": "quantity",
    "quantity": "quantity",
    # 事件时间
    "事件时间": "event_time",
    "时间": "event_time",
    "行为时间": "event_time",
    "event_time": "event_time",
    # 渠道
    "渠道": "channel",
    "来源": "channel",
    "channel": "channel",
    # 设备
    "设备": "device",
    "设备类型": "device",
    "device": "device",
}

# 事件类型值映射（中文 → 英文）
EVENT_TYPE_MAPPING = {
    "浏览": "view",
    "加购": "cart",
    "购买": "purchase",
    "下单": "purchase",
    "支付": "purchase",
    "view": "view",
    "cart": "cart",
    "purchase": "purchase",
}

# ============================================
# 分析参数
# ============================================
# GMV 异常检测阈值
GMV_SIGMA_THRESHOLD = 3.0  # 3-sigma 阈值
GMV_YOY_THRESHOLD = 0.30   # 同比变化率阈值 30%

# 数据质量评分权重
QUALITY_WEIGHTS = {
    "completeness": 0.40,   # 完整度
    "validity": 0.30,       # 合理性
    "uniqueness": 0.30,     # 唯一性
}

print(f"[Config] 项目路径: {BASE_DIR}")
print(f"[Config] 系统平台: {SYSTEM_PLATFORM}")
print(f"[Config] 中文字体: {CHINESE_FONT}")
print(f"[Config] AI功能: {'已启用 (DeepSeek)' if AI_ENABLED else '已禁用 (降级为规则引擎)'}")
