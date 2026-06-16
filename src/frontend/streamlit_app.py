from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
SHOW_NWP_COMPARISON = os.getenv("ENV", "local") == "local"

# ---------------------------------------------------------------------------
# 天気コード → クラス / 表示情報
# ---------------------------------------------------------------------------

# Open-Meteo が返す WMO 天気コード → 表示クラス
WEATHER_CODE_TO_CLASS: dict[int, int] = {
    # 快晴・ほぼ快晴
    0: 1, 1: 1, 2: 1,
    # 一部曇り・曇り・霧
    3: 2, 45: 2, 48: 2,
    # 霧雨
    51: 3, 53: 3, 55: 3,
    # 雨
    61: 3, 63: 3, 65: 3,
    # にわか雨
    80: 3, 81: 3, 82: 3,
    # 凍結霧雨・凍結雨
    56: 4, 57: 4, 66: 4, 67: 4,
    # 降雪・雪粒・にわか雪
    71: 4, 73: 4, 75: 4, 77: 4, 85: 4, 86: 4,
    # 雷雨・雹を伴う雷雨
    95: 5, 96: 5, 99: 5,
}

WEATHER_CLASS_INFO: dict[int, tuple[str, str]] = {
    1: ("晴天",   "☀️"),
    2: ("曇天",   "☁️"),
    3: ("雨",     "☔"),
    4: ("雪・氷", "❄️"),
    5: ("雷雨",   "⚡️"),
}

DOW_JA = ["月", "火", "水", "木", "金", "土", "日"]


# ---------------------------------------------------------------------------
# データ取得・整形
# ---------------------------------------------------------------------------

class ModelNotReady(Exception):
    """API が 503 を返した場合（モデル未学習）。"""


