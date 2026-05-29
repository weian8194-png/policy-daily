#!/usr/bin/env python3
"""Listing CDQ/LQI审计 - Vercel Serverless Function (v7)"""
import re
import json
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Cache-Control': 'max-age=0',
}


def fetch_amazon(asin):
    url = f'https://www.amazon.com/dp/{asin}'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        return {'error': f'Amazon fetch failed: {str(e)}', 'asin': asin, 'url': url}

    html = resp.text
    soup = BeautifulSoup(html, 'html.parser')

    for tag in soup.find_all(['script', 'style']):
        tag.decompose()
    clean_html = str(soup)

    data = {'asin': asin, 'url': url}

    # Title
    el = soup.find('span', id='productTitle')
    data['title'] = el.get_text(strip=True) if el else 'N/A'

    # Brand
    el = soup.find('a', id='bylineInfo')
    if el:
        brand = el.get_text(strip=True).replace('Visit the ', '').replace(' Store', '').replace('Brand: ', '')
        data['brand'] = brand
    else:
        data['brand'] = 'N/A'

    # Price - multi-pattern
    price = 'N/A'
    whole_el = soup.find('span', class_='a-price-whole')
    fraction_el = soup.find('span', class_='a-price-fraction')
    if whole_el:
        w = whole_el.get_text(strip=True).replace(',', '').rstrip('.')
        f = fraction_el.get_text(strip=True) if fraction_el else '00'
        price = f'{w}.{f}'
    else:
        el = soup.find('span', class_='a-offscreen')
        if el:
            m = re.search(r'[\d,.]+', el.get_text())
            if m:
                price = m.group().replace(',', '')
        else:
            for pid in ['priceblock_ourprice', 'priceblock_dealprice', 'priceblock_saleprice']:
                el = soup.find('span', id=pid)
                if el:
                    m = re.search(r'[\d,.]+', el.get_text())
                    if m:
                        price = m.group().replace(',', '')
                        break
    data['price'] = price

    # Rating
    m = re.search(r'([\d.]+)\s*out\s*of\s*5', html)
    data['rating'] = m.group(1) if m else 'N/A'

    # Review count
    el = soup.find('span', id='acrCustomerReviewText')
    if el:
        m = re.search(r'([\d,]+)', el.get_text())
        data['review_count'] = m.group(1).replace(',', '') if m else 'N/A'
    else:
        data['review_count'] = 'N/A'

    # Bullets - extract ALL (not just first 5)
    bullets = []
    feature_div = soup.find('div', id='feature-bullets')
    if feature_div:
        for li in feature_div.find_all('li'):
            span = li.find('span', class_='a-list-item')
            if span:
                text = span.get_text(strip=True)
                if text and 'Make sure this fits' not in text and len(text) > 10:
                    bullets.append(text)
    data['bullets'] = bullets if bullets else ['Failed to extract bullets']

    # Tech specs
    specs = {}
    for table_id in ['prodDetTable', 'productDetails_techSpec_section_1']:
        table = soup.find('table', id=table_id)
        if table:
            for row in table.find_all('tr'):
                th = row.find('th')
                td = row.find('td')
                if th and td:
                    k = th.get_text(strip=True)
                    v = td.get_text(strip=True)
                    if k and v:
                        specs[k] = v
            break
    data['tech_specs'] = specs

    # Images
    imgs = soup.find_all('img', class_='a-dynamic-image')
    img_count = len(imgs) if imgs else len(re.findall(r'altImageCard', html))
    data['images_count'] = max(img_count, 1)

    # Video
    data['has_video'] = bool(soup.find('video') or re.search(r'video|(?:ivm|vp)\.', html, re.IGNORECASE))

    # A+
    data['has_aplus'] = bool(soup.find(class_='aplus-v2') or 'aplus' in html)

    # BSR
    m = re.search(r'#([\d,]+)\s+in\s+([^(<]+)', clean_html)
    if m:
        data['bsr_rank'] = m.group(1).replace(',', '')
        data['bsr_category'] = m.group(2).strip()
    else:
        data['bsr_rank'] = 'N/A'
        data['bsr_category'] = 'N/A'

    return data


