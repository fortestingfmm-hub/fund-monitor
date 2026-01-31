import streamlit as st
import akshare as ak
import pandas as pd
import plotly.express as px
import time

# --- 页面配置 ---
st.set_page_config(page_title="我的基金看板", page_icon="📊", layout="wide") # 改成宽屏模式
st.title("📊 我的基金实时估值看板")
st.caption("支持批量监控 | 自动过滤无效代码 | 实时计算")

# --- 核心功能 1: 获取全市场行情 (带重试 & 缓存) ---
@st.cache_data(ttl=60)
def get_market_data():
    market_map = {}
    # 1. A股
    try:
        df_a = ak.stock_zh_a_spot_em()
        for _, row in df_a.iterrows():
            try:
                code = str(row['代码'])
                val = row['涨跌幅']
                market_map[code] = float(val) if val is not None else 0.0
            except: continue
    except: pass
    
    # 2. 港股
    try:
        df_hk = ak.stock_hk_spot_em()
        for _, row in df_hk.iterrows():
            try:
                code = str(row['代码']) 
                val = row['涨跌幅']
                market_map[code] = float(val) if val is not None else 0.0
            except: continue
    except: pass

    return market_map

# --- 核心功能 2: 计算单个基金估值 (健壮版) ---
def calculate_single_fund(fund_code, market_map):
    portfolio = pd.DataFrame()
    fund_name = "未知基金"
    
    # 1. 获取持仓
    try:
        portfolio = ak.fund_portfolio_hold_em(symbol=fund_code)
        # 顺便获取一下基金名字（如果接口里有的话）
        if '基金名称' in portfolio.columns:
            fund_name = portfolio.iloc[0]['基金名称']
    except: pass

    if portfolio.empty:
        try:
            portfolio = ak.fund_portfolio_hold_cninfo(symbol=fund_code)
        except: pass

    if portfolio.empty:
        return {"代码": fund_code, "名称": "获取失败", "估值": 0.0, "状态": "❌ 无数据"}

    # 2. 解析最新持仓
    try:
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
            holdings = portfolio.head(10) # 兜底

        # 尝试从数据里提取基金名称 (有些接口返回包含名称)
        if '基金名称' in holdings.columns and len(holdings) > 0:
            fund_name = holdings.iloc[0]['基金名称']
        
        holdings = holdings.head(10)
        
        # 3. 计算涨跌
        total_contribution = 0
        hk_count = 0
        
        for _, row in holdings.iterrows():
            s_code = str(row.get('股票代码', row.get('代码', '')))
            # 容错获取权重
            w_val = row.get('占净值比例', row.get('市值占净值比', 0))
            try: weight = float(w_val)
            except: weight = 0.0
            
            # 识别港股
            if len(s_code) == 5: hk_count += 1
            
            # 匹配行情
            change = 0.0
            keys = [s_code, "0"+s_code, s_code.split('.')[0]]
            for k in keys:
                if k in market_map:
                    change = market_map[k]
                    break
            
            total_contribution += change * (weight / 100)
            
        status_icon = "🇭🇰" if hk_count > 0 else "🇨🇳"
        
        return {
            "代码": fund_code,
            "名称": fund_name if fund_name != "未知基金" else f"基金{fund_code}",
            "估值": round(total_contribution, 2),
            "状态": f"{status_icon} 成功"
        }

    except Exception as e:
        return {"代码": fund_code, "名称": "解析错", "估值": 0.0, "状态": "❌ 出错"}

# --- 界面 UI ---

# 1. 侧边栏：输入列表
with st.sidebar:
    st.header("📝 持仓设置")
    default_list = "005827\n161226\n110011"
    codes_input = st.text_area("输入基金代码 (一行一个)", value=default_list, height=200)
    
    # 把输入文本变成列表，去掉空行
    fund_codes = [line.strip() for line in codes_input.split('\n') if line.strip()]
    
    start_btn = st.button("🚀 刷新估值", type="primary")
    st.info(f"当前共监控 {len(fund_codes)} 只基金")

# 2. 主区域
if start_btn:
    result_list = []
    
    # 进度条
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    with st.spinner("正在拉取全市场行情..."):
        # 这一步最慢，做一次就好
        market_map = get_market_data()
    
    # 循环计算每个基金
    for i, code in enumerate(fund_codes):
        status_text.text(f"正在计算 ({i+1}/{len(fund_codes)}): {code} ...")
        
        # 计算单个
        res = calculate_single_fund(code, market_map)
        result_list.append(res)
        
        # 更新进度条
        progress_bar.progress((i + 1) / len(fund_codes))
    
    status_text.text("✅ 计算完成！")
    time.sleep(0.5)
    status_text.empty() # 清除提示文字
    progress_bar.empty() # 清除进度条

    # 3. 展示结果表格
    df_res = pd.DataFrame(result_list)
    
    # 美化表格：根据估值正负上色
    def color_val(val):
        color = 'red' if val > 0 else 'green' if val < 0 else 'black'
        return f'color: {color}; font-weight: bold'

    st.subheader("📋 实时估值汇总")
    
    # 使用 Streamlit 的高级表格展示
    st.dataframe(
        df_res.style.applymap(color_val, subset=['估值'])
                    .format({"估值": "{:+.2f}%"}),
        use_container_width=True,
        column_config={
            "代码": st.column_config.TextColumn("代码"),
            "估值": st.column_config.NumberColumn("估值涨跌", format="%.2f%%"),
            "状态": st.column_config.TextColumn("类型/状态"),
        },
        hide_index=True
    )
    
    # 4. 可视化对比
    st.subheader("📊 横向对比")
    fig = px.bar(df_res, x='代码', y='估值', color='估值',
                 hover_data=['名称'],
                 color_continuous_scale=['green', '#f0f0f0', 'red'],
                 range_color=[-3, 3])
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("👈 请在左侧输入代码列表，然后点击“刷新估值”")
    st.markdown("""
    #### 使用说明：
    1. 在左侧文本框输入代码，**每行一个**。
    2. 点击刷新按钮。
    3. 支持 **A股混合基** 和 **LOF** (如 161226)。
    4. 自动识别 **港股** 重仓（显示 🇭🇰 图标）。
    """)
