import streamlit as st
import akshare as ak
import pandas as pd
import time

# --- 页面配置 ---
st.set_page_config(page_title="基金估值(稳健版)", page_icon="🐢", layout="wide")
st.title("🐢 基金实时估值 (单线程稳健版)")
st.caption("排队查询 | 防封IP | 专治161226无数据")

# ==========================================
# 0. 内置名称字典 (兜底保障)
# ==========================================
MANUAL_NAMES = {
    "005827": "易方达蓝筹精选混合",
    "161226": "建信优选成长混合(LOF)",
    "110011": "易方达中小盘混合",
    "000001": "华夏成长混合",
    "510300": "华泰柏瑞沪深300ETF"
}

# ==========================================
# 1. 核心功能: 获取持仓 (单线程 + 延时)
# ==========================================
@st.cache_data(persist="disk", show_spinner=False)
def get_all_fund_holdings_sequential(fund_codes_list):
    """
    【降速模式】一个一个查，中间休息，防止被封
    """
    results = {}
    logs = []

    # 定义进度条
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, code in enumerate(fund_codes_list):
        status_text.text(f"🐢 正在慢速挖掘: {code} ({i+1}/{len(fund_codes_list)})...")
        
        # --- 1. 获取名称 ---
        real_name = MANUAL_NAMES.get(code, f"基金{code}")
        try:
            # 尝试联网获取真名
            df_info = ak.fund_individual_basic_info_em(symbol=code)
            for key in ["基金简称", "基金全称"]:
                rows = df_info[df_info.iloc[:, 0] == key]
                if not rows.empty: 
                    real_name = rows.iloc[0, 1]
                    break
        except: pass

        # --- 2. 获取持仓 (特定策略) ---
        found_df = pd.DataFrame()
        success_source = "失败"
        
        # 策略A: 161226 特供 (优先查2024年，因为它更新慢)
        if code == "161226":
            try:
                df = ak.fund_portfolio_hold_em(symbol=code, date="2024")
                if not df.empty:
                    found_df = df
                    success_source = "2024(特供)"
            except: pass

        # 策略B: 正常查询 (默认 -> 2025 -> 2024)
        if found_df.empty:
            try:
                df = ak.fund_portfolio_hold_em(symbol=code)
                if not df.empty:
                    found_df = df
                    success_source = "默认"
            except: pass
        
        if found_df.empty:
            try:
                df = ak.fund_portfolio_hold_em(symbol=code, date="2025")
                if not df.empty:
                    found_df = df
                    success_source = "2025"
            except: pass
            
        if found_df.empty:
            try:
                df = ak.fund_portfolio_hold_em(symbol=code, date="2024")
                if not df.empty:
                    found_df = df
                    success_source = "2024"
            except: pass

        # --- 3. 解析数据 ---
        clean_holdings = []
        if not found_df.empty:
            try:
                df = found_df
                # 排序找最新
                cols = df.columns.tolist()
                if '季度' in cols:
                    df = df.sort_values(by='季度', ascending=False)
                    df = df[df['季度'] == df.iloc[0]['季度']]
                elif '截止报告期' in cols:
                    df = df.sort_values(by='截止报告期', ascending=False)
                    df = df[df['截止报告期'] == df.iloc[0]['截止报告期']]
                elif '年份' in cols:
                    df = df[df['年份'] == df['年份'].max()]

                df = df.head(10)
                
                for _, row in df.iterrows():
                    s_code = str(row.get('股票代码', row.get('代码', '')))
                    s_name = row.get('股票名称', row.get('简称', '未知'))
                    w_val = row.get('占净值比例', row.get('市值占净值比', 0))
                    try: w = float(w_val)
                    except: w = 0.0
                    if s_code:
                        clean_holdings.append({'c': s_code, 'n': s_name, 'w': w})
            except Exception as e:
                logs.append(f"❌ {code} 解析错误: {e}")

        # 记录结果
        results[code] = {
            "code": code,
            "name": real_name,
            "holdings": clean_holdings
        }
        
        if clean_holdings:
            logs.append(f"✅ {code}: 获取成功 ({success_source})")
        else:
            logs.append(f"❌ {code}: 获取失败 (已尝试所有年份)")

        # 更新进度条
        progress_bar.progress((i + 1) / len(fund_codes_list))
        
        # 关键一步：休息 0.5 秒，防止被封 IP
        time.sleep(0.5)

    status_text.empty()
    progress_bar.empty()
    return results, logs

