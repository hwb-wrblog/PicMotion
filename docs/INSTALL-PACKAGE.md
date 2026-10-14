# 一键整合包的安装过程

本程序本身只是一个界面，**必须先有一个能跑的 ComfyUI**。
最省事的办法就是用一键整合包，本文把整个过程写清楚。

---

## 一、这是什么、从哪来

| 项 | 内容 |
| --- | --- |
| 整合包 | 秋叶的 **ComfyUI 整合包 v3.2**（ComfyUI + 自带 Python + 绘世启动器 + 常用节点 + 部分模型） |
| **下载地址** | <https://www.bilibili.com/opus/1233418589167419397> |
| 作者主页 | <https://space.bilibili.com/12566101>（bilibili@秋葉aaaki） |

> **作者在包内的原话**（文件 `bilibili@秋葉aaaki.txt`）：
> 「AI 绘画内核【ComfyUI】为开源项目，以及启动器【绘世】是完全免费的软件，**严禁倒卖**。如有发现，请及时举报。」
>
> 请从这里给出的渠道获取，不要购买任何倒卖的副本。

**常用模型分享网盘**（出自包内 `使用教程+常见问题.txt`）：
<https://pan.quark.cn/s/32f374eef667>

---

## 二、安装步骤

### 1. 下载

从上面的动态页进入网盘，下载压缩包 **`ComfyUI-aki-v3.2.7z`**。
体积很大（几十 GB），建议在网络空闲时下。

### 2. 解压

- 需要一个支持 **7z** 的解压工具（7-Zip、Bandizip、WinRAR 都可以）。
- **解压密码：`bilibili-秋葉aaaki`**（注意「秋葉」是繁体字，建议直接复制）
- 解压后会出现**同名嵌套目录**：

```text
ComfyUI-aki-v3.2/              ← 外层，解压出来的
└── ComfyUI-aki-v3.2/          ← 里层，这才是真正的 ComfyUI 根目录
    ├── ComfyUI/               ← 主程序与模型
    ├── python/                ← 自带的 Python
    ├── 绘世启动器.exe
    ├── 使用教程+常见问题.txt
    └── bilibili@秋葉aaaki.txt
```

- 解压后整体约 **80 GB**，请留足磁盘空间。

### 3. 首次启动

两种方式，任选：

**方式 A：图形化启动器（推荐给新手）**

双击 **`绘世启动器.exe`**，在界面里启动。
包内说明明确写了：**遇到问题请前往启动器内「疑难解答」进行扫描**。

**方式 B：命令行直接启动（本程序内部就是这么做的）**

```bat
python\python.exe -s ComfyUI\main.py --windows-standalone-build --disable-auto-launch --port 8188
```

### 4. 验证装好了

浏览器打开 <http://127.0.0.1:8188>，能看到 ComfyUI 的节点界面就算成功。
**这个端口（8188）就是本程序默认要连的地址。**

---

## 三、把本程序接上去

1. 把本仓库放到整合包的**同级**目录（跟 `ComfyUI-aki-v3.2` 并排）：

```text
<任意父目录>/
├── ComfyUI-aki-v3.2/          ← 解压得到的（外层）
│   └── ComfyUI-aki-v3.2/      ← 真正的根（含 python/ 与 ComfyUI/）
└── simple-ui/                 ← 本仓库
```

2. 双击 **`start-app.bat`**。
3. 如果界面提示「ComfyUI 还没启动」，点一次「生成」，程序会自己把它拉起来
   （第一次约 10–60 秒）。

