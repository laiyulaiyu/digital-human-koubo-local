# 本地 ComfyUI 分支

基于原仓库 5fa9b19f52fb8920c83567468fa30e8391b8c503 改造。保留 templates/、kit/、assemble.py、align.py、voicefx/，只替换生成后端并适配 Windows 路径、编码与本地 ASR。没有复制另一套剪辑引擎。

本轮端到端实测范围是 B 竖屏模板 templates/huazi-916；A/C/D/E 的原实现保留，尚未逐一实测。样片的 H3 生成源为448×800，原模板输出1080×1920属于放大输出。

## 配置

推荐先运行随仓库提供的 scripts/configure.py，生成本机config/local.json；也可复制local.example.json后修改，或用 --config / DH_LOCAL_CONFIG 指定配置。workspace 是所有结果及任务记录的根目录。runner默认使用本仓库scripts/local_media.py，templates使用本仓库workflows目录；六份原生API工作流已包含，无需其他项目的Skill。相对路径按配置文件所在目录解析。执行器保留已验证的提交、续查及校验机制，未另造剪辑引擎。

本机需要已有 ComfyUI H3 模型/工作流、Python、ffmpeg/ffprobe、Node/npm 以及本地 ASR 模型。ASR 默认搜索已缓存 faster-whisper 大模型与 Whisper medium/small/base；也可设置 DH_ASR_MODEL 为模型目录、.pt 文件或 whisper.cpp .bin（后者需要 whisper-cli）。不自动下载模型。ASR 使用 CPU，H3 使用 GPU；不要并发多个 GPU 任务。

configure的 --asr-model 会写入本机配置，finish_local据此设置ASR后端。旧的 --config 外部执行器路径仍兼容，但发布版默认不依赖它。安装及模型来源从仓库根README进入。

## 从原文到原模板

以下命令中的 python 指安装了本仓库requirements的CLI解释器；配置里的python只用于启动已有ComfyUI。Windows根README用$PY明确指定CLI虚拟环境。统一使用-X utf8。先设定绝对脚本目录$S，然后在项目目录运行。保持script.json、tasks.json、ids.json、cut/及edit/属于同一个项目。

```powershell
$S = '<原仓库>/skills/digital-human-koubo/scripts'
python -X utf8 "$S/build_tasks.py" script.json tasks.json --config '<本地配置绝对路径>'
python -X utf8 "$S/local_backend.py" run tasks.json --only s1
# 检查第一段的实际音频、口型、画面后再生成剩余段
python -X utf8 "$S/local_backend.py" run tasks.json --only s2
# 所有生成完成且本项目队列空闲后，释放本项目服务，给 CPU ASR 留出内存
python -X utf8 '<配置中 runner 的路径>' --config '<本地配置绝对路径>' server stop
python -X utf8 "$S/new_edit.py" huazi-916 edit
python -X utf8 "$S/assemble.py" script.json ids.json --out edit/public/main.mp4
python -X utf8 "$S/align.py" script.json --out edit/src/tl.json
python -X utf8 "$S/voicefx/unify.py" voice cut/s1.mp4 cut/s2.mp4
# 用 ffmpeg 按段顺序拼接 voice/*.wav 到 edit/public/voice.wav；主视频轨保持 muted
# 按 references/huazi.md 编写 edit/src/edit.json，保留 AI 标识
python -X utf8 "$S/check_edit.py" edit/src
cd edit
npx remotion render src/index.ts Huazi final.mp4 --concurrency=1 --gl=swangle
```

无需生成新模板，new_edit.py 是原 new_edit.sh 的跨平台版本。已有 src/ 会拒绝覆盖；安装失败后可在 edit/ 内重试 npm install。--skip-install 仅复制原模板并生成原音效/占位配乐，之后仍需安装原 package.json 的依赖。

32GB 内存机器上，H3 的 CPU 卸载权重会与本地 ASR 争用内存。生成完后调用原执行器的 server stop，它只会停止有本项目归属记录且队列空闲的服务。勿结束其他项目的进程。Remotion 使用并发1和软件图形后端，沿用原模板的画面实现。

完成原模板初始化并写好 edit.json 后，也可用 `python -X utf8 "$S/finish_local.py" <项目目录>` 依次调用上面的原 assemble/align/voicefx/check_edit 脚本，按 script.json 的顺序拼接处理后的人声，并检查音画与时间轴时长一致。它不替代任何剪辑实现，也不会启动渲染或跳过低分 ASR。

## 本地脚本字段

```json
[
  {
    "id": "s1",
    "t": "人工智能说得流畅，不等于说得正确。",
    "seconds": 6,
    "first": "assets/presenter.png",
    "width": 448,
    "height": 800,
    "seed": 27411,
    "turbo": false
  }
]
```

