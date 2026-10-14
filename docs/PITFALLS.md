# 踩坑记录

本文记录 PicMotion（极简画影）开发与部署过程中**真实发生过**的问题，每条统一按
「症状 / 根因 / 解决」三段写，方便直接照方抓药。

环境前提：Windows + 中文系统 + Windows PowerShell 5.1 + ComfyUI 整合包（Windows 便携版）。
相当一部分坑来自「中文 + PowerShell 5.1 的编码/重定向行为」，与项目逻辑无关，但会在部署时真实拦路。

---

## 1. PowerShell 5.1 把无 BOM 的 UTF-8 当 GBK 读

**症状**
运行含中文的 `.ps1` 脚本时报语法错误，例如「表达式或语句中包含意外的标记」；或脚本里中文全变乱码。

**根因**
Windows PowerShell 5.1 对**没有 BOM** 的 `.ps1` 文件按系统 ANSI 代码页解码（中文系统是 GBK/936）。
UTF-8 的中文字节被拆成了 GBK 字符，字符串里的引号配对被打乱，于是解析器在中文那一行报错。
用编辑器/工具直接写出的文件默认是**无 BOM 的 UTF-8**，正好踩中。

**解决**
- 写 `.ps1` 时显式使用带 BOM 的 UTF-8：
  `[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($true)))`
- 改完脚本后先用 PowerShell 解析器校验一遍再执行（`[System.Management.Automation.Language.Parser]::ParseFile(...)`）。
- 非必要不要把中文写进 `.ps1`：把中文放到 `.json` / `.txt`（由程序读取）比放在脚本里安全得多。

---

## 2. `Invoke-RestMethod -Body <字符串>` 按 ANSI 编码，中文变 `?`

**症状**
向本地服务提交带中文提示词的请求，ComfyUI 侧报：

```text
[Errno 22] Invalid argument: '...\output\????_00001_.png'
```

文件名里的中文变成了一串 `?`。

**根因**
PowerShell 5.1 的 `Invoke-RestMethod` / `Invoke-WebRequest` 在 `-Body` 传**字符串**时，
按 ANSI 编码发送，非 ASCII 字符直接丢失。

**解决**
- 传字节数组并显式声明字符集：

```powershell
Invoke-RestMethod -Uri $url -Method Post `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($json)) `
  -ContentType 'application/json; charset=utf-8'
```

- 或者改用 `curl.exe`，把 JSON 先以无 BOM 的 UTF-8 写进文件，再 `--data-binary @file`。
- 服务端一侧也做了防御：自己组装 JSON 时统一 `ensure_ascii=False` + UTF-8 编码输出。

---

## 3. PowerShell 不跟随 HTTP 308 重定向 → 模型下载全部失败

**症状**
用 `Invoke-WebRequest` 从 HuggingFace 镜像批量下载模型，6 个文件**全部**失败。

**根因**
镜像对文件请求返回 **HTTP 308**（Permanent Redirect），而 PowerShell 5.1 的
`Invoke-WebRequest` / `HttpWebRequest` 不跟随 308，只跟随 301/302/307。请求停在重定向响应上。

**解决**
- 改用 `curl.exe -L`（能正确处理 308）。
- 下载后按脚本里固定的 **sha256** 逐个校验，确认文件完整（这一步不能省，镜像偶发截断）。
- 需要在 PowerShell 里跟随重定向时，可以手工处理 `-MaximumRedirection` 或用 .NET `HttpClient`。

---

## 4. pip 约束文件里写中文注释 → `UnicodeDecodeError: 'gbk' codec`

**症状**
某个插件首次安装 Python 依赖时报：

```text
UnicodeDecodeError: 'gbk' codec can't decode byte 0xa6 in position 44
```

**根因**
安装流程会生成一个 pip 约束文件（constraints），当时用**无 BOM 的 UTF-8 + 中文注释**写入。
pip 在中文 Windows 上按 GBK 读取该文件，读到中文字节就崩。

**解决**
- 约束文件内容保持**纯 ASCII**（注释也用英文），或写成带 BOM 的 UTF-8。
- 经验法则同第 1 条：**交给外部工具读的文本文件，不要写非 ASCII**。

