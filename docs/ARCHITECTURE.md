# 架构与流程

本文说明 PicMotion（极简画影）的完整工作流程：请求怎么走、每种模式在 ComfyUI 里长什么样、
以及关键设计决策背后的原因。

---

## 1. 总览

三层结构，**本仓库不做任何 AI 推理**：

```text
┌──────────────────────────────┐
│  index.html（单页界面）       │  无框架、无构建、无 CDN
│  中文输入 / 参数面板 / 预览    │
└───────────────┬──────────────┘
                │  HTTP（只监听 127.0.0.1）
┌───────────────▼──────────────┐
│  serve.py（本地服务 :8899）   │  只用标准库 + Pillow
│  检测 → 翻译 → 组装 → 提交    │  不持有模型、不做推理
└───────────────┬──────────────┘
                │  ComfyUI HTTP API（127.0.0.1:8188）
┌───────────────▼──────────────┐
│  ComfyUI（独立进程）          │  真正干活的引擎
│  /prompt /history /system_stats│  可由本服务按需拉起
└──────────────────────────────┘
```

图中端口是默认值：界面服务 `8899`、ComfyUI `8188`，都可通过 `config.json` 或环境变量覆盖，
监听地址固定为 `127.0.0.1`（见 4.9）。

职责划分很清晰：**本仓库负责"把中文变成合法的工作流并管理结果"，ComfyUI 负责算。**
好处是换模型、换采样器、换视频管线都只影响工作流组装那几十行，界面完全不用动。

---

## 2. 请求链路

一次「生成」的完整路径：

```text
浏览器                  serve.py                         ComfyUI
  │                        │                               │
  │  POST /api/generate    │                               │
  │  {prompt, mode, ...}   │                               │
  ├───────────────────────>│                               │
  │                        │ ① 违规检测 moderate()          │
  │                        │    ├─ 命中 → 记 blocked.log    │
  │                        │    │        直接返回 blocked    │
  │                        │    └─ 通过 ↓                   │
  │                        │ ② 中译英 translate()           │
  │                        │    Google → 本地词库 → 原文     │
  │                        │ ③ 组装工作流（纯字典）          │
  │                        │    build_workflow() / …        │
  │                        │ ④ ensure_comfy()               │
  │                        │    └─ 没在跑就 Popen 拉起 ─────>│
  │                        │  POST /prompt {prompt: wf}     │
  │                        ├───────────────────────────────>│
  │                        │         {prompt_id}            │
  │                        │<───────────────────────────────┤
  │                        │  轮询 GET /history/<id>（2 秒） │
  │                        ├───────────────────────────────>│
  │                        │   outputs{ images:[{filename…}] }│
  │                        │<───────────────────────────────┤
  │                        │  按扩展名归类 图片 / 视频        │
  │  {ok, images, videos…} │  （文件已由 ComfyUI 写入磁盘）   │
  │<───────────────────────┤                               │
  │  GET /api/img?name=…   │                               │
  ├───────────────────────>│  从预览缓存目录读文件并内联返回  │
  │<───────────────────────┤                               │
  │  显示预览（图 / 视频）   │                               │
```

### ① 违规检测

- 入口只有一个：`moderate(原文 + 英文提示词, 负面提示词)` —— **原文和译文都送检**
- 检测前做两步归一化，防止用空格/符号绕过：
  - `normalize()`：转小写、去掉零宽字符
  - `compact()`：去掉空格与 `.-_*·|/\~^+`，所以 `色 情`、`色-情` 也能命中
- 命中则写 `blocked.log` 并直接返回 `{ok:false, blocked:true}`，**请求到不了 ComfyUI**
- 规则来自 `rules.json`，**按 mtime 热加载**（见第 4 节）

### ② 中文 → 英文

三级降级，任何一级成功就停：

```text
translate(text)
  ├─ 1. Google 翻译（免费端点，走代理）  → engine = 'google'
  ├─ 2. 本地词库 translate_dict()        → engine = 'dict'，并返回被丢掉的词
  └─ 3. 原样返回                          → engine = 'none'
```

