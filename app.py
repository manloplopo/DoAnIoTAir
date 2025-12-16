import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from prophet import Prophet
import time

# ==========================================
# 1. KẾT NỐI FIREBASE (AN TOÀN & BẢO MẬT)
# ==========================================
if not firebase_admin._apps:
    try:
        # Lấy cấu hình từ Streamlit Secrets
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        
        # Kết nối với URL Database (Lấy từ code ESP32 của bạn)
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://iot32-233a2-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Lỗi kết nối Firebase: {e}")
        st.stop()

# ==========================================
# 2. HÀM LẤY & XỬ LÝ DỮ LIỆU
# ==========================================
@st.cache_data(ttl=5) # Cache dữ liệu 5 giây để giảm tải cho Firebase
def get_data():
    try:
        ref = db.reference('/air_quality') # Node dữ liệu trong Firebase
        data = ref.get()
        
        if data:
            # Chuyển đổi JSON sang DataFrame
            df = pd.DataFrame.from_dict(data, orient='index')
            
            # --- XỬ LÝ CỘT THỜI GIAN ---
            # Code ESP32 không gửi kèm ngày tháng năm, chỉ gửi giờ:phút:giây
            # Firebase tự sinh Key (ví dụ -OgX...) có chứa thông tin thời gian ẩn
            # Cách tốt nhất là tạo một cột thời gian giả lập dựa trên thứ tự bản ghi nếu thiếu timestamp chuẩn
            
            df = df.reset_index() # Đưa Key Firebase ra thành cột 'index'
            
            # Nếu có cột 'time' từ ESP32 gửi lên (như trong code arduino handleData)
            # Nhưng lưu ý: Hàm sendFirebase trong code Arduino KHÔNG gửi kèm trường 'time'
            # Nó chỉ gửi: temp, hum, pm25, mq135.
            # Do đó ta phải tự tạo thời gian dựa trên việc giả định dữ liệu gửi đều đặn
            
            # Tạo cột thời gian thực tế (Giả sử bản ghi cuối là hiện tại, mỗi bản ghi cách nhau 5s)
            now = pd.Timestamp.now()
            df['datetime'] = [now - pd.Timedelta(seconds=5*i) for i in range(len(df))][::-1]
            
            return df
    except Exception as e:
        st.error(f"Lỗi tải dữ liệu: {e}")
    return pd.DataFrame()

# ==========================================
# 3. GIAO DIỆN DASHBOARD
# ==========================================
st.set_page_config(page_title="Air Quality Monitor", page_icon="🌤️", layout="wide")

# Tiêu đề & Nút làm mới
c1, c2 = st.columns([3, 1])
with c1:
    st.title("🌤️ Giám Sát Chất Lượng Không Khí")
with c2:
    if st.button('🔄 Cập nhật ngay'):
        st.rerun()

# Load dữ liệu
df = get_data()

