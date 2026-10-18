"""Motor Genesis de Memória e Aprendizado do Zero — F.R.I.D.A.Y. Commercial Edition.

Responsável por:
1. Limpeza geral de bancos de dados (Factory Reset / Zero-State) sem nenhum dado pessoal prévio.
2. Inicialização limpa de todas as estruturas SQLite (memoria.sqlite, episodios.sqlite) e JSONs.
3. Onboarding de primeiro uso (configuração inicial do nome do usuário, voz, câmeras e preferências).
4. Aprendizado Contínuo Orgânico do Zero:
   - Memória Factual (fatos sobre o usuário, ambiente, aplicativos instalados e rotinas).
   - Memória Episódica (receitas de ações que deram certo em tarefas anteriores).
   - Auto-Reflexão e Lições (extração automática de regras a partir de falhas para não repetir erros).
"""
import difflib
import glob
import json
import os
import secrets
import sqlite3
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MEM = os.path.join(ROOT, "memory")

DB_MEMORIA = os.path.join(MEM, "memoria.sqlite")
DB_EPISODIOS = os.path.join(MEM, "episodios.sqlite")
CONFIG_COMERCIAL = os.path.join(MEM, "config_comercial.json")

_LOCK = threading.RLock()

CONFIG_PADRAO = {
    "versao": "2.3.1-commercial",
    "onboarding_concluido": False,
    "usuario": {
        "nome": "Chefe",
        "idioma": "pt-BR",
        "tratamento": "você"
    },
    "boot": {
        "iniciar_no_boot": False
    },
    "ia": {
        "provedor_cerebro": "ollama",      # ollama | gemini | claude | openai | auto
        "provedor_visao": "ollama",        # ollama | gemini | claude | openai | auto
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_modelo_cerebro": "qwen3-vl:4b-instruct",
        "ollama_modelo_visao": "qwen3-vl:4b-instruct",
        "gemini_api_key": "",
        "gemini_modelo": "gemini-2.5-flash",
        "claude_api_key": "",
        "claude_modelo": "claude-3-5-sonnet-latest",
        "openai_api_key": "",
        "openai_modelo": "gpt-4o"
    },
    "cameras": {
        "modo": "auto",                    # auto | sem_camera | 1_camera | 2_cameras | 3_cameras_ptz
        "quantidade_detectada": 0,
        "camera_principal": "auto",        # índice (0, 1) ou caminho (/dev/video0)
        "camera_secundaria": "none",       # índice, caminho ou URL RTSP
        "camera_ptz_ip": "",
        "camera_ptz_usuario": "admin",
        "camera_ptz_senha": "",
        "camera_ptz_rtsp": ""
    },
    "voz": {
        "ativa": True,
        "tts_motor": "auto",               # auto | piper | supertonic | pocket | edge
        "stt_motor": "faster-whisper",
        "wake_word": "Sexta-feira"
    },
    "mesh": {
        "ativo": True,
        "porta_http": 8790,
        "porta_udp": 8792
    }
}

POLITICA_PADRAO = {
    "confirmar": [
        "email.send",
        "wa.send",
        "sms.send",
        "file.delete",
        "pkg.install",
        "remote.connect",
        "shell.write"
    ],
    "bloquear": []
}


def _ler_json(caminho, padrao=None):
    if not os.path.exists(caminho):
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def _salvar_json(caminho, dados, privado=False):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)
    os.replace(tmp, caminho)
    if privado and hasattr(os, "chmod"):
        try:
            os.chmod(caminho, 0o600)
        except Exception:
            pass


def carregar_config():
    """Carrega a configuração comercial unificada, preenchendo chaves novas com o padrão."""
    with _LOCK:
        if not os.path.exists(CONFIG_COMERCIAL):
            _salvar_json(CONFIG_COMERCIAL, CONFIG_PADRAO, privado=True)
            return json.loads(json.dumps(CONFIG_PADRAO))
        atual = _ler_json(CONFIG_COMERCIAL, {}) or {}
        mesclado = json.loads(json.dumps(CONFIG_PADRAO))
        for k, v in atual.items():
            if isinstance(v, dict) and isinstance(mesclado.get(k), dict):
                mesclado[k].update(v)
            else:
                mesclado[k] = v
        return mesclado


