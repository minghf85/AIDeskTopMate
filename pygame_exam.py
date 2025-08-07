import os
import pygame
import pygame.gfxdraw
import live2d.v3 as live2d
# import live2d.v2 as live2d

from live2d.utils.image import Image
import win32gui
import win32con
import win32api

def make_window_transparent():
    """使窗口透明和无边框"""
    # 获取pygame窗口句柄
    hwnd = pygame.display.get_wm_info()["window"]
    
    # 设置窗口样式为无边框
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    style = style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    
    # 设置扩展样式，使窗口支持透明
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex_style = ex_style | win32con.WS_EX_LAYERED
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    
    # 设置透明色键（黑色透明）
    win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(0, 0, 0), 0, win32con.LWA_COLORKEY)
    
    # 设置窗口置顶
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, 
                         win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

def main():
    pygame.init()
    live2d.init()

    screen_width, screen_height = win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
    base_display = (screen_width, screen_height)
    current_scale = 1.0
    display = base_display
    
    # 设置高质量OpenGL属性
    pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
    pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 8)  # 提升到8x MSAA
    pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
    pygame.display.gl_set_attribute(pygame.GL_ALPHA_SIZE, 8)
    pygame.display.gl_set_attribute(pygame.GL_RED_SIZE, 8)
    pygame.display.gl_set_attribute(pygame.GL_GREEN_SIZE, 8)
    pygame.display.gl_set_attribute(pygame.GL_BLUE_SIZE, 8)
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    pygame.display.gl_set_attribute(pygame.GL_ACCELERATED_VISUAL, 1)
    
    screen = pygame.display.set_mode(display, pygame.DOUBLEBUF | pygame.OPENGL | pygame.NOFRAME)
    pygame.display.set_caption("Live2D Transparent Window")

    # 设置窗口透明和无边框
    try:
        make_window_transparent()
        print("Window made transparent and borderless")
    except Exception as e:
        print(f"Failed to make window transparent: {e}")

    live2d.glewInit()
    
    # 参考Live2DWindow.py的高质量OpenGL设置
    import OpenGL.GL as gl
    try:
        # 清除所有OpenGL错误
        while gl.glGetError() != gl.GL_NO_ERROR:
            pass
        
        # 设置视口
        gl.glViewport(0, 0, display[0], display[1])
        
        # 设置投影矩阵 - 参考Live2DWindow.py的设置
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, display[0], display[1], 0, -1, 1)  # 使用与Live2DWindow相同的深度范围
        
        # 设置模型视图矩阵
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        
        # 启用混合模式 - 与Live2DWindow.py相同
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        
        # 启用多重采样抗锯齿
        gl.glEnable(gl.GL_MULTISAMPLE)
        
        # 禁用不必要的功能以提高性能和质量
        gl.glDisable(gl.GL_DEPTH_TEST)  # Live2D通常不需要深度测试
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_LIGHTING)
        
        # 设置纹理过滤 - 高质量纹理采样
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        
        # 启用各种平滑模式
        gl.glEnable(gl.GL_LINE_SMOOTH)
        gl.glHint(gl.GL_LINE_SMOOTH_HINT, gl.GL_NICEST)
        
        gl.glEnable(gl.GL_POLYGON_SMOOTH)
        gl.glHint(gl.GL_POLYGON_SMOOTH_HINT, gl.GL_NICEST)
        
        # 设置点平滑
        gl.glEnable(gl.GL_POINT_SMOOTH)
        gl.glHint(gl.GL_POINT_SMOOTH_HINT, gl.GL_NICEST)
        
        # 设置透视校正
        gl.glHint(gl.GL_PERSPECTIVE_CORRECTION_HINT, gl.GL_NICEST)
        
        print("高质量OpenGL设置已启用")
    except Exception as e:
        print(f"设置OpenGL时出错: {e}")

    model = live2d.LAppModel()

    # 检查模型文件是否存在
    model_path = "Haru/Haru.model3.json" if live2d.LIVE2D_VERSION == 3 else "v2/kasumi2/kasumi2.model.json"
    if not os.path.exists(model_path):
        print(f"Warning: Model file not found: {model_path}")
        # 尝试寻找其他模型文件
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.endswith('.model3.json') or file.endswith('.model.json'):
                    model_path = os.path.join(root, file)
                    print(f"Using model file: {model_path}")
                    break
            if model_path != ("Haru/Haru.model3.json" if live2d.LIVE2D_VERSION == 3 else "v2/kasumi2/kasumi2.model.json"):
                break

    try:
        model.LoadModelJson(model_path)
        print(f"Model loaded: {model_path}")
    except Exception as e:
        print(f"Failed to load model: {e}")
        return
    print(model.GetCanvasSize())
    print(model.GetCanvasSizePixel())
    model.Resize(*display)

    clock = pygame.time.Clock()
    running = True
    dragging_window = False
    window_drag_offset = (0, 0)
    
    # 获取窗口句柄用于拖拽
    hwnd = pygame.display.get_wm_info()["window"]

    while running:
        # 获取全局鼠标位置用于视角跟随
        global_mouse_pos = win32gui.GetCursorPos()
        window_rect = win32gui.GetWindowRect(hwnd)
        
        # 计算相对于窗口的鼠标位置（即使鼠标在窗口外）
        relative_mouse_x = global_mouse_pos[0] - window_rect[0]
        relative_mouse_y = global_mouse_pos[1] - window_rect[1]
        
        # 将鼠标位置转换为Live2D坐标系（-1到1）
        look_x = (relative_mouse_x / display[0]) * 2.0 - 1.0
        look_y = -((relative_mouse_y / display[1]) * 2.0 - 1.0)  # Y轴翻转
        
        # 限制视角范围
        look_x = max(-1.0, min(1.0, look_x))
        look_y = max(-1.0, min(1.0, look_y))
        
        # 设置模型视角跟随
        try:
            model.SetParameterValue("ParamAngleX", look_x * 30)  # 角度范围约-30到30
            model.SetParameterValue("ParamAngleY", look_y * 30)
            model.SetParameterValue("ParamEyeBallX", look_x)
            model.SetParameterValue("ParamEyeBallY", look_y)
        except Exception as e:
            pass  # 忽略参数不存在的错误

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    # 空格键触发随机动作
                    try:
                        model.StartRandomMotion("TapBody", 3)
                    except:
                        pass
                elif event.key == pygame.K_r:
                    # R键重置窗口大小
                    current_scale = 1.0
                    display = base_display
                    screen = pygame.display.set_mode(display, pygame.DOUBLEBUF | pygame.OPENGL | pygame.NOFRAME)
                    model.Resize(*display)
                    make_window_transparent()
            
            elif event.type == pygame.MOUSEWHEEL:
                # 滚轮缩放窗口大小
                scale_factor = 1.1 if event.y > 0 else 0.9
                current_scale *= scale_factor
                current_scale = max(0.2, min(2.0, current_scale))  # 限制缩放范围
                model.SetScale(current_scale)

            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # 左键 - 点击功能
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    
                    # 检查是否点击在Live2D模型上
                    try:
                        if part_ids := model.HitPart(mouse_x, mouse_y):
                            print(part_ids)
                    except Exception as e:
                        print(f"Hit test error: {e}")
                
                elif event.button == 3:  # 右键 - 拖拽窗口
                    dragging_window = True
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    window_drag_offset = (mouse_x, mouse_y)
            
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 3:  # 右键释放
                    dragging_window = False
            
            elif event.type == pygame.MOUSEMOTION:
                if dragging_window:
                    # 拖拽窗口
                    mouse_global = win32gui.GetCursorPos()
                    new_x = mouse_global[0] - window_drag_offset[0]
                    new_y = mouse_global[1] - window_drag_offset[1]
                    win32gui.SetWindowPos(hwnd, 0, new_x, new_y, 0, 0, 
                                        win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)

        # 高质量清除和渲染 - 参考Live2DWindow.py
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        
        # 重置模型视图矩阵 - 与Live2DWindow.py保持一致
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        
        # 更新和绘制Live2D模型
        model.Update()
        model.Draw()

        pygame.display.flip()
        clock.tick(120)  # 限制帧率为120FPS

    live2d.dispose()
    pygame.quit()

if __name__ == "__main__":
    main()