# 🐱 猫娘桌面助手

![猫娘桌面助手](ee.png)

一个可爱的猫娘桌面AI助手，集成Ollama模型，支持个性化定制和模型微调。

## 项目愿景

创建一个可爱的猫娘桌面助手，能够在Windows 11桌面上以聊天气泡的形式与用户进行智能对话，支持Ollama模型微调和个性化定制。

## 模型说明

本项目使用HuggingFace上的GGUF格式的语言模型，具体信息如下：

- **模型名称**：L3.1-DeepSeek-8B-DrkIdl-Instruct-1.2-Uncensored-D_AU-Q4_k_m.gguf
- **模型路径**：`model/`目录下
- **模型特点**：基于DeepSeek 8B模型，经过优化和微调，支持高质量的对话生成
- **模型大小**：约4.7GB
- **使用方式**：通过Ollama框架加载和运行
- **数据集引用**: 引用自[NekoQA-10k](https://huggingface.co/datasets/liumindmind/NekoQA-10K/tree/main)

## 模型下载

由于GGUF模型文件较大，已添加到`.gitignore`中，不会被提交到版本控制系统。请按以下步骤下载模型：

1. 访问HuggingFace模型页面（具体链接请查看项目文档或联系维护者）
2. 下载`L3.1-DeepSeek-8B-DrkIdl-Instruct-1.2-Uncensored-D_AU-Q4_k_m.gguf`文件
3. 将下载的文件放置在项目的`model/`目录下
4. 确保文件名与上述模型名称完全一致

## 注意事项

- GGUF模型文件较大（约4.7GB），已添加到`.gitignore`中，不会被提交到版本控制系统
- 首次运行时，系统会自动加载模型，可能需要一些时间
- 建议在性能较好的设备上运行，以获得最佳体验