---

## 5. 模型下拉按字母排序 → 默认选中动漫模型；且风格按钮不切模型

**症状**
用户点的是「写实」风格，出来的图却像半写实油画 / 插画，怎么调都不像照片。

**根因**
两个问题叠加：

1. 模型下拉的选项来自 ComfyUI 返回的文件列表，**按字母排序**。动漫模型
   （`AWPainting…`）正好排在第一位，于是页面一打开，**默认模型就是动漫模型**。
2. 当时点风格按钮**只会设置风格、不会切换模型**。所以用户点「写实」时，
   实际组合是「**动漫模型 + `photorealistic, 85mm lens…` 提示词**」——
   两个方向互相拉扯，结果就是那种"油画感"。

**解决**
- 首次加载时，把模型下拉**按当前风格初始化**（而不是取列表第一项）。
- 点风格按钮**连带切换模型**，行为可预期。
- 在模型下拉下方显示一行明确提示：`风格「写实」→ 模型 xxx；会附加提示词：…`，
  切换风格时实时更新，让用户看得见"这个风格到底做了什么"。
- 另外把风格与模型的对应关系写进 `STYLES`，一处配置、界面与服务端一致。

---

## 6. 直出高分辨率导致构图涣散、人物双头多手

**症状**
把出图尺寸直接拉到 1024×1536 时：风景主体变小、细节发空、画面出现重复堆叠；
人物题材会出现双头、多手、多腿。

**根因**
SD1.5 在 **512×512** 附近训练，推理分辨率远超训练分布时，模型会把画面"当成多张图"来理解，
于是复制主体、结构崩坏。

**解决**
用**两遍画法（hires fix）**代替直出高分辨率：

```text
KSampler（基准尺寸，如 512×768）
  → LatentUpscale（bislerp，放大到目标尺寸）
  → KSampler（denoise < 1，补细节）
  → VAEDecode
```

- 1.5×：第二遍 `denoise = 0.40`
- 2×：第二遍 `denoise = 0.45`
- 第二遍步数取 `max(10, round(步数 × 0.7))`
- 同尺寸下，两遍画法的构图和细节都明显优于直出。

---

## 7. ControlNet 会把参考图硬缩放到出图尺寸 → 结构被拉伸

**症状**
用 ControlNet 时，人物被**拉长或压扁**，结构比例不对。

**根因**
`ControlNetApplyAdvanced` 内部会把控制图（预处理后的结构图）缩放到**出图尺寸**。
如果参考图比例与所选画面比例不一致，这个缩放就是**非等比**的 —— 结构被硬抻，输出继承了这个变形。

**解决**
按参考图比例反推**出图尺寸**：

- 以用户所选尺寸的**面积**为预算，套用参考图的宽高比 → 得到等比的出图尺寸
- 对齐到 8 的倍数（VAE 下采样要求）
- 限制长边 ≤ 1024、短边 ≥ 384，避免出现 SD1.5 处理不了的极端比例
- 换算结果与用户所选不一致时，在结果里标注「已按参考图比例把出图尺寸改成 WxH（否则结构会被拉伸）」

---

## 8. 扩图用 inpaint ControlNet：遮罩区必须是**灰色**，喂黑底会补出一整块灰

**症状**
给扩图挂上 `control_v11p_sd15_inpaint` 后，**新补的区域变成一整块纯灰色**，什么都没有生成。

**根因**
该 ControlNet 是专门为 inpainting 训练的，它要求控制图里**待补区域被填成灰色**（0.5），
以此告诉模型"这里是要生成的地方"。而 `ImagePadForOutpaint` 输出的图像里，
补出来的区域是**黑色**（0）。把黑底直接喂给这个 ControlNet，
它就把"保持黑色"当成结构约束强加给采样器 → 输出一片灰。

**解决**
在两者中间插入 `InpaintPreprocessor`，它专门负责把遮罩区渲染成灰色：

```text
ImagePadForOutpaint ─┬─→ InpaintPreprocessor(image, mask) ─→ ControlNetInpaintingAliMamaApply
                     └─→ VAEEncodeForInpaint ─→ KSampler
```

