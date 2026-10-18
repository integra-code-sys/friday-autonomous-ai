"""Motor Híbrido de IA e Visão (Local + Nuvem) — F.R.I.D.A.Y. Commercial Edition.

Permite usar tanto modelos 100% locais (via Ollama) quanto modelos em nuvem de ponta:
- Google Gemini (ex: gemini-2.5-flash, gemini-2.5-pro)
- Anthropic Claude (ex: claude-3-5-sonnet-latest, claude-3-7-sonnet-latest)
- OpenAI GPT (ex: gpt-4o, gpt-4o-mini)
- Modo 'auto' (usa nuvem se houver chave configurada com fallback p/ local, ou local com fallback p/ nuvem)

Compatível tanto com Visão Multimodal (imagens JPEG em base64) quanto com o Cérebro ReAct (tool-calling nativo).
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import memoria_zero as MZ

_MOCK_HTTP = None  # Usado pela suíte de testes para inspecionar payloads de Gemini/Claude/OpenAI


def set_mock_http(fn):
    """Permite injetar um interceptador HTTP(url, headers, body_dict) -> dict para testes de cenários."""
    global _MOCK_HTTP
    _MOCK_HTTP = fn


def _http_post_json(url, headers, body_dict, timeout=45):
    import privacy_guard
    cfg_ia = MZ.carregar_config().get("ia", {})
    privacy_guard.validar_url_saida(url, ollama_url_custom=cfg_ia.get("ollama_url", ""))
    if _MOCK_HTTP is not None:
        return _MOCK_HTTP(url, headers, body_dict)
    raw = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": "FRIDAY-IntegraCode-Commercial/2.0"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=raw, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def obter_config_ia():
    cfg = MZ.carregar_config().get("ia", {})
    for prov in ("gemini", "claude", "openai"):
        sub = cfg.get(prov)
        if isinstance(sub, dict):
            if not cfg.get(f"{prov}_api_key") and sub.get("api_key"):
                cfg[f"{prov}_api_key"] = sub["api_key"]
            if not cfg.get(f"{prov}_model") and (sub.get("modelo_visao") or sub.get("modelo_cerebro")):
                cfg[f"{prov}_model"] = sub.get("modelo_visao") or sub.get("modelo_cerebro")
    # Variáveis de ambiente têm precedência opcional se definidas
    if os.environ.get("GEMINI_API_KEY"):
        cfg["gemini_api_key"] = os.environ["GEMINI_API_KEY"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg["claude_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        cfg["openai_api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("FRIDAY_VISION_PROVIDER"):
        cfg["provedor_visao"] = os.environ["FRIDAY_VISION_PROVIDER"]
    if os.environ.get("FRIDAY_BRAIN_PROVIDER"):
        cfg["provedor_cerebro"] = os.environ["FRIDAY_BRAIN_PROVIDER"]
    return cfg


def resolver_provedor(tipo="visao", explicito=None):
    """Retorna o provedor efetivo ('ollama', 'gemini', 'claude', 'openai')."""
    cfg = obter_config_ia()
    escolha = (explicito or cfg.get(f"provedor_{tipo}") or "ollama").strip().lower()
    if escolha in ("gemini", "google"):
        return "gemini"
    if escolha in ("claude", "anthropic"):
        return "claude"
    if escolha in ("openai", "gpt", "chatgpt"):
        return "openai"
    if escolha == "auto":
        if cfg.get("gemini_api_key"):
            return "gemini"
        if cfg.get("openai_api_key"):
            return "openai"
        if cfg.get("claude_api_key"):
            return "claude"
        return "ollama"
    return "ollama"


# =====================================================================
# 1. VISÃO MULTIMODAL (VLM: Tela, Câmeras, Objetos, OCR assistido)
# =====================================================================
def consultar_vlm(jpg_bytes, prompt, max_tokens=220, temp=0.1, provider=None, timeout=40):
    """Analisa uma imagem JPEG usando o provedor configurado (Ollama, Gemini, Claude ou OpenAI)."""
    if not jpg_bytes:
        return None
    cfg = obter_config_ia()
    prov = resolver_provedor("visao", provider)
    b64 = base64.b64encode(jpg_bytes).decode("ascii")
    instrucao = "Responda em português do Brasil, de forma clara, natural e objetiva. " + str(prompt)

    ordem = [prov]
    if prov != "ollama":
        ordem.append("ollama")  # Fallback seguro para local se nuvem falhar

    for p in ordem:
        try:
            if p == "gemini":
                res = _vlm_gemini(b64, instrucao, cfg, max_tokens, temp, timeout)
                if res:
                    return res
            elif p == "claude":
                res = _vlm_claude(b64, instrucao, cfg, max_tokens, temp, timeout)
                if res:
                    return res
            elif p == "openai":
                res = _vlm_openai(b64, instrucao, cfg, max_tokens, temp, timeout)
                if res:
                    return res
            elif p == "ollama":
                res = _vlm_ollama(b64, instrucao, cfg, max_tokens, temp, timeout)
                if res:
                    return res
        except Exception as e:
            print(f"[VISAO-{p.upper()}] falha: {str(e)[:120]}", flush=True)
    return None


def _vlm_ollama(b64, prompt, cfg, max_tokens, temp, timeout):
    url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/generate"
    modelo = cfg.get("ollama_modelo_visao", "qwen3-vl:4b-instruct")
    body = {
        "model": modelo,
        "stream": False,
        "prompt": prompt,
        "images": [b64],
        "options": {"temperature": temp, "num_predict": max_tokens, "num_ctx": 8192, "num_gpu": 99}
    }
    r = _http_post_json(url, {}, body, timeout=timeout)
    return (r.get("response") or "").strip() or None


def _vlm_gemini(b64, prompt, cfg, max_tokens, temp, timeout):
    key = cfg.get("gemini_api_key", "").strip()
    if not key:
        raise ValueError("Chave gemini_api_key não configurada")
    modelo = cfg.get("gemini_modelo", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={key}"
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}}
            ]
        }],
        "generationConfig": {
            "temperature": temp,
            "maxOutputTokens": max_tokens
        }
    }
    r = _http_post_json(url, {}, body, timeout=timeout)
    cands = r.get("candidates") or []
    if cands:
        parts = (cands[0].get("content") or {}).get("parts") or []
        txts = [p.get("text", "") for p in parts if "text" in p]
        return " ".join(txts).strip() or None
    return None


def _vlm_claude(b64, prompt, cfg, max_tokens, temp, timeout):
    key = cfg.get("claude_api_key", "").strip()
    if not key:
        raise ValueError("Chave claude_api_key não configurada")
    modelo = cfg.get("claude_modelo", "claude-3-5-sonnet-latest")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01"
    }
    body = {
        "model": modelo,
        "max_tokens": max_tokens,
        "temperature": temp,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    }
    r = _http_post_json(url, headers, body, timeout=timeout)
    blocos = r.get("content") or []
    txts = [b.get("text", "") for b in blocos if b.get("type") == "text"]
    return " ".join(txts).strip() or None


def _vlm_openai(b64, prompt, cfg, max_tokens, temp, timeout):
    key = cfg.get("openai_api_key", "").strip()
    if not key:
        raise ValueError("Chave openai_api_key não configurada")
    modelo = cfg.get("openai_modelo", "gpt-4o")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}"}
    body = {
        "model": modelo,
        "max_tokens": max_tokens,
        "temperature": temp,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]
        }]
    }
    r = _http_post_json(url, headers, body, timeout=timeout)
    choices = r.get("choices") or []
    if choices:
        return ((choices[0].get("message") or {}).get("content") or "").strip() or None
    return None


# =====================================================================
# 2. CÉREBRO MULTI-TURNO COM TOOL-CALLING (Ollama, Gemini, Claude, GPT)
# =====================================================================
def chat_com_ferramentas(msgs, tools, temperature=0.2, max_tokens=600, timeout=120, provider=None):
    """Executa um passo do Cérebro ReAct com suporte a ferramentas e imagens em qualquer provedor.
    Retorna formato padronizado:
    {"message": {"role": "assistant", "content": "...", "tool_calls": [{"function": {"name": "...", "arguments": {...}}}]}}
    """
    cfg = obter_config_ia()
    prov = resolver_provedor("cerebro", provider)

    ordem = [prov]
    if prov != "ollama":
        ordem.append("ollama")

    ultimo_erro = None
    for p in ordem:
        try:
            if p == "gemini":
                return _chat_gemini(msgs, tools, cfg, temperature, max_tokens, timeout)
            if p == "claude":
                return _chat_claude(msgs, tools, cfg, temperature, max_tokens, timeout)
            if p == "openai":
                return _chat_openai(msgs, tools, cfg, temperature, max_tokens, timeout)
            return _chat_ollama(msgs, tools, cfg, temperature, max_tokens, timeout)
        except Exception as e:
            ultimo_erro = e
            print(f"[CEREBRO-{p.upper()}] falha: {str(e)[:120]}", flush=True)
    if ultimo_erro:
        raise ultimo_erro
    return {"message": {"role": "assistant", "content": "", "tool_calls": []}}


def _chat_ollama(msgs, tools, cfg, temperature, max_tokens, timeout):
    url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    limpas = []
    for m in msgs:
        mm = {k: v for k, v in m.items() if k != "images"}
        limpas.append(mm)
    modelo = cfg.get("ollama_modelo_cerebro", "qwen3.5:4b")
    body = {
        "model": modelo,
        "stream": False,
        "messages": limpas,
        "tools": tools,
        "think": False,
        "options": {"temperature": temperature, "num_predict": max(max_tokens, 1500), "num_ctx": 8192, "num_gpu": 99}
    }
    resp = _http_post_json(url, {}, body, timeout=timeout)
    msg = resp.get("message") or {}
    if not msg.get("content") and msg.get("thinking"):
        msg["content"] = msg["thinking"]
    return resp



def _chat_openai(msgs, tools, cfg, temperature, max_tokens, timeout):
    key = cfg.get("openai_api_key", "").strip()
    if not key:
        raise ValueError("Chave openai_api_key não configurada")
    modelo = cfg.get("openai_modelo", "gpt-4o")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}"}

    oai_msgs = []
    for m in msgs:
        role = m.get("role", "user")
        content = m.get("content", "")
        imgs = m.get("images") or []
        if role == "tool":
            oai_msgs.append({
                "role": "user",
                "content": f"[Resultado da ferramenta {m.get('tool_name', '')}]: {content}"
            })
        elif imgs:
            partes = [{"type": "text", "text": content or "Analise a imagem."}]
            for im_b64 in imgs:
                partes.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{im_b64}"}})
            oai_msgs.append({"role": "user", "content": partes})
        elif m.get("tool_calls"):
            oai_msgs.append({"role": "assistant", "content": content or "Executando ferramenta."})
        else:
            oai_msgs.append({"role": role, "content": content})

    body = {
        "model": modelo,
        "messages": oai_msgs,
        "tools": tools,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    r = _http_post_json(url, headers, body, timeout=timeout)
    msg = (r.get("choices") or [{}])[0].get("message") or {}
    tcalls = []
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments") or "{}"
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        tcalls.append({"function": {"name": fn.get("name", ""), "arguments": args}})
    return {"message": {"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcalls}}


def _chat_gemini(msgs, tools, cfg, temperature, max_tokens, timeout):
    key = cfg.get("gemini_api_key", "").strip()
    if not key:
        raise ValueError("Chave gemini_api_key não configurada")
    modelo = cfg.get("gemini_modelo", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={key}"

    sys_inst = ""
    contents = []
    for m in msgs:
        role = m.get("role", "user")
        content = m.get("content", "")
        imgs = m.get("images") or []
        if role == "system":
            sys_inst += content + "\n"
        elif role == "tool":
            contents.append({
                "role": "user",
                "parts": [{"text": f"[Resultado da ferramenta {m.get('tool_name', '')}]: {content}"}]
            })
        elif role == "assistant":
            tcs = m.get("tool_calls") or []
            parts = []
            if content:
                parts.append({"text": content})
            for tc in tcs:
                fn = tc.get("function") or {}
                parts.append({"functionCall": {"name": fn.get("name", ""), "args": fn.get("arguments") or {}}})
            if parts:
                contents.append({"role": "model", "parts": parts})
        else:
            parts = [{"text": content or "Ok"}]
            for im_b64 in imgs:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": im_b64}})
            contents.append({"role": "user", "parts": parts})

    decls = []
    for t in (tools or []):
        fn = t.get("function") or {}
        params = dict(fn.get("parameters") or {"type": "object", "properties": {}})
        params.pop("additionalProperties", None)
        decls.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": params
        })

    body = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
    }
    if sys_inst.strip():
        body["systemInstruction"] = {"parts": [{"text": sys_inst.strip()}]}
    if decls:
        body["tools"] = [{"functionDeclarations": decls}]

    r = _http_post_json(url, {}, body, timeout=timeout)
    parts = ((r.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    txt_parts = []
    tcalls = []
    for p in parts:
        if "text" in p:
            txt_parts.append(p["text"])
        if "functionCall" in p:
            fc = p["functionCall"]
            tcalls.append({"function": {"name": fc.get("name", ""), "arguments": fc.get("args") or {}}})
    return {"message": {"role": "assistant", "content": " ".join(txt_parts).strip(), "tool_calls": tcalls}}


def _chat_claude(msgs, tools, cfg, temperature, max_tokens, timeout):
    key = cfg.get("claude_api_key", "").strip()
    if not key:
        raise ValueError("Chave claude_api_key não configurada")
    modelo = cfg.get("claude_modelo", "claude-3-5-sonnet-latest")
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}

    sys_inst = ""
    c_msgs = []
    for m in msgs:
        role = m.get("role", "user")
        content = m.get("content", "")
        imgs = m.get("images") or []
        if role == "system":
            sys_inst += content + "\n"
        elif role == "tool":
            c_msgs.append({
                "role": "user",
                "content": f"[Resultado da ferramenta {m.get('tool_name', '')}]: {content}"
            })
        elif role == "assistant":
            c_msgs.append({"role": "assistant", "content": content or "Executando passo."})
        else:
            if imgs:
                blocos = []
                for im_b64 in imgs:
                    blocos.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": im_b64}
                    })
                blocos.append({"type": "text", "text": content or "Analise a imagem."})
                c_msgs.append({"role": "user", "content": blocos})
            else:
                c_msgs.append({"role": "user", "content": content or "Ok"})

    c_tools = []
    for t in (tools or []):
        fn = t.get("function") or {}
        c_tools.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}
        })

    body = {
        "model": modelo,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": c_msgs
    }
    if sys_inst.strip():
        body["system"] = sys_inst.strip()
    if c_tools:
        body["tools"] = c_tools

    r = _http_post_json(url, headers, body, timeout=timeout)
    blocos = r.get("content") or []
    txt_parts = []
    tcalls = []
    for b in blocos:
        if b.get("type") == "text":
            txt_parts.append(b.get("text", ""))
        elif b.get("type") == "tool_use":
            tcalls.append({"function": {"name": b.get("name", ""), "arguments": b.get("input") or {}}})
    return {"message": {"role": "assistant", "content": " ".join(txt_parts).strip(), "tool_calls": tcalls}}
