#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
simple-ui —— 极简画影：ComfyUI 的极简出图 / 出视频界面（本地小服务，只用标准库）

它做的事：
  浏览器打开一个只有「输入框 + 风格按钮 + 出图」的页面  →  本服务把请求转成
  ComfyUI 的工作流，提交给本机 ComfyUI（127.0.0.1:8188），取回图片并展示。

出图链路（顺序很重要）：
  用户输入 → ① 违规检测与拦截（moderate） → ② 组装工作流 → ③ 提交 ComfyUI → ④ 取图展示
  ① 不通过就直接拒绝，请求**不会**到达 ComfyUI。

扩展点：见文件里的 moderate() / BLOCK_PATTERNS —— 换成自己的规则或外部分类器即可。
"""

import base64
import json
import os
import re
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# 配置：ComfyUI 目录怎么找
#   顺序：config.json → 环境变量 PICMOTION_COMFY_ROOT → 自动探测
#   自动探测会看「本目录 / 上一级 / 上两级」以及这些目录的下一层，
#   找"同时有 ComfyUI/main.py 和自带 python"的那一层（覆盖各家整合包布局）。
#   找不到也不崩：页面会提示你去建 config.json。
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, 'config.json')


def _load_config():
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


CFG = _load_config()


def _looks_like_comfy_root(d):
    """整合包根目录：里面有 ComfyUI/main.py，并且带一个自带的 python。"""
    if not d or not os.path.isfile(os.path.join(d, 'ComfyUI', 'main.py')):
        return False
    return any(os.path.isfile(os.path.join(d, *rel)) for rel in (
        ('python', 'python.exe'), ('python_embeded', 'python.exe'),
        ('python', 'bin', 'python3'), ('venv', 'Scripts', 'python.exe'),
    ))


def _detect_comfy_root():
    cands, base = [], HERE
    for _ in range(3):
        parent = os.path.dirname(base)
        if not parent or parent == base:
            break
        cands.append(parent)
        base = parent
    for d in list(cands) + [HERE]:
        try:
            for name in os.listdir(d):
                p = os.path.join(d, name)
                if os.path.isdir(p):
                    cands.append(p)
        except Exception:
            pass
    for d in cands:
        if _looks_like_comfy_root(d):
            return d
    return ''


def _find_python(root):
    """找到能跑 ComfyUI 的 python（优先整合包自带的）。"""
    for rel in (('python', 'python.exe'), ('python_embeded', 'python.exe'),
                ('python', 'bin', 'python3'), ('venv', 'Scripts', 'python.exe'),
                ('venv', 'bin', 'python')):
        if root:
            p = os.path.join(root, *rel)
            if os.path.isfile(p):
                return p
    return 'python'


COMFY_ROOT = (CFG.get('comfy_root') or os.environ.get('PICMOTION_COMFY_ROOT')
              or _detect_comfy_root())
COMFY_OUTPUT = os.path.join(COMFY_ROOT, 'ComfyUI', 'output') if COMFY_ROOT else ''
COMFY_INPUT = os.path.join(COMFY_ROOT, 'ComfyUI', 'input') if COMFY_ROOT else ''
# 生成的图先落进这个子目录当「预览缓存」，不混进你的图片库；
# 想留哪张，在页面上点「保存到本地」下载到你自己选的位置。
PREVIEW_SUBDIR = 'simpleui_preview'
PY_EXE = _find_python(COMFY_ROOT)
# 同目录下无控制台版的解释器（给 start-app.bat 用）
PYW_EXE = (os.path.join(os.path.dirname(PY_EXE), 'pythonw.exe')
           if PY_EXE.lower().endswith('python.exe') else PY_EXE)


def _remember_runtime():
    """把解释器路径和实际端口写进 python.txt / port.txt。

    这是给 start-app.bat 用的：批处理没法解析 config.json，所以由服务端把结果落成
    两个纯文本文件，启动脚本直接读。它们只是缓存，删掉会自动重建。
    """
    try:
        if COMFY_ROOT:
            want = PYW_EXE if os.path.isfile(PYW_EXE) else PY_EXE
            with open(os.path.join(HERE, 'python.txt'), 'w', encoding='utf-8') as f:
                f.write(want)
    except Exception:
        pass
    try:
        with open(os.path.join(HERE, 'port.txt'), 'w', encoding='utf-8') as f:
            f.write(str(PORT))
    except Exception:
        pass

COMFY = (CFG.get('comfy_url') or os.environ.get('PICMOTION_COMFY_URL')
         or 'http://127.0.0.1:8188')
HOST = '127.0.0.1'
try:
    PORT = int(CFG.get('port') or os.environ.get('PICMOTION_PORT') or 8899)
except Exception:
    PORT = 8899

DEFAULT_CHECKPOINT = 'majicmixRealistic_v7.safetensors'
# 负面提示词：不想看到的东西。除了画质词，重点压制「解剖错误 / 比例失调 / 拉伸变形」——
# 这三类是 SD1.5 最容易翻车的地方（多手多脚、身体拉长、画面被抻开）。
DEFAULT_NEGATIVE = (
    'lowres, worst quality, low quality, normal quality, jpeg artifacts, blurry, out of focus, '
    'watermark, text, signature, logo, username, error, '
    'bad anatomy, bad proportions, deformed, disfigured, malformed limbs, missing limbs, extra limbs, '
    'extra arms, extra legs, extra fingers, missing fingers, fused fingers, too many fingers, '
    'mutated hands, poorly drawn hands, poorly drawn face, mutated, long neck, long body, '
    'unnatural pose, twisted body, disconnected limbs, floating limbs, '
    'stretched, squashed, warped, distorted, distorted proportions, uneven proportions, '
    'out of frame, cropped, cut off, duplicate, cloned face, '
    'anime, cartoon, 3d render, cgi'
)

# ---------------------------------------------------------------------------
# 内置「画面合理性」提示词
#   —— 用户要的是「人物 / 动作 / 场景都合理协调、不能拉伸」。
#      正向：在提示词后追加这些词，把模型往"构图正常、比例正常"上拉。
#      负向：上面的 DEFAULT_NEGATIVE 已经压了拉伸/畸形/多肢。
#      另外还有一条结构性保障：出图尺寸会按参考图比例换算，避免结构被硬抻（见 fit_size_to_aspect）。
# ---------------------------------------------------------------------------
QUALITY_PREFIX = 'masterpiece, best quality'
QUALITY_SUFFIX = 'coherent composition, natural proportions, correct anatomy'
SUBJECT_TOKENS = {
    'person': 'detailed face, correct human anatomy, proportionate body',
    'action': 'natural pose, balanced posture',
    'scene': 'coherent scene, consistent perspective',
}

# 扩图（在画面外补内容）：方向 -> (左, 上, 右, 下)，值是「源图对应边长的比例」
OUTPAINT_PAD = {
    'down': (0.00, 0.00, 0.00, 0.60),   # 向下补：半身补全身
    'up':   (0.00, 0.60, 0.00, 0.00),   # 向上补
    'lr':   (0.40, 0.00, 0.40, 0.00),   # 左右补：扩场景
    'all':  (0.35, 0.35, 0.35, 0.35),   # 四周补
}
OUTPAINT_MAX = 1280         # 补完后画布长边上限（再长 SD1.5 就开始崩）
OUTPAINT_SRC_MAX = 768      # 源图长边上限：超过先缩小，给要补的内容留出空间
OUTPAINT_FEATHER = 32       # 边缘羽化，接缝更自然
# 补幅：方向比例再乘这个系数。补全身选「大」，补脚/补头顶选「小」。
OUTPAINT_AMOUNT = {'small': 0.5, 'mid': 1.0, 'large': 1.8}
# 扩图专用的 inpaint ControlNet：管接缝、光照、透视、场景延续
# （普通 SD1.5 直接补最容易出的问题就是接缝断层、补出来的部位像"贴上去的"）
OUTPAINT_CN = 'control_v11p_sd15_inpaint_fp16.safetensors'
# 扩图时自动追加的连贯性词：让补出来的部分跟原图保持同一个人 / 同光照 / 同透视
OUTPAINT_SUFFIX = ('same person, same clothing, consistent lighting and perspective, '
                   'seamless continuation of the original photo, natural anatomy, photorealistic')


# 风格预设：把用户的中文意图补成模型认的英文标签
STYLES = {
    'realistic': {
        'label': '写实',
        'model': 'majicmixRealistic_v7.safetensors',
        'tokens': 'photorealistic, 85mm lens, soft light, film grain, professional photography',
    },
    'anime': {
        'label': '动漫',
        'model': 'AWPainting_v1.2.safetensors',
        'tokens': 'anime style, cel shading, vibrant colors, detailed lineart, illustration, best quality',
    },
    'cinematic': {
        'label': '电影感',
        'model': 'majicmixRealistic_v7.safetensors',
        'tokens': 'cinematic lighting, dramatic shadows, movie still, wide shot, color grading, atmospheric',
    },
    'painting': {
        'label': '插画',
        'model': 'AWPainting_v1.2.safetensors',
        'tokens': 'digital painting, concept art, soft brush strokes, highly detailed, trending on artstation',
    },
    'none': {
        'label': '不加风格',
        'model': 'majicmixRealistic_v7.safetensors',
        'tokens': '',
    },
}

SIZES = {
    'portrait': (512, 768),
    'landscape': (768, 512),
    'square': (640, 640),
    'wide': (896, 512),
}

# 清晰度档位。SD1.5 是在 512 上训练的：直接把宽高拉到 1024/1536 会出双头、多手、肢体错乱。
# 正确做法是「两遍画法」：先按基准尺寸画 → 放大潜空间 → 用较低重绘幅度再采样一遍补细节。
HIRES = {
    'none': None,           # 标准（只画一遍，最快）
    '1.5': (1.5, 0.40),     # 高清 1.5 倍
    '2': (2.0, 0.45),       # 高清 2 倍
}

# ---------------------------------------------------------------------------
# 视频：Wan 2.2 5B TI2V —— 一个模型同时支持文生视频和图生视频
#   管线照官方模板 video_wan2_2_5B_ti2v.json：
#   UNETLoader + CLIPLoader(type=wan) + VAELoader + ModelSamplingSD3(shift=8)
#   → Wan22ImageToVideoLatent(+可选首帧) → KSampler(uni_pc/simple) → VAEDecode
#   → CreateVideo(24fps) → SaveVideo
#   length 必须是 4n+1（潜空间时间维压缩 4 倍）
# ---------------------------------------------------------------------------
VIDEO_MODEL = 'wan2.2_ti2v_5B_fp16.safetensors'
VIDEO_CLIP = 'umt5_xxl_fp8_e4m3fn_scaled.safetensors'
VIDEO_VAE = 'wan2.2_vae.safetensors'
VIDEO_FPS = 24
VIDEO_SIZES = {
    '480p_landscape': (832, 480),
    '480p_portrait': (480, 832),
    '480p_square': (640, 640),
    '720p_landscape': (1280, 704),
}
VIDEO_NEG = ('色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，'
             '最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，'
             '画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，'
             '杂乱的背景，三条腿，背景人很多，倒着走')


# ---------------------------------------------------------------------------
# ControlNet：用参考图当「结构草图」重新画 —— 锁构图、换内容
#   和图生图的区别：图生图是把原图编码成潜空间（原图的光影色调会强势保留）；
#   ControlNet 是空潜空间重新画，只用参考图提供结构，所以内容/光线能真正换掉。
#   canny / scribble 是纯 OpenCV 预处理，不需要下权重；
#   depth / openpose / lineart 首次使用会下预处理器权重（HF 已指到镜像）。
# ---------------------------------------------------------------------------
CONTROLNET = {
    'canny': {'label': '边缘 Canny（保线条轮廓）',
              'model': 'control_v11p_sd15_canny_fp16.safetensors',
              'pre': 'CannyEdgePreprocessor',
              'pre_inputs': {'low_threshold': 100, 'high_threshold': 200, 'resolution': 512}},
    'depth': {'label': '深度 Depth（保空间结构）',
              'model': 'control_v11f1p_sd15_depth_fp16.safetensors',
              'pre': 'DepthAnythingV2Preprocessor',
              'pre_inputs': {'ckpt_name': 'depth_anything_v2_vits.pth', 'resolution': 512}},
    'openpose': {'label': '姿态 OpenPose（保人物动作）',
                 'model': 'control_v11p_sd15_openpose_fp16.safetensors',
                 'pre': 'OpenposePreprocessor',
                 'pre_inputs': {'detect_hand': 'enable', 'detect_body': 'enable',
                                'detect_face': 'enable', 'resolution': 512}},
    'lineart': {'label': '线稿 LineArt（保线稿）',
                'model': 'control_v11p_sd15_lineart_fp16.safetensors',
                'pre': 'LineArtPreprocessor',
                'pre_inputs': {'coarse': 'disable', 'resolution': 512}},
    'scribble': {'label': '涂鸦 Scribble（宽松保形）',
                 'model': 'control_v11p_sd15_scribble_fp16.safetensors',
                 'pre': 'FakeScribblePreprocessor',
                 'pre_inputs': {'safe': 'enable', 'resolution': 512}},
}


def frames_for(seconds):
    """秒数 → 合法帧数（4n+1）。"""
    f = max(9, int(round(float(seconds) * VIDEO_FPS)))
    return f - ((f - 1) % 4)


def build_video_workflow(prompt, negative, width, height, length, seed,
                         steps=20, cfg=5.0, prefix='video', init_image=''):
    wf = {
        '37': {'class_type': 'UNETLoader',
               'inputs': {'unet_name': VIDEO_MODEL, 'weight_dtype': 'default'}},
        '38': {'class_type': 'CLIPLoader',
               'inputs': {'clip_name': VIDEO_CLIP, 'type': 'wan', 'device': 'default'}},
        '39': {'class_type': 'VAELoader', 'inputs': {'vae_name': VIDEO_VAE}},
        '48': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['37', 0], 'shift': 8.0}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': prompt, 'clip': ['38', 0]}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'text': negative, 'clip': ['38', 0]}},
        '55': {'class_type': 'Wan22ImageToVideoLatent',
               'inputs': {'vae': ['39', 0], 'width': int(width), 'height': int(height),
                          'length': int(length), 'batch_size': 1}},
        '3': {'class_type': 'KSampler',
              'inputs': {'seed': int(seed), 'steps': int(steps), 'cfg': float(cfg),
                         'sampler_name': 'uni_pc', 'scheduler': 'simple', 'denoise': 1.0,
                         'model': ['48', 0], 'positive': ['6', 0], 'negative': ['7', 0],
                         'latent_image': ['55', 0]}},
        '8': {'class_type': 'VAEDecode', 'inputs': {'samples': ['3', 0], 'vae': ['39', 0]}},
        '57': {'class_type': 'CreateVideo', 'inputs': {'images': ['8', 0], 'fps': float(VIDEO_FPS)}},
        '58': {'class_type': 'SaveVideo',
               'inputs': {'video': ['57', 0], 'format': 'auto', 'codec': 'auto',
                          'filename_prefix': PREVIEW_SUBDIR + '/' + prefix}},
    }
    if init_image:
        wf['56'] = {'class_type': 'LoadImage', 'inputs': {'image': init_image}}
        wf['55']['inputs']['start_image'] = ['56', 0]
    return wf

# ---------------------------------------------------------------------------
#  ① 违规检测与拦截  —— 规则可在 rules.json 配置，也可以在页面里改（保存即生效）
#
#  规则格式：{ "name": 名字, "pattern": 正则, "enabled": true/false }
#  判定：任一条【启用】的规则命中 → 拦截，请求不会发往 ComfyUI。
#
#  能力边界（重要）：这是关键词/正则这一层，能挡住直白表达和简单拆写
#  （「色 情」「色-情」会被 compact 归一后抓到），但**挡不住刻意绕写**：
#  同音字、拼音、拆字、暗语、多语言混写、以及换个说法的间接表达都拦不住。
#  要更稳就得在 moderate() 里接模型判别或外部分类器 —— 同一个入口，改一处即可。
# ---------------------------------------------------------------------------
RULES_FILE = os.path.join(HERE, 'rules.json')

DEFAULT_RULES = [
    {'name': '未成年人性化', 'enabled': True,
     'pattern': r'(loli|shota|child|kid|underage|minor|小学生|儿童|幼女|萝莉|未成年)[^。，,.]{0,16}(nude|naked|sex|porn|nsfw|裸|色情|性|做爱)'},
    {'name': '未成年人性化（反序）', 'enabled': True,
     'pattern': r'(nude|naked|sex|porn|nsfw|裸|色情|做爱)[^。，,.]{0,16}(child|kid|loli|underage|小学生|儿童|幼女|萝莉|未成年)'},
    {'name': '露骨标记词', 'enabled': True,
     'pattern': r'\b(nsfw|explicit|hardcore porn)\b'},
    {'name': '露骨性内容', 'enabled': True,
     'pattern': r'(全裸|裸体|裸露|色情|做爱|性交|性行为|露点|私处)'},
    {'name': '真实人物伪造', 'enabled': True,
     'pattern': r'(deepfake|换脸|伪造)[^。，,.]{0,16}(色情|裸|nude|sex|做爱)'},
]

_rules_cache = {'mtime': None, 'rules': []}
_rules_lock = threading.Lock()


def _compile(rules):
    out = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        pat = str(r.get('pattern') or '').strip()
        if not pat:
            continue
        try:
            rx = re.compile(pat)
        except re.error:
            continue        # 写错的正则跳过，不让一条坏规则拖垮整条检测链
        out.append({'name': str(r.get('name') or ''), 'pattern': pat,
                    'enabled': bool(r.get('enabled', True)), 're': rx})
    return out


def save_rules(rules):
    """把规则写进 rules.json（UTF-8、缩进过，方便你直接用记事本改）。"""
    tmp = RULES_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'rules': rules}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RULES_FILE)


def load_rules(force=False):
    """读规则。文件改过不用重启，下一次请求自动生效（按修改时间判断）。"""
    with _rules_lock:
        try:
            mt = os.path.getmtime(RULES_FILE)
        except OSError:
            mt = None
        if not force and mt == _rules_cache['mtime'] and _rules_cache['rules']:
            return _rules_cache['rules']
        if not os.path.isfile(RULES_FILE):
            data = {'version': 1, 'rules': DEFAULT_RULES}
            try:
                save_rules(data['rules'])
            except Exception:
                pass
        else:
            try:
                with open(RULES_FILE, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = None
            if not isinstance(data, dict) or not isinstance(data.get('rules'), list):
                data = {'version': 1, 'rules': DEFAULT_RULES}   # 文件坏了就用默认，不覆盖它
        _rules_cache['rules'] = _compile(data['rules'])
        _rules_cache['mtime'] = mt
        return _rules_cache['rules']

BLOCKED_LOG = os.path.join(HERE, 'blocked.log')
_mod_lock = threading.Lock()


def normalize(text):
    """统一大小写、清掉零宽字符与方向控制符（用来对抗简单的绕过写法）。"""
    t = (text or '').lower()
    t = re.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', t)
    t = t.replace('　', ' ')
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


# ---------------------------------------------------------------------------
#  中文 → 英文
#  优先用 Google 翻译（免费端点，需要走代理）；失败才退回本地词库。
#  为什么必须显式走代理：你这台机器系统代理是关的（ProxyEnable=0），
#  直连 translate.googleapis.com 会超时，但 Clash 在 127.0.0.1:7897 上能通。
#  代理端口换了你也不用改代码 —— 下面会自动探测常见端口。
# ---------------------------------------------------------------------------
TRANSLATE_ENABLED = True                 # 改成 False 就只用本地词库
TRANSLATE_TIMEOUT = 8                    # 单次翻译超时（秒）
PROXY_CANDIDATES = [                     # 依次尝试，第一个能通的会被记住
    'http://127.0.0.1:7897', 'http://127.0.0.1:7890', 'http://127.0.0.1:7891',
    'http://127.0.0.1:10809', 'http://127.0.0.1:1080', 'http://127.0.0.1:2080',
]

_good_proxy = None
_tr_cache = {}
_tr_lock = threading.Lock()


def _http_get_json(url, proxy, timeout):
    handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy} if proxy else {})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def translate_google(text):
    """用 Google 翻译的免费端点中译英。成功返回英文，失败返回 None。"""
    global _good_proxy
    url = ('https://translate.googleapis.com/translate_a/single'
           '?client=gtx&sl=zh-CN&tl=en&dt=t&q=' + urllib.parse.quote(text))
    # 先试记住的那个；没记住或上次失败过，就按候选表扫一遍（探测用短超时）
    cands = []
    if _good_proxy:
        cands.append(_good_proxy)
    cands += [p for p in PROXY_CANDIDATES if p != _good_proxy]
    cands.append(None)                   # 最后试直连
    for p in cands:
        try:
            data = _http_get_json(url, p, TRANSLATE_TIMEOUT if p == _good_proxy else 4)
            segs = (data[0] or []) if isinstance(data, list) and data else []
            out = ''.join(s[0] for s in segs if s and s[0]).strip()
            out = out.rstrip('.').strip()
            if out:
                _good_proxy = p
                return out
        except Exception:
            continue
    _good_proxy = None
    return None


def translate(text):
    """返回 (译文, 被丢掉的中文词, 用的哪个引擎)。"""
    text = (text or '').strip()
    if not text:
        return '', [], 'none'
    with _tr_lock:
        hit = _tr_cache.get(text)
    if hit:
        return hit[0], hit[1], hit[2]
    if TRANSLATE_ENABLED:
        en = translate_google(text)
        if en:
            result = (en, [], 'google')
            with _tr_lock:
                _tr_cache[text] = result
            return result
    # 兜底：本地词库
    out, dropped = translate_dict(text)
    result = (out, dropped, 'dict')
    with _tr_lock:
        _tr_cache[text] = result
    return result


def translate_dict(text):
    """本地词库兜底：把认识的中文换成英文标签，不认识的丢掉并报出来。"""
    if not text:
        return '', []
    out = text
    for k in _ZH_KEYS:
        if k in out:
            out = out.replace(k, ' ' + ZH2EN[k] + ' ')
    out = re.sub(r'[，。、；：！？（）【】《》「」,;:!?()\[\]{}]+', ', ', out)
    leftover = re.findall(r'[\u4e00-\u9fff]+', out)
    dropped = []
    for t in leftover:
        if len(t) >= 2 and t not in dropped:
            dropped.append(t)
    out = re.sub(r'[\u4e00-\u9fff]+', ' ', out)
    out = re.sub(r'\s+', ' ', out)
    out = re.sub(r'\s*,\s*', ', ', out)
    out = re.sub(r'(,\s*)+', ', ', out)
    return out.strip(' ,'), dropped
ZH2EN = {
    # 人物
    '女孩': '1girl', '男孩': '1boy', '女人': 'woman', '男人': 'man', '少女': 'young girl',
    '少年': 'young boy', '儿童': 'child', '老人': 'old person', '情侣': 'couple',
    '学生': 'student', '女仆': 'maid', '武士': 'samurai', '骑士': 'knight', '女巫': 'witch',
    '天使': 'angel', '恶魔': 'demon', '精灵': 'elf', '机器人': 'robot', '赛博格': 'cyborg',
    # 动物
    '猫': 'cat', '橘猫': 'orange tabby cat', '黑猫': 'black cat', '白猫': 'white cat',
    '狗': 'dog', '柴犬': 'shiba inu', '狼': 'wolf', '狐狸': 'fox', '兔子': 'rabbit',
    '鸟': 'bird', '龙': 'dragon', '蝴蝶': 'butterfly', '鱼': 'fish', '马': 'horse',
    # 头发/外貌
    '长发': 'long hair', '短发': 'short hair', '银发': 'silver hair', '金发': 'blonde hair',
    '黑发': 'black hair', '红发': 'red hair', '蓝发': 'blue hair', '粉发': 'pink hair',
    '双马尾': 'twintails', '马尾': 'ponytail', '眼镜': 'glasses', '微笑': 'smiling',
    '侧脸': 'profile', '正脸': 'looking at viewer',
    # 服装
    '和服': 'kimono', '汉服': 'hanfu', '婚纱': 'wedding dress', '礼服': 'evening gown',
    '校服': 'school uniform', '西装': 'suit', '连衣裙': 'dress', '外套': 'jacket',
    '帽子': 'hat', '围巾': 'scarf', '盔甲': 'armor', '斗篷': 'cloak',
    # 地点/场景
    '城市': 'city', '街道': 'street', '小巷': 'alley', '城堡': 'castle', '房子': 'house',
    '房间': 'room', '卧室': 'bedroom', '厨房': 'kitchen', '教室': 'classroom',
    '图书馆': 'library', '书店': 'bookstore', '咖啡店': 'cafe', '酒吧': 'bar',
    '车站': 'train station', '地铁': 'subway', '商店': 'shop', '花园': 'garden',
    '森林': 'forest', '树林': 'woods', '山': 'mountain', '雪山': 'snow mountain',
    '海': 'sea', '海滩': 'beach', '湖': 'lake', '河': 'river', '瀑布': 'waterfall',
    '沙漠': 'desert', '草原': 'grassland', '天空': 'sky', '云': 'clouds',
    '星空': 'starry sky', '银河': 'milky way', '月亮': 'moon', '太阳': 'sun',
    '桥': 'bridge', '塔': 'tower', '废墟': 'ruins', '寺庙': 'temple', '教堂': 'church',
    '飞船': 'spaceship', '汽车': 'car', '摩托': 'motorcycle', '火车': 'train',
    # 物件
    '花': 'flowers', '樱花': 'cherry blossoms', '玫瑰': 'roses', '树': 'tree',
    '书': 'books', '书架': 'bookshelf', '咖啡': 'a cup of coffee', '茶杯': 'teacup',
    '窗': 'window', '窗台': 'windowsill', '台灯': 'desk lamp', '灯': 'lamp', '蜡烛': 'candle',
    '时钟': 'clock', '镜子': 'mirror', '伞': 'umbrella', '剑': 'sword', '翅膀': 'wings',
    # 天气/时间/季节
    '雨': 'rain', '下雨': 'raining', '雨夜': 'rainy night', '雪': 'snow', '下雪': 'snowing',
    '雾': 'fog', '雷': 'thunder', '夜晚': 'night', '深夜': 'late night', '白天': 'daytime',
    '清晨': 'early morning', '黄昏': 'dusk', '黎明': 'dawn', '傍晚': 'evening',
    '午后': 'afternoon', '正午': 'noon', '中午': 'noon', '凌晨': 'early hours',
    '半夜': 'midnight', '深夜': 'late night', '周末': 'weekend',
    '春天': 'spring', '夏天': 'summer', '秋天': 'autumn', '冬天': 'winter',
    # 氛围
    '温暖': 'warm', '温馨': 'cozy', '寒冷': 'cold', '安静': 'quiet', '热闹': 'lively',
    '梦幻': 'dreamy', '神秘': 'mysterious', '恐怖': 'scary', '孤独': 'lonely',
    '浪漫': 'romantic', '宁静': 'peaceful', '怀旧': 'nostalgic', '治愈': 'healing',
    # 风格
    '写实': 'photorealistic', '动漫': 'anime style', '插画': 'illustration',
    '油画': 'oil painting', '水彩': 'watercolor', '素描': 'sketch', '国风': 'chinese style',
    '赛博朋克': 'cyberpunk', '蒸汽朋克': 'steampunk', '科幻': 'sci-fi', '奇幻': 'fantasy',
    '复古': 'retro', '极简': 'minimalist', '像素': 'pixel art', '电影感': 'cinematic',
    '可爱': 'cute', '帅气': 'handsome', '唯美': 'beautiful', '暗黑': 'dark',
    # 构图/光线
    '特写': 'close-up', '半身': 'upper body', '全身': 'full body', '远景': 'wide shot',
    '俯视': 'from above', '仰视': 'from below', '背影': 'from behind',
    '逆光': 'backlighting', '柔光': 'soft lighting', '暖光': 'warm lighting',
    '冷光': 'cool lighting', '霓虹': 'neon lights', '阳光': 'sunlight', '月光': 'moonlight',
    '剪影': 'silhouette', '景深': 'depth of field',
    # 画质
    '高清': 'high resolution', '细节丰富': 'highly detailed', '精致': 'finely detailed',
    '杰作': 'masterpiece', '最高画质': 'best quality',
    # 修饰词 / 常见搭配（漏译会让提示词变脏）
    '暖黄': 'warm yellow light', '昏黄': 'dim yellow light', '木质': 'wooden',
    '木': 'wooden', '石': 'stone', '金属': 'metal', '玻璃': 'glass',
    '窗外': 'outside the window', '窗边': 'by the window', '桌上': 'on the table',
    '红色': 'red', '蓝色': 'blue', '白色': 'white', '黑色': 'black',
    '绿色': 'green', '金色': 'golden', '紫色': 'purple', '粉色': 'pink',
    '破旧': 'ruined', '古老': 'ancient', '现代': 'modern', '未来': 'futuristic',
    # 动作（动词写进提示词常常能改善构图）
    '站立': 'standing', '站': 'standing', '坐着': 'sitting', '坐': 'sitting',
    '躺着': 'lying down', '躺': 'lying', '趴': 'lying', '走动': 'walking', '走': 'walking',
    '奔跑': 'running', '跑': 'running', '飞翔': 'flying', '飞': 'flying', '跳': 'jumping',
    '睡觉': 'sleeping', '睡': 'sleeping', '望向': 'looking at', '看': 'looking',
    '抱着': 'hugging', '抱': 'hugging', '拿着': 'holding', '捧着': 'holding', '举着': 'raising',
    '看书': 'reading', '读书': 'reading a book', '弹琴': 'playing piano',
    '跳舞': 'dancing', '唱歌': 'singing', '战斗': 'fighting', '施法': 'casting a spell',
    '挥手': 'waving', '回头': 'looking back', '低头': 'looking down', '抬头': 'looking up',
    # 颜色 / 材质
    '银色': 'silver', '灰色': 'grey', '棕色': 'brown', '橙色': 'orange', '青色': 'cyan',
    '透明': 'transparent', '发光': 'glowing', '金属': 'metallic', '皮质': 'leather',
    '丝绸': 'silk', '毛茸茸': 'fluffy', '粗糙': 'rough texture', '光滑': 'smooth',
    # 科幻 / 机甲
    '机甲': 'mecha', '装甲': 'armored', '机械': 'mechanical', '引擎': 'engine',
    '全息': 'holographic', '激光': 'laser', '空间站': 'space station', '外星': 'alien',
    '末日': 'post-apocalyptic', '废土': 'wasteland', '遗迹': 'ancient ruins',
    # 人物补充
    '少女': 'young girl', '大叔': 'middle-aged man', '人群': 'crowd', '人影': 'silhouette',
    '侧影': 'silhouette', '面孔': 'face', '眼睛': 'eyes', '手': 'hands',
    # 场景补充
    '山顶': 'mountain top', '山谷': 'valley', '洞穴': 'cave', '沙滩': 'sandy beach',
    '码头': 'dock', '天台': 'rooftop', '阳台': 'balcony', '走廊': 'corridor',
    '楼梯': 'stairs', '屋顶': 'roof', '广场': 'square', '市场': 'market',
    '夜市': 'night market', '咖啡馆': 'cafe', '教室': 'classroom', '办公室': 'office',
}
_ZH_KEYS = sorted(ZH2EN.keys(), key=len, reverse=True)   # 长词优先，避免「猫」抢在「橘猫」前面


def _unused_translate_zh_removed():
    pass


def compact(text):
    """去掉空白与常见分隔符，用来抓「色 情」「色-情」「色.情」这类拆写。"""
    return re.sub(r'[\s\.,\-_*·|/\\~^+]+', '', normalize(text))


def moderate(prompt, negative=''):
    """返回 (ok, reason)。这是唯一的拦截入口（要接模型判别就改这一个函数）。"""
    text = normalize(prompt) + ' ' + normalize(negative)
    comp = compact(prompt) + compact(negative)
    for r in load_rules():
        if not r['enabled'] or not r['pattern']:
            continue
        m = r['re'].search(text) or r['re'].search(comp)
        if m:
            return False, '命中规则「%s」：%s' % (r['name'], m.group(0)[:40])
    return True, ''


def log_blocked(prompt, reason):
    try:
        with _mod_lock:
            with open(BLOCKED_LOG, 'a', encoding='utf-8') as f:
                f.write('%s\t%s\t%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'),
                                          reason.replace('\t', ' '),
                                          (prompt or '').replace('\n', ' ')[:500]))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ComfyUI 交互
# ---------------------------------------------------------------------------
# 访问本机 ComfyUI 一律【不走代理】：你把系统代理打开后，urllib 默认会把
# 连 127.0.0.1 的请求也交给代理，那样就连不上 ComfyUI 了。这里显式禁用。
_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(url, data=None, timeout=60):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json; charset=utf-8'
    req = urllib.request.Request(url, data=body, headers=headers)
    with _direct_opener.open(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw.decode('utf-8')) if raw else {}


def comfy_up():
    try:
        http_json(COMFY + '/system_stats', timeout=5)
        return True
    except Exception:
        return False


_start_lock = threading.Lock()


def ensure_comfy(timeout=300):
    """ComfyUI 没在跑就自己拉起来（隐藏窗口），返回 (ok, message)。"""
    if comfy_up():
        return True, '已在运行'
    py = PY_EXE
    main_py = os.path.join(COMFY_ROOT, 'ComfyUI', 'main.py')
    if not os.path.isfile(py) or not os.path.isfile(main_py):
        return False, '找不到 ComfyUI 自带 python 或 main.py，请检查目录'
    with _start_lock:
        if comfy_up():
            return True, '已在运行'
        flags = 0
        if os.name == 'nt':
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        env = dict(os.environ)
        # 预处理器（depth / openpose / lineart）首次使用要下权重，而 huggingface.co
        # 在这台机器上是墙的 —— 指到镜像，否则会卡在超时上。
        env.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
        subprocess.Popen(
            [py, '-s', os.path.join('ComfyUI', 'main.py'),
             '--windows-standalone-build', '--disable-auto-launch', '--port', '8188'],
            cwd=COMFY_ROOT, creationflags=flags, env=env,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            if comfy_up():
                return True, '已启动'
    return False, 'ComfyUI 在 %d 秒内没有就绪' % timeout


def list_models():
    try:
        oi = http_json(COMFY + '/object_info/CheckpointLoaderSimple', timeout=20)
        names = oi['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0]
        return [n for n in names if isinstance(n, str)]
    except Exception:
        return []


def save_input_image(data_url):
    """把页面传来的图片（data URL 或裸 base64）写进 ComfyUI 的 input 目录，返回文件名。"""
    try:
        b64 = data_url.split(',', 1)[1] if ',' in data_url else data_url
        raw = base64.b64decode(b64)
        if len(raw) < 64 or len(raw) > 40 * 1024 * 1024:
            return ''
        ext = 'png'
        if raw[:3] == b'\xff\xd8\xff':
            ext = 'jpg'
        elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            ext = 'webp'
        os.makedirs(COMFY_INPUT, exist_ok=True)
        name = 'simpleui_in_%d.%s' % (int(time.time() * 1000), ext)
        with open(os.path.join(COMFY_INPUT, name), 'wb') as f:
            f.write(raw)
        return name
    except Exception:
        return ''


def snap8(v, minimum=8):
    """对齐到 8 的倍数（VAE 下采样要求）。补 0 像素时要能返回 0，所以 minimum 可调。"""
    return max(minimum, int(round(float(v) / 8.0)) * 8)


def _truthy(v, default=False):
    """页面传来的勾选值（true/false、'1'/'0'、'on'…）。"""
    if v is None or v == '':
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ('0', 'false', 'no', 'off')


def image_size(path):
    """读图片尺寸；失败返回 (0, 0)。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


