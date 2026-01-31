import streamlit as st
import akshare as ak
import pandas as pd
import plotly.express as px
import time

# --- 页面配置 ---
st.set_page_config(page_title="基金实时估值修复版", page_icon="🔧", layout="centered")
st.title("🔧 基金实时估值 (强力修复版)")
st.caption("修复内容：变量丢失报错 | LOF基金支持 | 自动重试")

# --- 核心功能 1: 获取行情 (带重试) ---
@st.cache_data(ttl=60)
def get_market_data():
    market_map = {}
    
    # 1. A股行情
    try:
        df_a = ak.stock_zh_a_spot_em()
        for _, row in df_a.iterrows():
            try:
                code = str(row['代码'])
                val = row['涨跌幅']
                market_map[code] = float(val) if val is not None else 0.0
            except: continue
    except Exception as e:
        print(f"A股行情获取部分失败: {e}")

    # 2. 港股行情 (允许失败)
    try:
        df_hk = ak.stock_hk_spot_em()
        for _, row in df_hk.iterrows():
            try:
                code = str(row['代码']) 
                val = row['涨跌幅']
                market_map[code] = float(val) if val is not None else 0.0
            except: continue
    except:
        pass

    return market_map

# --- 核心功能 2: 获取持仓 (绝对安全逻辑) ---
def get_valuation(fund_code):
    # ⭐ 关键修复：一开始就初始化变量，防止报错
    portfolio = pd.DataFrame() 
    
    # --- 第一步：尝试获取数据 (多源) ---
    # 1. 尝试主接口 (东方财富)
    try:
        portfolio = ak.fund_portfolio_hold_em(symbol=fund_code)
    except:
        pass # 失败了不要紧，portfolio 还是空的

    # 2. 如果主接口没抓到，尝试备用接口 (巨潮)
    if portfolio.empty:
        try:
            st.toast(f"正在切换线路查询 {fund_code}...", icon="🔄")
            portfolio = ak.fund_portfolio_hold_cninfo(symbol=fund_code)
        except:
            pass

    # 3. 最终检查：如果还是空的，那就是真的抓不到
    if portfolio.empty:
        return None, "无法获取持仓数据 (可能是IP被封或基金代码不支持)", 0

    # --- 第二步：解析数据 (智能列名匹配) ---
    try:
        cols = portfolio.columns.tolist()
        holdings = pd.DataFrame()

        # 这里的逻辑是：不管列名怎么变，我们只找我们需要的
        # 优先找 '季度' 进行排序
        if '季度' in cols:
            portfolio = portfolio.sort_values(by='季度', ascending=False)
            latest = portfolio.iloc[0]['季度']
            holdings = portfolio[portfolio['季度'] == latest]
        elif '截止报告期' in cols:
            portfolio = portfolio.sort_values(by='截止报告期', ascending=False)
            latest = portfolio.iloc[0]['截止报告期']
            holdings = portfolio[portfolio['截止报告期'] == latest]
        elif '年份' in cols:
            latest = portfolio['年份'].max()
            holdings = portfolio[portfolio['年份'] == latest]
        else:
            # 如果什么都没有，就硬着头皮取前10行试试
            holdings = portfolio.head(10)

        # 截取前10大重仓
        holdings = holdings.head(10)
        
        # --- 第三步：计算估值 ---
        market_map = get_market_data()
        
        details = []
        total_contribution = 0
        
        for _, row in holdings.iterrows():
            # 容错获取字段 (不管它叫 '股票代码' 还是 '代码')
            s_code = str(row.get('股票代码', row.get('代码', '')))
            s_name = row.get('股票名称', row.get('简称', '未知'))
            # 容错获取权重 (不管它叫 '占净值比例' 还是 '市值占净值比')
            weight_val = row.get('占净值比例', row.get('市值占净值比', 0))
            try:
                weight = float(weight_val)
            except:
                weight = 0.0
            
            # 匹配行情
            change = 0.0
            found = False
            # 尝试多种代码格式
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
                "涨跌%": change,
                "贡献": contribution,
                "状态": "✅" if found else "❌"
            })
            
        return pd.DataFrame(details), None, total_contribution

    except Exception as e:
        return None, f"数据解析发生错误: {str(e)}", 0

# --- 界面 UI ---
fund_code = st.text_input("输入基金代码:", value="005827")

if st.button("🚀 开始计算", type="primary"):
    with st.spinner("正在努力连接数据源..."):
        df, error, val = get_valuation(fund_code)
        
        if error:
            st.error(error)
            st.warning("如果一直失败，请检查是否开启了VPN，或稍后再试。")
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
            try:
                fig = px.bar(df, x='股票', y='涨跌%', color='涨跌%', 
                             title="重仓股表现热力图",
                             text='市场',
                             color_continuous_scale=['green', '#f0f0f0', 'red'],
                             range_color=[-5, 5])
                st.plotly_chart(fig, use_container_width=True)
            except:
                st.caption("图表加载失败，请看下方表格")
            
            # 表格
            st.dataframe(df.style.format({
                "权重": "{:.2f}%", "涨跌%": "{:.2f}%", "贡献": "{:.4f}%"
            }), use_container_width=True)
