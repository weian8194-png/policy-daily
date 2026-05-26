#!/usr/bin/env python3
"""Listing CDQ/LQI审计引擎 - GitHub Actions版"""
import sys
import os
import re
import json
import requests
from bs4 import BeautifulSoup

ASIN = sys.argv[1].strip().upper()
if not re.match(r'^[A-Z0-9]{10}$', ASIN):
    print(f"Invalid ASIN: {ASIN}")
    sys.exit(1)

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(REPO_DIR, 'listing-audit', 'reports')
os.makedirs(REPORT_DIR, exist_ok=True)

# ========== 抓取Amazon ==========
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

def fetch_amazon(asin):
    url = f'https://www.amazon.com/dp/{asin}'
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, 'html.parser')

    data = {'asin': asin, 'url': url}

    # 标题
    el = soup.find('span', id='productTitle')
    data['title'] = el.get_text(strip=True) if el else 'N/A'

    # 品牌
    el = soup.find('a', id='bylineInfo')
    if el:
        brand = el.get_text(strip=True).replace('Visit the ', '').replace(' Store', '').replace('Brand: ', '')
        data['brand'] = brand
    else:
        data['brand'] = 'N/A'

    # 价格
    el = soup.find('span', class_='a-offscreen')
    if el:
        data['price'] = el.get_text(strip=True).replace('$', '').replace(',', '')
    else:
        el = soup.find('span', id='priceblock_ourprice')
        if el:
            data['price'] = el.get_text(strip=True).replace('$', '').replace(',', '')
        else:
            el = soup.find('span', id='priceblock_dealprice')
            data['price'] = el.get_text(strip=True).replace('$', '').replace(',', '') if el else 'N/A'

    # 评分
    m = re.search(r'([\d.]+)\s*out\s*of\s*5', html)
    data['rating'] = m.group(1) if m else 'N/A'

    # 评论数
    el = soup.find('span', id='acrCustomerReviewText')
    if el:
        m = re.search(r'([\d,]+)', el.get_text())
        data['review_count'] = m.group(1).replace(',', '') if m else 'N/A'
    else:
        data['review_count'] = 'N/A'

    # 五点描述
    bullets = []
    feature_div = soup.find('div', id='feature-bullets')
    if feature_div:
        for li in feature_div.find_all('li'):
            span = li.find('span', class_='a-list-item')
            if span:
                text = span.get_text(strip=True)
                if text and 'Make sure this fits' not in text and len(text) > 10:
                    bullets.append(text)
    data['bullets'] = bullets[:5] if bullets else ['未能抓取五点描述']

    # 技术规格
    specs = {}
    table = soup.find('table', id='prodDetTable')
    if not table:
        table = soup.find('table', id='productDetails_techSpec_section_1')
    if table:
        for row in table.find_all('tr'):
            th = row.find('th')
            td = row.find('td')
            if th and td:
                k = th.get_text(strip=True)
                v = td.get_text(strip=True)
                if k and v:
                    specs[k] = v
    data['tech_specs'] = specs

    # 图片数量
    imgs = soup.find_all('img', class_='a-dynamic-image')
    data['images_count'] = len(imgs) if imgs else len(re.findall(r'altImageCard', html))

    # 视频
    data['has_video'] = bool(soup.find('video') or re.search(r'video|vp\.', html, re.IGNORECASE))

    # A+页面
    data['has_aplus'] = bool(soup.find(class_='aplus-v2') or 'aplus' in html)

    # BSR
    m = re.search(r'#([\d,]+)\s+in\s+([^(<]+)', html)
    data['bsr_rank'] = m.group(1).replace(',', '') if m else 'N/A'
    data['bsr_category'] = m.group(2).strip() if m else 'N/A'

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
    bullets_text = ' '.join(bullets).lower()

    # CDQ checks
    if re.search(r'["""\u201c\u201d″]', title):
        cdq_issues.append({'level': 'high', 'title': '标题含特殊字符（引号）',
            'detail': '标题中的引号字符可能触发CDQ解析异常，建议替换为"-Inch"或删去'})
        cdq_score -= 10

    words = title_lower.split()
    word_counts = {}
    for w in words:
        if len(w) > 3: word_counts[w] = word_counts.get(w, 0) + 1
    repeated = {k: v for k, v in word_counts.items() if v > 1}
    if repeated:
        cdq_issues.append({'level': 'high', 'title': '标题关键词重复',
            'detail': f'重复词: {", ".join(f"{k}×{v}" for k,v in repeated.items())}，可能触发堆砌降权'})
        cdq_score -= 8

    voltage = ''
    for k, v in specs.items():
        if 'voltage' in k.lower() or 'volt' in k.lower():
            voltage = v; break
    if voltage and re.search(r'(230|220|240)', voltage):
        cdq_issues.append({'level': 'critical', 'title': '电压值异常（应为110-120V）',
            'detail': f'当前: {voltage}，错误电压导致退货和降权'})
        cdq_score -= 15
    elif not voltage:
        cdq_issues.append({'level': 'medium', 'title': '缺失电压属性', 'detail': 'CDQ高权重属性，建议补充'})
        cdq_score -= 3

    wattage_vals = {k: v for k, v in specs.items() if 'watt' in k.lower() or 'power' in k.lower()}
    if len(set(wattage_vals.values())) > 1:
        cdq_issues.append({'level': 'high', 'title': '功率数据不一致',
            'detail': f'多个功率值: {", ".join(f"{k}={v}" for k,v in wattage_vals.items())}'})
        cdq_score -= 8

    important = ['Noise Level', 'Certification', 'Material', 'Item Weight', 'Wattage', 'Package Dimensions']
    missing = [a for a in important if not any(a.lower() in k.lower() for k in specs)]
    if missing:
        cdq_issues.append({'level': 'medium', 'title': f'缺失{len(missing)}个高权重属性',
            'detail': f'建议补充: {", ".join(missing[:4])}'})
        cdq_score -= 3 * min(len(missing), 4)

    if len(title) < 80:
        cdq_issues.append({'level': 'low', 'title': f'标题偏短({len(title)}字符)',
            'detail': '建议150-200字符充分利用关键词空间'})
        cdq_score -= 3

    # LQI checks
    if 'bpa' in title_lower and 'bpa' not in bullets_text:
        lqi_issues.append({'level': 'high', 'title': 'BPA Free仅标题提及',
            'detail': '小家电Top3购买决策因素，五点描述未展开'})
        lqi_score -= 12

    if bullets and len(bullets) >= 5:
        last = bullets[-1].lower()
        if any(w in last for w in ['promise', 'quality', 'guarantee', 'deserve', 'mission', 'committed']):
            lqi_issues.append({'level': 'high', 'title': '第五条五点为品牌套话',
                'detail': '无差异化信息，浪费核心展示位'})
            lqi_score -= 10

    if images_count < 7:
        lqi_issues.append({'level': 'high', 'title': f'图片不足({images_count}张)',
            'detail': '建议9张以上，Top10平均10-12张'})
        lqi_score -= 12
    elif images_count < 9:
        lqi_issues.append({'level': 'medium', 'title': f'图片可补充({images_count}张)',
            'detail': '建议补充至9张以上'})
        lqi_score -= 5

    if not has_video:
        lqi_issues.append({'level': 'medium', 'title': '缺少产品视频',
            'detail': '视频提升转化率20%+'})
        lqi_score -= 8

    if not has_aplus:
        lqi_issues.append({'level': 'medium', 'title': '缺少A+页面',
            'detail': 'A+页面提升转化率3-10%'})
        lqi_score -= 8

    diff_words = ['wider', 'larger', 'unique', 'only', 'first', 'exclusive', 'unlike', 'compared']
    if not any(w in bullets_text for w in diff_words):
        lqi_issues.append({'level': 'medium', 'title': '卖点缺乏竞品对比',
            'detail': '消费者无法感知差异化价值'})
        lqi_score -= 6

    pct = re.findall(r'([\d.]+%)\s*(?:juice|yield|extract)', bullets_text)
    if pct and not any(w in bullets_text for w in ['test', 'lab', 'certif', 'verif']):
        lqi_issues.append({'level': 'low', 'title': '数据声明缺乏支撑',
            'detail': f'"{pct[0]}"无第三方测试或认证支撑'})
        lqi_score -= 4

    cdq_score = max(0, min(100, cdq_score))
    lqi_score = max(0, min(100, lqi_score))
    overall = int(cdq_score * 0.5 + lqi_score * 0.5)

    if overall >= 90: grade = 'Optimized'
    elif overall >= 75: grade = 'Great'
    elif overall >= 60: grade = 'Good'
    elif overall >= 40: grade = 'Fair'
    else: grade = 'Poor'

    # 优化标题
    opt = title
    for ch in ['"', '\u201c', '\u201d', '\u2033', '″']: opt = opt.replace(ch, '-Inch ')
    words = opt.split(); seen = set(); deduped = []
    for w in words:
        wl = w.lower().rstrip('s')
        if wl not in seen or len(w) <= 3: deduped.append(w); seen.add(wl)
    opt = ' '.join(deduped)

    return {'cdq_score': cdq_score, 'lqi_score': lqi_score, 'overall_score': overall,
            'grade': grade, 'cdq_issues': cdq_issues, 'lqi_issues': lqi_issues,
            'optimized_title': opt}