def salvar_config(nova_cfg):
    """Salva alterações na configuração comercial."""
    with _LOCK:
        atual = carregar_config()
        for k, v in nova_cfg.items():
            if isinstance(v, dict) and isinstance(atual.get(k), dict):
                atual[k].update(v)
            else:
                atual[k] = v
        _salvar_json(CONFIG_COMERCIAL, atual, privado=True)
        # Sincroniza nome do usuário com profile.json se mudou
        if "usuario" in nova_cfg and "nome" in nova_cfg["usuario"]:
            prof_path = os.path.join(MEM, "profile.json")
            prof = _ler_json(prof_path, {}) or {}
            prof["nome"] = atual["usuario"]["nome"]
            _salvar_json(prof_path, prof)
        return atual


def _inicializar_sqlite_memoria():
    """Cria a estrutura limpa do banco memoria.sqlite."""
    con = sqlite3.connect(DB_MEMORIA, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS fatos(
            tipo TEXT,
            chave TEXT,
            resumo TEXT,
            dados BLOB,
            visto_1 REAL,
            visto_ult REAL,
            vezes INTEGER DEFAULT 1,
            PRIMARY KEY(tipo, chave)
        );
        CREATE TABLE IF NOT EXISTS linha(
            id INTEGER PRIMARY KEY,
            t0 REAL,
            t1 REAL,
            tipo TEXT,
            resumo TEXT
        );
        CREATE INDEX IF NOT EXISTS linha_t ON linha(t1);
        CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5(
            tipo, chave, resumo,
            tokenize='unicode61 remove_diacritics 2'
        );
    """)
    con.commit()
    con.close()


def _inicializar_sqlite_episodios():
    """Cria a estrutura limpa do banco episodios.sqlite."""
    con = sqlite3.connect(DB_EPISODIOS, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE VIRTUAL TABLE IF NOT EXISTS ep USING fts5(
            pedido, passos, resultado, t UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        );
    """)
    con.commit()
    con.close()


def inicializar_do_zero(forcar=False, nome_usuario="Chefe", manter_config_ia=True):
    """Realiza a limpeza geral do banco de dados e inicializa a memória 100% do zero (Factory Reset).
    Se forcar=False, apenas garante que os arquivos existem sem apagar dados existentes."""
    with _LOCK:
        os.makedirs(MEM, exist_ok=True)
        os.makedirs(os.path.join(MEM, "planos"), exist_ok=True)
        os.makedirs(os.path.join(MEM, "ptz_vistas"), exist_ok=True)
        os.makedirs(os.path.join(MEM, "construtor"), exist_ok=True)
        os.makedirs(os.path.join(MEM, "dev"), exist_ok=True)

        cfg_antiga = carregar_config() if (manter_config_ia and os.path.exists(CONFIG_COMERCIAL)) else None

        if forcar:
            try:
                if "memoria" in sys.modules:
                    _m = sys.modules["memoria"]
                    if getattr(_m, "_con", None) is not None:
                        try:
                            _m._con.close()
                        except Exception:
                            pass
                        _m._con = None
            except Exception:
                pass
            # Remove bancos SQLite, WAL/SHM e logs de conversas/ações pessoais
            for padrao in ("*.sqlite", "*.sqlite-wal", "*.sqlite-shm", "*.jsonl", "*.bak", "node_id.txt", "mesh_state.json"):
                for arq in glob.glob(os.path.join(MEM, padrao)):
                    try:
                        os.remove(arq)
                    except OSError:
                        pass
            # Limpa vistas salvas de câmeras
            for arq in glob.glob(os.path.join(MEM, "ptz_vistas", "*")):
                try:
                    os.remove(arq)
                except OSError:
                    pass

        # 1. Bancos SQLite limpos
        _inicializar_sqlite_memoria()
        _inicializar_sqlite_episodios()

        # 2. Configuração comercial
        nova_cfg = json.loads(json.dumps(CONFIG_PADRAO))
        if cfg_antiga and manter_config_ia:
            nova_cfg["ia"] = cfg_antiga.get("ia", nova_cfg["ia"])
            nova_cfg["cameras"] = cfg_antiga.get("cameras", nova_cfg["cameras"])
            nova_cfg["boot"] = cfg_antiga.get("boot", nova_cfg["boot"])
        nova_cfg["usuario"]["nome"] = nome_usuario
        nova_cfg["onboarding_concluido"] = False
        if forcar or not os.path.exists(CONFIG_COMERCIAL):
            _salvar_json(CONFIG_COMERCIAL, nova_cfg, privado=True)

        # 3. Arquivos de estado JSON limpos (sem dados pessoais)
        estados_iniciais = {
            "profile.json": {
                "nome": nome_usuario,
                "fatos": {},
                "session": secrets.token_hex(8),
                "ultima_vez": time.time(),
                "conversas": 0,
                "turnos": 0,
                "camera": True,
                "voice": True,
                "autonomia": True,
                "onboarding_concluido": False
            },
            "agenda.json": {"itens": []},
            "tarefas.json": {"itens": []},
            "licoes.json": [],
            "aprendido.json": {"fatos": [], "preferencias": {}},
            "people.json": {"pessoas": {}},
            "voz_dono.json": {"nome": nome_usuario, "limiar": 0.58, "amostras": []},
            "voz.json": {"tts_motor": "auto", "mic_limpo": True},
            "friday.json": {"cerebro": "ativo", "autonomia": True},
            "peers.json": {"peers": []},
            "remotos.json": {"hosts": {}},
            "mundo_pares.json": {"nativa": [], "porta": []},
            "camera_ptz.json": {"posicoes": {}, "limites": {}},
            "aprovacoes.json": {"itens": []},
            "politica.json": POLITICA_PADRAO,
            "gestos.json": {"ativos": True},
            "zap.json": {"ativo": False}
        }

        for nome_arq, conteudo in estados_iniciais.items():
            caminho = os.path.join(MEM, nome_arq)
            if forcar or not os.path.exists(caminho):
                _salvar_json(caminho, conteudo)

        # 4. Token de acesso remoto novo e exclusivo para a instalação
        remoto_path = os.path.join(MEM, "remoto.json")
        if forcar or not os.path.exists(remoto_path):
            _salvar_json(remoto_path, {"token": secrets.token_urlsafe(18)}, privado=True)

        # 5. Arquivos JSONL vazios
        for jl in ("conversas.jsonl", "auditoria.jsonl", "acoes.jsonl"):
            p = os.path.join(MEM, jl)
            if forcar or not os.path.exists(p):
                open(p, "w", encoding="utf-8").close()

        return {
            "ok": True,
            "msg": "Memória e bancos de dados inicializados do zero com sucesso.",
            "usuario": nome_usuario,
            "timestamp": time.time()
        }


