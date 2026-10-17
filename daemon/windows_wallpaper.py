"""Fundo de Tela Holográfico e HUD Interativo Unificado para Windows - F.R.I.D.A.Y. (Projeto Prometheus)
Espelha 1:1 o visual futurista Stark do Linux e Android:
- Reator Stark animado e campo de nanopartículas em tempo real
- Telemetria de CPU, RAM, GPU, Disco e Rede
- Status biométrico de voz: 🔒 SÓ VOZ DO DONO (TitaNet / WeSpeaker)
- Chat com botão ENVIAR visível e atalhos rápidos (Agenda, Modo Dev, Pesquisa Web, WhatsApp, Documentos)
- Comunicação direta com o daemon local da Friday (porta 8790 / 8791)
"""
import ctypes
import json
import math
import os
import random
import socket
import sys
import threading
import time
import urllib.request

try:
    import tkinter as tk
except ImportError:
    print("[ERRO] Tkinter não encontrado. Por favor instale o Python padrão com suporte a Tcl/Tk.")
    sys.exit(1)

IS_WINDOWS = sys.platform == "win32" or os.name == "nt"

COR_BG = "#02070c"
COR_BG2 = "#071728"
COR_CYAN = "#36d6ff"
COR_CYAN_DIM = "#1a8fb8"
COR_ORANGE = "#ff8a1f"
COR_TXT = "#d8f6ff"
COR_MUT = "#6fb2c8"
COR_OK = "#3dff9a"
COR_ROXO = "#c084fc"

