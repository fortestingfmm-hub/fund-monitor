import streamlit as st
import akshare as ak
import pandas as pd
import plotly.express as px
import time
import datetime

# --- 页面配置 ---
st.set_page_config(page_title="基金实时估值看板", page_icon="📊", layout="wide")
st.title("📊 基金实时估值看板 (专业修复版)")
st.caption("支持批量监控 | A股+港股 | 自动修复LOF基金数据缺失 | 实时计算")

# --- 核心功能 1: 获取全市场行情 (带重试 & 缓存) ---
@st.cache_data(ttl=60)
def get_market_data():
    """获取A股和港股的实时涨跌幅，存入字典"""
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
            break # 成功则跳出
        except:
            time.sleep(1) # 失败休眠1秒重试
    
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

# --- 核心功能 2: 计算单个基金估值 (含强制年份修复) ---
def calculate_single_fund(fund_code, market_map):
    portfolio = pd.DataFrame()
    fund_name = "未知/加载中"
    
    # --- 1. 获取持仓 (多重补救策略) ---
    def try_fetch(source, specific_year=None):
        try:
            # akshare 的 date 参数通常接受字符串年份
            if specific_year:
                return ak.fund_portfolio_hold_em(symbol=fund_code, date=str(specific_year))
            else:
                if source == 'em': return ak.fund_portfolio_hold_em(symbol=fund_code)
                if source == 'cninfo': return ak.fund_portfolio_hold_cninfo(symbol=fund_code)
        except:
            return pd.DataFrame()

    # 策略 A: 默认查询
    portfolio = try_fetch('em')
    
    # 策略 B: 强制查 2025 年 (解决年初查不到最新数据的问题)
    if portfolio.empty:
        portfolio = try_fetch('em', specific_year=2025)
        
    # 策略 C: 备用接口 (巨潮)
    if portfolio.empty:
        portfolio = try_fetch('cninfo')
        
    # 策略 D: 强制查 2024 年 (针对更新极慢的老基金)
    if portfolio.empty:
        portfolio = try_fetch('em', specific_year=2024)

    # 如果所有策略都失败
    if portfolio.empty:
        return {"代码": fund_code, "名称": "获取失败", "估值": 0.0, "状态": "❌ 无数据", "港股含量": 0}

    # --- 2. 解析数据 ---
    try:
        # 尝试提取名称
        if '基金名称' in portfolio.columns and len(portfolio) > 0:
            fund_name = portfolio.iloc[0]['基金名称']

        cols = portfolio.columns.tolist()
        holdings = pd.DataFrame()

        # 智能排序找最新持仓
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

        # 确保只取前10大
        holdings = holdings.head(10)
        
        # --- 3. 计算估值 ---
        total_contribution = 0
        hk_count = 0
        
        for _, row in holdings.iterrows():
            # 列名容错
            s_code = str(row.get('股票代码', row.get('代码', '')))
            w_val = row.get('占净值比例', row.get('市值占净值比', 0))
            
            try: weight = float(w_val)
            except: weight = 0.0
            
            # 统计港股 (5位代码)
            if len(s_code) == 5: hk_count += 1
            
            # 匹配行情 (尝试 原代码, 补0, 去后缀)
            change = 0.0
            keys_to_try = [s_code, "0"+s_code, s_code.split('.')[0]]
            
            for k in keys_to_try:
                if k in market_map:
                    change = market_map[k]
                    break
            
            total_contribution += change * (weight / 100)
            
        # 状态图标
        if hk_count > 0:
            status = f"🇭🇰 港股({hk_count})"
        else:
            status = "🇨🇳 A股"
            
        # 修正基金名称显示
        display_name = fund_name if fund_name != "未知/加载中" else f"基金{fund_code}"

        return {
            "代码": fund_code,
            "名称": display_name,
            "估值": round(total_contribution, 2),
            "状态": status,
            "港股含量": hk_count
        }

    except Exception as e:
        return {"代码": fund_code, "名称": "解析错误", "估值": 0.0, "状态": "⚠️ 异常", "港股含量": 0}

# --- 界面 UI ---

