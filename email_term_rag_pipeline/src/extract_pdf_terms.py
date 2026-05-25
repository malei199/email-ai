#!/usr/bin/env python3
"""
服装词汇 PDF 提取器（增强版）
提取《汉英英汉服装分类词汇》中的术语条目，保留分类结构

页面分区策略：
  - 跳过: 1-15页（前言/目录）、436-491页（附录/缩写词）
  - 格式1 (16-163页): 汉英分类词汇，双栏中文+英文配对
  - 格式2 (166-399页): 英汉词汇 A-Z，英文词+音标+中文释义
  - 格式3 (402-435页): 颜色分类词汇，双栏中文+英文配对

与 email_rag_pipeline 风格对齐：
  - 输出到 email_term_rag_pipeline/output/
  - 单线程稳定提取，支持断点恢复（每50页自动保存）
  - 生成结构化 JSON + 统计报告
"""

import os
import re
import json
import argparse
from typing import List, Dict, Tuple
from collections import Counter

try:
    import pdfplumber
    from tqdm import tqdm
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip install pdfplumber tqdm")
    raise SystemExit(1)


# ============ 配置 ============
PDF_PATH = "data/pdf/汉英英汉服装分类词汇.pdf"
OUTPUT_DIR = "email_term_rag_pipeline/output"
CHECKPOINT_INTERVAL = 50

# 分栏阈值（页面宽度约 414，左栏约 42-190，右栏约 200-350）
SPLIT_X = 195
# 字符 y 坐标聚类容差：用于把同一水平线上的字符合并成一行
Y_TOLERANCE = 2.0

# 页面范围（页码从 1 开始）
SKIP_PAGES = set(range(1, 16)) | set(range(436, 492))   # 1-15, 436-491
FORMAT1_PAGES = set(range(16, 164))                      # 16-163
FORMAT2_PAGES = set(range(166, 400))                     # 166-399
FORMAT3_PAGES = set(range(402, 436))                     # 402-435

# 封面/前言垃圾词黑名单
TERM_BLACKLIST = {
    "图书在版编目", "中国版本图书馆", "前言", "目录", "凡购本书",
    "服装分类词汇", "汉英英汉服装分类词汇", "语词目为中心",
    "所有物种均被列入", "濒危野生动植物种国际贸易公约",
    "名录", "英汉服装词汇", "主编", "副主编", "参编",
    "中国纺织出版社", "内容提要", "版权", "ISBN", "CIP",
}

CATEGORY_BLACKLIST = {
    "前言", "目录", "附录", "索引", "英汉索引", "汉英索引",
    "服装分类词汇", "版权页", "内容提要",
}


# ============ 工具函数 ============

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def fullwidth_to_halfwidth(text: str) -> str:
    """全角字符转半角"""
    result = []
    for char in text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            result.append(" ")
        else:
            result.append(char)
    return "".join(result)


def clean_text(text: str) -> str:
    """清理提取文本中的垃圾字符"""
    text = fullwidth_to_halfwidth(text)
    # 移除空括号
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"〔\s*〕", "", text)
    # 移除开头/结尾的标点
    text = re.sub(r"^[;:,，、\.\s]+", "", text)
    text = re.sub(r"[;:,，、\.\s]+$", "", text)
    # 合并多余空格
    text = " ".join(text.split())
    return text


def fix_english_spacing(text: str) -> str:
    """尝试修复英文单词之间缺失的空格"""
    # 常见服装词根前后加空格
    text = re.sub(
        r"(clothes|dress|wear|coat|jacket|shirt|skirt|suit|pants|"
        r"garment|apparel|trousers|blouse|vest|shorts|jeans|"
        r"clothing|robe|gown|uniform|costume)([A-Z])",
        r"\1 \2", text,
    )
    text = re.sub(
        r"([a-z])(clothes|dress|wear|coat|jacket|shirt|skirt|suit|pants|"
        r"garment|apparel|trousers|blouse|vest|shorts|jeans|"
        r"clothing|robe|gown|uniform|costume)",
        r"\1 \2", text,
    )
    # 小写后接大写加空格（专有名词边界）
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return text


