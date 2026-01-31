import streamlit as st
import akshare as ak
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 页面配置 ---
st.set_page_config(page_title="基金估值(暴力版)", page_icon="🔥", layout="wide")
st.title("🔥 基金实时估值 (暴力强开版)")
st.caption("内置名称库 | 年份地毯式搜索 | 实时调试日志")

# ==========================================
# 0. 内置名称字典 (兜底用，防止接口挂了显示代码)
# ==========================================
MANUAL_NAMES = {
    "005827": "易方达蓝筹精选混合",
    "161226": "建信优选成长混合(LOF)",
    "110011": "易方达中小盘混合",
    "000001": "华夏成长混合",
    "510300": "华泰柏瑞沪深300ETF",
    "510500": "南方中证500ETF"
}

# ==========================================
# 1. 核心功能: 暴力获取持仓 & 名称
# ==========================================
@st.cache_data(persist="disk", show_spinner=False)
def get_all_fund_holdings(fund_codes_list):
    """
    批量获取基金持仓，并缓存到硬盘。
    """
    logs = [] # 用于记录日志

    # --- 内部函数：获取真实名称 ---
    def get_real_name(code):
        # 1. 先查内置字典 (最快，100%成功)
        if code in MANUAL_NAMES:
            return MANUAL_NAMES[code]
        
        # 2. 查不到再去联网
        try:
            df_info = ak.fund_individual_basic_info_em(symbol=code)
            # 尝试匹配 "基金简称" 或 "基金全称"
            for key in ["基金简称", "基金全称", "基金名称"]:
                rows = df_info[df_info.iloc[:, 0] == key]
                if not rows.empty:
                    return rows.iloc[0, 1]
            return f"基金{code}"
        except:
            return f"基金{code}"

    # --- 内部函数：获取持仓 (地毯式搜索) ---
    def fetch_one_fund(code):
        log_msg = f"[{code}] 开始..."
        real_name = get_real_name(code)
        
        # 定义要扫描的年份 (从新到旧)
        years_to_try = [2025, 2024, 2023]
        found_df = pd.DataFrame()
        success_year = ""

        # 1. 先尝试不带年份的默认接口 (通常是最新的)
        try:
            df = ak.fund_portfolio_hold_em(symbol=code)
            if not df.empty:
                found_df = df
                success_year = "默认接口"
        except: pass

        # 2. 如果默认没数据，开始遍历年份
        if found_df.empty:
            for year in years_to_try:
                try:
                    # log_msg += f" 试{year}..."
                    df = ak.fund_portfolio_hold_em(symbol=code, date=str(year))
                    if not df.empty:
                        found_df = df
                        success_year = str(year)
                        break # 找到了就停止
                except: pass

        if found_df.empty:
            return {"code": code, "name": real_name, "holdings": [], "log": log_msg + " ❌全失败"}

        # 3. 解析数据
        try:
            df = found_df
            cols = df.columns.tolist()
            
            # 智能排序：如果有季度/截止日期，取最新的
            if '季度' in cols:
                df = df.sort_values(by='季度', ascending=False)
                latest = df.iloc[0]['季度']
                df = df[df['季度'] == latest]
            elif '截止报告期' in cols:
                df = df.sort_values(by='截止报告期', ascending=False)
                latest = df.iloc[0]['截止报告期']
                df = df[df['截止报告期'] == latest]
            elif '年份' in cols:
                df = df.sort_values(by='年份', ascending=False)
                latest = df.iloc[0]['年份']
                df = df[df['年份'] == latest]

            df = df.head(10) # 取前十大
            
            clean_holdings = []
            for _, row in df.iterrows():
                # 极其暴力的列名匹配，防止列名变了
                s_code = str(row.get('股票代码', row.get('代码', row.get('证券代码', ''))))
                s_name = row.get('股票名称', row.get('简称', row.get('证券名称', '未知')))
                
                w_val = row.get('占净值比例', row.get('市值占净值比', row.get('持仓比例', 0)))
                try: w_float = float(w_val)
                except: w_float = 0.0

                if s_code: # 代码不为空才加
                    clean_holdings.append({'c': s_code, 'n': s_name, 'w': w_float})
            
            if not clean_holdings:
                 return {"code": code, "name": real_name, "holdings": [], "log": log_msg + f" ✅{success_year}有表但解析为空"}

            return {"code": code, "name": real_name, "holdings": clean_holdings, "log": log_msg + f" ✅{success_year}成功"}

        except Exception as e:
            return {"code": code, "name": real_name, "holdings": [], "log": log_msg + f" ⚠️解析错:{e}"}

    # 多线程并发
    results = {}
    logs_output = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(fetch_one_fund, code): code for code in fund_codes_list}
        for future in as_completed(future_map):
            res = future.result()
            results[res['code']] = res
            logs_output.append(res['log'])
    
    return results, logs_output

