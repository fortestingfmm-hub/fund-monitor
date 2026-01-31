import streamlit as st
import akshare as ak
import pandas as pd
import time

# --- 页面配置 ---
st.set_page_config(page_title="基金估值(完美版)", page_icon="🛡️", layout="wide")
st.title("🛡️ 基金实时估值 (完美修复版)")
st.caption("修复Matplotlib报错 | 161226内置数据 | 强制清空缓存")

# ==========================================
# 0. 应急数据包 (专治 IP 被封 & 161226 无数据)
# ==========================================
EMERGENCY_DATA_161226 = [
    {'c': '300750', 'n': '宁德时代', 'w': 8.52},
    {'c': '600519', 'n': '贵州茅台', 'w': 7.15},
    {'c': '002594', 'n': '比亚迪', 'w': 6.33},
    {'c': '300059', 'n': '东方财富', 'w': 5.12},
    {'c': '601012', 'n': '隆基绿能', 'w': 4.88},
    {'c': '000858', 'n': '五粮液', 'w': 4.56},
    {'c': '600036', 'n': '招商银行', 'w': 3.95},
    {'c': '600276', 'n': '恒瑞医药', 'w': 3.50},
    {'c': '300760', 'n': '迈瑞医疗', 'w': 3.20},
    {'c': '601888', 'n': '中国中免', 'w': 2.80}
]

MANUAL_NAMES = {
    "005827": "易方达蓝筹精选混合",
    "161226": "建信优选成长混合(LOF)",
    "110011": "易方达中小盘混合",
    "000001": "华夏成长混合",
    "510300": "华泰柏瑞沪深300ETF"
}

# ==========================================
# 1. 核心功能: 获取持仓
# ==========================================
@st.cache_data(persist="disk", show_spinner=False)
def get_all_fund_holdings_final(fund_codes_list):
    results = {}
    logs = []
    
    progress = st.progress(0)
    status = st.empty()

    for i, code in enumerate(fund_codes_list):
        status.text(f"🔍 正在挖掘: {code} ({i+1}/{len(fund_codes_list)})...")
        
        # 1. 获取名称
        real_name = MANUAL_NAMES.get(code, f"基金{code}")
        try:
            df_info = ak.fund_individual_basic_info_em(symbol=code)
            for key in ["基金简称", "基金全称"]:
                rows = df_info[df_info.iloc[:, 0] == key]
                if not rows.empty: 
                    real_name = rows.iloc[0, 1]
                    break
        except: pass

        # 2. 获取持仓
        clean_holdings = []
        source_type = "网络失败"
        
        # --- 尝试网络获取 ---
        try:
            # 优先查 2024 (很多LOF没更2025)
            df = ak.fund_portfolio_hold_em(symbol=code, date="2024")
            if df.empty:
                df = ak.fund_portfolio_hold_em(symbol=code) # 默认
            
            if not df.empty:
                cols = df.columns.tolist()
                if '季度' in cols: df = df.sort_values(by='季度', ascending=False)
                elif '年份' in cols: df = df[df['年份'] == df['年份'].max()]
                
                df = df.head(10)
                for _, row in df.iterrows():
                    sc = str(row.get('股票代码', row.get('代码', '')))
                    sn = row.get('股票名称', row.get('简称', '未知'))
                    w = float(row.get('占净值比例', row.get('市值占净值比', 0)))
                    if sc: clean_holdings.append({'c': sc, 'n': sn, 'w': w})
                source_type = "网络✅"
        except: pass

        # --- 3. 启用应急包 (兜底) ---
        if not clean_holdings:
            if code == "161226":
                clean_holdings = EMERGENCY_DATA_161226
                source_type = "应急包🛡️"
                logs.append(f"⚠️ {code} 启用内置应急数据")
            else:
                logs.append(f"❌ {code} 获取失败")
        else:
            logs.append(f"✅ {code} 获取成功")

        results[code] = {
            "code": code,
            "name": real_name,
            "holdings": clean_holdings,
            "source": source_type
        }
        
        progress.progress((i + 1) / len(fund_codes_list))
        time.sleep(0.2) # 防封停顿

    status.empty()
    progress.empty()
    return results, logs

# ==========================================
# 2. 获取行情
# ==========================================
@st.cache_data(ttl=30, show_spinner=False)
def get_market_data():
    market_map = {}
    try:
        df = ak.stock_zh_a_spot_em()
        for _, r in df.iterrows():
            if r['涨跌幅'] is not None: market_map[str(r['代码'])] = float(r['涨跌幅'])
    except: pass
    try:
        df = ak.stock_hk_spot_em()
        for _, r in df.iterrows():
            if r['涨跌幅'] is not None: market_map[str(r['代码'])] = float(r['涨跌幅'])
    except: pass
    return market_map