# ----------------------------------------------------------------- Aprendizado Contínuo do Zero
atualizar_config = salvar_config


def gravar_fato_aprendido(tipo, chave, resumo, dados=None):
    """Registra um fato aprendido organicamente do zero no SQLite."""
    with _LOCK:
        if not os.path.exists(DB_MEMORIA):
            _inicializar_sqlite_memoria()
        agora = time.time()
        con = sqlite3.connect(DB_MEMORIA, timeout=10)
        try:
            cur = con.cursor()
            r = cur.execute("SELECT visto_1, vezes FROM fatos WHERE tipo=? AND chave=?", (tipo, chave)).fetchone()
            if r:
                cur.execute(
                    "UPDATE fatos SET resumo=?, visto_ult=?, vezes=? WHERE tipo=? AND chave=?",
                    (resumo, agora, int(r[1] or 1) + 1, tipo, chave)
                )
            else:
                cur.execute(
                    "INSERT INTO fatos(tipo, chave, resumo, dados, visto_1, visto_ult, vezes) VALUES(?,?,?,?,?,?,1)",
                    (tipo, chave, resumo, None, agora, agora)
                )
            cur.execute("DELETE FROM busca WHERE tipo=? AND chave=?", (tipo, chave))
            cur.execute("INSERT INTO busca(tipo, chave, resumo) VALUES(?,?,?)", (tipo, chave, resumo))
            con.commit()
            return True
        finally:
            con.close()


def registrar_episodio_aprendido(pedido, passos, resultado):
    """Registra uma tarefa bem-sucedida na memória episódica para reutilização futura."""
    with _LOCK:
        if not os.path.exists(DB_EPISODIOS):
            _inicializar_sqlite_episodios()
        if isinstance(passos, list):
            passos = " -> ".join(str(x) for x in passos)
        con = sqlite3.connect(DB_EPISODIOS, timeout=10)
        try:
            con.execute(
                "INSERT INTO ep(pedido, passos, resultado, t) VALUES(?,?,?,?)",
                (str(pedido)[:300], str(passos)[:600], str(resultado)[:400], time.time())
            )
            con.commit()
            return True
        finally:
            con.close()