def fit_size_to_aspect(bw, bh, src_w, src_h, max_side=1024, min_side=384):
    """把「基准尺寸的面积」套到参考图的比例上。

    为什么需要它：ControlNet 会把参考图（预处理后的结构图）内部缩放到出图尺寸，
    两者比例不同就等于把结构硬抻 —— 人物被拉长压扁，这就是「拉伸」的来源。
    改成按参考图比例出图，缩放就是等比的，结构不会变形。
    """
    if not (bw and bh and src_w and src_h):
        return int(bw), int(bh)
    try:
        import math
        ar = float(src_w) / float(src_h)
        h = math.sqrt(float(bw) * float(bh) / ar)
        w = h * ar
        w, h = snap8(w), snap8(h)
        if max(w, h) > max_side:
            k = max_side / float(max(w, h))
            w, h = snap8(w * k), snap8(h * k)
        if min(w, h) < min_side:
            k = min_side / float(min(w, h))
            w, h = snap8(w * k), snap8(h * k)
            if max(w, h) > max_side:
                k = max_side / float(max(w, h))
                w, h = snap8(w * k), snap8(h * k)
        return int(w), int(h)
    except Exception:
        return int(bw), int(bh)


def plan_outpaint(src_w, src_h, direction, amount='mid', shrink=False):
    """算扩图参数：源图尺寸 + 四边补多少像素。

    amount: small/mid/large —— 补多少。补全身要大，补脚/头顶要小。
    shrink: 缩小原图腾空间。半身照想补成完整全身时要开 —— 不开的话人物占满画布，
            腿根本没有空间，模型只能把它压扁或截断（实测就是这样：补出裤子但没脚）。
            开了之后原图缩到画布高度的约 45%，腿才按正常比例放得下（代价：人物变小）。
    """
    l, t, r, b = OUTPAINT_PAD.get(direction) or OUTPAINT_PAD['down']
    if shrink and direction in ('down', 'up'):
        canvas_h = OUTPAINT_MAX
        k = min(1.0, (canvas_h * 0.42) / float(src_h))
        sw, sh = snap8(src_w * k), snap8(src_h * k)
        canvas_w = snap8(max(sw, sw * 1.33))
        side = snap8((canvas_w - sw) / 2.0, 0)
        room = snap8(canvas_h - sh, 0)
        if direction == 'down':
            return sw, sh, side, 0, side, room
        return sw, sh, side, room, side, 0
    mul = OUTPAINT_AMOUNT.get(amount, 1.0)
    l, t, r, b = l * mul, t * mul, r * mul, b * mul
    # 源图太大才缩（按长边），给要补的内容腾地方
    k = min(1.0, OUTPAINT_SRC_MAX / float(max(src_w, src_h)))
    sw, sh = snap8(src_w * k), snap8(src_h * k)
    pl, pt, pr, pb = sw * l, sh * t, sw * r, sh * b
    # 左右 / 上下各自的总补量，受画布上限约束（等比压缩，不改方向比例）
    room_x = max(0, OUTPAINT_MAX - sw)
    room_y = max(0, OUTPAINT_MAX - sh)
    tot_x, tot_y = pl + pr, pt + pb
    if tot_x > room_x and tot_x > 0:
        f = room_x / float(tot_x)
        pl, pr = pl * f, pr * f
    if tot_y > room_y and tot_y > 0:
        f = room_y / float(tot_y)
        pt, pb = pt * f, pb * f
    return sw, sh, snap8(pl, 0), snap8(pt, 0), snap8(pr, 0), snap8(pb, 0)