结果带缓存（`_tr_cache`，带锁），同一个提示词不重复请求。
翻译引擎、实际送出的英文、被丢掉的词都会回传到页面显示 —— **让"为什么效果不好"一眼可查**。

### ③ 组装工作流

纯字典拼接，没有任何模板引擎：每个模式的组装函数返回一个 **ComfyUI API 格式**的 `prompt` 字典
（`节点 ID → {class_type, inputs}`，连线用 `[来源节点ID, 输出槽位]` 表示）。

### ④ 提交与轮询

- `POST /prompt` 提交，拿到 `prompt_id`
- 每 **2 秒**轮询 `GET /history/<prompt_id>`
- 超时上限：图片 **900 秒**，视频 **1800 秒**
- 执行报错时从 `status.messages` 里取 `execution_error` 的原始信息回显给页面
- 拿到 `outputs` 后**按扩展名归类**：`.mp4/.webm/.mkv/.mov/.gif` → 视频，其余 → 图片

---

## 3. 各模式的 ComfyUI 工作流

> 约定：`[n]` 是工作流里的节点 ID；`A → B` 表示 A 的输出接到 B 的输入。
> 所有模式最后都落到 `SaveImage` / `SaveVideo`，且 **`filename_prefix` 指向预览缓存的子目录**。

### 3.1 文生图

```text
[4] CheckpointLoaderSimple(ckpt_name)
      ├─ MODEL ─────────────────────────────────┐
      ├─ CLIP ─→ [6] CLIPTextEncode(正向) ──────┤
      │         [7] CLIPTextEncode(负向) ──────┤
      └─ VAE ──────────────────────────┐        │
                                       │        ▼
[5] EmptyLatentImage(w, h, batch) ─────┼──→ [3] KSampler
                                       │      seed / steps=24 / cfg=7
                                       │      sampler=dpmpp_2m / scheduler=karras
                                       │      denoise=1.0
                                       │        │
                                       └───────→└─→ [8] VAEDecode(vae)
                                                      │
                                                      ▼
                                        [9] SaveImage(filename_prefix=simpleui_preview/simpleui)
```

关键点：正向/负向提示词各一个 `CLIPTextEncode`，共用同一个 `CLIP` 输出。

### 3.2 图生图

与文生图的差别只有**潜空间来源**：

```text
[20] LoadImage(image)
      │
      ▼
[21] VAEEncode(pixels, vae = [4].VAE)
      │
      ▼
[3] KSampler(denoise = 重绘幅度, latent_image = [21])
```

- **不加** `EmptyLatentImage` —— 尺寸由原图决定，所以画面比例选择在这个模式下不起作用
- `denoise` 越小越贴近原图（0.3–0.45 保画风，0.6–0.8 大改）
- 局限：原图的**光影色调被强约束**，改不动；

### 3.3 ControlNet（锁构图换内容）

```text
[20] LoadImage(image)
      │
      ▼
[22] 预处理器之一
      ├─ CannyEdgePreprocessor(low=100, high=200, resolution=512)
      ├─ DepthAnythingV2Preprocessor(ckpt=depth_anything_v2_vits.pth)
      ├─ OpenposePreprocessor(detect_body/hand/face=enable)
      ├─ LineArtPreprocessor(coarse=disable)
      └─ FakeScribblePreprocessor(safe=enable)
      │  结构图
      ▼
[23] ControlNetLoader(control_net_name) ──┐
                                          ▼
[24] ControlNetApplyAdvanced(positive=[6], negative=[7],
                             control_net=[23], image=[22],
                             strength=控制强度, start_percent=0.0, end_percent=0.85)
      │  改写后的 正/负 conditioning
      ▼
[3] KSampler(model=[4], positive=[24].0, negative=[24].1,
             latent_image=[5] EmptyLatentImage, denoise=1.0)
```