def registrar_licao_aprendida(texto_licao, *partes_extras):
    """Adiciona uma lição aprendida a partir de erro/reflexão, evitando duplicatas semânticas."""
    if partes_extras:
        texto_licao = " | ".join([str(texto_licao)] + [str(p) for p in partes_extras if p])
    txt = str(texto_licao or "").strip()[:220]
    if len(txt) < 10:
        return False
    with _LOCK:
        lic_path = os.path.join(MEM, "licoes.json")
        licoes = _ler_json(lic_path, []) or []
        for l in licoes:
            if difflib.SequenceMatcher(None, txt.lower(), l.get("txt", "").lower()).ratio() > 0.75:
                l["t"] = time.time()
                _salvar_json(lic_path, licoes)
                return False
        licoes.append({"txt": txt, "t": time.time()})
        _salvar_json(lic_path, licoes[-50:])
        return True


def concluir_onboarding(nome_usuario="Chefe", provedor_ia="ollama", modo_cameras="auto"):
    """Conclui o onboarding inicial do usuário e registra os primeiros fatos na memória limpa."""
    cfg = carregar_config()
    cfg["onboarding_concluido"] = True
    cfg["usuario"]["nome"] = nome_usuario
    cfg["ia"]["provedor_cerebro"] = provedor_ia
    cfg["ia"]["provedor_visao"] = provedor_ia
    cfg["cameras"]["modo"] = modo_cameras
    salvar_config(cfg)

    prof_path = os.path.join(MEM, "profile.json")
    prof = _ler_json(prof_path, {}) or {}
    prof["nome"] = nome_usuario
    prof["onboarding_concluido"] = True
    prof["ultima_vez"] = time.time()
    _salvar_json(prof_path, prof)

    gravar_fato_aprendido("dono", "nome", f"O usuário principal chama-se {nome_usuario}")
    gravar_fato_aprendido("sistema", "instalacao", f"Sistema inicializado do zero em {time.strftime('%Y-%m-%d %H:%M')}")
    return {"ok": True, "usuario": nome_usuario, "onboarding_concluido": True}


def status_memoria():
    """Retorna métricas completas do estado atual da memória e aprendizado."""
    fatos_n = 0
    eventos_n = 0
    episodios_n = 0
    try:
        if os.path.exists(DB_MEMORIA):
            con = sqlite3.connect(DB_MEMORIA, timeout=5)
            fatos_n = con.execute("SELECT COUNT(*) FROM fatos").fetchone()[0]
            eventos_n = con.execute("SELECT COUNT(*) FROM linha").fetchone()[0]
            con.close()
    except Exception:
        pass
    try:
        if os.path.exists(DB_EPISODIOS):
            con = sqlite3.connect(DB_EPISODIOS, timeout=5)
            episodios_n = con.execute("SELECT COUNT(*) FROM ep").fetchone()[0]
            con.close()
    except Exception:
        pass
    licoes_n = len(_ler_json(os.path.join(MEM, "licoes.json"), []) or [])
    pessoas_n = len((_ler_json(os.path.join(MEM, "people.json"), {}) or {}).get("pessoas", {}))

    cfg = carregar_config()
    concluido = bool(cfg.get("onboarding_concluido", False))
    return {
        "onboarding_concluido": concluido,
        "onboarding_pendente": not concluido,
        "usuario": cfg.get("usuario", {}).get("nome", "Chefe"),
        "fatos_aprendidos": fatos_n,
        "eventos_registrados": eventos_n,
        "episodios_aprendidos": episodios_n,
        "licoes_auto_reflexao": licoes_n,
        "licoes_aprendidas": licoes_n,
        "pessoas_conhecidas": pessoas_n
    }


if __name__ == "__main__":
    if "--reset" in sys.argv or "--init" in sys.argv:
        nome = "Chefe"
        for i, a in enumerate(sys.argv):
            if a == "--nome" and i + 1 < len(sys.argv):
                nome = sys.argv[i + 1]
        res = inicializar_do_zero(forcar=("--reset" in sys.argv), nome_usuario=nome)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(status_memoria(), indent=2, ensure_ascii=False))
