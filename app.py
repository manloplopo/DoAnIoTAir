import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from prophet import Prophet
import time
from datetime import datetime, date

# ==========================================
# 1. KẾT NỐI FIREBASE
# ==========================================
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://iot32-233a2-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Lỗi kết nối Firebase: {e}")
        st.stop()

# ==========================================
# 2. HÀM LẤY & XỬ LÝ DỮ LIỆU
# ==========================================
@st.cache_data(ttl=6)  # Cache 6 giây (gần với chu kỳ 5s của ESP32)
def get_data():
    try:
        ref = db.reference('/air_quality')
        data = ref.get()

        if not data:
            return pd.DataFrame()

        records = []
        for key, val in data.items():
            # Mỗi bản ghi có: temp, hum, pm25, mq135, deviceOn
            # ESP32 không gửi time, nhưng web server gửi time HH:MM:SS qua /data
            # Tuy nhiên Firebase push không có time → ta dùng thứ tự push (mới nhất ở cuối)
            record = {
                'key': key,
                'temp': val.get('temp', 0),
                'hum': val.get('hum', 0),
                'pm25': val.get('pm25', 0),
                'mq135': val.get('mq135', 0),
                'deviceOn': val.get('deviceOn', True)
            }
            records.append(record)

        df = pd.DataFrame(records)

        if df.empty:
            return df

        # Sắp xếp theo thứ tự push (key Firebase tăng dần → bản ghi mới nhất ở cuối)
        df = df.sort_index().reset_index(drop=True)

        # Tạo datetime: lấy ngày hôm nay + giờ từ web (nhưng Firebase không có time)
        # => Giả lập thời gian dựa trên khoảng cách 5 giây (độ chính xác chấp nhận được)
        now = pd.Timestamp.now()
        df['datetime'] = [now - pd.Timedelta(seconds=5 * i) for i in range(len(df))][::-1]

        return df

    except Exception as e:
        st.error(f"Lỗi tải dữ liệu: {e}")
        return pd.DataFrame()

# ==========================================
# 3. GIAO DIỆN DASHBOARD
# ==========================================
st.set_page_config(page_title="Air Quality Monitor", page_icon="🌤️", layout="wide")

c1, c2 = st.columns([3, 1])
with c1:
    st.title("🌤️ Giám Sát Chất Lượng Không Khí")
with c2:
    if st.button('🔄 Cập nhật ngay'):
        st.rerun()

df = get_data()