和图生图的本质区别：**潜空间是空的**，参考图只通过 ControlNet 提供结构，
所以内容、材质、光线都能真正换掉。

**防拉伸**：`ControlNetApplyAdvanced` 会把结构图内部缩放到出图尺寸，
比例不一致就是硬抻。因此在组装前先按参考图比例反推尺寸：

```text
以用户所选尺寸的面积为目标，套用参考图宽高比
  → 对齐到 8 的倍数
  → 长边 ≤ 1024、短边 ≥ 384
  → 与用户所选不一致时在结果里标注「已按参考图比例调整」
```

### 3.4 扩图 / 补全

```text
[20] LoadImage(image)
      │
      ▼
[25] ImageScale(lanczos, sw, sh, crop=disabled)     ← 按 plan_outpaint() 算出的尺寸
      │
      ▼
[26] ImagePadForOutpaint(left, top, right, bottom, feathering=32)
      │            │
      │ IMAGE      │ MASK
      ├────────────┼──────────────────────┐
      ▼            │                      ▼
[30] InpaintPreprocessor(image, mask,      [27] VAEEncodeForInpaint(
        black_pixel_for_xinsir_cn=False)        pixels=[26].IMAGE, vae=[4].VAE,
      │  （把遮罩区渲染成灰色 —— 关键）         mask=[26].MASK, grow_mask_by=24)
      ▼                                        │
[28] ControlNetLoader(inpaint ControlNet) ──┐  │
                                            ▼  │
[29] ControlNetInpaintingAliMamaApply(      │  │
        positive=[6], negative=[7],         │  │
        control_net=[28], vae=[4].VAE,      │  │
        image=[30], mask=[26].MASK,         │  │
        strength=1.0, start=0.0, end=1.0)   │  │
      │ 正/负 conditioning                    │  │
      ▼                                      ▼  ▼
[3] KSampler(denoise=1.0, dpmpp_2m/karras, positive=[29].0, negative=[29].1,
             latent_image=[27])
      │
      ▼
[8] VAEDecode → [9] SaveImage(prefix=simpleui_preview/outpaint)
```

**为什么必须加 `InpaintPreprocessor`**：`control_v11p_sd15_inpaint` 要求"待补区域"在控制图里是
**灰色**，而 `ImagePadForOutpaint` 输出的是黑底。少了这一步，模型会把"保持黑色"当结构约束，
补出一整块纯灰。

**尺寸规划**（`plan_outpaint()`）：

```text
方向比例 OUTPAINT_PAD:  down=(0,0,0,0.60)  up=(0,0.60,0,0)
                        lr=(0.40,0,0.40,0) all=(0.35,0.35,0.35,0.35)
补幅 OUTPAINT_AMOUNT:   small=0.5  mid=1.0  large=1.8
普通模式：源图长边超过 768 才缩小；补的量受"画布长边 ≤ 1280"约束（压补量，不缩原图）
缩小模式（勾选「缩小原图腾空间」）：
        原图缩到画布高度的约 42% → 水平居中 → 两侧各补少量 → 下方留出主要空间
```

「缩小模式」是为了解决**半身补全身**：不缩小的话原图占满画布，下半身没有空间，
腿会被压扁或截断。

### 3.5 两遍高清（可叠加在 3.1 / 3.2 / 3.3 之上）

```text
[3] KSampler（第一遍，基准尺寸）
      │
      ▼
[11] LatentUpscale(samples=[3], upscale_method=bislerp,
                   width=基准宽 × 倍率, height=基准高 × 倍率, crop=disabled)
      │
      ▼
[12] KSampler(seed 同第一遍, steps=max(10, round(步数 × 0.7)),
              denoise = 0.40（1.5×）/ 0.45（2×）,
              latent_image=[11])
      │
      ▼
[8] VAEDecode → [9] SaveImage
```

| 倍率 | 第二遍 denoise | 512×768 的输出 | 实测耗时（模型已加载） |
| --- | --- | --- | --- |
| 1.5× | 0.40 | 768×1152 | 约 7.6 秒 |
| 2× | 0.45 | 1024×1536 | 约 12.1 秒 |