# ─── Helper: search across all listing content ───

def _find_attr_in_listing(attr_name, title, bullets, specs):
    """Search for an attribute across title, bullets, and specs.
    Returns (found: bool, location: str) where location indicates where it was found."""
    attr_lower = attr_name.lower()
    # Common aliases for attribute names
    aliases = {
        'noise level': ['noise', 'decibel', 'db', 'quiet', 'sound level', 'operating noise'],
        'certification': ['certified', 'certification', 'ul listed', 'etl', 'ce', 'fcc', 'energy star', 'ul certified'],
        'material': ['material', 'stainless steel', 'bpa-free', 'bpa free', 'plastic', 'aluminum', 'silicone', 'glass', 'bamboo'],
        'package dimensions': ['package dimension', 'package size', 'boxed dimension', 'product dimension', 'item dimension'],
        'wattage': ['wattage', 'watt', 'w ', 'power consumption', 'rated power'],
        'item weight': ['weight', 'lb', 'kg', 'ounce', 'pound'],
        'voltage': ['voltage', 'volt', 'v ac', 'v dc', '110v', '120v', '220v', '240v'],
    }
    keywords = aliases.get(attr_lower, [attr_lower])

    # 1. Check specs (Product Information table)
    for k, v in specs.items():
        k_lower = k.lower()
        if any(kw in k_lower for kw in keywords):
            return True, 'specs'
        v_lower = v.lower()
        if any(kw in v_lower for kw in keywords):
            return True, 'specs'

    # 2. Check title
    title_lower = title.lower()
    if any(kw in title_lower for kw in keywords):
        return True, 'title'

    # 3. Check bullets
    bullets_text = ' '.join(bullets).lower() if bullets else ''
    if any(kw in bullets_text for kw in keywords):
        return True, 'bullets'

    return False, ''


def _has_comparative_language(bullets):
    """Enhanced check for competitive/comparative language in bullets."""
    if not bullets:
        return False
    bullets_text = ' '.join(bullets).lower()

    # Direct comparison words
    comparison_words = [
        'unlike', 'compared to', 'compared with', 'vs', 'versus',
        'instead of', 'rather than', 'other', 'traditional', 'conventional',
        'standard', 'ordinary', 'typical', 'normal', 'regular',
        'superior', 'outperform', 'exceed', 'surpass', 'beat',
        'better', 'faster', 'quieter', 'lighter', 'stronger', 'easier',
        'more efficient', 'more powerful', 'more durable',
        'industry-leading', 'best-in-class', 'top-rated',
        'advanced', 'upgraded', 'improved', 'enhanced', 'next-gen',
        'only', 'first', 'exclusive', 'unique', 'patented',
        'wider', 'larger', 'bigger', 'longer', 'higher',
        '2x', '3x', '5x', '10x',  # multiplier comparisons
    ]

    # Pattern: "X times more/less"
    pattern_multiplier = re.search(r'\d+x\s+(?:more|less|faster|quieter|longer|bigger|better)', bullets_text)
    if pattern_multiplier:
        return True

    # Pattern: "than standard/conventional/other/traditional"
    pattern_than = re.search(r'than\s+(?:standard|conventional|other|traditional|normal|regular|typical|ordinary)', bullets_text)
    if pattern_than:
        return True

    # Pattern: "X-inch vs Y-inch" or "X-inch feed chute vs standard Y-inch"
    pattern_vs = re.search(r'\d+[\.\d]*-?\s*(?:inch|in|cm|mm|oz|ml|l)\s+vs', bullets_text)
    if pattern_vs:
        return True

    for w in comparison_words:
        if w in bullets_text:
            return True

    return False


