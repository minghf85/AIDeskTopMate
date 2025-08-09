import streamlit as st
import requests
import json
import os
from typing import Dict, List

API_BASE = "http://127.0.0.1:8000"

def init_session_state():
    """初始化会话状态"""
    if 'model_info' not in st.session_state:
        st.session_state.model_info = {}
    if 'available_motions' not in st.session_state:
        st.session_state.available_motions = {}
    if 'available_expressions' not in st.session_state:
        st.session_state.available_expressions = []

def make_api_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict:
    """发送API请求"""
    url = f"{API_BASE}{endpoint}"
    try:
        if method == "GET":
            response = requests.get(url)
        else:
            response = requests.post(url, json=data)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"API请求错误: {str(e)}")
        return {}

def render_model_section():
    """渲染模型控制部分"""
    st.header("模型控制")
    
    # 模型列表
    models_resp = make_api_request("/models/list")
    if models := models_resp.get("models", []):
        selected_model = st.selectbox(
            "选择模型",
            options=[m["path"] for m in models],
            format_func=lambda x: os.path.basename(x)
        )
        
        col1, col2 = st.columns(2)
        with col1:
            scale = st.slider("模型缩放", 0.2, 2.0, 1.0, 0.1)
        with col2:
            pos_x = st.number_input("X位置", value=0)
            pos_y = st.number_input("Y位置", value=0)
            
        if st.button("加载模型"):
            make_api_request("/model/load", "POST", {
                "name": os.path.basename(selected_model),
                "path": selected_model,
                "scale": scale,
                "position": [pos_x, pos_y]
            })

def render_motion_section():
    """渲染动作控制部分"""
    st.header("动作控制")
    
    status = make_api_request("/status")
    state = status.get("state", {})
    available_motions = state.get("available_motions", {})
    
    if available_motions:
        col1, col2 = st.columns(2)
        with col1:
            motion_group = st.selectbox("动作组", options=list(available_motions.keys()))
        with col2:
            # 获取动作数量并确保是整数
            motion_count = available_motions.get(motion_group, [])
            if isinstance(motion_count, list):
                max_index = len(motion_count) - 1
            else:
                max_index = int(motion_count) - 1
            
            motion_index = st.number_input("动作索引", -1, max_index, -1)
            
        priority = st.slider("优先级", 1, 5, 3)
        
        if st.button("播放动作"):
            make_api_request("/motion/play", "POST", {
                "group": motion_group,
                "index": motion_index,
                "priority": priority
            })

def render_expression_section():
    """渲染表情控制部分"""
    st.header("表情控制")
    
    status = make_api_request("/status")
    state = status.get("state", {})
    available_expressions = state.get("available_expressions", [])
    
    if available_expressions:
        expression = st.selectbox(
            "选择表情",
            options=["随机"] + available_expressions
        )
        
        if st.button("设置表情"):
            make_api_request("/expression/set", "POST", {
                "expression_id": None if expression == "随机" else expression
            })

def render_transform_section():
    """渲染变换控制部分"""
    st.header("变换控制")
    
    col1, col2 = st.columns(2)
    with col1:
        offset_x = st.number_input("X偏移", -100.0, 100.0, 0.0, 0.1)
        offset_y = st.number_input("Y偏移", -100.0, 100.0, 0.0, 0.1)
        if st.button("设置偏移"):
            make_api_request("/offset/set", "POST", {
                "x": offset_x,
                "y": offset_y
            })
            
    with col2:
        rotation = st.number_input("旋转角度", -180.0, 180.0, 0.0, 1.0)
        if st.button("设置旋转"):
            make_api_request("/rotation/set", "POST", {
                "degrees": rotation
            })

def render_parameter_section():
    """渲染参数控制部分"""
    st.header("参数控制")
    
    params_resp = make_api_request("/parameters/list")
    if param_ids := params_resp.get("parameter_ids", []):
        param_id = st.selectbox("选择参数", options=param_ids)
        param_info = make_api_request(f"/parameter/info/{param_id}")
        
        if param_info:
            min_val = param_info.get("minimum_value", 0.0)
            max_val = param_info.get("maximum_value", 1.0)
            default_val = param_info.get("default_value", 0.0)
            current_val = param_info.get("current_value", default_val)
            
            col1, col2 = st.columns(2)
            with col1:
                value = st.slider("参数值", min_val, max_val, current_val)
                weight = st.slider("权重", 0.0, 1.0, 1.0, 0.1)
                
            with col2:
                st.write("当前值:", current_val)
                st.write("默认值:", default_val)
                
            col3, col4 = st.columns(2)
            with col3:
                if st.button("设置参数"):
                    make_api_request("/parameter/set", "POST", {
                        "parameter_id": param_id,
                        "value": value,
                        "weight": weight
                    })
            with col4:
                if st.button("重置参数"):
                    make_api_request("/parameter/set", "POST", {
                        "parameter_id": param_id,
                        "value": default_val,
                        "weight": 1.0
                    })

def render_window_section():
    """渲染窗口控制部分"""
    st.header("窗口控制")
    
    col1, col2 = st.columns(2)
    with col1:
        window_x = st.number_input("窗口X位置", 0, 3840, 0)
        window_y = st.number_input("窗口Y位置", 0, 2160, 0)
    
    with col2:
        always_on_top = st.checkbox("窗口置顶", True)
        transparent = st.checkbox("窗口透明", True)
    
    if st.button("应用窗口设置"):
        make_api_request("/window/configure", "POST", {
            "x": window_x,
            "y": window_y,
            "always_on_top": always_on_top,
            "transparent": transparent
        })

def main():
    st.set_page_config(
        page_title="Live2D控制面板",
        page_icon="🎭",
        layout="wide"
    )
    
    st.title("Live2D模型控制面板")
    
    # 初始化会话状态
    init_session_state()
    
    # 检查API服务器状态
    try:
        status = make_api_request("/status")
        if status.get("status") == "running":
            st.success("API服务器连接正常")
        else:
            st.error("API服务器未运行")
            return
    except:
        st.error("无法连接到API服务器")
        return
    
    # 使用tabs组织界面
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "模型控制", "动作控制", "表情控制", 
        "变换控制", "参数控制", "窗口控制"
    ])
    
    with tab1:
        render_model_section()
    with tab2:
        render_motion_section()
    with tab3:
        render_expression_section()
    with tab4:
        render_transform_section()
    with tab5:
        render_parameter_section()
    with tab6:
        render_window_section()

if __name__ == "__main__":
    main()