参数上使用 `black_pixel_for_xinsir_cn = False`（灰色，对应 ali-vilab 版 inpaint 模型；
该选项为 True 时填充黑色，是给另一族 ControlNet 用的）。

---

## 9. 扩图做「半身补全身」时不缩小原图 → 腿被压扁 / 截断

**症状**
上传半身照，选「向下补」补全身，结果：

- 不缩小原图时：补出裤子的上半段，**脚出不来**，或者腿被压扁；
- 加大补幅也没用，反而画布越长越崩。

**根因**
原图**占满了画布**，补出来的空间相对于人物太小。要放下完整的下半身，
画面里的人必须"变小"（换个取景），否则模型只能在有限的像素里把腿压缩或截断。
而画布又不能无限拉长（SD1.5 在极端长宽比下会崩）。

**解决**
提供「**缩小原图腾空间**」选项：

- 把原图缩到画布高度的约 **42%**，水平居中，两侧各补少量像素，下方留出主要空间
- 画布长边上限 1280
- 实测（512×768 半身图 → 画布 512×1280）：勾上后能得到**完整全身**（裤子 + 鞋 + 地面阴影），
  接缝看不出；代价是人物变小、脸占的像素变少

---

## 10. 大视频模型物理上装不下 → 换小模型

**症状**
加载某套大视频模型时无法完成，显存/内存直接爆掉，生成失败。

**根因**
该套权重合计约 **39.5 GB**（扩散模型 19.53 GB + 文本编码器 14.61 GB +
视频 VAE 4.85 GB + 音频 VAE 0.56 GB），而目标机器是：

| 项 | 容量 |
| --- | --- |
| 显存 | 12 GB |
| 内存 | 31.2 GB（可用约 15.3 GB） |
| 页面文件上限 | 2 GB |

**权重装不下，这不是接线问题。** 即使把页面文件调大，靠硬盘流式加载也会慢到不可用。

**解决**
改用 **Wan 2.2 5B TI2V**：约 **18 GB**（扩散模型 10.00 GB + fp8 文本编码器 6.74 GB +
VAE 1.41 GB），且**一个模型同时支持文生视频与图生视频**（首帧可选）。实测可在上述机器上跑通：
832×480、45 帧（约 2 秒 @24fps）、20 步，耗时约 52–64 秒。

选型提示：优先选 fp8 / 量化版的文本编码器（如 `umt5_xxl_fp8_e4m3fn_scaled`，6.74 GB，
而非 fp16 的 11.37 GB），能省下近 5 GB。

---

## 11. ControlNet 预处理器权重下不来：设了 `HF_ENDPOINT` 也没用

**症状**
首次使用 深度 / 姿态 / 线稿 时，ComfyUI 报：

```text
An error happened while trying to locate the file on the Hub and we cannot
find the requested files in the local cache.
```

**根因**
`comfyui_controlnet_aux` 的 `custom_hf_download()` 逻辑是：

1. 先看 `ckpts/<仓库名>/<文件名>` 是否存在；
2. 不存在才调用 `hf_hub_download()` 去 HuggingFace 下。

而直连 HuggingFace 不通。**给 ComfyUI 进程设置 `HF_ENDPOINT` 指向镜像后仍然失败** ——
该库的这条下载路径不生效（走到网络请求后依然报找不到文件）。

**解决**
不要跟库的下载逻辑较劲，**直接把权重预置到它要找的位置**，让它第 1 步就命中本地文件：

```text
<ComfyUI 目录>/ComfyUI/custom_nodes/comfyui_controlnet_aux/ckpts/
├── depth-anything/Depth-Anything-V2-Small/depth_anything_v2_vits.pth
└── lllyasviel/Annotators/
    ├── body_pose_model.pth
    ├── hand_pose_model.pth
    ├── facenet.pth
    ├── sk_model.pth
    └── sk_model2.pth
```

用 `curl.exe -L` 从镜像把这 6 个文件（合计约 614 MB）拉到上述路径即可，
之后 `from_pretrained()` 直接命中本地文件，不再联网。
（镜像偶发 429，加重试参数即可，最终按文件大小核对是否完整。）