**已知取舍**：第二遍的 conditioning 用的是原始 `[6]`/`[7]`，
**没有走 ControlNet 改写后的 conditioning**。也就是说 ControlNet + 高清时，
第二遍只做细节精修、不再受结构约束。这是当前行为。

### 3.6 视频（Wan 2.2 5B TI2V）

```text
[37] UNETLoader(unet_name=wan2.2_ti2v_5B_fp16.safetensors, weight_dtype=default)
      │
      ▼
[48] ModelSamplingSD3(shift=8.0)
      │
      ▼
[38] CLIPLoader(clip_name=umt5_xxl_fp8_e4m3fn_scaled.safetensors,
                type=wan, device=default)
      ├─→ [6] CLIPTextEncode(正向)
      └─→ [7] CLIPTextEncode(负向)

[39] VAELoader(wan2.2_vae.safetensors) ──────────────┐
                                                     │
[56] LoadImage(参考图)   ← 仅「图生视频」时接入        │
      │                                              │
      ▼                                              │
[55] Wan22ImageToVideoLatent(vae=[39], width, height,│
                             length, batch_size=1,   │
                             start_image=[56])       │
      │  LATENT                                       │
      ▼                                              │
[3] KSampler(seed, steps=20, cfg=5.0,                │
             sampler_name=uni_pc, scheduler=simple,  │
             denoise=1.0,                            │
             model=[48], positive=[6], negative=[7], │
             latent_image=[55])                      │
      │                                              │
      ▼                                              │
[8] VAEDecode(samples=[3], vae=[39]) ◄───────────────┘
      │
      ▼
[57] CreateVideo(images=[8], fps=24)
      │  VIDEO
      ▼
[58] SaveVideo(video=[57], format=auto, codec=auto,
               filename_prefix=simpleui_preview/video)
```

要点：

- **文生视频 / 图生视频共用同一条链**，唯一差别是 `Wan22ImageToVideoLatent` 有没有接 `start_image`
- 参数照官方模板：`uni_pc` + `simple` + 20 步 + CFG 5 + `ModelSamplingSD3(shift=8)` + 24fps
- **帧数必须是 `4n+1`**（潜空间时间维压缩 4 倍）：

```python
def frames_for(seconds):
    f = max(9, int(round(seconds * VIDEO_FPS)))   # VIDEO_FPS = 24
    return f - ((f - 1) % 4)                      # 向下取到 4n+1
```

换算结果：2 秒 → **45 帧**（1.88 秒）、3 秒 → **69 帧**、5 秒 → **117 帧**。

- 尺寸档位：832×480 / 480×832 / 640×640 / 1280×704（最后一档未做充分验证，12 GB 显存有风险）
- 实测：832×480、45 帧、20 步，约 **52–64 秒**

---

## 4. 关键设计决策

### 4.1 为什么只用标准库

服务端只依赖 Python 标准库（外加 Pillow，用于读图片尺寸，ComfyUI 环境自带）。

- **免安装**：用户不需要 `pip install`，不会遇到依赖冲突
- **和 ComfyUI 版本解耦**：ComfyUI 的 Python 环境千奇百怪（整合包/conda/venv），只用标准库最稳
- 代价：没有 Web 框架、没有模板引擎，路由和 JSON 都要手写 —— 但总共也就百来行

### 4.2 为什么访问本地 ComfyUI 要显式禁用代理

```python
_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
```

系统代理开着时（例如本地开着代理软件），`urllib` 默认会把**所有**请求走代理，
包括 `http://127.0.0.1:8188`。有些代理软件会把 loopback 请求吞掉或绕出去，导致
"ComfyUI 明明在跑却连不上"。

因此：**访问 ComfyUI 一律用禁用代理的 opener**；而访问 Google 翻译则**显式使用代理**。
两种请求走两条路，各按需要。