def get_column_lines(page, split_x: int = SPLIT_X, is_left: bool = True, y_tol: float = Y_TOLERANCE) -> List[str]:
    """按字符位置分栏，并按 y 坐标聚类成文本行"""
    chars = [c for c in page.chars if c["text"].strip()]
    filtered = [c for c in chars if (c["x0"] < split_x) == is_left]
    if not filtered:
        return []

    filtered.sort(key=lambda c: c["y0"])
    clusters = []
    current_cluster = [filtered[0]]

    for c in filtered[1:]:
        avg_y = sum(cc["y0"] for cc in current_cluster) / len(current_cluster)
        if abs(c["y0"] - avg_y) < y_tol:
            current_cluster.append(c)
        else:
            clusters.append(current_cluster)
            current_cluster = [c]

    if current_cluster:
        clusters.append(current_cluster)

    lines = []
    for cluster in clusters:
        cluster.sort(key=lambda c: c["x0"])
        line = "".join(c["text"] for c in cluster)
        lines.append(line.strip())

    return lines[::-1]  # 从上到下


def detect_categories(lines: List[str]) -> Tuple[str, str]:
    """从页面左栏行列表中检测一级/二级分类标题
    返回 (primary_category, secondary_category)
    """
    primary = ""
    secondary = ""
    for line in lines[:15]:
        line = line.strip()
        if not line:
            continue
        # 一级分类：一、服装成品
        m = re.match(r"^([一二三四五六七八九十]+)、([\u4e00-\u9fff]+)$", line)
        if m:
            primary = m.group(2)
            continue
        # 二级分类（纯中文）：（一）一般名称
        m = re.match(r"^（[一二三四五六七八九十]+）([\u4e00-\u9fff]+)$", line)
        if m:
            secondary = m.group(1)
            continue
        # 二级分类（混英）：（一）一般名称General Terms
        m = re.match(r"^（[一二三四五六七八九十]+）([\u4e00-\u9fff]+)", line)
        if m:
            secondary = m.group(1)
            continue
    return primary, secondary


def make_category(primary: str, secondary: str) -> str:
    """组合一级和二级分类"""
    parts = [p for p in (primary, secondary) if p]
    return "·".join(parts) if parts else "未分类"


# ============ 格式解析 ============

def parse_format1_column(lines: List[str], category: str, page_num: int) -> List[Dict]:
    """解析汉英分类词汇栏（格式1/3）"""
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # 跳过页码
        if re.match(r"^[０-９]+$", line) and len(line) <= 4:
            i += 1
            continue
        # 跳过极短行（可能是序号或碎片）
        if len(line) <= 1:
            i += 1
            continue

        has_cn = bool(re.search(r"[\u4e00-\u9fff]", line))
        has_en = bool(re.search(r"[ａ-ｚＡ-Ｚ]", line))

        # 中文行 → 找后续英文行
        if has_cn and not has_en:
            chinese = line
            english_parts = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                nxt_has_cn = bool(re.search(r"[\u4e00-\u9fff]", nxt))
                nxt_has_en = bool(re.search(r"[ａ-ｚＡ-Ｚ]", nxt))
                if nxt_has_en and not nxt_has_cn:
                    english_parts.append(nxt)
                    j += 1
                    if nxt.endswith("⁃"):
                        continue
                    break
                elif nxt_has_cn:
                    break
                j += 1
            if chinese and english_parts:
                cn = clean_text(chinese)
                en = clean_text(" ".join(english_parts))
                en = fix_english_spacing(en)
                if cn and en and len(cn) >= 2:
                    entries.append({
                        "chinese": cn,
                        "english": en,
                        "category": category,
                        "page": page_num,
                        "type": "汉英",
                    })
            i = j
        else:
            i += 1
    return entries


def is_format2_entry_start(line: str) -> bool:
    """判断是否为英汉词汇的新词条起始行"""
    if not re.match(r"^[ａ-ｚＡ-Ｚ]", line):
        return False
    if not re.search(r"[\u4e00-\u9fff]", line):
        return False
    # 排除纯音标/标点碎片
    if re.match(r"^[ˈˌ\s\(\)\[\]；，\.\/ａ-ｚæəɒɔːʊʌɜːŋʃɪʒɛɑːɪɒʒʒəː［］]+$", line):
        return False
    return True