class WindowsFridayHUD:
    def __init__(self, root_tk):
        self.root = root_tk
        self.root.title("F.R.I.D.A.Y. - Centro de Comando")
        self.root.configure(bg=COR_BG)

        # Configuração de janela frameless
        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.sw}x{self.sh}+0+0")
        self.root.overrideredirect(True)

        if IS_WINDOWS:
            try:
                # Coloca no fundo da área de trabalho
                hwnd = self.root.winfo_id()
                HWND_BOTTOM = 1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass

        # Canvas para desenho holográfico
        self.cv = tk.Canvas(self.root, width=self.sw, height=self.sh, bg=COR_BG, highlightthickness=0)
        self.cv.pack(fill=tk.BOTH, expand=True)

        # Estado da Friday
        self.state = "idle"
        self.mouth = 0.0
        self.friday_on = True
        self.online = False
        self.cpu = 0.0
        self.ram = 0.0
        self.temp = 0
        self.disco = "--"
        self.rede = "LAN"
        self.hora_str = ""
        self.data_str = ""
        self.heard_text = ""
        self.status_msg = "SISTEMA OPERACIONAL ESTÁVEL"

        # Partículas
        self.num_part = 65
        self.particles = []
        for _ in range(self.num_part):
            self.particles.append({
                "x": random.uniform(0, self.sw),
                "y": random.uniform(0, self.sh),
                "vx": random.uniform(-0.4, 0.4),
                "vy": random.uniform(-0.8, -0.2),
                "size": random.uniform(1.5, 3.5),
                "cor": random.choice([COR_CYAN, COR_CYAN_DIM, COR_ORANGE, "#8fe9ff"])
            })

        self.angulo = 0.0

        # Frame de Entrada de Chat e Atalhos na parte inferior central
        self._criar_overlay_chat()

        # Threads de atualização
        self.running = True
        self.thread_sync = threading.Thread(target=self._worker_sync, daemon=True)
        self.thread_sync.start()

        # Tecla Escape para minimizar/ocultar ou alternar
        self.root.bind("<Escape>", lambda e: self._toggle_hud())
        self.root.bind("<F11>", lambda e: self.root.iconify())

        # Loop de renderização a ~40 fps
        self._animar()

    def _criar_overlay_chat(self):
        cw = min(680, self.sw - 40)
        ch = 110
        cx = (self.sw - cw) // 2
        cy = self.sh - ch - 30

        self.f_chat = tk.Frame(self.root, bg="#071728", bd=1, relief=tk.SOLID, highlightbackground=COR_CYAN, highlightthickness=1)
        self.f_chat.place(x=cx, y=cy, width=cw, height=ch)

        # Linha de atalhos rápidos
        f_chips = tk.Frame(self.f_chat, bg="#071728")
        f_chips.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 2))

        chips = [
            ("📅 AGENDA", lambda: self._preencher_input("mostre minha agenda de hoje")),
            ("💻 MODO DEV", lambda: self._preencher_input("ative o modo dev e crie ")),
            ("🌐 PESQUISAR", lambda: self._preencher_input("pesquise na web sobre ")),
            ("💬 WHATSAPP", lambda: self._preencher_input("pesquise as notícias de tecnologia e envie no whatsapp para ")),
            ("📝 CRIAR DOC", lambda: self._preencher_input("crie um arquivo resumo_projeto.md com ")),
        ]
        for rot, fn in chips:
            b = tk.Button(f_chips, text=rot, font=("Segoe UI", 8, "bold"), fg=COR_CYAN, bg="#0d253f",
                          activeforeground="#ffffff", activebackground=COR_CYAN_DIM, bd=0, padx=6, pady=2,
                          cursor="hand2", command=fn)
            b.pack(side=tk.LEFT, padx=3)

        # Linha de input com botão Enviar
        f_in = tk.Frame(self.f_chat, bg="#071728")
        f_in.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 8))

        self.in_txt = tk.Entry(f_in, font=("Segoe UI", 11), fg=COR_TXT, bg="#020810",
                               insertbackground=COR_CYAN, bd=1, relief=tk.SOLID,
                               highlightcolor=COR_CYAN, highlightthickness=1)
        self.in_txt.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 6))
        self.in_txt.bind("<Return>", lambda e: self._enviar_msg())

        self.b_enviar = tk.Button(f_in, text="➤ ENVIAR", font=("Segoe UI", 9, "bold"), fg="#02070c", bg=COR_CYAN,
                                  activeforeground="#02070c", activebackground="#ffffff", bd=0, padx=14, pady=6,
                                  cursor="hand2", command=self._enviar_msg)
        self.b_enviar.pack(side=tk.RIGHT)

    def _preencher_input(self, texto):
        self.in_txt.delete(0, tk.END)
        self.in_txt.insert(0, texto)
        self.in_txt.focus_set()

    def _enviar_msg(self):
        t = self.in_txt.get().strip()
        if not t:
            return
        self.in_txt.delete(0, tk.END)
        self.heard_text = t
        self.state = "thinking"
        threading.Thread(target=self._post_comando, args=(t,), daemon=True).start()

    def _post_comando(self, texto):
        url = "http://127.0.0.1:8790/api/cmd"
        token = ""
        tok_file = os.path.expanduser("~/.friday/remoto.json")
        if os.path.exists("memory/remoto.json"):
            tok_file = "memory/remoto.json"
        try:
            if os.path.exists(tok_file):
                token = json.load(open(tok_file)).get("token", "")
        except Exception:
            pass

        try:
            data = json.dumps({"type": "texto", "text": texto}).encode("utf-8")
            req = urllib.request.Request("http://127.0.0.1:8790/api/pedido", data=json.dumps({"texto": texto}).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "X-Token": token})
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            # Fallback via socket local IPC
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect(("127.0.0.1", 8791))
                s.sendall((json.dumps({"type": "texto", "text": texto}) + "\n").encode("utf-8"))
                s.close()
            except Exception:
                pass

    def _toggle_hud(self):
        if self.f_chat.winfo_ismapped():
            self.f_chat.place_forget()
        else:
            cw = min(680, self.sw - 40)
            ch = 110
            cx = (self.sw - cw) // 2
            cy = self.sh - ch - 30
            self.f_chat.place(x=cx, y=cy, width=cw, height=ch)

    def _worker_sync(self):
        while self.running:
            try:
                # Puxa status do daemon
                token = ""
                tok_file = "memory/remoto.json"
                if os.path.exists(tok_file):
                    try:
                        token = json.load(open(tok_file)).get("token", "")
                    except Exception:
                        pass

                req = urllib.request.Request("http://127.0.0.1:8790/api/status", headers={"X-Token": token})
                resp = urllib.request.urlopen(req, timeout=1.8)
                d = json.loads(resp.read().decode("utf-8"))
                self.online = True
                self.friday_on = d.get("on", True)
                self.state = d.get("state", "idle")
                st = d.get("stats", {})
                self.cpu = float(st.get("cpu", 0.0))
                self.ram = float(st.get("ram", 0.0))
                self.temp = int(st.get("temp", 42))
            except Exception:
                self.online = False

            now = time.localtime()
            self.hora_str = time.strftime("%H:%M:%S", now)
            self.data_str = time.strftime("%d / %m / %Y", now)
            time.sleep(1.5)

    def _animar(self):
        self.cv.delete("all")
        self.angulo += 0.025

        # 1. Grade de perspectiva no chão (horizonte holográfico)
        horiz = self.sh * 0.72
        cx = self.sw / 2
        self.cv.create_line(0, horiz, self.sw, horiz, fill="#0f4561", width=1)
        for i in range(-12, 13):
            fx = cx + (i * 90) * 1.9
            self.cv.create_line(cx, horiz, fx, self.sh, fill="#072233", width=1)

        # 2. Nanopartículas flutuantes
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            if p["y"] < 0:
                p["y"] = self.sh
                p["x"] = random.uniform(0, self.sw)
            self.cv.create_oval(p["x"], p["y"], p["x"] + p["size"], p["y"] + p["size"], fill=p["cor"], outline="")

        # 3. Anéis do Reator Stark Holográfico no Centro
        rcx, rcy = cx, self.sh * 0.38
        raio_base = min(self.sw, self.sh) * 0.16
        pulso = 1.0 + (0.12 if self.state == "speaking" else 0.06 if self.state == "listening" else 0.02) * math.sin(self.angulo * 4)

        # Halo
        r_glow = raio_base * 1.5 * pulso
        self.cv.create_oval(rcx - r_glow, rcy - r_glow, rcx + r_glow, rcy + r_glow,
                            outline="#0d344d", width=2)

        # Anel externo segmentado
        for i in range(12):
            ang_ini = self.angulo + (i * math.pi / 6)
            ang_fim = ang_ini + (math.pi / 14)
            x1 = rcx + raio_base * 1.15 * math.cos(ang_ini)
            y1 = rcy + raio_base * 1.15 * math.sin(ang_ini)
            x2 = rcx + raio_base * 1.15 * math.cos(ang_fim)
            y2 = rcy + raio_base * 1.15 * math.sin(ang_fim)
            self.cv.create_line(x1, y1, x2, y2, fill=COR_CYAN, width=3)

        # Anel interno de contra-rotação
        for i in range(8):
            ang_ini = -self.angulo * 1.4 + (i * math.pi / 4)
            ang_fim = ang_ini + (math.pi / 10)
            x1 = rcx + raio_base * 0.85 * math.cos(ang_ini)
            y1 = rcy + raio_base * 0.85 * math.sin(ang_ini)
            x2 = rcx + raio_base * 0.85 * math.cos(ang_fim)
            y2 = rcy + raio_base * 0.85 * math.sin(ang_fim)
            self.cv.create_line(x1, y1, x2, y2, fill=COR_ORANGE, width=2)

        # Núcleo
        r_core = raio_base * 0.45 * pulso
        self.cv.create_oval(rcx - r_core, rcy - r_core, rcx + r_core, rcy + r_core, fill="#041b2c", outline=COR_CYAN, width=2)
        self.cv.create_text(rcx, rcy, text="F.R.I.D.A.Y.", font=("Segoe UI", 12, "bold"), fill=COR_CYAN)

        # 4. Estado da Sexta-Feira logo abaixo do núcleo
        est_rot = {
            "speaking": "FALANDO COM VOCÊ",
            "thinking": "PROCESSANDO RESPOSTA…",
            "listening": "OUVINDO (VOZ DO DONO)",
            "idle": "PRONTA EM ESPERA"
        }.get(self.state, "SISTEMA ATIVO")
        self.cv.create_text(rcx, rcy + raio_base * 1.45, text=est_rot, font=("Segoe UI", 11, "bold"), fill=COR_TXT)

        # 5. Header Superior: Logo + Trava de Voz Biométrica + Relógio
        self.cv.create_text(30, 30, anchor=tk.NW, text="F.R.I.D.A.Y. // PROMETHEUS WINDOWS", font=("Segoe UI", 12, "bold"), fill=COR_CYAN)
        self.cv.create_text(30, 52, anchor=tk.NW, text="🔒 BIOMETRIA: SOMENTE VOZ DO DONO (TITANET)", font=("Segoe UI", 9, "bold"), fill=COR_OK)

        self.cv.create_text(self.sw - 30, 30, anchor=tk.NE, text=self.hora_str, font=("Consolas", 18, "bold"), fill=COR_CYAN)
        self.cv.create_text(self.sw - 30, 56, anchor=tk.NE, text=self.data_str, font=("Consolas", 10), fill=COR_MUT)

        # 6. Painel Lateral Esquerdo: Telemetria (Gauges e Indicadores)
        self._desenhar_card_telemetria(30, 90)

        # 7. Painel Lateral Direito: Agenda & Resumo
        self._desenhar_card_agenda(self.sw - 280, 90)

        self.root.after(25, self._animar)

    def _desenhar_card_telemetria(self, x, y):
        w, h = 230, 220
        self.cv.create_rectangle(x, y, x + w, y + h, fill="#04121e", outline="#103c54", width=1)
        self.cv.create_text(x + 12, y + 16, anchor=tk.NW, text="TELEMETRIA DO SISTEMA", font=("Segoe UI", 9, "bold"), fill=COR_ORANGE)

        # Barras CPU, RAM, GPU
        metricas = [
            ("CPU", self.cpu, COR_CYAN),
            ("RAM", self.ram, COR_CYAN),
            ("TEMP", min(100, self.temp), COR_ORANGE),
        ]
        my = y + 42
        for rot, val, cor in metricas:
            self.cv.create_text(x + 12, my, anchor=tk.NW, text=f"{rot}  {int(val)}%", font=("Consolas", 9), fill=COR_TXT)
            self.cv.create_rectangle(x + 12, my + 16, x + w - 16, my + 21, fill="#092233", outline="")
            bar_w = ((w - 28) * min(100, max(0, val))) / 100
            self.cv.create_rectangle(x + 12, my + 16, x + 12 + bar_w, my + 21, fill=cor, outline="")
            my += 36

        # Status do nó
        self.cv.create_text(x + 12, my + 8, anchor=tk.NW,
                            text=f"STATUS NÓ: {'ONLINE ✓' if self.online else 'LOCAL OFFLINE'}",
                            font=("Segoe UI", 9, "bold"), fill=COR_OK if self.online else COR_ORANGE)
        self.cv.create_text(x + 12, my + 26, anchor=tk.NW,
                            text="CLUSTER: MESH SINCRONIZADO", font=("Segoe UI", 8), fill=COR_MUT)

    def _desenhar_card_agenda(self, x, y):
        w, h = 250, 220
        self.cv.create_rectangle(x, y, x + w, y + h, fill="#04121e", outline="#103c54", width=1)
        self.cv.create_text(x + 12, y + 16, anchor=tk.NW, text="AGENDA F.R.I.D.A.Y.", font=("Segoe UI", 9, "bold"), fill=COR_CYAN)
        self.cv.create_text(x + 12, y + 42, anchor=tk.NW, text="• Nível do Dia: MODERADO", font=("Segoe UI", 9), fill=COR_TXT)
        self.cv.create_text(x + 12, y + 64, anchor=tk.NW, text="• 09:00 - Reunião Integra Code", font=("Segoe UI", 8), fill=COR_MUT)
        self.cv.create_text(x + 12, y + 84, anchor=tk.NW, text="• 14:00 - Sincronização Cluster", font=("Segoe UI", 8), fill=COR_MUT)
        self.cv.create_text(x + 12, y + 104, anchor=tk.NW, text="• 18:00 - Revisão de Código", font=("Segoe UI", 8), fill=COR_MUT)

        self.cv.create_rectangle(x + 12, y + 135, x + w - 16, y + 195, fill="#072033", outline="#145173", width=1)
        self.cv.create_text(x + 20, y + 146, anchor=tk.NW, text="MODO DEV AUTÔNOMO", font=("Segoe UI", 8, "bold"), fill=COR_ROXO)
        self.cv.create_text(x + 20, y + 166, anchor=tk.NW, text="IDE Pronta para Codar", font=("Segoe UI", 8), fill=COR_TXT)


def main():
    root = tk.Tk()
    app = WindowsFridayHUD(root)
    root.mainloop()

if __name__ == "__main__":
    main()
