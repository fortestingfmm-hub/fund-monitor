import streamlit as st
import akshare as ak
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 页面配置 ---
st.set_page_config(page_title="基金实时估值", page_icon="📈", layout="wide")
st.title("📈 基金实时估值看板")
st.caption("真实名称 | 持仓本地缓存 | 股价实时刷新")

# ==========================================
# 核心优化 1: 持仓数据 + 真实名称 (存硬盘)
# ==========================================
@st.cache_data(persist="disk", show_spinner=False)
def get_all_fund_holdings(fund_codes_list):
    """
    批量获取基金持仓 & 真实名称，并缓存到硬盘。
    """
    
    # --- 内部函数：获取真实名称 ---
    def get_real_name(code):
        try:
            # 使用“基金基本信息”接口查名字，这个最准
            df_info = ak.fund_individual_basic_info_em(symbol=code)
            # 接口返回的是竖表，列名是 item 和 value
            # 我们找 item 等于 "基金简称" 的那一行
            name_row = df_info[df_info['item'] == "基金简称"]
            if not name_row.empty:
                return name_row.iloc[0]['value']
            else:
                return f"基金{code}" # 实在找不到的兜底
        except:
            return f"基金{code}"

    # --- 内部函数：获取持仓 ---
    def fetch_one_fund(code):
        # 1. 先去查名字 (专门查一次，确保显示真名)
        real_name = get_real_name(code)
        
        # 2. 再去查持仓
        def try_fetch(source, specific_year=None):
            try:
                if specific_year:
                    return ak.fund_portfolio_hold_em(symbol=code, date=str(specific_year))
                else:
                    if source == 'em': return ak.fund_portfolio_hold_em(symbol=code)
                    if source == 'cninfo': 
                        if hasattr(ak, 'fund_portfolio_hold_cninfo'):
                            return ak.fund_portfolio_hold_cninfo(symbol=code)
            except: return pd.DataFrame()
            return pd.DataFrame()

        # 梯队式抓取持仓
        df = try_fetch('em')
        if df.empty: df = try_fetch('em', specific_year=2025)
        if df.empty: df = try_fetch('em', specific_year=2024)
        if df.empty: df = try_fetch('cninfo')
        
        if df.empty: return None

        # 解析持仓
        try:
            cols = df.columns.tolist()
            if '季度' in cols:
                df = df.sort_values(by='季度', ascending=False)
                df = df[df['季度'] == df.iloc[0]['季度']]
            elif '截止报告期' in cols:
                df = df.sort_values(by='截止报告期', ascending=False)
                df = df[df['截止报告期'] == df.iloc[0]['截止报告期']]
            elif '年份' in cols:
                df = df[df['年份'] == df['年份'].max()]
            
            df = df.head(10) # 前十大
            
            clean_holdings = []
            for _, row in df.iterrows():
                clean_holdings.append({
                    'c': str(row.get('股票代码', row.get('代码', ''))),
                    'n': row.get('股票名称', row.get('简称', '未知')),
                    'w': float(row.get('占净值比例', row.get('市值占净值比', 0)))
                })
            
            return {"name": real_name, "holdings": clean_holdings}
        except:
            return None

    # 多线程并发
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(fetch_one_fund, code): code for code in fund_codes_list}
        for future in as_completed(future_map):
            code = future_map[future]
            res = future.result()
            if res:
                results[code] = res
            else:
                results[code] = {"name": f"基金{code}(无数据)", "holdings": []}
    
    return results

