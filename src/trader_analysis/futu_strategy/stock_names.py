"""美股/港股 ticker → 中文名 映射。

用于文案生成和复盘时，将英文名（如 Broadcom Inc.）替换为中文名（博通）。
映射缺失时回退到英文名或 ticker。
"""

from __future__ import annotations

# ticker → 中文名
TICKER_CN: dict[str, str] = {
    # ── 港股 ──
    "00700": "腾讯控股",
    "01211": "比亚迪",
    "03690": "美团",
    # ── 大盘 ETF ──
    "SPY": "标普500",
    "QQQ": "纳指100",
    "GLD": "黄金",
    "IBIT": "比特币",
    "MAGS": "七巨头ETF",
    "SOXX": "半导体ETF",
    "GDX": "黄金矿业ETF",
    "EWJ": "日本ETF",
    "EWT": "台湾ETF",
    "EWY": "韩国ETF",
    "SLV": "白银",
    "URA": "铀矿ETF",
    "SPCX": "SpaceX",
    # ── 板块 ETF ──
    "XLK": "科技ETF", "XLF": "金融ETF", "XLE": "能源ETF", "XLI": "工业ETF",
    "XLP": "必需消费ETF", "XLY": "可选消费ETF", "XLV": "医疗ETF", "XLB": "材料ETF",
    "XLC": "通信ETF", "XLU": "公用事业ETF", "XLRE": "地产ETF",
    # ── MAG7 ──
    "AAPL": "苹果", "AMZN": "亚马逊", "GOOGL": "谷歌", "META": "Meta",
    "MSFT": "微软", "NVDA": "英伟达", "TSLA": "特斯拉",
    # ── 半导体 ──
    "AMD": "超微半导体", "AVGO": "博通", "INTC": "英特尔", "AMAT": "应用材料",
    "KLAC": "科磊", "LRCX": "泛林", "MU": "美光", "QCOM": "高通", "TXN": "德州仪器",
    "ADI": "亚德诺", "ASML": "阿斯麦", "TSM": "台积电", "ARM": "安谋", "MRVL": "迈威尔",
    "WDC": "西部数据", "STX": "希捷", "SNDK": "闪迪", "DELL": "戴尔",
    # ── 科技/软件 ──
    "CRM": "赛富时", "NOW": "ServiceNow", "ORCL": "甲骨文", "PLTR": "Palantir",
    "PANW": "Palo Alto", "CRWD": "CrowdStrike", "SHOP": "Shopify", "UBER": "优步",
    "SPOT": "Spotify", "NFLX": "奈飞", "COIN": "Coinbase", "HOOD": "Robinhood",
    "MSTR": "微策略", "IBM": "IBM", "SAP": "SAP", "APP": "AppLovin", "FUTU": "富途",
    "ANET": "Arista", "FTNT": "Fortinet", "CSCO": "思科", "NBIS": "Nebius",
    "COHR": "Coherent", "LITE": "Lumentum", "CRCL": "Circle", "CRWV": "CoreWeave",
    "BMNR": "Bitcoin Miners",
    # ── 中概 ──
    "PDD": "拼多多", "BABA": "阿里巴巴", "YUMC": "百胜中国", "B": "Barnes",
    # ── 金融 ──
    "JPM": "摩根大通", "BAC": "美国银行", "WFC": "富国银行", "GS": "高盛",
    "MS": "摩根士丹利", "C": "花旗", "SCHW": "嘉信理财", "AXP": "美国运通",
    "V": "Visa", "MA": "万事达", "BLK": "贝莱德", "COF": "第一资本", "IBKR": "盈透证券",
    "CB": "丘博", "PGR": "前进保险", "HDB": "HDFC银行", "IBN": "印度工业信贷",
    "BNS": "丰业银行", "BMO": "蒙特利尔银行", "CM": "加拿大帝国银行", "TD": "多伦多道明",
    "UBS": "瑞银", "SAN": "桑坦德", "BBVA": "西班牙对外银行", "HSBC": "汇丰",
    "MFG": "三菱日联", "SMFG": "三井住友", "MUFG": "三菱UFJ", "AIQUY": "欧莱雅",
    # ── 医药 ──
    "LLY": "礼来", "JNJ": "强生", "PFE": "辉瑞", "MRK": "默沙东", "ABBV": "艾伯维",
    "BMY": "百时美施贵宝", "AMGN": "安进", "GILD": "吉利德", "VRTX": "福泰制药",
    "MDT": "美敦力", "ISRG": "直觉外科", "TMO": "赛默飞", "NVO": "诺和诺德",
    "NVS": "诺华", "SNY": "赛诺菲", "AZN": "阿斯利康", "CVS": "西维斯", "UNH": "联合健康",
    # ── 消费 ──
    "KO": "可口可乐", "PEP": "百事", "MCD": "麦当劳", "SBUX": "星巴克",
    "HD": "家得宝", "LOW": "劳氏", "WMT": "沃尔玛", "COST": "好市多", "TJX": "TJX",
    "DIS": "迪士尼", "BKNG": "Booking", "PM": "菲利普莫里斯", "MO": "奥驰亚",
    "BTI": "英美烟草", "BUD": "百威英博", "UL": "联合利华", "PG": "宝洁",
    # ── 能源/工业 ──
    "XOM": "埃克森美孚", "CVX": "雪佛龙", "BP": "英国石油", "SHEL": "壳牌",
    "TTE": "道达尔", "COP": "康菲", "ENB": "安桥", "CAT": "卡特彼勒", "DE": "迪尔",
    "GE": "通用电气", "GEV": "GE Vernova", "ETN": "伊顿", "RTX": "雷神",
    "LMT": "洛克希德马丁", "BA": "波音", "HWM": "霍尼韦尔", "PH": "派克汉尼汾",
    "UNP": "联合太平洋", "NEE": "新纪元能源", "VST": "Vistra", "CEG": "Constellation",
    "SO": "南方公司", "DHR": "丹纳赫", "LIN": "林德", "APH": "安费诺", "VRT": "Vertiv",
    # ── 通信/媒体 ──
    "T": "AT&T", "VZ": "威瑞森", "TMUS": "T-Mobile", "SONY": "索尼",
    # ── 材料/矿业 ──
    "BHP": "必和必拓", "RIO": "力拓", "SCCO": "南方铜业", "GLW": "康宁",
    # ── 其他龙头 ──
    "SYK": "史赛克", "ABT": "雅培", "ADP": "ADP", "PLD": "普洛斯",
    "EQIX": "易昆尼克斯", "WELL": "Welltower", "HOOD": "Robinhood",
    "RKLB": "Rocket Lab", "AXAHY": "AXA安盛", "ZURVY": "苏黎世保险",
    "LVMUY": "LVMH", "DRAM": "DRAM",
}


def get_cn_name(ticker: str) -> str | None:
    """根据 ticker 返回中文名，无映射返回 None。"""
    return TICKER_CN.get(ticker.upper())
