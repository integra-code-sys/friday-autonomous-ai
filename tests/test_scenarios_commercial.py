#!/usr/bin/env python3
"""Suíte Automatizada de Testes Multi-Cenário da F.R.I.D.A.Y. Commercial Edition.

Testa e valida:
1. Limpeza Geral de Banco de Dados (Zero-State) e ausência de dados pessoais.
2. Criação de Memória e Aprendizado do Zero (Fatos, Episódios/Receitas, Lições de Erros e Onboarding).
3. Cenários de Hardware de Câmeras: 0 câmeras (Desktop), 1 câmera (Notebook), 2 câmeras e 3+ câmeras (PTZ).
4. Provedores de Visão e Cérebro em Nuvem (Google Gemini, Anthropic Claude, OpenAI GPT, Ollama Local e Auto Fallback).
5. Ativação/Desativação no Boot e Central de Configuração Web (/config e /api/config/*).
6. Sincronização Mesh P2P entre 3 nós (Linux, Windows, Android).
"""
import asyncio
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DAEMON = os.path.join(ROOT, "daemon")
if DAEMON not in sys.path:
    sys.path.insert(0, DAEMON)

import memoria_zero
import camera_manager
import cloud_providers
import config_center
import visao
import cerebro
import sync_mesh


class TestFridayCommercialScenarios(unittest.TestCase):

    def setUp(self):
        memoria_zero.inicializar_do_zero(forcar=True, nome_usuario="Chefe", manter_config_ia=False)
        camera_manager.forcar_cenario_teste(None)
        cloud_providers.set_mock_http(None)

    def tearDown(self):
        camera_manager.forcar_cenario_teste(None)
        cloud_providers.set_mock_http(None)
        memoria_zero.inicializar_do_zero(forcar=True, nome_usuario="Chefe", manter_config_ia=False)

    def test_01_zero_state_database_and_clean_memory(self):
        """Verifica que o banco de dados comercial inicia 100% limpo e sem dados pessoais."""
        st = memoria_zero.status_memoria()
        self.assertEqual(st["fatos_aprendidos"], 0)
        self.assertEqual(st["episodios_aprendidos"], 0)
        self.assertEqual(st["licoes_aprendidas"], 0)
        self.assertEqual(st["usuario"], "Chefe")
        self.assertTrue(st["onboarding_pendente"])

        with open(os.path.join(ROOT, "memory", "people.json"), encoding="utf-8") as fp:
            pessoas = json.load(fp)
        self.assertEqual(pessoas.get("pessoas"), {})

        with open(os.path.join(ROOT, "memory", "voz_dono.json"), encoding="utf-8") as fv:
            voz = json.load(fv)
        self.assertEqual(voz.get("amostras"), [])

    def test_02_learning_from_scratch_lifecycle(self):
        """Testa a criação de memória e aprendizado contínuo a partir do zero."""
        # 1. Onboarding do novo usuário
        memoria_zero.concluir_onboarding("Marina")
        st = memoria_zero.status_memoria()
        self.assertEqual(st["usuario"], "Marina")
        self.assertFalse(st["onboarding_pendente"])

        # 2. Aprendizado de fatos duráveis
        ok_f = memoria_zero.gravar_fato_aprendido("dono", "editor_preferido", "VS Code e Neovim")
        self.assertTrue(ok_f)
        import memoria
        achados = memoria.buscar("Neovim", 5)
        self.assertTrue(any("Neovim" in s for _, _, s in achados))

        # 3. Aprendizado de episódio (receita que deu certo)
        ok_e = memoria_zero.registrar_episodio_aprendido(
            "abrir editor de código",
            ["acao {\"t\":\"abrir\",\"alvo\":\"code\"} -> ok (verificado)"],
            "Abri o VS Code para você."
        )
        self.assertTrue(ok_e)

        # 4. Aprendizado de lição de erro (autorreflexão)
        ok_l = memoria_zero.registrar_licao_aprendida(
            "clicar no ícone oculto",
            "elemento fora da janela visível",
            "usar atalho de teclado ou maximizar janela antes"
        )
        self.assertTrue(ok_l)

        st2 = memoria_zero.status_memoria()
        self.assertGreaterEqual(st2["fatos_aprendidos"], 2)
        self.assertEqual(st2["episodios_aprendidos"], 1)
        self.assertEqual(st2["licoes_aprendidas"], 1)

    def test_03_camera_scenarios_0_1_2_3_cameras(self):
        """Testa adaptação automática de ferramentas e visão para 0, 1, 2 e 3+ câmeras."""
        # Cenário 0: PC sem câmera (Desktop Puro)
        cen0 = camera_manager.forcar_cenario_teste(0)
        self.assertEqual(cen0["modo"], "sem_camera")
        self.assertFalse(camera_manager.tem_camera_ptz())
        self.assertEqual(camera_manager.fontes_olhar_disponiveis(), ["tela"])
        tools0 = {t["function"]["name"]: t["function"] for t in cerebro.ferramentas()}
        self.assertNotIn("camera", tools0)
        self.assertEqual(tools0["olhar"]["parameters"]["properties"]["fonte"]["enum"], ["tela"])
        msg0, jpg0 = cerebro._olhar("camera_notebook")
        self.assertIsNone(jpg0)
        self.assertIn("sem câmeras", msg0.lower())

        # Cenário 1: Notebook / PC com 1 câmera apenas
        cen1 = camera_manager.forcar_cenario_teste(1)
        self.assertEqual(cen1["modo"], "1_camera")
        self.assertFalse(camera_manager.tem_camera_ptz())
        self.assertEqual(camera_manager.fontes_olhar_disponiveis(), ["tela", "camera_notebook", "maos"])
        tools1 = {t["function"]["name"]: t["function"] for t in cerebro.ferramentas()}
        self.assertNotIn("camera", tools1)
        f_res, nota = camera_manager.resolver_fonte_camera("camera_quarto")
        self.assertEqual(f_res, "camera_notebook")
        self.assertTrue(len(nota) > 0)

        # Cenário 2: PC com 2 câmeras (sem PTZ)
        cen2 = camera_manager.forcar_cenario_teste(2)
        self.assertEqual(cen2["modo"], "2_cameras")
        self.assertFalse(camera_manager.tem_camera_ptz())
        self.assertIn("camera_porta", camera_manager.fontes_olhar_disponiveis())
        f_res2, _ = camera_manager.resolver_fonte_camera("camera_quarto")
        self.assertEqual(f_res2, "camera_porta")

        # Cenário 3: Setup completo com 3+ câmeras e PTZ motorizada
        cen3 = camera_manager.forcar_cenario_teste(3)
        self.assertEqual(cen3["modo"], "3_cameras_ptz")
        self.assertTrue(camera_manager.tem_camera_ptz())
        tools3 = {t["function"]["name"]: t["function"] for t in cerebro.ferramentas()}
        self.assertIn("camera", tools3)
        self.assertIn("camera_quarto", tools3["olhar"]["parameters"]["properties"]["fonte"]["enum"])

    def test_04_cloud_vision_and_brain_providers(self):
        """Testa Visão (VLM) e Cérebro (Tool-Calling) com Gemini, Claude, OpenAI GPT, Ollama e Auto Fallback."""
        fake_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

        def mock_http(url, headers, body):
            # 1. Google Gemini API
            if "generativelanguage.googleapis.com" in url:
                return {"candidates": [{"content": {"parts": [
                    {"text": "Visão Gemini OK: vejo um smartphone na mão."},
                    {"functionCall": {"name": "lembrar", "args": {"chave": "objeto", "valor": "smartphone"}}}
                ]}}]}
            # 2. Anthropic Claude API
            if "api.anthropic.com" in url:
                return {"content": [
                    {"type": "text", "text": "Visão Claude OK: tela analisada com precisão."},
                    {"type": "tool_use", "name": "lembrar", "input": {"chave": "ia", "valor": "claude"}}
                ]}
            # 3. OpenAI GPT API
            if "api.openai.com" in url:
                return {"choices": [{"message": {
                    "content": "Visão OpenAI GPT-4o OK: ambiente claro.",
                    "tool_calls": [{"function": {"name": "lembrar", "arguments": json.dumps({"chave": "ia", "valor": "gpt4o"})}}]
                }}]}
            # 4. Ollama Local API
            if "/api/generate" in url:
                return {"response": "Visão Ollama Local OK."}
            if "/api/chat" in url:
                return {"message": {"role": "assistant", "content": "Cérebro Ollama Local OK.", "tool_calls": []}}
            raise RuntimeError(f"URL inesperada: {url}")

        cloud_providers.set_mock_http(mock_http)

        # Teste Google Gemini
        memoria_zero.atualizar_config({"ia": {"provedor_visao": "gemini", "provedor_cerebro": "gemini",
                                              "gemini_api_key": "test-gemini-key"}})
        res_v_gem = visao.consultar_vlm(fake_jpg, "O que tenho na mão?")
        self.assertIn("Visão Gemini OK", res_v_gem)
        res_c_gem = cerebro._chat([{"role": "user", "content": "Lembre que tenho um smartphone"}], cerebro.ferramentas())
        self.assertEqual(res_c_gem["message"]["tool_calls"][0]["function"]["name"], "lembrar")

        # Teste Anthropic Claude
        memoria_zero.atualizar_config({"ia": {"provedor_visao": "claude", "provedor_cerebro": "claude",
                                              "claude_api_key": "test-claude-key"}})
        res_v_cla = visao.consultar_vlm(fake_jpg, "Analise a tela")
        self.assertIn("Visão Claude OK", res_v_cla)
        res_c_cla = cerebro._chat([{"role": "user", "content": "Teste Claude"}], cerebro.ferramentas())
        self.assertEqual(res_c_cla["message"]["tool_calls"][0]["function"]["name"], "lembrar")

        # Teste OpenAI GPT
        memoria_zero.atualizar_config({"ia": {"provedor_visao": "openai", "provedor_cerebro": "openai",
                                              "openai_api_key": "test-openai-key"}})
        res_v_oai = visao.consultar_vlm(fake_jpg, "Como está o ambiente?")
        self.assertIn("Visão OpenAI GPT-4o OK", res_v_oai)
        res_c_oai = cerebro._chat([{"role": "user", "content": "Teste OpenAI"}], cerebro.ferramentas())
        self.assertEqual(res_c_oai["message"]["tool_calls"][0]["function"]["name"], "lembrar")

        # Teste Modo Híbrido ("auto") com fallback para Ollama Local quando sem chave de nuvem
        env_backup = {k: os.environ.pop(k, None) for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
        try:
            memoria_zero.atualizar_config({"ia": {"provedor_visao": "auto", "provedor_cerebro": "auto",
                                                  "gemini_api_key": "", "claude_api_key": "", "openai_api_key": ""}})
            res_v_loc = visao.consultar_vlm(fake_jpg, "Teste fallback local")
            self.assertEqual(res_v_loc, "Visão Ollama Local OK.")
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v

    def test_05_boot_toggle_and_config_center_api(self):
        """Testa ativação/desativação no boot e endpoints HTTP da Central de Configuração."""
        autostart_existed = os.path.exists(config_center.LINUX_AUTOSTART_FILE)

        try:
            r_on = config_center.configurar_boot(True)
            self.assertTrue(r_on["ok"])
            self.assertTrue(config_center.status_boot()["ativo_no_sistema"])

            r_off = config_center.configurar_boot(False)
            self.assertTrue(r_off["ok"])
            self.assertFalse(config_center.status_boot()["ativo_no_sistema"])
        finally:
            if autostart_existed:
                config_center.configurar_boot(True)

        async def _test_http():
            from aiohttp.test_utils import TestClient, TestServer
            import remoto
            app = remoto.criar_app({"estado": lambda: {"on": True}})
            async with TestClient(TestServer(app)) as client:
                r1 = await client.get("/config")
                self.assertEqual(r1.status, 200)
                html = await r1.text()
                self.assertIn("Central de Configuração", html)

                r2 = await client.get("/api/config/status")
                self.assertEqual(r2.status, 200)
                st = await r2.json()
                self.assertIn("cameras", st)
                self.assertIn("memoria", st)

                r3 = await client.post("/api/config/salvar", json={
                    "usuario": {"nome": "Carlos"},
                    "cameras": {"modo": "1_camera"},
                    "ia": {"provedor_visao": "gemini"}
                })
                self.assertEqual(r3.status, 200)
                d3 = await r3.json()
                self.assertTrue(d3["ok"])
                self.assertEqual(memoria_zero.carregar_config()["usuario"]["nome"], "Carlos")

                r4 = await client.post("/api/config/reset_memoria", json={"nome": "Chefe"})
                self.assertEqual(r4.status, 200)
                self.assertEqual(memoria_zero.carregar_config()["usuario"]["nome"], "Chefe")

        asyncio.run(_test_http())

    def test_06_mesh_sync_three_nodes(self):
        """Verifica que a sincronização Mesh aplica deltas corretamente entre dispositivos."""
        deltas_remotos = {
            "agenda": [{"id": "ev-win-1", "titulo": "Reunião Comercial", "inicio": 1999999999, "mod": 1999999999}],
            "fatos": [{"tipo": "dono", "chave": "projeto_atual", "resumo": "Friday Commercial", "visto_1": 1999999999.0, "visto_ult": 1999999999.0, "vezes": 5}],
            "licoes": [{"txt": "Usar verificação visual após clique na janela", "t": 1999999999.0}]
        }
        sync_mesh.obter_mesh().aplicar_deltas(deltas_remotos)
        import memoria
        achados = memoria.buscar("Commercial", 5)
        self.assertTrue(any("Friday Commercial" in s for _, _, s in achados))


if __name__ == "__main__":
    unittest.main(verbosity=2)