---

## 12. 重启界面服务会打断浏览器里正在等待的请求

**症状**
用户点了「生成视频」，界面报错；但去 ComfyUI 的历史记录一看，任务**其实成功完成**了，
输出文件也正常写了出来。

**根因**
浏览器此时正挂在 `POST /api/generate` 上等待回复（一个长连接）。
如果这时界面服务进程被重启/杀掉，**连接当场断掉**，页面只能报错。
而 ComfyUI 是**独立进程**，任务不受影响，照常跑完并落盘。

**解决**
- 页面在捕获到网络错误后，**自动去「最近生成」接口轮询**（每 5 秒一次，最多 2 分钟），
  发现比断线前更新的文件就直接显示出来，并提示「连接中断前任务已完成」。
- 运维约定：**重启界面服务前，先确认没有任务在跑**。
- 这一点也说明了一个设计事实：**结果是 ComfyUI 写的文件**，所以只要文件写出来了，
  界面服务换一个进程重新起来也能找回，不会真的丢结果。

---

## 13. CSS 只给 `.stage img` 写了宽度限制，忘了 `.stage video`

**症状**
预览里出现**横版视频**时，整个页面可以**左右滚动**（内容被撑宽约 130px）。

**根因**
加视频支持时，CSS 里只有：

```css
.stage img { max-width:100%; max-height:72vh; ... }   /* 图片有宽度限制 */
.stage video { ... }                                   /* 视频漏了 max-width */
```

预览区所在栏宽约 700px，而横版视频天然宽度 832px，元素没有宽度约束就顶破了容器和页面。

**解决**
- 统一限制：`.stage img, .stage video { max-width:100%; max-height:72vh; }`
- 加全局兜底，防止以后再犯：`img, video, canvas { max-width:100%; }`
- **验证方式**：用无头浏览器打开 `?diag=1`，页面会把 `scrollWidth / clientWidth` 和
  "最宽的元素"显示出来；`scrollWidth == clientWidth` 才算没有横向溢出。

---

## 14. 给右栏加 `overflow:auto` 做吸附 → 出现两条滚动条

**症状**
想让「左边滚动控制项时右边预览不动」，改完之后页面出现**两条滚动条**：
页面一条 + 右栏自己一条。

**根因**
为了实现吸附，同时给右栏加了 `position:sticky`、`max-height:calc(100vh - …)` 和 `overflow:auto`。
右栏内部可滚动 → 自带一条滚动条，与页面滚动条并存。

**解决**
- **只保留吸附**：`.cols > .card:last-child { position:sticky; top:18px; align-self:start; }`
  不加 `overflow`，全页只留一条滚动条。
- 为了让整张右卡能塞进视口（不然「吸住了但看不到底」），把预览高度压到 `56vh`、
  最近生成限制为 8 个缩略图。
- 吸附只在宽屏启用（`@media (min-width:901px)`），窄屏单列布局下不启用。

---

## 15. Windows 图标缓存：换掉 `icon.ico` 桌面图标不变

**症状**
替换了 `.ico` 文件、快捷方式也确认指向它，但桌面图标还是旧的（甚至还是空白）。

**根因**
Windows 的图标缓存**按文件路径/文件名**缓存。同名文件被替换后，系统仍然用缓存里的旧图标。

**解决**
- **换一个新文件名**（例如 `icon-v2.ico`），把快捷方式重新指向新文件；
- 再执行 `ie4uinit.exe -show` 刷新图标缓存；
- 必要时重启资源管理器。

推论：以后要换图标，**永远用新文件名**，不要覆盖同名文件。

---

## 16. 没有声明 favicon，服务端也没有 `/favicon.ico` 路由

**症状**
以独立应用窗口打开时，**窗口标题栏 / 任务栏的图标是空白的**（页面上方的 logo 却正常显示）。

**根因**
两处都缺：

1. 页面 `<head>` 里没有 `<link rel="icon">`，浏览器只能去请求 `/favicon.ico`；
2. 服务端只处理了 `/logo.png`，**没有 `/favicon.ico` 这个路由** → 请求 404。

