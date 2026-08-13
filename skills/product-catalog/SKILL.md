---
name: product-catalog
description: Look up the company's home-appliance catalog (models, specs, prices, style, min install size) when a customer asks about available products or when you need specs to make a recommendation.
---

# Product Catalog

Use the `get_product_catalog` tool to fetch the company's appliance data.
- Call `get_product_catalog("")` for the full overview of categories.
- Call `get_product_catalog("冰箱")` (or 洗衣机 / 空调) for one category's models.

Each product includes: `model`, `params`, `price`, `style`, `min_width_cm`.
Use these to match the customer's family size, decor style, and reserved
installation dimensions before recommending.
