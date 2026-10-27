---
name: digital-human-koubo
description: 数字人口播视频：默认使用本机 ComfyUI MiniMax H3 和本地参考图生成带原声的分段视频，复用原仓库的语音核对、逐字对齐、声音统一与 Remotion 模板和包装组件。也保留显式选择的 Renoise 云端生成。适用于科技解读、教程、评论、花字、卡片、地图、弹幕等数字人口播制作；本地配置与运行方法见 references/local-comfyui.md。
---

# 数字人口播

这是上游 digital-human-koubo 的本地化改造。默认走 `references/local-comfyui.md`：本地参考图 → ComfyUI H3 原声口播 → 原仓库 assemble / align / voicefx → 原 Remotion 模板与包装组件。不要另造一套剪辑引擎。

本地生成参数写入 script.json，路径和运行环境写入 config/local.json（从 local.example.json 复制，或用 --config 指定）。原 persona.json 中的云端素材 ID、Grok 语速和计费参数仅用于显式 --backend renoise。剪辑风格继续按 `references/style-menu.md`。用户已确认的风格和实施范围直接沿用。

口播肢体动作与LoRA：按 local-comfyui.md 的对应章节配置 gestures / loras；使用双手可见的中景，把动作绑定到台词短语和停顿，再按实际ASR时间检查。手势来自生成视频本身，继续复用原剪辑模板。

## 红线
- 本地流程不调用 Renoise，不查询余额，不上传参考图；先做一段检查语音与口型，保留原声和任务记录。新增LoRA先核实H3兼容性与来源，记录文件哈希和强度，用真实短片验证。
- 仅显式选择 Renoise 云端时：create_tasks 之前先报「段数 · 秒数 · 预估 credits · 余额」，等用户在对话里明确同意。重拍也要先报价。
- 成片标「内容由 AI 数字人演绎」；场景、动物片段角上标「AI 生成」。
- 用户本人的形象（persona.json → other_hosts.me）只用在用户自己的片子里。
- 「小林式」只学结构和剪辑手法：不用真实创作者的脸、声音、布景和原句。
- 点名评价第三方产品的说法，要有出处或标「网友分析 / 个人体验」。展示素材只用用户自己的作品；带歌词字幕的片子不用。

## 流程

### 准备：先检查，有就跳过，缺才引导安装（每次新对话第一次用时做）
**默认本地分支**：先读 `references/local-comfyui.md`，检查配置中的已有 Python、ffmpeg、Node、ComfyUI 模型及本地 ASR 缓存，不重复安装。Windows 用 `python -X utf8 scripts/new_edit.py` 复用模板。显存任务串行，勿中断其他项目的服务或队列。下面 Renoise 的安装、余额和素材 ID 检查仅用于用户显式选择云端的情况。
**原则：已经装好的一句话带过，不让用户重装；缺什么才给装法，装法给多种，先放用户当前用的那种。** 详细装法在 references/install.md。
1. **Renoise MCP**：直接调 `get_account`。
   - 成功 → 只说一句「Renoise 已连接，余额 X 积分」，接着干活。
   - 工具不存在 / 未连接 → 停下引导安装。用户还没有 Renoise 账号时，注册链接一律给 https://renoise.ai/mcp?utm_medium=xcom&utm_source=official（原样给出，保留 utm 追踪参数，不要改写成 renoise.ai 首页）。然后把用户当前客户端的装法放第一个并标「推荐」，下面列出其他方式（Claude 桌面端/网页连接器、Claude Code 插件、Codex `codex mcp add`、OpenClaw、Cursor 等通用远程 MCP 配置、renoise.ai/plugin 官网），让用户自己挑。装完让用户重开对话或重连，再调一次确认。
   - 报工具被关闭 → 不是没装，让用户去连接器设置里打开；报授权过期 → 重新登录授权，不用重装。
2. **本机环境**（要剪辑时才需要）：`bash scripts/doctor.sh`。有的打 ✓ 不提；缺的它会按 macOS / Windows / Linux 列出多种装法。系统软件让用户自己装，Python 包可以在用户同意后帮装。
3. **数字人形象**：persona.json 的 reference_material 能用就直接用；当前账号用不了（换了账号、素材过期、别人的包）→ 按 references/new-avatar.md 用用户自己的照片重做。