# ==========================================
# 核心优化 2: 市场行情 (A股港股同时跑)
# ==========================================
@st.cache_data(ttl=30, show_spinner=False)
def get_market_data_fast():
    market_map = {}
    def get_a():
        try:
            df = ak.stock_zh_a_spot_em()
            return {str(row['代码']): float(row['涨跌幅']) for _, row in df.iterrows() if row['涨跌幅'] is not None}
        except: return {}
    def get_hk():
        try:
            df = ak.stock_hk_spot_em()
            return {str(row['代码']): float(row['涨跌幅']) for _, row in df.iterrows() if row['涨跌幅'] is not None}
        except: return {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        fa = executor.submit(get_a)
        fh = executor.submit(get_hk)
        market_map.update(fa.result())
        market_map.update(fh.result())
    return market_map

# ==========================================
# 核心优化 3: 纯计算
# ==========================================
def calculate_valuation(fund_codes, holdings_data, market_map):
    final_list = []
    
    for code in fund_codes:
        data = holdings_data.get(code)
        # 如果缓存里没数据，或者持仓为空
        if not data or not data['holdings']:
            final_list.append({
                "代码": code, 
                "名称": data.get('name', f"基金{code}") if data else f"基金{code}",
                "估值": 0.0, "状态": "❌ 无数据", "港股含量": 0, "明细": pd.DataFrame()
            })
            continue

        total_val = 0.0
        hk_cnt = 0
        details = []

        for item in data['holdings']:
            s_code = item['c']
            weight = item['w']
            if len(s_code) == 5: hk_cnt += 1
            
            change = 0.0
            keys = [s_code, "0"+s_code, s_code.split('.')[0]]
            found_key = False
            for k in keys:
                if k in market_map:
                    change = market_map[k]
                    found_key = True
                    break
            if not found_key and len(s_code) == 5 and s_code in market_map:
                 change = market_map[s_code]
            
            contrib = change * (weight / 100)
            total_val += contrib
            
            details.append({
                "股票代码": s_code,
                "股票名称": item['n'],
                "权重": weight,
                "今日涨跌%": change,
                "贡献度": contrib
            })

        status = f"🇭🇰 港({hk_cnt})" if hk_cnt > 0 else "🇨🇳 A"
        
        final_list.append({
            "代码": code,
            "名称": data['name'], # 这里直接用缓存里的真名
            "估值": round(total_val, 2),
            "状态": status,
            "港股含量": hk_cnt,
            "明细": pd.DataFrame(details)
        })
        
    return final_list

# --- 样式 ---
def style_text_color(val):
    if not isinstance(val, (int, float)): return ''
    color = '#d32f2f' if val > 0 else '#2e7d32' if val < 0 else 'black'
    return f'color: {color}; font-weight: bold'

def style_bg_color(val):
    if not isinstance(val, (int, float)): return ''
    if val > 0: return 'background-color: #ffcdd2; color: black'
    if val < 0: return 'background-color: #c8e6c9; color: black'
    return ''

# --- 界面 UI ---
with st.sidebar:
    st.header("⚡ 控制台")
    default_text = "005827\n161226\n110011\n000001\n510300"
    codes_input = st.text_area("代码池", value=default_text, height=150)
    fund_codes = [line.strip() for line in codes_input.split('\n') if line.strip()]
    
    refresh_price = st.button("🚀 仅刷新股价 (极速)", type="primary", use_container_width=True)
    update_holdings = st.button("📂 更新持仓 & 名称", help="获取最新持仓和基金名字", use_container_width=True)
    
    if update_holdings:
        get_all_fund_holdings.clear()
        st.toast("已清除缓存，正在重新抓取名称和持仓...", icon="📂")

if refresh_price or update_holdings or 'last_result' not in st.session_state:
    if not fund_codes:
        st.warning("请在左侧输入代码")
    else:
        # 1. 获取持仓+名字 (带缓存)
        with st.spinner("📦 正在核对基金档案..."):
            holdings_data = get_all_fund_holdings(fund_codes)
        
        # 2. 获取行情
        with st.spinner("📈 正在拉取实时行情..."):
            market_map = get_market_data_fast()
            
        # 3. 计算
        results = calculate_valuation(fund_codes, holdings_data, market_map)
        st.session_state['last_result'] = results

if 'last_result' in st.session_state:
    results = st.session_state['last_result']
    df_res = pd.DataFrame(results)
    
    st.subheader("⚡ 估值看板")
    # 显示结果
    st.dataframe(
        df_res[['代码', '名称', '估值', '状态']].style.applymap(style_text_color, subset=['估值'])
                    .format({"估值": "{:+.2f}%"}),
        use_container_width=True,
        hide_index=True
    )
    
    st.divider()
    
    st.subheader("🔍 持仓透视")
    names = [f"{r['代码']} - {r['名称']}" for r in results]
    sel = st.selectbox("选择基金：", names)
    target = next((r for r in results if r['代码'] == sel.split(' - ')[0]), None)
    
    if target and not target['明细'].empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("名称", target['名称'])
        c2.metric("估值", f"{target['估值']:.2f}%")
        c3.metric("港股", f"{target['港股含量']}")
        
        st.dataframe(
            target['明细'].style
                .applymap(style_bg_color, subset=['今日涨跌%'])
                .applymap(style_text_color, subset=['贡献度'])
                .format({"权重": "{:.2f}%", "今日涨跌%": "{:.2f}%", "贡献度": "{:.4f}%"}),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("无持仓明细，请尝试点击左侧【更新持仓 & 名称】")