@st.cache_data(ttl=60)
def load_predictions() -> pd.DataFrame:
    resp = requests.get(f"{API_URL}/forecast", timeout=300)
    if resp.status_code == 503:
        raise ModelNotReady(resp.json().get("detail", "モデルが未学習です"))
    resp.raise_for_status()
    df = pd.DataFrame(resp.json()["predictions"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


@st.cache_data(ttl=3600)
def load_model_info() -> dict | None:
    try:
        resp = requests.get(f"{API_URL}/model-info", timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


@st.cache_data(ttl=600)
def load_today_weather() -> dict | None:
    try:
        resp = requests.get(f"{API_URL}/today", timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def extract_tokyo(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "datetime":                                  "datetime",
        "step_hour":                                 "step_hour",
        "temperature_2m_tokyo_center":               "temperature",
        "precipitation_corrected":                   "precipitation",
        "precipitation_probability_tokyo_center":    "precipitation_probability",
        "cloud_cover_corrected":                     "cloud_cover",
        "cloud_cover_low_corrected":                 "cloud_cover_low",
        "weather_code_tokyo_center":                 "weather_code",
    }
    missing = [k for k in col_map if k not in df.columns and k not in ("datetime", "step_hour")]
    if missing:
        st.error(f"予測データに必要な列がありません: {missing}")
        st.stop()

    result = df[[k for k in col_map]].rename(columns=col_map).copy()

    for src, dst in [
        ("nwp_temperature_2m",  "nwp_temperature"),
        ("nwp_precipitation",   "nwp_precipitation"),
        ("nwp_cloud_cover",     "nwp_cloud_cover"),
        ("nwp_cloud_cover_low", "nwp_cloud_cover_low"),
    ]:
        if src in df.columns:
            result[dst] = df[src]

    result["weather_class"] = result["weather_code"].map(
        lambda c: WEATHER_CODE_TO_CLASS.get(int(c), 1)
    )
    result["date"] = result["datetime"].dt.date
    return result


def make_daily(df: pd.DataFrame) -> pd.DataFrame:
    def worst_class(codes):
        return max(WEATHER_CODE_TO_CLASS.get(int(c), 1) for c in codes)

    return (
        df.groupby("date")
        .agg(
            max_temp        =("temperature",             "max"),
            min_temp        =("temperature",             "min"),
            max_precip_prob =("precipitation_probability", "max"),
            max_precip      =("precipitation",           "max"),
            weather_class   =("weather_code",            worst_class),
        )
        .reset_index()
        .assign(max_precip=lambda d: d["max_precip"].clip(lower=0))
    )


def _weather_transition(day_df: pd.DataFrame) -> list[str]:
    """朝(6-11)/昼(12-17)/夜(18-23) の代表天気アイコンリストを返す（最大3要素、連続重複は除去）。"""
    hour = day_df["datetime"].dt.hour
    slots = [
        day_df[hour.between(6, 11)],
        day_df[hour.between(12, 17)],
        day_df[hour.between(18, 23)],
    ]
    icons: list[str] = []
    for slot in slots:
        if slot.empty:
            continue
        worst = max(WEATHER_CODE_TO_CLASS.get(int(c), 1) for c in slot["weather_code"])
        _, emoji = WEATHER_CLASS_INFO.get(worst, ("❓", "❓"))
        icons.append(emoji)

    result: list[str] = []
    for icon in icons:
        if not result or icon != result[-1]:
            result.append(icon)
    return result if result else ["❓"]


# ---------------------------------------------------------------------------
# UI コンポーネント
# ---------------------------------------------------------------------------

def _card_html(date_obj, max_temp: float, min_temp: float, max_precip_prob: float, max_precip: float, icons: list[str]) -> str:
    dow = DOW_JA[date_obj.weekday()]
    date_color = "#e05c3a" if date_obj.weekday() == 6 else ("#3a7ae0" if date_obj.weekday() == 5 else "#333")
    prob_pct = int(round(max_precip_prob * 100 / 5) * 5)  # 5%区切り

    if prob_pct > 0:
        precip_str = "最大0.01mm以上" if max_precip < 0.05 else f"最大 {max_precip:.1f}mm"
        precip_html = f'<div style="font-size:11px; color:#5ba4e0;">({precip_str})</div>'
    else:
        precip_html = ""

    arrow = '<span style="font-size:10px; color:#999; margin:0 2px; vertical-align:middle;">▶</span>'
    transition_html = arrow.join(
        f'<span style="font-size:20px; line-height:1;">{icon}</span>' for icon in icons
    )

    return f"""
    <div style="text-align:center; padding:10px 6px; border:1px solid #e8e8e8;
                border-radius:12px; background:#fafafa; height:100%;">
      <div style="font-size:13px; font-weight:600; color:{date_color};">
        {date_obj.strftime('%m/%d')}({dow})
      </div>
      <div style="margin:6px 0; white-space:nowrap; overflow:hidden;">
        {transition_html}
      </div>
      <div style="font-size:17px; color:#e05c3a; font-weight:700;">▲ {max_temp:.1f}°</div>
      <div style="font-size:17px; color:#3a7ae0; font-weight:700;">▼ {min_temp:.1f}°</div>
      <div style="font-size:12px; color:#5ba4e0; margin-top:6px;">💧 {prob_pct}%</div>
      {precip_html}
    </div>
    """


def render_daily_cards(daily: pd.DataFrame, hourly: pd.DataFrame) -> None:
    cols = st.columns(len(daily))
    for i, (_, row) in enumerate(daily.iterrows()):
        day_df = hourly[hourly["date"] == row.date]
        icons = _weather_transition(day_df)
        with cols[i]:
            st.markdown(
                _card_html(row.date, row.max_temp, row.min_temp, row.max_precip_prob, row.max_precip, icons),
                unsafe_allow_html=True,
            )


def render_temperature_chart(df: pd.DataFrame) -> None:
    daily = df.groupby("date").agg(max_temp=("temperature", "max"), min_temp=("temperature", "min")).reset_index()
    daily["datetime_start"] = pd.to_datetime(daily["date"])
    daily["datetime_end"]   = daily["datetime_start"] + pd.Timedelta(hours=23)

    fig = go.Figure()

    for _, row in daily.iterrows():
        x_range = [row.datetime_start, row.datetime_end, row.datetime_end, row.datetime_start]
        y_range = [row.max_temp, row.max_temp, row.min_temp, row.min_temp]
        fig.add_trace(go.Scatter(
            x=x_range, y=y_range,
            fill="toself",
            fillcolor="rgba(224, 92, 58, 0.08)",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        ))

    if SHOW_NWP_COMPARISON and "nwp_temperature" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"],
            y=df["nwp_temperature"],
            mode="lines",
            name="NWP生予報",
            line=dict(color="#aaaaaa", width=1.5, dash="dash"),
            hovertemplate="%{x|%m/%d %H:00}<br><b>NWP: %{y:.1f}°C</b><extra></extra>",
        ))

    fig.add_trace(go.Scatter(
        x=df["datetime"],
        y=df["temperature"],
        mode="lines",
        name="補正済み予報",
        line=dict(color="#e05c3a", width=2.5),
        hovertemplate="%{x|%m/%d %H:00}<br><b>%{y:.1f}°C</b><extra></extra>",
    ))

    fig.update_layout(
        title=dict(text="🌡️ 気温（°C）", font=dict(size=15, color="#333"), x=0),
        showlegend=SHOW_NWP_COMPARISON,
        xaxis=dict(
            tickformat="%m/%d(%a)",
            dtick=86400000,
            showgrid=True,
            gridcolor="#d0d0d0",
            tickfont=dict(color="#444", size=11),
            title=dict(font=dict(color="#333")),
        ),
        yaxis=dict(
            title="°C",
            ticksuffix="°",
            showgrid=True,
            gridcolor="#d0d0d0",
            tickfont=dict(color="#444", size=11),
            title_font=dict(color="#333"),
        ),
        height=300,
        margin=dict(t=45, b=30, l=50, r=20),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(font=dict(color="#333", size=12), bgcolor="rgba(255,255,255,0.8)"),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_precipitation_chart(df: pd.DataFrame) -> None:
    fig = go.Figure()

    if SHOW_NWP_COMPARISON and "nwp_precipitation" in df.columns:
        fig.add_trace(go.Bar(
            x=df["datetime"],
            y=df["nwp_precipitation"].clip(lower=0),
            name="NWP生予報",
            marker_color="#cccccc",
            opacity=0.6,
            hovertemplate="%{x|%m/%d %H:00}<br><b>NWP: %{y:.2f} mm</b><extra></extra>",
        ))

    fig.add_trace(go.Bar(
        x=df["datetime"],
        y=df["precipitation"].clip(lower=0),
        name="補正済み予報",
        marker_color="#5ba4e0",
        opacity=0.8,
        hovertemplate="%{x|%m/%d %H:00}<br><b>%{y:.2f} mm</b><extra></extra>",
    ))

    fig.update_layout(
        title=dict(text="🌧️ 降水量（mm）", font=dict(size=15, color="#333"), x=0),
        showlegend=SHOW_NWP_COMPARISON,
        barmode="overlay",
        xaxis=dict(
            tickformat="%m/%d(%a)",
            dtick=86400000,
            showgrid=True,
            gridcolor="#d0d0d0",
            tickfont=dict(color="#444", size=11),
            title=dict(font=dict(color="#333")),
        ),
        yaxis=dict(
            title="mm",
            rangemode="tozero",
            showgrid=True,
            gridcolor="#d0d0d0",
            tickfont=dict(color="#444", size=11),
            title_font=dict(color="#333"),
        ),
        height=240,
        margin=dict(t=45, b=30, l=50, r=20),
        bargap=0.15,
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(font=dict(color="#333", size=12), bgcolor="rgba(255,255,255,0.8)"),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_cloud_chart(df: pd.DataFrame) -> None:
    fig = go.Figure()

    if SHOW_NWP_COMPARISON and "nwp_cloud_cover" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"],
            y=df["nwp_cloud_cover"].clip(0, 100),
            mode="lines",
            name="NWP全雲量",
            line=dict(color="#5ba4e0", width=1.5, dash="dash"),
            hovertemplate="%{x|%m/%d %H:00}<br><b>NWP全雲量: %{y:.0f}%</b><extra></extra>",
        ))
    if SHOW_NWP_COMPARISON and "nwp_cloud_cover_low" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"],
            y=df["nwp_cloud_cover_low"].clip(0, 100),
            mode="lines",
            name="NWP下層雲量",
            line=dict(color="#a8d4f5", width=1.5, dash="dash"),
            hovertemplate="%{x|%m/%d %H:00}<br><b>NWP下層雲量: %{y:.0f}%</b><extra></extra>",
        ))

    fig.add_trace(go.Scatter(
        x=df["datetime"],
        y=df["cloud_cover"].clip(0, 100),
        mode="lines",
        name="全雲量（補正済み）",
        line=dict(color="#888888", width=2),
        fill="tozeroy",
        fillcolor="rgba(136,136,136,0.12)",
        hovertemplate="%{x|%m/%d %H:00}<br><b>全雲量: %{y:.0f}%</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["datetime"],
        y=df["cloud_cover_low"].clip(0, 100),
        mode="lines",
        name="下層雲量（補正済み）",
        line=dict(color="#aaaaaa", width=1.5, dash="dot"),
        hovertemplate="%{x|%m/%d %H:00}<br><b>下層雲量: %{y:.0f}%</b><extra></extra>",
    ))

    fig.update_layout(
        title=dict(text="☁️ 雲量（%）", font=dict(size=15, color="#333"), x=0),
        xaxis=dict(
            tickformat="%m/%d(%a)",
            dtick=86400000,
            showgrid=True,
            gridcolor="#d0d0d0",
            tickfont=dict(color="#444", size=11),
            title=dict(font=dict(color="#333")),
        ),
        yaxis=dict(
            title="%",
            range=[0, 100],
            ticksuffix="%",
            showgrid=True,
            gridcolor="#d0d0d0",
            tickfont=dict(color="#444", size=11),
            title_font=dict(color="#333"),
        ),
        height=240,
        margin=dict(t=45, b=30, l=50, r=20),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(color="#333", size=12),
        ),
    )

    st.plotly_chart(fig, use_container_width=True)


