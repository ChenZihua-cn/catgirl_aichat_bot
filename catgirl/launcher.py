#!/usr/bin/env python3
"""
猫娘桌面助手启动器
自动检查环境并启动应用
"""

import os
import sys
import webbrowser
import subprocess
import time
import json
from pathlib import Path

class CatgirlLauncher:
    def __init__(self):
        self.ollama_running = False
        self.required_models = ['llama2', 'mistral']
        self.available_models = []
        
    def check_ollama(self):
        """检查Ollama是否正在运行"""
        print("🔍 检查Ollama服务状态...")
        try:
            import requests
            response = requests.get('http://localhost:11434/api/tags', timeout=5)
            if response.status_code == 200:
                self.ollama_running = True
                print("✅ Ollama服务正在运行")
                return True
        except:
            pass
        
        print("❌ Ollama服务未启动")
        return False
    
    def start_ollama(self):
        """启动Ollama服务"""
        print("🚀 正在启动Ollama服务...")
        try:
            # 尝试启动Ollama（在后台运行）
            if os.name == 'nt':  # Windows
                subprocess.Popen(['ollama', 'serve'], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
            else:  # Unix/Linux/Mac
                subprocess.Popen(['ollama', 'serve'], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL,
                               preexec_fn=os.setsid)
            
            # 等待服务启动
            print("⏳ 等待Ollama服务启动...")
            for i in range(30):
                if self.check_ollama():
                    return True
                time.sleep(1)
            
            print("❌ Ollama服务启动超时")
            return False
            
        except Exception as e:
            print(f"❌ 启动Ollama失败: {e}")
            return False
    
    def check_models(self):
        """检查必需的模型是否已下载"""
        print("📦 检查AI模型...")
        try:
            import requests
            response = requests.get('http://localhost:11434/api/tags')
            if response.status_code == 200:
                data = response.json()
                self.available_models = [model['name'] for model in data.get('models', [])]
                print(f"✅ 已安装模型: {', '.join(self.available_models)}")
                
                missing_models = []
                for model in self.required_models:
                    if model not in self.available_models:
                        missing_models.append(model)
                
                if missing_models:
                    print(f"⚠️  缺少模型: {', '.join(missing_models)}")
                    return False
                
                print("✅ 所有必需模型已安装")
                return True
        except Exception as e:
            print(f"❌ 检查模型失败: {e}")
        
        return False
    
    def download_model(self, model_name):
        """下载指定的模型"""
        print(f"📥 正在下载模型 {model_name}...")
        try:
            result = subprocess.run(['ollama', 'pull', model_name], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✅ 模型 {model_name} 下载完成")
                return True
            else:
                print(f"❌ 下载模型 {model_name} 失败: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ 下载模型 {model_name} 失败: {e}")
            return False
    
    def download_missing_models(self):
        """下载所有缺少的模型"""
        missing_models = []
        for model in self.required_models:
            if model not in self.available_models:
                missing_models.append(model)
        
        if not missing_models:
            return True
        
        print(f"🚀 开始下载 {len(missing_models)} 个缺少的模型...")
        success_count = 0
        
        for model in missing_models:
            if self.download_model(model):
                success_count += 1
        
        if success_count == len(missing_models):
            print("✅ 所有模型下载完成")
            return True
        else:
            print(f"⚠️  部分模型下载失败 ({success_count}/{len(missing_models)})")
            return False
    
    def create_settings(self):
        """创建默认设置文件"""
        settings = {
            "themeColor": "#ec4899",
            "opacity": 80,
            "fontSize": 14,
            "animation": True,
            "personality": "cute",
            "autoHide": False,
            "autoHideDelay": 30,
            "sound": True,
            "volume": 50,
            "ollamaUrl": "http://localhost:11434",
            "defaultModel": "llama2",
            "hardwareAccel": True,
            "memoryLimit": 512
        }
        
        settings_file = Path('settings.json')
        if not settings_file.exists():
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            print("✅ 创建默认设置文件")
    
    def launch_app(self):
        """启动应用"""
        print("🌟 准备启动猫娘桌面助手...")
        
        # 检查index.html是否存在
        if not os.path.exists('index.html'):
            print("❌ 找不到 index.html 文件")
            return False
        
        # 创建默认设置
        self.create_settings()
        
        # 启动应用
        app_url = f'file://{os.path.abspath("index.html")}'
        print(f"🚀 启动应用: {app_url}")
        
        try:
            webbrowser.open(app_url)
            print("✅ 应用已启动！")
            return True
        except Exception as e:
            print(f"❌ 启动应用失败: {e}")
            return False
    
    def run(self):
        """主运行流程"""
        print("🐱 猫娘桌面助手启动器")
        print("=" * 50)
        
        # 检查Ollama
        if not self.check_ollama():
            if not self.start_ollama():
                print("❌ 无法启动Ollama服务，请手动启动后重试")
                print("💡 提示: 在终端运行 'ollama serve'")
                return
        
        # 检查模型
        if not self.check_models():
            if not self.download_missing_models():
                print("⚠️  部分模型下载失败，但仍可继续使用")
        
        # 启动应用
        if self.launch_app():
            print("\n🎉 猫娘桌面助手启动成功！")
            print("💡 提示: 按 Ctrl+M 可以快速打开/关闭聊天窗口")
            print("⚙️  设置: 点击控制菜单中的设置按钮进行个性化配置")
        else:
            print("❌ 应用启动失败")

if __name__ == "__main__":
    try:
        launcher = CatgirlLauncher()
        launcher.run()
    except KeyboardInterrupt:
        print("\n👋 用户取消操作")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
    
    input("\n按 Enter 键退出...")