def parse_format2_column(lines: List[str], category: str, page_num: int) -> List[Dict]:
    """解析英汉词汇栏（格式2）"""
    entries = []
    current_lines = []

    for line in lines:
        if re.match(r"^[０-９]+$", line) and len(line) <= 4:
            continue
        if re.match(r"^[ａ-ｚＡ-Ｚ]+$", line) and len(line) <= 2:
            continue

        if is_format2_entry_start(line):
            if current_lines:
                entries.append(" ".join(current_lines))
            current_lines = [line]
        elif current_lines:
            current_lines.append(line)

    if current_lines:
        entries.append(" ".join(current_lines))

    results = []
    for text in entries:
        first_cn_idx = None
        for idx, ch in enumerate(text):
            if "\u4e00" <= ch <= "\u9fff":
                first_cn_idx = idx
                break
        if first_cn_idx is None:
            continue

        en_part = text[:first_cn_idx].strip()
        cn_part = text[first_cn_idx:].strip()

        # 提取英文词和音标
        m = re.match(r"^([ａ-ｚＡ-Ｚ][ａ-ｚＡ-Ｚ\s\-0-9]*)(［[^［］]*］)?$", en_part)
        if m:
            en = m.group(1).strip()
            phonetic = m.group(2) or ""
        else:
            m2 = re.match(r"^([ａ-ｚＡ-Ｚ][ａ-ｚＡ-Ｚ\s\-0-9]*)", en_part)
            en = m2.group(1).strip() if m2 else en_part
            phonetic = ""

        if en and cn_part and len(en) >= 2:
            # 清理释义中的音标碎片和孤立标点
            meaning = re.sub(r"\s*[ˈˌ][^\u4e00-\u9fff]*?(?=\s|$)", " ", cn_part)
            meaning = re.sub(r"\s*[əɒɔːʊʌɜːŋʃɪʒɛɑːɪɒʒʒəː]+(?=\s|$)", " ", meaning)
            meaning = re.sub(r"\s*[；，\.\/（）]+\s*", " ", meaning)
            meaning = " ".join(meaning.split())

            en_clean = clean_text(en)
            ph_clean = clean_text(phonetic)
            cn_clean = clean_text(meaning)

            if en_clean and cn_clean:
                results.append({
                    "english": en_clean,
                    "phonetic": ph_clean,
                    "chinese": cn_clean,
                    "category": category,
                    "page": page_num,
                    "type": "英汉",
                })
    return results


# ============ 页面处理 ============

def extract_entries_from_page(page, page_num: int, current_category: str) -> Tuple[List[Dict], str]:
    """从单页提取词条，返回 (entries, updated_category)"""
    entries = []

    if page_num in SKIP_PAGES:
        return entries, current_category

    if page_num in FORMAT1_PAGES or page_num in FORMAT3_PAGES:
        left_lines = get_column_lines(page, is_left=True)
        right_lines = get_column_lines(page, is_left=False)

        # 从左栏检测分类
        primary, secondary = detect_categories(left_lines)
        if primary or secondary:
            current_category = make_category(primary, secondary)

        # 同时处理左右栏
        entries.extend(parse_format1_column(left_lines, current_category, page_num))
        entries.extend(parse_format1_column(right_lines, current_category, page_num))

    elif page_num in FORMAT2_PAGES:
        left_lines = get_column_lines(page, is_left=True)
        right_lines = get_column_lines(page, is_left=False)

        # 格式2 统一分类为 "英汉词汇"，保留当前分类状态
        cat = current_category if current_category else "英汉词汇"
        entries.extend(parse_format2_column(left_lines, cat, page_num))
        entries.extend(parse_format2_column(right_lines, cat, page_num))

    return entries, current_category


# ============ 过滤与去重 ============

def filter_and_deduplicate(entries: List[Dict]) -> List[Dict]:
    """质量过滤：去重、去黑名单、长度过滤"""
    seen = set()
    filtered = []

    for e in entries:
        cn = e.get("chinese", "").strip()
        en = e.get("english", "").strip()

        if len(cn) < 2 or len(en) < 2:
            continue

        full_text = cn + " " + en
        if any(b in full_text for b in TERM_BLACKLIST):
            continue

        key = (cn.lower(), en.lower())
        if key in seen:
            continue
        seen.add(key)

        filtered.append(e)

    return filtered


# ============ 断点 ============

