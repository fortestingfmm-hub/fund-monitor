import streamlit as st
import akshare as ak
import pandas as pd
import plotly.express as px
import time

# --- 页面配置 ---
st.set_page_config(page_title="基金实时估值看板", page_icon="📊", layout="wide")
st.title("📊 基金实时估值看板")
st.caption("批量监控 | 强制刷新 | 持仓透视")

# --- 核心功能 1: 获取全市场行情 (带重试 & 缓存) ---
# 缓存时间设为60秒，避免频繁请求被封
@st.cache_data(ttl=60)
def get_market_data():
    market_map = {}
    
    # 1. A股 (尝试3次)
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
        except:
            time.sleep(1)
    
    # 2. 港股 (尝试3次)
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
        except:
            time.sleep(1)

    return market_map

# --- 核心功能 2: 计算单个基金 (返回 估值 + 持仓明细表) ---
# 注意：这里去掉了缓存，因为我们要允许用户强制刷新
def calculate_single_fund(fund_code, market_map):
    
    # 内部函数：获取原始数据
    def try_fetch(source, specific_year=None):
        try:
            if specific_year:
                return ak.fund_portfolio_hold_em(symbol=fund_code, date=str(specific_year))
            else:
                if source == 'em': return ak.fund_portfolio_hold_em(symbol=fund_code)
                if source == 'cninfo': return ak.fund_portfolio_hold_cninfo(symbol=fund_code)
        except:
            return pd.DataFrame()

    # 1. 获取数据 (自动修复策略)
    portfolio = try_fetch('em')
    if portfolio.empty: portfolio = try_fetch('em', specific_year=2025)
    if portfolio.empty: portfolio = try_fetch('cninfo')
    if portfolio.empty: portfolio = try_fetch('em', specific_year=2024)

    if portfolio.empty:
        return {
            "代码": fund_code, "名称": "获取失败", "估值": 0.0, 
            "状态": "❌ 无数据", "港股含量": 0, "明细": None
        }

    # 2. 解析数据
    try:
        fund_name = portfolio.iloc[0]['基金名称'] if '基金名称' in portfolio.columns else f"基金{fund_code}"
        cols = portfolio.columns.tolist()
        holdings = pd.DataFrame()

        # 智能找最新持仓
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

        holdings = holdings.head(10) # 前十大
        
        # 3. 计算估值 & 生成明细表
        total_contribution = 0
        hk_count = 0
        details_list = [] # 用于存储明细
        
        for _, row in holdings.iterrows():
            s_code = str(row.get('股票代码', row.get('代码', '')))
            s_name = row.get('股票名称', row.get('简称', '未知'))
            try: weight = float(row.get('占净值比例', row.get('市值占净值比', 0)))
            except: weight = 0.0
            
            if len(s_code) == 5: hk_count += 1
            
            # 匹配行情
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
            
            # 添加到明细列表
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
            "明细": pd.DataFrame(details_list) # 把明细表藏在结果里
        }

    except:
        return {
            "代码": fund_code, "名称": "解析错", "估值": 0.0, 
            "状态": "⚠️ 异常", "港股含量": 0, "明细": None
        }

# --- 界面 UI ---

with st.sidebar:
    st.header("📝 控制台")
    default_text = "005827\n161226\n110011"
    codes_input = st.text_area("基金代码池", value=default_text, height=150)
    fund_codes = [line.strip() for line in codes_input.split('\n') if line.strip()]
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        # 普通刷新（利用缓存，速度快）
        refresh = st.button("🚀 刷新", type="primary", use_container_width=True)
    with col_btn2:
        # 强制刷新（清除缓存，重新联网）
        force_refresh = st.button("🔄 强制更新", use_container_width=True)
        
    if force_refresh:
        st.cache_data.clear() # 清空缓存指令
        st.toast("缓存已清空，正在从交易所重新抓取...", icon="🧹")

# 逻辑控制
if refresh or force_refresh or 'data_cache' not in st.session_state:
    if not fund_codes:
        st.warning("请在左侧添加代码")
    else:
        # 1. 进度条
        progress = st.progress(0)
        status = st.empty()
        
        # 2. 获取行情
        with st.spinner("正在连接交易所..."):
            market_map = get_market_data()
        
        # 3. 计算所有基金
        results = []
        for i, code in enumerate(fund_codes):
            status.text(f"正在分析 {code} ...")
            res = calculate_single_fund(code, market_map)
            results.append(res)
            progress.progress((i + 1) / len(fund_codes))
        
        status.empty()
        progress.empty()
        
        # 将结果存入 session_state 以便交互时不会消失
        st.session_state['data_cache'] = results

# --- 展示区域 ---
if 'data_cache' in st.session_state:
    results = st.session_state['data_cache']
    df_res = pd.DataFrame(results)
    
    # 1. 汇总大表
    st.subheader("📋 估值汇总")
    
    def color_val(val):
        c = '#d32f2f' if val > 0 else '#2e7d32' if val < 0 else 'black'
        return f'color: {c}; font-weight: bold'

    st.dataframe(
        df_res[['代码', '名称', '估值', '状态']].style.applymap(color_val, subset=['估值'])
                    .format({"估值": "{:+.2f}%"}),
        use_container_width=True,
        hide_index=True
    )
    
    st.divider()

    # 2. 持仓详情透视 (你想要的功能！)
    st.subheader("🔍 单只基金持仓透视")
    
    # 下拉选择框
    selected_fund_name = st.selectbox(
        "选择要查看详情的基金：", 
        options=[f"{r['代码']} - {r['名称']}" for r in results]
    )
    
    # 找到选中的那个基金的数据
    selected_code = selected_fund_name.split(' - ')[0]
    target_data = next((item for item in results if item["代码"] == selected_code), None)
    
    if target_data and target_data['明细'] is not None:
        detail_df = target_data['明细']
        
        # 展示 3 列布局：基本信息
        c1, c2, c3 = st.columns(3)
        c1.metric("基金名称", target_data['名称'])
        c2.metric("实时估值", f"{target_data['估值']:.2f}%", 
                  delta=f"{target_data['估值']:.2f}%", delta_color="normal")
        c3.metric("港股数量", f"{target_data['港股含量']} 只")
        
        # 展示详细持仓表
        st.write("▼ 前十大重仓股实时表现")
        st.dataframe(
            detail_df.style.format({
                "权重": "{:.2f}%", "今日涨跌%": "{:.2f}%", "贡献度": "{:.4f}%"
            }).background_gradient(subset=['今日涨跌%'], cmap='RdYlGn_r', vmin=-5, vmax=5),
            use_container_width=True,
            hide_index=True
        )
        
        # 刷新当前持仓的按钮（只针对视图）
        if st.button("🔄 仅刷新此持仓明细"):
            st.cache_data.clear()
            st.experimental_rerun()
            
    else:
        st.warning("该基金暂无持仓明细数据")

else:
    st.info("👈 点击左侧刷新按钮开始")