def _classify_bullet_opening(bullet_text):
    """Classify whether a bullet opening is benefit-oriented or feature-oriented.
    Returns 'benefit' or 'feature'."""
    if not bullet_text:
        return 'feature'

    # Extract the opening phrase (before the colon or first 50 chars)
    colon_match = re.match(r'^([^:]{2,50}):', bullet_text)
    if colon_match:
        opening = colon_match.group(1).strip().lower()
    else:
        opening = bullet_text[:50].lower()

    # Benefit-oriented patterns: starts with action verb, benefit adjective, or outcome
    benefit_patterns = [
        # Action verbs
        r'^(save|stay|enjoy|keep|get|make|create|protect|prevent|avoid|eliminate|reduce|maximize|minimize|never|always|easily|quickly|safely|effortlessly)',
        # Benefit adjectives
        r'^(easy|quiet|portable|convenient|safe|durable|reliable|powerful|efficient|comfortable|healthy|smart|versatile|flexible|compact|lightweight|ultra)',
        # Benefit phrases
        r'^(no more|no need|never worry|peace of mind|ready to|perfect for|ideal for|designed for|built for)',
        # "Easy to X" pattern
        r'^easy\s+to\s+',
        # "Save X" pattern
        r'^save\s+',
    ]

    for pat in benefit_patterns:
        if re.search(pat, opening):
            return 'benefit'

    # Feature-oriented patterns: starts with noun, number, or technical spec
    feature_patterns = [
        # Starts with number (e.g., "17 lb", "400W", "12V", "3-level")
        r'^\d',
        # Technical noun phrases
        r'^(dual|triple|single|multi|2-in-1|3-in-1)\s+',
        # Product component references
        r'^(the\s+)?(compressor|motor|battery|chute|blade|filter|tank|cable|cord|adapter|handle|wheel)',
    ]

    for pat in feature_patterns:
        if re.search(pat, opening):
            return 'feature'

    # Default: check if the opening is a compound with a benefit word
    # E.g., "Fast Cooling & Dual Modes" - "Fast" is benefit-ish
    first_word = opening.split()[0] if opening.split() else ''
    benefit_first_words = {
        'fast', 'rapid', 'quick', 'ultra', 'super', 'powerful', 'quiet',
        'easy', 'safe', 'smart', 'portable', 'compact', 'lightweight',
        'premium', 'advanced', 'pro', 'max', 'eco'
    }
    if first_word.rstrip(',') in benefit_first_words:
        return 'benefit'

    return 'feature'


def _extract_key_specs_from_listing(title, bullets, specs):
    """Extract key specifications from the listing for title optimization."""
    info = {
        'brand': '',
        'product_type': '',
        'key_specs': [],
        'features': [],
        'scenarios': [],
        'certifications': [],
        'material_color': [],
    }

    # Brand from title
    if title:
        words = title.split()
        if words:
            info['brand'] = words[0]

    # From specs: extract capacity, dimensions, wattage, voltage etc.
    spec_keys_of_interest = {
        'capacity': ['capacity', 'volume', 'size', 'quart', 'liter', 'can', 'can hold', 'cubic'],
        'wattage': ['wattage', 'watt', 'power'],
        'voltage': ['voltage', 'volt'],
        'material': ['material'],
        'color': ['color', 'colour'],
        'certification': ['certification', 'certified'],
    }
    for k, v in specs.items():
        k_lower = k.lower()
        for cat, keywords in spec_keys_of_interest.items():
            if any(kw in k_lower for kw in keywords):
                val = v.strip()
                if val and len(val) < 60:
                    info['key_specs'].append(f'{k}: {val}')
                break

    # From bullets: extract key features and scenarios
    bullets_text = ' '.join(bullets).lower() if bullets else ''
    scenario_words = ['outdoor', 'indoor', 'home', 'office', 'camping', 'travel', 'rv', 'truck', 'car', 'kitchen', 'bedroom', 'garage']
    for sw in scenario_words:
        if sw in bullets_text:
            info['scenarios'].append(sw.title())

    # Certifications from bullets
    cert_words = ['ul certified', 'etl listed', 'ce certified', 'fcc certified', 'energy star', 'bpa-free', 'bpa free']
    for cw in cert_words:
        if cw in bullets_text:
            info['certifications'].append(cw.upper())

    return info


