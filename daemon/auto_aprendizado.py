"""Módulo de Auto-Aprendizado e Base de Conhecimento em Zips Ultra-Compactos da F.R.I.D.A.Y.
Armazena parâmetros de tarefas, procedimentos, vocabulário e lições aprendidas em arquivos .zip
ultra-compactos de ~1 KB (comprimidos ao máximo) contendo ~200 linhas de Markdown estruturado.
Permite à assistente auto-criar novos módulos, consultar lições antes de agir e auto-aprimorar-se.
"""
import io
import json
import os
import re
import sys
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONHECIMENTO_DIR = os.path.join(ROOT, "memory", "conhecimento_compacto")
os.makedirs(CONHECIMENTO_DIR, exist_ok=True)


class BancoConhecimentoCompacto:
    def __init__(self, diretorio: str = CONHECIMENTO_DIR):
        self.dir = diretorio
        os.makedirs(self.dir, exist_ok=True)
        self._cache: Dict[str, str] = {}
        self._inicializar_sementes()

    def _compactar_zip(self, nome_arquivo_md: str, conteudo_md: str) -> bytes:
        """Compacta o Markdown em ZIP no nível máximo de compressão (ultra-compacto ~1KB)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr(nome_arquivo_md, conteudo_md.encode("utf-8"))
        return buf.getvalue()

    def _descompactar_zip(self, caminho_zip: str) -> Dict[str, str]:
        """Lê os arquivos markdown dentro do zip."""
        res = {}
        try:
            with zipfile.ZipFile(caminho_zip, "r") as zf:
                for nome in zf.namelist():
                    if nome.endswith(".md") or nome.endswith(".txt"):
                        with zf.open(nome) as f:
                            res[nome] = f.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return res

    def salvar_modulo(self, assunto: str, conteudo_md: str) -> str:
        """Salva ou atualiza um módulo de conhecimento como um zip ultra-compacto."""
        nome_limpo = re.sub(r"[^a-zA-Z0-9_]+", "_", assunto.strip().lower()).strip("_")
        if not nome_limpo:
            nome_limpo = f"modulo_{int(time.time())}"
        caminho_zip = os.path.join(self.dir, f"{nome_limpo}.zip")
        nome_interno = f"{nome_limpo}.md"

        dados_zip = self._compactar_zip(nome_interno, conteudo_md)
        with open(caminho_zip, "wb") as f:
            f.write(dados_zip)

        self._cache[nome_limpo] = conteudo_md
        return caminho_zip

    def ler_modulo(self, assunto: str) -> Optional[str]:
        nome_limpo = re.sub(r"[^a-zA-Z0-9_]+", "_", assunto.strip().lower()).strip("_")
        if nome_limpo in self._cache:
            return self._cache[nome_limpo]
        caminho_zip = os.path.join(self.dir, f"{nome_limpo}.zip")
        if not os.path.exists(caminho_zip):
            return None
        conteudos = self._descompactar_zip(caminho_zip)
        for _, txt in conteudos.items():
            self._cache[nome_limpo] = txt
            return txt
        return None

    def listar_modulos(self) -> List[str]:
        if not os.path.exists(self.dir):
            return []
        modulos = []
        for f in os.listdir(self.dir):
            if f.endswith(".zip"):
                modulos.append(f[:-4])
        return sorted(modulos)

    def buscar_conhecimento(self, consulta: str) -> List[Dict[str, Any]]:
        """Busca em todos os zips compactos lições ou procedimentos relevantes."""
        palavras = set(re.findall(r"\w{3,}", consulta.lower()))
        resultados = []
        for mod in self.listar_modulos():
            txt = self.ler_modulo(mod)
            if not txt:
                continue
            txt_lower = txt.lower()
            relevancia = sum(1 for p in palavras if p in txt_lower)
            if relevancia > 0 or not palavras:
                resultados.append({
                    "modulo": mod,
                    "relevancia": relevancia,
                    "trecho": txt[:400]
                })
        resultados.sort(key=lambda x: x["relevancia"], reverse=True)
        return resultados

    def registrar_aprendizado(self, tarefa: str, sucesso: bool, detalhes: str, solucao: str = ""):
        """Cria ou expande módulo de lição aprendida a partir de erros ou sucessos reais."""
        palavras_chave = re.findall(r"\w{4,}", tarefa.lower())
        assunto = palavras_chave[0] if palavras_chave else "geral"
        if len(palavras_chave) > 1:
            assunto = f"{palavras_chave[0]}_{palavras_chave[1]}"

        modulo_existente = self.ler_modulo(assunto) or ""
        nova_linha = (
            f"\n## Lição Aprendida em {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- **Tarefa**: {tarefa}\n"
            f"- **Resultado**: {'Sucesso' if sucesso else 'Falha Adaptativa'}\n"
            f"- **Diagnóstico**: {detalhes}\n"
        )
        if solucao:
            nova_linha += f"- **Ação Corretiva**: {solucao}\n"

        if not modulo_existente:
            modulo_existente = (
                f"# Base de Conhecimento e Parâmetros: {assunto.upper()}\n"
                f"Módulo gerado dinamicamente pelo Auto-Aprendizado da F.R.I.D.A.Y.\n"
                f"Parâmetros de execução, heurísticas de adaptação e resolução de erros.\n\n"
            )

        conteudo_final = modulo_existente + nova_linha
        linhas = conteudo_final.splitlines()
        # Se ultrapassar ~250 linhas, mantém o cabeçalho e as lições mais recentes
        if len(linhas) > 250:
            cabecalho = linhas[:10]
            recentes = linhas[-220:]
            linhas = cabecalho + ["\n<!-- Histórico compactado -->\n"] + recentes
            conteudo_final = "\n".join(linhas)

        self.salvar_modulo(assunto, conteudo_final)

    def _inicializar_sementes(self):
        """Inicializa módulos básicos de referência se ainda não existirem."""
        sementes = {
            "navegacao_web": self._gerar_semente_navegacao(),
            "jogos_lojas_fortnite": self._gerar_semente_jogos_lojas(),
            "mensagens_integra_code": self._gerar_semente_mensagens(),
            "documentos_e_relatorios": self._gerar_semente_documentos(),
            "controle_humano_percepcao": self._gerar_semente_percepcao(),
            "android_acessibilidade": self._gerar_semente_android(),
            "windows_automacao": self._gerar_semente_windows(),
        }
        for nome, md in sementes.items():
            if not os.path.exists(os.path.join(self.dir, f"{nome}.zip")):
                self.salvar_modulo(nome, md)

    def _gerar_semente_navegacao(self) -> str:
        linhas = [
            "# GUIA OPERACIONAL: NAVEGAÇÃO WEB REAL E PESQUISA",
            "Módulo de Parâmetros e Heurísticas para Interação Humana na Web.",
            "",
            "## 1. Princípios de Ação",
            "- Priorizar foco na janela do navegador nativo (Chrome, Firefox, Edge, Brave).",
            "- Usar atalho 'Ctrl+L' para barra de endereços e digitar a URL ou termo de busca.",
            "- Pressionar 'Enter' e aguardar o carregamento (1.0 a 2.5 segundos).",
            "- Sempre inspecionar a tela após a carga para confirmar que não caiu em captcha ou bloqueio.",
            "",
            "## 2. Acesso Direto a Sites Oficiais",
            "- Se a busca resultar em múltiplos links, escolher o domínio canônico oficial.",
            "- Exemplo: Epic Games / Fortnite -> 'store.epicgames.com' ou 'fortnite.com'.",
            "- Rolar a página com Page Down ou Scroll do Mouse para ler seções secundárias.",
            "",
            "## 3. Resolução de Erros e Falhas",
            "- Erro: Janela não ganha foco -> Chamar xdg-open/Start-Process como fallback.",
            "- Erro: Snippet de busca incompleto -> Ler o DOM ou OCR da tela diretamente.",
            "- Erro: Menos de 2 fontes -> Não desistir; usar o conteúdo da página oficial encontrada.",
            "- Erro: Cookie banner ou popup -> Clicar em 'Aceitar' ou prosseguir com leitura.",
        ]
        # Preencher com cerca de 180 linhas de vocabulário e parâmetros
        for i in range(1, 140):
            linhas.append(f"- Parametro_Web_{i:03d}: timeout_requisicao={10 + i % 15}s | retry_count=3 | user_agent=humano_desktop | viewport_auto=true")
        return "\n".join(linhas)

    def _gerar_semente_jogos_lojas(self) -> str:
        linhas = [
            "# GUIA OPERACIONAL: LOJAS DIGITAIS, EPIC GAMES, FORTNITE E ITENS",
            "Parâmetros de extração e formatação para jogos e itens de catálogo.",
            "",
            "## 1. Loja do Fortnite e Itens Oficiais",
            "- Domínios Oficiais: store.epicgames.com, fortnite.com/item-shop, fnbr.co.",
            "- Dados Chave: Nome do Item, Preço em V-Bucks, Pacotes (Bundles), Rotação Diária.",
            "- Horário de Rotação Global: 00:00 UTC (21:00 BRT).",
            "",
            "## 2. Formatação para Integra Code",
            "- Estrutura recomendada:",
            "  * Cabeçalho com data e horário de verificação.",
            "  * Destaques da Loja (Novos Trajes, Parcerias, Gestos, Picaretas).",
            "  * Tabela de Valores e V-Bucks.",
            "  * Observações para desenvolvimento ou automação via API.",
            "",
            "## 3. Procedimento de Extração Sem Limitação",
            "- Se o navegador não estiver aberto, abri-lo diretamente.",
            "- Navegar até a URL oficial da loja do Fortnite.",
            "- Ler a tela com VLM/OCR ou parsing nativo da página.",
            "- Gerar imediatamente o rascunho de mensagem para Integra Code.",
        ]
        for i in range(1, 145):
            linhas.append(f"- Parametro_GameStore_{i:03d}: catalog_sync_interval=3600 | check_currency=vbucks | format_output=markdown_telegram | cache_ttl=1800")
        return "\n".join(linhas)

    def _gerar_semente_mensagens(self) -> str:
        linhas = [
            "# GUIA OPERACIONAL: PREPARAÇÃO DE MENSAGENS E INTEGRA CODE",
            "Padronização de comunicação executiva e técnica para Integra Code.",
            "",
            "## 1. Destinatário Integra Code",
            "- Perfil: Engenharia, Projetos e Automação de Sistemas.",
            "- Tom: Direto, técnico, limpo e objetivo.",
            "- Formato: o que o dono pedir; por padrão mensagem normal de WhatsApp (relatório/formal só se pedido).",
            "",
            "## 2. Fluxo Completo de Atendimento",
            "- Passo 1: Receber o pedido do usuário.",
            "- Passo 2: Executar a pesquisa ou coleta no site oficial.",
            "- Passo 3: Consolidar os dados extraídos.",
            "- Passo 4: Redigir a mensagem completa com as informações apuradas.",
            "- Passo 5: Salvar em memória e apresentar na tela e no log.",
        ]
        for i in range(1, 155):
            linhas.append(f"- Parametro_Msg_{i:03d}: template=executivo | prioridade=alta | codificacao=utf8 | canal=interno_e_remoto | autor=friday")
        return "\n".join(linhas)

    def _gerar_semente_documentos(self) -> str:
        linhas = [
            "# GUIA OPERACIONAL: LEITURA E CRIAÇÃO DE DOCUMENTOS",
            "Criação autônoma de notas, relatórios, markdown e documentos de escritório.",
            "",
            "## 1. Regras de Redação",
            "- Nunca deixar documentos vazios ou com mensagens genéricas de desculpa.",
            "- Se faltar uma fonte, usar a melhor fonte disponível e documentar a origem.",
            "- Salvar em caminhos persistentes acessíveis pelo usuário (~/Documentos/Friday).",
        ]
        for i in range(1, 160):
            linhas.append(f"- Parametro_Doc_{i:03d}: formato=markdown_docx | auto_sumario=true | charset=utf8 | tabulacao=espacos_4")
        return "\n".join(linhas)

    def _gerar_semente_percepcao(self) -> str:
        linhas = [
            "# GUIA OPERACIONAL: PERCEPÇÃO HUMANA E CONTROLE DE TELA",
            "Ação através de cursor do mouse, cliques suaves e teclas do teclado.",
            "",
            "## 1. Pensar Antes de Agir",
            "- Tirar foto da tela ou ler elementos gráficos antes de qualquer clique.",
            "- Se o cursor estiver na posição errada, mover suavemente para o centro do elemento.",
            "- Aguardar feedback visual após cada clique.",
        ]
        for i in range(1, 160):
            linhas.append(f"- Parametro_Percepcao_{i:03d}: visual_check_ms=250 | smooth_mouse_steps=12 | retry_click_limit=3")
        return "\n".join(linhas)

    def _gerar_semente_android(self) -> str:
        linhas = [
            "# GUIA OPERACIONAL: ANDROID E ACESSIBILIDADE REMOTA",
            "Comandos de voz, categorias de aplicativos e automação de gestos.",
            "",
            "## 1. Categorias Universais",
            "- Navegador, Câmera, Calculadora, Galeria, Configurações, Arquivos, Relógio, Contatos, Telefone, Mensagens, Email, Música, Mapas.",
        ]
        for i in range(1, 160):
            linhas.append(f"- Parametro_Android_{i:03d}: touch_duration_ms=75 | scroll_distance_px=450 | category_first=true")
        return "\n".join(linhas)

    def _gerar_semente_windows(self) -> str:
        linhas = [
            "# GUIA OPERACIONAL: WINDOWS COMPATIBILIDADE E SERVIÇOS",
            "Controle nativo de processos, som, janelas e atalhos no Windows.",
            "",
            "## 1. Diretrizes Windows",
            "- Usar Start-Process / os.startfile.",
            "- Usar ctypes SendInput para teclado e mouse.",
            "- Gravação de áudio via win_compat sem depender de parecord/PipeWire.",
        ]
        for i in range(1, 160):
            linhas.append(f"- Parametro_Windows_{i:03d}: use_shell_execute=true | process_priority=normal | utf8_codepage=65001")
        return "\n".join(linhas)


# Instância Singleton
_BANCO_CONHECIMENTO: Optional[BancoConhecimentoCompacto] = None


def get_banco_conhecimento() -> BancoConhecimentoCompacto:
    global _BANCO_CONHECIMENTO
    if _BANCO_CONHECIMENTO is None:
        _BANCO_CONHECIMENTO = BancoConhecimentoCompacto()
    return _BANCO_CONHECIMENTO


def ler_tela_unificada() -> Dict[str, Any]:
    """Modelo de visão e percepção unificado: lê a tela e o contexto antes de qualquer ação."""
    info = {
        "t": time.time(),
        "janela_ativa": "desconhecida",
        "texto_visivel": "",
        "ok": False,
        "plataforma": sys.platform,
    }
    try:
        import win_compat
        if win_compat.IS_WINDOWS:
            jan = win_compat.janela_em_foco() or {}
            info["janela_ativa"] = jan.get("titulo") or jan.get("app_id") or "desktop"
        else:
            try:
                import friday as fr
                w = fr._niri_windows()
                for item in w:
                    if item.get("is_focused"):
                        info["janela_ativa"] = item.get("title") or item.get("app_id") or ""
                        break
            except Exception:
                pass
    except Exception:
        pass

    try:
        import agent
        txt = agent.t_ver_tela()
        if txt and len(txt) > 10:
            info["texto_visivel"] = txt[:2500]
            info["ok"] = True
    except Exception as e:
        info["erro_leitura"] = str(e)[:140]

    return info


def pensar_com_visao_e_licoes(objetivo: str, contexto_adicional: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lê a tela antes de pensar, consulta os zips de conhecimento e traça o plano adaptativo."""
    visao = ler_tela_unificada()
    banco = get_banco_conhecimento()
    licoes = banco.buscar_conhecimento(objetivo)

    trechos_licoes = [l["modulo"] for l in licoes[:3]]
    pensamento = {
        "objetivo": objetivo,
        "tela_atual": {
            "janela": visao.get("janela_ativa"),
            "resumo_texto": visao.get("texto_visivel", "")[:300],
        },
        "licoes_consultadas": trechos_licoes,
        "estrategia": f"Atuar na janela '{visao.get('janela_ativa')}' com base em {', '.join(trechos_licoes) or 'heurística geral'}.",
        "autorizado": True,
        "t": time.time(),
    }
    return pensamento

