// Listing CDQ/LQI Audit API v7 - User Feedback Fixes
// Fixes: attribute search scope, title optimization, bullet analysis, 
// comparative language detection, benefit-opening detection,
// wattage false positive, voltage category-aware
// Uses RapidAPI Real-Time Amazon Data API

export const config = { runtime: 'edge' };

const RAPIDAPI_HOST = 'real-time-amazon-data.p.rapidapi.com';
const RAPIDAPI_KEY = process.env.RAPIDAPIKEY || '';

function jsonRes(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
  });
}

async function fetchAmazonData(asin) {
  if (!RAPIDAPI_KEY) {
    return { error: 'API key not configured. Please set RAPIDAPIKEY environment variable in Vercel.', asin };
  }

  const url = `https://${RAPIDAPI_HOST}/product-details?asin=${asin}&country=US`;

  try {
    const resp = await fetch(url, {
      headers: {
        'x-rapidapi-host': RAPIDAPI_HOST,
        'x-rapidapi-key': RAPIDAPI_KEY,
      },
      signal: AbortSignal.timeout(25000),
    });

    if (!resp.ok) {
      const body = await resp.text();
      return { error: `API returned ${resp.status}: ${body.slice(0, 200)}`, asin };
    }

    const json = await resp.json();

    if (json.message && json.message.includes('not subscribed')) {
      return { error: 'RapidAPI subscription required. Please subscribe to Real-Time Amazon Data API (free tier available).', asin };
    }

    const product = json.data;
    if (!product || !product.product_title) {
      return { error: 'No product data returned. ASIN may be invalid or product unavailable.', asin };
    }

    const data = {
      asin,
      url: `https://www.amazon.com/dp/${asin}`,
      title: product.product_title || 'N/A',
      brand: (product.product_byline || 'N/A').replace('Visit the ', '').replace(' Store', ''),
      price: '',
      original_price: '',
      rating: product.product_star_rating?.toString() || 'N/A',
      review_count: product.product_num_ratings?.toString() || 'N/A',
      bullets: [],
      tech_specs: {},
      images_count: 0,
      has_video: false,
      has_aplus: false,
      bsr_rank: 'N/A',
      bsr_category: 'N/A',
      deal_type: 'none',
      is_amazon_choice: product.is_amazon_choice || false,
      is_best_seller: product.is_best_seller || false,
      availability: product.product_availability || '',
      sales_volume: product.sales_volume || '',
    };

    if (product.product_price) data.price = String(product.product_price).replace(/[^0-9.]/g, '');
    if (product.product_original_price) data.original_price = String(product.product_original_price).replace(/[^0-9.]/g, '');
    if (product.deal_badge === 'Limited time deal') data.deal_type = 'BD';

    if (Array.isArray(product.about_product)) {
      data.bullets = product.about_product.filter(b => b && b.trim().length > 5).slice(0, 5);
    }

    if (product.product_information && typeof product.product_information === 'object') {
      for (const [k, v] of Object.entries(product.product_information)) {
        if (typeof v === 'string' || typeof v === 'number') {
          data.tech_specs[k] = String(v);
        }
      }
    }

    if (Array.isArray(product.product_photos)) data.images_count = product.product_photos.length;
    data.has_video = Array.isArray(product.product_videos) && product.product_videos.length > 0;
    data.has_aplus = !!product.has_aplus;

    if (data.tech_specs['Best Sellers Rank']) {
      const bsrStr = data.tech_specs['Best Sellers Rank'];
      const bsrMatch = bsrStr.match(/#([\d,]+)/);
      if (bsrMatch) data.bsr_rank = bsrMatch[1].replace(/,/g, '');
      const catMatch = bsrStr.match(/in\s+([^((]+)/);
      if (catMatch) data.bsr_category = catMatch[1].trim();
    }

    return data;
  } catch (err) {
    return { error: `Fetch failed: ${err.message}`, asin };
  }
}

// ========== Fix #1: Search attribute across entire listing ==========
function findAttrInListing(attrName, title, bullets, specs) {
  const attrLower = attrName.toLowerCase();
  const aliases = {
    'noise level': ['noise', 'decibel', 'db', 'quiet', 'sound level', 'operating noise'],
    'certification': ['certified', 'certification', 'ul listed', 'etl', 'ce', 'fcc', 'energy star', 'ul certified'],
    'material': ['material', 'stainless steel', 'bpa-free', 'bpa free', 'plastic', 'aluminum', 'silicone', 'glass', 'bamboo'],
    'package dimensions': ['package dimension', 'package size', 'boxed dimension', 'product dimension', 'item dimension'],
    'wattage': ['wattage', 'watt', 'power consumption', 'rated power'],
    'item weight': ['weight', 'lb', 'kg', 'ounce', 'pound'],
    'voltage': ['voltage', 'volt', 'v ac', 'v dc', '110v', '120v', '220v', '240v'],
    'capacity': ['capacity', 'volume', 'quart', 'liter', 'can hold', 'cubic'],
    'color': ['color', 'colour'],
  };
  const keywords = aliases[attrLower] || [attrLower];
  const titleLower = title.toLowerCase();
  const bulletsText = bullets.join(' ').toLowerCase();

  // 1. Check specs (Product Information)
  for (const [k, v] of Object.entries(specs)) {
    const kLower = k.toLowerCase();
    if (keywords.some(kw => kLower.includes(kw))) return { found: true, location: 'specs' };
    const vLower = String(v).toLowerCase();
    if (keywords.some(kw => vLower.includes(kw))) return { found: true, location: 'specs' };
  }
  // 2. Check title
  if (keywords.some(kw => titleLower.includes(kw))) return { found: true, location: 'title' };
  // 3. Check bullets
  if (keywords.some(kw => bulletsText.includes(kw))) return { found: true, location: 'bullets' };

  return { found: false, location: '' };
}

// ========== Fix #4: Enhanced comparative language detection ==========
function hasComparativeLanguage(bullets) {
  if (!bullets || bullets.length === 0) return false;
  const text = bullets.join(' ').toLowerCase();

  const comparisonWords = [
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
  ];

  // Pattern: multiplier comparison "X times more/less"
  if (/\d+x\s+(?:more|less|faster|quieter|longer|bigger|better)/.test(text)) return true;
  // Pattern: "than standard/conventional/other/traditional"
  if (/than\s+(?:standard|conventional|other|traditional|normal|regular|typical|ordinary)/.test(text)) return true;
  // Pattern: "X-inch vs Y-inch"
  if (/\d+[\d.]*-?\s*(?:inch|in|cm|mm|oz|ml|l)\s+vs/.test(text)) return true;

  return comparisonWords.some(w => text.includes(w));
}

// ========== Fix #5: Benefit-oriented opening detection ==========
function classifyBulletOpening(bulletText) {
  if (!bulletText) return 'feature';
  const colonMatch = bulletText.match(/^([^:]{2,50}):/);
  const opening = colonMatch ? colonMatch[1].trim().toLowerCase() : bulletText.slice(0, 50).toLowerCase();

  const benefitPatterns = [
    /^(save|stay|enjoy|keep|get|make|create|protect|prevent|avoid|eliminate|reduce|maximize|minimize|never|always|easily|quickly|safely|effortlessly)/,
    /^(easy|quiet|portable|convenient|safe|durable|reliable|powerful|efficient|comfortable|healthy|smart|versatile|flexible|compact|lightweight|ultra)/,
    /^(no more|no need|never worry|peace of mind|ready to|perfect for|ideal for|designed for|built for)/,
    /^easy\s+to\s+/,
    /^save\s+/,
  ];
  for (const pat of benefitPatterns) {
    if (pat.test(opening)) return 'benefit';
  }

  // Feature patterns
  if (/^\d/.test(opening)) return 'feature';
  if (/^(dual|triple|single|multi|2-in-1|3-in-1)\s+/.test(opening)) return 'feature';
  if (/^(the\s+)?(compressor|motor|battery|chute|blade|filter|tank|cable|cord|adapter|handle|wheel)/.test(opening)) return 'feature';

  // Check first word for benefit-ish quality
  const firstWord = (opening.split(/\s+/)[0] || '').replace(/[,;.]/g, '');
  const benefitFirstWords = new Set([
    'fast', 'rapid', 'quick', 'ultra', 'super', 'powerful', 'quiet',
    'easy', 'safe', 'smart', 'portable', 'compact', 'lightweight',
    'premium', 'advanced', 'pro', 'max', 'eco',
  ]);
  if (benefitFirstWords.has(firstWord)) return 'benefit';

  return 'feature';
}

// ========== DATA COMPLETENESS ==========
function assessCompleteness(data) {
  const modules = [
    { key: 'title', label: '标题', fetched: data.title && data.title !== 'N/A', note: '可用于标题合规分析' },
    { key: 'bullets', label: '五点描述', fetched: data.bullets && data.bullets.length > 0 && data.bullets[0] !== 'Failed to extract bullets', note: '可用于LQI与关键词分析' },
    { key: 'specs', label: '技术规格', fetched: data.tech_specs && Object.keys(data.tech_specs).length > 0, note: '可用于CDQ一致性分析' },
    { key: 'images', label: '图片数量', fetched: data.images_count > 0, note: '仅识别数量，未分析图片文案' },
    { key: 'video', label: '视频', fetched: data.has_video, note: '仅判断有无，未分析视频内容' },
    { key: 'aplus', label: 'A+页面', fetched: data.has_aplus, note: '仅判断有无，未分析模块质量' },
    { key: 'reviews', label: '评论内容', fetched: false, note: '暂未抓取，无法进行VOC分析' },
    { key: 'price', label: '价格信息', fetched: !!data.price, note: '可用于优惠分析' },
  ];
  const fetched = modules.filter(m => m.fetched).length;
  return { modules, fetched, total: modules.length, percentage: Math.round(fetched / modules.length * 100) };
}

// ========== SUB-DIMENSION SCORING + EXPLAINABLE ISSUES (v7) ==========
function auditListing(data) {
  const title = data.title || '';
  const bullets = data.bullets || [];
  const specs = data.tech_specs || {};
  const imagesCount = data.images_count || 0;
  const hasVideo = data.has_video || false;
  const hasAplus = data.has_aplus || false;
  const titleLower = title.toLowerCase();
  const bulletsText = bullets.join(' ').toLowerCase();

  const cdqTitleCompliance = { name: '标题规范', max: 30, score: 30, issues: [] };
  const cdqAttributeComplete = { name: '属性饱和度', max: 30, score: 30, issues: [] };
  const cdqDataConsistency = { name: '数据一致性', max: 40, score: 40, issues: [] };

  const lqiContentQuality = { name: '内容质量', max: 35, score: 35, issues: [] };
  const lqiMediaCoverage = { name: '媒体覆盖', max: 35, score: 35, issues: [] };
  const lqiDifferentiation = { name: '差异化表达', max: 30, score: 30, issues: [] };

  function addIssue(dim, deduction, level, title_text, impact, fix) {
    dim.score = Math.max(0, dim.score - deduction);
    dim.issues.push({ level, title: title_text, impact, fix, deduction });
  }

  // ===== CDQ: Title Compliance =====
  if (/["""\u201c\u201d\u2033]/.test(title)) {
    addIssue(cdqTitleCompliance, 8, 'high', '标题含特殊字符(引号/英寸符号)',
      'CDQ系统可能解析异常，导致属性缺失或索引失败',
      '将 " 和 ″ 替换为 Inch，将引号内容改为短横线连接');
  }

  const wordCounts = {};
  titleLower.split(/\s+/).forEach(w => { if (w.length > 3) wordCounts[w] = (wordCounts[w] || 0) + 1; });
  const repeated = Object.entries(wordCounts).filter(([, v]) => v > 1);
  if (repeated.length) {
    addIssue(cdqTitleCompliance, 7, 'high', `标题关键词重复(${repeated.length}组)`,
      '亚马逊视为关键词堆砌，可能降权或限制展示',
      `去除重复词: ${repeated.map(([k, v]) => `${k}(${v}次)`).join(', ')}，每词仅保留1次`);
  }

  if (title.length < 80) {
    addIssue(cdqTitleCompliance, 5, 'medium', `标题偏短(${title.length}字符)`,
      '浪费搜索权重空间，少了150+字符可携带的关键词',
      `补充至150-200字符，优先添加用途/场景/材质/颜色等属性`);
  } else if (title.length > 200) {
    addIssue(cdqTitleCompliance, 8, 'high', `标题过长(${title.length}字符)`,
      '超200字符被截断，尾部关键词无效，堆砌风险高',
      '精简至200字符内，保留核心关键词，删除冗余修饰');
  }

  const brandInTitle = data.brand && data.brand !== 'N/A' && titleLower.startsWith(data.brand.toLowerCase());
  if (!brandInTitle && data.brand && data.brand !== 'N/A') {
    addIssue(cdqTitleCompliance, 5, 'medium', '品牌名未在标题首位',
      '品牌前置提升搜索权重和品牌认知，CDQ推荐格式Brand+Core+Specs',
      `将 "${data.brand}" 移到标题最前面`);
  }

  // ===== CDQ: Attribute Completeness (Fix #1: search entire listing) =====
  // Fix #7: Category-aware voltage check
  const voltageResult = findAttrInListing('voltage', title, bullets, specs);
  let voltageVal = '';
  for (const [k, v] of Object.entries(specs)) {
    if (/voltage|volt/i.test(k)) { voltageVal = v; break; }
  }

  if (voltageVal && /(230|220|240)/.test(voltageVal)) {
    addIssue(cdqDataConsistency, 15, 'critical', `电压值异常: ${voltageVal}`,
      '美国市场应为110-120V，错误电压导致退货率飙升和CDQ降权',
      '立即修改后台Voltage属性为正确值(110V或120V)');
  } else if (!voltageResult.found) {
    // Check if category even has voltage fields
    const hasPowerFields = Object.keys(specs).some(k => /watt|power/i.test(k));
    const hasPowerSource = Object.keys(specs).some(k => /power source/i.test(k));
    if (hasPowerFields || hasPowerSource) {
      // Category has power but no voltage field - likely doesn't need it
      addIssue(cdqAttributeComplete, 1, 'low', '建议补充电压属性(可选)',
        '当前类目后台可能无电压字段，如可补充则建议填写110-120V',
        '在后台Attributes中查看是否有Voltage字段，如有则补充110-120V');
    } else {
      addIssue(cdqAttributeComplete, 5, 'medium', '缺失电压属性',
        '已在标题/五点/Product Information中搜索，均未找到电压信息',
        '在后台Attributes中补充Voltage值(美国市场填110-120V)');
    }
  }

  // Fix #1: Search attributes across entire listing (not just specs)
  const importantAttrs = [
    { key: 'Noise Level', cn: '噪音等级', weight: 4 },
    { key: 'Certification', cn: '认证', weight: 4 },
    { key: 'Material', cn: '材质', weight: 5 },
    { key: 'Item Weight', cn: '重量', weight: 3 },
    { key: 'Package Dimensions', cn: '包装尺寸', weight: 3 },
    { key: 'Wattage', cn: '功率', weight: 5 },
    { key: 'Capacity', cn: '容量', weight: 4 },
    { key: 'Color', cn: '颜色', weight: 2 },
  ];

  const missingAttrs = [];
  const foundAttrsInfo = [];
  for (const a of importantAttrs) {
    const result = findAttrInListing(a.key, title, bullets, specs);
    if (!result.found) {
      missingAttrs.push(a);
    } else {
      const locNames = { specs: 'Product Information', title: '标题', bullets: '五点描述' };
      foundAttrsInfo.push(`${a.key} → 已在${locNames[result.location] || result.location}中找到`);
    }
  }

  if (missingAttrs.length) {
    const totalWeight = missingAttrs.reduce((s, a) => s + a.weight, 0);
    const deduction = Math.min(totalWeight, 20);
    const attrList = missingAttrs.map(a => `${a.key}(${a.cn})`).join(', ');
    const categoryNote = missingAttrs.length > 3 ? '（如当前类目后台无该字段，可忽略）' : '';
    addIssue(cdqAttributeComplete, deduction, 'medium', `缺失${missingAttrs.length}个高权重属性`,
      `已在标题/五点/Product Information中搜索，字段饱和度不足，影响搜索收录和过滤器匹配`,
      `补充: ${attrList}，优先补权重≥4的属性${categoryNote}`);
  }

  // ===== CDQ: Data Consistency =====
  // Fix #6: Don't compare Power Plug Type / Power Source with Wattage
  const wattageVals = {};
  for (const [k, v] of Object.entries(specs)) {
    const kLower = k.toLowerCase();
    // Only include true wattage/power measurement fields
    if ((/wattage|watt/i.test(kLower) && !/plug|source/i.test(kLower)) || kLower === 'maximum power' || kLower === 'rated power') {
      wattageVals[k] = v;
    }
  }
  if (Object.keys(wattageVals).length > 1 && new Set(Object.values(wattageVals)).size > 1) {
    addIssue(cdqDataConsistency, 10, 'high', `功率数据不一致`,
      '多个功率字段值冲突，亚马逊可能标记数据异常，消费者产生信任危机',
      `统一为一个值: ${Object.entries(wattageVals).map(([k, v]) => `${k}=${v}`).join(', ')}，建议以额定功率为准`);
  }

  if (/[\d.]+%/.test(title)) {
    addIssue(cdqDataConsistency, 5, 'medium', '标题含百分号(%)',
      '亚马逊标题规范建议避免特殊符号，百分号可能触发CDQ解析问题',
      '将百分号改为 Percent，如 99.6% → 99.6 Percent');
  }

  // ===== LQI: Content Quality =====
  if (titleLower.includes('bpa') && !bulletsText.includes('bpa')) {
    addIssue(lqiContentQuality, 8, 'high', 'BPA Free仅标题提及，五点未展开',
      '消费者在决策区域看不到关键卖点，转化率流失',
      '在五点中增加一条展开BPA-Free卖点');
  }

  if (bullets.length >= 5) {
    const last = bullets[bullets.length - 1].toLowerCase();
    if (['promise', 'quality', 'guarantee', 'deserve', 'mission', 'committed'].some(w => last.includes(w))) {
      addIssue(lqiContentQuality, 8, 'high', '第五条五点为品牌套话',
        '第五条是转化黄金位，品牌套话浪费了最后说服买家的机会',
        '替换为实际卖点(清洁方式/配件/保修)');
    }
  }

  const pctMatch = bulletsText.match(/([\d.]+%)\s*(?:juice|yield|extract)/);
  if (pctMatch && !['test', 'lab', 'certif', 'verif', 'independ'].some(w => bulletsText.includes(w))) {
    addIssue(lqiContentQuality, 4, 'low', `数据声明"${pctMatch[1]}"缺乏第三方认证`,
      '无支撑的数字声明可能被消费者质疑，也面临合规风险',
      `补充第三方测试报告或修改措辞为"Up to ${pctMatch[1]}"，并附上测试机构名称`);
  }

  // ===== LQI: Media Coverage =====
  if (imagesCount < 7) {
    addIssue(lqiMediaCoverage, 10, 'high', `图片严重不足(仅${imagesCount}张)`,
      '7张以下图片转化率显著偏低，竞品通常9-15张',
      '补充至9张以上: 1主图+2场景图+2细节图+1尺寸图+1配件图+1对比图');
  } else if (imagesCount < 9) {
    addIssue(lqiMediaCoverage, 5, 'medium', `图片可补充(${imagesCount}张)`,
      '9张是及格线，Top竞品通常12张以上',
      '补充场景图和生活方式图至9+张');
  }

  if (!hasVideo) {
    addIssue(lqiMediaCoverage, 8, 'high', '缺少产品视频',
      '视频提升转化率20%+，亚马逊优先展示含视频的Listing',
      '上传30-60秒产品演示视频');
  }

  if (!hasAplus) {
    addIssue(lqiMediaCoverage, 6, 'medium', '缺少A+页面',
      'A+页面提升转化3-10%，是品牌卖家标配',
      '注册品牌后创建A+内容');
  }

  // ===== LQI: Differentiation =====
  // Fix #4: Enhanced comparative language detection
  if (!hasComparativeLanguage(bullets)) {
    addIssue(lqiDifferentiation, 6, 'medium', '卖点缺乏竞品对比语言',
      '消费者无法感知"为什么选你"，纯功能罗列无差异化说服力',
      '在五点中加入对比表述: "Unlike traditional juicers..." / "Wider 5.8-inch vs standard 3-inch..." / "3x faster than..."');
  }

  // Fix #5: Benefit-oriented opening detection
  if (bullets.length > 0) {
    const featureOpenings = [];
    for (let i = 0; i < Math.min(5, bullets.length); i++) {
      const openingType = classifyBulletOpening(bullets[i]);
      if (openingType === 'feature') {
        const colonIdx = bullets[i].indexOf(':');
        const phrase = colonIdx > 0 ? bullets[i].slice(0, colonIdx).trim() : bullets[i].slice(0, 40).trim();
        featureOpenings.push(`第${i + 1}条: "${phrase}"`);
      }
    }

    if (featureOpenings.length >= 3) {
      addIssue(lqiDifferentiation, 4, 'medium', `${featureOpenings.length}条五点缺乏利益导向开头`,
        '消费者扫读时只看开头5个词，功能描述开头不如利益点开头有吸引力',
        `需修改: ${featureOpenings.slice(0, 3).join('; ')}。建议改为利益导向如"Easy to Clean..."/"Save Time with..."/"Stay Safe with..."`);
    }
  }

  // ===== COMPUTE TOTALS =====
  const cdqScore = cdqTitleCompliance.score + cdqAttributeComplete.score + cdqDataConsistency.score;
  const lqiScore = lqiContentQuality.score + lqiMediaCoverage.score + lqiDifferentiation.score;
  const overall = Math.round(cdqScore * 0.5 + lqiScore * 0.5);

  let grade;
  if (overall >= 90) grade = 'Optimized';
  else if (overall >= 75) grade = 'Great';
  else if (overall >= 60) grade = 'Good';
  else if (overall >= 40) grade = 'Fair';
  else grade = 'Poor';

  const titleOpts = generateTitleOptions(title, data.brand, specs, bulletsText);

  // Fix #3: Improved bullet optimization with opening type analysis
  const bulletOptimization = analyzeBullets(bullets, titleLower, specs);
  const bulletRewrites = rewriteBullets(bullets, titleLower, specs);

  const allIssues = [
    ...cdqTitleCompliance.issues.map(i => ({ ...i, dimension: 'CDQ-标题', sub: cdqTitleCompliance.name })),
    ...cdqAttributeComplete.issues.map(i => ({ ...i, dimension: 'CDQ-属性', sub: cdqAttributeComplete.name })),
    ...cdqDataConsistency.issues.map(i => ({ ...i, dimension: 'CDQ-一致', sub: cdqDataConsistency.name })),
    ...lqiContentQuality.issues.map(i => ({ ...i, dimension: 'LQI-内容', sub: lqiContentQuality.name })),
    ...lqiMediaCoverage.issues.map(i => ({ ...i, dimension: 'LQI-媒体', sub: lqiMediaCoverage.name })),
    ...lqiDifferentiation.issues.map(i => ({ ...i, dimension: 'LQI-差异', sub: lqiDifferentiation.name })),
  ].sort((a, b) => {
    const priority = { critical: 0, high: 1, medium: 2, low: 3 };
    return (priority[a.level] || 3) - (priority[b.level] || 3);
  });

  return {
    cdq_score: cdqScore,
    lqi_score: lqiScore,
    overall_score: overall,
    grade,
    cdq_dimensions: [cdqTitleCompliance, cdqAttributeComplete, cdqDataConsistency],
    lqi_dimensions: [lqiContentQuality, lqiMediaCoverage, lqiDifferentiation],
    all_issues: allIssues,
    title_options: titleOpts,
    bullet_optimization: bulletOptimization,
    bullet_rewrites: bulletRewrites,
    found_attrs_info: foundAttrsInfo,
  };
}

// ========== Fix #3: Bullet opening analysis ==========
function analyzeBullets(bullets, titleLower, specs) {
  if (!bullets || bullets.length === 0 || bullets[0] === 'Failed to extract bullets') {
    return [];
  }

  return bullets.slice(0, 5).map((bullet, i) => {
    const openingType = classifyBulletOpening(bullet);
    const colonIdx = bullet.indexOf(':');
    const openingPhrase = colonIdx > 0 ? bullet.slice(0, colonIdx).trim() : bullet.slice(0, 40).trim();

    let suggestion = null;
    if (openingType === 'feature') {
      // Try to convert feature opening to benefit opening
      const featureToBenefit = [
        { re: /^(\d+[\d.]*)\s*(?:lb|quart|liter|l|oz|gal)/i, repl: 'Store More with ' },
        { re: /^(Dual|Triple|Multi|2-in-1|3-in-1)\s+/i, repl: 'Versatile ' },
        { re: /^(Low|High|Eco|Max)\s+(Power|Mode)/i, repl: 'Efficient ' },
      ];
      for (const { re, repl } of featureToBenefit) {
        if (re.test(openingPhrase)) {
          suggestion = repl + openingPhrase + (colonIdx > 0 ? ':' + bullet.slice(colonIdx + 1) : '');
          break;
        }
      }
      if (!suggestion && colonIdx > 0) {
        suggestion = `[利益导向改写] 原开头: "${openingPhrase}" — 建议改为利益导向如"Easy to Clean..."/"Save Time with..."/"Enjoy Quiet Operation with..."`;
      }
    }

    return {
      index: i + 1,
      original: bullet.slice(0, 200),
      opening_type: openingType,
      opening_phrase: openingPhrase,
      suggestion,
    };
  });
}

// ========================================================================
// TITLE OPTIMIZATION ENGINE v4 — FIELD-LOCK + REASSEMBLE (unchanged)
// ========================================================================

function generateTitleOptions(originalTitle, brand, specs, bulletsText) {
  const titleLower = originalTitle.toLowerCase();
  const brandClean = (brand || '').replace('Visit the ', '').replace(' Store', '').trim();
  const specEntries = Object.entries(specs || {});

  const fields = { brand: brandClean, productTypes: [], numericSpecs: [], features: [], certifications: [], useCases: [], color: '', capacity: '', modifiers: [], outputRate: '' };

  for (const [k, v] of specEntries) { if (/^color$/i.test(k.trim())) { fields.color = String(v).trim(); break; } }
  if (!fields.color) {
    const cParen = originalTitle.match(/\(([A-Za-z\s]+?)\)\s*$/);
    if (cParen && cParen[1].length < 25) fields.color = cParen[1].trim();
  }

  const typePatterns = [
    /Snow\s+Cone\s+Machine/i, /Shaved\s+Ice\s+Machine/i, /Electric\s+Ice\s+Shaver/i, /Snow\s+Cone\s+Maker/i,
    /Espresso\s+Coffee\s+Maker/i, /Espresso\s+Machine/i, /Coffee\s+Maker/i,
    /Cold\s+Press\s+Juicer/i, /Slow\s+Masticating\s+Juicer/i, /Masticating\s+Juicer/i, /Juicer\s+Machine/i, /Juicer/i, /Juice\s+Extractor/i,
    /Air\s+Fryer/i, /Deep\s+Fryer/i,
    /Blender/i, /Food\s+Processor/i,
    /Stand\s+Mixer/i, /Hand\s+Mixer/i, /Mixer/i,
    /Ice\s+Cream\s+Maker/i, /Ice\s+Maker/i, /Nugget\s+Ice\s+Maker/i,
    /Rice\s+Cooker/i, /Slow\s+Cooker/i, /Pressure\s+Cooker/i,
    /Toaster\s+Oven/i, /Toaster/i,
    /Waffle\s+Maker/i, /Sandwich\s+Maker/i,
    /Dehydrator/i,
    /Portable\s+Refrigerator/i, /Car\s+Refrigerator/i, /Car\s+Freezer/i, /Electric\s+Cooler/i, /Portable\s+Cooler/i, /12V\s+Refrigerator/i,
  ];
  for (const pat of typePatterns) {
    const m = originalTitle.match(pat);
    if (m && !fields.productTypes.some(pt => pt.toLowerCase() === m[0].toLowerCase())) {
      fields.productTypes.push(m[0].trim());
    }
  }

  const numExtractors = [
    { re: /(\d+[\d,]*\.?\d*)\s*Lbs\s*\/\s*H/i, norm: v => v.replace(/,/g, '') + ' Lbs per Hour', label: 'Output Rate' },
    { re: /(\d+[\d,]*\.?\d*)\s*Pounds?\s*(?:per|\/)\s*Hour/i, norm: v => v.replace(/,/g, '') + ' Lbs per Hour', label: 'Output Rate' },
    { re: /(\d+\.?\d*)\s*Bar\b/i, norm: v => v + ' Bar', label: 'Pressure' },
    { re: /(\d{3,4})\s*W(?:att)?\b/i, norm: v => v + 'W', label: 'Wattage' },
    { re: /(\d+\.?\d*)\s*(?:Liters?|L)\b/i, norm: v => v + ' Liter', label: 'Capacity' },
    { re: /(\d+\.?\d*)\s*(?:Oz|Ounces?)\b/i, norm: v => v + ' Oz', label: 'Capacity' },
    { re: /(\d+\.?\d*)\s*Cups?\b/i, norm: v => v + ' Cup', label: 'Capacity' },
    { re: /(\d+\.?\d*)\s*Quarts?\b/i, norm: v => v + ' Quart', label: 'Capacity' },
    { re: /(\d+\.?\d*)\s*RPM/i, norm: v => v + ' RPM', label: 'Speed' },
    { re: /(\d+\.?\d*)\s*(?:["""\u2033]|Inch)/i, norm: v => v + ' Inch', label: 'Size' },
    { re: /(\d+\.?\d*)%/i, norm: v => v + ' Percent', label: 'Percentage' },
  ];
  const seenLabels = {};
  for (const { re, norm, label } of numExtractors) {
    const m = originalTitle.match(re);
    if (m) {
      const normalized = norm(m[1]);
      if (!seenLabels[label]) {
        fields.numericSpecs.push({ raw: m[0], normalized, label, value: m[1] });
        seenLabels[label] = true;
      }
    }
  }
  if (!seenLabels['Wattage']) {
    for (const [k, v] of specEntries) {
      if (/wattage/i.test(k)) {
        const wVal = String(v).replace(/[^0-9.]/g, '');
        if (wVal) { fields.numericSpecs.push({ raw: v, normalized: wVal + 'W', label: 'Wattage', value: wVal }); break; }
      }
    }
  }

  const outRate = fields.numericSpecs.find(s => s.label === 'Output Rate');
  if (outRate) fields.outputRate = outRate.normalized;
  const capSpec = fields.numericSpecs.find(s => s.label === 'Capacity');
  if (capSpec) fields.capacity = capSpec.normalized + ' Capacity';

  // Features
  const featureChecks = [
    [/with\s+Grinder|built[\s-]*in\s+grinder/i, 'with Grinder'],
    [/milk\s*frother/i, 'with Milk Frother'],
    [/steam\s*wand/i, 'with Steam Wand'],
    [/dual\s+blades?/i, 'Dual Blades'],
    [/bpa[\s-]*free/i, 'BPA Free'],
    [/easy[\s-]*(?:to[\s-]*)?clean/i, 'Easy to Clean'],
    [/dishwasher[\s-]*safe/i, 'Dishwasher Safe'],
    [/wide\s+feed\s+chute/i, 'Wide Feed Chute'],
    [/whole\s+(fruit|vegetable)/i, 'Whole Vegetables and Fruits'],
    [/high\s*juice\s*yield/i, 'High Juice Yield'],
    [/compact/i, 'Compact'],
    [/removable/i, 'Removable'],
    [/touch\s*screen/i, 'Touch Screen'],
    [/semi[\s-]*automatic/i, 'Semi Automatic'],
    [/quiet/i, 'Quiet'],
    [/reverse\s*(?:function)?/i, 'Reverse Function'],
    [/anti[\s-]*drip|drip[\s-]*free/i, 'Anti Drip'],
    [/dual\s+power/i, 'Dual Power'],
    [/shockproof/i, 'Shockproof'],
    [/battery\s*protection/i, 'Battery Protection'],
    [/eco\s*mode/i, 'ECO Mode'],
    [/memory\s*function/i, 'Memory Function'],
  ];
  for (const [re, name] of featureChecks) {
    if (re.test(originalTitle)) fields.features.push(name);
  }

  // Certifications
  const certChecks = [
    [/etl[\s-]*certified/i, 'ETL Certified'],
    [/ul[\s-]*(?:certified|listed)/i, 'UL Certified'],
    [/ce[\s-]*certified/i, 'CE Certified'],
    [/nsf[\s-]*certified/i, 'NSF Certified'],
    [/fcc/i, 'FCC'],
    [/energy\s*star/i, 'Energy Star'],
  ];
  for (const [re, name] of certChecks) {
    if (re.test(originalTitle)) fields.certifications.push(name);
  }

  // Use Cases
  if (/home.*commercial|commercial.*home/i.test(originalTitle)) fields.useCases.push('Home and Commercial Use');
  else if (/home.*kitchen/i.test(originalTitle)) fields.useCases.push('for Home Kitchen');
  else if (/outdoor/i.test(originalTitle) && /indoor/i.test(originalTitle)) fields.useCases.push('Indoor and Outdoor');
  else if (/outdoor/i.test(originalTitle)) fields.useCases.push('for Outdoor');
  else if (/home/i.test(originalTitle)) fields.useCases.push('for Home');
  else if (/commercial/i.test(originalTitle)) fields.useCases.push('Commercial Use');
  if (fields.useCases.length === 0) {
    const forM = originalTitle.match(/for\s+([A-Za-z\s&]+?)(?:\s*[,(]|\s*$)/i);
    if (forM) fields.useCases.push('for ' + forM[1].trim().replace(/&/g, 'and'));
  }

  // Modifiers
  if (/professional/i.test(originalTitle)) fields.modifiers.push('Professional');
  if (/commercial/i.test(originalTitle)) fields.modifiers.push('Commercial');
  if (/barista/i.test(originalTitle)) fields.modifiers.push('Barista Style');
  if (/stainless\s*steel/i.test(originalTitle)) fields.modifiers.push('Stainless Steel');
  if (/portable/i.test(originalTitle)) fields.modifiers.push('Portable');

  // Category detection
  let category = 'generic';
  if (/snow\s+cone|shaved\s+ice|ice\s+shaver/i.test(originalTitle)) category = 'snow_cone';
  else if (/espresso\s*machine|espresso\s*coffee\s*maker/i.test(originalTitle)) category = 'espresso';
  else if (/(?:cold\s*press|slow\s*masticating|masticating)\s*juicer|juice\s*extractor|\bjuicer\b/i.test(originalTitle)) category = 'juicer';
  else if (/air\s*fryer/i.test(originalTitle)) category = 'air_fryer';
  else if (/blender/i.test(originalTitle)) category = 'blender';
  else if (/coffee\s*maker/i.test(originalTitle)) category = 'coffee_maker';
  else if (/mixer/i.test(originalTitle)) category = 'mixer';
  else if (/car\s+refrigerator|car\s+freezer|electric\s+cooler|portable\s+(?:refrigerator|cooler)|12v\s+refrigerator/i.test(originalTitle)) category = 'car_fridge';

  // Positional slots
  const brandSlot = { text: fields.brand || '', name: 'Brand' };
  const coreTypeSlot = [];
  const specSlot = [];
  const featureSlot = [];
  const useCaseSlot = [];
  const sellingPointSlot = [];
  const materialColorSlot = [];

  for (const pt of fields.productTypes) coreTypeSlot.push({ text: pt, name: pt });

  if (category === 'car_fridge') {
    const wattSpec = fields.numericSpecs.find(s => s.label === 'Wattage');
    if (wattSpec) specSlot.push({ text: wattSpec.normalized, name: 'Wattage' });
    if (fields.capacity) specSlot.push({ text: fields.capacity, name: 'Capacity' });
    for (const f of fields.features.slice(0, 3)) featureSlot.push({ text: f, name: f });
    if (fields.useCases.length) useCaseSlot.push({ text: fields.useCases[0], name: 'Use Case' });
    for (const c of fields.certifications) sellingPointSlot.push({ text: c, name: c });
    if (fields.modifiers.includes('Portable')) sellingPointSlot.push({ text: 'Portable', name: 'Portable' });
    if (fields.color) materialColorSlot.push({ text: fields.color, name: 'Color' });
  } else if (category === 'snow_cone') {
    if (fields.outputRate) specSlot.push({ text: fields.outputRate, name: 'Output Rate' });
    const wattSpec = fields.numericSpecs.find(s => s.label === 'Wattage');
    if (wattSpec) specSlot.push({ text: wattSpec.normalized, name: 'Wattage' });
    if (fields.capacity) specSlot.push({ text: fields.capacity, name: 'Capacity' });
    if (fields.features.includes('Dual Blades')) featureSlot.push({ text: 'with Dual Blades', name: 'Dual Blades' });
    if (fields.useCases.length) useCaseSlot.push({ text: fields.useCases[0], name: 'Use Case' });
    if (fields.certifications.includes('ETL Certified')) sellingPointSlot.push({ text: 'ETL Certified', name: 'ETL Certified' });
    if (fields.color) materialColorSlot.push({ text: fields.color, name: 'Color' });
  } else if (category === 'espresso') {
    const barSpec = fields.numericSpecs.find(s => s.label === 'Pressure');
    if (barSpec) specSlot.push({ text: barSpec.normalized, name: 'Bar Pressure' });
    const wattSpec = fields.numericSpecs.find(s => s.label === 'Wattage');
    if (wattSpec) specSlot.push({ text: wattSpec.normalized, name: 'Wattage' });
    if (fields.capacity) specSlot.push({ text: fields.capacity.replace(' Capacity', '') + ' Water Tank', name: 'Water Tank' });
    if (fields.features.includes('with Grinder')) featureSlot.push({ text: 'with Grinder', name: 'Grinder' });
    if (fields.features.includes('with Milk Frother')) featureSlot.push({ text: 'with Milk Frother', name: 'Milk Frother' });
    if (fields.useCases.length) useCaseSlot.push({ text: fields.useCases[0], name: 'Use Case' });
    if (fields.modifiers.includes('Professional')) sellingPointSlot.push({ text: 'Professional', name: 'Professional' });
    if (fields.modifiers.includes('Barista Style')) sellingPointSlot.push({ text: 'Barista Style', name: 'Barista Style' });
    if (fields.modifiers.includes('Stainless Steel')) materialColorSlot.push({ text: 'Stainless Steel', name: 'Material' });
    if (fields.color) materialColorSlot.push({ text: fields.color, name: 'Color' });
  } else if (category === 'juicer') {
    const inchSpec = fields.numericSpecs.find(s => s.label === 'Size');
    if (inchSpec) specSlot.push({ text: inchSpec.normalized + ' Wide Feed Chute', name: 'Feed Chute' });
    const wattSpec = fields.numericSpecs.find(s => s.label === 'Wattage');
    if (wattSpec) specSlot.push({ text: wattSpec.normalized, name: 'Wattage' });
    if (fields.capacity) specSlot.push({ text: fields.capacity, name: 'Capacity' });
    if (fields.features.includes('BPA Free')) featureSlot.push({ text: 'BPA Free', name: 'BPA Free' });
    if (fields.features.includes('Easy to Clean')) featureSlot.push({ text: 'Easy to Clean', name: 'Easy to Clean' });
    if (fields.features.includes('Whole Vegetables and Fruits')) featureSlot.push({ text: 'for Whole Vegetables and Fruits', name: 'Whole Fruits' });
    if (fields.useCases.length) useCaseSlot.push({ text: fields.useCases[0], name: 'Use Case' });
    if (fields.features.includes('High Juice Yield')) sellingPointSlot.push({ text: 'High Juice Yield', name: 'High Juice Yield' });
    if (fields.features.includes('Compact')) sellingPointSlot.push({ text: 'Compact', name: 'Compact' });
    if (fields.features.includes('Quiet')) sellingPointSlot.push({ text: 'Quiet Motor', name: 'Quiet' });
    if (fields.color) materialColorSlot.push({ text: fields.color, name: 'Color' });
  } else {
    const wattSpec = fields.numericSpecs.find(s => s.label === 'Wattage');
    if (wattSpec) specSlot.push({ text: wattSpec.normalized, name: 'Wattage' });
    if (fields.capacity) specSlot.push({ text: fields.capacity, name: 'Capacity' });
    for (const f of fields.features.slice(0, 3)) featureSlot.push({ text: f, name: f });
    if (fields.useCases.length) useCaseSlot.push({ text: fields.useCases[0], name: 'Use Case' });
    for (const c of fields.certifications) sellingPointSlot.push({ text: c, name: c });
    if (fields.color) materialColorSlot.push({ text: fields.color, name: 'Color' });
  }

  function clean(s) {
    return s.replace(/&/g, 'and').replace(/[,;]+/g, '').replace(/\s+/g, ' ').trim();
  }

  function assembleByVersion(version) {
    const parts = [];
    if (brandSlot.text) parts.push(brandSlot.text);
    for (const f of coreTypeSlot) parts.push(f.text);
    for (const f of specSlot) parts.push(f.text);
    for (const f of featureSlot) parts.push(f.text);
    if (version === 'seo') { for (const f of useCaseSlot) parts.push(f.text); }
    else if (useCaseSlot.length) parts.push(useCaseSlot[0].text);
    if (version === 'seo') { for (const f of sellingPointSlot) parts.push(f.text); }
    else if (version === 'bal') { for (let i = 0; i < Math.min(2, sellingPointSlot.length); i++) parts.push(sellingPointSlot[i].text); }
    else { for (let i = 0; i < Math.min(1, sellingPointSlot.length); i++) parts.push(sellingPointSlot[i].text); }
    for (const f of materialColorSlot) parts.push(f.text);

    let result = clean(parts.join(' '));
    const maxLen = version === 'seo' ? 200 : version === 'bal' ? 180 : 165;
    if (result.length > maxLen) {
      for (const f of [...materialColorSlot].reverse()) {
        if (result.length <= maxLen) break;
        const fClean = clean(f.text);
        const idx = result.lastIndexOf(fClean);
        if (idx > -1) result = clean(result.slice(0, idx) + result.slice(idx + fClean.length));
      }
      for (const f of [...sellingPointSlot].reverse()) {
        if (result.length <= maxLen) break;
        const fClean = clean(f.text);
        const idx = result.lastIndexOf(fClean);
        if (idx > -1) result = clean(result.slice(0, idx) + result.slice(idx + fClean.length));
      }
      for (const f of [...useCaseSlot].reverse()) {
        if (result.length <= maxLen) break;
        const fClean = clean(f.text);
        const idx = result.lastIndexOf(fClean);
        if (idx > -1) result = clean(result.slice(0, idx) + result.slice(idx + fClean.length));
      }
    }
    return result;
  }

  let seoTitle = assembleByVersion('seo');
  let readTitle = assembleByVersion('read');
  let balTitle = assembleByVersion('bal');

  function explainChanges(original, optimized) {
    const changes = [];
    const origLower = original.toLowerCase();
    if (fields.brand && origLower.startsWith(fields.brand.toLowerCase())) {
      changes.push(`品牌名"${fields.brand}"保留在标题首位`);
    } else if (fields.brand) {
      changes.push(`品牌名"${fields.brand}"移至标题首位`);
    }
    if (original.includes('&') && !optimized.includes('&')) changes.push('将 & 替换为 and');
    if (/[\d.]+%/.test(original) && !/[\d.]+%/.test(optimized)) changes.push('将百分号替换为 Percent');
    if (/,/.test(original) && !/,/.test(optimized)) changes.push('移除逗号，改为空格连接');
    if (/\(/.test(original) && !/\(/.test(optimized)) changes.push('移除括号，颜色自然融入标题尾部');

    const origCounts = {};
    origLower.split(/\s+/).forEach(w => { if (w.length > 3) origCounts[w] = (origCounts[w] || 0) + 1; });
    const optCounts = {};
    optimized.toLowerCase().split(/\s+/).forEach(w => { if (w.length > 3) optCounts[w] = (optCounts[w] || 0) + 1; });
    const reduced = Object.entries(origCounts).filter(([w, c]) => c > 2 && (optCounts[w] || 0) < c);
    if (reduced.length) changes.push(`去重: ${reduced.map(([w, c]) => `"${w}"(${c}次→${optCounts[w] || 1}次)`).join('、')}`);

    if (changes.length === 0) changes.push('标题结构已优化，保持核心信息完整');
    return changes;
  }

  function checkQuality(title, version) {
    const c = {};
    c.charCount = title.length;
    c.brandFirst = fields.brand ? title.toLowerCase().startsWith(fields.brand.toLowerCase()) : true;
    const targets = { seo: { min: 160, max: 190 }, read: { min: 110, max: 160 }, bal: { min: 140, max: 175 } };
    const t = targets[version] || targets.bal;
    c.coveredKeywords = [];
    const allSlots = [brandSlot, ...coreTypeSlot, ...specSlot, ...featureSlot, ...useCaseSlot, ...sellingPointSlot, ...materialColorSlot];
    for (const f of allSlots) {
      if (!f.text) continue;
      const checkWord = f.text.split(' ')[0].toLowerCase();
      if (title.toLowerCase().includes(checkWord)) c.coveredKeywords.push(f.name);
    }
    c.paramIntegrity = true;
    c.alteredParams = [];
    for (const spec of fields.numericSpecs) {
      const numVal = spec.value.replace(/,/g, '');
      if (!title.includes(numVal)) { c.paramIntegrity = false; c.alteredParams.push(spec.raw + ' → missing'); }
    }
    c.trimmedFields = [];
    for (const f of [...sellingPointSlot, ...materialColorSlot, ...useCaseSlot]) {
      if (!f.text) continue;
      const checkWord = f.text.split(' ')[0].toLowerCase();
      if (!title.toLowerCase().includes(checkWord)) c.trimmedFields.push(f.name);
    }
    c.hasSpecialChars = /["""\u201c\u201d\u2033&%]/.test(title);
    const wc = {};
    title.toLowerCase().split(/\s+/).forEach(w => { const wl = w.replace(/[.,;:]/g, ''); if (wl.length > 3) wc[wl] = (wc[wl] || 0) + 1; });
    c.repeatedWords = Object.entries(wc).filter(([, v]) => v > 2).map(([w]) => w);
    c.parameterClaims = [];
    for (const spec of fields.numericSpecs) {
      if (title.includes(spec.value.replace(/,/g, ''))) c.parameterClaims.push(spec.label + ': ' + spec.normalized);
    }
    c.tooShort = title.length < 100;
    c.belowTarget = title.length < t.min;

    let score = 10;
    if (c.charCount < 80) score -= 5;
    else if (c.charCount < 100) score -= 3;
    else if (c.charCount < t.min) score -= 1;
    else if (c.charCount > t.max) score -= 1;
    if (!c.brandFirst) score -= 1;
    if (c.trimmedFields.length > 2) score -= 1;
    if (!c.paramIntegrity) score -= 4;
    if (c.hasSpecialChars) score -= 1;
    if (c.repeatedWords.length > 0) score -= 1;
    score = Math.max(0, Math.min(10, score));
    if (!c.paramIntegrity) c.qualityGrade = 'Poor';
    else if (score >= 9) c.qualityGrade = 'Optimized';
    else if (score >= 7) c.qualityGrade = 'Great';
    else if (score >= 5) c.qualityGrade = 'Good';
    else c.qualityGrade = 'Fair';
    return c;
  }

  const seoChecks = checkQuality(seoTitle, 'seo');
  const readChecks = checkQuality(readTitle, 'read');
  const balChecks = checkQuality(balTitle, 'bal');

  function buildWarnings(checks) {
    const w = [];
    if (checks.tooShort) w.push({ type: 'yellow', text: '标题偏短，建议补充核心功能参数或使用场景。' });
    if (!checks.paramIntegrity) w.push({ type: 'red', text: `参数被篡改: ${checks.alteredParams.join('；')}，原始数值必须保留。` });
    if (checks.hasSpecialChars) w.push({ type: 'yellow', text: '标题包含特殊字符，建议替换为标准格式。' });
    if (checks.repeatedWords.length > 0) w.push({ type: 'yellow', text: `标题存在重复关键词: ${checks.repeatedWords.join('、')}，建议合并。` });
    if (checks.parameterClaims.length > 0) w.push({ type: 'info', text: `${checks.parameterClaims.join('、')}属于参数型声明，请确保与后台属性和说明书一致。` });
    if (checks.trimmedFields.length > 0) w.push({ type: 'info', text: `因长度限制未包含: ${checks.trimmedFields.join('、')}，如需完整覆盖建议使用SEO优先版。` });
    return w;
  }

  return [
    { label: 'SEO优先版', desc: '关键词覆盖最大化，适合新品、广告投放', title: seoTitle, charCount: seoTitle.length, qualityGrade: seoChecks.qualityGrade, coveredKeywords: seoChecks.coveredKeywords, trimmedFields: seoChecks.trimmedFields, paramIntegrity: seoChecks.paramIntegrity, changes: explainChanges(originalTitle, seoTitle), warnings: buildWarnings(seoChecks) },
    { label: '可读性优先版', desc: '自然流畅，保留核心功能', title: readTitle, charCount: readTitle.length, qualityGrade: readChecks.qualityGrade, coveredKeywords: readChecks.coveredKeywords, trimmedFields: readChecks.trimmedFields, paramIntegrity: readChecks.paramIntegrity, changes: explainChanges(originalTitle, readTitle), warnings: buildWarnings(readChecks) },
    { label: '平衡版', desc: '兼顾SEO、CDQ合规和用户阅读，推荐默认使用', title: balTitle, charCount: balTitle.length, qualityGrade: balChecks.qualityGrade, coveredKeywords: balChecks.coveredKeywords, trimmedFields: balChecks.trimmedFields, paramIntegrity: balChecks.paramIntegrity, changes: explainChanges(originalTitle, balTitle), warnings: buildWarnings(balChecks) },
  ];
}

// ========== BULLET REWRITING ENGINE ==========
function rewriteBullets(bullets, titleLower, specs) {
  if (!bullets || bullets.length === 0 || bullets[0] === 'Failed to extract bullets') return [];

  const rewrites = [];
  const brandFluffWords = ['promise', 'mission', 'committed', 'deserve', 'superior quality', 'we offer', 'our mission'];

  for (let i = 0; i < bullets.length; i++) {
    const original = bullets[i];
    const origLower = original.toLowerCase();
    let rewritten = original;
    let changes = [];

    if (i === bullets.length - 1 && brandFluffWords.some(w => origLower.includes(w))) {
      if (origLower.includes('brush') || origLower.includes('cup') || origLower.includes('manual')) {
        rewritten = 'COMPLETE ACCESSORIES & EASY CLEANUP: Includes all accessories. Detachable parts rinse clean in under 60 seconds.';
      } else if (origLower.includes('warranty') || origLower.includes('support') || origLower.includes('service')) {
        rewritten = 'RELIABLE SUPPORT & WARRANTY: Backed by dedicated customer service and manufacturer warranty.';
      } else {
        rewritten = 'WHAT YOU GET: Complete product with all accessories and user manual. Ready to use right out of the box.';
      }
      changes.push({ type: 'content', desc: '移除品牌套话，替换为决策推动信息' });
      changes.push({ type: 'structure', desc: '开头改为利益导向大写关键词' });
    }

    if (changes.length === 0) {
      const colonIdx = original.indexOf(':');
      if (colonIdx < 0 || colonIdx > 30) {
        const benefitStarters = { 'large': 'SAVE PREP TIME', 'easy': 'EFFORTLESS CLEANUP', 'simple': 'QUICK ASSEMBLY', 'slow': 'MAXIMUM NUTRITION', 'one-button': 'ONE-TOUCH OPERATION', 'powerful': 'POWERFUL PERFORMANCE', 'superior': 'COMPLETE PACKAGE', 'bpa': 'SAFE & HEALTHY', 'fast cooling': 'RAPID COOLING', 'portable': 'ULTRA PORTABLE', 'quiet': 'WHISPER QUIET', 'dual power': 'DUAL POWER READY' };
        for (const [keyword, header] of Object.entries(benefitStarters)) {
          if (origLower.includes(keyword)) {
            rewritten = `${header}: ${original.trim()}`;
            changes.push({ type: 'structure', desc: '添加利益导向大写标题，提升扫读转化' });
            break;
          }
        }
      }
    }

    if (/[\d.]+%/.test(rewritten)) {
      rewritten = rewritten.replace(/(\d+\.?\d*)%/g, '$1 Percent');
      changes.push({ type: 'compliance', desc: '百分号替换为Percent' });
    }

    if (titleLower.includes('bpa') && i === 0 && !origLower.includes('bpa')) {
      rewritten = `BPA-FREE & SAFE: ${rewritten}`;
      changes.push({ type: 'keyword', desc: '标题提及BPA-Free但五点未展开' });
    }

    const dimensions = changes.map(c => {
      if (c.type === 'structure') return '可读性';
      if (c.type === 'content') return '卖点证据';
      if (c.type === 'keyword') return '关键词密度';
      if (c.type === 'compliance') return '合规性';
      return '场景代入';
    });

    rewrites.push({
      index: i + 1,
      before: original,
      after: rewritten,
      changes: changes.map((c, ci) => `${c.desc} [↑${dimensions[ci]}]`),
      hasChange: changes.length > 0,
    });
  }

  return rewrites;
}

// ========== MAIN HANDLER ==========
export default async function handler(req) {
  try {
    if (req.method === 'OPTIONS') {
      return new Response(null, {
        status: 200,
        headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, OPTIONS' },
      });
    }

    const u = new URL(req.url);
    const asin = (u.searchParams.get('asin') || '').trim().toUpperCase();

    if (!asin || !/^[A-Z0-9]{10}$/.test(asin)) {
      return jsonRes({ error: 'Please enter a valid 10-character ASIN' }, 400);
    }

    const data = await fetchAmazonData(asin);

    if (data.error) {
      return jsonRes(data);
    }

    const audit = auditListing(data);
    const completeness = assessCompleteness(data);

    return jsonRes({ ...data, audit, completeness });

  } catch (err) {
    return jsonRes({ error: `Server error: ${err.message}` }, 500);
  }
}
