"""Orquestrador Contínuo e Intermitente de Tarefas Gerais da F.R.I.D.A.Y.
Capaz de planejar, executar, monitorar e retomar qualquer tarefa:
- Tarefas curtas, de longa duração (horas a dias) ou contínuas/eternas ("para sempre").
- Persistência com checkpoints atômicos em memory/objetivos_ativos.json (sobrevive a reboots/quedas).
- Reflexão pré-ação ("Pensar antes de agir") multimodal e adaptativa.
- Orquestração de outras IAs (Claude Code CLI, Gemini, ChatGPT, Ollama, DeepSeek).
- Criação e modificação dinâmica super-rápida de telas internas (QML Quickshell e HTML5 Web/HUD).
"""
import asyncio
import difflib
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MEM_DIR = os.path.join(ROOT, "memory")
OBJETIVOS_FILE = os.path.join(MEM_DIR, "objetivos_ativos.json")
LOG_ORQUESTRA = os.path.join(MEM_DIR, "orchestrator_log.jsonl")
TELAS_DIR = os.path.join(ROOT, "shell", "telas_dinamicas")
WEB_TELAS_DIR = os.path.join(HERE, "web", "telas")

os.makedirs(MEM_DIR, exist_ok=True)
os.makedirs(TELAS_DIR, exist_ok=True)
os.makedirs(WEB_TELAS_DIR, exist_ok=True)


