# PicMotion · 极简画影

> 跑在本地的 ComfyUI 极简中文界面：**写中文 → 点「生成」→ 出图 / 出视频**。
> 不联网、不要 API key、不注册账号，全部在你自己的机器上完成。

![PicMotion Logo](logo.png)

---

## English

**PicMotion** (Chinese name: **极简画影**) is a minimal, Chinese-first web interface that sits on
top of a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) installation. Type a prompt in
Chinese, press one button, and get an image or a short video. There is no cloud service, no API key
and no account — everything runs offline on your own machine.

### Features

- **Text-to-image** and **image-to-image**
- **Structure-guided generation** via ControlNet: Canny, Depth, OpenPose, LineArt, Scribble
- **Outpainting** to extend the canvas or complete a cropped subject
- **Two-pass high-resolution mode** (latent upscale + a second sampler pass)
- **Automatic Chinese → English prompt translation**
- **Built-in, configurable content moderation rules**
- **Preview-first workflow** — results land in a preview cache, you click to save
- **Text-to-video / image-to-video** (Wan 2.2 5B TI2V)

### Quick Start

```text
<parent folder>/
├── ComfyUI-aki-v3.2/      # your ComfyUI installation
└── simple-ui/             # this repository
```

1. Place this repository next to your ComfyUI folder (same parent directory) so it can be
   auto-detected. If it lives elsewhere, point the app at your ComfyUI root via `config.json`
   (copy `config.example.json`) or the `PICMOTION_COMFY_ROOT` environment variable.
2. Requirements: the Python bundled with ComfyUI, with **Pillow**. Nothing else — the UI server
   uses the Python standard library only.
3. Make sure ComfyUI is runnable (the app can start it for you on first use).
4. Double-click `start-app.bat` — it starts the local service and opens a standalone app window.
5. Type a Chinese prompt and press **生成** (Generate).

The user interface itself is in Chinese. The UI service listens on `127.0.0.1:8899`; ComfyUI must
be reachable on `127.0.0.1:8188`.

---

## 目录

