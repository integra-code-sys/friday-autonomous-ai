<div align="center">

# 🤖 F.R.I.D.A.Y. Commercial Edition (Prometheus OS v2.0)
### **Agente de Inteligência Artificial Multimodal Autônomo (Linux • Windows `.EXE` • Android `.APK`)**
**Oficialmente Desenvolvido e Mantido por [Integra Code](https://github.com/integracode)**

[![Desenvolvido por Integra Code](https://img.shields.io/badge/Organization-Integra%20Code-00e5ff?style=for-the-badge)](TERMS_OF_USE.md)
[![Privacidade Zero-Data-Retention](https://img.shields.io/badge/Privacy-Zero%20Data%20Retention-00e676?style=for-the-badge)](PRIVACY_POLICY.md)
[![Plataformas](https://img.shields.io/badge/OS-Linux%20%7C%20Windows%20.EXE%20%7C%20Android%20.APK-0077ff?style=for-the-badge)](#instalacao-rapida-e-automatizada)
[![Test Battery](https://img.shields.io/badge/Tests-18%2F18%20Passing%20(100%25)-2ee59d?style=for-the-badge)](tests/test_mega_battery.py)
[![License: MIT](https://img.shields.io/badge/License-MIT%20(Integra%20Code)-yellow?style=for-the-badge)](LICENSE)

<br/>

![F.R.I.D.A.Y. Commercial Showcase — PC + Android Sync](media/showcase_preview.gif)

**[⚡ Demonstração Animada](media/showcase_preview.gif)** •
**[🌐 Landing Page Comercial](docs/index.html)** •
**[📱 APK Android (v2.0)](android/dist/friday-remoto.apk)** •
**[💻 Instalador Windows (.EXE)](Instalador_Friday_Comercial_Windows.exe)**

</div>

---

## 🔒 Termo de Uso e Garantia de Soberania de Dados — **Integra Code**

> [!IMPORTANT]
> **GARANTIA ABSOLUTA DE NÃO-RETENÇÃO DE DADOS (`ZERO-DATA-RETENTION`):**  
> A **Integra Code NÃO coleta, NÃO armazena, NÃO intercepta e NÃO possui acesso** a nenhum dado pessoal, gravação de voz, imagem de câmera, captura de tela, banco de dados de memória ou chave de API do usuário.
>
> Todo o processamento da **F.R.I.D.A.Y.** ocorre **exclusivamente**:
> 1. **100% Localmente no Hardware do Usuário** (via `Ollama`, `faster-whisper`, `Piper TTS`, `OpenCV/ONNX` e bancos locais `SQLite`), **OU**
> 2. **Diretamente entre a Máquina do Usuário e o Provedor de Nuvem escolhido pelo próprio usuário** (**Google Gemini**, **Anthropic Claude** ou **OpenAI GPT**) usando a chave de API (`BYOK`) privada do próprio usuário.
>
> Essa garantia é auditada e imposta tecnicamente em tempo de execução pelo módulo [`daemon/privacy_guard.py`](daemon/privacy_guard.py). Consulte os [Termos de Uso Completos](TERMS_OF_USE.md) e a [Política de Privacidade](PRIVACY_POLICY.md).

---

## ✨ Principais Diferenciais da Edição Comercial

### 1. 📷 Adaptação Automática para Qualquer Cenário de Câmeras (`0`, `1`, `2` ou `3+` Câmeras PTZ)
Nem todo usuário possui múltiplas câmeras ou uma câmera motorizada PTZ. O módulo [`daemon/camera_manager.py`](daemon/camera_manager.py) detecta e adapta automaticamente as ferramentas do agente:
- **`0 Câmeras` (`sem_camera` — Desktop sem webcam):** Opera 100% com análise de tela (`grim`/`mss`) e voz; remove automaticamente ferramentas de câmera física para evitar alucinações.
- **`1 Câmera` (`1_camera` — Notebook ou PC com 1 Webcam):** Unifica detecção de presença, rosto, gestos e leitura de objetos na mão (`ROI Mãos + VLM`) na única webcam disponível.
- **`2 Câmeras` (`2_cameras`):** Separa webcam frontal (mesa/mãos) e câmera secundária USB/IP (porta/ambiente).
- **`3+ Câmeras + PTZ` (`3_cameras_ptz`):** Suporte completo a câmera motorizada ONVIF/RTSP com rastreamento autônomo e correção automática de espectro de cor e áudio.

### 2. ☁️ Visão e Cérebro Híbridos: Local (`Ollama`) ou Nuvem (`Gemini`, `Claude`, `OpenAI`)
Através do módulo [`daemon/cloud_providers.py`](daemon/cloud_providers.py) e da Central de Configuração (`/config`), você escolhe com 1 clique:
- **100% Local (Offline):** `Ollama` (`qwen3-vl:4b-instruct`, `gemma3`, `moondream`).
- **Google Gemini:** `gemini-2.5-flash` / `gemini-2.5-pro` (Visão + Tool-Calling nativo).
- **Anthropic Claude:** `claude-3-5-sonnet-latest` / `claude-3-7-sonnet` (Visão + Tool-Use nativo).
- **OpenAI GPT:** `gpt-4o` / `gpt-4o-mini` (Visão + Function-Calling nativo).
- **Modo Híbrido Automático (`auto`):** Usa o provedor de nuvem configurado e realiza *fallback* transparente e instantâneo para o `Ollama` local caso a internet caia ou o limite de requisição seja atingido.

### 3. 🧠 Memória *Zero-State* e Aprendizado Contínuo a partir do Zero
O módulo [`daemon/memoria_zero.py`](daemon/memoria_zero.py) garante que a instalação comercial inicie com bancos de dados **100% limpos** (sem nenhum dado pessoal prévio) e aprenda organicamente com você:
- **Onboarding Inteligente:** Aprende como você prefere ser chamado e suas preferências no primeiro uso.
- **Memória Factual (`memoria.sqlite` + FTS5):** Registra fatos duráveis sobre o usuário, projetos e aplicativos.
- **Memória Episódica (`episodios.sqlite`):** Aprende receitas de sequências de ferramentas que deram certo para reutilizá-las instantaneamente no futuro.
- **Autorreflexão e Deduplicação de Lições (`licoes.json`):** Quando uma ação falha, extrai uma regra corretiva para nunca repetir o mesmo erro.

### 4. 🔄 Sincronização Mesh P2P Autônoma (Linux ↔ Windows ↔ Android)
O módulo [`daemon/sync_mesh.py`](daemon/sync_mesh.py) mantém até 3 ou mais nós sincronizados em malha Peer-to-Peer (via LAN ou VPN privada como Tailscale):
- Se um ou dois dispositivos estiverem desligados, assim que ligarem eles descobrem os pares ativos via beacon UDP (`8792`) e trocam deltas HTTP (`8790`) de **agenda, fatos, conversas, tarefas e lições aprendidas** usando resolução de conflitos *Last-Write-Wins*.

### 5. 🛠️ Instalador Automático de Dependências (`auto_deps.py`) e Ativação no Boot
- **Auto-Diagnóstico e Auto-Instalação:** [`daemon/auto_deps.py`](daemon/auto_deps.py) verifica e instala automaticamente bibliotecas Python, utilitários de sistema (`ffmpeg`, `curl`, `grim`) e baixa modelos neurais ONNX (`yunet.onnx`, `sface_2021dec.onnx`).
- **Ativação no Boot em 1 Clique:** Ative ou desative o início automático com o sistema operacional no Linux (`~/.config/autostart/friday-commercial.desktop`) e no Windows (`Startup` / `.vbs` silencioso) direto pelo painel Web ou CLI.

### 6. 🔒 Biometria Vocal Estrita — Somente a Voz do Dono
- **No PC:** Verificação neural ativa com **NVIDIA TitaNet-L** (`voz.py`) rejeita vozes estranhas e ruídos de fundo antes de transcrever.
- **No Android:** Verificação neural embarcada via **WeSpeaker ResNet34 ONNX** (`Ouvido.java`), ativa tanto no aplicativo quanto no Assistente Padrão (botão liga/desliga).

### 7. 📅 Agenda Própria da Friday (Multi-Dispositivo)
- Agenda autônoma nativa sem dependência de calendários externos (como Google Calendar).
- Cálculo inteligente do nível do dia (`LIVRE`, `LEVE`, `MODERADO`, `INTENSO`, `CRÍTICO`), horas livres restantes, prioridades e sincronização mesh automática entre PC e celular.

### 8. 💻 Modo Dev — Engenheira de Software Autônoma
- IDE integrada para planejar, codificar, executar testes automatizados e corrigir erros em loops de até 8 rounds autônomos.
- Funciona no PC (Claude Code CLI / IDE local) e no celular Android (Termux ou geração GGUF local com janela flutuante HUD).

### 9. ⚡ Tarefas Compostas Determinísticas
- Encadeia pesquisas na internet e ações de envio ou criação em uma única frase (ex.: *"pesquise sobre inteligência artificial e envie no WhatsApp para Fulano"*, *"pesquise sobre computação quântica e crie um arquivo resumo.md"*).

### 10. 🎨 Fundo Holográfico e HUD Unificado (Linux & Windows)
- Visual futurista Stark com piso holográfico em perspectiva, reator pulsante ao falar e poeira de nanopartículas em tempo real.
- Totalmente unificado entre o compositor Wayland do Linux (`shell.qml` / `PainelStark.qml`) e o HUD do Windows (`windows_wallpaper.py`).

---

## 🚀 Instalação Rápida e Automatizada

### 🐧 Opção 1: Linux (Arch, Ubuntu, Debian, Fedora)
```bash
chmod +x install_linux.sh run.sh friday-config
./install_linux.sh
./run.sh
```

### 🪟 Opção 2: Windows 10 / 11 (Instalador `.EXE` Autônomo)
1. Execute diretamente o instalador autônomo **[`Instalador_Friday_Comercial_Windows.exe`](Instalador_Friday_Comercial_Windows.exe)** (extrai em `%LOCALAPPDATA%\FridayCommercial`, instala as dependências automaticamente e cria atalhos na Área de Trabalho e Inicialização), **OU**
2. Execute via scripts batch:
```bat
install_windows.bat
Friday.bat
```

### 📱 Opção 3: Android (`.APK` Nativo + Web App)
Instale o APK diretamente no seu smartphone Android ou via ADB:
```bash
adb install -r android/friday-commercial.apk
```

---

## ⚙️ Central de Configuração Fácil (Web GUI & CLI)

Com a F.R.I.D.A.Y. em execução, acesse no navegador:
👉 **`http://localhost:8790/config`**

Ou utilize a ferramenta de linha de comando `./friday-config`:
```bash
# Ver status completo (Câmeras, IA, Boot, Memória, Dependências e Privacidade)
./friday-config --status

# Verificar e instalar automaticamente todas as dependências e modelos ONNX
./friday-config --install-deps

# Ativar ou desativar inicialização automática no Boot do sistema
./friday-config --boot on
./friday-config --boot off

# Alterar provedor de Visão e Cérebro para Google Gemini, Claude, OpenAI ou Ollama Local
./friday-config --vision gemini --gemini-key "SUA_CHAVE_AQUI"
./friday-config --brain claude --claude-key "SUA_CHAVE_AQUI"
./friday-config --vision ollama --brain ollama

# Definir cenário de câmeras manualmente (auto | sem_camera | 1_camera | 2_cameras | 3_cameras_ptz)
./friday-config --cameras 1_camera

# Executar limpeza geral de fábrica (Factory Reset Zero-State)
./friday-config --reset-memory --nome "Chefe"

# Exibir Termos de Uso e Auditoria de Privacidade da Integra Code
./friday-config --terms
```

---

## 🧪 Bateria Massiva de Testes Automatizados

A edição comercial conta com **18 suítes completas de testes** ([`tests/test_mega_battery.py`](tests/test_mega_battery.py) e [`tests/test_scenarios_commercial.py`](tests/test_scenarios_commercial.py)) que validam compilação AST de todos os módulos, ausência total de dados pessoais, bloqueio de telemetria (`privacy_guard`), auto-instalador de dependências (`auto_deps`), cenários de 0/1/2/3+ câmeras, provedores Cloud/Local com fallback, aprendizado contínuo do zero e sincronização Mesh P2P:

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -p "test_*.py" -v
```

---

## 📄 Licença e Direitos Autorais

Distribuído sob a **Licença MIT** em nome da **Integra Code**.  
Consulte [`LICENSE`](LICENSE), [`TERMS_OF_USE.md`](TERMS_OF_USE.md) e [`PRIVACY_POLICY.md`](PRIVACY_POLICY.md) para detalhes completos.