if not df.empty:
    last_row = df.iloc[-1]

    st.subheader("⏱️ Thông số hiện tại")

    # Trạng thái thiết bị
    device_on = bool(last_row['deviceOn'])
    if device_on:
        st.success("✅ THIẾT BỊ ĐANG HOẠT ĐỘNG")
    else:
        st.error("🛑 THIẾT BỊ ĐANG TẮT (Dữ liệu có thể cũ)")

    m1, m2, m3, m4 = st.columns(4)

    temp = float(last_row['temp'])
    hum = float(last_row['hum'])
    pm25 = float(last_row['pm25'])
    mq135 = int(last_row['mq135'])

    m1.metric("🌡️ Nhiệt độ", f"{temp:.1f} °C")
    m2.metric("💧 Độ ẩm", f"{hum:.1f} %")
    m3.metric("🌫️ Bụi PM2.5", f"{pm25:.2f} µg/m³")
    m4.metric("🧪 Khí Gas (MQ135)", f"{mq135}")

    # Cảnh báo theo đúng logic ESP32 mới
    status_cols = st.columns(2)

    with status_cols[0]:
        if pm25 <= 80:
            st.success("✅ PM2.5: Không khí SẠCH")
        elif pm25 <= 150:
            st.warning("⚠️ PM2.5: Ô nhiễm nhẹ - Cảnh báo")
        else:
            st.error("🚨 PM2.5: NGUY HIỂM - Ô nhiễm nặng")

    with status_cols[1]:
        if mq135 < 600:
            st.success("✅ Khí Gas: An toàn (LED Xanh)")
        elif mq135 < 1000:
            st.warning("⚠️ Khí Gas: Cảnh báo (LED Vàng - CO2 cao)")
        else:
            st.error("🚨 Khí Gas: NGUY HIỂM (LED Đỏ - Phát hiện khí độc)")

    # ==================================
    # BIỂU ĐỒ LỊCH SỬ
    # ==================================
    st.divider()
    st.subheader("📉 Biểu đồ diễn biến")

    fig = go.Figure()

    fig.add_trace(go.Scatter(x=df['datetime'], y=df['temp'], name='Nhiệt độ (°C)', line=dict(color='red')))
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['hum'], name='Độ ẩm (%)', line=dict(color='blue')))
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['pm25'], name='PM2.5 (µg/m³)', line=dict(color='green'), yaxis='y2'))
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['mq135'], name='MQ135', line=dict(color='orange'), yaxis='y3'))

    fig.update_layout(
        xaxis_title="Thời gian",
        yaxis=dict(title="Nhiệt độ / Độ ẩm", side='left'),
        yaxis2=dict(title="PM2.5", overlaying='y', side='right', position=0.85),
        yaxis3=dict(title="MQ135", overlaying='y', side='right', anchor='free', position=1.0),
        legend=dict(x=0, y=1.2, orientation='h'),
        height=500,
        margin=dict(r=100)
    )

    st.plotly_chart(fig, use_container_width=True)

    # ==================================
    # DỰ BÁO PM2.5 (PROPHET)
    # ==================================
    st.divider()
    st.subheader("🔮 Dự báo xu hướng PM2.5 (30 phút tới)")

    if len(df) >= 20:  # Cần ít nhất 20 điểm để Prophet hoạt động ổn định
        try:
            with st.spinner("Đang huấn luyện mô hình Prophet..."):
                df_prophet = df[['datetime', 'pm25']].copy()
                df_prophet = df_prophet.rename(columns={'datetime': 'ds', 'pm25': 'y'})

                m = Prophet(
                    daily_seasonality=False,
                    weekly_seasonality=False,
                    yearly_seasonality=False,
                    changepoint_prior_scale=0.05
                )
                m.add_seasonality(name='minute_cycle', period=30, fourier_order=5)
                m.fit(df_prophet)

                future = m.make_future_dataframe(periods=30, freq='T')  # 30 phút tới, mỗi phút
                forecast = m.predict(future)

                fig_forecast = go.Figure()
                # Dữ liệu thực
                fig_forecast.add_trace(go.Scatter(
                    x=df_prophet['ds'], y=df_prophet['y'],
                    mode='lines+markers', name='Thực tế', line=dict(color='green')
                ))
                # Dự báo
                fig_forecast.add_trace(go.Scatter(
                    x=forecast['ds'], y=forecast['yhat'],
                    mode='lines', name='Dự báo', line=dict(color='purple')
                ))
                # Vùng tin cậy
                fig_forecast.add_trace(go.Scatter(
                    x=forecast['ds'], y=forecast['yhat_upper'],
                    mode='lines', line=dict(width=0), showlegend=False
                ))
                fig_forecast.add_trace(go.Scatter(
                    x=forecast['ds'], y=forecast['yhat_lower'],
                    mode='lines', line=dict(width=0), fill='tonexty',
                    fillcolor='rgba(128, 0, 128, 0.2)', name='Vùng tin cậy 80%'
                ))

                fig_forecast.update_layout(
                    title="Dự báo nồng độ PM2.5 trong 30 phút tới",
                    xaxis_title="Thời gian",
                    yaxis_title="PM2.5 (µg/m³)",
                    height=450
                )
                st.plotly_chart(fig_forecast, use_container_width=True)

                # Nhận xét xu hướng
                recent_avg = df_prophet['y'].tail(10).mean()
                forecast_next_30 = forecast['yhat'].tail(30).mean()
                trend_diff = forecast_next_30 - recent_avg

                if trend_diff > 5:
                    st.error("🚨 Dự báo: Bụi PM2.5 có xu hướng TĂNG MẠNH trong 30 phút tới!")
                elif trend_diff > 2:
                    st.warning("⚠️ Dự báo: Bụi PM2.5 đang tăng nhẹ.")
                elif trend_diff < -5:
                    st.success("✅ Dự báo: Chất lượng không khí sẽ CẢI THIỆN rõ rệt.")
                elif trend_diff < -2:
                    st.success("✅ Dự báo: Bụi PM2.5 đang giảm nhẹ.")
                else:
                    st.info("ℹ️ Dự báo: Chất lượng không khí ổn định trong 30 phút tới.")

        except Exception as e:
            st.warning(f"Lỗi dự báo: {e}")
    else:
        st.info(f"Đang thu thập dữ liệu... (có {len(df)} bản ghi, cần ít nhất 20 để dự báo)")

    # ==================================
    # BẢNG DỮ LIỆU CHI TIẾT
    # ==================================
    with st.expander("📋 Xem dữ liệu thô (mới nhất ở trên)"):
        display_df = df.copy()
        display_df['datetime'] = display_df['datetime'].dt.strftime('%H:%M:%S')
        display_df['deviceOn'] = display_df['deviceOn'].map({True: 'Bật', False: 'Tắt'})
        st.dataframe(
            display_df[['datetime', 'temp', 'hum', 'pm25', 'mq135', 'deviceOn']]
            .sort_values(by='datetime', ascending=False)
            .reset_index(drop=True),
            use_container_width=True
        )

else:
    st.info("Đang chờ dữ liệu từ thiết bị ESP32... Vui lòng đợi vài giây.")
    time.sleep(2)
    st.rerun()
