#!/usr/bin/env python3
"""
Bateria Massiva de Testes Comerciais — F.R.I.D.A.Y. Commercial Edition (Integra Code)
Valida:
  1. Compilação AST e sintaxe de todos os módulos Python do pacote comercial.
  2. Sanitização de dados pessoais/sensíveis em todos os arquivos de código, memória e documentação.
  3. Presença e integridade dos documentos legais da Integra Code (TERMS_OF_USE.md, PRIVACY_POLICY.md, LICENSE).
  4. Privacy Guard (bloqueio de domínios não autorizados, permissão de provedores do usuário, auditoria estática de zero-telemetria).
  5. Auto Dependencies (verificação de pacotes Python, binários de sistema, modelos ONNX, dry-run installer e bootstrap zero-state).
  6. Todos os cenários de câmera (0, 1, 2, 3+ câmeras PTZ, adaptação dinâmica de ferramentas e resolução de fallback).
  7. Provedores de IA em Nuvem e Local (Ollama, Gemini, Claude, OpenAI, modo Auto híbrido e bloqueio de URL maliciosa via Privacy Guard).
  8. Memória Zero-State e Aprendizado Contínuo do Zero (fatos, episódios, autocrítica deduplicada, onboarding).
  9. Mesh Sync P2P Multi-Dispositivo (merge bidirecional de agenda, fatos, lições, conversas e resolução de conflitos).
  10. Central de Configuração Web e CLI (geração de scripts de boot, endpoints JSON e interface HTML com Termos Integra Code).
"""
import ast
import asyncio
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(HERE)
DAEMON_DIR = os.path.join(ROOT_DIR, "daemon")
if DAEMON_DIR not in sys.path:
    sys.path.insert(0, DAEMON_DIR)

import auto_deps
import camera_manager
import cerebro
import cloud_providers
import config_center
import memoria
import memoria_zero
import privacy_guard
import sync_mesh
import visao


