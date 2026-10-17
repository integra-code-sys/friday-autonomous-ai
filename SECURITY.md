# Política de Segurança e Privacidade (Security Policy)

## Proteção de Dados e Portão de Aprovação (`Gated Actions`)

A **F.R.I.D.A.Y.** foi projetada com segurança em camadas:
1. **Portão de Aprovação Obrigatória**: Ações sensíveis (envio de mensagens no WhatsApp, envio de e-mails, comandos `sudo` ou alterações destrutivas no terminal) nunca são executadas silenciosamente — elas geram um rascunho pendente para aprovação explícita do usuário por voz ou no app.
2. **Autenticação por Token (`X-Token`)**: O servidor remoto/mesh na porta `8790` gera automaticamente um token criptográfico único em `memory/remoto.json` (`chmod 0600`) na primeira inicialização.
3. **Chaves de Nuvem Locais**: Suas chaves de API (Gemini, Claude, OpenAI) ficam salvas exclusivamente em `memory/config_comercial.json` na sua máquina local e são mascaradas na interface web.
