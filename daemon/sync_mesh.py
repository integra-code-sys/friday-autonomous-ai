"""Sincronizador Mesh Autônomo para F.R.I.D.A.Y. (Projeto Prometheus).
Permite que 3 ou mais nós (Workstation Linux, PC Windows, Servidor/Celular)
mantenham sincronização bidirecional completa e contínua de:
- Agenda (memory/agenda.json) com Last-Write-Wins (LWW) e preservação de tombstones (removido: true)
- Conversas (memory/conversas.jsonl) com união append-only e deduplicação por hash
- Conhecimento e Fatos (memory/memoria.sqlite) com atualização incremental de fatos e busca FTS5
- Lições Aprendidas (memory/licoes.json) com fusão inteligente e deduplicação semântica
- Pessoas e Rostos (memory/people.json) com merge de perfis
- Tarefas (memory/tarefas.json) com resolução por carimbo de tempo
- Perfil do Dono (memory/profile.json)

Descoberta dinâmica via UDP broadcast (porta 8792) + lista de pares estáticos/VPN (memory/peers.json).
Quando um ou dois nós ficam desligados, ao ligarem sincronizam automaticamente tudo o que mudou.
"""
import asyncio
import difflib
import hashlib
import json
import os
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MEM = os.path.join(ROOT, "memory")
PEERS_FILE = os.path.join(MEM, "peers.json")
NODE_FILE = os.path.join(MEM, "node_id.txt")
STATE_FILE = os.path.join(MEM, "mesh_state.json")
REMOTO_CFG = os.path.join(MEM, "remoto.json")

UDP_BEACON_PORT = 8792
DEFAULT_HTTP_PORT = 8790
BEACON_INTERVAL = 10.0
SYNC_INTERVAL = 20.0

_LOCK = threading.RLock()