def _optimize_title_v7(title, bullets, specs, brand):
    """v7 title optimization: 7-position structure with P0 protection.
    Structure: Brand → Core Product → Key Specs → Features → Scenarios → Selling Points/Certs → Material/Color
    P0 (Brand + Product Type + Specs + Features) NEVER deleted; only P1/P2 can be trimmed."""
    if not title or title == 'N/A':
        return title

    # Step 1: Clean special characters
    clean = title
    for ch in ['"', '\u201c', '\u201d', '\u2033']:
        clean = clean.replace(ch, '-Inch ')

    # Step 2: Extract info from listing for enrichment
    info = _extract_key_specs_from_listing(clean, bullets, specs)
    if brand and brand != 'N/A':
        info['brand'] = brand

    # Step 3: Build 7-position title
    # If title is already reasonable length (120+), just clean and deduplicate
    if len(clean) >= 120:
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for w in clean.split():
            wl = w.lower().rstrip('s')
            if wl not in seen or len(w) <= 3:
                deduped.append(w)
                seen.add(wl)
        result = ' '.join(deduped)
        # Only enrich if still under 200
        if len(result) < 150 and info['certifications']:
            cert_str = ', '.join(info['certifications'][:2])
            result = result + ', ' + cert_str
        return result[:200]

    # Title is too short - need to rebuild
    # P0: Brand + Product Type (from existing title)
    parts = []

    # Extract core product type from title words
    title_words = clean.split()
    # Brand
    if info['brand']:
        parts.append(info['brand'])

    # Core product words (skip brand, keep everything else from original title)
    core_words = title_words[1:] if info['brand'] and title_words[0].lower() == info['brand'].lower() else title_words
    product_phrase = ' '.join(core_words[:8])  # Keep first 8 words as product type + key details
    parts.append(product_phrase)

    # P1: Key specs from Product Information
    if info['key_specs']:
        # Pick most relevant 2 specs
        for spec in info['key_specs'][:2]:
            # Extract just the value part
            val = spec.split(': ', 1)[-1] if ': ' in spec else spec
            if val.lower() not in clean.lower():
                parts.append(val)

    # P2: Scenarios
    if info['scenarios']:
        scenario_str = 'for ' + ', '.join(info['scenarios'][:3])
        if scenario_str.lower() not in clean.lower():
            parts.append(scenario_str)

    # P2: Certifications
    if info['certifications']:
        cert_str = ', '.join(info['certifications'][:2])
        if cert_str.lower() not in clean.lower():
            parts.append(cert_str)

    result = ', '.join(parts)

    # Final dedup
    seen = set()
    deduped = []
    for w in result.split():
        wl = w.lower().rstrip('s')
        if wl not in seen or len(w) <= 3:
            deduped.append(w)
            seen.add(wl)

    return ' '.join(deduped)[:200]


def _optimize_bullets(bullets, specs):
    """Generate optimized bullet suggestions based on analysis.
    Returns list of dicts with original + suggestion + opening_type."""
    if not bullets or bullets == ['Failed to extract bullets']:
        return []

    results = []
    for i, bullet in enumerate(bullets[:5]):
        opening_type = _classify_bullet_opening(bullet)

        # Extract the opening phrase (before colon)
        colon_pos = bullet.find(':')
        opening = bullet[:colon_pos].strip() if colon_pos > 0 else bullet[:50].strip()

        suggestion = None
        if opening_type == 'feature':
            # Suggest a benefit-oriented alternative
            # Try to convert feature opening to benefit opening
            feature_to_benefit = {
                # Pattern: "X Capacity" -> "Store More with X Capacity"
                r'^(\d+[\d.]*)\s*(?:lb|quart|liter|l|oz|gal|cu ft|sq ft)': r'Store More with \g<0>',
                # Pattern: "Dual/Triple/Single X" -> "Versatile X"
                r'^(Dual|Triple|Multi|2-in-1|3-in-1)\s+': r'Versatile \g<0>',
                # Pattern: "X Power" -> "Powerful X"
                r'^(Low|High|Eco|Max)\s+(Power|Mode)': r'Efficient \g<0>',
            }
            for pat, repl in feature_to_benefit.items():
                m = re.match(pat, opening, re.IGNORECASE)
                if m:
                    suggestion = re.sub(pat, repl, opening, count=1, flags=re.IGNORECASE)
                    # Rebuild the bullet with new opening
                    if colon_pos > 0:
                        suggestion = suggestion + ':' + bullet[colon_pos+1:]
                    break

            # Generic suggestion if no pattern matched
            if not suggestion and colon_pos > 0:
                suggestion = f"[Benefit-oriented rewrite needed] Original opening: \"{opening}\" — try leading with the benefit (e.g., \"Save Time with...\", \"Stay Safe with...\", \"Enjoy Quiet Operation with...\")"

        results.append({
            'index': i + 1,
            'original': bullet[:200],
            'opening_type': opening_type,
            'suggestion': suggestion,
        })

    return results


