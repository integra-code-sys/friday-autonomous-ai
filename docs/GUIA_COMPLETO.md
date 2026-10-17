# 📖 Guia Completo — F.R.I.D.A.Y. Commercial Edition

## 1. Como Funciona a Criação de Memória e Aprendizado do Zero

Na edição comercial, a F.R.I.D.A.Y. nasce como uma **folha em branco** (`Zero-State`).
Ao iniciar pela primeira vez (ou após rodar `./friday-config --reset-memory`), o módulo [`daemon/memoria_zero.py`](../daemon/memoria_zero.py) cria tabelas limpas:
- **Fatos sobre o Usuário e o PC (`memoria.sqlite`)**: Sempre que você diz algo durável (*"Meu nome é Ana e trabalho com engenharia de dados"*), a ferramenta `lembrar` grava o fato com carimbo de tempo e relevância.
- **Receitas Episódicas (`episodios.sqlite`)**: Quando a F.R.I.D.A.Y. executa uma sequência de passos que atinge o objetivo e passa na verificação visual da tela, ela armazena a receita (`pedido -> sequência de ferramentas -> resultado`). Da próxima vez que você pedir algo semelhante, a receita é injetada em `[já deu certo antes]`.
- **Lições de Erros (`licoes_aprendidas.json`)**: Se uma ferramenta falha durante a execução, o motor registra a causa e a alternativa para evitar loops futuros.

---

## 2. Configurando Visão e Cérebro em Nuvem (Gemini, Claude, GPT) ou Local (Ollama)

Você pode alterar o provedor a qualquer momento pelo navegador em `http://127.0.0.1:8790/config` ou via terminal:

| Provedor | Comando Rápido CLI | Modelo Padrão Recomendado |
| :--- | :--- | :--- |
| **Ollama Local (Offline)** | `./friday-config --provider ollama` | `qwen3-vl:4b-instruct` |
| **Google Gemini** | `./friday-config --provider gemini --api-key SUA_CHAVE` | `gemini-2.5-flash` |
| **Anthropic Claude** | `./friday-config --provider claude --api-key SUA_CHAVE` | `claude-3-5-sonnet-latest` |
| **OpenAI GPT** | `./friday-config --provider openai --api-key SUA_CHAVE` | `gpt-4o` |
| **Híbrido (`auto`)** | `./friday-config --provider auto` | Tenta Nuvem configurada -> Fallback Ollama Local |

---

## 3. Cenários de Câmeras (0, 1, 2 ou 3+ Câmeras)

O módulo [`daemon/camera_manager.py`](../daemon/camera_manager.py) garante que a F.R.I.D.A.Y. funcione perfeitamente em qualquer computador:

- **PC Desktop sem Webcam (`0 câmeras` / `sem_camera`)**:
  - Nenhuma thread de captura de vídeo é iniciada.
  - A ferramenta `olhar` expõe apenas `fonte="tela"`, lendo sua tela e OCR em alta resolução.
  - Se você perguntar sobre câmeras, ela responde educadamente que o modo sem câmeras está ativo.
- **Notebook ou PC com 1 Webcam (`1_camera`)**:
  - A ferramenta de câmera motorizada (`camera` PTZ) é removida automaticamente da lista de ferramentas do modelo.
  - Pedidos de olhar o usuário, objetos na mão (`fonte="maos"`) ou o quarto são roteados de forma transparente para a sua única câmera (`camera_notebook`).
- **PC com 2 Câmeras (`2_cameras`)**:
  - Usa a primeira câmera para você/mãos e a segunda para o ambiente, mantendo o controle PTZ desativado.
- **Setup Completo com 3+ Câmeras e PTZ (`3_cameras_ptz`)**:
  - Habilita todas as fontes (`tela`, `camera_notebook`, `camera_porta`, `camera_quarto`, `maos`, `todas`) e todas as operações ONVIF/RTSP da câmera motorizada.
