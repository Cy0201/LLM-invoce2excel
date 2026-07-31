# -*- coding: utf-8 -*-
"""
ai_client.py —— 网关客户端（Anthropic Messages 协议）  v7
需要连哪个网关：环境变量 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / CLAUDE_MODEL
由于协议同为 Anthropic Messages，把 base_url/token/model 指向
https://api.anthropic.com + claude 模型即可直接切到 Claude 做对照测试，代码零改动。

相对旧版的关键改动：
  1. 预填 JSON（assistant prefill "{"）：从生成第一个 token 起就锁死 JSON 输出，
     比"请只输出JSON"的口头约定可靠得多；个别网关不接受 assistant 结尾消息时
     自动降级并记住，不再重试预填。
  2. 认证双保险：同时携带 x-api-key 与 Authorization: Bearer——
     内网网关两种写法都有，官方 Anthropic 走 x-api-key，一套配置全兼容。
  3. qwen 系思考抑制双保险：chat_template_kwargs.enable_thinking=false
     （vLLM/SGLang 认的写法）+ system 末尾 /no_think 软开关；
     即便网关不透传，也能显著降低"思考吃光 max_tokens"的概率，
     且响应里的 <think> 块始终会被剥离。
  4. 返回 (text, stop_reason)：上层能看见 max_tokens 截断并自动升额重试
     （旧版把截断吞掉了，长表就悄悄少行）。
  5. 视觉能力探测：带图请求返回空 content 时抛 AIResponseError(no_vision=True)，
     上层据此自动改走"OCR 文本"路线，而不是反复撞墙。
  6. 内置 JSON 修复（去尾逗号/补右括号/剥代码栅栏），json_repair 装了更好、
     不装也能跑。
"""
import re
import json
import time
import random
import logging

logger = logging.getLogger('ai_client')

import os as _os
DEFAULT_TIMEOUT = float(_os.environ.get('AI_TIMEOUT', '300'))  # 慢模型生成长表可能超3分钟


class GatewayConfig(object):
    def __init__(self, base_url, token, model, timeout=None):
        self.base_url = (base_url or '').rstrip('/')
        self.token = (token or '').strip()
        self.model = (model or 'qwen3.6').strip()
        self.timeout = float(timeout or DEFAULT_TIMEOUT)

    def is_qwen_like(self):
        return bool(re.search(r'qwen|glm|deepseek|hunyuan|minimax', self.model, re.I))


class AIResponseError(RuntimeError):
    """网关有响应但拿不到可用正文。带诊断信息与 no_vision 标记。"""

    def __init__(self, msg, no_vision=False):
        super(AIResponseError, self).__init__(msg)
        self.no_vision = no_vision


# ══════════════════════════════════════════════════════════════
#  响应正文抽取（剥 thinking，区分空响应成因）
# ══════════════════════════════════════════════════════════════
_THINK = re.compile(r'<thinking\b[^>]*>.*?</thinking>|<think>.*?</think>', re.S | re.I)


def _strip_think(t):
    t = _THINK.sub('', t or '')
    t = re.sub(r'<think>.*\Z', '', t, flags=re.S | re.I).strip()
    # 兜底：去掉任何残留的 <thinking...>...</thinking>
    t = re.sub(r'<thinking\b[^>]*>.*?</thinking>', '', t, flags=re.S | re.I).strip()
    return t


def _resp_text(resp, had_image):
    content = getattr(resp, 'content', None)
    if content is None and isinstance(resp, dict):
        content = resp.get('content')
    stop = getattr(resp, 'stop_reason', None) or (
        resp.get('stop_reason') if isinstance(resp, dict) else None)
    if isinstance(content, str):
        return _strip_think(content), stop
    blocks = list(content or [])
    parts, kinds, think_len = [], [], 0
    for b in blocks:
        bt = b.get('type') if isinstance(b, dict) else getattr(b, 'type', None)
        tx = b.get('text') if isinstance(b, dict) else getattr(b, 'text', None)
        th = b.get('thinking') if isinstance(b, dict) else getattr(b, 'thinking', None)
        kinds.append(str(bt or '?'))
        if tx and bt in (None, 'text'):
            parts.append(str(tx))
        if th:
            think_len += len(str(th))
    text = _strip_think('\n'.join(parts))
    if text:
        return text, stop
    if think_len:
        raise AIResponseError(
            '模型只输出了 %d 字的思考块、没有正文（stop_reason=%s）。已通过 '
            'chat_template_kwargs.enable_thinking=false 与 /no_think 双重关闭思考；'
            '若仍出现，请在网关侧确认思考开关是否透传。' % (think_len, stop))
    if not blocks:
        if had_image:
            raise AIResponseError(
                '带图片的请求返回了空 content（stop_reason=%s）——该网关/模型不支持'
                '视觉输入。已自动切换 OCR 文本路线（建议安装 rapidocr-onnxruntime '
                '以提升扫描件效果，或换用视觉模型）。' % stop, no_vision=True)
        raise AIResponseError('网关返回空 content（stop_reason=%s）。' % stop)
    raise AIResponseError('响应中没有文本块，块类型=%s（stop_reason=%s）。' % (kinds, stop))


