# Changelog — F.R.I.D.A.Y. Commercial Edition

## [2.2.0-commercial] - 2026-10-17
### Adicionado
- **Agenda única PC ↔ celular**: prioridade (alta/normal/baixa), **nível do dia** (livre → crítico), foco do dia, conflitos e tempo livre; espelho do Google Agenda do celular no PC e calendário local "Sexta-Feira (PC)" no Android com lembretes; fila offline (`/api/agenda`, `/api/agenda/sync`, `/api/agenda/add`).
- **Auto-aprendizado no celular (`Aprende.java`)**: calibração automática do limiar de voz, botão **FUI EU**, correções de palavras aprendidas ("não, eu disse…"), receitas de pedidos que deram certo e falhas a evitar.
- **Auto-aprimoramento do app Android**: o celular pede a melhoria ao PC (`/api/aprimorar`); o Claude propõe numa cópia, o dono aprova, e o PC compila e instala o APK.
- **Servidor de STT dedicado (`daemon/stt_servidor.py`)**: Whisper fora do processo principal, nos núcleos de desempenho (~5,9 s → ~3,4 s por frase); atende o PC e o celular (`/api/stt`).
- Painel do assistente no Android com partículas que reagem ao áudio real da voz e do microfone; agenda flutuante em linha do tempo; IDE do MODO DEV redesenhada.

### Corrigido
- Android: o reconhecedor do sistema ignora áudio entregue pelo app (texto vazio e microfone reaberto em loop) — a fala filtrada agora vai ao Whisper do PC; sem PC, o reconhecedor usa o microfone direto.
- Cérebro: prefixo do prompt estável (a hora saiu das instruções) — 1º passo de ~3,7 s para ~0,1 s de processamento.
- O APK comercial não traz mais perfil de voz nem endereço de PC pré-configurados: cada cliente cadastra a própria voz e o próprio PC.

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