def escape(text):
    return text.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')


def generate_report(data, audit):
    asin = data['asin']
    title = escape(data.get('title','N/A'))
    brand = escape(data.get('brand','N/A'))
    price = data.get('price','N/A')
    rating = data.get('rating','N/A')
    review_count = data.get('review_count','N/A')
    bullets = data.get('bullets',[])
    specs = data.get('tech_specs',{})
    images_count = data.get('images_count',0)
    has_video = data.get('has_video',False)
    has_aplus = data.get('has_aplus',False)
    bsr_rank = data.get('bsr_rank','N/A')
    bsr_category = escape(data.get('bsr_category','N/A'))
    url = data['url']
    cdq = audit['cdq_score']; lqi = audit['lqi_score']; overall = audit['overall_score']; grade = audit['grade']

    def ring(score, color, label):
        c = 2*3.14159*42; o = c*(1-score/100)
        return f'<div class="ring-container"><svg width="100" height="100" viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" fill="none" stroke="#0f3460" stroke-width="8"/><circle cx="50" cy="50" r="42" fill="none" stroke="{color}" stroke-width="8" stroke-dasharray="{c:.1f}" stroke-dashoffset="{o:.1f}" transform="rotate(-90 50 50)" stroke-linecap="round"/></svg><div class="ring-score">{score}</div><div class="ring-label">{label}</div></div>'

    # 生成问题卡片
    cdq_cards = ''
    for i, iss in enumerate(audit['cdq_issues'], 1):
        icon = {'critical':'🔴','high':'⚠️','medium':'🟡','low':'ℹ️'}.get(iss['level'],'ℹ️')
        cdq_cards += f'<div class="issue-card cdq-issue"><div class="issue-num">{i}</div><div class="issue-content"><div class="issue-title">{icon} {escape(iss["title"])}</div><div class="issue-detail">{escape(iss["detail"])}</div></div></div>'

    lqi_cards = ''
    for i, iss in enumerate(audit['lqi_issues'], 1):
        icon = {'high':'❌','medium':'⚠️','low':'💡'}.get(iss['level'],'ℹ️')
        lqi_cards += f'<div class="issue-card lqi-issue"><div class="issue-num">{i}</div><div class="issue-content"><div class="issue-title">{icon} {escape(iss["title"])}</div><div class="issue-detail">{escape(iss["detail"])}</div></div></div>'

    bullets_h = ''.join(f'<div class="bullet-item"><span class="bullet-num">{i}</span><span>{escape(b[:120]+("..." if len(b)>120 else ""))}</span></div>' for i,b in enumerate(bullets[:5],1))
    specs_h = ''.join(f'<tr><td class="spec-key">{escape(k)}</td><td class="spec-val">{escape(v)}</td></tr>' for k,v in specs.items())

    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Listing审计 - {asin}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#1a1a2e;color:#fff;line-height:1.6}}.container{{max-width:900px;margin:0 auto;padding:20px}}.header{{background:linear-gradient(135deg,#16213e,#0f3460);padding:30px 20px;text-align:center;border-bottom:2px solid #FF9900;margin-bottom:30px;border-radius:0 0 12px 12px}}.header h1{{font-size:1.5rem;margin-bottom:4px}}.header .subtitle{{color:#a0a0a0;font-size:0.85rem}}.back-link{{display:inline-block;margin-bottom:20px;color:#16c79a;text-decoration:none;font-size:0.9rem}}.section{{background:#16213e;border-radius:12px;padding:25px;margin-bottom:25px;border:1px solid #0f3460}}.section-title{{font-size:1.2rem;margin-bottom:20px;padding-bottom:10px;border-bottom:1px solid #0f3460}}.meta-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:15px}}.meta-item{{background:#1a1a2e;padding:12px;border-radius:8px}}.meta-label{{color:#a0a0a0;font-size:0.8rem;margin-bottom:4px}}.meta-value{{font-weight:600;font-size:1rem}}.scores{{display:flex;justify-content:center;gap:40px;flex-wrap:wrap;margin:20px 0}}.ring-container{{text-align:center;position:relative;width:100px;margin:0 auto}}.ring-score{{position:absolute;top:38px;left:0;right:0;font-size:1.4rem;font-weight:700}}.ring-label{{margin-top:8px;font-size:0.85rem;color:#a0a0a0}}.grade-badge{{text-align:center;margin:15px 0;font-size:1.3rem;font-weight:700;padding:10px 24px;border-radius:20px;display:inline-block}}.grade-optimized{{background:#16c79a;color:#111}}.grade-great{{background:#4ade80;color:#111}}.grade-good{{background:#FF9900;color:#111}}.grade-fair{{background:#f59e0b;color:#111}}.grade-poor{{background:#e94560;color:#fff}}.issue-card{{display:flex;gap:12px;padding:14px;border-radius:8px;margin-bottom:10px;align-items:flex-start}}.cdq-issue{{background:#2d1b1b;border-left:4px solid #e94560}}.lqi-issue{{background:#1b2d1b;border-left:4px solid #f59e0b}}.issue-num{{background:#0f3460;color:#16c79a;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:0.85rem;flex-shrink:0}}.issue-title{{font-weight:600;margin-bottom:4px}}.issue-detail{{color:#a0a0a0;font-size:0.9rem}}.bullet-item{{display:flex;gap:10px;padding:10px;background:#1a1a2e;border-radius:6px;margin-bottom:8px;align-items:flex-start}}.bullet-num{{background:#0f3460;color:#16c79a;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:0.8rem;font-weight:700;flex-shrink:0}}.specs-table{{width:100%;border-collapse:collapse}}.specs-table td{{padding:10px 12px;border-bottom:1px solid #0f3460;font-size:0.9rem}}.spec-key{{color:#a0a0a0;width:40%}}.spec-val{{color:#fff}}.optimized-title{{background:#1b2d1b;border:1px solid #16c79a;padding:16px;border-radius:8px;line-height:1.5}}.original-title{{background:#2d1b1b;border:1px solid #e94560;padding:16px;border-radius:8px;line-height:1.5;margin-bottom:12px}}.compare-arrow{{text-align:center;font-size:2rem;color:#16c79a;margin:10px 0}}.footer{{text-align:center;padding:30px;color:#555;font-size:0.85rem;border-top:1px solid #0f3460;margin-top:30px}}@media(max-width:600px){{.meta-grid{{grid-template-columns:1fr 1fr}}.scores{{gap:20px}}}}</style></head><body>