def audit_listing(data):
    title = data.get('title', '')
    bullets = data.get('bullets', [])
    specs = data.get('tech_specs', {})
    images_count = data.get('images_count', 0)
    has_video = data.get('has_video', False)
    has_aplus = data.get('has_aplus', False)
    brand = data.get('brand', '')

    cdq_issues = []
    lqi_issues = []
    cdq_score = 100
    lqi_score = 100

    title_lower = title.lower()
    bullets_text = ' '.join(bullets).lower() if bullets else ''

    # ═══════════════════════════════════════════
    # CDQ Checks
    # ═══════════════════════════════════════════

    # CDQ-1: Special characters in title
    if re.search(r'["""\u201c\u201d\u2033]', title):
        cdq_issues.append({'level': 'high', 'title': '标题含特殊字符(引号)', 'detail': '引号可能触发CDQ解析异常，建议替换为-Inch或删去'})
        cdq_score -= 10

    # CDQ-2: Keyword repetition
    words = title_lower.split()
    word_counts = {}
    for w in words:
        if len(w) > 3: word_counts[w] = word_counts.get(w, 0) + 1
    repeated = {k: v for k, v in word_counts.items() if v > 1}
    if repeated:
        cdq_issues.append({'level': 'high', 'title': '标题关键词重复', 'detail': f'重复词: {", ".join(f"{k}x{v}" for k,v in repeated.items())}'})
        cdq_score -= 8

    # CDQ-3: Voltage check (category-aware)
    # Search across entire listing, not just specs
    voltage_found, voltage_loc = _find_attr_in_listing('voltage', title, bullets, specs)

    # Extract voltage value from specs for validation
    voltage_val = ''
    for k, v in specs.items():
        if 'voltage' in k.lower() or 'volt' in k.lower():
            voltage_val = v
            break

    if voltage_val and re.search(r'(230|220|240)', voltage_val):
        cdq_issues.append({'level': 'critical', 'title': '电压值异常(美国市场应为110-120V)', 'detail': f'当前: {voltage_val}，错误电压导致退货和降权'})
        cdq_score -= 15
    elif not voltage_found:
        # Check if this category even has voltage fields
        # If specs has wattage/power but no voltage, it's likely a category without voltage
        has_power_fields = any('watt' in k.lower() or 'power' in k.lower() for k in specs.keys())
        has_power_source = any('power source' in k.lower() or 'power source' in k.lower() for k in specs.keys())

        if has_power_fields or has_power_source:
            # Category has power-related fields but no voltage - likely doesn't need it
            cdq_issues.append({'level': 'low', 'title': '建议补充电压属性(可选)', 'detail': '当前类目后台可能无电压字段，如可补充则建议填写110-120V'})
            cdq_score -= 1
        else:
            # No power info at all - might be relevant
            cdq_issues.append({'level': 'medium', 'title': '缺失电压属性', 'detail': '已在标题/五点/Product Information中搜索，均未找到电压信息，建议补充'})
            cdq_score -= 3

    # CDQ-4: Power/wattage consistency (FIX: don't compare plug type with power source)
    # Only compare values that are actually wattage/power measurements
    wattage_vals = {}
    for k, v in specs.items():
        k_lower = k.lower()
        # Only include true wattage/power measurement fields, NOT plug type or power source type
        if ('wattage' in k_lower or 'watt' in k_lower) and 'plug' not in k_lower and 'source' not in k_lower:
            wattage_vals[k] = v
        elif k_lower == 'maximum power' or k_lower == 'rated power':
            wattage_vals[k] = v

    if len(wattage_vals) > 1 and len(set(wattage_vals.values())) > 1:
        cdq_issues.append({'level': 'high', 'title': '功率数据不一致', 'detail': f'多个功率字段值冲突: {", ".join(f"{k}={v}" for k,v in wattage_vals.items())}，建议以额定功率为准统一'})
        cdq_score -= 8
    # Note: Power Plug Type and Power Source are NOT compared - they are different concepts

    # CDQ-5: Missing high-weight attributes (FIX: search across entire listing)
    important_attrs = {
        'Noise Level': '噪音等级',
        'Certification': '认证',
        'Material': '材质',
        'Item Weight': '重量',
        'Package Dimensions': '包装尺寸',
        'Wattage': '功率',
    }

    missing_attrs = []
    found_attrs_info = []
    for attr_en, attr_cn in important_attrs.items():
        found, location = _find_attr_in_listing(attr_en, title, bullets, specs)
        if not found:
            missing_attrs.append(f'{attr_en}({attr_cn})')
        else:
            loc_names = {'specs': 'Product Information', 'title': '标题', 'bullets': '五点描述'}
            found_attrs_info.append(f'{attr_en} → 已在{loc_names.get(location, location)}中找到')

    if missing_attrs:
        cdq_issues.append({
            'level': 'medium',
            'title': f'缺失{len(missing_attrs)}个高权重属性',
            'detail': f'已在标题/五点/Product Information中搜索，建议补充: {", ".join(missing_attrs[:4])}{"（如当前类目后台无该字段，可忽略）" if len(missing_attrs) > 3 else ""}'
        })
        cdq_score -= 3 * min(len(missing_attrs), 4)

    # CDQ-6: Title length
    if len(title) < 80:
        cdq_issues.append({'level': 'low', 'title': f'标题偏短({len(title)}字符)', 'detail': '建议150-200字符，当前标题未能充分利用关键词空间'})
        cdq_score -= 3
    elif len(title) > 200:
        cdq_issues.append({'level': 'medium', 'title': f'标题过长({len(title)}字符)', 'detail': '超200字符会被截断'})
        cdq_score -= 5

    # ═══════════════════════════════════════════
    # LQI Checks
    # ═══════════════════════════════════════════

    # LQI-1: BPA Free only in title
    if 'bpa' in title_lower and 'bpa' not in bullets_text:
        lqi_issues.append({'level': 'high', 'title': 'BPA Free仅标题提及', 'detail': '五点描述未展开'})
        lqi_score -= 12

    # LQI-2: Last bullet is brand boilerplate
    if bullets and len(bullets) >= 5:
        last = bullets[-1].lower()
        if any(w in last for w in ['promise', 'quality', 'guarantee', 'deserve', 'mission', 'committed']):
            lqi_issues.append({'level': 'high', 'title': '第五条五点为品牌套话', 'detail': '浪费核心展示位，建议改为功能卖点'})
            lqi_score -= 10

    # LQI-3: Images
    if images_count < 7:
        lqi_issues.append({'level': 'high', 'title': f'图片不足({images_count}张)', 'detail': '建议9张以上'})
        lqi_score -= 12
    elif images_count < 9:
        lqi_issues.append({'level': 'medium', 'title': f'图片可补充({images_count}张)', 'detail': '建议补充至9+'})
        lqi_score -= 5

    # LQI-4: Video
    if not has_video:
        lqi_issues.append({'level': 'medium', 'title': '缺少产品视频', 'detail': '视频提升转化率20%+'})
        lqi_score -= 8

    # LQI-5: A+ page
    if not has_aplus:
        lqi_issues.append({'level': 'medium', 'title': '缺少A+页面', 'detail': 'A+提升转化3-10%'})
        lqi_score -= 8

    # LQI-6: Competitive/comparative language (FIX: enhanced detection)
    if not _has_comparative_language(bullets):
        lqi_issues.append({
            'level': 'medium',
            'title': '卖点缺乏竞品对比语言',
            'detail': '消费者无法感知"为什么选你"，建议加入对比表述如"Unlike traditional..."、"Wider 5.8-inch vs standard 3-inch..."、"X times faster than..."'
        })
        lqi_score -= 6

    # LQI-7: Benefit-oriented opening check (NEW)
    if bullets and len(bullets) >= 1:
        feature_openings = []
        for i, bullet in enumerate(bullets[:5]):
            opening_type = _classify_bullet_opening(bullet)
            if opening_type == 'feature':
                colon_pos = bullet.find(':')
                opening_phrase = bullet[:colon_pos].strip() if colon_pos > 0 else bullet[:40].strip()
                feature_openings.append(f'第{i+1}条: "{opening_phrase}"')

        if len(feature_openings) >= 3:
            lqi_issues.append({
                'level': 'medium',
                'title': f'{len(feature_openings)}条五点缺乏利益导向开头',
                'detail': f'消费者扫读只看开头5个词，功能描述开头不如利益点开头有吸引力。需修改: {"; ".join(feature_openings[:3])}。建议改为利益导向如"Easy to Clean..."/"Save Time with..."/"Stay Safe with..."'
            })
            lqi_score -= 4

    # LQI-8: Data claims without support
    pct_match = re.findall(r'([\d.]+%)\s*(?:juice|yield|extract)', bullets_text)
    if pct_match and not any(w in bullets_text for w in ['test', 'lab', 'certif', 'verif']):
        lqi_issues.append({'level': 'low', 'title': '数据声明缺乏支撑', 'detail': f'"{pct_match[0]}"无第三方认证'})
        lqi_score -= 4

    # ═══════════════════════════════════════════
    # Calculate scores
    # ═══════════════════════════════════════════
    cdq_score = max(0, min(100, cdq_score))
    lqi_score = max(0, min(100, lqi_score))
    overall = int(cdq_score * 0.5 + lqi_score * 0.5)

    if overall >= 90: grade = 'Optimized'
    elif overall >= 75: grade = 'Great'
    elif overall >= 60: grade = 'Good'
    elif overall >= 40: grade = 'Fair'
    else: grade = 'Poor'

    # Title optimization (v7)
    opt_title = _optimize_title_v7(title, bullets, specs, brand)

    # Bullet optimization
    bullet_optimization = _optimize_bullets(bullets, specs)

    return {
        'cdq_score': cdq_score, 'lqi_score': lqi_score, 'overall_score': overall,
        'grade': grade, 'cdq_issues': cdq_issues, 'lqi_issues': lqi_issues,
        'optimized_title': opt_title,
        'bullet_optimization': bullet_optimization,
    }


def handler(request):
    """Vercel Python runtime entry point"""
    try:
        # Vercel Python passes event dict
        if isinstance(request, dict):
            qs = request.get('queryStringParameters') or {}
            asin = qs.get('asin', '').strip().upper()
        else:
            asin = ''
            if hasattr(request, 'args'):
                asin = request.args.get('asin', '').strip().upper()
            if not asin and hasattr(request, 'query'):
                asin = request.query.get('asin', '').strip().upper()

        if not asin or not re.match(r'^[A-Z0-9]{10}$', asin):
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Please enter a valid 10-character ASIN'}, ensure_ascii=False)
            }

        data = fetch_amazon(asin)
        if 'error' in data:
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps(data, ensure_ascii=False)
            }

        audit = audit_listing(data)
        result = {**data, 'audit': audit}

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(result, ensure_ascii=False)
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': str(e)}, ensure_ascii=False)
        }
