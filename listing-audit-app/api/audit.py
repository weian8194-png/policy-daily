#!/usr/bin/env python3
"""Listing CDQ/LQI审计 - Vercel Serverless Function"""
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

    # Bullets
    bullets = []
    feature_div = soup.find('div', id='feature-bullets')
    if feature_div:
        for li in feature_div.find_all('li'):
            span = li.find('span', class_='a-list-item')
            if span:
                text = span.get_text(strip=True)
                if text and 'Make sure this fits' not in text and len(text) > 10:
                    bullets.append(text)
    data['bullets'] = bullets[:5] if bullets else ['Failed to extract bullets']

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


def audit_listing(data):
    title = data.get('title', '')
    bullets = data.get('bullets', [])
    specs = data.get('tech_specs', {})
    images_count = data.get('images_count', 0)
    has_video = data.get('has_video', False)
    has_aplus = data.get('has_aplus', False)

    cdq_issues = []
    lqi_issues = []
    cdq_score = 100
    lqi_score = 100

    title_lower = title.lower()
    bullets_text = ' '.join(bullets).lower() if bullets else ''

    # CDQ checks
    if re.search(r'["""\u201c\u201d\u2033]', title):
        cdq_issues.append({'level': 'high', 'title': '标题含特殊字符(引号)', 'detail': '引号可能触发CDQ解析异常，建议替换为-Inch或删去'})
        cdq_score -= 10

    words = title_lower.split()
    word_counts = {}
    for w in words:
        if len(w) > 3: word_counts[w] = word_counts.get(w, 0) + 1
    repeated = {k: v for k, v in word_counts.items() if v > 1}
    if repeated:
        cdq_issues.append({'level': 'high', 'title': '标题关键词重复', 'detail': f'重复词: {", ".join(f"{k}x{v}" for k,v in repeated.items())}'})
        cdq_score -= 8

    voltage = ''
    for k, v in specs.items():
        if 'voltage' in k.lower() or 'volt' in k.lower(): voltage = v; break
    if voltage and re.search(r'(230|220|240)', voltage):
        cdq_issues.append({'level': 'critical', 'title': '电压值异常(美国市场应为110-120V)', 'detail': f'当前: {voltage}，错误电压导致退货和降权'})
        cdq_score -= 15
    elif not voltage:
        cdq_issues.append({'level': 'medium', 'title': '缺失电压属性', 'detail': 'CDQ高权重属性，建议补充'})
        cdq_score -= 3

    wattage_vals = {k: v for k, v in specs.items() if 'watt' in k.lower() or 'power' in k.lower()}
    if len(wattage_vals) > 1 and len(set(wattage_vals.values())) > 1:
        cdq_issues.append({'level': 'high', 'title': '功率数据不一致', 'detail': f'多值: {", ".join(f"{k}={v}" for k,v in wattage_vals.items())}'})
        cdq_score -= 8

    important_attrs = {'Noise Level': '噪音等级', 'Certification': '认证', 'Material': '材质', 'Item Weight': '重量', 'Package Dimensions': '包装尺寸', 'Wattage': '功率'}
    missing = [f'{a}({c})' for a, c in important_attrs.items() if not any(a.lower() in k.lower() for k in specs)]
    if missing:
        cdq_issues.append({'level': 'medium', 'title': f'缺失{len(missing)}个高权重属性', 'detail': f'建议补充: {", ".join(missing[:4])}'})
        cdq_score -= 3 * min(len(missing), 4)

    if len(title) < 80:
        cdq_issues.append({'level': 'low', 'title': f'标题偏短({len(title)}字符)', 'detail': '建议150-200字符'})
        cdq_score -= 3
    elif len(title) > 200:
        cdq_issues.append({'level': 'medium', 'title': f'标题过长({len(title)}字符)', 'detail': '超200字符会被截断'})
        cdq_score -= 5

    # LQI checks
    if 'bpa' in title_lower and 'bpa' not in bullets_text:
        lqi_issues.append({'level': 'high', 'title': 'BPA Free仅标题提及', 'detail': '五点描述未展开'})
        lqi_score -= 12

    if bullets and len(bullets) >= 5:
        last = bullets[-1].lower()
        if any(w in last for w in ['promise', 'quality', 'guarantee', 'deserve', 'mission', 'committed']):
            lqi_issues.append({'level': 'high', 'title': '第五条五点为品牌套话', 'detail': '浪费核心展示位'})
            lqi_score -= 10

    if images_count < 7:
        lqi_issues.append({'level': 'high', 'title': f'图片不足({images_count}张)', 'detail': '建议9张以上'})
        lqi_score -= 12
    elif images_count < 9:
        lqi_issues.append({'level': 'medium', 'title': f'图片可补充({images_count}张)', 'detail': '建议补充至9+'})
        lqi_score -= 5

    if not has_video:
        lqi_issues.append({'level': 'medium', 'title': '缺少产品视频', 'detail': '视频提升转化率20%+'})
        lqi_score -= 8

    if not has_aplus:
        lqi_issues.append({'level': 'medium', 'title': '缺少A+页面', 'detail': 'A+提升转化3-10%'})
        lqi_score -= 8

    diff_words = ['wider', 'larger', 'unique', 'only', 'first', 'exclusive', 'unlike', 'compared']
    if not any(w in bullets_text for w in diff_words):
        lqi_issues.append({'level': 'medium', 'title': '卖点缺乏竞品对比', 'detail': '消费者无法感知差异化'})
        lqi_score -= 6

    pct_match = re.findall(r'([\d.]+%)\s*(?:juice|yield|extract)', bullets_text)
    if pct_match and not any(w in bullets_text for w in ['test', 'lab', 'certif', 'verif']):
        lqi_issues.append({'level': 'low', 'title': '数据声明缺乏支撑', 'detail': f'"{pct_match[0]}"无第三方认证'})
        lqi_score -= 4

    cdq_score = max(0, min(100, cdq_score))
    lqi_score = max(0, min(100, lqi_score))
    overall = int(cdq_score * 0.5 + lqi_score * 0.5)

    if overall >= 90: grade = 'Optimized'
    elif overall >= 75: grade = 'Great'
    elif overall >= 60: grade = 'Good'
    elif overall >= 40: grade = 'Fair'
    else: grade = 'Poor'

    opt_title = title
    for ch in ['"', '\u201c', '\u201d', '\u2033']:
        opt_title = opt_title.replace(ch, '-Inch ')
    seen = set()
    deduped = []
    for w in opt_title.split():
        wl = w.lower().rstrip('s')
        if wl not in seen or len(w) <= 3:
            deduped.append(w); seen.add(wl)
    opt_title = ' '.join(deduped)

    return {
        'cdq_score': cdq_score, 'lqi_score': lqi_score, 'overall_score': overall,
        'grade': grade, 'cdq_issues': cdq_issues, 'lqi_issues': lqi_issues,
        'optimized_title': opt_title,
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
