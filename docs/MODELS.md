# 模型准备

权重不随代码包分发。请在模型作者/分发者页面核对适用许可与版本，下载到已有ComfyUI的models目录。仓库提供的是API工作流；如使用其他精度或同系列不同文件名，需要同步调整工作流中的loader字段。

## H3 首帧口播（必需）

来源：[Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main)。

| ComfyUI子目录 | 工作流默认文件名 |
|---|---|
| models/diffusion_models | minimax_h3_fl2va_pruned_int8_convrot.safetensors |
| models/text_encoders | qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors |
| models/vae | minimax_h3_video_vae_fp16.safetensors |
| models/vae | minimax_h3_audio_vae_fp32.safetensors |

## 可选功能

- 首帧Turbo8步：同一Comfy-Org模型仓库的 `loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`。
- Ref2VA：同一仓库的 `diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors`，以及可选 `loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`。Ref2VA尚未纳入本轮端到端验收。
- 人体动作LoRA：[vpakarinen/better-human-motion-h3-lora](https://huggingface.co/vpakarinen/better-human-motion-h3-lora)，文件 `better_motion_h3_lora_v1_500.safetensors` 放models/loras。本轮固定版本df545ebfbdaf30799196098f6df157ee4388b766，SHA256为 `285f9ed3fbb735c3625fca0d22166c7450ad7acb552a869fcbbd8e86e79d1f4c`，首帧普通20步、权重0.5。没有验证与Turbo叠加。
- Qwen参考图：[Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main) 提供工作流使用的 `diffusion_models/qwen_image_2.1_int8_convrot.safetensors` 和 `vae/qwen_image_2.1_vae_bf16.safetensors`。本轮文本编码器为 [Stick9190/qwen3vl_8b_int8_convrot](https://huggingface.co/Stick9190/qwen3vl_8b_int8_convrot) 的 `qwen3vl_8b_int8_convrot.safetensors`，放models/text_encoders。Qwen为可选；使用自己的首帧图时无需安装Qwen模型。
- ASR：[Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) 的完整本地模型目录，或已缓存的medium/small/base；本轮实际使用large-v3、CPU int8。执行器不自动下载ASR模型。Whisper .pt及whisper.cpp .bin路径也保留兼容，分别需自行安装相应后端。

`doctor` 从随仓库提供的工作流读取实际需要的模型名并检查文件存在；它不承诺只凭文件名即可判断权重完整，重要下载建议自行核对作者的SHA256。