### 0. 看内容 → 推荐风格 → 让用户选
按 `references/style-menu.md`：
1. 一行诊断（内容类型、有没有可展示的素材、适合的平台和时长）。
2. 推荐 2 个风格并说理由，把 `assets/styles/` 里对应的预览图发给用户。
3. 一次问完：风格 · 比例和时长 · 花字强度（克制 / 标准 / 热闹）· 主播（白背心 / 用户本人 / 两人接力 / 动物）。每题第一个选项是推荐项。Claude Code 用 AskUserQuestion，其他工具列编号。
4. 用户回「你定」就按推荐，并说一句按了什么。结果写进 `brief.json`，后面每一步按它来。

| 风格 | 比例 | 时长 | 剪辑实现 |
|---|---|---|---|
| A 小林式解说 | 16:9 | 3–20 分钟 | finance-explainer skill 的引擎（episode.json 拍表） |
| B 网红花字口播 | 9:16 | 30–120 秒 | `templates/huazi-916`（edit.json 驱动，三档花字） |
| C 发布解读 | 16:9 | 30–90 秒 | 参考实现 `templates/reference/launch-169` |
| D 保姆级教程 | 16:9 | 3–8 分钟 | 参考实现 `templates/reference/tutorial-169` |
| E 多主播多语言 | 16:9 | 3–7 分钟 | 参考实现 `templates/reference/multihost-169` |

### 1. 写稿 → script.json
本地 H3：每段显式写 seconds（4–15 秒）、first 本地图、seed、width/height；示例和校验见 local-comfyui.md。不要用 Grok 的 5.4 字/秒推导 H3 台词容量。下段的 Grok 经验仅供云端分支。
按选定风格的稿子写法（style-menu.md 里每种都有）。每段一句或两句，10 秒左右（约 40–55 字，Grok 中文约 5.4 字/秒），标 `shot`：`full`（全屏出镜）/ `pip`（画中画讲解）/ `vlog`（随意自拍口吻）/ `depth`（要做「文字在人身后」的段：中景、头顶两侧留背景）。英文缩写、网址写成好念的样子。外语段直接写目标语言的台词。

### 2. 切段 + 报价
本地：`python -X utf8 scripts/build_tasks.py script.json tasks.json --config <本地配置>`。默认生成本地清单，打印段数和实际帧数对应时长，无 Renoise 积分。以下计价说明只用于加 `--backend renoise` 的云端清单。
`python3 scripts/build_tasks.py script.json tasks.json --purpose "teaching a beginner tutorial step by step"`
→ 打印段数、秒数、预估 credits。full 段 720p（17/秒），pip 段 480p（10/秒）。拿 `estimate_cost` 核一次，报给用户等确认。用户本人或动物主播用 persona.json → other_hosts 里的提示词模板。

### 3. 生成
本地：`python -X utf8 scripts/local_backend.py run tasks.json --only s1`。检查首段后运行剩余段。重新执行同一命令续查已有任务，不重复提交；改变 seed 才是新拍摄。保留 ids.json 和 runtime/jobs。参考图由本机 Qwen 工作流提供。以下 create_tasks 仅属云端分支。
tasks.json 每 10 个一批 create_tasks → wait_tasks。要进场景（直播间、门店、街景）时先用 GPT Image 2.5 合成开场画面（人物参考图 + 场景描述，2k 约 23 积分），再把这张图当 Grok 的参考图。

### 4. 下载（Renoise 美国 CDN 很慢，必须这样下）
本地不下载 CDN：执行器已校验并保存原声 mp4；ids.json 的本地条目含 path、job_id、state。只有 succeeded 可进入拼接。下面下载器保留给云端。
download_results 拿链接 → 整理成 `urls.txt`（每行 `<taskId>.<ext> <url>`）→ `python3 scripts/rangedl.py`：每个文件 6 段 Range 并发、断点续传、下完 ffmpeg 解码校验。