def build_outpaint_workflow(prompt, negative, checkpoint, src_w, src_h, direction,
                            steps, cfg, seed, init_image, amount='mid', shrink=False,
                            prefix='outpaint'):
    """扩图 / 补全：原图放画布一角，外面用 inpaint 把内容补出来。

    接法照官方 outpainting 示例，并额外挂上**专门为扩图训练的 inpaint ControlNet**
    （control_v11p_sd15_inpaint）—— 普通 SD1.5 直接补最容易出的问题就是
    接缝断层、下半身像"贴上去的"、透视和光照不接。这个 ControlNet 就是治这个的。

      LoadImage → ImageScale → ImagePadForOutpaint ─┬→ VAEEncodeForInpaint → KSampler
                                                    └→ ControlNetInpaintingAliMamaApply ↗
    VAEEncodeForInpaint 带噪声掩码：原图区域受保护，只有新补的区域重新生成。
    """
    sw, sh, pl, pt, pr, pb = plan_outpaint(src_w, src_h, direction, amount, shrink)
    wf = {
        '4': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': checkpoint}},
        '20': {'class_type': 'LoadImage', 'inputs': {'image': init_image}},
        '25': {'class_type': 'ImageScale',
               'inputs': {'image': ['20', 0], 'upscale_method': 'lanczos',
                          'width': sw, 'height': sh, 'crop': 'disabled'}},
        '26': {'class_type': 'ImagePadForOutpaint',
               'inputs': {'image': ['25', 0], 'left': pl, 'top': pt,
                          'right': pr, 'bottom': pb, 'feathering': OUTPAINT_FEATHER}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': prompt, 'clip': ['4', 1]}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'text': negative, 'clip': ['4', 1]}},
        # 扩图专用 ControlNet：管接缝、光照、透视、场景延续
        #   ⚠ 它要求"要补的区域"在控制图里是灰色，而 ImagePadForOutpaint 给的是黑底，
        #     所以必须先用 InpaintPreprocessor 把遮罩区渲染成灰，否则模型会照着一块灰/黑画，
        #     结果就是补出来的地方什么都没有（一片灰）。
        '28': {'class_type': 'ControlNetLoader',
               'inputs': {'control_net_name': OUTPAINT_CN}},
        '30': {'class_type': 'InpaintPreprocessor',
               'inputs': {'image': ['26', 0], 'mask': ['26', 1],
                          'black_pixel_for_xinsir_cn': False}},
        '29': {'class_type': 'ControlNetInpaintingAliMamaApply',
               'inputs': {'positive': ['6', 0], 'negative': ['7', 0],
                          'control_net': ['28', 0], 'vae': ['4', 2],
                          'image': ['30', 0], 'mask': ['26', 1],
                          'strength': 1.0, 'start_percent': 0.0, 'end_percent': 1.0}},
        '27': {'class_type': 'VAEEncodeForInpaint',
               'inputs': {'pixels': ['26', 0], 'vae': ['4', 2], 'mask': ['26', 1],
                          'grow_mask_by': 24}},
        '3': {'class_type': 'KSampler',
              'inputs': {'seed': int(seed), 'steps': int(steps), 'cfg': float(cfg),
                         'sampler_name': 'dpmpp_2m', 'scheduler': 'karras', 'denoise': 1.0,
                         'model': ['4', 0], 'positive': ['29', 0], 'negative': ['29', 1],
                         'latent_image': ['27', 0]}},
        '8': {'class_type': 'VAEDecode', 'inputs': {'samples': ['3', 0], 'vae': ['4', 2]}},
        '9': {'class_type': 'SaveImage',
              'inputs': {'filename_prefix': PREVIEW_SUBDIR + '/' + prefix, 'images': ['8', 0]}},
    }
    return wf, (sw + pl + pr, sh + pt + pb), (pl, pt, pr, pb)


def build_workflow(prompt, negative, checkpoint, width, height, steps, cfg,
                   sampler, scheduler, seed, batch, hires=None, prefix='simpleui',
                   init_image=None, denoise=1.0, control=None, control_strength=1.0):
    wf = {
        '4': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': checkpoint}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': prompt, 'clip': ['4', 1]}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'text': negative, 'clip': ['4', 1]}},
    }
    use_cn = bool(init_image and control and control in CONTROLNET)
    if use_cn:
        # ControlNet：参考图 → 预处理出结构图 → 作为引导；潜空间是空的，从头画
        cn = CONTROLNET[control]
        wf['20'] = {'class_type': 'LoadImage', 'inputs': {'image': init_image}}
        wf['22'] = {'class_type': cn['pre'], 'inputs': dict(cn['pre_inputs'], image=['20', 0])}
        wf['23'] = {'class_type': 'ControlNetLoader',
                    'inputs': {'control_net_name': cn['model']}}
        wf['24'] = {'class_type': 'ControlNetApplyAdvanced',
                    'inputs': {'positive': ['6', 0], 'negative': ['7', 0],
                               'control_net': ['23', 0], 'image': ['22', 0],
                               'strength': float(control_strength),
                               'start_percent': 0.0, 'end_percent': 0.85}}
        pos_ref, neg_ref = ['24', 0], ['24', 1]
    else:
        pos_ref, neg_ref = ['6', 0], ['7', 0]

    if init_image and not use_cn:
        # 传统图生图：把参考图编码进潜空间，用较低 denoise 重绘（原图光影会强势保留）
        wf['20'] = {'class_type': 'LoadImage', 'inputs': {'image': init_image}}
        wf['21'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['20', 0], 'vae': ['4', 2]}}
        latent = ['21', 0]
    else:
        # 文生图 / ControlNet：空潜空间从头画
        wf['5'] = {'class_type': 'EmptyLatentImage',
                   'inputs': {'width': int(width), 'height': int(height), 'batch_size': int(batch)}}
        latent = ['5', 0]

    wf['3'] = {'class_type': 'KSampler',
               'inputs': {'seed': int(seed), 'steps': int(steps), 'cfg': float(cfg),
                          'sampler_name': sampler, 'scheduler': scheduler,
                          'denoise': float(denoise), 'model': ['4', 0],
                          'positive': pos_ref, 'negative': neg_ref, 'latent_image': latent}}
    last = ['3', 0]
    if hires:
        # 第二遍：把潜空间放大，再用低重绘幅度采样一次补细节（hires fix）
        scale, hd = hires
        wf['11'] = {'class_type': 'LatentUpscale',
                    'inputs': {'samples': ['3', 0], 'upscale_method': 'bislerp',
                               'width': int(round(width * scale)),
                               'height': int(round(height * scale)), 'crop': 'disabled'}}
        wf['12'] = {'class_type': 'KSampler',
                    'inputs': {'seed': int(seed), 'steps': max(10, int(round(steps * 0.7))),
                               'cfg': float(cfg), 'sampler_name': sampler,
                               'scheduler': scheduler, 'denoise': hd,
                               'model': ['4', 0], 'positive': ['6', 0],
                               'negative': ['7', 0], 'latent_image': ['11', 0]}}
        last = ['12', 0]
    wf['8'] = {'class_type': 'VAEDecode', 'inputs': {'samples': last, 'vae': ['4', 2]}}
    wf['9'] = {'class_type': 'SaveImage',
               'inputs': {'filename_prefix': PREVIEW_SUBDIR + '/' + prefix, 'images': ['8', 0]}}
    return wf


