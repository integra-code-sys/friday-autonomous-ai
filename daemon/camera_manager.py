"""Gerenciador Adaptativo de Câmeras (0, 1, 2 ou 3+ câmeras) — F.R.I.D.A.Y. Commercial Edition.

Adapta dinamicamente os sensores visuais, ferramentas do Cérebro e prompts para qualquer cenário de hardware:
- Cenário 0 ('sem_camera'): PC Desktop sem webcam -> Opera 100% com Visão de Tela + OCR + Áudio + Automação.
- Cenário 1 ('1_camera'): Notebook ou PC com 1 webcam -> Todas as consultas visuais de rosto/mãos/ambiente usam a câmera única; motor PTZ desativado.
- Cenário 2 ('2_cameras'): Webcam frontal + 1 câmera ambiente (USB ou IP) -> Mosaico duplo, sem exigir motor PTZ.
- Cenário 3 ('3_cameras_ptz'): Configuração completa (Frontal + Porta/Ambiente + Câmera PTZ Motorizada ONVIF/RTSP).
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import memoria_zero as MZ
import win_compat

_OVERRIDE_CENARIO = None  # Permite forçar cenário em testes automatizados (0, 1, 2, 3)


def forcar_cenario_teste(num_cameras=None):
    """Usado pelos testes de cenários para simular 0, 1, 2 ou 3 câmeras independentemente do hardware físico."""
    global _OVERRIDE_CENARIO
    _OVERRIDE_CENARIO = num_cameras
    return obter_cenario_cameras() if num_cameras is not None else None


def detectar_cameras_fisicas():
    """Detecta quantas e quais câmeras estão disponíveis no sistema (Linux V4L2, Windows DirectShow e RTSP)."""
    if _OVERRIDE_CENARIO is not None:
        if _OVERRIDE_CENARIO <= 0:
            return {"total": 0, "qtd_cameras": 0, "tem_ptz": False, "modo": "sem_camera", "principal": None, "secundaria": None, "ptz": None}
        if _OVERRIDE_CENARIO == 1:
            return {"total": 1, "qtd_cameras": 1, "tem_ptz": False, "modo": "1_camera", "principal": 0, "secundaria": None, "ptz": None}
        if _OVERRIDE_CENARIO == 2:
            return {"total": 2, "qtd_cameras": 2, "tem_ptz": False, "modo": "2_cameras", "principal": 0, "secundaria": 1, "ptz": None}
        return {"total": 3, "qtd_cameras": 3, "tem_ptz": True, "modo": "3_cameras_ptz", "principal": 0, "secundaria": 1, "ptz": "rtsp://mock/stream"}

    cfg = MZ.carregar_config().get("cameras", {})
    modo_cfg = cfg.get("modo", "auto")

    if modo_cfg == "sem_camera":
        return {"total": 0, "qtd_cameras": 0, "tem_ptz": False, "modo": "sem_camera", "principal": None, "secundaria": None, "ptz": None}

    dispositivos_locais = []
    if win_compat.IS_WINDOWS:
        # No Windows, testa índices DirectShow 0 e 1 rapidamente se configurado auto
        try:
            import cv2
            for idx in (0, 1):
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if cap is not None and cap.isOpened():
                    dispositivos_locais.append(idx)
                    cap.release()
        except Exception:
            pass
    else:
        por_id = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))
        if por_id:
            for p in por_id:
                dispositivos_locais.append(os.path.realpath(p))
        else:
            for d in ("/dev/video0", "/dev/video2", "/dev/video4"):
                if os.path.exists(d):
                    dispositivos_locais.append(d)

    ptz_rtsp = (cfg.get("camera_ptz_rtsp") or "").strip()
    ptz_ip = (cfg.get("camera_ptz_ip") or "").strip()
    tem_ptz = bool(ptz_rtsp or ptz_ip)

    principal = dispositivos_locais[0] if len(dispositivos_locais) >= 1 else None
    secundaria = dispositivos_locais[1] if len(dispositivos_locais) >= 2 else None
    ptz_fonte = ptz_rtsp or (f"http://{ptz_ip}" if ptz_ip else None)

    if modo_cfg == "1_camera":
        q = 1 if principal is not None else 0
        return {"total": q, "qtd_cameras": q, "tem_ptz": False, "modo": "1_camera", "principal": principal, "secundaria": None, "ptz": None}
    if modo_cfg == "2_cameras":
        return {"total": 2, "qtd_cameras": 2, "tem_ptz": False, "modo": "2_cameras", "principal": principal, "secundaria": secundaria, "ptz": None}
    if modo_cfg == "3_cameras_ptz":
        return {"total": 3, "qtd_cameras": 3, "tem_ptz": True, "modo": "3_cameras_ptz", "principal": principal, "secundaria": secundaria, "ptz": ptz_fonte}

    # Modo automático baseado no hardware real encontrado
    total = len(dispositivos_locais[:2]) + (1 if tem_ptz else 0)
    if total == 0:
        modo = "sem_camera"
    elif total == 1 and not tem_ptz:
        modo = "1_camera"
    elif total == 2 and not tem_ptz:
        modo = "2_cameras"
    else:
        modo = "3_cameras_ptz" if tem_ptz else f"{total}_cameras"

    return {
        "total": total,
        "qtd_cameras": total,
        "tem_ptz": bool(ptz_fonte) or modo == "3_cameras_ptz",
        "modo": modo,
        "principal": principal,
        "secundaria": secundaria,
        "ptz": ptz_fonte
    }


def obter_cenario_cameras():
    return detectar_cameras_fisicas()


def fontes_olhar_disponiveis():
    """Retorna a lista de fontes válidas para a ferramenta 'olhar' conforme o cenário atual de câmeras."""
    info = detectar_cameras_fisicas()
    total = info["total"]
    if total == 0:
        return ["tela"]
    if total == 1 and not info["ptz"]:
        return ["tela", "camera_notebook", "maos"]
    if total == 2 and not info["ptz"]:
        return ["tela", "camera_notebook", "camera_porta", "maos", "todas"]
    return ["tela", "camera_notebook", "camera_porta", "camera_quarto", "maos", "todas"]


def tem_camera_ptz():
    """Indica se há câmera PTZ motorizada configurada/disponível."""
    info = detectar_cameras_fisicas()
    return bool(info.get("ptz")) or info.get("modo") == "3_cameras_ptz"


def instrucao_cameras_prompt():
    """Gera a instrução específica sobre câmeras para o prompt do Cérebro de acordo com o hardware do usuário."""
    info = detectar_cameras_fisicas()
    modo = info["modo"]
    if modo == "sem_camera":
        return ("- Este computador está operando no modo SEM CÂMERAS FÍSICAS (0 câmeras). "
                "Para enxergar o que o usuário está fazendo no PC, use 'olhar' com fonte='tela'. "
                "Se o usuário pedir para ver algo pela webcam, explique gentilmente que nenhuma câmera física foi detectada.")
    if modo == "1_camera":
        return ("- Este computador possui 1 CÂMERA (webcam única). "
                "Use 'olhar' com fonte='camera_notebook' para ver o usuário/ambiente ou fonte='maos' para objetos nas mãos. "
                "Não há câmera motorizada PTZ nem câmera de porta separada.")
    if modo == "2_cameras":
        return ("- Este computador possui 2 CÂMERAS FIXAS ('camera_notebook' frontal e 'camera_porta' secundária/ambiente). "
                "Não há câmera motorizada com zoom/giro PTZ.")
    return ('- Câmeras: "camera_porta" e "camera_notebook" são FIXAS (localizam pessoas); '
            'a "camera_quarto" tem motor PTZ e zoom digital.')


def resolver_fonte_camera(fonte_pedida):
    """Mapeia qualquer fonte pedida pelo modelo para a câmera realmente existente no cenário do usuário.
    Retorna (fonte_resolvida, nota_informativa)."""
    info = detectar_cameras_fisicas()
    modo = info["modo"]
    if fonte_pedida == "tela":
        return "tela", ""
    if modo == "sem_camera":
        return "sem_camera", "Modo sem câmeras ativo: este dispositivo não possui câmeras conectadas."
    if modo == "1_camera":
        alvo = "maos" if fonte_pedida == "maos" else "camera_notebook"
        nota = f"Redirecionado de {fonte_pedida} para {alvo} (modo 1 câmera)" if fonte_pedida not in ("camera_notebook", "maos") else ""
        return alvo, nota
    if modo == "2_cameras":
        if fonte_pedida == "camera_quarto":
            return "camera_porta", "Redirecionado de camera_quarto para camera_porta (modo 2 câmeras sem PTZ)"
        return fonte_pedida, ""
    return fonte_pedida, ""