# ══════════════════════════��═════════════════════════════
#  客户端
# ══════════════════════════════════════════════════════════════
class AIClient(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self._prefill_ok = True     # 网关拒绝 assistant 预填时降级并记住

    def _extra_body(self):
        if self.cfg.is_qwen_like():
            return {'chat_template_kwargs': {'enable_thinking': False}}
        return None

    def _system(self, system):
        if self.cfg.is_qwen_like() and '/no_think' not in system:
            return system + '\n/no_think'
        return system

    def call(self, kind, system, user, max_tokens, image_b64=None):
        """统一入口。kind ∈ {'text','vision'}；返回 (text, stop_reason)。
        测试可整体替换本方法（app._AI_CALL_OVERRIDE）。"""
        if self.cfg.is_qwen_like():
            return self._raw_call(kind, system, user, max_tokens, image_b64)
        return self._sdk_call(kind, system, user, max_tokens, image_b64)

    def _sdk_call(self, kind, system, user, max_tokens, image_b64=None):
        """通过 Anthropic SDK（非 qwen 模型使用）。"""
        import anthropic
        client = anthropic.Anthropic(
            base_url=self.cfg.base_url or None,
            api_key=self.cfg.token or 'EMPTY',
            auth_token=self.cfg.token or None,
            timeout=self.cfg.timeout,
            max_retries=0)
        if kind == 'vision' and image_b64:
            content = [
                {'type': 'image',
                 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                            'data': image_b64}},
                {'type': 'text', 'text': user}]
            had_image = True
        else:
            content = user
            had_image = False
        msgs = [{'role': 'user', 'content': content}]
        use_prefill = self._prefill_ok
        if use_prefill:
            msgs.append({'role': 'assistant', 'content': '{'})

        def _do(messages):
            return client.messages.create(
                model=self.cfg.model, max_tokens=int(max_tokens), temperature=0,
                system=self._system(system), messages=messages,
                extra_body=self._extra_body())

        try:
            resp = _do(msgs)
        except Exception as e:
            if use_prefill and _looks_like_bad_request(e):
                logger.info('网关不支持 assistant 预填，已降级（本会话不再预填）')
                self._prefill_ok = False
                resp = _do(msgs[:-1])
            else:
                raise
        text, stop = _resp_text(resp, had_image)
        if use_prefill and self._prefill_ok and not text.lstrip().startswith('{'):
            text = '{' + text
        return text, stop

    def _raw_call(self, kind, system, user, max_tokens, image_b64=None):
        """通过 raw HTTP 请求（qwen 模型专用，确保 thinking 参数透传）。"""
        import httpx
        if kind == 'vision' and image_b64:
            content = [
                {'type': 'image',
                 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                            'data': image_b64}},
                {'type': 'text', 'text': user}]
            had_image = True
        else:
            content = user
            had_image = False
        msgs = [{'role': 'user', 'content': content}]
        use_prefill = self._prefill_ok
        if use_prefill:
            msgs.append({'role': 'assistant', 'content': '{'})

        body = {
            'model': self.cfg.model,
            'max_tokens': int(max_tokens),
            'temperature': 0,
            'messages': msgs,
            'system': self._system(system),
            'chat_template_kwargs': {'enable_thinking': False},
        }
        if image_b64:
            body['images'] = [image_b64]  # qwen 网关可能用 images 而非 content[0].image
        logger.info('raw_call body: model=%s max_tokens=%d thinking=%s', self.cfg.model, body['max_tokens'], body.get('chat_template_kwargs'))

        headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.cfg.token,
            'Authorization': f'Bearer {self.cfg.token}',
        }

        with httpx.Client(timeout=self.cfg.timeout) as http:
            resp = http.post(
                self.cfg.base_url + '/v1/messages',
                json=body, headers=headers)

        if resp.status_code == 400 and use_prefill and 'assistant' in resp.text.lower():
            logger.info('网关不支持 assistant 预填，已降级')
            self._prefill_ok = False
            body['messages'] = msgs[:-1]
            resp = http.post(
                self.cfg.base_url + '/v1/messages',
                json=body, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f'HTTP {resp.status_code}: {resp.text[:500]}')

        data = resp.json()
        content = data.get('content', [])
        stop = data.get('stop_reason', '')

        parts = []
        think_len = 0
        if isinstance(content, str):
            text = _strip_think(content)
            if text:
                return text, stop
            if '<thinking' in (content or '') or '<think>' in (content or ''):
                think_len = len(content)
        else:
            for b in (content or []):
                bt = b.get('type')
                tx = b.get('text')
                th = b.get('thinking')
                if tx and bt in (None, 'text'):
                    parts.append(str(tx))
                if th:
                    think_len += len(str(th))

        text = _strip_think('\n'.join(parts))
        if text:
            return text, stop
        if think_len:
            raise AIResponseError(
                '模型只输出了 %d 字的思考块、没有正文（stop_reason=%s）。'
                '已通过 raw HTTP chat_template_kwargs.enable_thinking=false 关闭思考；'
                '请在网关侧确认思考开关是否透传。' % (think_len, stop))
        if not content:
            raise AIResponseError('网关返回空 content（stop_reason=%s）。' % stop)
        raise AIResponseError('响应中没有文本块（stop_reason=%s）。' % stop)


