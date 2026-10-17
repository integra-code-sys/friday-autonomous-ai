# Política de Privacidade e Arquitetura Zero-Telemetry — Integra Code

**Entidade Responsável pelo Software:** **Integra Code**  
**Produto:** F.R.I.D.A.Y. — Autonomous Multimodal AI Agent (Commercial Edition)

---

## Resumo Executivo

| Categoria de Dados | Coletado pela Integra Code? | Onde fica armazenado? | Quem tem acesso? |
| :--- | :---: | :--- | :--- |
| **Voz e Áudio (Microfone)** | **NÃO (0%)** | Memória RAM / Temporário Local | Apenas o Usuário |
| **Vídeo e Fotos (Câmeras / Tela)** | **NÃO (0%)** | Diretório local `dados/` (se solicitado) | Apenas o Usuário (e Provedor Cloud se ativado pelo usuário) |
| **Memória Semântica e Episódica** | **NÃO (0%)** | `dados/memoria.sqlite` e `dados/episodios.sqlite` (Local) | Apenas o Usuário |
| **Reconhecimento Facial / Biometria** | **NÃO (0%)** | Vetores ONNX locais em `dados/` | Apenas o Usuário |
| **Chaves de API (Gemini/Claude/GPT)** | **NÃO (0%)** | `dados/commercial_config.json` (Local) | Apenas o Usuário |
| **Telemetria / Analytics / Crash Logs** | **NÃO (0%)** | Logs locais na máquina do usuário | Apenas o Usuário |

---

## 1. Arquitetura "Local-First & User-Cloud Only"

A **Integra Code** projetou a F.R.I.D.A.Y. sob o princípio de **Privacidade por Design (*Privacy by Design*)**:
1. **Zero Servidores Intermediários:** Não existem servidores de backend da Integra Code recebendo dados da sua instalação.
2. **Auditoria de Rede em Tempo Real:** O módulo [`daemon/privacy_guard.py`](daemon/privacy_guard.py) inspeciona todas as chamadas de saída para garantir que apenas o motor local (`127.0.0.1` / LAN do usuário) ou os provedores de IA explicitamente configurados pelo usuário (`generativelanguage.googleapis.com`, `api.anthropic.com`, `api.openai.com`) possam ser contatados.
3. **Reset Instantâneo (Zero-State):** A qualquer momento, o usuário pode executar `./friday-config --reset-memory` ou clicar em **"Zerar Memória (Zero-State)"** no painel web para apagar todos os bancos de dados locais (`memoria.sqlite`, `episodios.sqlite`, `agenda.json`, `estado_mental.json`) e reiniciar o aprendizado do zero absoluto.

---

## 2. Contato e Transparência

Todo o código-fonte desta distribuição é aberto e auditável. Você pode verificar a conformidade de privacidade a qualquer momento executando:

```bash
python3 -m daemon.privacy_guard
```

**© 2026 Integra Code**
