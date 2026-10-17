# 📦 Guia de Publicação e Página de Release para o GitHub — Integra Code

Este documento contém o texto pronto para a **Descrição do Repositório GitHub**, **GitHub Release (v2.1.0 Commercial Edition)** e instruções de publicação sob a chancela da **Integra Code**.

---

## 1. Nome e Descrição Curta Sugeridos para o Repositório GitHub
- **Organização / Autor:** `Integra Code`
- **Nome do Repositório:** `friday-autonomous-ai` (ou `prometheus-friday-os`)
- **Descrição Curta (About):**
  > 🤖 F.R.I.D.A.Y. Commercial Edition by Integra Code — Autonomous Multimodal AI Agent for Linux, Windows (.exe) & Android (.apk). Strict Owner-Only Voice Biometrics (TitaNet/WeSpeaker), Native Friday Agenda, Autonomous Dev IDE, Adaptive 0-to-3+ Camera Vision, Local (Ollama/GGUF) or Cloud AI (Gemini/Claude/GPT), P2P Mesh Sync & 100% Zero-Data-Retention Privacy Guarantee.

---

## 2. Texto Completo para a Release Oficial (`v2.1.0 - Integra Code Commercial Release`)

```markdown
# 🚀 F.R.I.D.A.Y. Commercial Edition v2.1.0 — Official Release by Integra Code

A **Integra Code** apresenta o lançamento oficial da edição comercial da **F.R.I.D.A.Y. (Prometheus OS)** — o ecossistema de inteligência artificial autônoma multimodal para **Linux, Windows e Android**, projetado com soberania digital, privacidade absoluta e execução distribuída.

![F.R.I.D.A.Y. Showcase](media/showcase_preview.gif)

---

### 📥 Instaladores Oficiais Disponíveis nesta Release
* 🪟 **Windows 10 / 11:** [`Instalador_Friday_Comercial_Windows.exe`](Instalador_Friday_Comercial_Windows.exe) (Instalador `.EXE` automático com atalho na Área de Trabalho e inicialização com o Windows)
* 📱 **Android 10+:** [`android/dist/friday-remoto.apk`](android/dist/friday-remoto.apk) (APK nativo com cérebro local GGUF, biometria de voz e floating HUD)
* 🐧 **Linux (Debian / Ubuntu / Fedora / Arch):** `./install_linux.sh && ./run.sh`

---

### 🌟 Principais Recursos e Inovações

#### 1. 🔒 Biometria Vocal Estrita — Apenas a Voz do Dono
* **No PC (Linux / Windows):** Rede neural **NVIDIA TitaNet-L** para verificação de locutor (`voz.py`). O sistema rejeita ativamente vozes de terceiros ou ruídos externos, processando comandos apenas quando o locutor verificado for o dono.
* **No Celular (Android):** Rede neural **WeSpeaker ResNet34 ONNX** integrada diretamente ao APK e ao Assistente Padrão (botão liga/desliga), com limiar dinâmico configurável e aprendizado adaptativo anti-deriva (*Voice Drift Protection*).

#### 2. 📅 Agenda Própria da Friday (Multi-Dispositivo)
* Sistema autônomo de gestão de compromissos que roda nativamente na Friday em vez de depender de calendários de terceiros.
* Níveis de ocupação diária inteligentes (`LIVRE`, `LEVE`, `MODERADO`, `INTENSO`, `CRÍTICO`), cálculo de horas livres em tempo real e timeline com status e prioridades.
* Sincronização automática via malha P2P entre o computador e o aplicativo móvel.

#### 3. 💻 Modo Dev — IDE Autônoma de Engenharia de Software
* **No PC (Linux / Windows):** Interface nativa `DevIDE` integrada diretamente ao Shell HUD (árvore de arquivos, editor com números de linha e diffs visuais, seletor de modelos, histórico e terminal do agente Claude CLI/local). Não abre mais apenas logs nem depende de janela externa.
* **No Celular (Android):** IDE móvel integrada com execução em até 8 rounds autônomos (**Planejamento -> Codificação -> Testes -> Auto-correção**), gerando arquivos direto no dispositivo ou despachando para a IDE do PC via malha P2P.

#### 4. ⚡ Tarefas Compostas Determinísticas
* Capacidade de interpretar e encadear ações complexas em comando único, por exemplo:
  * *"Pesquise as principais notícias sobre inteligência artificial e envie no WhatsApp para Fulano"*
  * *"Pesquise sobre computação quântica e crie um arquivo resumo.md na pasta de documentos"*
  * *"Pesquise o clima para o fim de semana e anote na agenda"*

#### 5. 🎨 Interface Futurista Stark — Zero Figurinhas/Emojis
* Eliminação total de ícones infantis, figurinhas e emojis em todos os componentes visuais do Android APK e do PC.
* Substituição por badges cyber e holográficos de alta precisão (`[ALTA]`, `[CRÍTICA]`, `[OK]`, `[AUTO]`, `[PC]`, `[PY]`, `[WEB]`, `[API]`, `[TOOL]`, `[STARK BIO]`, `>`).
* Fundo de tela dinâmico Stark com piso holográfico em perspectiva, reator animado com pulsação de voz e partículas em tempo real (unificado entre Linux Wayland e Windows).

#### 6. 🌐 Visão Multimodal Adaptativa (0 a 3+ Câmeras com Tolerância a Desconexão)
* Opera perfeitamente sem nenhuma câmera (modo desktop puro), com webcam única ou com conjunto multi-câmera (Nativa, Porta e PTZ do quarto).
* **Tratamento Inteligente de Desconexão PTZ:** Se a câmera PTZ for desligada ou desconectada da rede, o sistema limpa os caches imediatamente, não gera spam de logs, desabilita controles de pan/tilt com badge `[DESCONECTADA]` e promove dinamicamente a câmera conectada para a visualização principal.
* Alternância dinâmica entre modelos de visão local (`YOLO-World`, `Moondream`, `Ollama`) e nuvem (`Gemini 2.5 Flash`, `Claude 3.5 Sonnet`, `GPT-4o`).

#### 7. 🛡️ Garantia de Não-Retenção de Dados (Zero-Data-Retention)
* A **Integra Code** garante formalmente que **nenhum dado pessoal, áudio, vídeo ou credencial é transmitido ou retido por nós**.
* Todo o processamento é 100% local ou roteado diretamente da máquina do usuário para o provedor de nuvem de sua escolha ([Termos de Uso](TERMS_OF_USE.md) e [Política de Privacidade](PRIVACY_POLICY.md)).
* Bateria de 19 testes automatizados de conformidade, segurança e regressão 100% aprovada.
```

---

## 3. Como Publicar no GitHub

1. Inicialize e faça o push dos arquivos desta pasta para o repositório da Integra Code:
   ```bash
   cd "friday-commercial-github"
   git init
   git add .
   git commit -m "feat: F.R.I.D.A.Y. Commercial Edition v2.1.0 by Integra Code"
   git branch -M main
   git remote add origin https://github.com/integra-code/friday-autonomous-ai.git
   git push -u origin main
   ```
2. Crie a Release oficial anexando os executáveis compilados:
   ```bash
   gh release create v2.1.0 \
     --title "F.R.I.D.A.Y. Commercial Edition v2.1.0 — Integra Code" \
     --notes-file GITHUB_RELEASE_PAGE.md \
     Instalador_Friday_Comercial_Windows.exe \
     android/dist/friday-remoto.apk
   ```