### 5. 回听 + 抽帧 + 拼接
本地同样运行下方原 assemble.py，自动选用已缓存的本地 ASR（CPU）并转换成原对齐格式；`DH_ASR_MODEL` 可指定路径。不向 ASR 输入预期台词。低于 85% 的段暂停拼接，先核对真实音频，不把 ASR 相似度当作口型或听感通过。输出 cut/qa.json。
`python3 scripts/assemble.py script.json ids.json --out 成片_完整版.mp4`（ids.json = {段 id: taskId}）：whisper 逐段转写比对文稿、只保留到说完后 0.25 秒、拼接、loudnorm -16。
- whisper `--prompt 原文` 会让个别段漏掉前半句，用中性提示「以下是普通话的句子。」。外语段按语言转写；日韩阿拉伯语不要加 `-ml 1`（会把多字节字符截断成乱码）。
- **每段抽 4 帧看一眼**：Grok 横屏口播偶尔自己烧字幕（提示词写了也挡不住），有就重拍那段。
- Grok 有时漏念开头的语气词：没影响意思就按实际口播改字幕，别为这个重拍。

### 6. 对齐 + 剪辑
本地 Windows 用 `python -X utf8 scripts/new_edit.py huazi-916 <工程>`，其余仍用原 align.py / check_edit.py / voicefx 和模板。`new_edit.sh` 保留给原平台。不要用估计的字时长代替实测 ASR 对齐。
`python3 scripts/align.py script.json --out <工程>/src/tl.json` 出逐字时间轴，然后按 brief.json 的风格剪：
- **B 花字口播**：`bash scripts/new_edit.sh huazi-916 <工程>` → 写 `src/edit.json`（关键词、表情、卡片、作品展示、号召，字段见 references/huazi.md）→ `python3 scripts/check_edit.py <工程>/src` → 抽帧 → 渲染。
- **A 小林式**：`bash ~/.claude/skills/finance-explainer/scripts/setup_engine.sh <工程>`，按那边的拍表和画面语法做；数字人口播片段放进 host.json。
- **C / D / E**：`bash scripts/new_edit.sh reference/<目录> <工程>`，换 tl.json，按段重写 Scene（templates/reference/README.md）。
- **包装（每种风格都做）**：按 `references/packaging-presets.json` 里这个风格的默认包装排——开场 30 秒按 open 顺序、正文保证 stimulus_every_s 秒内有一个新视觉事件、讲到 per_beat 里那类内容就用对应组件、recurring 全片挂着。组件写进 `pack` 数组（字段见 references/packaging.md），手法依据见 references/packaging-playbook.md。用户点名要的手法（「加地图」「开场加预告」「加弹幕」「换成 MrBeast 那种」）在默认基础上加减。用户问「有哪些包装」先发 `assets/packaging/图鉴.jpg`。景深字（文字在人身后）要先跑 `scripts/cutout_video.py` 抠像，见 references/packaging.md。
- 声音：数字人视频轨一定 `muted`，人声单独铺一条；多段 Grok 原声用 `python3 scripts/voicefx/unify.py <输出目录> <片段…>` 统一频谱 + 同一个小房间混响（复用旧段时加 `--ref 旧片段目录`，场景/动物片段加 `--scene`）。BGM 压在人声下约 20 dB。
- 抽帧检查一定看过渡的中间帧和零间隔衔接处（上一条的尾巴会盖住下一条）。

## 参考
- references/install.md：Renoise MCP 和本机环境的多种装法（只在缺的时候用）
- references/style-menu.md：五种风格、内容诊断、怎么问用户、brief.json
- references/packaging.md：47 个包装组件的用法和参数（pack 写法、9:16 自动适配）
- references/packaging-playbook.md：头部博主实测结论（节奏、开场公式、字幕、声音、号召、红线），完整报告在 references/research/
- references/packaging-presets.json：五种风格各自的默认包装
- references/huazi.md：花字模板 edit.json 字段、九种卡片、三档强度、写法习惯
- persona.json：白背心数字人 + 其他主播（用户本人、橘猫店长、柴犬主播）、提示词模板、动作库、多语言实测
- references/voice.md：换声音（MiMo 克隆 / 音色设计）
- references/new-avatar.md：从一张照片做新形象
- references/edit-styles.md：各剪辑工程的入口文件和声音统一做法
- assets/styles/：五种风格的预览图（给用户选的时候发）
- assets/packaging/：包装组件图鉴（47 格总览 + 每个组件一张）