@st.cache_data(ttl=3600)
def load_historical_comparison(days: int = 7) -> dict | None:
    try:
        resp = requests.get(f"{API_URL}/historical-comparison", params={"days": days}, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def render_comparison_section() -> None:
    """過去の NWP 生予報・補正済み予報・ERA5 実績の比較セクション。"""
    st.markdown("---")
    st.markdown("### 📊 過去の予報精度（NWP 生予報 vs 補正済み予報 vs ERA5 実績）")
    st.caption("ERA5 実績データは約 5 日の遅延があるため、直近 5 日を除いた過去 7 日間を表示しています。")

    data = load_historical_comparison(days=7)
    if data is None or not data.get("records"):
        st.info("比較データを取得できませんでした。")
        return

    df = pd.DataFrame(data["records"])
    df["datetime"] = pd.to_datetime(df["datetime"])

    period = f"{data['period_start'][:10]} 〜 {data['period_end'][:10]}"
    st.caption(f"表示期間: {period}")

    tab_temp, tab_precip, tab_cloud = st.tabs(["🌡️ 気温", "🌧️ 降水量", "☁️ 雲量"])

    _COMPARISON_COLORS = {
        "actual":    ("#333333", "solid",  "ERA5 実績"),
        "forecast":  ("#5ba4e0", "dash",   "NWP 生予報"),
        "corrected": ("#e05c3a", "solid",  "補正済み予報"),
    }

    def _make_comparison_fig(col_prefix: str, y_title: str, height: int = 300) -> go.Figure:
        fig = go.Figure()
        for suffix, (color, dash, label) in _COMPARISON_COLORS.items():
            col = f"{col_prefix}_{suffix}"
            if col not in df.columns:
                continue
            fig.add_trace(go.Scatter(
                x=df["datetime"],
                y=df[col],
                mode="lines",
                name=label,
                line=dict(color=color, width=2, dash=dash),
                hovertemplate=f"%{{x|%m/%d %H:00}}<br><b>{label}: %{{y:.2f}}</b><extra></extra>",
            ))
        fig.update_layout(
            xaxis=dict(
                tickformat="%m/%d(%a)",
                dtick=86400000,
                showgrid=True,
                gridcolor="#d0d0d0",
                tickfont=dict(color="#444", size=11),
                title_font=dict(color="#333"),
            ),
            yaxis=dict(
                title=y_title,
                showgrid=True,
                gridcolor="#d0d0d0",
                tickfont=dict(color="#444", size=11),
                title_font=dict(color="#333"),
            ),
            height=height,
            margin=dict(t=50, b=30, l=50, r=20),
            hovermode="x unified",
            plot_bgcolor="white",
            paper_bgcolor="white",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                font=dict(color="#333", size=12),
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#ccc",
                borderwidth=1,
            ),
        )
        return fig

    with tab_temp:
        st.plotly_chart(_make_comparison_fig("temp", "°C"), use_container_width=True)
    with tab_precip:
        st.plotly_chart(_make_comparison_fig("precip", "mm"), use_container_width=True)
    with tab_cloud:
        col1, col2 = st.columns(2)
        with col1:
            st.caption("全雲量")
            st.plotly_chart(_make_comparison_fig("cloud", "%"), use_container_width=True)
        with col2:
            st.caption("下層雲量")
            st.plotly_chart(_make_comparison_fig("cloud_low", "%"), use_container_width=True)


