# Changelog — F.R.I.D.A.Y. Commercial Edition

## [2.4.0-commercial] - 2026-10-19
### Adicionado
- Android 5.3: **papel de parede ao vivo Mark 85**. A armadura gira em 240 quadros de 1,5° com luz âmbar, em cima de um piso em perspectiva, pedestal holográfico, reflexo, brasas, paralaxe por inclinação e varredura com rótulos. Tem telemetria do aparelho (CPU, RAM, disco, bateria, rede, temperatura, núcleos) e 7 atalhos. Em paisagem mostra o busto. Roda num processo próprio, com canvas de hardware a 30 fps (~4 ms por quadro).
- App: visual de desktop Linux (janelas de vidro, barra com relógio, dock flutuante) e fundo holográfico com a mesma armadura.
- VNC: botões de clique esquerdo/direito/meio, rolagem, setas, ESC/TAB/F1–F12, CTRL/ALT/SHIFT/SUPER fixos e atalhos (CTRL+C/V/Z/A, ALT+TAB, ALT+F4, CTRL+ALT+DEL).
- Controles: 9 ações novas (mídia, brilho, desempenho, janelas) e o botão "PAPEL DE PAREDE MARK 85".
### Alterado
- Partículas do assistente padrão passaram do azul para o âmbar.

## [2.3.1-commercial] - 2026-10-17
### Alterado
- Plano composto começa em cursor, teclado ou gesto. Shell só depois que a tela falha.
- Android 4.4: pesquisa abre o navegador por intent, toca a tela e lê o resultado.

## [2.3.0-commercial] - 2026-10-17
### Adicionado
- Orquestrador geral com CLI longa (`prom-orquestra run`), fila persistente e plano antes da ação.
- Navegador do sistema nas três plataformas (intent Android, xdg-open no Linux, Start-Process no Windows).
- Instalador Windows Inno Setup (`installer/Friday.iss`), no lugar do extrator 7z.

## [2.2.0-commercial] - 2026-10-17
### Adicionado
- **Agenda única PC ↔ celular**: prioridade (alta/normal/baixa), **nível do dia** (livre → crítico), foco do dia, conflitos e tempo livre; espelho do Google Agenda do celular no PC e calendário local "Sexta-Feira (PC)" no Android com lembretes; fila offline (`/api/agenda`, `/api/agenda/sync`, `/api/agenda/add`).
- **Auto-aprendizado no celular (`Aprende.java`)**: calibração automática do limiar de voz, botão **FUI EU**, correções de palavras aprendidas ("não, eu disse…"), receitas de pedidos que deram certo e falhas a evitar.
- **Auto-aprimoramento do app Android**: o celular pede a melhoria ao PC (`/api/aprimorar`); o Claude propõe numa cópia, o dono aprova, e o PC compila e instala o APK.
- **Servidor de STT dedicado (`daemon/stt_servidor.py`)**: Whisper fora do processo principal, nos núcleos de desempenho (~5,9 s → ~3,4 s por frase); atende o PC e o celular (`/api/stt`).
- Painel do assistente no Android com partículas que reagem ao áudio real da voz e do microfone; agenda flutuante em linha do tempo; IDE do MODO DEV redesenhada.

### Corrigido
- Android: **WhatsApp de verdade** — abre a conversa pelo NOME (busca do próprio WhatsApp, inclusive grupos e Business), escreve e só envia após o "sim" do dono; antes abria um link sem número e dizia "enviei" sem enviar.
- Android: **pesquisa que responde** — perguntas viram busca na web (navegador interno invisível + Wikipédia) e a Friday responde com o resultado; o navegador só abre quando pedido. O DuckDuckGo bloqueava a busca automatizada.
- Android: permissão de contatos (WhatsApp/ligação pelo nome) e regra contra repetir respostas anteriores.
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
