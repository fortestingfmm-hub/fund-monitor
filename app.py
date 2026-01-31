import streamlit as st
import akshare as ak
import pandas as pd
import plotly.express as px
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 页面配置 ---
st.set_page_config(page_title="极速基金估值", page_icon="⚡", layout="wide")
st.title("⚡ 基金实时估值 (轻量稳定版)")
st.caption("多线程并发 | 纯CSS渲染 | 彻底修复ImportError")

# --- 核心功能 1: 获取全市场行情 (带缓存) ---
@st.cache_data(ttl=60)
def get_market_data():
    market_map = {}
    # 1. A股
    for i in range(3):
        try:
            df_a = ak.stock_zh_a_spot_em()
            for _, row in df_a.iterrows():
                try:
                    code = str(row['代码'])
                    val = row['涨跌幅']
                    market_map[code] = float(val) if val is not None else 0.0
                except: continue
            break 
        except: time.sleep(1)
    
    # 2. 港股
    for i in range(3):
        try:
            df_hk = ak.stock_hk_spot_em()
            for _, row in df_hk.iterrows():
                try:
                    code = str(row['代码']) 
                    val = row['涨跌幅']
                    market_map[code] = float(val) if val is not None else 0.0
                except: continue
            break
        except: time.sleep(1)
    return market_map

# --- 核心功能 2: 计算单个基金 ---
def calculate_single_fund(fund_code, market_map):
    # 内部函数：安全的获取数据
    def try_fetch(source, specific_year=None):
        try:
            if specific_year:
                return ak.fund_portfolio_hold_em(symbol=fund_code, date=str(specific_year))
            else:
                if source == 'em': return ak.fund_portfolio_hold_em(symbol=fund_code)
                if source == 'cninfo': 
                    if hasattr(ak, 'fund_portfolio_hold_cninfo'):
                        return ak.fund_portfolio_hold_cninfo(symbol=fund_code)
                    else: return pd.DataFrame()
        except: return pd.DataFrame()

    # 1. 获取数据
    portfolio = try_fetch('em') 
    if portfolio.empty: portfolio = try_fetch('em', specific_year=2025)
    if portfolio.empty: portfolio = try_fetch('em', specific_year=2024)
    if portfolio.empty: portfolio = try_fetch('cninfo')

    if portfolio.empty:
        return {
            "代码": fund_code, "名称": "获取失败", "估值": 0.0, 
            "状态": "❌ 无数据", "港股含量": 0, "明细": None
        }

    # 2. 解析数据
    try:
        fund_name = f"基金{fund_code}"
        if '基金名称' in portfolio.columns and not portfolio.empty:
            fund_name = portfolio.iloc[0]['基金名称']

        cols = portfolio.columns.tolist()
        holdings = pd.DataFrame()

        if '季度' in cols:
            portfolio = portfolio.sort_values(by='季度', ascending=False)
            holdings = portfolio[portfolio['季度'] == portfolio.iloc[0]['季度']]
        elif '截止报告期' in cols:
            portfolio = portfolio.sort_values(by='截止报告期', ascending=False)
            holdings = portfolio[portfolio['截止报告期'] == portfolio.iloc[0]['截止报告期']]
        elif '年份' in cols:
            holdings = portfolio[portfolio['年份'] == portfolio['年份'].max()]
        else:
            holdings = portfolio.head(10)

        holdings = holdings.head(10)
        
        # 3. 计算估值
        total_contribution = 0
        hk_count = 0
        details_list = []
        
        for _, row in holdings.iterrows():
            s_code = str(row.get('股票代码', row.get('代码', '')))
            s_name = row.get('股票名称', row.get('简称', '未知'))
            try: weight = float(row.get('占净值比例', row.get('市值占净值比', 0)))
            except: weight = 0.0
            
            if len(s_code) == 5: hk_count += 1
            
            change = 0.0
            found = False
            keys = [s_code, "0"+s_code, s_code.split('.')[0]]
            for k in keys:
                if k in market_map:
                    change = market_map[k]
                    found = True
                    break
            
            contribution = change * (weight / 100)
            total_contribution += contribution
            
            details_list.append({
                "股票代码": s_code,
                "股票名称": s_name,
                "市场": "🇭🇰" if len(s_code)==5 else "🇨🇳",
                "权重": weight,
                "今日涨跌%": change if found else 0.0,
                "贡献度": contribution
            })
            
        status = f"🇭🇰 港股({hk_count})" if hk_count > 0 else "🇨🇳 A股"

        return {
            "代码": fund_code,
            "名称": fund_name,
            "估值": round(total_contribution, 2),
            "状态": status,
            "港股含量": hk_count,
            "明细": pd.DataFrame(details_list)
        }

    except:
        return {
            "代码": fund_code, "名称": "解析错", "估值": 0.0, 
            "状态": "⚠️ 异常", "港股含量": 0, "明细": None
        }

