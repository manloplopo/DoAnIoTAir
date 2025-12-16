import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
import pandas as pd
import plotly.express as px
import json

# --- 1. KẾT NỐI FIREBASE (AN TOÀN) ---
if not firebase_admin._apps:
    # Lấy cấu hình từ Streamlit Secrets
    key_dict = dict(st.secrets["firebase"])
    cred = credentials.Certificate(key_dict)
    
    # Kết nối với URL Database của bạn
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://iot32-233a2-default-rtdb.asia-southeast1.firebasedatabase.app'
    })

# --- 2. HÀM LẤY DỮ LIỆU ---
def get_data():
    ref = db.reference('/air_quality') # Đường dẫn node dữ liệu trong Firebase
    data = ref.get()
    if data:
        # Chuyển đổi dữ liệu JSON thành DataFrame
        df = pd.DataFrame.from_dict(data, orient='index')
        # Sắp xếp theo thời gian (nếu có cột time hoặc timestamp)
        return df
    return pd.DataFrame()

# --- 3. GIAO DIỆN DASHBOARD ---
st.set_page_config(page_title="Giám Sát Không Khí", page_icon="🌤️")
st.title("🌤️ Hệ Thống Giám Sát Chất Lượng Không Khí")

# Nút làm mới dữ liệu
if st.button('🔄 Cập nhật dữ liệu mới nhất'):
    st.rerun()

# Load dữ liệu
df = get_data()

if not df.empty:
    # Lấy bản ghi mới nhất (dòng cuối cùng)
    last_row = df.iloc[-1]
    
    # Hiển thị thông số hiện tại (Metric Cards)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nhiệt độ", f"{last_row.get('temp', 0)} °C")
    c2.metric("Độ ẩm", f"{last_row.get('hum', 0)} %")
    c3.metric("Bụi PM2.5", f"{last_row.get('pm25', 0)} µg/m³")
    c4.metric("Khí Gas (MQ)", f"{last_row.get('mq135', 0)}")

    # Cảnh báo màu sắc
    pm_val = float(last_row.get('pm25', 0))
    if pm_val <= 80:
        st.success("Không khí SẠCH 🟢")
    elif pm_val <= 150:
        st.warning("Cảnh báo: Ô nhiễm nhẹ 🟡")
    else:
        st.error("NGUY HIỂM: Ô nhiễm nặng 🔴")

    # Vẽ biểu đồ lịch sử
    st.subheader("📉 Biểu đồ diễn biến")
    
    # Chuyển đổi index thành cột thời gian nếu cần thiết
    if 'time' in df.columns:
        x_column = 'time' # Dùng cột 'time' (ví dụ: 10:30:05)
    else:
        df['Time_ID'] = df.index 
        x_column = 'Time_ID' # Dự phòng nếu dữ liệu cũ chưa có time

    fig = px.line(df, x=x_column, y=['pm25', 'temp', 'hum'], 
                  title='Diễn biến Nhiệt độ, Độ ẩm và Bụi mịn',
                  markers=True)
    st.plotly_chart(fig, use_container_width=True)

    # Hiển thị bảng dữ liệu
    with st.expander("Xem dữ liệu chi tiết"):
        st.dataframe(df.sort_index(ascending=False)) # Mới nhất lên đầu

else:

    st.info("Chưa có dữ liệu trên Firebase hoặc đang tải...")


