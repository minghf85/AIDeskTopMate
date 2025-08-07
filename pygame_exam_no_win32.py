import os
import pygame
import live2d.v3 as live2d
import OpenGL.GL as gl
from OpenGL.GL import *

def main():
    # 设置环境变量以支持透明窗口
    os.environ['SDL_VIDEO_WINDOW_POS'] = '100,100'
    
    pygame.init()
    live2d.init()

    # 获取屏幕尺寸
    info = pygame.display.Info()
    screen_width = info.current_w
    screen_height = info.current_h
    
    # 设置窗口大小（不使用全屏）
    window_width = 400
    window_height = 600
    display = (window_width, window_height)
    
    # 设置OpenGL属性以获得更好的透明度支持
    pygame.display.gl_set_attribute(pygame.GL_ALPHA_SIZE, 8)
    pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    
    # 尝试启用多重采样抗锯齿
    try:
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4)
    except:
        print("多重采样不可用")
    
    # 创建窗口（无边框）
    screen = pygame.display.set_mode(display, pygame.DOUBLEBUF | pygame.OPENGL | pygame.NOFRAME)
    pygame.display.set_caption("Live2D Transparent Window")
    
    # 初始化OpenGL和Live2D
    live2d.glewInit()
    
    # OpenGL设置
    try:
        # 清除错误
        while gl.glGetError() != gl.GL_NO_ERROR:
            pass
        
        # 设置视口
        gl.glViewport(0, 0, window_width, window_height)
        
        # 设置投影矩阵
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, window_width, window_height, 0, -1, 1)
        
        # 设置模型视图矩阵
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        
        # 启用混合
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        
        # 启用抗锯齿
        try:
            gl.glEnable(gl.GL_MULTISAMPLE)
            gl.glEnable(gl.GL_LINE_SMOOTH)
            gl.glHint(gl.GL_LINE_SMOOTH_HINT, gl.GL_NICEST)
            gl.glEnable(gl.GL_POLYGON_SMOOTH)
            gl.glHint(gl.GL_POLYGON_SMOOTH_HINT, gl.GL_NICEST)
        except:
            pass
        
        # 禁用不需要的功能
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_LIGHTING)
        
        print("OpenGL设置完成")
    except Exception as e:
        print(f"OpenGL设置错误: {e}")

    # 创建并加载Live2D模型
    model = live2d.LAppModel()
    
    # 查找模型文件
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

    model.Resize(window_width, window_height)
    
    # 游戏变量
    clock = pygame.time.Clock()
    running = True
    model_scale = 1.0
    dragging = False
    drag_offset = (0, 0)
    
    # 视角跟随变量
    eye_tracking_enabled = True
    
    while running:
        # 处理事件
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
                    # R键重置模型缩放
                    model_scale = 1.0
                    model.SetScale(model_scale)
                elif event.key == pygame.K_t:
                    # T键切换视角跟随
                    eye_tracking_enabled = not eye_tracking_enabled
                    print(f"Eye tracking: {'Enabled' if eye_tracking_enabled else 'Disabled'}")
            
            elif event.type == pygame.MOUSEWHEEL:
                # 滚轮缩放模型
                mouse_x, mouse_y = pygame.mouse.get_pos()
                
                # 检查鼠标是否在模型上
                try:
                    if model.HitTest("Body", mouse_x, mouse_y) or model.HitTest("Head", mouse_x, mouse_y):
                        scale_factor = 1.05 if event.y > 0 else 0.95
                        model_scale *= scale_factor
                        model_scale = max(0.3, min(3.0, model_scale))
                        model.SetScale(model_scale)
                        print(f"Model scale: {model_scale:.2f}")
                except Exception as e:
                    print(f"Wheel event error: {e}")
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # 左键 - 点击功能
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    
                    try:
                        # 检查点击的部位
                        if part_ids := model.HitPart(mouse_x, mouse_y):
                            print(f"Clicked parts: {part_ids}")
                        
                        # 先检查头部，再检查身体
                        if model.HitTest("Head", mouse_x, mouse_y):
                            model.SetRandomExpression()
                            print("Clicked Head - Random Expression")
                        elif model.HitTest("Body", mouse_x, mouse_y):
                            model.StartRandomMotion("TapBody", 3)
                            print("Clicked Body - Random Motion")
                    except Exception as e:
                        print(f"Hit test error: {e}")
                
                elif event.button == 3:  # 右键 - 开始拖拽
                    # 简单的拖拽实现（需要手动移动窗口）
                    dragging = True
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    drag_offset = (mouse_x, mouse_y)
                    print("右键拖拽开始（请手动移动窗口）")
            
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 3:  # 右键释放
                    dragging = False
                    print("右键拖拽结束")
        
        # 视角跟随（全局鼠标位置）
        if eye_tracking_enabled:
            try:
                # 获取鼠标位置（相对于屏幕）
                mouse_x, mouse_y = pygame.mouse.get_pos()
                
                # 转换为Live2D坐标系
                look_x = (mouse_x / window_width) * 2.0 - 1.0
                look_y = -((mouse_y / window_height) * 2.0 - 1.0)
                
                # 限制范围
                look_x = max(-1.0, min(1.0, look_x))
                look_y = max(-1.0, min(1.0, look_y))
                
                # 设置参数
                model.SetParameterValue("ParamAngleX", look_x * 30)
                model.SetParameterValue("ParamAngleY", look_y * 30)
                model.SetParameterValue("ParamEyeBallX", look_x)
                model.SetParameterValue("ParamEyeBallY", look_y)
            except Exception as e:
                pass
        
        # 渲染
        try:
            # 清除背景为完全透明
            gl.glClearColor(0.0, 0.0, 0.0, 0.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            
            # 重置矩阵
            gl.glMatrixMode(gl.GL_MODELVIEW)
            gl.glLoadIdentity()
            
            # 更新和绘制模型
            model.Update()
            model.Draw()
            
        except Exception as e:
            print(f"渲染错误: {e}")
        
        # 刷新显示
        pygame.display.flip()
        clock.tick(60)  # 60 FPS
    
    # 清理
    live2d.dispose()
    pygame.quit()

if __name__ == "__main__":
    main()
