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
    # --- 内部函数：尝试获取数据 ---
    def fetch_data(source_type):
        try:
            if source_type == "em": 
                # 注意：这里务必使用 symbol=fund_code
                return ak.fund_portfolio_hold_em(symbol=fund_code)
            elif source_type == "cninfo": 
                return ak.fund_portfolio_hold_cninfo(symbol=fund_code)
        except:
            return pd.DataFrame() 

    # 1. 获取数据
    portfolio = fetch_data("em")
    if portfolio.empty:
        st.toast(f"东方财富源无数据，尝试巨潮源...", icon="🔄")
        portfolio = fetch_data("cninfo")
    
    if portfolio.empty:
        return None, "未找到持仓数据 (请确认基金代码正确)", 0

    try:
        # --- 🔍 核心修复：智能识别列名 ---
        # 打印一下列名，方便调试 (在CMD窗口可以看到)
        print(f"Debug: 抓取到的列名: {portfolio.columns.tolist()}")

        holdings = pd.DataFrame()
        
        # 情况 A: 如果有 '年份' 和 '季度' 列 (旧格式)
        if '年份' in portfolio.columns and '季度' in portfolio.columns:
            portfolio['年份'] = portfolio['年份'].astype(str)
            latest_year = portfolio['年份'].max()
            df_year = portfolio[portfolio['年份'] == latest_year]
            latest_quarter = df_year['季度'].max()
            holdings = df_year[df_year['季度'] == latest_quarter]

        # 情况 B: 如果只有 '季度' 列 (新格式, 例如 "2024年3季度")
        elif '季度' in portfolio.columns:
            # 字符串排序: "2024年3季度" > "2023年4季度"，所以直接降序排
            portfolio = portfolio.sort_values(by='季度', ascending=False)
            # 取第一行的季度作为最新季度
            latest_q_str = portfolio.iloc[0]['季度']
            # 筛选出所有属于该季度的数据
            holdings = portfolio[portfolio['季度'] == latest_q_str]
            
        # 情况 C: 只有 '截止报告期' (巨潮源常见)
        elif '截止报告期' in portfolio.columns:
             portfolio = portfolio.sort_values(by='截止报告期', ascending=False)
             latest_date = portfolio.iloc[0]['截止报告期']
             holdings = portfolio[portfolio['截止报告期'] == latest_date]
        
        else:
            return None, f"无法识别的数据格式，列名: {portfolio.columns.tolist()}", 0

        # 取前10大重仓 (防止数据源返回全部持仓)
        holdings = holdings.head(10)

        # --- 下面是通用的计算逻辑 ---
        market_map, err = get_market_data()
        if err: return None, f"行情失败: {err}", 0

        details = []
        total_contribution = 0
        
        for _, row in holdings.iterrows():
            # 兼容不同接口的列名 (有的叫'股票代码', 有的叫'代码')
            stock_code = str(row.get('股票代码', row.get('代码', '')))
            stock_name = row.get('股票名称', row.get('简称', '未知'))
            # 兼容权重列名 (有的叫'占净值比例', 有的叫'市值占净值比')
            weight = float(row.get('占净值比例', row.get('市值占净值比', 0)))
            
            # 匹配行情
            current_change = 0.0
            found = False
            
            # 尝试直接匹配 / 补零匹配 / 去后缀匹配
            keys_to_try = [stock_code, "0"+stock_code, stock_code.split('.')[0]]
            
            for k in keys_to_try:
                if k in market_map:
                    current_change = market_map[k]
                    found = True
                    break
            
            contribution = current_change * (weight / 100)
            total_contribution += contribution
            
            market_type = "🇭🇰" if len(stock_code) == 5 else "🇨🇳"
            
            details.append({
                "市场": market_type,
                "股票名称": stock_name,
                "代码": stock_code,
                "权重": weight,
                "今日涨跌%": current_change if found else 0.0,
                "贡献度": contribution
            })
            
        return pd.DataFrame(details), None, total_contribution

    except Exception as e:
        import traceback
        traceback.print_exc() # 在CMD打印详细报错
        return None, f"数据解析错误: {str(e)}", 0

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