> 程序会自动找到 ComfyUI 目录。放在别处也能用，用 `config.json` 指路即可 ——
> 见 [README 的「配置从哪来」](../README.md#配置从哪来)。

---

## 四、装完就有 / 还需要补什么

以下都是**从解压出来的包实测**得到的。

### 自带运行时

| 项 | 版本 |
| --- | --- |
| Python | **3.13.11** |
| torch | **2.13.0+cu130**（CUDA 可用） |
| transformers | **4.57.6** |

### 自带自定义节点（11 个）

```text
ComfyUI-GGUF              ComfyUI-Impact-Pack       ComfyUI-LTXVideo
ComfyUI-Manager           ComfyUI-RMBG              ComfyUI-VideoHelperSuite
ComfyUI-WanVideoWrapper   comfyui_controlnet_aux    ComfyUI_Custom_Nodes_AlekPet
ComfyUI_IPAdapter_plus    ComfyUI_UltimateSDUpscale
```

与本程序的关系：

| 节点 | 对本程序的作用 |
| --- | --- |
| `comfyui_controlnet_aux` | ControlNet 的 **Depth / OpenPose / LineArt** 预处理要用它（还需补权重，见 [MODELS.md](MODELS.md) 第五节） |
| `ComfyUI-Manager` | 装/更新节点，方便 |
| `ComfyUI-VideoHelperSuite`、`ComfyUI-WanVideoWrapper`、`ComfyUI-LTXVideo` | 视频相关。本程序走的是 ComfyUI **原生** Wan 2.2 节点，不依赖它们 |
| 其余（GGUF / Impact-Pack / RMBG / IPAdapter / UltimateSDUpscale / AlekPet） | 本程序暂未使用，留着以后扩展 |

### 自带模型盘点

| 目录 | 个数 | 体积 |
| --- | --- | --- |
| `checkpoints` | 5 | 5.96 GB |
| `controlnet` | 15 | 9.42 GB |
| `vae` | 8 | 8.12 GB |
| `diffusion_models` | 3 | 28.84 GB |
| `text_encoders` | 3 | 20.88 GB |
| `loras` / `embeddings` / `upscale_models` | 2 / 3 / 1 | 很小 |
| **`models` 合计** | | **73.3 GB** |

**整合包整体 79.8 GB。**

- ✅ **出图和 ControlNet 开箱即用**：底模和 ControlNet（含扩图要用的 inpaint）都齐了。
- ⚠ **视频模型要注意**：包里那套 **minimax_h3**（主模型 19.53 GB + 文本编码器 14.61 GB，
  合计约 34 GB）**本程序用不上** —— 它在 12 GB 显存 + 32 GB 内存的机器上**装不下**
  （原因见 [HARDWARE.md](HARDWARE.md)）。
  本程序用的是更小的 **Wan 2.2 5B TI2V**（合计 18.15 GB），按
  [MODELS.md](MODELS.md) 第四节补下即可。
  确定不玩 minimax_h3 的话，删掉它能腾出约 **34 GB**。

---

## 五、常见问题

| 现象 | 处理 |
| --- | --- |
| 解压提示密码错误 | 密码是 `bilibili-秋葉aaaki`；「秋葉」是繁体字，直接复制粘贴 |
| 找不到 `ComfyUI\main.py` | 你打开的是**外层**目录，往里再进一层 |
| 启动时报缺依赖 / 各种报错 | 用**启动器内的「疑难解答」**扫描（作者原话） |
| 想再下别的模型 | 作者的模型分享网盘：<https://pan.quark.cn/s/32f374eef667> |
| 下载太慢 | 压缩包本身很大，属正常；单个模型可以改用 [MODELS.md](MODELS.md) 里的 hf-mirror 镜像单独下 |
| 8188 端口被占用 | 本程序默认连 8188；用启动器换端口后，改 `config.json` 的 `comfy_url` 同步 |
| 想换本程序的端口 | 改 `config.json` 的 `port`（`start-app.bat` 会读 `serve.py` 写出的 `port.txt`） |

---

## 六、包里自带的三个说明文件

作者放在包根目录，建议扫一眼：

| 文件 | 内容 |
| --- | --- |
| `使用教程+常见问题.txt` | ComfyUI 官方示例、基础工作流仓库、模型分享网盘、**疑难解答入口** |
| `bilibili@秋葉aaaki.txt` | 作者信息 + 上面那段免费声明 |
| `用户协议.txt` | 使用条款 |
