# Guia de Contribuição (Contributing) & Arquitetura Comercial

Obrigado pelo interesse em contribuir com a **F.R.I.D.A.Y. (Projeto Prometheus — Commercial Edition)**!

## Estrutura de Diretórios

- `daemon/` — Núcleo autônomo em Python:
  - `cerebro.py` — Agente ReAct multi-turno com tool-calling nativo e verificação visual pós-ação.
  - `visao.py` — Captura multimodal de tela, câmeras e recortes de alta resolução para objetos na mão.
  - `cloud_providers.py` — Roteador unificado para **Ollama Local**, **Google Gemini**, **Anthropic Claude** e **OpenAI GPT**.
  - `camera_manager.py` — Gerenciador adaptativo para cenários com **0, 1, 2 ou 3+ câmeras (PTZ)**.
  - `memoria_zero.py` — Inicialização Zero-State (banco de dados limpo) e motor de aprendizado contínuo do zero.
  - `config_center.py` — Central de Configuração (Web UI em `/config` + CLI) e gerenciador de inicialização no Boot (Linux/Windows).
  - `sync_mesh.py` — Sincronização P2P Offline-First entre Linux, Windows e Android.
  - `win_compat.py` — Camada de abstração nativa para Windows 10/11 e Linux Wayland.
- `shell/` — Interface holográfica QML/Quickshell (HUD estilo Homem de Ferro).
- `android/` — Código-fonte e APK do controle remoto e assistente para Android.
- `tests/` — Suíte automatizada de testes multi-cenário (`test_scenarios_commercial.py`).

## Antes de Abrir um Pull Request

1. Certifique-se de não incluir nenhuma chave de API real ou dados pessoais em `memory/`.
2. Execute `python3 daemon/memoria_zero.py --reset` para manter o estado de fábrica limpo.
3. Execute a suíte de testes multi-cenário:
   ```bash
   python3 tests/test_scenarios_commercial.py
   ```
