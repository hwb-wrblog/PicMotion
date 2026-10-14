# 模型从哪来、放哪里

本文说明本程序需要哪些模型文件、**从哪个仓库下载**、**放进哪个目录**。
所有仓库地址与文件大小都经过实际查询核对（2026-10 核对），不是凭印象写的。

---

## 〇、两条路线，先选一条

### 路线 A：用一键整合包（省事，推荐）

**一键整合包下载地址：<https://www.bilibili.com/opus/1233418589167419397>**

本程序的开发和测试环境就是这个包（秋叶 ComfyUI 整合包 v3.2），一步到位：
ComfyUI 本体 + 自带 Python + 绘世启动器 + 一批常用自定义节点 + 部分常用模型。

- 压缩包解压密码：`bilibili-秋葉aaaki`
- 解压后的目录名：`ComfyUI-aki-v3.2`（里面还有一层同名目录，真正含 `ComfyUI/main.py` 的是**里层**）
- 启动方式：双击 `绘世启动器.exe`（图形化）或直接用 `python\python.exe ComfyUI\main.py`

> 完整的下载与安装步骤（解压密码、嵌套目录、首次启动、自带节点与模型盘点、常见问题）
> 见 **[INSTALL-PACKAGE.md](INSTALL-PACKAGE.md)**。

把本仓库放在这个目录的**同级**即可，程序会自动找到它：

```text
<任意父目录>/
├── ComfyUI-aki-v3.2/          # 整合包解压出来的目录
│   └── ComfyUI-aki-v3.2/      # 真正的 ComfyUI 根目录（含 python/ 与 ComfyUI/）
└── simple-ui/                 # 本仓库
```

整合包通常已自带 SD1.5 底模和 ControlNet，**先启动一次看看有什么**，缺什么再按下表补。

### 路线 B：自己装

