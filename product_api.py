"""模拟「产品描述接口」——售前 Agent 获取家电型号/参数/价格的数据源。

真实项目中这里会换成 HTTP 调用（如 requests.get("/api/products")）。
本 demo 用本地静态数据 + 简单查询函数模拟，便于演示 Agent 的推销逻辑。
"""

# 模拟后端产品库：每个产品含型号、关键参数、价格、风格标签。
_PRODUCT_DB: dict[str, list[dict]] = {
    "冰箱": [
        {
            "model": "BCD-468WKP",
            "params": "468L 对开门 / 一级能效 / 风冷无霜 / 变频压缩机",
            "price": 3299,
            "style": "现代简约",
            "min_width_cm": 70,
        },
        {
            "model": "BCD-320WG",
            "params": "320L 三门 / 二级能效 / 风冷 / 静音",
            "price": 1899,
            "style": "北欧",
            "min_width_cm": 60,
        },
        {
            "model": "BCD-610WFX",
            "params": "610L 十字对开 / 一级能效 / 嵌入式的超薄机身 60cm",
            "price": 5699,
            "style": "轻奢",
            "min_width_cm": 60,
        },
    ],
    "洗衣机": [
        {
            "model": "XQG100-BS",
            "params": "10kg 滚筒 / 变频 / 巴氏除菌 / 一级能效",
            "price": 2499,
            "style": "现代简约",
            "min_width_cm": 60,
        },
        {
            "model": "XQB80-TW",
            "params": "8kg 波轮 / 免清洗 / 二级能效",
            "price": 1099,
            "style": "实用",
            "min_width_cm": 55,
        },
    ],
    "空调": [
        {
            "model": "KFR-35GW-QX",
            "params": "1.5匹 挂机 / 新一级能效 / 自清洁 / 柔风",
            "price": 2199,
            "style": "现代简约",
            "min_width_cm": 80,
        },
        {
            "model": "KFR-72LW-CL",
            "params": "3匹 柜机 / 新一级能效 / 圆柱型 / 客厅适用",
            "price": 4999,
            "style": "轻奢",
            "min_width_cm": 40,
        },
    ],
}


def get_product_catalog(category: str = "") -> dict:
    """模拟产品描述接口：返回家电目录。

    Args:
        category: 家电类别，如「冰箱」「洗衣机」「空调」。为空则返回全部类别概览。

    Returns:
        字典，键为类别，值为该类别下的产品列表（型号/参数/价格/风格/最小安装宽度）。
    """
    catalog = _PRODUCT_DB
    if category:
        key = category.strip()
        return {key: catalog.get(key, [])}
    return catalog


def get_categories() -> list[str]:
    """返回所有可用的家电类别名称。"""
    return list(_PRODUCT_DB.keys())
