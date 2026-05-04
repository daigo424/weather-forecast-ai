from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# 天気コード → クラス / 表示情報
# ---------------------------------------------------------------------------

# Open-Meteo が返す WMO 天気コード → 表示クラス
WEATHER_CODE_TO_CLASS: dict[int, int] = {
    # 快晴・ほぼ快晴
    0: 1, 1: 1,
    # 一部曇り・曇り・霧
    2: 2, 3: 2, 45: 2, 48: 2,
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
    3: ("雨",     "🌧️"),
    4: ("雪・氷", "❄️"),
    5: ("雷雨",   "⛈️"),
}

DOW_JA = ["月", "火", "水", "木", "金", "土", "日"]


# ---------------------------------------------------------------------------
# データ取得・整形
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def load_predictions() -> pd.DataFrame:
    resp = requests.get(f"{API_URL}/forecast", timeout=300)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json()["predictions"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


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
        "datetime":                        "datetime",
        "step_hour":                       "step_hour",
        "temperature_2m_tokyo_center":     "temperature",
        "precipitation_tokyo_center":      "precipitation",
        "weather_code_tokyo_center":       "weather_code",
    }
    missing = [k for k in col_map if k not in df.columns and k != "datetime"]
    if missing:
        st.error(f"予測データに必要な列がありません: {missing}")
        st.stop()

    result = df[[k for k in col_map]].rename(columns=col_map).copy()
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
            max_temp     =("temperature",  "max"),
            min_temp     =("temperature",  "min"),
            total_precip =("precipitation", "sum"),
            weather_class=("weather_code",  worst_class),
        )
        .reset_index()
    )


def _weather_transition(day_df: pd.DataFrame) -> str:
    """朝(6-11)/昼(12-17)/夜(18-23) の代表天気アイコンを → でつなげた文字列を返す。"""
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
    return "→".join(result) if result else "❓"


# ---------------------------------------------------------------------------
# UI コンポーネント
# ---------------------------------------------------------------------------

def _card_html(date_obj, max_temp: float, min_temp: float, total_precip: float, transition: str) -> str:
    dow = DOW_JA[date_obj.weekday()]
    date_color = "#e05c3a" if date_obj.weekday() == 6 else ("#3a7ae0" if date_obj.weekday() == 5 else "#333")

    return f"""
    <div style="text-align:center; padding:10px 6px; border:1px solid #e8e8e8;
                border-radius:12px; background:#fafafa; height:100%;">
      <div style="font-size:13px; font-weight:600; color:{date_color};">
        {date_obj.strftime('%m/%d')}({dow})
      </div>
      <div style="font-size:28px; line-height:1.5; margin:6px 0; letter-spacing:2px;">{transition}</div>
      <div style="font-size:17px; color:#e05c3a; font-weight:700;">▲ {max_temp:.1f}°</div>
      <div style="font-size:17px; color:#3a7ae0; font-weight:700;">▼ {min_temp:.1f}°</div>
      <div style="font-size:12px; color:#5ba4e0; margin-top:6px;">💧 {total_precip:.1f} mm</div>
    </div>
    """


def render_daily_cards(daily: pd.DataFrame, hourly: pd.DataFrame) -> None:
    cols = st.columns(len(daily))
    for i, (_, row) in enumerate(daily.iterrows()):
        day_df = hourly[hourly["date"] == row.date]
        transition = _weather_transition(day_df)
        with cols[i]:
            st.markdown(
                _card_html(row.date, row.max_temp, row.min_temp, row.total_precip, transition),
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

    fig.add_trace(go.Scatter(
        x=df["datetime"],
        y=df["temperature"],
        mode="lines",
        name="気温",
        line=dict(color="#e05c3a", width=2.5),
        hovertemplate="%{x|%m/%d %H:00}<br><b>%{y:.1f}°C</b><extra></extra>",
    ))

    fig.update_layout(
        title=dict(text="🌡️ 気温（°C）", font=dict(size=15, color="#333"), x=0),
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
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_precipitation_chart(df: pd.DataFrame) -> None:
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df["datetime"],
        y=df["precipitation"],
        name="降水量",
        marker_color="#5ba4e0",
        opacity=0.8,
        hovertemplate="%{x|%m/%d %H:00}<br><b>%{y:.2f} mm</b><extra></extra>",
    ))

    fig.update_layout(
        title=dict(text="💧 降水量（mm / h）", font=dict(size=15, color="#333"), x=0),
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
            rangemode="nonnegative",
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
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True)


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
    except Exception as e:
        st.error(f"予測の読み込みに失敗しました: {e}")
        st.info("先に `make train` でモデルを学習し、MLflow にモデルを登録してください。")
        st.stop()

df    = extract_tokyo(raw_df)
daily = make_daily(df)

start_dt = df["datetime"].min()
st.caption(f"予測開始: {start_dt.strftime('%Y年%m月%d日 %H:00')} から 168時間（1時間ごと）")

st.markdown("---")
render_daily_cards(daily, df)
st.markdown("<br>", unsafe_allow_html=True)
render_temperature_chart(df)
render_precipitation_chart(df)