def generate(params):
    """核心流程：拦截 → 组装 → 提交 → 收输出。支持 文生图 / 图生图 / 文生视频 / 图生视频。"""
    user_prompt = (params.get('prompt') or '').strip()
    if not user_prompt:
        return {'ok': False, 'error': '请输入要画的内容'}

    mode = 'video' if str(params.get('mode') or '') == 'video' else 'image'
    style_key = params.get('style') or 'realistic'
    style = STYLES.get(style_key, STYLES['realistic'])
    negative = (params.get('negative') or '').strip() or (VIDEO_NEG if mode == 'video' else DEFAULT_NEGATIVE)

    # 中文 → 英文：优先 Google 翻译（走代理），失败才退回本地词库
    translated, dropped, engine = translate(user_prompt)

    # 拼提示词：翻译结果 + 风格标签 + 内置合理性词（视频不加图片那套）
    applied = []
    if mode == 'video':
        full_prompt = translated
    else:
        # 顺序很重要：CLIP 只吃前 77 个 token，超了从尾部截。
        # 所以把**用户自己写的词放最前**，通用的质量词放最后 —— 万一被截，砍掉的是通用词。
        parts = [translated] if translated else []
        if style['tokens']:
            parts.append(style['tokens'])
            applied.append('风格　' + style['tokens'])
        for key, label in (('person', '人物'), ('action', '动作'), ('scene', '场景')):
            if _truthy(params.get(key)):
                parts.append(SUBJECT_TOKENS[key])
                applied.append(label + '　' + SUBJECT_TOKENS[key])
        if _truthy(params.get('quality'), True):
            parts.append(QUALITY_PREFIX)
            parts.append(QUALITY_SUFFIX)
            applied.append('合理性　' + QUALITY_SUFFIX)
        full_prompt = ', '.join(p for p in parts if p)

    # ---------- ① 违规检测与拦截 ----------
    ok, reason = moderate('%s %s' % (user_prompt, full_prompt), negative)
    if not ok:
        log_blocked(user_prompt, reason)
        return {'ok': False, 'blocked': True, 'error': reason}

    # ---------- ② 组装 ----------
    init_image = ''
    data_url = params.get('image') or ''
    if data_url:
        init_image = save_input_image(data_url)
        if not init_image:
            return {'ok': False, 'error': '参考图解析失败（太大或格式不支持）'}

    seed = int(params.get('seed') or 0) or random.randint(1, 2147483646)
    control = ''
    control_strength = 1.0
    outpaint = ''
    aspect_fixed = False
    src_w = src_h = 0
    out_canvas = (0, 0)

    if mode == 'video':
        width, height = VIDEO_SIZES.get(str(params.get('vsize') or '480p_landscape'),
                                        VIDEO_SIZES['480p_landscape'])
        length = frames_for(params.get('seconds') or 2)
        steps = int(params.get('steps') or 20)
        cfg = float(params.get('cfg') or 5.0)
        checkpoint = VIDEO_MODEL
        hires_key, denoise, batch = 'none', 1.0, 1
    else:
        width, height = SIZES.get(params.get('size') or 'portrait', SIZES['portrait'])
        hires_key = str(params.get('hires') or 'none')
        checkpoint = (params.get('checkpoint') or '').strip() or style['model']
        steps = int(params.get('steps') or 24)
        cfg = float(params.get('cfg') or 7.0)
        batch = max(1, min(4, int(params.get('batch') or 1)))
        denoise = max(0.05, min(0.95, float(params.get('denoise') or 0.55))) if init_image else 1.0
        length = 0
        # ControlNet：参考图只当结构草图，空潜空间重画 → denoise 必须是 1.0
        if init_image and str(params.get('control') or '') in CONTROLNET:
            control = str(params.get('control'))
            control_strength = max(0.1, min(2.0, float(params.get('cnStrength') or 1.0)))
            denoise = 1.0
        # 扩图 / 补全（和 ControlNet 是两种做法，扩图优先）
        if init_image and str(params.get('outpaint') or '') in OUTPAINT_PAD:
            outpaint = str(params.get('outpaint'))
            control = ''
            hires_key = 'none'
            denoise = 1.0
            # 补内容时追加连贯性词，让新补的部分跟原图接得上
            full_prompt = (full_prompt + ', ' + OUTPAINT_SUFFIX).strip(', ')
            applied.append('扩图连贯性　' + OUTPAINT_SUFFIX)
        if init_image:
            src_w, src_h = image_size(os.path.join(COMFY_INPUT, init_image))
        # ControlNet 的防拉伸：按参考图比例换算出图尺寸
        # （比例不一致时 ControlNet 会把结构图硬缩放到出图尺寸，人物就被拉长压扁）
        if control and src_w and src_h:
            nw, nh = fit_size_to_aspect(width, height, src_w, src_h)
            if (nw, nh) != (width, height):
                width, height = nw, nh
                aspect_fixed = True

    up, msg = ensure_comfy()
    if not up:
        return {'ok': False, 'error': msg}

    if mode == 'video':
        wf = build_video_workflow(full_prompt, negative, width, height, length, seed,
                                  steps=steps, cfg=cfg, init_image=init_image)
    elif outpaint:
        wf, out_canvas, _pad = build_outpaint_workflow(
            full_prompt, negative, checkpoint, src_w, src_h, outpaint, steps, cfg,
            seed, init_image, amount=str(params.get('opAmount') or 'mid'),
            shrink=_truthy(params.get('opShrink')))
    else:
        wf = build_workflow(full_prompt, negative, checkpoint, width, height,
                            steps, cfg, 'dpmpp_2m', 'karras', seed, batch,
                            hires=HIRES.get(hires_key, None),
                            init_image=init_image, denoise=denoise,
                            control=control or None, control_strength=control_strength)

    # ---------- ③ 提交 ----------
    t0 = time.time()
    try:
        sub = http_json(COMFY + '/prompt', {'prompt': wf, 'client_id': 'simple-ui'}, timeout=90)
    except Exception as e:
        return {'ok': False, 'error': '提交失败：%s' % e}
    pid = sub.get('prompt_id')
    if not pid:
        return {'ok': False, 'error': '提交后没有拿到任务号'}

    # 等执行完（视频慢得多，给 30 分钟）
    entry = None
    deadline = time.time() + (1800 if mode == 'video' else 900)
    while time.time() < deadline:
        time.sleep(2.0)
        try:
            h = http_json('%s/history/%s' % (COMFY, pid), timeout=20)
        except Exception:
            continue
        if pid in h:
            e = h[pid]
            st = (e.get('status') or {}).get('status_str')
            if st == 'error':
                detail = ''
                for m in (e.get('status') or {}).get('messages', []):
                    if m and m[0] == 'execution_error':
                        detail = str((m[1] or {}).get('exception_message', '')).strip()
                return {'ok': False, 'error': 'ComfyUI 执行报错：%s' % (detail or '未知')}
            outs = e.get('outputs') or {}
            if outs:
                entry = e
                break
    if not entry:
        return {'ok': False, 'error': '执行超时'}

    # ---------- ④ 收输出（图片/视频按扩展名归类）----------
    files, images, videos = [], [], []
    for node in (entry.get('outputs') or {}).values():
        for key in ('images', 'gifs', 'videos', 'audio'):
            for it in (node.get(key) or []):
                if not isinstance(it, dict) or not it.get('filename'):
                    continue
                if (it.get('type') or 'output') != 'output':
                    continue
                sub = (it.get('subfolder') or '').replace('\\', '/').strip('/')
                fn = it['filename']
                name = (sub + '/' + fn) if sub else fn
                if os.path.splitext(fn)[1].lower() in ('.mp4', '.webm', '.mkv', '.mov', '.gif'):
                    videos.append(name)
                else:
                    images.append(name)
                files.append(name)
    if not files:
        return {'ok': False, 'error': '执行完成但没有输出文件'}

    result = {
        'ok': True,
        'mode': mode,
        'images': images,
        'videos': videos,
        'files': files,
        'seed': seed,
        'checkpoint': checkpoint,
        'style': style_key,
        'initImage': init_image,
        'denoise': denoise,
        'prompt': full_prompt,
        'translated': translated,
        'dropped': dropped,
        'engine': engine,
        'applied': applied,
        'elapsed': round(time.time() - t0, 2),
    }
    if mode == 'video':
        result['vsize'] = '%dx%d' % (width, height)
        result['frames'] = length
        result['seconds'] = round(length / float(VIDEO_FPS), 2)
    else:
        factor = (HIRES.get(hires_key) or (1,))[0]
        result['imgMode'] = 'i2i' if init_image else 'txt2img'
        if control:
            result['imgMode'] = 'controlnet'
            result['control'] = control
            result['controlStrength'] = control_strength
        if outpaint:
            result['imgMode'] = 'outpaint'
            result['outpaint'] = outpaint
            result['outpaintCanvas'] = '%dx%d' % out_canvas
        result['aspectFixed'] = aspect_fixed
        result['size'] = '%dx%d' % (width, height)
        result['hires'] = hires_key
        result['outSize'] = '%dx%d' % (int(round(width * factor)), int(round(height * factor)))
        if outpaint:
            result['outSize'] = result['outpaintCanvas']   # 扩图的实际输出 = 补完的画布
    return result