def _looks_like_bad_request(e):
    try:
        import anthropic
        if isinstance(e, anthropic.BadRequestError):
            return True
    except Exception:
        pass
    return 'assistant' in str(e).lower() and '400' in str(e)


# ══════════════════════════════════════════════════════════════
#  网络级重试（解析类错误由上层阶梯处理）
# ══════════════════════════════════════════════════════════════
def _net_errs():
    errs = (ConnectionError, TimeoutError)
    for mod, names in (('httpx', ('TransportError', 'TimeoutException')),
                       ('anthropic', ('APIConnectionError', 'APITimeoutError',
                                      'InternalServerError', 'RateLimitError',
                                      'APIStatusError'))):
        try:
            m = __import__(mod)
            errs += tuple(getattr(m, n) for n in names if hasattr(m, n))
        except Exception:
            pass
    return errs


def robust_call(fn, net_retries=4, ctx=''):
    NET = _net_errs()
    n, last = 0, None
    while True:
        try:
            return fn()
        except AIResponseError:
            raise                                    # 语义错误直接上抛，由阶梯处理
        except NET as e:
            code = getattr(e, 'status_code', None)
            if code is not None and int(code) in (400, 401, 403, 404, 413, 422):
                raise                                # 请求本身有问题，重试无意义
            n += 1
            last = e
            if n > net_retries:
                break
            d = min(8.0, 0.6 * 2 ** n) + random.uniform(0, 0.4)
            logger.warning('%s网络错误#%d: %s，%.1fs 后重试', ctx, n, e, d)
            time.sleep(d)
    raise last


# ══════════════════════════════════════════════════════════════
#  JSON 解析（多策略容错，内置修复，json_repair 可选增强）
# ══════════════════════════════════════════════════════════════
def _find_json(t):
    depth, instr, esc, s = 0, False, False, None
    for i, ch in enumerate(t):
        if instr:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch in '{[':
            if depth == 0:
                s = i
            depth += 1
        elif ch in '}]':
            if depth > 0:
                depth -= 1
                if depth == 0 and s is not None:
                    return t[s:i + 1]
    return t[s:] if s is not None else None


def _basic_repair(t):
    """够用的本地修复：去尾逗号、补齐未闭合括号/引号。"""
    t = re.sub(r',\s*([}\]])', r'\1', t)
    stack, instr, esc = [], False, False
    for ch in t:
        if instr:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch in '{[':
            stack.append('}' if ch == '{' else ']')
        elif ch in '}]':
            if stack and stack[-1] == ch:
                stack.pop()
    if instr:
        t += '"'
    t = re.sub(r',\s*$', '', t.rstrip())
    return t + ''.join(reversed(stack))


def _fence_strip(t):
    t = re.sub(r'^```(?:json)?\s*', '', t.strip())
    return re.sub(r'\s*```$', '', t).strip()


def parse_json(text):
    """尽最大努力把模型输出解析成 dict。失败抛 ValueError（带片段便于排查）。"""
    cleaned = _fence_strip(_strip_think(text))
    cands = [cleaned]
    if not cleaned.lstrip().startswith(('{', '[')):
        cands.append('{' + cleaned)                  # 预填被网关吞掉的情况
    found = _find_json(cleaned)
    if found:
        cands.append(found)
    tried = []
    for c in cands:
        tried.append(c)
        try:
            d = json.loads(c)
            return d if isinstance(d, dict) else {'items': d}
        except Exception:
            pass
    for c in tried:
        try:
            d = json.loads(_basic_repair(c))
            return d if isinstance(d, dict) else {'items': d}
        except Exception:
            pass
    try:
        from json_repair import repair_json
        d = json.loads(repair_json(cleaned))
        return d if isinstance(d, dict) else {'items': d}
    except Exception:
        pass
    raise ValueError('JSON 解析失败: %s' % cleaned[:200])