- id 唯一且仅字母、数字、下划线、连字符。seconds 必须显式 4–15 秒，H3 帧数按原执行器对齐；实际时长写进清单。width/height 是 32 的倍数。
- first 为相对 script.json 的本地首帧图；不接受云端素材 ID/URL。默认 I2VA 提示词完整保留 t 的台词，静态镜头，原生人声，不生成字幕。
- 使用 refs 时必须提供符合 Ref2VA 格式的 prompt，不把 I2VA 提示词错误套用。first 与 refs 互斥。
- 可选 voice、lang 改变提示词，lang_code 指定 ASR 语言；H3 没有锁定说话人的音色嵌入，多段音色一致性必须实测。原 unify 仅统一频谱和空间感，不保证声纹完全相同。
- turbo=false 为普通 20 步；true 使用已有 H3 加速 LoRA。增加动作/人物/风格LoRA时先核对模型卡，不默认与加速LoRA叠加。需要新拍时修改 seed 并重建清单，不覆盖旧任务档案。

## 续跑、质量和成本

local_backend.py 会在提交前保存 ids.json 中的 job_id。重跑同一清单会按输入哈希查找/续查任务；--dry-run 只准备工作流，不提交、不产生样片。不要删除 runtime/jobs，也不要将提交状态不明的任务重新创建。断点未知时遵循原执行器的失败信息核查队列。

本地没有 Renoise 积分，仍有硬件运行时间、电费和模型的授权条件；不声称无限免费。不要在失败时自动切换收费服务。

生成后必须有原生音轨且通过执行器的解码检查。assemble.py 用实际 ASR 比对文稿，低于 85% 会暂停；低分需核对真实音频并重拍，不用预期稿诱导 ASR。--allow-low-asr 只能在真实复核后显式使用。align.py 保持原逐字时间轴格式，插值仅用于少量识别差异；不是精确音素强制对齐。

抽看每段至少四帧以及段间和包装中间帧，核查烧字、口部、人脸、转场、字幕遮挡。ASR 通过不代表口型和听感通过。交付应同时列出原始片段、cut/qa.json、时间轴、包装成片及尚需人工试听的限制。

## 口播节奏与动作 LoRA

用户希望看到肢体动作时，参考首帧应改成头至腰/大腿的中景，完整显示双手及手势空间。保持静态镜头，让动作来自H3生成，包装的punch设为空以便审核真实动作。

script.json 可增加按台词顺序排列的 `gestures` 和模型专属 `loras`：

```json
{
  "gestures": [
    {"on": "先看来源", "action": "opens her right palm upward at waist level"},
    {"on": "再看证据", "action": "opens her left palm while relaxing the right hand"}
  ],
  "loras": [{"name": "better_motion_h3_lora_v1_500.safetensors", "strength": 0.5}]
}
```

on 必须在台词中出现且按顺序排列。默认提示词将手势绑定到这些话语，停顿时收势；自定义prompt时由其自行描述动作。LoRA增强动作先验，不提供确定性的逐拍控制。先用实际ASR定位台词，再抽看对应动作与停顿，不能把加载成功当作节奏同步通过。

需要保留说完后手势收回的过程时，可在该段设置 `keep_full: true`，assemble保留整段并对齐30fps帧边界。普通口播默认仍保留到说完后0.25秒。

LoRA放在配置的comfy_root/models/loras内，name支持子目录，不接受越界路径。原生LoraLoaderModelOnly串接到已有H3模型，同时更新guider和scheduler。清单记录文件SHA256及权重，执行时复核；改变文件或权重会改变任务身份。续跑使用local_backend.py run清单，保留审核记录。

可选的真人写实示例为仓库 `examples/gesture/script-realism.json`：保留动作 LoRA 0.5，增加 H3 写实 LoRA 0.7，并在实际视频提示词中包含作者指定触发词 `r34l1sm`。模型版本、校验码与许可见 `docs/MODELS.md`。可将整个 `examples/gesture` 复制到一个**新的**工作目录，将该文件作为 `build_tasks.py` 的输入，再按正常本地流程运行；不要覆盖此前样片。模型加载成功只证明流程接通，画面、动作、字幕和实际语音仍需人工审看。原版 B/C/D/E 剪辑风格与 LoRA 是不同层次的选择，按内容分别设置。

已选人体动作模型的作者说明：https://huggingface.co/vpakarinen/better-human-motion-h3-lora ，建议0.4–0.8、20–30步；本轮首测0.5/20步。没有验证它与Turbo叠加的质量，不默认把动作LoRA叠到加速流程上。其他基础模型的LoRA不能直接通用。

## 原云端兼容（显式选择）

显式 --backend renoise 仍输出原 Grok 任务数组，后续继续原 MCP/下载流程及费用确认。旧 ids.json 的整数 taskId 仍可由 assemble.py 读取。本地默认不需要 Renoise 连接、账号余额或 persona.json 中作者的素材 ID。