<div class="header"><h1>🔍 Listing CDQ/LQI 深度审计</h1><div class="subtitle">ASIN: {asin} · {brand}</div></div>
<div class="container"><a href="https://weian8194-png.github.io/policy-daily/listing-audit/" class="back-link">← 返回输入新ASIN</a>
<div class="section"><h2 class="section-title">📋 产品基本信息</h2><div class="meta-grid">
<div class="meta-item"><div class="meta-label">ASIN</div><div class="meta-value">{asin}</div></div>
<div class="meta-item"><div class="meta-label">品牌</div><div class="meta-value">{brand}</div></div>
<div class="meta-item"><div class="meta-label">价格</div><div class="meta-value">${price}</div></div>
<div class="meta-item"><div class="meta-label">评分</div><div class="meta-value">{rating} ★</div></div>
<div class="meta-item"><div class="meta-label">评论数</div><div class="meta-value">{review_count}</div></div>
<div class="meta-item"><div class="meta-label">BSR排名</div><div class="meta-value">#{bsr_rank}</div></div>
<div class="meta-item"><div class="meta-label">图片/视频</div><div class="meta-value">{images_count}张{"+ 视频" if has_video else ""}</div></div>
<div class="meta-item"><div class="meta-label">A+页面</div><div class="meta-value">{"✅有" if has_aplus else "❌无"}</div></div>
</div><div style="margin-top:15px;color:#a0a0a0;font-size:0.9rem"><strong style="color:#fff">标题：</strong>{title}</div>
<div style="margin-top:8px;color:#a0a0a0;font-size:0.85rem">BSR: {bsr_category} &nbsp;|&nbsp; <a href="{url}" target="_blank" style="color:#FF9900">在Amazon打开 →</a></div></div>
<div class="section"><h2 class="section-title">📊 综合评分</h2><div class="scores">{ring(cdq,"#e94560","CDQ")}{ring(lqi,"#16c79a","LQI")}{ring(overall,"#FF9900","综合")}</div><div style="text-align:center"><span class="grade-badge grade-{grade.lower()}">当前等级: {grade}</span></div></div>
<div class="section"><h2 class="section-title">🔴 CDQ降权风险（{len(audit["cdq_issues"])}项）</h2>{cdq_cards if cdq_cards else '<p style="color:#16c79a">✅ 未发现明显CDQ降权风险</p>'}</div>
<div class="section"><h2 class="section-title">🟡 LQI转化流失点（{len(audit["lqi_issues"])}项）</h2>{lqi_cards if lqi_cards else '<p style="color:#16c79a">✅ 未发现明显LQI转化流失</p>'}</div>
<div class="section"><h2 class="section-title">✏️ 标题优化</h2><div class="original-title"><strong>Before:</strong> {title}</div><div class="compare-arrow">↓</div><div class="optimized-title"><strong>After:</strong> {escape(audit["optimized_title"])}</div></div>
<div class="section"><h2 class="section-title">📝 当前五点描述</h2>{bullets_h}</div>
<div class="section"><h2 class="section-title">⚙️ 技术规格</h2><table class="specs-table">{specs_h if specs_h else '<tr><td colspan="2" style="color:#a0a0a0;text-align:center;padding:20px">未抓取到技术规格</td></tr>'}</table></div>
<div class="footer"><p>Listing CDQ/LQI审计工具 · GitHub Actions自动执行 · 数据实时抓取自Amazon</p></div></div></body></html>'''


if __name__ == '__main__':
    print(f'抓取ASIN: {ASIN}...')
    data = fetch_amazon(ASIN)
    print(f'标题: {data.get("title", "N/A")[:60]}')
    print(f'品牌: {data.get("brand", "N/A")}')
    print(f'价格: ${data.get("price", "N/A")}')

    print('执行审计...')
    audit = audit_listing(data)
    print(f'CDQ: {audit["cdq_score"]} | LQI: {audit["lqi_score"]} | 综合: {audit["overall_score"]} ({audit["grade"]})')

    print('生成报告...')
    report = generate_report(data, audit)

    report_path = os.path.join(REPORT_DIR, f'{ASIN}.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f'报告已保存: {report_path}')

    # 更新首页index.html中的最近报告列表
    index_path = os.path.join(REPO_DIR, 'listing-audit', 'index.html')
    # 首页会由单独的脚本生成/更新
    print('完成!')