- [这是什么](#这是什么)
- [工作原理](#工作原理一句话)
- [特性](#特性)
- [环境与前置条件](#环境与前置条件)
- [安装](#安装)
- [使用说明](#使用说明)
- [配置](#配置)
- [常见问题](#常见问题)
- [目录结构](#目录结构)
- [相关文档](#相关文档)
- [License](#license)

---

## 这是什么

一个**单文件服务 + 单页界面**的极简外壳，把 ComfyUI 的强大能力包装成「写一句话、点一下」的体验。

它自己**不做任何 AI 推理**：所有生成都由本地 ComfyUI 完成，本仓库负责中文输入 → 英文提示词、
参数预设、工作流组装、安全检测、以及结果的预览与保存。

设计取向是**绿色、免依赖、可读**：

- 服务端只用一个 `serve.py`，**只用 Python 标准库**（外加读图片尺寸用的 Pillow，ComfyUI 自带）
- 前端只有一个 `index.html`，无框架、无构建步骤、无 CDN
- 不写注册表、不装服务、不留后台常驻进程（关窗口即走，服务可单独停）

## 工作原理（一句话）

页面把中文提示词发给本地服务 `serve.py`，它依次做**① 违规检测 → ② 中译英 → ③ 组装 ComfyUI 工作流 → ④ 提交并轮询结果**，
拿到文件后写进预览缓存目录，再由页面取回来显示。

## 特性

| 功能 | 说明 |
| --- | --- |
| 文生图 | 写中文直接出图 |
| 图生图 | 放参考图 + 调重绘幅度 |
| ControlNet | 边缘 / 深度 / 姿态 / 线稿 / 涂鸦，锁构图换内容 |
| 扩图补全 | 在画面外补内容；支持「缩小原图腾空间」补全身 |
| 两遍高清 | 1.5× / 2×，先按基准画再放大重绘 |
| 中译英 | 优先 Google 翻译，失败自动退回本地词库 |
| 违规检测 | 规则可配置、可热加载、带不产图的自测 |
| 只预览 + 点击保存 | 结果先落预览缓存，想留才点保存下载 |
| 最近生成 | 页面底部缩略图，图片和视频一起显示 |
| 视频 | 文生视频 / 图生视频（Wan 2.2 5B TI2V，24fps） |

## 环境与前置条件

### 起步：一键整合包

最省事的方式是用一键整合包（自带 ComfyUI + Python + 常用节点 + 部分模型）：

**下载地址：<https://www.bilibili.com/opus/1233418589167419397>**

解压密码 `bilibili-秋葉aaaki`，解压后目录名 `ComfyUI-aki-v3.2`。
本程序就放在它的同级目录（见[摆放位置](#1-摆放位置)），程序会自动找到它。
各文件的出处与下载命令见 **[docs/MODELS.md](docs/MODELS.md)**。

**完整的下载与安装步骤**（解压密码、嵌套目录、首次启动、自带节点与模型盘点、常见问题）
见 **[docs/INSTALL-PACKAGE.md](docs/INSTALL-PACKAGE.md)**。

### 必须有

| 项 | 说明 |
| --- | --- |
| 可访问的 ComfyUI | 默认 `127.0.0.1:8188`。本程序**不自己做推理**，只调用 ComfyUI 的 4 个 HTTP 接口 |
| SD1.5 底模 | 至少一个（见 [MODELS.md](docs/MODELS.md)） |
| Python | ComfyUI 整合包自带的即可；只用标准库 + Pillow（读图片尺寸） |

用到的 ComfyUI 接口：

```text
GET  /system_stats                     探活
GET  /object_info/CheckpointLoaderSimple   列出可用底模
POST /prompt                           提交工作流
GET  /history/<prompt_id>              轮询并取回输出文件
```

### 按功能可选

| 功能 | 额外需要 |
| --- | --- |
| ControlNet：Canny / Scribble | 对应 ControlNet 模型（预处理是纯 OpenCV，无需权重） |
| ControlNet：Depth / OpenPose / LineArt | 上面 + 自定义节点 `comfyui_controlnet_aux` + 预处理器权重 |
| 扩图 / 补全 | `control_v11p_sd15_inpaint` 模型（节点是 ComfyUI 核心自带） |
| 视频 | 较新的 ComfyUI（需内置 `Wan22ImageToVideoLatent`、`CreateVideo`、`SaveVideo`、`ModelSamplingSD3`）+ 视频三件套 |
| 中文翻译 | 能访问 Google 的本地代理（关掉则退回本地词库） |

### 系统与网络

- **系统**：开发与测试均在 **Windows**。`start-app.bat` / `stop.bat` 是批处理，
  「在文件夹中显示」依赖 Windows 资源管理器；其它系统可用 `python serve.py` 启动服务，
  再用浏览器打开 `http://127.0.0.1:8899/`，其余功能不受影响。
- **浏览器**：`start-app.bat` 用 Edge 或 Chrome 开独立应用窗口；都没有则退回默认浏览器。
- **网络**：可以**完全离线**使用。只有两件事需要联网：① 中译英（可关）；
  ② 首次下载模型。服务只监听 `127.0.0.1`，不上传任何东西。
- **硬件**：见 **[docs/HARDWARE.md](docs/HARDWARE.md)**（含实测耗时与显存建议）。

## 安装

### 1. 摆放位置

最省事的摆法是让本仓库与 ComfyUI 目录**同级**（这样能被自动探测到，不用写配置）：

```text
<任意父目录>/
├── ComfyUI-aki-v3.2/       # 你的 ComfyUI（整合包或自建都行）
│   ├── python/             # 带 Pillow 的 Python
│   ├── ComfyUI/
│   │   ├── main.py
│   │   ├── models/
│   │   ├── input/
│   │   └── output/
│   └── ...
└── simple-ui/              # 本仓库
    ├── serve.py
    ├── index.html
    └── docs/
```

#### 怎么让程序找到 ComfyUI

按以下顺序解析，**前一步有结果就不看后面**：

1. **`config.json` 的 `comfy_root`** —— 仓库里给了模板 `config.example.json`，
   复制成 `config.json` 再改：

   ```json
   {
     "comfy_root": "把这里换成你的 ComfyUI 根目录（含 ComfyUI/main.py 的那一层）",
     "comfy_url": "http://127.0.0.1:8188",
     "port": 8899
   }
   ```

   （`config.json` 已在 `.gitignore` 里，不会被提交）

2. **环境变量** `PICMOTION_COMFY_ROOT`
3. **自动探测** —— 依次看「本目录 / 上一级 / 上两级」以及这些目录的**下一层**，
   命中条件是：该目录下有 `ComfyUI/main.py`，且自带 Python
   （`python/python.exe`、`python_embeded/python.exe`、`python/bin/python3`、
   `venv/Scripts/python.exe` 任一）

三步都没找到时，程序会打印提示并以**退出码 1** 退出，不会带着错误配置硬跑。

**解释器**同样自动查找（优先整合包自带的那个），并在启动时把结果写进 `python.txt`；
`start-app.bat` 优先读 `python.txt`，读不到再按常见整合包布局
（`..\ComfyUI-aki-v3.2\python\pythonw.exe`、`..\..\…`、`python_embeded` 等）逐个试，最后才报错。

#### 端口与地址

| 项 | 配置方式 | 默认 |
| --- | --- | --- |
| ComfyUI API 地址 | `config.json` 的 `comfy_url` 或环境变量 `PICMOTION_COMFY_URL` | `http://127.0.0.1:8188` |
| 界面服务端口 | `config.json` 的 `port` 或环境变量 `PICMOTION_PORT` | `8899` |
| 界面监听地址 | 固定为 `127.0.0.1`（**只监听本机**，不对外暴露） | — |

> 改了 `comfy_url` 或 `port` 之后，`start-app.bat` 里打开的地址也要跟着改。

### 2. 依赖

- **ComfyUI 自带的 Python**（含 Pillow）。本仓库不再需要任何其它第三方包。
- 用 `serve.py` 里的 `ensure_comfy()` 自动拉起 ComfyUI：它会调用 `<ComfyUI 目录>/python/python.exe -s ComfyUI/main.py --windows-standalone-build --disable-auto-launch --port 8188`。
- ComfyUI 的自定义节点建议装：`comfyui_controlnet_aux`（ControlNet 预处理器）、`ComfyUI-Manager`（可选，装工作流用）。

### 3. 模型准备

放到 ComfyUI 的对应目录（`<ComfyUI 目录>/ComfyUI/models/`）：

| 用途 | 目录 | 示例文件名 |
| --- | --- | --- |
| 写实出图 | `checkpoints/` | `majicmixRealistic_v7.safetensors` |
| 动漫/插画出图 | `checkpoints/` | `AWPainting_v1.2.safetensors` |
| ControlNet | `controlnet/` | `control_v11p_sd15_canny_fp16.safetensors` 等 |
| 扩图专用 ControlNet | `controlnet/` | `control_v11p_sd15_inpaint_fp16.safetensors` |
| 视频主模型 | `diffusion_models/` | `wan2.2_ti2v_5B_fp16.safetensors` |
| 视频文本编码器 | `text_encoders/` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| 视频 VAE | `vae/` | `wan2.2_vae.safetensors` |

ControlNet 的**预处理器权重**（深度 / 姿态 / 线稿需要）放在：

```text
<ComfyUI 目录>/ComfyUI/custom_nodes/comfyui_controlnet_aux/ckpts/<仓库名>/<文件名>
```

例如 `ckpts/depth-anything/Depth-Anything-V2-Small/depth_anything_v2_vits.pth`、
`ckpts/lllyasviel/Annotators/body_pose_model.pth`。

> 边缘 Canny 与涂鸦 Scribble 是纯 OpenCV 实现，**不需要任何权重**，装好节点即可用。

模型文件名可以在 `serve.py` 里改（见[配置](#配置)）。

**每个文件从哪个仓库下载、下载命令、以及整合包里已有哪些** —— 全部整理在
**[docs/MODELS.md](docs/MODELS.md)**（所有仓库地址与体积都实际核对过）。

### 4. 启动

| 文件 | 作用 |
| --- | --- |
| `start-app.bat` | **推荐**。确保服务在跑，然后以独立应用窗口打开（无地址栏、无标签页） |
| `start.bat` | 只启动本地服务（然后自己用浏览器开 `http://127.0.0.1:8899/`） |
| `stop.bat` | 停掉本地服务 |
| `编辑规则.bat` | 用记事本打开 `rules.json` |

首次点击「生成」时，如果 ComfyUI 没在跑，服务会自动把它拉起来（约 10–60 秒），页面会提示。

## 使用说明

### 文生图

写中文（例：`深夜的书店，窗外下雨，暖黄台灯，木书架，一杯咖啡`）→ 点「生成」。

- **风格**：给提示词追加英文标签，并连带切换模型
  - 写实 / 电影感 / 不加风格 → `majicmixRealistic_v7`
  - 动漫 / 插画 → `AWPainting_v1.2`
  - 点风格时，模型下拉**会跟着变**，下方会提示「当前用哪个模型、附加了哪些词」
- **画面比例（基准尺寸）**：竖版 512×768 / 横版 768×512 / 方形 640×640 / 宽屏 896×512
- **画面合理性**（内置，默认开）：`合理·不拉伸` 追加构图 / 比例 / 解剖相关正向词；`人物` `动作` `场景` 按需再补细节词。生成后图下方会列出**实际追加了什么**

### 图生图

放参考图 → 调**重绘幅度**：

| 幅度 | 效果 |
| --- | --- |
| 0.3–0.45 | 基本保留原图，微调画风 |
| 0.55（默认） | 明显改动，构图仍在 |
| 0.7–0.8 | 改动大 |

⚠️ 图生图会**强势保留原图的光影色调**（把白天的图改成夜晚，即使 0.8 也常常改不动）。想换光线 / 换场景 / 换材质，请用 ControlNet 或扩图。

### ControlNet（锁构图换内容）

放参考图 → 选**控制方式** → 调**控制强度**（0.2–1.6，默认 1.0）。

| 方式 | 保什么 | 需要下权重 |
| --- | --- | --- |
| 边缘 Canny | 线条轮廓 | 否 |
| 深度 Depth | 空间结构 | 是 |
| 姿态 OpenPose | 人物动作 | 是 |
| 线稿 LineArt | 线稿 | 是 |
| 涂鸦 Scribble | 宽松保形 | 否 |

和「图生图」的区别：ControlNet 是**空潜空间重画**，参考图只提供结构，所以内容和光线能真正换掉。
出图尺寸会**按参考图比例自动换算**（避免结构被拉伸），图下方会注明是否调整过。

### 扩图 / 补全

放参考图 → 选**方向**（向下 / 向上 / 左右 / 四周）→ 选**补多少**（小 / 中 / 大）。

- 原图那块**不会被改动**，只有新补的区域重新生成
- 已挂扩图专用 inpaint ControlNet，接缝 / 光照 / 背景会延续原图
- **半身补全身**：请勾上「**缩小原图腾空间**」。实测（512×768 半身图 → 画布 512×1280）：
  - 不勾：接缝干净，但人物占满画布，腿被压扁、脚出不来
  - 勾上：完整全身（裤子 + 鞋 + 地面阴影），接缝看不出 ← **补全身用这个**
  - 代价：人物变小，脸占的像素变少
- 提示词请把**要补的东西 + 整体**都写上（例：`全身照，牛仔裤，双腿，白色运动鞋，站在水泥地面上，写实摄影`）
- 画布长边上限 1280（再长 SD1.5 会崩）

### 两遍高清

**清晰度**选 `高清 1.5×` 或 `高清 2×`。

| 档位 | 基准 512×768 的输出 | 实测耗时（模型已加载） |
| --- | --- | --- |
| 标准 | 512×768 | 约 4.5 秒 |
| 高清 1.5× | 768×1152 | 约 7.6 秒 |
| 高清 2× | 1024×1536 | 约 12.1 秒 |

**不要直接把分辨率调高**：SD1.5 在 512 上训练，直出高分辨率会构图涣散（人物还会双头多手）。
两遍画法是「先按基准画，再放大重绘」，同样尺寸下质量明显更好。

### 视频

顶部「生成什么」选**视频**：

- **文生视频**：写提示词即可
- **图生视频**：放参考图，它会被当作**首帧**

参数：**视频尺寸**（横版 832×480 / 竖版 480×832 / 方形 640×640 / 高清横版 1280×704）、
**时长**（2 / 3 / 5 秒）、**步数**（10 / 20 / 30）。

实测（832×480、2 秒 = 45 帧、20 步）：约 **52–64 秒**。5 秒是 121 帧，耗时约为 2 秒的 2.5 倍以上。
720p 那档未做充分验证，12 GB 显存有风险。

### 违规检测

点顶部「**⚙ 违规检测**」按钮打开配置弹窗：

- 规则列表可增删改、逐条启用/停用
- **保存规则** 写入 `rules.json`，下一次请求即生效（无需重启）
- 坏正则会被拒绝并提示，不会写坏文件
- **检测自测**：输入一段文字，只判断会不会被拦，**不产图**
- 规则条数为 0 时，顶部按钮会变红提醒

链路位置：检测在**翻译之前**就执行，且原文和译文都会送检；不通过则直接返回，**请求到不了 ComfyUI**。被拦截的记录写入 `blocked.log`。

### 只预览 + 点击保存

生成的图 / 视频先落在预览缓存目录（`<ComfyUI 目录>/ComfyUI/output/simpleui_preview/`），页面**只是预览**。

- **保存到本地**：下载到你自己的位置
- **在文件夹中显示**：用资源管理器定位该文件
- **清空预览缓存**：一键删掉预览缓存（已另存的不受影响）

### 最近生成

右栏底部显示最近的结果缩略图（图片和视频都在内，默认最多 8 个），点缩略图即可在主区域预览。

### 小技巧

- 提示词框里 `Ctrl+Enter` 直接生成
- 「再画一张（换种子）」保留参数只换随机种子
- 出图下方会显示**实际送出的英文提示词**、用的哪个翻译引擎、以及被丢掉的词
- 支持 `?show=<文件名>` 直接打开某个已有结果，例如
  `http://127.0.0.1:8899/?show=simpleui_preview/simpleui_00001_.png`
- `?diag=1` 会在图下方显示页面实际宽度和最宽的元素（排查布局用）

## 配置

### 配置从哪来

| 项 | 从哪里配（按优先级） | 默认 |
| --- | --- | --- |
| ComfyUI 目录 | `config.json` 的 `comfy_root` → 环境变量 `PICMOTION_COMFY_ROOT` → 自动探测 | 探测结果 |
| ComfyUI API 地址 | `config.json` 的 `comfy_url` → 环境变量 `PICMOTION_COMFY_URL` | `http://127.0.0.1:8188` |
| 界面服务端口 | `config.json` 的 `port` → 环境变量 `PICMOTION_PORT` | `8899` |
| 界面监听地址 | `serve.py` 顶部的 `HOST`（固定，不建议改） | `127.0.0.1` |

> 路径和端口不要写进代码 —— 用 `config.json` 或环境变量，换机器时不用改源码。

### 其它常量（都在 `serve.py` 顶部）

| 常量 | 默认 | 说明 |
| --- | --- | --- |
| `PREVIEW_SUBDIR` | `simpleui_preview` | 预览缓存的子目录名 |
| `DEFAULT_CHECKPOINT` | `majicmixRealistic_v7.safetensors` | 默认模型 |
| `DEFAULT_NEGATIVE` | 见文件 | 默认负面提示词（压制拉伸 / 畸形 / 多肢等） |
| `STYLES` | 5 个预设 | 风格标签、连带模型、附加提示词 |
| `SIZES` | 4 档 | 图片基准尺寸 |
| `HIRES` | 3 档 | 高清倍率与第二遍 denoise |
| `CONTROLNET` | 5 种 | 控制方式、对应模型、预处理器 |
| `OUTPAINT_*` | 见文件 | 扩图方向比例、补幅、画布上限、羽化、专用 ControlNet |
| `VIDEO_*` | 见文件 | 视频模型 / 文本编码器 / VAE / 帧率 |
| `TRANSLATE_ENABLED` | `True` | 关掉就只用本地词库 |
| `PROXY_CANDIDATES` | 7897 / 7890 / 7891 / 10809 / 1080 / 2080 | 代理端口候选，依次探测 |

### 模型路径怎么改

`serve.py` 只把**文件名**交给 ComfyUI，目录由 ComfyUI 自己管。所以要换模型，改这些名字：

- 出图模型 → `STYLES[*]['model']` 与 `DEFAULT_CHECKPOINT`
- ControlNet → `CONTROLNET[*]['model']`、`OUTPAINT_CN`
- 视频 → `VIDEO_MODEL` / `VIDEO_CLIP` / `VIDEO_VAE`

想换 ComfyUI 的**位置**（不是模型文件），用 `config.json` 的 `comfy_root`
或环境变量 `PICMOTION_COMFY_ROOT`（见上文「怎么让程序找到 ComfyUI」）——
**不要把路径写进代码**，那样换台机器就得改源码。

### rules.json

```json
{
  "version": 1,
  "rules": [
    {
      "name": "规则名",
      "pattern": "正则表达式",
      "flags": "i",
      "enabled": true,
      "note": "备注"
    }
  ]
}
```

- 仓库里给了模板 `rules.example.json`（5 条默认规则），复制成 `rules.json` 使用；
  **`rules.json` 不存在时，程序会自动用内置默认规则生成一份**
- `rules.json` 已在 `.gitignore` 里 —— 里面是你自己的规则，不要提交
- `pattern` 是**正则**，坏正则保存时会被拒绝
- `flags` 常用 `i`（忽略大小写）
- 规则按 **mtime 热加载**：文件一改，下一次请求就生效，不用重启
- 匹配前会做归一化（小写、去零宽字符）和「紧凑化」（去掉空格与 `.-_*·|/\~^+`），
  所以 `色 情`、`色-情` 这类写法也能命中
- 也可以直接双击 `编辑规则.bat` 用记事本改

### 代理与翻译

中文 → 英文优先走 **Google 翻译**（免费端点，非官方 API，可能被限流）。它有两个前提：

1. 能访问 `translate.googleapis.com` —— 直连不通时，需要本地代理
2. 代理端口在 `PROXY_CANDIDATES` 里 —— 服务会**依次探测**，第一个能通的会被记住

失败时自动降级到**本地词库**（约 300 条，覆盖动作 / 颜色 / 机甲 / 场景 / 时间等），
再不行就原样发送。页面会显示用的是哪个引擎、以及词库里没有而被丢掉的词。

> 本地访问 ComfyUI **不走代理**：`serve.py` 用 `build_opener(ProxyHandler({}))` 显式禁用代理，
> 因为系统代理开着时 `127.0.0.1` 也会被代理吞掉（详见 `docs/PITFALLS.md`）。

## 常见问题

**Q：第一次点生成特别慢？**
A：ComfyUI 需要加载模型（视频模型 10 GB 级，首次可达几十秒到数分钟）。第二次起会快很多。

**Q：提示显存不够 / 生成失败？**
A：SD1.5 出图对 8 GB 显存足够；视频模型对显存和**内存**要求都高（详见 `docs/PITFALLS.md` 第 10 条）。
可以先降分辨率、降时长、降步数，或用「标准」清晰度。

**Q：中文没被翻译，出图效果差？**
A：看图片下方的提示——如果写的是「本地词库」，说明 Google 翻译没接通。检查代理是否开着、
端口是否在 `PROXY_CANDIDATES` 里；也可以直接在提示词里写英文。

**Q：页面能左右滚动 / 出现两条滚动条？**
A：这是旧版本的布局问题，已修复（预览区媒体宽度限制、右栏只吸附不内部滚动）。
按 `Ctrl+R` 刷新页面即可；如果仍有问题，用 `?diag=1` 看是哪个元素最宽。

**Q：点「写实」出来的却像油画？**
A：检查「模型」下拉。旧版本里模型下拉按字母排序、默认选中动漫模型，且风格按钮不会切换模型。
现在点风格会连带切模型，下拉下方也会明确提示当前用哪个模型。想照片感就选「写实」或「不加风格」。

**Q：换了桌面图标但图标没变？**
A：Windows 图标缓存。换一个新文件名 + 执行 `ie4uinit.exe -show`（见 `docs/PITFALLS.md` 第 15 条）。

**Q：应用窗口标题栏 / 任务栏没有图标？**
A：需要 favicon。本仓库已在页面声明图标并提供 `/favicon.ico` 路由；若仍是空白，删掉
生成的 `app-profile/` 目录再启动一次（浏览器会缓存「没有图标」这件事）。

**Q：启动时报「找不到 ComfyUI」怎么办？**
A：程序按 `config.json` → 环境变量 `PICMOTION_COMFY_ROOT` → 自动探测 的顺序找 ComfyUI 目录，
三步都没命中就会打印提示并退出（退出码 1）。最省事的办法是在本目录建一个 `config.json`
（照 `config.example.json` 复制），把 `comfy_root` 写成你的 ComfyUI 根目录 ——
也就是同时含 `ComfyUI/main.py` 和自带 Python 的那一层。

**Q：怎么把结果发给别人？**
A：点「保存到本地」下载后自行分享即可。本工具不提供任何上传 / 云端能力。

## 目录结构

```text
simple-ui/                       # 本仓库
├── serve.py                     # 服务端（标准库）：检测 + 翻译 + 工作流组装 + 调 ComfyUI
├── index.html                   # 界面（单文件，无框架）
├── start-app.bat                # 启动服务 + 打开独立应用窗口（推荐入口）
├── start.bat                    # 只启动服务
├── stop.bat                     # 停止服务
├── 编辑规则.bat                  # 用记事本打开 rules.json
├── config.example.json          # 配置模板（复制成 config.json 使用）
├── rules.example.json           # 规则模板（复制成 rules.json 使用）
├── LICENSE                      # MIT
├── .gitignore
├── logo.png                     # 界面 logo（同时用作 favicon）
├── icon-v2.ico                  # 应用窗口 / 任务栏图标
├── docs/
│   ├── ARCHITECTURE.md          # 完整流程与工作流节点图
│   └── PITFALLS.md              # 踩坑记录（症状 / 根因 / 解决）
│
│   ── 以下是运行时产物，已被 .gitignore 排除 ──
├── config.json                  # 你自己的配置（comfy_root / comfy_url / port）
├── rules.json                   # 你自己的规则；缺失时自动用内置默认规则生成
├── python.txt                   # serve.py 写下的解释器路径，供 start-app.bat 复用
├── blocked.log / serve.log      # 被拦截记录 / 服务日志（可能含提示词，别提交）
├── icon.ico / logo-v2.png       # 本机图标素材
├── 说明.txt                      # 面向使用者的简要说明
└── app-profile/                 # 应用窗口专用的浏览器配置（可删，会自动重建）
```

运行时还会用到（位于 ComfyUI 目录内，不在本仓库）：

```text
<ComfyUI 目录>/ComfyUI/input/                     # 上传的参考图存这里
<ComfyUI 目录>/ComfyUI/output/simpleui_preview/   # 生成结果的预览缓存
```

## 相关文档

- [`docs/INSTALL-PACKAGE.md`](docs/INSTALL-PACKAGE.md) —— 一键整合包的完整安装过程（下载、解压密码、目录结构、首次启动、自带节点与模型盘点、常见问题）
- [`docs/MODELS.md`](docs/MODELS.md) —— 模型清单：文件名、体积、放哪个目录、**从哪个仓库下载**（含直接可用的下载命令）
- [`docs/HARDWARE.md`](docs/HARDWARE.md) —— 硬件要求与实测性能、内存/页面文件/磁盘建议
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) —— 请求链路、每种模式的工作流节点图、关键设计决策、API 一览
- [`docs/PITFALLS.md`](docs/PITFALLS.md) —— 开发与部署中真实踩过的坑，统一按「症状 / 根因 / 解决」记录

## License

本项目以 **MIT License** 发布，完整文本见 [`LICENSE`](LICENSE)。

```text
Copyright (c) 2026 H-W-B
```