于是浏览器拿不到任何图标，标题栏和任务栏就是空的。

**解决**
- 页面里声明三个：`<link rel="icon" type="image/png" href="/logo.png">`、
  `<link rel="shortcut icon" href="/favicon.ico">`、`<link rel="apple-touch-icon" href="/logo.png">`
- 服务端 `/favicon.ico` 返回**真正的 `.ico`**（`image/x-icon`），读不到时回退到 `logo.png`。
- 浏览器可能把"这个站点没有图标"缓存下来：如果仍空白，删掉运行时生成的
  `app-profile/` 目录再启动一次（会自动重建）。

---

## 17. 补 0 像素被当成 8 像素，画布超出上限

**症状**
扩图算出来的画布尺寸总是比预期大 16px（例如预期的 512×1024 变成 528×1032），
偶尔会刚好越过画布上限。

**根因**
尺寸对齐函数写成了「最小值 8」：

```python
def snap8(v):
    return max(8, int(round(v / 8.0)) * 8)   # snap8(0) 返回 8，而不是 0
```

而扩图里"不补的那几条边"传进去的就是 0，结果每条边都被补了 8px。

**解决**
把最小值做成参数，补边时允许 0：

```python
def snap8(v, minimum=8):
    return max(minimum, int(round(v / 8.0)) * 8)

# 补边：snap8(pl, 0)；宽高：snap8(w)（仍要求至少 8）
```

教训：**"对齐并取最小值"这类函数，要显式考虑输入为 0 的语义**，
不要用默认下限悄悄改变业务含义。

---

## 18. 用 PowerShell 解析 ComfyUI 的大 JSON 容易取错结构

**症状**
想列出 ComfyUI 支持哪些节点，用 PowerShell 处理 `/object_info` 的返回，
结果得到「节点总数: 1」——明显不对，浪费了一轮排查。

**根因**
`/object_info` 返回的是一个很大的嵌套 JSON（上千个节点）。用 PowerShell 的
`PSObject.Properties` 去数键、或在管道里做多层属性访问时，很容易因为自动展开、
类型转换或输出截断而拿到错误结果，且**看不出错**。

**解决**
- 把大 JSON 交给 **Python** 处理：`json.loads(...)` 后直接遍历键，
  语义清晰、不受 PowerShell 管道行为影响。
- PowerShell 只负责发起请求或调 Python，不做复杂 JSON 加工。
- 同理：查询结构不确定时，**先把原始返回落到文件里**再分析，而不是在管道里猜。

---

## 19. 把 ComfyUI 目录名写死在代码里 → 换个整合包就找不到

**症状**
程序只能在「与本仓库同级、并叫 `ComfyUI-aki-v3.2`」的布局下工作。
换成官方便携版、别的整合包，或者把仓库挪到别处，就报找不到 ComfyUI / 找不到 Python。

**根因**
最初把相对路径写死了：

```python
COMFY_ROOT = os.path.abspath(os.path.join(HERE, '..', 'ComfyUI-aki-v3.2'))
```

而现实里各家的布局差异很大：

- 官方便携版：`python_embeded/python.exe`
- 国内整合包：`python/python.exe`
- 自建 / 虚拟环境：`venv/Scripts/python.exe` 或 `python/bin/python3`
- 目录名本身更是随意

**解决**
改成**三级解析 + 候选式查找**（实现细节见 `docs/ARCHITECTURE.md` 4.9）：

1. `config.json` 的 `comfy_root`
2. 环境变量 `PICMOTION_COMFY_ROOT`
3. 自动探测：本目录 / 上一级 / 上两级，以及这些目录的下一层；
   命中条件 = 有 `ComfyUI/main.py` **且**自带 Python（候选路径覆盖上面几种布局）

配套两件事：

- 解释器路径在启动时写进 `python.txt`，`start-app.bat` 优先复用它，
  读不到再对常见布局逐个兜底
- 三级都找不到时**打印三种指定方式并以退出码 1 退出**，而不是带着错误配置硬跑

**教训**：脚本里不要出现「同级目录名」这类机器相关假设 ——
**要么可配置，要么可探测**，两者都做不到才写死。