def render_today_weather() -> None:
    """現在の東京の天気を取得して表示する。"""
    today = load_today_weather()
    if today is None:
        return

    time_str = today.get("time") or today.get("datetime", "")
    try:
        time_label = pd.to_datetime(time_str).strftime("%Y/%m/%d %H:%M")
    except Exception:
        time_label = str(time_str)

    temp = today.get("temperature_2m")
    precip = today.get("precipitation")
    wind = today.get("wind_speed_10m")
    wcode = today.get("weather_code")

    wclass = WEATHER_CODE_TO_CLASS.get(int(wcode), 1) if wcode is not None else 1
    wlabel, wemoji = WEATHER_CLASS_INFO.get(wclass, ("不明", "❓"))

    parts = [f"{wemoji} **{wlabel}**"]
    if temp is not None:
        parts.append(f"🌡️ **{temp:.1f}°C**")
    if precip is not None:
        parts.append(f"💧 {precip:.1f} mm")
    if wind is not None:
        parts.append(f"💨 {wind:.1f} m/s")

    st.markdown(f"#### 📍 現在の東京の天気　<span style='font-size:13px;color:#888;'>更新: {time_label}</span>", unsafe_allow_html=True)
    st.markdown("　".join(parts))
    st.markdown("---")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

st.set_page_config(page_title="東京 天気予報", page_icon="🌤️", layout="wide")