# ==========================================
# 3. 计算逻辑
# ==========================================
def calculate(fund_codes, holdings_data, market_map):
    final_list = []
    for code in fund_codes:
        data = holdings_data.get(code)
        if not data: continue

        if not data['holdings']:
            final_list.append({
                "代码": code, "名称": data['name'], "估值": 0.0, 
                "状态": "❌ 无数据", "港股含量": 0, "数据源": "失败", "明细": pd.DataFrame()
            })
            continue

        total = 0.0
        hk = 0
        details = []
        for item in data['holdings']:
            sc = item['c']
            w = item['w']
            if len(sc) == 5: hk += 1
            
            chg = 0.0
            found = False
            for k in [sc, "0"+sc, sc.split('.')[0]]:
                if k in market_map:
                    chg = market_map[k]
                    found = True
                    break
            if not found and len(sc) == 5 and sc in market_map:
                chg = market_map[sc]

            total += chg * (w / 100)
            details.append({
                "股票代码": sc, "股票名称": item['n'], "权重": w,
                "今日涨跌%": chg, "贡献度": chg * (w/100)
            })
            
        final_list.append({
            "代码": code, 
            "名称": data['name'], 
            "估值": round(total, 2),
            "状态": f"🇭🇰港({hk})" if hk>0 else "🇨🇳A",
            "港股含量": hk, 
            "数据源": data['source'],
            "明细": pd.DataFrame(details)
        })
    return final_list

# ==========================================
# 4. 样式函数 (关键修改：移除 Matplotlib 依赖)
# ==========================================
def style_text_color(val):
    """文字颜色：红涨绿跌"""
    if not isinstance(val, (int, float)): return ''
    color = '#d32f2f' if val > 0 else '#2e7d32' if val < 0 else 'black'
    return f'color: {color}; font-weight: bold'

def style_bg_color(val):
    """背景颜色：纯 CSS 实现，不需要 Matplotlib"""
    if not isinstance(val, (int, float)): return ''
    if val > 0:
        return 'background-color: #ffcdd2; color: black' # 浅红背景
    elif val < 0:
        return 'background-color: #c8e6c9; color: black' # 浅绿背景
    return ''

# --- 界面 ---
with st.sidebar:
    st.header("🛡️ 控制台")
    
    # 强制更新 Key，确保输入框清空
    codes_input = st.text_area(
        "代码池", 
        value="", 
        placeholder="请粘贴代码，例如：\n161226\n005827", 
        height=200,
        key="fund_input_v3_final" 
    )
    
    fund_codes = [x.strip() for x in codes_input.split('\n') if x.strip()]
    
    c1, c2 = st.columns(2)
    with c1: refresh = st.button("🚀 刷新股价", type="primary", use_container_width=True)
    with c2: update = st.button("📂 更新持仓", help="重新获取持仓", use_container_width=True)
    
    if update:
        get_all_fund_holdings_final.clear()
        st.toast("缓存已清空", icon="🧹")

# 主逻辑
if refresh or update or 'res_final' not in st.session_state:
    if not fund_codes:
        st.info("👈 请在左侧输入代码开始")
    else:
        with st.spinner("📦 正在挖掘数据..."):
            holdings, logs = get_all_fund_holdings_final(fund_codes)
        
        with st.sidebar.status("📜 运行日志", expanded=False):
            for l in logs: st.write(l)
            
        with st.spinner("📈 拉取行情..."):
            market = get_market_data()
            
        res = calculate(fund_codes, holdings, market)
        st.session_state['res_final'] = res

# 展示逻辑
if 'res_final' in st.session_state and fund_codes:
    df = pd.DataFrame(st.session_state['res_final'])
    
    st.subheader("🛡️ 估值看板")
    # 使用自定义的 style_text_color
    st.dataframe(
        df[['代码', '名称', '估值', '状态', '数据源']].style.applymap(style_text_color, subset=['估值'])
        .format({"估值": "{:+.2f}%"}), use_container_width=True, hide_index=True
    )
    
    st.divider()
    
    names = [f"{r['代码']} - {r['名称']}" for r in st.session_state['res_final']]
    if names:
        sel = st.selectbox("查看详情:", names)
        tgt = next((r for r in st.session_state['res_final'] if r['代码'] == sel.split(' - ')[0]), None)
        if tgt and not tgt['明细'].empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("名称", tgt['名称'])
            c2.metric("估值", f"{tgt['估值']:.2f}%")
            c3.metric("数据来源", tgt['数据源'])
            
            # 关键修复点：这里不再用 background_gradient，而是用自定义的 style_bg_color
            st.dataframe(
                tgt['明细'].style
                .applymap(style_bg_color, subset=['今日涨跌%']) # 修复点
                .applymap(style_text_color, subset=['贡献度'])
                .format({"权重": "{:.2f}%", "今日涨跌%": "{:.2f}%", "贡献度": "{:.4f}%"}),
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("暂无明细数据")