# ==========================================
# 2. 获取行情 (依然可以快一点)
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
        if not data or not data['holdings']:
            # 即使没数据，也尽量显示个名字
            fallback_name = MANUAL_NAMES.get(code, f"基金{code}")
            real_name = data.get('name', fallback_name) if data else fallback_name
            final_list.append({
                "代码": code, "名称": real_name, "估值": 0.0, 
                "状态": "❌ 暂无持仓", "港股含量": 0, "明细": pd.DataFrame()
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
            "代码": code, "名称": data['name'], "估值": round(total, 2),
            "状态": f"🇭🇰 港({hk})" if hk>0 else "🇨🇳 A",
            "港股含量": hk, "明细": pd.DataFrame(details)
        })
    return final_list

# --- 样式 ---
def style_color(val):
    if not isinstance(val, (int, float)): return ''
    c = '#d32f2f' if val > 0 else '#2e7d32' if val < 0 else 'black'
    return f'color: {c}; font-weight: bold'

# --- 界面 ---
with st.sidebar:
    st.header("🐢 控制台")
    codes_input = st.text_area("代码池", value="", placeholder="请输入代码，每行一个\n161226\n005827", height=200)
    fund_codes = [x.strip() for x in codes_input.split('\n') if x.strip()]
    
    c1, c2 = st.columns(2)
    with c1: refresh = st.button("🚀 刷新股价", type="primary", use_container_width=True)
    with c2: update = st.button("📂 更新持仓", help="非常慢，但很稳", use_container_width=True)
    
    if update:
        get_all_fund_holdings_sequential.clear()
        st.toast("缓存已清空", icon="🧹")

if refresh or update or 'res' not in st.session_state:
    if not fund_codes:
        st.info("👈 请在左侧输入代码")
    else:
        # 1. 慢速获取持仓
        with st.spinner("📦 正在排队挖掘持仓 (防封模式)..."):
            holdings, logs = get_all_fund_holdings_sequential(fund_codes)
        
        with st.sidebar.status("📜 抓取日志", expanded=True):
            for l in logs: st.write(l)
            
        # 2. 获取行情
        with st.spinner("📈 拉取行情..."):
            market = get_market_data()
            
        # 3. 计算
        res = calculate(fund_codes, holdings, market)
        st.session_state['res'] = res

if 'res' in st.session_state and fund_codes:
    df = pd.DataFrame(st.session_state['res'])
    st.subheader("🐢 稳健估值表")
    st.dataframe(
        df[['代码', '名称', '估值', '状态']].style.applymap(style_color, subset=['估值'])
        .format({"估值": "{:+.2f}%"}), use_container_width=True, hide_index=True
    )
    
    st.divider()
    
    names = [f"{r['代码']} - {r['名称']}" for r in st.session_state['res']]
    if names:
        sel = st.selectbox("查看详情:", names)
        tgt = next((r for r in st.session_state['res'] if r['代码'] == sel.split(' - ')[0]), None)
        if tgt and not tgt['明细'].empty:
            c1, c2 = st.columns(2)
            c1.metric("名称", tgt['名称'])
            c2.metric("估值", f"{tgt['估值']:.2f}%")
            st.dataframe(tgt['明细'].style.format("{:.2f}%", subset=['权重','今日涨跌%']), use_container_width=True)
        else:
            st.warning("暂无明细数据")
