#!/usr/bin/env python3
"""
模拟电商数据生成器（漏斗模型版）
------------------
严格按照 浏览→加购→购买 漏斗生成事件，保证购买数 < 加购数 < 浏览数。
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import random

np.random.seed(42)
random.seed(42)

# ============================================
# 配置参数
# ============================================
START_DATE = "2026-04-01"
END_DATE = "2026-06-30"
OUTPUT_PATH = Path(__file__).parent / "data" / "sample_ecommerce_data.xlsx"

# 品类配置
CATEGORIES = {
    "服装": {"price_mean": 120, "price_std": 50,  "price_min": 50,  "price_max": 300,  "products": 50},
    "数码": {"price_mean": 500, "price_std": 300, "price_min": 100, "price_max": 2000, "products": 40},
    "食品": {"price_mean": 30,  "price_std": 15,  "price_min": 5,   "price_max": 100,  "products": 40},
    "美妆": {"price_mean": 100, "price_std": 60,  "price_min": 20,  "price_max": 400,  "products": 40},
    "家居": {"price_mean": 200, "price_std": 120, "price_min": 50,  "price_max": 800,  "products": 30},
}

# 渠道权重
CHANNELS = ["抖音", "微信", "淘宝", "京东", "小红书", "organic"]
CHANNEL_WEIGHTS = [0.30, 0.20, 0.20, 0.12, 0.10, 0.08]
# 促销期渠道权重（抖音拉满）
PROMO_CHANNEL_WEIGHTS = [0.45, 0.15, 0.15, 0.08, 0.10, 0.07]

# 设备权重
DEVICES = ["iOS", "Android", "PC", "unknown"]
DEVICE_WEIGHTS = [0.35, 0.45, 0.15, 0.05]

NUM_USERS = 500

# ============================================
# 漏斗参数配置
# ============================================
# 格式: (每日基础浏览数, 浏览→加购率, 加购→购买率)
# 事件分布 ≈ 浏览: 1/(1+vc+vc*cp), 加购: vc/(1+vc+vc*cp), 购买: vc*cp/(1+vc+vc*cp)
# 浏览→购买转化率 = vc * cp

MONTH_CONFIG = {
    4: {
        "daily_views": 70,
        "view_to_cart": 0.42,     # 浏览→加购
        "cart_to_purchase": 0.45, # 加购→购买 (浏览→购买 ≈ 18.9%)
        "traffic_fluctuation": 0.20,
    },
    5: {
        "daily_views": 82,
        "view_to_cart": 0.40,
        "cart_to_purchase": 0.40, # 浏览→购买 ≈ 16.0%
        "traffic_fluctuation": 0.22,
    },
    6: {
        "daily_views": 95,
        "view_to_cart": 0.42,
        "cart_to_purchase": 0.38, # 浏览→购买非促销 ≈ 16.0%，含促销加权 ≈ 12%
        "traffic_fluctuation": 0.25,
    },
}

# 6月15-20日促销活动：流量翻倍但漏斗转化率暴跌
PROMO_START = datetime(2026, 6, 15)
PROMO_END = datetime(2026, 6, 20)
PROMO_CONFIG = {
    "daily_views": 260,          # 浏览暴涨（~2.7x平时）
    "view_to_cart": 0.22,        # 加购率大跌
    "cart_to_purchase": 0.28,    # 购买率大跌 (浏览→购买 ≈ 6.2%)
    "traffic_fluctuation": 0.10,
}

# ============================================
# 生成用户与商品
# ============================================
print("=" * 60)
print("  生成用户和商品...")

user_ids = [f"U{str(i).zfill(4)}" for i in range(1, NUM_USERS + 1)]

# 用户注册日期
user_reg_dates = {}
for uid in user_ids:
    if random.random() < 0.70:
        user_reg_dates[uid] = datetime(2026, 3, random.randint(1, 31))
    else:
        user_reg_dates[uid] = datetime(2026, random.randint(4, 6), random.randint(1, 28))

# 生成商品
products = []
product_prices = {}
product_categories = {}
product_id = 1
for cat, config in CATEGORIES.items():
    for i in range(config["products"]):
        pid = f"P{str(product_id).zfill(4)}"
        price = np.random.lognormal(mean=np.log(config["price_mean"]), sigma=0.4)
        price = max(config["price_min"], min(config["price_max"], price))
        price = round(price, 2)
        products.append(pid)
        product_prices[pid] = price
        product_categories[pid] = cat
        product_id += 1

NUM_PRODUCTS = len(products)
hot_products = set(random.sample(products, 15))  # 热门商品
print(f"  用户: {NUM_USERS} | 商品: {NUM_PRODUCTS}")

# ============================================
# 漏斗生成事件
# ============================================
print("\n" + "=" * 60)
print("  按漏斗模型生成事件数据...")

all_events = []
order_counter = 1
total_stats = {"浏览": 0, "加购": 0, "购买": 0}

start_dt = datetime.strptime(START_DATE, "%Y-%m-%d")
end_dt = datetime.strptime(END_DATE, "%Y-%m-%d")
date_range = (end_dt - start_dt).days + 1

for day_offset in range(date_range):
    current_date = start_dt + timedelta(days=day_offset)
    month = current_date.month
    is_promo = PROMO_START <= current_date <= PROMO_END

    # 1. 选择漏斗参数
    if is_promo:
        cfg = PROMO_CONFIG
        ch_weights = PROMO_CHANNEL_WEIGHTS
    else:
        cfg = MONTH_CONFIG[month]
        ch_weights = CHANNEL_WEIGHTS

    # 2. 当天浏览数（含随机波动 + 周末效应）
    daily_views = int(cfg["daily_views"] * np.random.uniform(
        1 - cfg["traffic_fluctuation"], 1 + cfg["traffic_fluctuation"]
    ))
    weekday = current_date.weekday()
    if weekday >= 5:
        daily_views = int(daily_views * 1.25)
    elif weekday == 0:
        daily_views = int(daily_views * 0.85)
    daily_views = max(20, daily_views)

    v_to_c = cfg["view_to_cart"]

    # 每天每个用户只可能浏览一次（避免同一用户大量重复浏览）
    # 从500个用户中随机抽取 daily_views 个
    day_users = random.sample(user_ids, min(daily_views, NUM_USERS))
    if daily_views > NUM_USERS:
        # 如果浏览数超过用户数，部分用户浏览多次（不同商品）
        extra = daily_views - NUM_USERS
        day_users += random.choices(user_ids, k=extra)

    day_events = []

    for uid in day_users:
        # 选择商品（热门商品概率高）
        if random.random() < 0.30:
            pid = random.choice(list(hot_products))
        else:
            pid = random.choice(products)

        # 渠道和设备
        channel = random.choices(CHANNELS, weights=ch_weights, k=1)[0]
        device = random.choices(DEVICES, weights=DEVICE_WEIGHTS, k=1)[0]

        # 价格（含波动）
        base_price = product_prices[pid]
        price = round(base_price * np.random.uniform(0.92, 1.08), 2)

        # 数量
        quantity = 1 if random.random() < 0.85 else random.randint(2, 5)

        # 时间（散落在一天内）
        hour = random.randint(6, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        view_time = current_date.replace(hour=hour, minute=minute, second=second)

        # === 漏斗起点：浏览事件 ===
        view_event = {
            "用户ID": uid,
            "商品ID": pid,
            "品类": product_categories[pid],
            "单价": price,
            "数量": quantity,
            "渠道": channel,
            "设备": device,
            "事件时间": view_time,
        }
        day_events.append(("浏览", view_event))
        total_stats["浏览"] += 1

        # === 漏斗第二层：加购（有概率） ===
        if random.random() < v_to_c:
            cart_time = view_time + timedelta(seconds=random.randint(30, 300))
            day_end = current_date.replace(hour=23, minute=59, second=59)
            if cart_time > day_end:
                cart_time = day_end
            cart_event = {
                "用户ID": uid,
                "商品ID": pid,
                "品类": product_categories[pid],
                "单价": price,
                "数量": quantity,
                "渠道": channel,
                "设备": device,
                "事件时间": cart_time,
            }
            day_events.append(("加购", cart_event))
            total_stats["加购"] += 1

            # === 漏斗第三层：购买（从加购转化） ===
            # 加购→购买率随月份调整
            if is_promo:
                c_to_p = cfg["cart_to_purchase"]
            else:
                c_to_p = MONTH_CONFIG[month]["cart_to_purchase"]

            if random.random() < c_to_p:
                purchase_time = cart_time + timedelta(seconds=random.randint(60, 1800))
                day_end = current_date.replace(hour=23, minute=59, second=59)
                if purchase_time > day_end:
                    purchase_time = day_end
                purchase_event = {
                    "用户ID": uid,
                    "商品ID": pid,
                    "品类": product_categories[pid],
                    "单价": price,
                    "数量": quantity,
                    "渠道": channel,
                    "设备": device,
                    "事件时间": purchase_time,
                }
                day_events.append(("购买", purchase_event))
                total_stats["购买"] += 1

    # 当天所有事件排好序，分配订单ID
    day_events.sort(key=lambda x: x[1]["事件时间"])

    for event_type, event_data in day_events:
        order_id = f"ORD{str(order_counter).zfill(8)}"
        if event_type == "购买":
            order_counter += 1
        all_events.append({
            "订单ID": order_id,
            "用户ID": event_data["用户ID"],
            "商品ID": event_data["商品ID"],
            "品类": event_data["品类"],
            "事件类型": event_type,
            "单价": event_data["单价"],
            "数量": event_data["数量"],
            "事件时间": event_data["事件时间"],
            "渠道": event_data["渠道"],
            "设备": event_data["设备"],
        })

    if (day_offset + 1) % 15 == 0:
        v = total_stats["浏览"]
        c = total_stats["加购"]
        p = total_stats["购买"]
        print(f"  进度: {day_offset+1}/{date_range} 天 | "
              f"浏览 {v} | 加购 {c} | 购买 {p} | "
              f"览→购 {p/v*100:.1f}% | 加→购 {p/c*100:.1f}%")

# ============================================
# 构建 DataFrame
# ============================================
print(f"\n构建 DataFrame ({len(all_events):,} 行)...")
df = pd.DataFrame(all_events)
df = df.sort_values("事件时间").reset_index(drop=True)

# ============================================
# 验证数据特征
# ============================================
print("\n" + "=" * 60)
print("  数据特征验证")
print("=" * 60)

total = len(df)
print(f"  总行数: {total:,}")
print(f"  时间范围: {df['事件时间'].min()} ~ {df['事件时间'].max()}")
print(f"  用户数: {df['用户ID'].nunique()}")
print(f"  商品数: {df['商品ID'].nunique()}")

# 事件分布
event_dist = df["事件类型"].value_counts()
v = event_dist.get("浏览", 0)
c = event_dist.get("加购", 0)
p = event_dist.get("购买", 0)

print(f"\n  事件类型分布:")
print(f"    浏览: {v:,} ({v/total*100:.1f}%)")
print(f"    加购: {c:,} ({c/total*100:.1f}%)")
print(f"    购买: {p:,} ({p/total*100:.1f}%)")

# 漏斗验证
print(f"\n  漏斗健康度:")
print(f"    浏览 > 加购: {'OK' if v > c else 'FAIL!'}")
print(f"    加购 > 购买: {'OK' if c > p else 'FAIL!'}")
print(f"    浏览→加购率: {c/v*100:.2f}%")
print(f"    加购→购买率: {p/c*100:.2f}%")
print(f"    浏览→购买率: {p/v*100:.2f}%  ← 整体转化率")

# 各月转化率
df["月份"] = df["事件时间"].dt.month
print(f"\n  各月浏览→购买转化率:")
for m in [4, 5, 6]:
    md = df[df["月份"] == m]
    mv = (md["事件类型"] == "浏览").sum()
    mp = (md["事件类型"] == "购买").sum()
    mc = (md["事件类型"] == "加购").sum()
    print(f"    {m}月: {mp/mv*100:.2f}% (浏览{mv} → 加购{mc} → 购买{mp}, 加→购 {mp/mc*100:.1f}%)")

# 促销期
promo = df[(df["事件时间"] >= PROMO_START) & (df["事件时间"] <= PROMO_END)]
pv = (promo["事件类型"] == "浏览").sum()
pp = (promo["事件类型"] == "购买").sum()
print(f"\n  促销期(6/15-20): 浏览{pv} → 购买{pp}, 转化率 {pp/pv*100:.2f}%")

# 客单价
purchase_df = df[df["事件类型"] == "购买"].copy()
purchase_df["金额"] = purchase_df["单价"] * purchase_df["数量"]
print(f"\n  总GMV: RMB {purchase_df['金额'].sum():,.0f}")
print(f"  平均客单价: RMB {purchase_df['金额'].mean():.0f}")
print(f"  各品类客单价:")
for cat in CATEGORIES:
    cp = purchase_df[purchase_df["品类"] == cat]
    if len(cp) > 0:
        print(f"    {cat}: RMB {cp['金额'].mean():.0f}")

# 复购率
user_pc = purchase_df.groupby("用户ID").size()
repeat = (user_pc > 1).sum()
print(f"\n  复购用户: {repeat}/{len(user_pc)} ({repeat/len(user_pc)*100:.1f}%)")

# ============================================
# 导出
# ============================================
print(f"\n导出...")
df = df.drop(columns=["月份"])
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
df.to_excel(OUTPUT_PATH, index=False, engine="openpyxl")
fsize = OUTPUT_PATH.stat().st_size / 1024
print(f"DONE! {OUTPUT_PATH.name} ({fsize:.0f} KB, {len(df):,} rows)")