### 4.3 预览缓存 + 「只预览、点击保存」

生成结果由 ComfyUI 写入：

```text
<ComfyUI 目录>/ComfyUI/output/simpleui_preview/
```

而不是直接写用户的图片目录。页面上：

- 主区域**只预览**，不自动另存
- **保存到本地** → 走 `/api/download`（带 `Content-Disposition: attachment`）下载到用户自己选的位置
- **在文件夹中显示** → 调系统资源管理器定位文件
- **清空预览缓存** → 只删这个子目录

**取舍**：文件客观上必须先落到某处才能被页面读到，所以"只预览"的准确含义是
**"落在专属的缓存目录里、不混进用户图库、可一键清空"**，而不是"完全不写磁盘"。
好处是结果不会在用户还没决定前就散落各处，也不需要额外的内存中转。

### 4.4 `rules.json` 基于 mtime 热加载

```python
load_rules()  # 每次请求前检查文件 mtime，变了才重新读取并编译正则
```

- 规则文件可以**直接编辑**（记事本/`编辑规则.bat`），存盘后**下一次请求即生效**，不用重启服务
- 规则列表为空时每次都会重新读（避免"空规则被缓存住、加了规则不生效"）
- 保存规则时先逐条编译正则，**坏正则整批拒绝**，不会把文件写坏
- 检测失败时**默认放行还是拦截**：当前实现是"编译不出来的规则不参与匹配"，
  即坏规则不会变成"拦死一切"

### 4.5 翻译的三级降级

```text
Google 翻译（走代理，超时 8 秒）
  → 本地词库（约 300 条，逐个词替换，未命中的词收集为 dropped）
  → 原文
```

- Google 用的是**非官方免费端点**，可能限流；本地词库是保底，保证"没网也能画"
- 代理端口从 `PROXY_CANDIDATES` **依次探测**，第一个通的会被记住（`_good_proxy`），避免每次都试
- 降级结果如实显示给用户：用的哪个引擎、被丢掉了哪些词 —— 不假装翻译成功

### 4.6 目录穿越防护

`/api/img` 与 `/api/download` 接受文件名参数，因此做了解析 + 越界检查：

```python
def _img_path(name):
    name = (name or '').replace('\\', '/').lstrip('/')
    if not name or '..' in name:
        return ''
    base = os.path.realpath(COMFY_OUTPUT)
    p = os.path.realpath(os.path.join(COMFY_OUTPUT, name))
    return p if (p == base or p.startswith(base + os.sep)) and os.path.isfile(p) else ''
```

- 拒绝含 `..` 的路径
- 用 `realpath` 解析后**再校验是否仍在输出目录内**（防止符号链接/大小写等绕过）
- 越界直接返回 **404**（实测 `../../../../Windows/win.ini` 被拒）

### 4.7 断线找回

界面在生成请求上等待时，如果本地服务被重启，连接会断。但 **ComfyUI 是独立进程，任务照跑**。
因此页面在捕获网络错误后会轮询 `/api/recent`（每 5 秒，最多 2 分钟），
发现新出现的文件就直接显示，避免"活儿干完了但结果丢了"。

### 4.8 尺寸对齐

所有传给 ComfyUI 的宽高都对齐到 **8 的倍数**（VAE 下采样要求）：

```python
def snap8(v, minimum=8):     # minimum 可调：补 0 像素的边必须得到 0，而不是 8
    return max(minimum, int(round(v / 8.0)) * 8)
```

这个 `minimum` 参数是踩坑后加的（见 `PITFALLS.md` 第 17 条）。

### 4.9 ComfyUI 目录、解释器与端口：为什么用配置文件而不是写死

ComfyUI 的目录布局**五花八门**：官方便携版是 `python_embeded/python.exe`，
国内整合包常见 `python/python.exe`，自建环境可能是 `venv/Scripts/python.exe`，
而且仓库目录名也各不相同。把路径写死在代码里，换个包就跑不起来。

所以改成**三级解析**，前一步有结果就不看后面：