# 侧边栏配置
with st.sidebar:
    st.header("📝 基金池设置")
    # 默认包含 易方达蓝筹(005827) 和 建信优选(161226)
    default_text = "005827\n161226\n110011\n000001"
    codes_input = st.text_area("输入代码 (每行一个)", value=default_text, height=200)
    
    # 清洗输入：去空行、去空格
    fund_codes = [line.strip() for line in codes_input.split('\n') if line.strip()]
    
    start_btn = st.button("🚀 刷新估值", type="primary")
    st.markdown("---")
    st.markdown("**说明：**\n1. 红色代表估值上涨\n2. 绿色代表估值下跌\n3. 🇭🇰 表示含港股持仓")

# 主区域逻辑
if start_btn:
    if not fund_codes:
        st.warning("请先在左侧输入基金代码！")
    else:
        # 1. 初始化进度条
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 2. 获取行情 (耗时操作)
        with st.spinner("正在连接交易所获取实时行情..."):
            market_map = get_market_data()
        
        # 3. 循环计算
        results = []
        for i, code in enumerate(fund_codes):
            status_text.text(f"正在分析 ({i+1}/{len(fund_codes)}): {code} ...")
            
            # 计算单个
            res = calculate_single_fund(code, market_map)
            results.append(res)
            
            # 更新进度
            progress_bar.progress((i + 1) / len(fund_codes))
            
        status_text.text("✅ 所有基金计算完成！")
        time.sleep(1)
        status_text.empty()
        progress_bar.empty()
        
        # 4. 展示结果
        df_res = pd.DataFrame(results)
        
        # 4.1 数据概览 (使用 Metrics)
        avg_val = df_res['估值'].mean()
        up_count = len(df_res[df_res['估值'] > 0])
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("监控数量", f"{len(df_res)} 只")
        col_b.metric("平均涨跌", f"{avg_val:.2f}%", delta_color="normal")
        col_c.metric("上涨数量", f"{up_count} 只", delta_color="off")
        
        st.divider()

        # 4.2 详细表格 (带颜色高亮)
        st.subheader("📋 详细估值表")
        
        # 定义颜色函数
        def color_valuation(val):
            color = '#d32f2f' if val > 0 else '#2e7d32' if val < 0 else 'black'
            return f'color: {color}; font-weight: bold'

        st.dataframe(
            df_res.style.applymap(color_valuation, subset=['估值'])
                        .format({"估值": "{:+.2f}%"}),
            use_container_width=True,
            column_config={
                "代码": st.column_config.TextColumn("代码", width="small"),
                "名称": st.column_config.TextColumn("基金名称"),
                "估值": st.column_config.NumberColumn("估算涨跌", format="%.2f%%"),
                "状态": st.column_config.TextColumn("持仓类型"),
                "港股含量": st.column_config.NumberColumn("港股数", help="前十大重仓中包含的港股数量"),
            },
            hide_index=True
        )

        # 4.3 可视化图表
        if not df_res.empty:
            st.subheader("📊 涨跌幅对比")
            # 排序方便看
            df_chart = df_res.sort_values(by='估值', ascending=False)
            
            fig = px.bar(
                df_chart, 
                x='名称', 
                y='估值', 
                color='估值',
                text='估值',
                hover_data=['代码', '状态'],
                color_continuous_scale=['#2e7d32', '#f5f5f5', '#d32f2f'], # 绿-白-红
                range_color=[-3, 3]
            )
            fig.update_traces(texttemplate='%{text:.2f}%', textposition='outside')
            st.plotly_chart(fig, use_container_width=True)

else:
    # 初始欢迎页
    st.info("👈 请在左侧侧边栏输入代码，点击按钮开始。")
    st.markdown("""
    ### 🌟 功能亮点
    1. **批量处理**：一次性看清手里所有基金的当日表现。
    2. **LOF 支持**：专门修复了 161226 等 LOF 基金数据难抓的问题。
    3. **港股穿透**：易方达蓝筹等含港股基金也能准确估值。
    4. **智能容错**：输入错误代码不会导致程序崩溃。
    """)