if not df.empty:
    # Lấy bản ghi mới nhất
    last_row = df.iloc[-1]
    
    # --- PHẦN 1: THÔNG SỐ REALTIME ---
    st.subheader("⏱️ Thông số hiện tại")

    # Lấy thêm trạng thái thiết bị
    device_on = last_row.get('deviceOn', True) # Mặc định là True nếu không có dữ liệu
    
    # Hiển thị trạng thái máy
    if device_on:
        st.success("✅ THIẾT BỊ ĐANG HOẠT ĐỘNG")
    else:
        st.error("🛑 THIẾT BỊ ĐANG TẮT (Dữ liệu có thể cũ)")

    m1, m2, m3, m4 = st.columns(4)
    
    temp = float(last_row.get('temp', 0))
    hum = float(last_row.get('hum', 0))
    pm25 = float(last_row.get('pm25', 0))
    mq135 = int(last_row.get('mq135', 0))
    
    m1.metric("🌡️ Nhiệt độ", f"{temp} °C")
    m2.metric("💧 Độ ẩm", f"{hum} %")
    m3.metric("🌫️ Bụi PM2.5", f"{pm25:.2f} µg/m³")
    m4.metric("🧪 Khí Gas (MQ)", f"{mq135}")

    # --- CẢNH BÁO MÀU SẮC (Logic giống code ESP32) ---
    # Code ESP32: xanh (<150), vàng (150-300), đỏ (>300) cho MQ
    # Code ESP32: nháy đèn đỏ nếu PM2.5 > 80
    
    status_cols = st.columns(2)
    
    # Đánh giá PM2.5
    with status_cols[0]:
        if pm25 <= 80:
            st.success("✅ PM2.5: Không khí SẠCH")
        elif pm25 <= 150:
            st.warning("⚠️ PM2.5: Cảnh báo (Ô nhiễm nhẹ)")
        else:
            st.error("🚨 PM2.5: NGUY HIỂM (Ô nhiễm nặng)")
            
    # Đánh giá MQ135
    with status_cols[1]:
        if mq135 < 150:
            st.success("✅ Khí Gas: An toàn")
        elif mq135 < 300:
            st.warning("⚠️ Khí Gas: Cảnh báo")
        else:
            st.error("🚨 Khí Gas: Phát hiện khí độc!")

    # --- PHẦN 2: BIỂU ĐỒ LỊCH SỬ ---
    st.divider()
    st.subheader("📉 Biểu đồ diễn biến")
    
    # Biểu đồ đa trục (Nhiệt/Ẩm trục trái, PM2.5/Gas trục phải)
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['temp'], name='Nhiệt độ (°C)', line=dict(color='red')))
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['hum'], name='Độ ẩm (%)', line=dict(color='blue')))
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['pm25'], name='PM2.5', line=dict(color='green'), yaxis='y2'))
    
    fig.update_layout(
        xaxis_title="Thời gian",
        yaxis=dict(title="Nhiệt độ / Độ ẩm"),
        yaxis2=dict(title="PM2.5 (µg/m³)", overlaying='y', side='right'),
        legend=dict(x=0, y=1.2, orientation='h'),
        height=400
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- PHẦN 3: DỰ BÁO (PROPHET) ---
    st.divider()
    st.subheader("🔮 Dự báo xu hướng (30 phút tới)")
    
    if len(df) > 30: # Cần ít nhất 30 điểm dữ liệu để dự báo
        try:
            with st.spinner("Đang chạy mô hình AI dự báo..."):
                # Chuẩn bị dữ liệu cho Prophet (cột ds và y)
                df_prophet = df[['datetime', 'pm25']].rename(columns={'datetime': 'ds', 'pm25': 'y'})
                
                # Huấn luyện mô hình
                m = Prophet()
                m.fit(df_prophet)
                
                # Tạo khung thời gian tương lai (30 phút, mỗi phút 1 điểm)
                future = m.make_future_dataframe(periods=30, freq='1min') 
                forecast = m.predict(future)
                
                # Vẽ biểu đồ dự báo
                fig_forecast = px.line(forecast, x='ds', y='yhat', title="Dự báo nồng độ PM2.5", labels={'ds': 'Thời gian', 'yhat': 'PM2.5 Dự báo'})
                
                # Thêm vùng tin cậy (Confidence Interval)
                fig_forecast.add_traces([
                    go.Scatter(x=forecast['ds'], y=forecast['yhat_upper'], mode='lines', line_color='rgba(0,0,0,0)', showlegend=False),
                    go.Scatter(x=forecast['ds'], y=forecast['yhat_lower'], mode='lines', line_color='rgba(0,0,0,0)', fill='tonexty', fillcolor='rgba(0, 255, 0, 0.2)', name='Vùng tin cậy')
                ])
                
                st.plotly_chart(fig_forecast, use_container_width=True)
                
                # Nhận xét xu hướng
                trend = forecast.iloc[-1]['yhat'] - forecast.iloc[-30]['yhat']
                if trend > 2:
                    st.error("⚠️ Dự báo: Xu hướng bụi tăng nhanh trong 30 phút tới!")
                elif trend < -2:
                    st.success("✅ Dự báo: Chất lượng không khí đang cải thiện.")
                else:
                    st.info("ℹ️ Dự báo: Chất lượng không khí ổn định.")
                    
        except Exception as e:
            st.warning(f"Chưa đủ dữ liệu để dự báo chính xác ({e})")
    else:
        st.info("Cần thu thập thêm dữ liệu để chạy mô hình dự báo...")

    # --- PHẦN 4: BẢNG DỮ LIỆU ---
    with st.expander("Xem dữ liệu chi tiết"):
        st.dataframe(df.sort_values(by='datetime', ascending=False))

else:
    st.info("Đang chờ dữ liệu từ thiết bị ESP32... Vui lòng đợi trong giây lát.")
    time.sleep(2)
    st.rerun()

