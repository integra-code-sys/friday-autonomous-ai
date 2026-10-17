# Termos de Uso e Garantia de Soberania de Dados — F.R.I.D.A.Y. Commercial Edition

**Desenvolvido e Mantido por:** **Integra Code**  
**Versão:** 2.0.0 Commercial Edition  
**Última Atualização:** Outubro de 2026

---

## 1. Declaração Fundamental de Soberania de Dados (Zero-Data-Retention)

A **Integra Code** fornece o ecossistema **F.R.I.D.A.Y. (Prometheus OS)** como um software de inteligência artificial autônomo e auto-hospedado (*Self-Hosted / Edge AI*).

> [!IMPORTANT]
> **GARANTIA ABSOLUTA DE NÃO-RETENÇÃO DE DADOS:**  
> A **Integra Code NÃO coleta, NÃO armazena, NÃO intercepta, NÃO transmite e NÃO possui acesso** a nenhum dado pessoal, gravação de voz, captura de câmera, captura de tela, banco de dados de memória, histórico de conversas ou chaves de API do usuário.

Todo o processamento de dados ocorre **exclusivamente** em duas modalidades controladas 100% pelo próprio usuário:
1. **Processamento 100% Local (Offline / On-Device):** Na própria máquina do usuário (PC Linux, PC Windows ou smartphone Android) utilizando motores locais como `Ollama`, `Piper TTS`, `faster-whisper`, `OpenCV` e bancos de dados locais `SQLite`.
2. **Provedores de Nuvem Configurados pelo Próprio Usuário (BYOK — *Bring Your Own Key*):** Caso o usuário opte voluntariamente por ativar modelos em nuvem (**Google Gemini**, **Anthropic Claude** ou **OpenAI GPT**), as requisições saem **diretamente da máquina do usuário para os endpoints oficiais do respectivo provedor** utilizando a chave de API (`API Key`) privada fornecida pelo próprio usuário. Nenhuma requisição passa por servidores da **Integra Code**.

---

## 2. Proteção Técnica Auditável (`privacy_guard.py`)

Para garantir tecnicamente o cumprimento deste Termo de Uso, a edição comercial inclui o módulo de auditoria ativa [`daemon/privacy_guard.py`](daemon/privacy_guard.py), que:
- Bloqueia em tempo de execução qualquer conexão HTTP/HTTPS de saída para domínios que não estejam na lista estrita de provedores autorizados pelo usuário (`localhost`, `127.0.0.1`, redes locais privadas LAN/Tailscale do próprio usuário, `generativelanguage.googleapis.com`, `api.anthropic.com` e `api.openai.com`).
- Realiza auditoria estática em todos os módulos do sistema (`auditar_privacidade_instalacao()`) comprovando a ausência de SDKs de telemetria, *analytics*, *trackers* ou coletores ocultos.
- Armazena credenciais e memórias exclusivamente no diretório local `dados/` da máquina do usuário (protegido por `.gitignore`).

---

## 3. Uso de Provedores de Terceiros (Google, Anthropic, OpenAI)

Quando o usuário configura uma chave de API para **Google Gemini**, **Anthropic Claude** ou **OpenAI GPT**:
- O usuário estabelece uma relação direta com o provedor escolhido e está sujeito aos respectivos termos de serviço e políticas de privacidade daquele provedor.
- O usuário pode desativar o uso de nuvem a qualquer momento através do Centro de Configuração (`./friday-config` ou interface web `/config`), retornando instantaneamente ao modo **100% Local (`ollama`)**.

---

## 4. Sincronização Multi-Dispositivo (Mesh Sync P2P)

A funcionalidade de sincronização entre dispositivos (Linux, Windows e Android) opera de forma **Peer-to-Peer (P2P)** diretamente entre os dispositivos configurados pelo usuário em sua própria rede local (LAN) ou VPN privada (ex.: Tailscale). Nenhum servidor central da **Integra Code** intermedia essa sincronização.

---

## 5. Isenção de Garantias e Limitação de Responsabilidade

O software é fornecido "COMO ESTÁ" (*AS IS*), sob a licença MIT da **Integra Code**. O usuário é o único responsável:
- Pelas ações automatizadas executadas pelo agente em seu sistema operacional;
- Pela segurança física e lógica de seus dispositivos e chaves de API;
- Pelo cumprimento das leis locais aplicáveis ao uso de câmeras de monitoramento e gravação de áudio em seu próprio ambiente.

---

**© 2026 Integra Code — Todos os direitos reservados sob Licença MIT.**  
*Soberania Digital, Privacidade Absoluta e Inteligência Autônoma.*