st.title("🌤️ 東京の天気予報（1週間）")

render_today_weather()

with st.spinner("予測を生成中..."):
    try:
        raw_df = load_predictions()
        model_not_ready = False
    except ModelNotReady as e:
        model_not_ready = True
        st.warning(
            "**モデル未学習のため、予報データがありません。**\n\n"
            "以下の手順でモデルを学習してください：\n"
            "```\n"
            "make fetch   # データ取得\n"
            "make train   # 学習・評価・MLflow 登録\n"
            "```\n\n"
            f"詳細: {e}"
        )
    except Exception as e:
        st.error(f"予測の読み込みに失敗しました: {e}")
        st.stop()

if not model_not_ready:
    df    = extract_tokyo(raw_df)
    daily = make_daily(df)

    start_dt = df["datetime"].min()
    st.caption(f"予測開始: {start_dt.strftime('%Y年%m月%d日 %H:00')} から 168時間（1時間ごと）")

    st.markdown("---")
    render_daily_cards(daily, df)
    st.markdown("<br>", unsafe_allow_html=True)
    render_temperature_chart(df)
    render_precipitation_chart(df)
    render_cloud_chart(df)

render_comparison_section()

if not model_not_ready:
    info = load_model_info()
    tokyo_info = (info or {}).get("tokyo", {})
    if tokyo_info.get("registry_version"):
        parts = [
            f"**{tokyo_info['model_name']}** v{tokyo_info['registry_version']}",
            f"run: {tokyo_info.get('run_name', '-')}",
            f"git: `{tokyo_info.get('git_commit', '-')}`",
        ]
        data_start = tokyo_info.get("training_data_start")
        data_end   = tokyo_info.get("training_data_end")
        if data_start and data_end:
            parts.append(f"学習期間: {data_start} 〜 {data_end}")
        st.markdown("---")
        st.caption("🤖 モデル情報　" + "　／　".join(parts))