def load_checkpoint(output_dir: str) -> Tuple[int, str]:
    cp_path = os.path.join(output_dir, "extract_checkpoint.json")
    if os.path.exists(cp_path):
        with open(cp_path, "r", encoding="utf-8") as f:
            cp = json.load(f)
        return cp.get("next_page", 0), cp.get("current_category", "")
    return 0, ""


def save_checkpoint(output_dir: str, next_page: int, current_category: str, entries: List[Dict]):
    ensure_dir(output_dir)
    cp_path = os.path.join(output_dir, "extract_checkpoint.json")
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump({
            "next_page": next_page,
            "current_category": current_category,
            "accumulated_count": len(entries),
        }, f, ensure_ascii=False, indent=2)

    temp_path = os.path.join(output_dir, "extracted_terms_temp.json")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ============ 主流程 ============

def main():
    parser = argparse.ArgumentParser(description="服装词汇 PDF 提取器")
    parser.add_argument("--resume", action="store_true", help="从断点恢复")
    args = parser.parse_args()

    pdf_path = PDF_PATH
    if not os.path.exists(pdf_path):
        print(f"[ERROR] PDF 文件不存在: {pdf_path}")
        raise SystemExit(1)

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    print(f"📖 总页数: {total_pages}")

    start_page, current_category = 0, ""
    all_entries = []

    if args.resume:
        start_page, current_category = load_checkpoint(OUTPUT_DIR)
        temp_path = os.path.join(OUTPUT_DIR, "extracted_terms_temp.json")
        if os.path.exists(temp_path):
            with open(temp_path, "r", encoding="utf-8") as f:
                all_entries = json.load(f)
        print(f"🔄 从断点恢复: 第 {start_page + 1} 页，已累积 {len(all_entries)} 条，当前分类: {current_category or '未识别'}")

    # 计算有效页数
    valid_pages = [p for p in range(start_page, total_pages) if (p + 1) not in SKIP_PAGES]
    print(f"⏳ 开始提取（有效页面 {len(valid_pages)} / {total_pages - start_page} 页）...")

    with pdfplumber.open(pdf_path) as pdf:
        iterator = tqdm(range(start_page, total_pages), desc="提取页面", initial=start_page, total=total_pages)
        for page_num in iterator:
            page = pdf.pages[page_num]
            text = page.extract_text()
            if not text:
                continue

            page_entries, current_category = extract_entries_from_page(page, page_num + 1, current_category)
            all_entries.extend(page_entries)

            if (page_num + 1) % CHECKPOINT_INTERVAL == 0 or page_num == total_pages - 1:
                save_checkpoint(OUTPUT_DIR, page_num + 1, current_category, all_entries)
                iterator.set_postfix(entries=len(all_entries), cat=current_category[:10])

    print(f"\n📊 原始提取: {len(all_entries)} 条")

    filtered = filter_and_deduplicate(all_entries)
    print(f"✨ 过滤去重后: {len(filtered)} 条")

    cat_dist = Counter(e.get("category", "未分类") for e in filtered)
    print(f"📁 分类数量: {len(cat_dist)}")
    print(f"Top 10 分类: {cat_dist.most_common(10)}")

    ensure_dir(OUTPUT_DIR)

    raw_path = os.path.join(OUTPUT_DIR, "extracted_terms.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)

    filtered_path = os.path.join(OUTPUT_DIR, "filtered_terms.json")
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)

    stats_path = os.path.join(OUTPUT_DIR, "extract_stats.json")
    stats = {
        "total_raw": len(all_entries),
        "total_filtered": len(filtered),
        "unique_categories": len(cat_dist),
        "category_distribution": dict(cat_dist.most_common()),
    }
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # 清理临时文件
    for temp in ["extract_checkpoint.json", "extracted_terms_temp.json"]:
        tp = os.path.join(OUTPUT_DIR, temp)
        if os.path.exists(tp):
            os.remove(tp)

    print(f"\n💾 输出文件:")
    print(f"  原始提取: {raw_path}")
    print(f"  过滤结果: {filtered_path}")
    print(f"  统计报告: {stats_path}")

    print(f"\n📄 示例条目:")
    for e in filtered[:5]:
        cat = e.get("category", "未分类")
        if e["type"] == "英汉":
            print(f"  [{cat}] {e['english']} | {e['chinese'][:60]}")
        else:
            print(f"  [{cat}] {e['chinese']} | {e['english'][:60]}")


if __name__ == "__main__":
    main()