```text
ComfyUI 目录：
  1. config.json 的 comfy_root
  2. 环境变量 PICMOTION_COMFY_ROOT
  3. 自动探测：本目录 / 上一级 / 上两级，以及这些目录的下一层
       命中条件 = 有 ComfyUI/main.py  且  自带 python
       （python/python.exe、python_embeded/python.exe、
         python/bin/python3、venv/Scripts/python.exe 任一）

解释器：按同样的候选顺序找（优先整合包自带的），
        启动时把结果写进 python.txt，供 start-app.bat 复用

端口/地址：
  COMFY = config.json 的 comfy_url → PICMOTION_COMFY_URL → http://127.0.0.1:8188
  PORT  = config.json 的 port     → PICMOTION_PORT     → 8899
  HOST  = 固定 127.0.0.1（只监听本机，不对外暴露）
```

三点考虑：

- **仓库里不存机器相关的东西**：`config.json` 和 `python.txt` 都被 `.gitignore` 排除，
  仓库里只放 `config.example.json` 这样的模板
- **找不到就明确失败**：三级都没命中时打印三种指定方式并 `sys.exit(1)`，
  而不是带着错误配置硬跑、让人对着诡异报错排查
- **`python.txt` 是缓存不是配置**：它由 `serve.py` 在启动时写入，`start-app.bat` 优先读它，
  读不到再按候选路径逐个试 —— 用户既不用手填，也不会因为缺少它而启动不了

---

## 5. `/api` 接口一览

服务默认监听 `127.0.0.1:8899`（端口可由 `config.json` 的 `port` 或环境变量 `PICMOTION_PORT` 改）。
下表方法一栏中，标 GET 的直接用浏览器就能试。

| 方法 | 路径 | 入参 | 说明 |
| --- | --- | --- | --- |
| GET | `/` `/index.html` | — | 返回页面 |
| GET | `/logo.png` | — | 界面 logo（PNG） |
| GET | `/favicon.ico` | — | 窗口/任务栏图标（ICO，回退 PNG） |
| GET | `/api/state` | — | 全量状态：ComfyUI 是否在跑、模型列表、风格与对应模型/提示词、最近结果、规则与计数、翻译开关与当前代理 |
| GET | `/api/recent` | `limit`（默认 24） | 最近结果列表（**字段名是 `images`**，图片与视频混排） |
| GET | `/api/img` | `name` | 内联返回文件，用于页面预览（图片/视频按扩展名给 Content-Type） |
| GET | `/api/download` | `name` | 同 `/api/img`，但带 `Content-Disposition: attachment` → 「保存到本地」 |
| POST | `/api/generate` | 见下 | 生成入口 |
| POST | `/api/check` | `prompt` | 干跑检测：只判断会不会被拦，**不产图** |
| POST | `/api/rules` | `rules` | 校验并保存规则 → 写 `rules.json` → 热生效 |
| POST | `/api/reveal` | `name` | 在资源管理器里定位该文件 |
| POST | `/api/clear-preview` | — | 清空预览缓存目录 |

### `POST /api/generate` 请求体

| 字段 | 说明 |
| --- | --- |
| `prompt` | 中文提示词（必填） |
| `mode` | `image`（默认）/ `video` |
| `style` | 风格键：`realistic` / `anime` / `cinematic` / `painting` / `none` |
| `size` | 图片基准尺寸键：`portrait` / `landscape` / `square` / `wide` |
| `hires` | `none` / `1.5` / `2` |
| `vsize` `seconds` | 视频尺寸键、时长（秒） |
| `image` | 参考图，data URL 或裸 base64 |
| `denoise` | 图生图重绘幅度 |
| `control` `cnStrength` | ControlNet 类型、控制强度 |
| `outpaint` `opAmount` `opShrink` | 扩图方向、补幅、是否缩小原图 |
| `quality` `person` `action` `scene` | 内置合理性提示词开关 |
| `checkpoint` | 模型文件名（覆盖风格默认） |
| `negative` | 负面提示词（留空用内置默认） |
| `steps` `cfg` `seed` `batch` | 采样参数 |