def _img_path(name):
    """把 name（可能带 simpleui_preview/ 前缀）解析成真实路径；越界一律拒绝。"""
    name = (name or '').replace('\\', '/').lstrip('/')
    if not name or '..' in name:
        return ''
    base = os.path.realpath(COMFY_OUTPUT)
    p = os.path.realpath(os.path.join(COMFY_OUTPUT, name))
    return p if (p == base or p.startswith(base + os.sep)) and os.path.isfile(p) else ''


def recent_images(limit=24):
    """最近生成：优先预览缓存目录，其次 output 根目录（你以前生成的那些）。"""
    out = []
    for sub in (PREVIEW_SUBDIR, ''):
        d = os.path.join(COMFY_OUTPUT, sub) if sub else COMFY_OUTPUT
        try:
            files = [f for f in os.listdir(d)
                     if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp',
                                            '.gif', '.mp4', '.webm', '.mkv', '.mov'))]
        except Exception:
            continue
        files.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
        for f in files:
            out.append((sub + '/' + f) if sub else f)
    return out[:limit]


def clear_preview():
    """清空预览缓存。"""
    d = os.path.join(COMFY_OUTPUT, PREVIEW_SUBDIR)
    n = 0
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                os.remove(p)
                n += 1
    except Exception:
        pass
    return n


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = 'simple-ui/1.0'

    def log_message(self, fmt, *args):
        pass  # 静音访问日志

    def _send(self, code, payload, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        elif isinstance(payload, str):
            payload = payload.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except Exception:
            pass

    def _read_json(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n).decode('utf-8')
        return json.loads(raw) if raw.strip() else {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        if u.path in ('/', '/index.html'):
            try:
                with open(os.path.join(HERE, 'index.html'), 'rb') as f:
                    self._send(200, f.read(), 'text/html; charset=utf-8')
            except Exception as e:
                self._send(500, {'ok': False, 'error': str(e)})
            return

        if u.path in ('/logo.png', '/favicon.ico'):
            # 页面左上角的 logo 用 png；浏览器自动请求的 /favicon.ico 给真正的图标文件，
            # 这样窗口标题栏和任务栏按钮才有图标（以前这里 404，图标是空的）
            if u.path == '/favicon.ico':
                cand = [(os.path.join(HERE, 'icon-v2.ico'), 'image/x-icon'),
                        (os.path.join(HERE, 'logo.png'), 'image/png')]
            else:
                cand = [(os.path.join(HERE, 'logo.png'), 'image/png')]
            for path, ctype in cand:
                try:
                    with open(path, 'rb') as f:
                        self._send(200, f.read(), ctype)
                    return
                except Exception:
                    continue
            self._send(404, {'ok': False, 'error': 'logo not found'})
            return

        if u.path == '/api/state':
            rules = load_rules()
            self._send(200, {
                'ok': True,
                'comfy': comfy_up(),
                'models': list_models(),
                'styles': {k: v['label'] for k, v in STYLES.items()},
                # 风格会连带的模型和附加提示词 —— 让页面能明确告诉用户「这个风格到底做了什么」
                'styleModels': {k: v['model'] for k, v in STYLES.items()},
                'styleTokens': {k: v['tokens'] for k, v in STYLES.items()},
                'recent': recent_images(),
                'moderation': True,
                'translateEnabled': TRANSLATE_ENABLED,
                'translateProxy': _good_proxy,
                'blockPatterns': sum(1 for r in rules if r['enabled']),
                'ruleCount': len(rules),
                'rules': [{'name': r['name'], 'pattern': r['pattern'], 'enabled': r['enabled']} for r in rules],
                'rulesFile': RULES_FILE,
            })
            return

        if u.path == '/api/recent':
            self._send(200, {'ok': True, 'images': recent_images(int((q.get('limit') or ['24'])[0]))})
            return

        # /api/img 是页面内预览；/api/download 是「保存到本地」（浏览器下载）
        if u.path in ('/api/img', '/api/download'):
            path = _img_path((q.get('name') or [''])[0])
            if not path:
                self._send(404, {'ok': False, 'error': '图片不存在'})
                return
            ext = os.path.splitext(path)[1].lower()
            ctype = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                     '.webp': 'image/webp', '.gif': 'image/gif',
                     '.mp4': 'video/mp4', '.webm': 'video/webm',
                     '.mkv': 'video/x-matroska', '.mov': 'video/quicktime'
                     }.get(ext, 'application/octet-stream')
            extra = None
            if u.path == '/api/download':
                extra = {'Content-Disposition': 'attachment; filename="%s"' % os.path.basename(path)}
            with open(path, 'rb') as f:
                self._send(200, f.read(), ctype, extra)
            return

        self._send(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)

        # 检测自测：只跑规则，不产图、不碰 ComfyUI。
        # 用来调规则：改完 BLOCK_PATTERNS 后，把各种写法丢进来看到底命中没有。
        if u.path == '/api/check':
            try:
                params = self._read_json()
            except Exception as e:
                self._send(400, {'ok': False, 'error': '请求格式错误：%s' % e})
                return
            text = params.get('text') or ''
            negative = params.get('negative') or ''
            ok, reason = moderate(text, negative)
            rules = load_rules()
            hay = normalize(text) + ' ' + normalize(negative)
            comp = compact(text) + compact(negative)
            matched = []
            for r in rules:
                if not r['enabled'] or not r['pattern']:
                    continue
                m = r['re'].search(hay) or r['re'].search(comp)
                if m:
                    matched.append({'name': r['name'], 'pattern': r['pattern'], 'hit': m.group(0)[:60]})
            self._send(200, {
                'ok': True,
                'blocked': not ok,
                'reason': reason,
                'matched': matched,
                'rules': sum(1 for r in rules if r['enabled']),
                'ruleCount': len(rules),
                'normalized': normalize(text),
                'compact': comp,
            })
            return

        # 保存规则：页面里改完点「保存」走这里。先校验正则，写坏了直接拒绝，不会把规则改废。
        if u.path == '/api/rules':
            try:
                params = self._read_json()
            except Exception as e:
                self._send(400, {'ok': False, 'error': '请求格式错误：%s' % e})
                return
            incoming = params.get('rules')
            if not isinstance(incoming, list):
                self._send(400, {'ok': False, 'error': 'rules 必须是数组'})
                return
            clean = []
            for i, r in enumerate(incoming):
                if not isinstance(r, dict):
                    continue
                pat = str(r.get('pattern') or '').strip()
                if not pat:
                    continue
                try:
                    re.compile(pat)
                except re.error as e:
                    self._send(400, {'ok': False,
                                     'error': '第 %d 条规则的正则写错了：%s' % (i + 1, e)})
                    return
                clean.append({'name': str(r.get('name') or ('规则%d' % (i + 1))).strip(),
                              'pattern': pat,
                              'enabled': bool(r.get('enabled', True))})
            try:
                save_rules(clean)
            except Exception as e:
                self._send(500, {'ok': False, 'error': '写入 rules.json 失败：%s' % e})
                return
            load_rules(force=True)
            self._send(200, {'ok': True, 'count': len(clean),
                             'enabled': sum(1 for r in clean if r['enabled'])})
            return

        # 在资源管理器里定位这张图（本机操作，方便你另存/拖走）
        if u.path == '/api/reveal':
            try:
                params = self._read_json()
            except Exception:
                params = {}
            path = _img_path(params.get('name') or '')
            if not path:
                self._send(404, {'ok': False, 'error': '图片不存在'})
                return
            try:
                subprocess.Popen(['explorer', '/select,' + path])
                self._send(200, {'ok': True, 'path': path})
            except Exception as e:
                self._send(500, {'ok': False, 'error': str(e)})
            return

        # 清空预览缓存
        if u.path == '/api/clear-preview':
            self._send(200, {'ok': True, 'removed': clear_preview()})
            return

        if u.path == '/api/generate':
            try:
                params = self._read_json()
            except Exception as e:
                self._send(400, {'ok': False, 'error': '请求格式错误：%s' % e})
                return
            try:
                result = generate(params)
            except Exception as e:
                result = {'ok': False, 'error': '内部错误：%s' % e}
            self._send(200 if result.get('ok') else 200, result)
            return
        self._send(404, {'ok': False, 'error': 'not found'})


def main():
    if not os.path.isdir(COMFY_ROOT):
        print('找不到 ComfyUI 目录。')
        print('本程序需要和 ComfyUI 整合包放在一起。请任选一种方式指定：')
        print('  1) 在本目录建 config.json：{"comfy_root": "<你的 ComfyUI 根目录>"}')
        print('  2) 设环境变量 PICMOTION_COMFY_ROOT')
        print('  3) 把本目录直接放进整合包根目录下一层（自动探测）')
        sys.exit(1)
    _remember_runtime()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    rules = load_rules()
    print('=' * 56)
    print(' 极简画影 已启动')
    print(' 请在浏览器打开： http://%s:%d' % (HOST, PORT))
    print(' ComfyUI 目录： %s' % COMFY_ROOT)
    print(' 违规检测： 已启用（%d 条规则，%d 条生效）' %
          (len(rules), sum(1 for r in rules if r['enabled'])))
    print(' 规则文件： %s' % RULES_FILE)
    print(' 按 Ctrl+C 关闭')
    print('=' * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已关闭')


if __name__ == '__main__':
    main()
