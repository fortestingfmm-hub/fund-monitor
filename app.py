import streamlit as st
import akshare as ak
import pandas as pd
import plotly.express as px

# --- 页面配置 ---
st.set_page_config(page_title="高级基金估值(含港股)", page_icon="🌏")
st.title("🌏 基金实时估值 (A股+港股版)")
st.caption("支持：沪深A股、港股 | 数据源：东方财富 | 延迟：约 1-3 分钟")

# --- 核心逻辑 ---

@st.cache_data(ttl=60) # 缓存60秒，防止频繁请求卡顿
def get_market_data():
    """一次性获取全市场A股和港股数据，并建立查找表"""
    market_map = {}
    
    try:
        # 1. 获取A股实时行情
        df_a = ak.stock_zh_a_spot_em()
        # 建立 A股 字典：{代码: 涨跌幅}
        for _, row in df_a.iterrows():
            code = str(row['代码'])
            change = float(row['涨跌幅'])
            market_map[code] = change
            
        # 2. 获取港股实时行情
        df_hk = ak.stock_hk_spot_em()
        # 建立 港股 字典：{代码: 涨跌幅}
        # 港股接口返回的代码通常是 5位 (e.g., "00700")
        for _, row in df_hk.iterrows():
            code = str(row['代码']) 
            change = float(row['涨跌幅'])
            market_map[code] = change
            
        return market_map, None
    except Exception as e:
        return {}, str(e)

def get_valuation(fund_code):
    # 1. 获取基金持仓
    try:
        portfolio = ak.fund_portfolio_hold_em(symbol=fund_code)
        if portfolio.empty:
            return None, "未找到持仓数据", 0
            
        # 筛选最新季度
        latest_year = portfolio['年份'].max()
        df_year = portfolio[portfolio['年份'] == latest_year]
        latest_quarter = df_year['季度'].max()
        holdings = df_year[df_year['季度'] == latest_quarter].head(10)
        
        # 获取最新的市场数据
        market_map, err = get_market_data()
        if err:
            return None, f"行情获取失败: {err}", 0

        details = []
        total_contribution = 0
        total_weight = 0
        
        for _, row in holdings.iterrows():
            stock_code = str(row['股票代码'])
            stock_name = row['股票名称']
            weight = float(row['占净值比例'])
            
            # --- 核心匹配逻辑 ---
            # 基金持仓里的港股代码有时是 00700 (5位)，有时带后缀
            # 我们直接在 market_map 里找
            
            current_change = 0.0
            found = False
            
            # 尝试直接匹配
            if stock_code in market_map:
                current_change = market_map[stock_code]
                found = True
            # 尝试补零匹配 (防止数据源格式不一致)
            elif len(stock_code) == 5 and ("0" + stock_code) in market_map: 
                 current_change = market_map["0" + stock_code]
                 found = True
            
            # 计算贡献
            contribution = current_change * (weight / 100)
            total_contribution += contribution
            total_weight += weight
            
            # 标记一下是哪里的股票
            market_type = "🇭🇰 港" if len(stock_code) == 5 else "🇨🇳 A"
            
            details.append({
                "市场": market_type,
                "股票名称": stock_name,
                "代码": stock_code,
                "权重": weight,
                "今日涨跌%": current_change if found else 0.0,
                "贡献度": contribution,
                "状态": "✅" if found else "❌无数据"
            })
            
        return pd.DataFrame(details), None, total_contribution

    except Exception as e:
        return None, str(e), 0

# --- 界面交互 ---

default_code = "005827" # 易方达蓝筹 (典型含港股基金)
fund_code = st.text_input("输入基金代码:", value=default_code)

if st.button("开始计算", type="primary"):
    with st.spinner('正在连接 A股 和 港股 交易所...'):
        df, error_msg, estimate = get_valuation(fund_code)
        
        if error_msg:
            st.error(error_msg)
        else:
            # 结果展示区
            col1, col2 = st.columns(2)
            
            with col1:
                color = "red" if estimate > 0 else "green"
                st.metric("估算净值涨跌", f"{estimate:.2f}%")
            
            with col2:
                # 统计一下含多少港股
                hk_count = len(df[df['市场'].str.contains("港")])
                st.info(f"前十大重仓中包含 {hk_count} 只港股")

            st.caption("注：港股涨跌未计算汇率波动，仅做近似参考。")
            
            # 漂亮的表格
            st.dataframe(
                df.style.format({
                    "权重": "{:.2f}%", 
                    "今日涨跌%": "{:.2f}%", 
                    "贡献度": "{:.4f}%"
                }).background_gradient(subset=['今日涨跌%'], cmap='RdYlGn_r', vmin=-3, vmax=3),
                use_container_width=True
            )
            
            # 柱状图
            fig = px.bar(df, x='股票名称', y='今日涨跌%', 
                         color='今日涨跌%', 
                         text='市场',
                         title="重仓股涨跌幅 (含港股)",
                         color_continuous_scale=['green', '#f0f0f0', 'red'],
                         range_color=[-5, 5])

            st.plotly_chart(fig, use_container_width=True)
