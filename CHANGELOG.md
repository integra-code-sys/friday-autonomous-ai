# Changelog — F.R.I.D.A.Y. Commercial Edition

## [2.0.0-commercial] - 2026-10-17
### Adicionado
- **Memória Zero-State & Aprendizado do Zero (`daemon/memoria_zero.py`)**: Inicialização limpa de bancos SQLite (`memoria.sqlite`, `episodios.sqlite`) e arquivos JSON sem dados pessoais pré-existentes, com aprendizado contínuo de fatos, receitas episódicas e lições de autorreflexão.
- **Gerenciador Adaptativo Multi-Câmeras (`daemon/camera_manager.py`)**: Suporte automático e manual para computadores com **0 câmeras** (`sem_camera`), **1 câmera** (`1_camera`), **2 câmeras** (`2_cameras`) ou **3+ câmeras com PTZ** (`3_cameras_ptz`).
- **Provedores de Visão e Cérebro em Nuvem (`daemon/cloud_providers.py`)**: Suporte nativo a **Google Gemini**, **Anthropic Claude**, **OpenAI GPT** e **Ollama Local**, além de modo híbrido (`auto`) com fallback offline.
- **Central de Configuração & Inicialização no Boot (`daemon/config_center.py`)**: Painel Web em `http://127.0.0.1:8790/config` e CLI `./friday-config` para ativar/desativar inicialização automática no boot (Linux e Windows), configurar chaves de nuvem, modo de câmeras e reset de memória.
- **Instaladores Fáceis Multiplataforma**:
  - Linux: `install_linux.sh`, `run.sh`, `friday-config`.
  - Windows: `Instalador_Friday_Comercial_Windows.exe` (auto-extraível SFX) e `install_windows.bat`.
  - Android: `android/friday-commercial.apk` e `android/install_android.sh`.
- **Sincronização Mesh P2P (`daemon/sync_mesh.py`)**: Replicação e merge delta automático entre PC Linux, PC Windows e Android.
