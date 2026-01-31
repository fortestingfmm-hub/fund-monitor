import streamlit as st
import akshare as ak
import pandas as pd
import plotly.express as px
import time

# --- 页面配置 ---
st.set_page_config(page_title="基金实时估值终极版", page_icon="🚀", layout="centered")
st.title("🚀 基金实时估值 (抗网络波动版)")
st.caption("支持：LOF/混合/股票型 | A股+港股 | 自动重试机制")

# --- 核心功能 1: 获取行情 (带自动重试) ---
@st.cache_data(ttl=60)
def get_market_data():
    """获取全市场行情，带断线重连机制"""
    market_map = {}
    max_retries = 3
    
    # 1. 获取 A 股
    df_a = pd.DataFrame()
    for i in range(max_retries):
        try:
            df_a = ak.stock_zh_a_spot_em()
            break
        except Exception as e:
            if i < max_retries - 1:
                print(f"A股行情重试 {i+1}...")
                time.sleep(1)
            else:
                return {}, f"网络连接失败，请关闭VPN后重试: {str(e)}"

    if not df_a.empty:
        for _, row in df_a.iterrows():
            try:
                code = str(row['代码'])
                val = row['涨跌幅']
                market_map[code] = float(val) if val is not None else 0.0
            except: continue

    # 2. 获取港股 (失败不报错，只打印)
    for i in range(max_retries):
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

    return market_map, None

# --- 核心功能 2: 获取持仓 (带多源切换 & 智能解析) ---
def get_valuation(fund_code):
    
    # 内部函数：获取原始数据
    # 内部函数：获取原始数据 (暴力增强版)
    def fetch_raw_data(source):
        try:
            # 1. 尝试标准接口
            if source == 'em': 
                df = ak.fund_portfolio_hold_em(symbol=fund_code)
                if not df.empty: return df
                
                # 🚑 补丁：如果标准接口没数据，尝试 "大成基金" 接口 (有时候这个接口有LOF数据)
                # 注意：这个接口返回格式可能不同，但我们试试运气
                try:
                    print(f"尝试备用接口抓取 {fund_code}...")
                    # 这是一个很少用但对老基金很有效的接口
                    return ak.fund_portfolio_hold_em(symbol=fund_code, date="2024") # 强行指定年份试试
                except:
                    pass

            # 2. 尝试巨潮接口
            if source == 'cninfo': 
                return ak.fund_portfolio_hold_cninfo(symbol=fund_code)
                
        except Exception as e:
            print(f"接口报错: {e}") # 在黑窗口打印真实错误
            return pd.DataFrame()
        return pd.DataFrame()

    try:
        # --- 智能解析列名 ---
        # 很多报错是因为列名变了，这里做模糊匹配逻辑
        cols = portfolio.columns.tolist()
        holdings = pd.DataFrame()

        # 逻辑 A: 按季度排序找最新的
        if '季度' in cols:
            # 字符串排序: "2025年1季度" > "2024年4季度"
            portfolio = portfolio.sort_values(by='季度', ascending=False)
            latest_q = portfolio.iloc[0]['季度']
            holdings = portfolio[portfolio['季度'] == latest_q]
        # 逻辑 B: 按截止日期排序
        elif '截止报告期' in cols:
            portfolio = portfolio.sort_values(by='截止报告期', ascending=False)
            latest_d = portfolio.iloc[0]['截止报告期']
            holdings = portfolio[portfolio['截止报告期'] == latest_d]
        # 逻辑 C: 旧版年份逻辑 (兼容)
        elif '年份' in cols:
            latest_y = portfolio['年份'].max()
            df_y = portfolio[portfolio['年份'] == latest_y]
            # 这里如果不含季度列，就直接用
            holdings = df_y 
        else:
            return None, f"数据格式异常，列名: {cols}", 0
        
        # 截取前10大
        holdings = holdings.head(10)
        
        # --- 计算估值 ---
        market_map, err = get_market_data()
        if err: return None, err, 0

        details = []
        total_contribution = 0
        
        for _, row in holdings.iterrows():
            # 容错获取字段
            s_code = str(row.get('股票代码', row.get('代码', '')))
            s_name = row.get('股票名称', row.get('简称', '未知'))
            weight = float(row.get('占净值比例', row.get('市值占净值比', 0)))
            
            # 匹配行情 (尝试 A股6位, 港股5位, 补零等多种情况)
            change = 0.0
            found = False
            possible_keys = [s_code, "0"+s_code, s_code.split('.')[0]]
            
            for k in possible_keys:
                if k in market_map:
                    change = market_map[k]
                    found = True
                    break
            
            contribution = change * (weight / 100)
            total_contribution += contribution
            
            details.append({
                "市场": "🇭🇰" if len(s_code)==5 else "🇨🇳",
                "股票": s_name,
                "代码": s_code,
                "权重": weight,
                "涨跌%": change if found else 0.0,
                "贡献": contribution,
                "状态": "✅" if found else "❌"
            })
            
        return pd.DataFrame(details), None, total_contribution

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"解析错误: {str(e)}", 0

# --- 界面 UI ---
fund_code = st.text_input("输入基金代码:", value="005827")

if st.button("🚀 开始计算", type="primary"):
    with st.spinner("正在连接交易所数据..."):
        df, error, val = get_valuation(fund_code)
        
        if error:
            st.error(error)
        else:
            # 结果卡片
            col1, col2 = st.columns(2)
            with col1:
                color = "red" if val > 0 else "green"
                st.metric("估算净值涨跌", f"{val:.2f}%")
            with col2:
                hk_cnt = len(df[df['市场']=="🇭🇰"])
                st.info(f"含 {hk_cnt} 只港股" if hk_cnt > 0 else "纯A股持仓")

            # 图表
            fig = px.bar(df, x='股票', y='涨跌%', color='涨跌%', 
                         title="重仓股表现热力图",
                         text='市场',
                         color_continuous_scale=['green', '#f0f0f0', 'red'],
                         range_color=[-5, 5])
            st.plotly_chart(fig, use_container_width=True)
            
            # 表格
            st.dataframe(df.style.format({
                "权重": "{:.2f}%", "涨跌%": "{:.2f}%", "贡献": "{:.4f}%"
            }), use_container_width=True)