用官方 [ComfyUI](https://github.com/comfyanonymous/ComfyUI) 自己配环境，然后按下面第二节的表下模型。
需要额外装的自定义节点见 [README 的前置条件](../README.md#环境与前置条件)。

---

## 一、镜像说明（国内网络）

下文所有下载地址都用 **`hf-mirror.com`**，它是 `huggingface.co` 的国内镜像，
路径与官方完全一致，**把域名换掉即可**。官方地址也能用，只是国内通常连不上。

```text
https://hf-mirror.com/<仓库名>/resolve/main/<文件路径>
https://huggingface.co/<仓库名>/resolve/main/<文件路径>     # 官方地址
```

> **下载务必用 `curl.exe -L`**。
> PowerShell 的 `Invoke-WebRequest` / `HttpWebRequest` **不跟随 HTTP 308 重定向**，
> 用它们下镜像会拿到 0 字节或直接失败 —— 这个坑详见 [PITFALLS.md](PITFALLS.md)。

---

## 二、出图必需

### SD1.5 底模 → `ComfyUI/models/checkpoints/`

| 文件名 | 大小 | 用途 | 来源 |
| --- | --- | --- | --- |
| `majicmixRealistic_v7.safetensors` | 2.13 GB | **写实 / 电影感 / 不加风格** 用这个 | [`digiplay/majicMIX_realistic_v7`](https://hf-mirror.com/digiplay/majicMIX_realistic_v7) ✅ 已核对 |
| `AWPainting_v1.2.safetensors` | 约 2 GB | 动漫 / 插画 用这个 | 整合包自带；**未在 HuggingFace 上核实到官方仓库**，它多见于 Civitai，请自行搜索或直接用整合包里的 |
| `anything-v5-PrtRE.safetensors` | 约 2 GB | 动漫向备选，可不下 | 同上，未核实 |

> 只要有一个能用的 SD1.5 底模就能出图。想省事就只用 `majicmixRealistic_v7`，
> 然后把 `serve.py` 里 `STYLES['anime']['model']`、`STYLES['painting']['model']` 也改成它。

**下载示例**（写实底模）：

```powershell
curl.exe -L --retry 5 --retry-all-errors -C - `
  -o "<ComfyUI 目录>\ComfyUI\models\checkpoints\majicmixRealistic_v7.safetensors" `
  "https://hf-mirror.com/digiplay/majicMIX_realistic_v7/resolve/main/majicmixRealistic_v7.safetensors"
```

---

## 三、ControlNet（要「锁构图换内容」才需要）→ `ComfyUI/models/controlnet/`

来源：[`comfyanonymous/ControlNet-v1-1_fp16_safetensors`](https://hf-mirror.com/comfyanonymous/ControlNet-v1-1_fp16_safetensors) ✅ 已核对，6 个文件都在

| 文件名 | 大小 | 对应功能 |
| --- | --- | --- |
| `control_v11p_sd15_canny_fp16.safetensors` | 0.72 GB | 边缘 Canny |
| `control_v11f1p_sd15_depth_fp16.safetensors` | 0.72 GB | 深度 Depth |
| `control_v11p_sd15_openpose_fp16.safetensors` | 0.72 GB | 姿态 OpenPose |
| `control_v11p_sd15_lineart_fp16.safetensors` | 0.72 GB | 线稿 LineArt |
| `control_v11p_sd15_scribble_fp16.safetensors` | 0.72 GB | 涂鸦 Scribble |
| `control_v11p_sd15_inpaint_fp16.safetensors` | 0.72 GB | **扩图补全必需** |

> 也可以用原始 `.pth` 版（[`lllyasviel/ControlNet-v1-1`](https://hf-mirror.com/lllyasviel/ControlNet-v1-1)，每个约 1.45 GB），
> 但 fp16 安全张量版体积只有一半、加载更快，推荐用上面这套。
> 文件名要和 `serve.py` 里 `CONTROLNET[*]['model']`、`OUTPAINT_CN` 一致；换成别的名字就同步改那里。

```powershell
$base = "https://hf-mirror.com/comfyanonymous/ControlNet-v1-1_fp16_safetensors/resolve/main"
$dst  = "<ComfyUI 目录>\ComfyUI\models\controlnet"
foreach ($f in @('control_v11p_sd15_canny_fp16.safetensors',
                 'control_v11f1p_sd15_depth_fp16.safetensors',
                 'control_v11p_sd15_openpose_fp16.safetensors',
                 'control_v11p_sd15_lineart_fp16.safetensors',
                 'control_v11p_sd15_scribble_fp16.safetensors',
                 'control_v11p_sd15_inpaint_fp16.safetensors')) {
  curl.exe -L --retry 5 --retry-all-errors -C - -o "$dst\$f" "$base/$f"
}
```

---

## 四、视频（可选）→ 三个文件，放三个不同目录

来源：[`Comfy-Org/Wan_2.2_ComfyUI_Repackaged`](https://hf-mirror.com/Comfy-Org/Wan_2.2_ComfyUI_Repackaged) ✅ 已核对

| 仓库里的路径 | 大小 | 放到 |
| --- | --- | --- |
| `split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` | 10.00 GB | `ComfyUI/models/diffusion_models/` |
| `split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6.74 GB | `ComfyUI/models/text_encoders/` |
| `split_files/vae/wan2.2_vae.safetensors` | 1.41 GB | `ComfyUI/models/vae/` |

合计 **18.15 GB**。选 **fp8** 的文本编码器（6.74 GB），不要选 fp16 那个（11.37 GB）。

```powershell
$base = "https://hf-mirror.com/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main"
$m    = "<ComfyUI 目录>\ComfyUI\models"
$files = @(
  @{ p='split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors';     d="$m\diffusion_models" },
  @{ p='split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors'; d="$m\text_encoders" },
  @{ p='split_files/vae/wan2.2_vae.safetensors';                           d="$m\vae" }
)
foreach ($f in $files) {
  New-Item -ItemType Directory -Force -Path $f.d | Out-Null
  curl.exe -L --retry 5 --retry-all-errors -C - -o (Join-Path $f.d (Split-Path $f.p -Leaf)) "$base/$($f.p)"
}
```

**显存不够就别硬上**：Wan 2.2 5B 已经是为了能在 12 GB 显存上跑而挑的小模型。
更小的选择（本程序未适配，需要自己改 `build_video_workflow`）：
Wan 2.1 T2V 1.3B（约 3 GB 底模）、LTX-Video 2B。判断标准见 [HARDWARE.md](HARDWARE.md)。

---

## 五、预处理器权重（用 depth / openpose / lineart 才需要）

ControlNet 的「控制方式」里，**Canny 和 Scribble 是纯 OpenCV 算法，不需要任何权重**；
其它三种需要预处理器模型，由自定义节点 `comfyui_controlnet_aux` 提供。

**关键点**：这个库自己下载权重的逻辑在你网络受限时会失败（它读不到 `HF_ENDPOINT`），
所以**直接把文件按它期望的路径放好**，它就会跳过下载。目录结构必须完全一致：

`ComfyUI/custom_nodes/comfyui_controlnet_aux/ckpts/<仓库名>/<文件名>`

| 目标路径（相对 ckpts 目录） | 大小 | 来源 |
| --- | --- | --- |
| `depth-anything/Depth-Anything-V2-Small/depth_anything_v2_vits.pth` | 0.10 GB | [`depth-anything/Depth-Anything-V2-Small`](https://hf-mirror.com/depth-anything/Depth-Anything-V2-Small) ✅ |
| `lllyasviel/Annotators/body_pose_model.pth` | 0.21 GB | [`lllyasviel/Annotators`](https://hf-mirror.com/lllyasviel/Annotators) ✅ |
| `lllyasviel/Annotators/hand_pose_model.pth` | 0.15 GB | 同上 |
| `lllyasviel/Annotators/facenet.pth` | 0.15 GB | 同上 |
| `lllyasviel/Annotators/sk_model.pth` | 0.02 GB | 同上（线稿用） |
| `lllyasviel/Annotators/sk_model2.pth` | 0.02 GB | 同上（线稿用） |

合计约 **0.65 GB**。

```powershell
$ck = "<ComfyUI 目录>\ComfyUI\custom_nodes\comfyui_controlnet_aux\ckpts"
$items = @(
  @{ r='depth-anything/Depth-Anything-V2-Small'; f='depth_anything_v2_vits.pth' },
  @{ r='lllyasviel/Annotators'; f='body_pose_model.pth' },
  @{ r='lllyasviel/Annotators'; f='hand_pose_model.pth' },
  @{ r='lllyasviel/Annotators'; f='facenet.pth' },
  @{ r='lllyasviel/Annotators'; f='sk_model.pth' },
  @{ r='lllyasviel/Annotators'; f='sk_model2.pth' }
)
foreach ($i in $items) {
  $dir = Join-Path $ck ($i.r -replace '/', '\')
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  curl.exe -L --retry 5 --retry-all-errors -o (Join-Path $dir $i.f) "https://hf-mirror.com/$($i.r)/resolve/main/$($i.f)"
}
```

---

## 六、可选：让高清更锐

本程序的「高清 1.5× / 2×」用的是**潜空间放大 + 第二遍重绘**（两遍画法），不依赖任何放大模型。

想更进一步，可以放一个 ESRGAN 类放大模型到 `ComfyUI/models/upscale_models/`，
再用 ComfyUI 的 `UltimateSDUpscale` 之类节点做像素级放大。
**本程序尚未接入这个流程**，属于可自行扩展的部分。

---

## 七、一张总表

| 用途 | 总下载量 | 必需？ |
| --- | --- | --- |
| SD1.5 底模 ×1 | 约 2 GB | **必需** |
| ControlNet ×6 | 4.3 GB | 用「锁构图换内容 / 扩图」才需要 |
| 预处理器权重 ×6 | 0.65 GB | 用 depth / openpose / lineart 才需要 |
| 视频三件套 | 18.15 GB | 要出视频才需要 |
| **最小可用（只出图）** | **约 2 GB** | |
| **出图 + 视频全功能** | **约 25 GB** | |

> 整合包（路线 A）通常已经包含底模和 ControlNet，实际需要补的往往只有视频那 18 GB。