# --- 界面 UI ---

with st.sidebar:
    st.header("⚡ 控制台")
    default_text = "005827\n161226\n110011\n000001"
    codes_input = st.text_area("基金代码池", value=default_text, height=150)
    fund_codes = [line.strip() for line in codes_input.split('\n') if line.strip()]
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        refresh = st.button("🚀 极速刷新", type="primary", use_container_width=True)
    with col_btn2:
        force_refresh = st.button("🔄 强制重连", use_container_width=True)
        
    if force_refresh:
        st.cache_data.clear()
        st.toast("缓存已清空", icon="🧹")

# --- 样式函数 (纯Python实现，不依赖matplotlib) ---
def style_negative_positive(val):
    """
    手动实现背景色：
    涨(>0) -> 浅红背景
    跌(<0) -> 浅绿背景
    """
    if not isinstance(val, (int, float)): return ''
    if val > 0:
        return 'background-color: #ffcdd2; color: black' # 浅红
    elif val < 0:
        return 'background-color: #c8e6c9; color: black' # 浅绿
    return ''

def style_text_color(val):
    """文字颜色：红涨绿跌"""
    if not isinstance(val, (int, float)): return ''
    color = '#d32f2f' if val > 0 else '#2e7d32' if val < 0 else 'black'
    return f'color: {color}; font-weight: bold'


# --- 主逻辑 ---
if refresh or force_refresh or 'data_cache' not in st.session_state:
    if not fund_codes:
        st.warning("请在左侧添加代码")
    else:
        progress = st.progress(0)
        status = st.empty()
        
        with st.spinner("正在拉取全市场数据..."):
            market_map = get_market_data()
        
        results = []
        status.text("🚀 正在多线程并发计算...")
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_code = {executor.submit(calculate_single_fund, code, market_map): code for code in fund_codes}
            for i, future in enumerate(as_completed(future_to_code)):
                res = future.result()
                results.append(res)
                progress.progress((i + 1) / len(fund_codes))
        
        # 重新排序
        final_results = []
        res_dict = {r['代码']: r for r in results}
        for code in fund_codes:
            if code in res_dict:
                final_results.append(res_dict[code])
        
        status.empty()
        progress.empty()
        st.session_state['data_cache'] = final_results

# --- 结果展示 ---
if 'data_cache' in st.session_state:
    results = st.session_state['data_cache']
    df_res = pd.DataFrame(results)
    
    st.subheader("⚡ 极速估值表")
    
    # 应用文字颜色样式
    st.dataframe(
        df_res[['代码', '名称', '估值', '状态']].style.applymap(style_text_color, subset=['估值'])
                    .format({"估值": "{:+.2f}%"}),
        use_container_width=True,
        hide_index=True
    )
    
    st.divider()

    st.subheader("🔍 持仓透视")
    selected_fund_name = st.selectbox(
        "选择基金查看详情：", 
        options=[f"{r['代码']} - {r['名称']}" for r in results]
    )
    
    selected_code = selected_fund_name.split(' - ')[0]
    target_data = next((item for item in results if item["代码"] == selected_code), None)
    
    if target_data and target_data['明细'] is not None:
        c1, c2, c3 = st.columns(3)
        c1.metric("名称", target_data['名称'])
        c2.metric("估值", f"{target_data['估值']:.2f}%", delta_color="normal")
        c3.metric("港股", f"{target_data['港股含量']} 只")
        
        # ⚠️ 关键修改：这里不再用 background_gradient，改用自定义的 style_negative_positive
        # 这样就完全移除了对 matplotlib 的依赖
        st.dataframe(
            target_data['明细'].style
                .applymap(style_negative_positive, subset=['今日涨跌%']) # 使用背景色
                .applymap(style_text_color, subset=['贡献度']) # 使用文字色
                .format({
                    "权重": "{:.2f}%", "今日涨跌%": "{:.2f}%", "贡献度": "{:.4f}%"
                }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("暂无持仓明细")
else:
    st.info("👈 点击左侧刷新")
