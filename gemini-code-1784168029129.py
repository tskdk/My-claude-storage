import streamlit as st
import boto3
import pymongo
from bson.objectid import ObjectId
import datetime
import urllib.parse
import hashlib

# --- 1. 초기 설정 및 연결 ---
st.set_page_config(page_title="내 클라우드 스토리지", page_icon="☁️", layout="centered")

# S3 클라이언트 연결
@st.cache_resource
def get_s3_client():
    return boto3.client(
        's3',
        region_name=st.secrets["AWS_REGION"],
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY"],
        aws_secret_access_key=st.secrets["AWS_SECRET_KEY"]
    )

# MongoDB 클라이언트 연결
@st.cache_resource
def get_db():
    client = pymongo.MongoClient(st.secrets["MONGODB_URI"])
    return client['cloud_storage_db']

s3 = get_s3_client()
db = get_db()
users_collection = db['users']
items_collection = db['items']

# --- 2. 상태 관리 (Session State) ---
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'current_folder_id' not in st.session_state:
    st.session_state['current_folder_id'] = None
if 'folder_history' not in st.session_state:
    st.session_state['folder_history'] = []

# --- 3. 유틸리티 함수 ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_download_link(s3_key, file_name):
    # S3에서 즉시 다운로드 되도록 강제(attachment)하는 임시 URL 생성
    url = s3.generate_presigned_url(
        ClientMethod='get_object',
        Params={
            'Bucket': st.secrets["AWS_BUCKET_NAME"],
            'Key': s3_key,
            'ResponseContentDisposition': f'attachment; filename="{urllib.parse.quote(file_name)}"'
        },
        ExpiresIn=3600
    )
    return url

# --- 4. 인증 화면 (로그인 / 회원가입) ---
def render_auth_page():
    st.title("☁️ 파이썬 클라우드 스토리지")
    tab1, tab2 = st.tabs(["로그인", "회원가입"])
    
    with tab1:
        login_id = st.text_input("아이디", key="login_id")
        login_pw = st.text_input("비밀번호", type="password", key="login_pw")
        if st.button("로그인"):
            user = users_collection.find_one({"username": login_id, "password": hash_password(login_pw)})
            if user:
                st.session_state['user_id'] = str(user['_id'])
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 틀렸습니다.")
                
    with tab2:
        reg_id = st.text_input("새 아이디", key="reg_id")
        reg_pw = st.text_input("새 비밀번호", type="password", key="reg_pw")
        if st.button("가입하기"):
            if users_collection.find_one({"username": reg_id}):
                st.warning("이미 존재하는 아이디입니다.")
            else:
                users_collection.insert_one({"username": reg_id, "password": hash_password(reg_pw)})
                st.success("가입 성공! 로그인해주세요.")

# --- 5. 메인 스토리지 화면 ---
def render_storage_page():
    st.title("📂 내 드라이브")
    
    if st.button("로그아웃"):
        st.session_state['user_id'] = None
        st.session_state['current_folder_id'] = None
        st.session_state['folder_history'] = []
        st.rerun()
        
    st.divider()

    # 상단 메뉴: 뒤로가기 / 새 폴더 / 파일 업로드
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.session_state['current_folder_id']:
            if st.button("⬅ 상위 폴더"):
                st.session_state['current_folder_id'] = st.session_state['folder_history'].pop()
                st.rerun()
    
    with col2:
        new_folder_name = st.text_input("새 폴더 이름", label_visibility="collapsed", placeholder="새 폴더명")
        if st.button("폴더 생성"):
            if new_folder_name:
                items_collection.insert_one({
                    "name": new_folder_name,
                    "type": "folder",
                    "user_id": st.session_state['user_id'],
                    "parent_id": st.session_state['current_folder_id'],
                    "created_at": datetime.datetime.now()
                })
                st.rerun()

    with col3:
        uploaded_file = st.file_uploader("파일 업로드", label_visibility="collapsed")
        if uploaded_file:
            if st.button("S3에 업로드"):
                s3_key = f"{st.session_state['user_id']}/{int(datetime.datetime.now().timestamp())}-{uploaded_file.name}"
                # S3에 파일 직접 업로드
                s3.upload_fileobj(uploaded_file, st.secrets["AWS_BUCKET_NAME"], s3_key)
                # MongoDB에 정보 저장
                items_collection.insert_one({
                    "name": uploaded_file.name,
                    "type": "file",
                    "user_id": st.session_state['user_id'],
                    "parent_id": st.session_state['current_folder_id'],
                    "s3_key": s3_key,
                    "size": uploaded_file.size,
                    "created_at": datetime.datetime.now()
                })
                st.success("업로드 완료!")
                st.rerun()

    st.divider()

    # 파일 및 폴더 목록 렌더링
    items = list(items_collection.find({
        "user_id": st.session_state['user_id'],
        "parent_id": st.session_state['current_folder_id']
    }).sort([("type", -1), ("name", 1)])) # 폴더를 먼저 보여줌

    if not items:
        st.info("현재 폴더가 비어 있습니다.")
    else:
        for item in items:
            item_col1, item_col2 = st.columns([3, 1])
            with item_col1:
                if item['type'] == 'folder':
                    st.markdown(f"📁 **{item['name']}**")
                else:
                    st.markdown(f"📄 {item['name']} ({(item.get('size', 0)/1024):.1f} KB)")
            
            with item_col2:
                if item['type'] == 'folder':
                    # 폴더 클릭 시 하위 폴더로 이동
                    if st.button("열기", key=f"open_{item['_id']}"):
                        st.session_state['folder_history'].append(st.session_state['current_folder_id'])
                        st.session_state['current_folder_id'] = str(item['_id'])
                        st.rerun()
                else:
                    # 파일 클릭 시 HTML a 태그를 이용해 즉시 다운로드 구현
                    download_url = generate_download_link(item['s3_key'], item['name'])
                    # Streamlit의 Markdown을 이용해 다운로드 버튼 디자인
                    st.markdown(
                        f"""
                        <a href="{download_url}" download="{item['name']}" style="
                            display: inline-block; padding: 5px 10px; 
                            background-color: #FF4B4B; color: white; 
                            text-decoration: none; border-radius: 5px; font-size: 14px;">
                            ⬇ 다운로드
                        </a>
                        """,
                        unsafe_allow_html=True
                    )

# --- 6. 메인 실행 로직 ---
if st.session_state['user_id'] is None:
    render_auth_page()
else:
    render_storage_page()