# ----------------------------------------------------------------- Identidade do Nó e Token
def obter_token_cluster():
    """Retorna o token compartilhado do cluster (de remoto.json)."""
    try:
        if os.path.exists(REMOTO_CFG):
            with open(REMOTO_CFG, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("token"):
                return d["token"]
    except Exception:
        pass
    # Se não existir, gera um padrão fixo de nó ou novo
    tok = "prometheus-mesh-" + secrets.token_urlsafe(16)
    try:
        os.makedirs(MEM, exist_ok=True)
        with open(REMOTO_CFG, "w", encoding="utf-8") as f:
            json.dump({"token": tok}, f, indent=1)
    except Exception:
        pass
    return tok


def obter_node_id():
    """Gera ou lê ID único deste nó (ex.: FRIDAY-LINUX-a1b2 ou FRIDAY-WIN-c3d4)."""
    try:
        if os.path.exists(NODE_FILE):
            with open(NODE_FILE, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    prefix = "WIN" if sys.platform == "win32" or os.name == "nt" else "LINUX"
    nid = f"FRIDAY-{prefix}-{socket.gethostname()[:8]}-{secrets.token_hex(3)}"
    try:
        os.makedirs(MEM, exist_ok=True)
        with open(NODE_FILE, "w") as f:
            f.write(nid)
    except Exception:
        pass
    return nid


NODE_ID = obter_node_id()
CLUSTER_TOKEN = obter_token_cluster()
TOKEN_HASH = hashlib.sha256(CLUSTER_TOKEN.encode()).hexdigest()[:16]


# ----------------------------------------------------------------- Estado do Mesh (Pares e Carimbos)
def _ler_json(caminho, padrao):
    try:
        if os.path.exists(caminho):
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return padrao


def _gravar_json(caminho, dados):
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        tmp = caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=1, ensure_ascii=False)
        os.replace(tmp, caminho)
    except Exception:
        pass


def obter_peers_configurados():
    """Retorna lista de pares estáticos ou salvos em peers.json."""
    d = _ler_json(PEERS_FILE, {"peers": []})
    return d.get("peers", [])


def salvar_peer_configurado(host, port=DEFAULT_HTTP_PORT, alias=""):
    with _LOCK:
        d = _ler_json(PEERS_FILE, {"peers": []})
        peers = d.get("peers", [])
        for p in peers:
            if p.get("host") == host and p.get("port") == port:
                if alias: p["alias"] = alias
                _gravar_json(PEERS_FILE, d)
                return
        peers.append({"host": host, "port": port, "alias": alias, "adicionado_em": time.time()})
        d["peers"] = peers
        _gravar_json(PEERS_FILE, d)


# ----------------------------------------------------------------- Gerenciador Mesh
class MeshManager:
    def __init__(self):
        self.node_id = NODE_ID
        self.token = CLUSTER_TOKEN
        self.token_hash = TOKEN_HASH
        self.http_port = int(os.environ.get("FRIDAY_REMOTE_PORT", str(DEFAULT_HTTP_PORT)))
        self.active_peers = {}     # peer_id -> {"ip": ..., "port": ..., "last_seen": ..., "hostname": ..., "os": ...}
        self.sync_state = _ler_json(STATE_FILE, {"last_sync": {}})
        self.running = False
        self._threads = []
        self._udp_sock = None
        self._sync_lock = threading.Lock()
        self._trigger_event = threading.Event()

    def iniciar(self):
        """Inicia os serviços de beacon e sincronização em segundo plano."""
        if self.running:
            return
        self.running = True
        print(f"[MESH] Iniciando nó {self.node_id} na porta HTTP {self.http_port} (token hash: {self.token_hash})", flush=True)

        # Thread de escuta de beacons UDP
        t_recv = threading.Thread(target=self._ouvir_beacons, daemon=True, name="MeshUDPRecv")
        t_recv.start()
        self._threads.append(t_recv)

        # Thread de envio periódico de beacons UDP
        t_send = threading.Thread(target=self._enviar_beacons, daemon=True, name="MeshUDPSend")
        t_send.start()
        self._threads.append(t_send)

        # Thread do laço principal de sincronização
        t_sync = threading.Thread(target=self._loop_sincronizacao, daemon=True, name="MeshSyncLoop")
        t_sync.start()
        self._threads.append(t_sync)

    def parar(self):
        self.running = False
        self._trigger_event.set()
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass

    def notificar_mudanca(self, dataset="todos"):
        """Dispara sincronização imediata com os pares conhecidos."""
        self._trigger_event.set()

    # ------------------------------------------------------------- Beacons UDP (Descoberta LAN)
    def _enviar_beacons(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(2.0)
        while self.running:
            try:
                payload = json.dumps({
                    "mesh": "prometheus-friday",
                    "node_id": self.node_id,
                    "hostname": socket.gethostname(),
                    "os": sys.platform,
                    "http_port": self.http_port,
                    "token_hash": self.token_hash,
                    "ts": time.time()
                }).encode("utf-8")
                # Broadcast local geral
                sock.sendto(payload, ("255.255.255.255", UDP_BEACON_PORT))
                # Também tenta subnet local comum
                try:
                    sock.sendto(payload, ("192.168.1.255", UDP_BEACON_PORT))
                except Exception:
                    pass
            except Exception as e:
                pass
            time.sleep(BEACON_INTERVAL)

    def _ouvir_beacons(self):
        try:
            self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # No Windows, SO_REUSEPORT não existe
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except Exception:
                    pass
            self._udp_sock.bind(("0.0.0.0", UDP_BEACON_PORT))
            self._udp_sock.settimeout(3.0)
        except Exception as e:
            print(f"[MESH] Aviso: Não foi possível abrir porta UDP {UDP_BEACON_PORT} ({e}). Usando pares estáticos.", flush=True)
            return

        while self.running:
            try:
                data, addr = self._udp_sock.recvfrom(2048)
                msg = json.loads(data.decode("utf-8"))
                if msg.get("mesh") != "prometheus-friday":
                    continue
                sender_id = msg.get("node_id")
                if sender_id == self.node_id:
                    continue  # ignora o próprio beacon
                if msg.get("token_hash") != self.token_hash:
                    continue  # nós de clusters diferentes não misturam dados

                ip = addr[0]
                port = int(msg.get("http_port", DEFAULT_HTTP_PORT))
                recem_descoberto = sender_id not in self.active_peers
                with _LOCK:
                    self.active_peers[sender_id] = {
                        "ip": ip,
                        "port": port,
                        "hostname": msg.get("hostname", ""),
                        "os": msg.get("os", ""),
                        "last_seen": time.time()
                    }
                if recem_descoberto:
                    print(f"[MESH] Novo nó descoberto na rede: {sender_id} @ {ip}:{port}", flush=True)
                    self._trigger_event.set()
            except socket.timeout:
                continue
            except Exception:
                time.sleep(1.0)

    # ------------------------------------------------------------- Laço de Sincronização
    def _loop_sincronizacao(self):
        # Sincroniza imediatamente ao subir
        time.sleep(1.5)
        self.sincronizar_todos()

        while self.running:
            self._trigger_event.wait(timeout=SYNC_INTERVAL)
            self._trigger_event.clear()
            if not self.running:
                break
            self.sincronizar_todos()

    def obter_todos_destinos(self):
        """Combina pares descobertos via UDP com os pares estáticos do peers.json."""
        destinos = {}
        now = time.time()
        with _LOCK:
            # Pares ativos do UDP (vistos nos últimos 90 s)
            for nid, p in list(self.active_peers.items()):
                if now - p["last_seen"] < 90:
                    destinos[nid] = (p["ip"], p["port"])
                else:
                    self.active_peers.pop(nid, None)

        # Pares estáticos de peers.json
        for p in obter_peers_configurados():
            h = p.get("host")
            prt = p.get("port", DEFAULT_HTTP_PORT)
            if h and (h, prt) not in destinos.values():
                destinos[f"static-{h}-{prt}"] = (h, prt)
        return destinos

    def sincronizar_todos(self):
        """Executa sincronização bidirecional com todos os pares conhecidos."""
        with self._sync_lock:
            destinos = self.obter_todos_destinos()
            if not destinos:
                return
            for pid, (ip, port) in destinos.items():
                try:
                    self._sincronizar_com_peer(pid, ip, port)
                except Exception as e:
                    pass

    def _sincronizar_com_peer(self, peer_id, ip, port):
        """Conecta via HTTP ao endpoint /api/mesh/sync do par e troca deltas."""
        last_sync = self.sync_state.get("last_sync", {}).get(peer_id, {})
        since_timestamps = {
            "agenda": last_sync.get("agenda", 0.0),
            "conversas": last_sync.get("conversas", 0.0),
            "fatos": last_sync.get("fatos", 0.0),
            "licoes": last_sync.get("licoes", 0.0),
            "people": last_sync.get("people", 0.0),
            "tarefas": last_sync.get("tarefas", 0.0)
        }

        # Extrai deltas locais que mudaram desde que sincronizamos com este par
        deltas_locais = self.extrair_deltas(since_timestamps)

        url = f"http://{ip}:{port}/api/mesh/sync"
        payload = {
            "node_id": self.node_id,
            "since": since_timestamps,
            "deltas": deltas_locais,
            "now": time.time()
        }
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Token": self.token
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    resposta = json.loads(resp.read().decode("utf-8"))
                    if resposta.get("ok"):
                        remote_node = resposta.get("node_id", peer_id)
                        deltas_remotos = resposta.get("deltas", {})
                        # Aplica deltas vindos do par
                        self.aplicar_deltas(deltas_remotos)
                        # Atualiza carimbo de sincronização com este nó
                        agora = resposta.get("now", time.time())
                        if "last_sync" not in self.sync_state:
                            self.sync_state["last_sync"] = {}
                        self.sync_state["last_sync"][remote_node] = {
                            "agenda": agora,
                            "conversas": agora,
                            "fatos": agora,
                            "licoes": agora,
                            "people": agora,
                            "tarefas": agora
                        }
                        _gravar_json(STATE_FILE, self.sync_state)
        except Exception as e:
            # Par indisponível / offline no momento
            pass

    # ------------------------------------------------------------- Extração de Deltas Locais
    def extrair_deltas(self, since):
        deltas = {}
        # 1. Agenda
        since_ag = since.get("agenda", 0.0)
        try:
            ag_data = _ler_json(os.path.join(MEM, "agenda.json"), {"itens": []})
            itens_novos = [i for i in ag_data.get("itens", [])
                           if max(float(i.get("mod", 0)), float(i.get("criado", 0))) > since_ag]
            deltas["agenda"] = itens_novos
        except Exception:
            deltas["agenda"] = []

        # 2. Conversas
        since_cv = since.get("conversas", 0.0)
        cv_novas = []
        try:
            cv_path = os.path.join(MEM, "conversas.jsonl")
            if os.path.exists(cv_path):
                with open(cv_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line: continue
                        try:
                            item = json.loads(line)
                            if float(item.get("t", 0)) > since_cv:
                                cv_novas.append(item)
                        except Exception:
                            pass
        except Exception:
            pass
        deltas["conversas"] = cv_novas[-200:]  # Limita tamanho por pacote se esteve muito tempo offline

        # 3. Fatos (memoria.sqlite)
        since_ft = since.get("fatos", 0.0)
        ft_novos = []
        try:
            db_path = os.path.join(MEM, "memoria.sqlite")
            if os.path.exists(db_path):
                con = sqlite3.connect(db_path, timeout=5)
                cur = con.cursor()
                for row in cur.execute("SELECT tipo, chave, resumo, visto_1, visto_ult, vezes FROM fatos WHERE visto_ult > ?", (since_ft,)):
                    ft_novos.append({
                        "tipo": row[0],
                        "chave": row[1],
                        "resumo": row[2],
                        "visto_1": row[3],
                        "visto_ult": row[4],
                        "vezes": row[5]
                    })
                con.close()
        except Exception:
            pass
        deltas["fatos"] = ft_novos

        # 4. Lições
        since_lc = since.get("licoes", 0.0)
        try:
            lc_data = _ler_json(os.path.join(MEM, "licoes.json"), [])
            deltas["licoes"] = [l for l in lc_data if float(l.get("t", 0)) > since_lc]
        except Exception:
            deltas["licoes"] = []

        # 5. Pessoas
        try:
            pe_data = _ler_json(os.path.join(MEM, "people.json"), {"pessoas": {}})
            deltas["people"] = pe_data.get("pessoas", {})
        except Exception:
            deltas["people"] = {}

        # 6. Tarefas
        since_tf = since.get("tarefas", 0.0)
        try:
            tf_data = _ler_json(os.path.join(MEM, "tarefas.json"), {"itens": []})
            deltas["tarefas"] = [t for t in tf_data.get("itens", [])
                                 if max(float(t.get("criada", 0)), float(t.get("ultima", 0)), float(t.get("mod", 0))) > since_tf]
        except Exception:
            deltas["tarefas"] = []

        return deltas

    # ------------------------------------------------------------- Aplicação de Deltas Remotos
    def aplicar_deltas(self, deltas):
        if not deltas:
            return

        # 1. Agenda: Last-Write-Wins (LWW) por ID, preservando tombstones (removido: true)
        novos_ag = deltas.get("agenda", [])
        if novos_ag:
            try:
                ag_file = os.path.join(MEM, "agenda.json")
                ag_data = _ler_json(ag_file, {"itens": []})
                locais = {i.get("id"): i for i in ag_data.get("itens", []) if i.get("id")}
                alterou = False
                for r in novos_ag:
                    rid = r.get("id")
                    if not rid: continue
                    r_mod = max(float(r.get("mod", 0)), float(r.get("criado", 0)))
                    if rid not in locais:
                        locais[rid] = r
                        alterou = True
                    else:
                        l = locais[rid]
                        l_mod = max(float(l.get("mod", 0)), float(l.get("criado", 0)))
                        if r_mod > l_mod:
                            locais[rid] = r
                            alterou = True
                if alterou:
                    ag_data["itens"] = list(locais.values())
                    _gravar_json(ag_file, ag_data)
                    print(f"[MESH] Agenda sincronizada: {len(novos_ag)} itens mesclados", flush=True)
            except Exception as e:
                print(f"[MESH] Erro ao mesclar agenda: {e}", flush=True)

        # 2. Conversas: União append-only com hash de deduplicação
        novas_cv = deltas.get("conversas", [])
        if novas_cv:
            try:
                cv_file = os.path.join(MEM, "conversas.jsonl")
                existentes = set()
                if os.path.exists(cv_file):
                    with open(cv_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            try:
                                d = json.loads(line.strip())
                                t_val = int(round(float(d.get("t", 0))))
                                h = f"{t_val}_{d.get('role')}_{d.get('text', '')[:60]}"
                                existentes.add(h)
                            except Exception:
                                pass
                a_gravar = []
                for c in novas_cv:
                    t_val = int(round(float(c.get("t", 0))))
                    h = f"{t_val}_{c.get('role')}_{c.get('text', '')[:60]}"
                    if h not in existentes:
                        existentes.add(h)
                        a_gravar.append(c)
                if a_gravar:
                    with open(cv_file, "a", encoding="utf-8") as f:
                        for item in a_gravar:
                            f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    print(f"[MESH] Conversas sincronizadas: {len(a_gravar)} novas falas registradas", flush=True)
            except Exception as e:
                print(f"[MESH] Erro ao mesclar conversas: {e}", flush=True)

        # 3. Fatos (memoria.sqlite)
        novos_ft = deltas.get("fatos", [])
        if novos_ft:
            try:
                db_path = os.path.join(MEM, "memoria.sqlite")
                if os.path.exists(db_path):
                    con = sqlite3.connect(db_path, timeout=5)
                    cur = con.cursor()
                    for f in novos_ft:
                        tp, ch, res = f.get("tipo"), f.get("chave"), f.get("resumo")
                        v1, vu, vz = f.get("visto_1", 0), f.get("visto_ult", 0), f.get("vezes", 1)
                        if not tp or not ch: continue

                        # Confere se o local é mais antigo
                        r = cur.execute("SELECT visto_ult FROM fatos WHERE tipo=? AND chave=?", (tp, ch)).fetchone()
                        if not r or float(vu) > float(r[0] or 0):
                            cur.execute("""
                                INSERT INTO fatos(tipo, chave, resumo, visto_1, visto_ult, vezes)
                                VALUES(?, ?, ?, ?, ?, ?)
                                ON CONFLICT(tipo, chave) DO UPDATE SET
                                    resumo=excluded.resumo,
                                    visto_ult=excluded.visto_ult,
                                    vezes=max(fatos.vezes, excluded.vezes)
                            """, (tp, ch, res, v1, vu, vz))
                            try:
                                cur.execute("INSERT INTO busca(tipo, chave, resumo) VALUES(?, ?, ?)", (tp, ch, res))
                            except Exception:
                                pass
                    con.commit()
                    con.close()
                    print(f"[MESH] Memória Fatos sincronizada: {len(novos_ft)} fatos integrados", flush=True)
            except Exception as e:
                print(f"[MESH] Erro ao mesclar fatos sqlite: {e}", flush=True)

        # 4. Lições: Deduplicação por similaridade
        novas_lc = deltas.get("licoes", [])
        if novas_lc:
            try:
                lc_file = os.path.join(MEM, "licoes.json")
                lc_atuais = _ler_json(lc_file, [])
                alterou = False
                for n in novas_lc:
                    txt = n.get("txt", "").strip()
                    if not txt: continue
                    # Verifica se já temos lição muito similar
                    igual = False
                    for x in lc_atuais:
                        if difflib.SequenceMatcher(None, txt.lower(), x.get("txt", "").lower()).ratio() > 0.75:
                            igual = True
                            if float(n.get("t", 0)) > float(x.get("t", 0)):
                                x["t"] = n["t"]
                                alterou = True
                            break
                    if not igual:
                        lc_atuais.append(n)
                        alterou = True
                if alterou:
                    _gravar_json(lc_file, lc_atuais[-50:])
                    print(f"[MESH] Lições sincronizadas: total agora {len(lc_atuais)}", flush=True)
            except Exception as e:
                print(f"[MESH] Erro ao mesclar lições: {e}", flush=True)

        # 5. Pessoas e Rostos
        novas_pe = deltas.get("people", {})
        if novas_pe:
            try:
                pe_file = os.path.join(MEM, "people.json")
                pe_data = _ler_json(pe_file, {"pessoas": {}})
                locais = pe_data.get("pessoas", {})
                alterou = False
                for k, v in novas_pe.items():
                    if k not in locais:
                        locais[k] = v
                        alterou = True
                    else:
                        # Mescla atributos
                        loc_p = locais[k]
                        for f_k, f_v in v.items():
                            if f_k not in loc_p or not loc_p[f_k]:
                                loc_p[f_k] = f_v
                                alterou = True
                if alterou:
                    pe_data["pessoas"] = locais
                    _gravar_json(pe_file, pe_data)
                    print(f"[MESH] Pessoas sincronizadas: {len(novas_pe)} perfis analisados", flush=True)
            except Exception as e:
                print(f"[MESH] Erro ao mesclar people.json: {e}", flush=True)

        # 6. Tarefas
        novas_tf = deltas.get("tarefas", [])
        if novas_tf:
            try:
                tf_file = os.path.join(MEM, "tarefas.json")
                tf_data = _ler_json(tf_file, {"itens": []})
                locais = {t.get("id"): t for t in tf_data.get("itens", []) if t.get("id")}
                alterou = False
                for r in novas_tf:
                    rid = r.get("id")
                    if not rid: continue
                    r_mod = max(float(r.get("criada", 0)), float(r.get("ultima", 0)), float(r.get("mod", 0)))
                    if rid not in locais:
                        locais[rid] = r
                        alterou = True
                    else:
                        l = locais[rid]
                        l_mod = max(float(l.get("criada", 0)), float(l.get("ultima", 0)), float(l.get("mod", 0)))
                        if r_mod > l_mod:
                            locais[rid] = r
                            alterou = True
                if alterou:
                    tf_data["itens"] = list(locais.values())
                    _gravar_json(tf_file, tf_data)
                    print(f"[MESH] Tarefas sincronizadas: {len(novas_tf)} tarefas mescladas", flush=True)
            except Exception as e:
                print(f"[MESH] Erro ao mesclar tarefas: {e}", flush=True)


# Instância global do MeshManager
_MESH = MeshManager()


def obter_mesh():
    return _MESH


def iniciar_mesh():
    _MESH.iniciar()


def notificar_mudanca(dataset="todos"):
    _MESH.notificar_mudanca(dataset)


# ----------------------------------------------------------------- Handlers HTTP (Integrados no remoto.py)
async def handle_mesh_info(req):
    """GET /api/mesh/info -> Metadados do nó e estado atual."""
    from aiohttp import web
    m = _MESH
    return web.json_response({
        "ok": True,
        "node_id": m.node_id,
        "hostname": socket.gethostname(),
        "os": sys.platform,
        "http_port": m.http_port,
        "token_hash": m.token_hash,
        "active_peers": list(m.active_peers.keys()),
        "time": time.time()
    })


async def handle_mesh_peers(req):
    """GET /api/mesh/peers -> Lista detalhada de pares conhecidos."""
    from aiohttp import web
    m = _MESH
    destinos = m.obter_todos_destinos()
    peers_list = []
    for pid, (ip, prt) in destinos.items():
        info = m.active_peers.get(pid, {})
        peers_list.append({
            "node_id": pid,
            "ip": ip,
            "port": prt,
            "hostname": info.get("hostname", ""),
            "os": info.get("os", ""),
            "last_seen": info.get("last_seen", 0)
        })
    return web.json_response({
        "ok": True,
        "node_id": m.node_id,
        "peers": peers_list
    })


async def handle_mesh_sync(req):
    """POST /api/mesh/sync -> Ponto central de troca de deltas bidirecionais."""
    from aiohttp import web
    m = _MESH
    try:
        dados = await req.json()
    except Exception:
        return web.json_response({"ok": False, "erro": "JSON inválido"}, status=400)

    sender_id = dados.get("node_id", "desconhecido")
    since_timestamps = dados.get("since", {})
    deltas_recebidos = dados.get("deltas", {})

    # 1. Aplica deltas enviados pelo par no nó local
    m.aplicar_deltas(deltas_recebidos)

    # 2. Extrai deltas locais que o par ainda não tem
    deltas_locais = m.extrair_deltas(since_timestamps)

    return web.json_response({
        "ok": True,
        "node_id": m.node_id,
        "deltas": deltas_locais,
        "now": time.time()
    })
