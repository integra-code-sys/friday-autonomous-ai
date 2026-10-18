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
import inspect
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
MOTOR_FILE = os.path.join(MEM_DIR, "orquestra_motor.json")      # {"pausado": bool} do motor da fila do orquestra_geral
OG_LOCK = threading.RLock()     # orquestra_geral tem UMA sessão em disco: um avancar() por vez (motor, objetivos, agent)
TELAS_DIR = os.path.join(ROOT, "shell", "telas_dinamicas")
WEB_TELAS_DIR = os.path.join(HERE, "web", "telas")

os.makedirs(MEM_DIR, exist_ok=True)
os.makedirs(TELAS_DIR, exist_ok=True)
os.makedirs(WEB_TELAS_DIR, exist_ok=True)


def _loop_atual():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


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
        self._loop = _loop_atual()      # loop do daemon: as threads emitem por ele (get_event_loop() falha fora da thread principal)
        self._motor_th: Optional[threading.Thread] = None
        self._motor_stop: Optional[threading.Event] = None
        self._liberar_sid = ""          # sessão bloqueada que o dono mandou retomar
        self._carregar_checkpoint()
        self._iniciar_retomada_automatica()

    # ------------------------------------------------------------------ Persistência
    def _carregar_checkpoint(self):
        with self.lock:
            if os.path.exists(OBJETIVOS_FILE):
                try:
                    with open(OBJETIVOS_FILE, "r", encoding="utf-8") as f:
                        self.objetivos = json.load(f)
                    if not isinstance(self.objetivos, dict):
                        self.objetivos = {}
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
                if inspect.iscoroutinefunction(self.broadcast):
                    # threads do orquestrador não têm loop: agenda no loop do daemon guardado na criação
                    loop = self._loop or _loop_atual()
                    if loop is not None and loop.is_running():
                        asyncio.run_coroutine_threadsafe(self.broadcast(msg), loop)
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

        # 1. Leitura unificada da tela e consulta de lições compactas
        try:
            import auto_aprendizado
            pv = auto_aprendizado.pensar_com_visao_e_licoes(objetivo, contexto)
            if pv.get("licoes_consultadas"):
                pensamento["licoes_consultadas"] = pv["licoes_consultadas"]
            if pv.get("tela_atual", {}).get("janela"):
                pensamento["tela_foco"] = pv["tela_atual"]["janela"]
                pensamento["analise_situacional"] += f" Janela em foco: '{pv['tela_atual']['janela']}'."
        except Exception:
            pass

        # 2. Avalia dificuldades na tela se fornecidas
        dificuldades = contexto.get("dificuldade_tela") or []
        if dificuldades:
            pensamento["riscos_detectados"].append(f"Detectadas dificuldades na tela: {len(dificuldades)} erros")
            pensamento["analise_situacional"] += " A tela contém erros que precisam de contorno adaptativo."

        # 3. Avalia emoção do usuário
        emocao = contexto.get("emocao_usuario") or "neutro"
        if emocao in ("frustrado", "triste", "cansado"):
            pensamento["analise_situacional"] += f" Usuário está {emocao}; priorizar resposta direta, sem rodeios."

        # 4. Trava de segurança para ações perigosas
        perigosos = [r"\brm\s+-rf\b", r"\bmkfs\b", r"\bdd\s+if=", r"\bformat\b", r"\bdrop\s+database\b", r"\bpay\b", r"\btransfer\b"]
        for p in perigosos:
            if re.search(p, acao_planejada, re.I):
                pensamento["autorizado"] = False
                pensamento["riscos_detectados"].append("Comando destrutivo ou financeiro detectado. Bloqueado sem confirmação direta.")
                pensamento["estrategia"] = "Solicitar aprovação explícita ao usuário antes de qualquer execução."
                break

        if pensamento["autorizado"]:
            licoes_txt = f" (aplicando lições de {', '.join(pensamento.get('licoes_consultadas', []))})" if pensamento.get("licoes_consultadas") else ""
            pensamento["estrategia"] = f"Executar {acao_planejada}{licoes_txt} com verificação adaptativa de pós-condição."

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
                anterior = obj.get("status")
                if anterior == "aguardando_dono":
                    obj["_liberado"] = True          # dono mandou retomar: segue a sessão depois do passo sensível
                elif anterior == "concluido":
                    obj.pop("_sessao_id", None)      # rodar de novo = plano novo
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

            # Inicia thread se não estiver rodando (ou se a viva já recebeu parada: pausar+retomar rápido perdia o worker)
            antigo_stop = self.stops.get(objetivo_id)
            if objetivo_id not in self.threads or not self.threads[objetivo_id].is_alive() or antigo_stop is None or antigo_stop.is_set():
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

    def retomar_objetivo(self, objetivo_id: str) -> Dict[str, Any]:
        with self.lock:
            obj = self.objetivos.get(objetivo_id)
            if not obj:
                return {"ok": False, "erro": "Objetivo não encontrado."}
            return self.iniciar_ou_retomar_objetivo(objetivo_id, obj.get("titulo") or objetivo_id, obj.get("instrucao") or "",
                                                    obj.get("tipo") or "continua", obj.get("intervalo_s") or 60.0)

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
                fim = obj.pop("_og_fim", None)      # None = sem orquestra_geral (fallback); "seguir" = plano em andamento

                # 3. Atualização do checkpoint
                with self.lock:
                    obj["erros_seguidos"] = 0
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

                # Sessão bloqueada (passo sensível fica com o dono) ou recusada: para e NÃO continua sozinho
                if fim in ("bloqueada", "recusada"):
                    with self.lock:
                        obj["status"] = "aguardando_dono" if fim == "bloqueada" else "bloqueado_seguranca"
                        self.salvar_checkpoint()
                    self.emitir({"type": "orquestrador_ciclo", "id": obj_id, "ciclo": obj["ciclos_executados"], "status": obj["status"]})
                    break

                # Tarefa rápida/longa concluída (com orquestra_geral: só quando o PLANO acabou, não no 1º passo):
                if (obj.get("tipo") == "rapida" and fim in (None, "concluida")) or (obj.get("tipo") == "longa" and fim == "concluida"):
                    with self.lock:
                        obj["status"] = "concluido"
                        self.salvar_checkpoint()
                    try:
                        import auto_aprendizado
                        auto_aprendizado.get_banco_conhecimento().registrar_aprendizado(
                            tarefa=obj.get("titulo", obj_id),
                            sucesso=True,
                            detalhes=str(obj.get("ultimo_resultado", "Concluído com sucesso"))[:240],
                            solucao="Orquestração rápida finalizada"
                        )
                    except Exception:
                        pass
                    break

            except Exception as e:
                _log_ev("erro_ciclo", {"id": obj_id, "erro": str(e)})
                obj.pop("_og_fim", None)
                with self.lock:
                    obj["ultimo_erro"] = str(e)
                    obj["erros_seguidos"] = int(obj.get("erros_seguidos") or 0) + 1
                    desistir = obj.get("tipo") in ("rapida", "longa") and obj["erros_seguidos"] >= 5
                    if desistir:
                        obj["status"] = "falhou"         # sem isso uma tarefa finita repetia o erro para sempre
                    self.salvar_checkpoint()
                try:
                    import auto_aprendizado
                    auto_aprendizado.get_banco_conhecimento().registrar_aprendizado(
                        tarefa=obj.get("titulo", obj_id),
                        sucesso=False,
                        detalhes=str(e)[:240],
                        solucao="Replanejamento e adaptação contínua"
                    )
                except Exception:
                    pass
                if desistir:
                    break

            # Espera intervalo ou sinal de parada
            intervalo = obj.get("intervalo_s", 60.0)
            if stop_evt.wait(intervalo):
                break

    def _executar_passo_orquestrado(self, obj: Dict[str, Any]) -> str:
        """Um passo real do plano persistente. Shell cru só se a instrução começar com sh:."""
        instrucao = obj.get("instrucao", "")
        obj.pop("_og_fim", None)
        try:
            import orquestra_geral as og
            with OG_LOCK:
                # orquestra_geral guarda UMA sessão: cada objetivo avança só a SUA (id), sem atropelar a da fila/de outro
                atual = og.status().get("sessao") or {}
                sid = obj.get("_sessao_id")
                liberado = obj.pop("_liberado", False)   # vale UMA vez e só para a sessão que estava bloqueada
                if sid and atual.get("id") != sid:
                    sid = None                       # a sessão deste objetivo foi substituída: replaneja quando o slot vagar
                if not sid:
                    liberado = False
                    if atual.get("status") == "ativa":
                        obj["_og_fim"] = "seguir"
                        return f"aguardando: outra sessão ativa ({atual.get('id')})"
                    ses = og.sessao_nova(instrucao)
                    if not ses.get("ok"):
                        obj["_og_fim"] = "recusada"
                        return ses.get("fala") or "recusado"
                    sid = obj["_sessao_id"] = (ses.get("sessao") or {}).get("id")
                    atual = ses.get("sessao") or {}
                st = atual.get("status")
                if st == "recusada":
                    obj["_og_fim"] = "recusada"
                    return atual.get("fala") or "recusada"
                if st == "bloqueada" and not liberado:
                    obj["_og_fim"] = "bloqueada"     # avancar() não checa bloqueio: chamar de novo pulava o passo sensível
                    ult = (atual.get("evidencia") or [{}])[-1] or {}
                    return "sessão bloqueada: " + str(ult.get("res") or "passo sensível aguarda o dono")[:300]
                if st == "concluida":
                    obj.pop("_sessao_id", None)      # contínua: próximo ciclo replaneja
                    obj["_og_fim"] = "concluida"
                    return "plano concluído"
                if st == "pausada":
                    obj["_og_fim"] = "seguir"
                    return "sessão pausada"
                r = og.avancar()
            st = (r.get("sessao") or {}).get("status")
            if st == "concluida":
                obj.pop("_sessao_id", None)
            obj["_og_fim"] = st if st in ("concluida", "bloqueada", "recusada") else "seguir"
            return (r.get("fala") or "sem resultado")[:800]
        except ImportError as e:
            _log_ev("orquestra_fallback", {"erro": str(e)[:180]})
        except Exception as e:
            _log_ev("orquestra_erro", {"id": obj.get("id"), "erro": str(e)[:180]})
            raise                                    # erro no passo NÃO é "concluído": o worker registra e tenta no próximo ciclo
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
        # fila/sessão do orquestra_geral também sobrevivem a reboot (ex.: "amanhã às 9h faça Y")
        try:
            import orquestra_geral as og
            st = og.status()
            pend = any(i.get("status") in ("esperando", "ativo") for i in (st.get("fila") or {}).get("itens") or [])
            if pend or (st.get("sessao") or {}).get("status") == "ativa":
                self.garantir_motor()
        except Exception as e:
            _log_ev("erro_motor", {"erro": "retomada: " + str(e)[:180]})

    # ------------------------------------------------------------------ Motor da fila/sessão do orquestra_geral
    def _motor_pausado(self) -> bool:
        try:
            with open(MOTOR_FILE, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("pausado"))
        except Exception:
            return False

    def _motor_gravar(self, pausado: bool):
        try:
            tmp = MOTOR_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pausado": bool(pausado), "t": time.time()}, f)
            os.replace(tmp, MOTOR_FILE)
        except Exception as e:
            _log_ev("erro_motor", {"erro": str(e)[:180]})

    def motor_estado(self) -> Dict[str, Any]:
        rodando = bool(self._motor_th and self._motor_th.is_alive() and self._motor_stop and not self._motor_stop.is_set())
        return {"pausado": self._motor_pausado(), "rodando": rodando}

    def garantir_motor(self, intervalo_s: float = 20.0) -> bool:
        """Liga (uma vez) a thread que puxa a fila (horário 'quando') e avança a sessão longa. False = dono pausou."""
        with self.lock:
            if self._motor_pausado():
                return False
            if self.motor_estado()["rodando"]:
                return True
            self._motor_stop = threading.Event()
            self._motor_th = threading.Thread(target=self._motor_loop, args=(self._motor_stop, intervalo_s),
                                              daemon=True, name="orquestra-motor")
            self._motor_th.start()
            _log_ev("motor_ligado", {"intervalo_s": intervalo_s})
            return True

    def pausar_motor(self) -> Dict[str, Any]:
        with self.lock:
            self._motor_gravar(True)
            if self._motor_stop:
                self._motor_stop.set()
        _log_ev("motor_pausado", {})
        return {"ok": True, "mensagem": "Orquestrador pausado. A sessão e a fila ficaram salvas; diga retomar para continuar."}

    def retomar_motor(self) -> Dict[str, Any]:
        sid = ""
        try:
            import orquestra_geral as og
            ses = og.status().get("sessao") or {}
            if ses.get("status") == "bloqueada" and not any(o.get("_sessao_id") == ses.get("id") for o in self.listar_objetivos()):
                sid = ses.get("id") or ""          # dono mandou seguir: continua depois do passo sensível
        except Exception:
            pass
        with self.lock:
            self._liberar_sid = sid
            self._motor_gravar(False)
        self.garantir_motor()
        return {"ok": True, "mensagem": "Orquestrador retomado" + (": continuando a sessão que esperava por você." if sid else ".")}

    def _motor_loop(self, stop_evt: threading.Event, intervalo_s: float):
        """Mesma regra do orquestra_geral.loop (um objetivo ativo, fila por horário), mas pausável e sem morrer em erro."""
        while not stop_evt.is_set():
            try:
                import orquestra_geral as og
                if not og.trava_unica():           # outro processo (ex.: friday-orquestra.service) já executa
                    if stop_evt.wait(max(1.0, float(intervalo_s))):
                        break
                    continue
                with OG_LOCK:
                    ses = og.status().get("sessao") or {}
                    with self.lock:
                        donos = {o.get("_sessao_id") for o in self.objetivos.values()
                                 if o.get("_sessao_id") and o.get("status") in ("ativo", "pausado")}
                        liberar = self._liberar_sid
                        self._liberar_sid = ""
                    if ses.get("id") in donos:
                        pass                           # sessão de um objetivo contínuo: o worker dele é quem avança
                    elif ses.get("status") == "ativa" or (liberar and ses.get("status") == "bloqueada" and ses.get("id") == liberar):
                        if not stop_evt.is_set():
                            r = og.avancar()
                            self.emitir({"type": "orquestrador_sessao", "id": ses.get("id"),
                                         "status": (r.get("sessao") or {}).get("status"), "fala": str(r.get("fala") or "")[:300]})
                    else:
                        it = og.fila_tick()            # sessão acabou/bloqueou: libera o próximo da fila cujo horário chegou
                        if it:
                            _log_ev("motor_fila", {"item": it.get("id")})
            except Exception as e:
                _log_ev("erro_motor", {"erro": str(e)[:200]})
            if stop_evt.wait(max(1.0, float(intervalo_s))):
                break

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
    if broadcast_fn is not None and _ORQUESTRADOR._loop is None:
        _ORQUESTRADOR._loop = _loop_atual()     # singleton criado antes fora do loop (agent/cerebro): pega o loop agora
    return _ORQUESTRADOR