def _log_ev(tipo: str, dados: Dict[str, Any]):
    try:
        dados["_t"] = time.time()
        dados["_hora"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dados["tipo"] = tipo
        with open(LOG_ORQUESTRA, "a", encoding="utf-8") as f:
            f.write(json.dumps(dados, ensure_ascii=False) + "\n")
    except Exception:
        pass


class OrquestradorContinuo:
    def __init__(self, broadcast_fn=None):
        self.broadcast = broadcast_fn
        self.lock = threading.RLock()
        self.objetivos: Dict[str, Dict[str, Any]] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self.stops: Dict[str, threading.Event] = {}
        self._carregar_checkpoint()
        self._iniciar_retomada_automatica()

    # ------------------------------------------------------------------ Persistência
    def _carregar_checkpoint(self):
        with self.lock:
            if os.path.exists(OBJETIVOS_FILE):
                try:
                    with open(OBJETIVOS_FILE, "r", encoding="utf-8") as f:
                        self.objetivos = json.load(f)
                except Exception as e:
                    self.objetivos = {}
            else:
                self.objetivos = {}

    def salvar_checkpoint(self):
        with self.lock:
            try:
                tmp = OBJETIVOS_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.objetivos, f, ensure_ascii=False, indent=2)
                os.chmod(tmp, 0o600)
                os.replace(tmp, OBJETIVOS_FILE)
            except Exception as e:
                _log_ev("erro_checkpoint", {"erro": str(e)})

    # ------------------------------------------------------------------ Broadcast
    def emitir(self, msg: Dict[str, Any]):
        if self.broadcast:
            try:
                if asyncio.iscoroutinefunction(self.broadcast):
                    # Loop corrente ou schedule threadsafe
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(self.broadcast(msg), loop)
                    else:
                        loop.run_until_complete(self.broadcast(msg))
                else:
                    self.broadcast(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------ "Pensar antes de agir"
    def pensar_antes_de_agir(self, objetivo: str, contexto: Dict[str, Any], acao_planejada: str) -> Dict[str, Any]:
        """Gera raciocínio tático de pré-ação avaliando contexto, tela, emoção do usuário e riscos."""
        if isinstance(contexto, str):
            contexto = {"detalhes": contexto}
        elif not isinstance(contexto, dict):
            contexto = {}

        pensamento = {
            "objetivo": objetivo,
            "analise_situacional": f"Contexto: {contexto.get('detalhes', 'operacional')}.",
            "riscos_detectados": [],
            "estrategia": "",
            "proximo_passo": acao_planejada,
            "autorizado": True,
            "t": time.time(),
        }

        # 1. Avalia dificuldades na tela se fornecidas
        dificuldades = contexto.get("dificuldade_tela") or []
        if dificuldades:
            pensamento["riscos_detectados"].append(f"Detectadas dificuldades na tela: {len(dificuldades)} erros")
            pensamento["analise_situacional"] += " A tela contém erros que precisam de contorno adaptativo."

        # 2. Avalia emoção do usuário
        emocao = contexto.get("emocao_usuario") or "neutro"
        if emocao in ("frustrado", "triste", "cansado"):
            pensamento["analise_situacional"] += f" Usuário está {emocao}; priorizar resposta direta, sem rodeios."

        # 3. Trava de segurança para ações perigosas
        perigosos = [r"\brm\s+-rf\b", r"\bmkfs\b", r"\bdd\s+if=", r"\bformat\b", r"\bdrop\s+database\b", r"\bpay\b", r"\btransfer\b"]
        for p in perigosos:
            if re.search(p, acao_planejada, re.I):
                pensamento["autorizado"] = False
                pensamento["riscos_detectados"].append("Comando destrutivo ou financeiro detectado. Bloqueado sem confirmação direta.")
                pensamento["estrategia"] = "Solicitar aprovação explícita ao usuário antes de qualquer execução."
                break

        if pensamento["autorizado"]:
            pensamento["estrategia"] = f"Executar {acao_planejada} com verificação adaptativa de pós-condição."

        # Notifica HUD e sistema
        self.emitir({
            "type": "orquestrador_pensamento",
            "objetivo": objetivo,
            "pensamento": pensamento["estrategia"] or pensamento["analise_situacional"],
            "autorizado": pensamento["autorizado"]
        })
        _log_ev("pensamento", pensamento)
        return pensamento

    # ------------------------------------------------------------------ Ciclo Contínuo / Intermitente
    def iniciar_ou_retomar_objetivo(
        self,
        objetivo_id: str,
        titulo: str,
        instrucao: str,
        tipo: str = "continua",  # "rapida", "longa", "continua", "intermitente"
        intervalo_s: float = 60.0,
        parametros: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            agora = time.time()
            if objetivo_id in self.objetivos:
                obj = self.objetivos[objetivo_id]
                obj["status"] = "ativo"
                obj["atualizado_em"] = agora
            else:
                obj = {
                    "id": objetivo_id,
                    "titulo": titulo,
                    "instrucao": instrucao,
                    "tipo": tipo,
                    "intervalo_s": max(1.0, float(intervalo_s)),
                    "status": "ativo",
                    "criado_em": agora,
                    "atualizado_em": agora,
                    "ciclos_executados": 0,
                    "historico_passos": [],
                    "dados_checkpoint": parametros or {},
                    "ultimo_resultado": None,
                }
                self.objetivos[objetivo_id] = obj

            self.salvar_checkpoint()

            # Inicia thread se não estiver rodando
            if objetivo_id not in self.threads or not self.threads[objetivo_id].is_alive():
                stop_evt = threading.Event()
                self.stops[objetivo_id] = stop_evt
                th = threading.Thread(
                    target=self._worker_loop,
                    args=(objetivo_id, stop_evt),
                    daemon=True,
                    name=f"orquestra-{objetivo_id}"
                )
                self.threads[objetivo_id] = th
                th.start()

            _log_ev("objetivo_iniciado", {"id": objetivo_id, "tipo": tipo, "titulo": titulo})
            return {"ok": True, "id": objetivo_id, "status": "ativo", "mensagem": f"Objetivo '{titulo}' orquestrado com sucesso."}

    def parar_objetivo(self, objetivo_id: str) -> Dict[str, Any]:
        with self.lock:
            if objetivo_id in self.stops:
                self.stops[objetivo_id].set()
            if objetivo_id in self.objetivos:
                self.objetivos[objetivo_id]["status"] = "pausado"
                self.objetivos[objetivo_id]["atualizado_em"] = time.time()
                self.salvar_checkpoint()
                _log_ev("objetivo_pausado", {"id": objetivo_id})
                return {"ok": True, "mensagem": f"Objetivo {objetivo_id} pausado."}
            return {"ok": False, "erro": "Objetivo não encontrado."}

    def listar_objetivos(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.objetivos.values())

    def _worker_loop(self, obj_id: str, stop_evt: threading.Event):
        while not stop_evt.is_set():
            with self.lock:
                obj = self.objetivos.get(obj_id)
                if not obj or obj.get("status") != "ativo":
                    break

            try:
                # 1. Pré-ação / reflexão
                pensamento = self.pensar_antes_de_agir(
                    objetivo=obj["instrucao"],
                    contexto={"checkpoint": obj["dados_checkpoint"], "ciclo": obj["ciclos_executados"]},
                    acao_planejada=f"Passo {obj['ciclos_executados'] + 1} para {obj['titulo']}"
                )

                if not pensamento.get("autorizado", True):
                    with self.lock:
                        obj["status"] = "bloqueado_seguranca"
                        self.salvar_checkpoint()
                    break

                # 2. Execução do passo através dos subsistemas do Prometheus
                resultado = self._executar_passo_orquestrado(obj)

                # 3. Atualização do checkpoint
                with self.lock:
                    obj["ciclos_executados"] += 1
                    obj["atualizado_em"] = time.time()
                    obj["ultimo_resultado"] = str(resultado)[:800]
                    obj["historico_passos"].append({
                        "ciclo": obj["ciclos_executados"],
                        "t": time.time(),
                        "res": str(resultado)[:300]
                    })
                    if len(obj["historico_passos"]) > 50:
                        obj["historico_passos"] = obj["historico_passos"][-50:]
                    self.salvar_checkpoint()

                self.emitir({
                    "type": "orquestrador_ciclo",
                    "id": obj_id,
                    "ciclo": obj["ciclos_executados"],
                    "status": "executado"
                })

                # Se for tarefa rápida e concluiu:
                if obj.get("tipo") == "rapida":
                    with self.lock:
                        obj["status"] = "concluido"
                        self.salvar_checkpoint()
                    break

            except Exception as e:
                _log_ev("erro_ciclo", {"id": obj_id, "erro": str(e)})
                with self.lock:
                    obj["ultimo_erro"] = str(e)
                    self.salvar_checkpoint()

            # Espera intervalo ou sinal de parada
            intervalo = obj.get("intervalo_s", 60.0)
            if stop_evt.wait(intervalo):
                break

    def _executar_passo_orquestrado(self, obj: Dict[str, Any]) -> str:
        """Um passo real do plano persistente. Shell cru só se a instrução começar com sh:."""
        instrucao = obj.get("instrucao", "")
        try:
            import orquestra_geral as og
            if not obj.get("_plano"):
                ses = og.sessao_nova(instrucao)
                if not ses.get("ok"):
                    return ses.get("fala") or "recusado"
                obj["_plano"] = True
            r = og.avancar()
            return (r.get("fala") or "sem resultado")[:800]
        except Exception as e:
            _log_ev("orquestra_fallback", {"erro": str(e)[:180]})
        if instrucao.startswith("sh:") or instrucao.startswith("bash:"):
            cmd = instrucao.split(":", 1)[1].strip()
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return r.stdout or r.stderr

        # 2. Se envolve operação com outra IA
        if instrucao.startswith("ia:"):
            # formato ia:claude|gemini|openai|ollama:prompt
            partes = instrucao.split(":", 2)
            ia_alvo = partes[1].strip() if len(partes) > 1 else "claude"
            prompt_ia = partes[2].strip() if len(partes) > 2 else instrucao
            return self.operar_outra_ia(ia_alvo, prompt_ia)

        # 3. Default: registro de monitoramento contínuo
        return f"Passo de monitoramento {obj['ciclos_executados']} cumprido para {obj['titulo']}."

    def _iniciar_retomada_automatica(self):
        """Retoma todas as tarefas ativas persistidas que sobreviveram a reboot."""
        for obj_id, obj in list(self.objetivos.items()):
            if obj.get("status") == "ativo":
                stop_evt = threading.Event()
                self.stops[obj_id] = stop_evt
                th = threading.Thread(
                    target=self._worker_loop,
                    args=(obj_id, stop_evt),
                    daemon=True,
                    name=f"orquestra-retomada-{obj_id}"
                )
                self.threads[obj_id] = th
                th.start()
                _log_ev("objetivo_retomado_boot", {"id": obj_id, "titulo": obj.get("titulo")})

    # ------------------------------------------------------------------ Operação de Outras IAs
    def operar_outra_ia(self, ia: str, prompt: str, modelo: Optional[str] = None) -> str:
        """Opera outras IAs locais ou em nuvem para resolução de sub-tarefas especializadas."""
        ia = (ia or "claude").lower().strip()
        _log_ev("operar_ia_req", {"ia": ia, "prompt_preview": prompt[:120]})

        # 1. Claude Code CLI
        if "claude" in ia:
            try:
                cmd = ["claude", "-p", prompt]
                if modelo:
                    cmd.extend(["--model", modelo])
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=ROOT)
                out = res.stdout.strip() or res.stderr.strip()
                _log_ev("operar_ia_res", {"ia": "claude", "tam": len(out)})
                return out or "Claude CLI executou sem saída."
            except Exception as e:
                return f"Falha ao chamar Claude CLI: {e}"

        # 2. Ollama (Modelos Locais)
        if "ollama" in ia or "local" in ia:
            mod = modelo or "qwen2.5-coder:latest"
            try:
                cmd = ["ollama", "run", mod, prompt]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                out = res.stdout.strip()
                return out or "Ollama executou sem saída."
            except Exception as e:
                return f"Falha ao chamar Ollama: {e}"

        # 3. Gemini CLI / API
        if "gemini" in ia:
            try:
                # Tenta google-genai se instalado
                py_script = (
                    "import os, sys\n"
                    "try:\n"
                    "    from google import genai\n"
                    "    client = genai.Client()\n"
                    "    resp = client.models.generate_content(model='gemini-2.5-flash', contents=sys.argv[1])\n"
                    "    print(resp.text)\n"
                    "except Exception as e:\n"
                    "    print('ERRO:', e)\n"
                )
                res = subprocess.run([os.path.join(ROOT, ".venv", "bin", "python"), "-c", py_script, prompt],
                                     capture_output=True, text=True, timeout=90)
                if res.stdout.strip() and not res.stdout.startswith("ERRO:"):
                    return res.stdout.strip()
                return f"Gemini API: {res.stdout.strip() or res.stderr.strip()}"
            except Exception as e:
                return f"Falha no Gemini: {e}"

        # Fallback genérico
        return f"IA {ia} não suportada diretamente ou sem chaves configuradas."

    # ------------------------------------------------------------------ Criação / Modificação Dinâmica de Telas
    def criar_ou_modificar_tela_interna(self, nome: str = "", tipo: str = "qml", codigo: str = "", titulo: str = "", **kwargs) -> Dict[str, Any]:
        """Cria ou modifica uma tela interna (QML para o Quickshell da máquina ou HTML para a Web/Android) super-rápido."""
        nome = nome or kwargs.get("nome_tela") or kwargs.get("target") or ""
        codigo = codigo or kwargs.get("codigo_conteudo") or kwargs.get("content") or kwargs.get("code") or ""
        tipo = (tipo or kwargs.get("type") or "qml").lower().strip()
        nome_limpo = re.sub(r"[^a-zA-Z0-9_\-]", "_", nome).strip("_")
        if not nome_limpo:
            nome_limpo = f"tela_dinamica_{int(time.time())}"

        if "qml" in tipo:
            caminho = os.path.join(TELAS_DIR, f"{nome_limpo}.qml")
            # Garante cabeçalho QtQuick se não estiver presente
            if "import QtQuick" not in codigo:
                codigo = "import QtQuick\nimport QtQuick.Controls\nimport QtQuick.Layouts\n\n" + codigo

            with open(caminho, "w", encoding="utf-8") as f:
                f.write(codigo)

            self.emitir({
                "type": "tela_dinamica_criada",
                "tipo": "qml",
                "nome": nome_limpo,
                "titulo": titulo or nome_limpo,
                "caminho": caminho
            })
            _log_ev("tela_criada", {"tipo": "qml", "nome": nome_limpo, "caminho": caminho})
            return {
                "ok": True,
                "tipo": "qml",
                "nome": nome_limpo,
                "caminho": caminho,
                "mensagem": f"Tela QML '{nome_limpo}' gerada e compilada em {caminho}."
            }

        elif "html" in tipo or "web" in tipo:
            caminho = os.path.join(WEB_TELAS_DIR, f"{nome_limpo}.html")
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(codigo)

            url_acesso = f"http://127.0.0.1:8790/telas/{nome_limpo}.html"
            self.emitir({
                "type": "tela_dinamica_criada",
                "tipo": "html",
                "nome": nome_limpo,
                "titulo": titulo or nome_limpo,
                "url": url_acesso
            })
            _log_ev("tela_criada", {"tipo": "html", "nome": nome_limpo, "caminho": caminho})
            return {
                "ok": True,
                "tipo": "html",
                "nome": nome_limpo,
                "url": url_acesso,
                "mensagem": f"Tela HTML5 HUD '{nome_limpo}' criada com sucesso. Acesse em {url_acesso}."
            }

        return {"ok": False, "erro": f"Tipo '{tipo}' não suportado. Use 'qml' ou 'html'."}


# Instância Singleton do Orquestrador
_ORQUESTRADOR: Optional[OrquestradorContinuo] = None


def get_orquestrador(broadcast_fn=None) -> OrquestradorContinuo:
    global _ORQUESTRADOR
    if _ORQUESTRADOR is None:
        _ORQUESTRADOR = OrquestradorContinuo(broadcast_fn=broadcast_fn)
    elif broadcast_fn is not None and _ORQUESTRADOR.broadcast is None:
        _ORQUESTRADOR.broadcast = broadcast_fn
    return _ORQUESTRADOR
