import { tool } from "@langchain/core/tools";
import { z } from "zod";

/**
 * 产品目录工具 —— 对标 Python 版 product_api.py。
 * 真实场景这里应调用「产品描述接口」(REST/RPC)，此处用内存数据模拟。
 */

interface Product {
  name: string;
  category: string;
  price: number;
  minWidth: number;
  tags: string[];
}

const CATALOG: Product[] = [
  { name: "净味系列冰箱 BCD-468", category: "冰箱", price: 3299, minWidth: 70, tags: ["大容量", "静音", "一级能效"] },
  { name: "纤薄嵌入式冰箱 BCD-401", category: "冰箱", price: 4599, minWidth: 60, tags: ["嵌入式", "超薄", "风冷无霜"] },
  { name: "变频静音空调 KFR-35", category: "空调", price: 2199, minWidth: 80, tags: ["变频", "一级能效", "自清洁"] },
  { name: "洗烘一体机 XQG100", category: "洗衣机", price: 2899, minWidth: 60, tags: ["洗烘一体", "10kg", "智能投放"] },
  { name: "超薄油烟机 CXW-260", category: "厨卫", price: 1599, minWidth: 90, tags: ["超薄", "大吸力", "挥手智控"] },
  { name: "嵌入式洗碗机 K6", category: "厨卫", price: 3699, minWidth: 60, tags: ["嵌入式", "13套", "热风烘干"] },
  { name: "75寸电视 75E5", category: "电视", price: 3999, minWidth: 167, tags: ["4K", "MEMC", "远场语音"] },
  { name: "滚筒洗衣机 XQG80", category: "洗衣机", price: 1999, minWidth: 60, tags: ["8kg", "变频", "除菌"] },
];

export const getCategories = tool(
  async () => {
    const cats = Array.from(new Set(CATALOG.map((p) => p.category)));
    return JSON.stringify({ categories: cats });
  },
  {
    name: "get_categories",
    description: "获取所有可选的产品大类（如 冰箱、空调、洗衣机、厨卫、电视）。先了解有哪些品类时使用。",
    schema: z.object({}),
  },
);

export const getProductCatalog = tool(
  async ({ category }: { category?: string }) => {
    const list = category ? CATALOG.filter((p) => p.category === category) : CATALOG;
    return JSON.stringify(
      list.map((p) => ({
        name: p.name,
        category: p.category,
        price: p.price,
        minWidth: p.minWidth,
        tags: p.tags,
      })),
      null,
      2,
    );
  },
  {
    name: "get_product_catalog",
    description:
      "查询产品目录。可按 category 筛选（如 '冰箱'/'空调'/'洗衣机'/'厨卫'/'电视'）；不传则返回全部。返回型号、价格、最小安装宽度(minWidth, 单位cm)、卖点标签。推荐前务必核对 minWidth 是否满足用户预留尺寸。",
    schema: z.object({
      category: z.string().optional().describe("产品大类，不传则返回全部"),
    }),
  },
);