### 响应常用字段

| 字段 | 说明 |
| --- | --- |
| `ok` | 是否成功 |
| `blocked` | 是否被违规检测拦截（此时 `error` 是原因） |
| `images` / `videos` / `files` | 输出文件名（带预览子目录前缀） |
| `imgMode` | `txt2img` / `i2i` / `controlnet` / `outpaint` |
| `checkpoint` `style` `size` `outSize` `hires` | 实际生效的参数 |
| `prompt` `translated` `dropped` `engine` | 最终英文提示词、翻译结果、被丢词、翻译引擎 |
| `applied` | 本次实际追加了哪些内置提示词（逐条列出） |
| `aspectFixed` | 是否为防拉伸调整过出图尺寸 |
| `outpaintCanvas` `frames` `seconds` | 扩图画布尺寸 / 视频帧数与时长 |
| `elapsed` | 服务端耗时（秒） |

---

## 6. 运行时文件

| 路径 | 说明 |
| --- | --- |
| `<仓库>/config.json` | 你的配置：`comfy_root` / `comfy_url` / `port`（**已 gitignore**，模板见 `config.example.json`） |
| `<仓库>/rules.json` | 违规检测规则（可热加载；**不存在时自动用内置默认规则生成**，已 gitignore，模板见 `rules.example.json`） |
| `<仓库>/python.txt` | `serve.py` 启动时写下的解释器路径，供 `start-app.bat` 复用（已 gitignore） |
| `<仓库>/blocked.log` | 被拦截记录 |
| `<仓库>/serve.log` | 服务日志 |
| `<仓库>/app-profile/` | 应用窗口专用浏览器配置（生成物，可删） |
| `<ComfyUI 目录>/ComfyUI/input/` | 上传的参考图（服务写入，供 `LoadImage` 读） |
| `<ComfyUI 目录>/ComfyUI/output/simpleui_preview/` | 结果的预览缓存 |

---

## 7. 扩展点

想加功能，通常只动 `serve.py` 里的配置表，界面会自动跟上：

| 想做什么 | 改哪里 |
| --- | --- |
| 加一个风格 | `STYLES` 加一项（`label` / `model` / `tokens`）—— 界面按钮、`styleModels`、`styleTokens` 全自动 |
| 加一种 ControlNet | `CONTROLNET` 加一项（`model` / `pre` / `pre_inputs`） |
| 换出图模型 | `STYLES[*]['model']` 与 `DEFAULT_CHECKPOINT` |
| 换视频模型 | `VIDEO_MODEL` / `VIDEO_CLIP` / `VIDEO_VAE` |
| 调内置提示词 | `QUALITY_PREFIX` / `QUALITY_SUFFIX` / `SUBJECT_TOKENS` / `DEFAULT_NEGATIVE` |
| 加尺寸档位 | `SIZES` / `VIDEO_SIZES` |
| 调高清倍率 | `HIRES`（倍率, 第二遍 denoise） |
| 换 ComfyUI 位置 | `config.json` 的 `comfy_root` 或环境变量 `PICMOTION_COMFY_ROOT`（**不要改代码**，见 4.9） |
| 换端口 / ComfyUI 地址 | `config.json` 的 `port` / `comfy_url`，或环境变量 `PICMOTION_PORT` / `PICMOTION_COMFY_URL` |
| 换端口 | `HOST` / `PORT`（界面里的 URL 也要一起改） |

加一种**全新管线**（例如 Inpainting、放大模型）时，需要：

1. 写一个 `build_xxx_workflow()` 返回 API 格式字典（照现有三个函数的结构抄）
2. 在 `generate()` 的分支里选它
3. 在 `index.html` 里加对应的控件，并把它塞进 `POST /api/generate` 的请求体
4. 在 `applied` / 结果字段里带上必要信息，让页面能解释"这次到底做了什么"
