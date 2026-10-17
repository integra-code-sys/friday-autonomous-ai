import os
import sys
import unittest
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DAEMON_DIR = os.path.join(ROOT, "daemon")
if DAEMON_DIR not in sys.path:
    sys.path.insert(0, DAEMON_DIR)

import tela
import senses
import agent


class TestPerceptionSuite(unittest.TestCase):
    """Bateria de testes para reconhecimento de dificuldades na tela, emoções e gestos."""

    def test_01_detectar_dificuldades_tela(self):
        """Valida que erros críticos, exceções e stacktraces na tela são detectados com precisão."""
        # 1. Traceback Python
        tela_py_err = {"itens": [{"nome": "Terminal - bash"}, {"texto": "Traceback (most recent call last):\n  File \"run.py\", line 45\nTypeError: unsupported operand type"}]}
        d1 = tela.detectar_dificuldades(tela_py_err)
        self.assertTrue(d1["tem_dificuldade"])
        self.assertEqual(d1["severidade"], "alta")
        self.assertIn("Python", d1["tipo"])

        # 2. ModuleNotFoundError
        tela_mod = {"itens": [{"nome": "Console"}, {"texto": "ModuleNotFoundError: No module named 'scipy'"}]}
        d2 = tela.detectar_dificuldades(tela_mod)
        self.assertTrue(d2["tem_dificuldade"])
        self.assertIn("Módulo Python Ausente", d2["tipo"])

        # 3. Segfault
        tela_seg = {"itens": [{"nome": "App"}, {"texto": "Falha de segmentação (imagem do núcleo gravada)"}]}
        d3 = tela.detectar_dificuldades(tela_seg)
        self.assertTrue(d3["tem_dificuldade"])
        self.assertEqual(d3["severidade"], "alta")

        # 4. Tela normal sem erro
        tela_ok = {"itens": [{"nome": "Editor"}, {"texto": "def soma(a, b):\n    return a + b"}]}
        d4 = tela.detectar_dificuldades(tela_ok)
        self.assertFalse(d4["tem_dificuldade"])
        self.assertEqual(d4["severidade"], "baixa")

    def test_02_reconhecer_gestos_expandidos(self):
        """Valida o classificador geométrico hand_pose para gestos novos e clássicos."""
        # Base da mão: punho em (100, 100), base do médio em (100, 50) -> palm = 50
        def criar_mao():
            lm = np.zeros((21, 2))
            lm[0] = [100.0, 100.0]
            lm[9] = [100.0, 50.0]
            # Nós bases
            lm[5] = [80.0, 60.0]
            lm[17] = [120.0, 60.0]
            return lm

        # 1. Joinha (polegar para cima e dedos dobrados)
        m_up = criar_mao()
        m_up[4] = [70.0, 30.0]
        m_up[3] = [75.0, 60.0]
        # Dedos dobrados próximos do punho
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            m_up[tip] = [100.0, 95.0]
            m_up[pip] = [100.0, 90.0]
        self.assertEqual(senses.hand_pose(m_up), "joinha")

        # 2. Polegar para baixo (desaprovação/cancelar)
        m_down = criar_mao()
        m_down[4] = [70.0, 130.0] # y bem maior que y do punho (100)
        m_down[3] = [75.0, 110.0]
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            m_down[tip] = [100.0, 95.0]
            m_down[pip] = [100.0, 90.0]
        self.assertEqual(senses.hand_pose(m_down), "polegar_baixo")

        # 3. Pare / Palma aberta
        m_pare = criar_mao()
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            m_pare[tip] = [100.0, 20.0] # pontas bem estendidas para cima
            m_pare[pip] = [100.0, 60.0]
        m_pare[4] = [50.0, 40.0]
        m_pare[3] = [60.0, 60.0]
        pose = senses.hand_pose(m_pare)
        self.assertIn(pose, ("pare", "aberta"))

        # 4. Paz (indicador e médio estendidos)
        m_paz = criar_mao()
        m_paz[8] = [90.0, 20.0]; m_paz[6] = [90.0, 50.0]   # indicador estendido
        m_paz[12] = [110.0, 20.0]; m_paz[10] = [110.0, 50.0] # médio estendido
        m_paz[16] = [100.0, 95.0]; m_paz[14] = [100.0, 90.0] # anelar dobrado
        m_paz[20] = [100.0, 95.0]; m_paz[18] = [100.0, 90.0] # mínimo dobrado
        self.assertEqual(senses.hand_pose(m_paz), "paz")

    def test_03_reconhecimento_emocao_facial(self):
        """Valida que metricas_rosto classifica estados emocionais a partir da geometria."""
        # Linha sintética do YuNet: x,y,w,h, olho_dir(4,5), olho_esq(6,7), nariz(8,9), boca_dir(10,11), boca_esq(12,13), score
        # d = 60 px entre olhos
        # Rosto neutro
        linha_neutro = [100, 100, 120, 120, 120, 130, 180, 130, 150, 160, 130, 190, 170, 190, 0.95]
        estado = {}
        m_neutro = senses.metricas_rosto(linha_neutro, estado, W=320, H=240)
        self.assertIsNotNone(m_neutro)
        self.assertIn("emocao", m_neutro)
        self.assertIn("conf_emocao", m_neutro)
        self.assertIn("postura", m_neutro)

        # Rosto com boca bem alargada (sorriso largo)
        # boca_dir x=115, boca_esq x=185 -> boca=70 px, r=70/60=1.16
        linha_sorriso = [100, 100, 120, 120, 120, 130, 180, 130, 150, 160, 115, 185, 185, 185, 0.95]
        m_feliz = senses.metricas_rosto(linha_sorriso, estado, W=320, H=240, agora=100.0)
        self.assertIsNotNone(m_feliz)
        self.assertTrue(m_feliz["sorriso"] > 0.3)
        self.assertEqual(m_feliz["emocao"], "feliz")

    def test_04_ferramentas_agente_percepcao(self):
        """Valida a execução das novas ferramentas de percepção situacional no agent.py."""
        # 1. Dificuldade na tela
        r1 = agent.t_analisar_dificuldade_tela()
        self.assertIsInstance(r1, str)
        self.assertGreater(len(r1), 5)

        # 2. Emoção
        r2 = agent.t_reconhecer_emocao()
        self.assertIsInstance(r2, str)
        self.assertIn("EMOÇÃO", r2.upper())

        # 3. Gestos
        r3 = agent.t_reconhecer_gestos()
        self.assertIsInstance(r3, str)
        self.assertIn("GESTO", r3.upper())

        # 4. Percepção situacional completa
        r4 = agent.t_percepcao_situacional()
        self.assertIn("[TELA", r4)
        self.assertIn("[USUÁRIO", r4)
        self.assertIn("[GESTOS", r4)
        self.assertIn("[SISTEMA", r4)


if __name__ == "__main__":
    unittest.main()