class TestMegaBatteryIntegraCode(unittest.TestCase):

    def setUp(self):
        memoria_zero.inicializar_do_zero(forcar=True, nome_usuario="Senhor", manter_config_ia=False)
        camera_manager.forcar_cenario_teste(None)
        cloud_providers.set_mock_http(None)

    def tearDown(self):
        camera_manager.forcar_cenario_teste(None)
        cloud_providers.set_mock_http(None)
        memoria_zero.inicializar_do_zero(forcar=True, nome_usuario="Senhor", manter_config_ia=False)

    # =========================================================================
    # 1. COMPILAÇÃO AST E INTEGRIDADE DE SINTAXE DE TODOS OS MÓDULOS
    # =========================================================================
    def test_01_ast_syntax_all_python_files(self):
        """Verifica se todos os arquivos .py do diretório comercial compilam sem erros de sintaxe."""
        py_files = []
        for root, _, files in os.walk(ROOT_DIR):
            if ".venv" in root or "__pycache__" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    py_files.append(os.path.join(root, f))

        self.assertGreaterEqual(len(py_files), 20, "Deve haver pelo menos 20 módulos Python no pacote comercial")
        for filepath in py_files:
            with open(filepath, "r", encoding="utf-8") as fh:
                source = fh.read()
            try:
                ast.parse(source, filename=filepath)
            except SyntaxError as e:
                self.fail(f"Erro de sintaxe em {filepath}: {e}")

    # =========================================================================
    # 2. AUDITORIA DE ZERO DADOS PESSOAIS / SENSÍVEIS E DOCUMENTOS INTEGRA CODE
    # =========================================================================
    def test_02_zero_personal_data_leak(self):
        """Garante que nenhum arquivo de configuração, banco de dados ou documentação contenha dados pessoais."""
        forbidden_tokens = [
            "100.110.228.59",
            "100.78.57.122",
            "100.84.228.72",
            "1 577 000 126",
            "1577000126",
        ]
        for root, _, files in os.walk(ROOT_DIR):
            if ".git" in root or "__pycache__" in root or "media" in root:
                continue
            for f in files:
                if f.endswith((".py", ".md", ".json", ".sh", ".bat", ".html", ".kt")):
                    if f == "test_mega_battery.py":
                        continue
                    path = os.path.join(root, f)
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                    for token in forbidden_tokens:
                        self.assertNotIn(token, content, f"Dado sensível '{token}' encontrado em {path}")

    def test_03_integra_code_branding_and_legal_docs_exist(self):
        """Valida a presença dos documentos legais da Integra Code (TERMS_OF_USE.md, PRIVACY_POLICY.md, LICENSE)."""
        for doc in ("TERMS_OF_USE.md", "PRIVACY_POLICY.md", "LICENSE"):
            p = os.path.join(ROOT_DIR, doc)
            self.assertTrue(os.path.exists(p), f"Documento obrigatório ausente: {doc}")
            with open(p, "r", encoding="utf-8") as fh:
                txt = fh.read()
            self.assertIn("Integra Code", txt, f"Marca 'Integra Code' ausente em {doc}")

    # =========================================================================
    # 3. PRIVACY GUARD & ZERO-DATA-RETENTION ENFORCEMENT
    # =========================================================================
    def test_04_privacy_guard_allows_local_and_user_cloud_only(self):
        """Garante que localhost, host Ollama customizado do usuário e provedores oficiais são aceitos."""
        allowed_urls = [
            ("http://127.0.0.1:11434/api/chat", ""),
            ("http://localhost:8790/status", ""),
            ("http://192.168.1.50:11434/api/generate", "http://192.168.1.50:11434"),
            ("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent", ""),
            ("https://api.anthropic.com/v1/messages", ""),
            ("https://api.openai.com/v1/chat/completions", ""),
        ]
        for url, custom_ollama in allowed_urls:
            self.assertTrue(privacy_guard.validar_url_saida(url, ollama_url_custom=custom_ollama))

    def test_05_privacy_guard_blocks_unauthorized_external_servers(self):
        """Garante que qualquer servidor externo não autorizado dispara PrivacyViolationError."""
        blocked_urls = [
            "https://telemetry.evil-tracker.com/collect",
            "https://analytics.google.com/collect",
            "http://8.8.8.8:8080/exfiltrate",
            "https://sentry.io/api/123/store/",
            "https://api.unknown-llm-proxy.org/v1/chat",
            "",
        ]
        for url in blocked_urls:
            with self.assertRaises(privacy_guard.PrivacyViolationError):
                privacy_guard.validar_url_saida(url)

    def test_06_privacy_guard_static_code_audit(self):
        """Executa a auditoria estática de código garantindo zero telemetria em todos os módulos."""
        relatorio = privacy_guard.auditar_privacidade_instalacao()
        self.assertTrue(relatorio["ok"])
        self.assertEqual(relatorio["organizacao"], "Integra Code")
        self.assertFalse(relatorio["telemetria_externa"])
        self.assertFalse(relatorio["retencao_dados_integracode"])
        self.assertEqual(len(relatorio["violacoes"]), 0)
        self.assertIn("Integra Code", relatorio["declaracao"])

    # =========================================================================
    # 4. AUTO DEPENDENCIES & BOOTSTRAP
    # =========================================================================
    def test_07_auto_deps_verification_and_bootstrap(self):
        """Verifica o diagnóstico completo de dependências Python, binários, modelos ONNX e dry-run installer."""
        rel = auto_deps.relatorio_completo()
        self.assertEqual(rel["empresa"], "Integra Code")
        self.assertTrue(rel["python_deps"]["todos_obrigatorios_ok"])
        self.assertTrue(rel["modelos"]["todos_essenciais_ok"])
        self.assertTrue(rel["binarios"]["ffmpeg"])
        self.assertTrue(rel["binarios"]["curl"])

        # Dry-run de instalação de sistema
        sys_res = auto_deps.instalar_dependencias_sistema(dry_run=True)
        self.assertTrue(sys_res["ok"])

        # Bootstrap completo sem reinstalar via rede
        boot_res = auto_deps.bootstrap_completo(auto_install_python=False, auto_download_models=False)
        self.assertTrue(boot_res["ok"])

    # =========================================================================
    # 5. TODOS OS CENÁRIOS DE CÂMERA (0, 1, 2, 3+ CÂMERAS E FALLBACKS)
    # =========================================================================
    def test_08_camera_scenarios_comprehensive(self):
        """Testa todos os cenários de câmera (0, 1, 2, 3+ câmeras) e fallbacks de resolução."""
        # 0 câmeras
        c0 = camera_manager.forcar_cenario_teste(0)
        self.assertEqual(c0["modo"], "sem_camera")
        self.assertFalse(camera_manager.tem_camera_ptz())
        self.assertEqual(camera_manager.fontes_olhar_disponiveis(), ["tela"])
        f0, nota0 = camera_manager.resolver_fonte_camera("camera_notebook")
        self.assertEqual(f0, "sem_camera")
        self.assertIn("sem câmeras", nota0.lower())

        # 1 câmera
        c1 = camera_manager.forcar_cenario_teste(1)
        self.assertEqual(c1["modo"], "1_camera")
        self.assertEqual(camera_manager.fontes_olhar_disponiveis(), ["tela", "camera_notebook", "maos"])
        f1, nota1 = camera_manager.resolver_fonte_camera("camera_quarto")
        self.assertEqual(f1, "camera_notebook")
        self.assertTrue(len(nota1) > 0)

        # 2 câmeras
        c2 = camera_manager.forcar_cenario_teste(2)
        self.assertEqual(c2["modo"], "2_cameras")
        self.assertIn("camera_porta", camera_manager.fontes_olhar_disponiveis())
        f2, _ = camera_manager.resolver_fonte_camera("camera_quarto")
        self.assertEqual(f2, "camera_porta")

        # 3+ câmeras com PTZ
        c3 = camera_manager.forcar_cenario_teste(3)
        self.assertEqual(c3["modo"], "3_cameras_ptz")
        self.assertTrue(camera_manager.tem_camera_ptz())
        f3, nota3 = camera_manager.resolver_fonte_camera("camera_quarto")
        self.assertEqual(f3, "camera_quarto")
        self.assertEqual(nota3, "")

    # =========================================================================
    # 6. PROVEDORES DE IA (GEMINI, CLAUDE, OPENAI, OLLAMA, AUTO + FALLBACK DE ERRO)
    # =========================================================================
    def test_09_cloud_providers_fallback_on_network_failure(self):
        """Testa se o modo 'auto' cai automaticamente para o Ollama local caso a nuvem falhe."""
        fake_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

        def mock_http_fail_cloud(url, headers, body):
            if "generativelanguage.googleapis.com" in url:
                raise RuntimeError("Simulated Cloud Rate Limit 429")
            if "/api/generate" in url:
                return {"response": "Fallback Local Ollama acionado com sucesso após erro na nuvem."}
            if "/api/chat" in url:
                return {"message": {"role": "assistant", "content": "Cérebro Local acionado após falha cloud.", "tool_calls": []}}
            raise RuntimeError(f"Unexpected URL: {url}")

        cloud_providers.set_mock_http(mock_http_fail_cloud)
        memoria_zero.atualizar_config({
            "ia": {
                "provedor_visao": "auto",
                "provedor_cerebro": "auto",
                "gemini_api_key": "key-present-but-failing",
                "claude_api_key": "",
                "openai_api_key": "",
            }
        })
        res_v = visao.consultar_vlm(fake_jpg, "O que vê?")
        self.assertIn("Fallback Local Ollama acionado com sucesso", res_v)

        res_c = cerebro._chat([{"role": "user", "content": "Olá"}], cerebro.ferramentas())
        self.assertIn("Cérebro Local acionado", res_c["message"]["content"])

    # =========================================================================
    # 7. MEMÓRIA ZERO-STATE, DEDUPLICAÇÃO E APRENDIZADO CONTÍNUO
    # =========================================================================
    def test_10_memory_deduplication_and_formatting(self):
        """Garante que lições aprendidas idênticas ou muito similares são deduplicadas e salvas corretamente."""
        memoria_zero.registrar_licao_aprendida("tocar música", "abriu navegador manual", "usar ferramenta tocar_midia")
        memoria_zero.registrar_licao_aprendida("tocar música", "abriu navegador manual", "usar ferramenta tocar_midia")
        st = memoria_zero.status_memoria()
        self.assertEqual(st["licoes_aprendidas"], 1)

        with open(os.path.join(ROOT_DIR, "memory", "licoes.json"), encoding="utf-8") as fh:
            licoes = json.load(fh)
        self.assertEqual(len(licoes), 1)
        self.assertIn("usar ferramenta tocar_midia", licoes[0]["txt"])

        # Receita episódica registrada e contabilizada
        ok_ep = memoria_zero.registrar_episodio_aprendido(
            "pesquise no youtube a musica sequencia de homem de ferro",
            ["tocar_midia {\"termo\":\"sequencia de homem de ferro\"} -> ok"],
            "Coloquei Sequência de Homem de Ferro para tocar."
        )
        self.assertTrue(ok_ep)
        self.assertEqual(memoria_zero.status_memoria()["episodios_aprendidos"], 1)

    # =========================================================================
    # 8. MESH SYNC P2P MULTI-DISPOSITIVO (CONFLICT RESOLUTION & CONVERSATIONS)
    # =========================================================================
    def test_11_mesh_sync_conflict_resolution_last_write_wins(self):
        """Verifica que na sincronização entre nós, o fato com timestamp mais recente vence."""
        t_old = time.time() - 500
        t_new = time.time() + 500

        # Grava fato local antigo
        memoria.gravar("usuario", "cidade", "São Paulo", t=t_old)
        deltas_remotos = {
            "agenda": [{"id": "rem1", "titulo": "Deploy Integra Code", "inicio": t_new + 3600, "mod": t_new}],
            "fatos": [{"tipo": "usuario", "chave": "cidade", "resumo": "Curitiba", "visto_1": t_old, "visto_ult": t_new, "vezes": 3}],
            "licoes": [{"txt": "Verificar foco da janela antes de digitar", "t": t_new}],
            "conversas": [{"ts": t_new, "de": "usuario", "txt": "Oi da estação Windows"}],
        }
        sync_mesh.obter_mesh().aplicar_deltas(deltas_remotos)

        achados = memoria.buscar("Curitiba", 5)
        self.assertTrue(any("Curitiba" in s for _, _, s in achados))

    # =========================================================================
    # 9. CENTRAL DE CONFIGURAÇÃO WEB E INTEGRA CODE TERMS
    # =========================================================================
    def test_12_web_config_center_integra_code_terms_and_deps(self):
        """Testa se a interface Web (/config) e o endpoint (/api/config/status) exibem Termos Integra Code e Auto-Deps."""
        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            import remoto
            app = remoto.criar_app({"estado": lambda: {"on": True}})
            async with TestClient(TestServer(app)) as client:
                r_html = await client.get("/config")
                self.assertEqual(r_html.status, 200)
                html = await r_html.text()
                self.assertIn("Integra Code", html)
                self.assertIn("NÃO retém", html)

                r_st = await client.get("/api/config/status")
                self.assertEqual(r_st.status, 200)
                data = await r_st.json()
                self.assertIn("privacidade", data)
                self.assertEqual(data["privacidade"]["organizacao"], "Integra Code")
                self.assertFalse(data["privacidade"]["retencao_dados_integracode"])
                self.assertIn("dependencias", data)
                self.assertTrue(data["dependencias"]["ok"])

        asyncio.run(_run())

    # =========================================================================
    # 10. PESQUISA NO NAVEGADOR (PC E ANDROID): MULTI-LOJAS, FOLLOW-UPS E LINKS
    # =========================================================================
    def test_13_browser_and_mobile_search_fixes(self):
        """Testa URLs de busca no navegador (Google, eBay, Amazon, Mercado Livre, US), follow-ups e correções no Android."""
        import agent as A

        # 1. Multi-loja e limpeza de termos no PC
        urls1, termo1 = A._urls_para_site_ou_busca(
            busca="sexta feira, abra o navegador e pesquise por linhas de cosmeticos Wella em sites americanos como ebay e amazon global e me mostre oque achar",
            contexto_lojas="ebay e amazon global"
        )
        self.assertEqual(termo1, "linhas de cosmeticos Wella")
        self.assertTrue(any("ebay.com" in u for u in urls1))
        self.assertTrue(any("amazon.com" in u for u in urls1))

        urls2, termo2 = A._urls_para_site_ou_busca(busca="procure em sites americanos Wella Oil Reflections", contexto_lojas="sites americanos")
        self.assertEqual(termo2, "Wella Oil Reflections")
        self.assertTrue(any("gl=us" in u for u in urls2))

        # 2. Detecção de promessa de ação sem chamar ferramenta (_AFIRMA_ACAO)
        self.assertIsNotNone(cerebro._AFIRMA_ACAO.search("Vou abrir uma nova aba no navegador e pesquisar pelas linhas Wella."))
        self.assertIsNotNone(cerebro._AFIRMA_ACAO.search("Abrirei a busca agora."))

        # 3. Verificação do código Android (Cerebro.java, Ferramentas.java, MainActivity.java, app.js)
        with open(os.path.join(ROOT_DIR, "android", "src", "dev", "integra", "friday", "Cerebro.java"), encoding="utf-8") as fh:
            c_java = fh.read()
        self.assertIn("atalhoPesquisa", c_java)
        self.assertIn("ultimaBusca", c_java)
        self.assertIn("acao.equals(\"pesquisar\") || acao.equals(\"abrir_site\")", c_java)

        with open(os.path.join(ROOT_DIR, "android", "src", "dev", "integra", "friday", "Ferramentas.java"), encoding="utf-8") as fh:
            f_java = fh.read()
        self.assertIn("ebay.com/sch/i.html", f_java)
        self.assertIn("amazon.com/s?k=", f_java)
        self.assertIn("pesquisarLinks", f_java)

        with open(os.path.join(ROOT_DIR, "android", "assets", "app.js"), encoding="utf-8") as fh:
            app_js = fh.read()
        self.assertIn("function linkify", app_js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
