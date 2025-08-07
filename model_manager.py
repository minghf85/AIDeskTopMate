import os

class Live2DModelManager:
    def __init__(self):
        self.model_paths = {}
        self.current_model = None
        self.scan_models_directory()

    def scan_models_directory(self, base_path="."):
        """扫描目录下的所有Live2D模型文件"""
        for root, _, files in os.walk(base_path):
            for file in files:
                if file.endswith(('.model3.json', '.model.json')):
                    model_path = os.path.join(root, file)
                    model_name = os.path.splitext(os.path.basename(file))[0]
                    self.model_paths[model_name] = model_path

    def get_available_models(self):
        """获取所有可用的模型列表"""
        return list(self.model_paths.keys())

    def get_model_path(self, model_name):
        """获取指定模型的路径"""
        return self.model_paths.get(model_name)

    def register_model(self, model_name, model_path):
        """注册新的模型"""
        if os.path.exists(model_path):
            self.model_paths[model_name] = model_path
            return True
        return False