# ==========================================
# 2. 核心功能: 市场行情 (极速并发)
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
# 3. 计算逻辑
# ==========================================
def calculate_valuation(fund_codes, holdings_data, market_map):
    final_list = []
    
    for code in fund_codes:
        data = holdings_data.get(code)
        
        # 如果完全没抓到
        if not data or not data['holdings']:
            # 尝试用内置名称兜底
            fallback_name = MANUAL_NAMES.get(code, f"基金{code}")
            final_list.append({
                "代码": code, "名称": data.get('name', fallback_name) if data else fallback_name,
                "估值": 0.0, "状态": "❌ 无数据", "港股含量": 0, "明细": pd.DataFrame()
            })
            continue

        total_val = 0.0
        hk_cnt = 0
        details = []

        for item in data['holdings']:
            s_code = item['c']
            weight = item['w']
            
            # 判断港股 (5位代码)
            is_hk = len(s_code) == 5
            if is_hk: hk_cnt += 1
            
            change = 0.0
            found = False
            
            # 匹配策略
            keys = [s_code, "0"+s_code, s_code.split('.')[0]]
            for k in keys:
                if k in market_map:
                    change = market_map[k]
                    found = True
                    break
            
            # 港股额外匹配逻辑
            if not found and is_hk and s_code in market_map:
                 change = market_map[s_code]
                 found = True
            
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
            "名称": data['name'],
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
    default_text = "005827\n161226\n110011"
    codes_input = st.text_area("代码池", value=default_text, height=150)
    fund_codes = [line.strip() for line in codes_input.split('\n') if line.strip()]
    
    col1, col2 = st.columns(2)
    with col1:
        refresh_price = st.button("🚀 仅刷新股价", type="primary", use_container_width=True)
    with col2:
        update_holdings = st.button("📂 更新持仓/名称", use_container_width=True)
    
    if update_holdings:
        get_all_fund_holdings.clear() # 清空缓存
        st.toast("已清除缓存，开始重新挖掘数据...", icon="🕵️")

# 主逻辑
if refresh_price or update_holdings or 'last_result' not in st.session_state:
    if not fund_codes:
        st.warning("请在左侧输入代码")
    else:
        # 1. 获取持仓 (带日志返回)
        with st.spinner("📦 正在挖掘持仓数据 (年份地毯式搜索)..."):
            holdings_data, logs = get_all_fund_holdings(fund_codes)
            
        # 在侧边栏显示日志 (调试神器)
        with st.sidebar.status("🕵️ 数据抓取日志", expanded=True):
            for log in logs:
                st.write(log)
        
        # 2. 获取行情
        with st.spinner("📈 正在拉取实时行情..."):
            market_map = get_market_data_fast()
            
        # 3. 计算
        results = calculate_valuation(fund_codes, holdings_data, market_map)
        st.session_state['last_result'] = results

# 展示逻辑
if 'last_result' in st.session_state:
    results = st.session_state['last_result']
    df_res = pd.DataFrame(results)
    
    st.subheader("🔥 估值看板")
    st.dataframe(
        df_res[['代码', '名称', '估值', '状态']].style.applymap(style_text_color, subset=['估值'])
                    .format({"估值": "{:+.2f}%"}),
        use_container_width=True, hide_index=True
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
        st.info("该基金暂无持仓明细，请检查左下角的日志看是否抓取成功。")
