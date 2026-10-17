import QtQuick
import QtMultimedia

// Holograma de alta performance do CELULAR: espelha a tela do aparelho ao vivo (H.264 -> mpegts) a 60 FPS.
// Moldura Stark Titanium (metal escuro, chanfro holográfico ciano/laranja, furo da câmera, botões laterais).
// Totalmente adaptativo: ajusta a proporção automaticamente para a resolução real do dispositivo sem distorção.
// Interativo: clique = toque, arrastar = deslizar, roda = rolar, barra inferior = voltar/início/recentes.
Item {
    id: holo

    // ---- entrada ----
    property string fonte: ""                 // ex.: tcp://127.0.0.1:8793
    property int vidW: 720
    property int vidH: 1600
    property bool ligado: true                // false -> anima a saída
    property string titulo: "CELULAR"

    signal tocar(real nx, real ny, int ms)
    signal arrastar(real nx0, real ny0, real nx1, real ny1)
    signal tecla(string nome)
    signal fechar()

    // ---- paleta Stark Cyberpunk ----
    readonly property color ciano: "#8fe9ff"
    readonly property color cianoForte: "#38bdf8"
    readonly property color laranja: "#ff8a1f"
    readonly property color verde: "#4ade80"
    readonly property color vidro: "#0b131b"

    // ---- geometria adaptativa (sem distorção) ----
    readonly property real topoH: 40
    readonly property real baseH: 64
    readonly property real ladoM: 10
    readonly property real corpoH: Math.max(260, height - topoH - baseH)

    // Detecta a proporção real do fluxo de vídeo automaticamente:
    readonly property real videoAspect: {
        if (vo.contentRect.height > 20 && vo.contentRect.width > 20) {
            return vo.contentRect.width / vo.contentRect.height
        }
        if (vidW > 0 && vidH > 0) {
            return vidW / vidH
        }
        return 9.0 / 20.0
    }

    readonly property real borda: Math.max(7, Math.round(corpoH * 0.012))
    readonly property real telaH: corpoH - 2 * borda
    readonly property real telaW: Math.round(telaH * videoAspect)
    readonly property real corpoW: telaW + 2 * borda
    readonly property real raio: Math.round(corpoW * 0.08)
    implicitWidth: corpoW + 2 * ladoM
    width: implicitWidth

    // ---- telemetria de FPS e conexão ----
    property int fps: 0
    property int quadros: 0
    property double ultimoQuadro: 0
    property double tentouEm: 0
    property bool semSinal: true
    property bool jaRecebeu: false
    property bool pronto: false

    function reiniciar() {
        if (!pronto) return
        tentouEm = Date.now()
        player.stop()
        player.source = ""
        if (fonte !== "" && ligado) {
            player.source = fonte
            player.play()
        }
    }
    onFonteChanged: reiniciar()
    onLigadoChanged: if (!ligado) player.stop(); else reiniciar()
    Component.onCompleted: { pronto = true; reiniciar() }

    // anel de toque holográfico na coordenada normalizada
    function toque(nx, ny) {
        const r = vo.contentRect.width > 0 ? vo.contentRect : Qt.rect(0, 0, tela.width, tela.height)
        anelComp.createObject(tela, { cx: r.x + nx * r.width, cy: r.y + ny * r.height })
    }

    // ---- animações suaves de entrada/saída ----
    property real aparecer: 0
    Behavior on aparecer { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
    Component.onDestruction: player.stop()
    Timer { interval: 16; running: true; onTriggered: holo.aparecer = Qt.binding(() => holo.ligado ? 1 : 0) }
    opacity: aparecer
    scale: 0.88 + 0.12 * aparecer
    transform: Rotation {
        origin.x: holo.width / 2; origin.y: holo.height / 2
        axis { x: 0.2; y: 1; z: 0 }
        angle: (1 - holo.aparecer) * -22
    }

    MediaPlayer {
        id: player
        videoOutput: vo
        playbackOptions.playbackIntent: PlaybackOptions.PlaybackIntent.LowLatencyStreaming
        playbackOptions.probeSize: 32768
        onErrorOccurred: (err, msg) => console.log("[celular] player:", msg)
    }

    // Monitoramento de quadros reais do VideoOutput (60 FPS direto)
    Connections {
        target: vo.videoSink
        function onVideoFrameChanged() {
            holo.quadros++
            holo.ultimoQuadro = Date.now()
            if (!holo.jaRecebeu) holo.jaRecebeu = true
            if (holo.semSinal) holo.semSinal = false
        }
    }
    Timer {
        interval: 1000; running: holo.visible; repeat: true
        onTriggered: { holo.fps = holo.quadros; holo.quadros = 0 }
    }
    Timer {
        interval: 350; running: holo.visible; repeat: true
        onTriggered: holo.semSinal = (Date.now() - holo.ultimoQuadro > 1800)
    }
    Timer {
        interval: 2000; running: holo.visible && holo.ligado && holo.fonte !== ""; repeat: true
        onTriggered: {
            const parado = player.playbackState !== MediaPlayer.PlayingState || player.error !== MediaPlayer.NoError
            const mudo = Date.now() - holo.ultimoQuadro > 3500 && Date.now() - holo.tentouEm > 4500
            if (parado || mudo) holo.reiniciar()
        }
    }

    // ================== CABEÇALHO HUD (Arrastar janela) ==================
    Item {
        id: topo
        x: holo.ladoM; width: holo.corpoW; height: holo.topoH - 6
        MouseArea { anchors.fill: parent; drag.target: holo; cursorShape: Qt.SizeAllCursor }

        Rectangle {
            anchors.bottom: parent.bottom; width: parent.width; height: 1
            color: holo.ciano; opacity: 0.4
        }
        Rectangle {
            anchors.bottom: parent.bottom; width: 48; height: 2.5
            color: holo.laranja
        }

        Row {
            anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Text {
                text: "◈"; color: holo.laranja; font.pixelSize: 13
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: holo.titulo; color: holo.ciano
                font.family: "monospace"; font.pixelSize: 12; font.bold: true; font.letterSpacing: 2
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: (vo.contentRect.width > 0 ? Math.round(vo.contentRect.width) : holo.vidW) + "×" + (vo.contentRect.height > 0 ? Math.round(vo.contentRect.height) : holo.vidH)
                color: holo.ciano; opacity: 0.65; font.family: "monospace"; font.pixelSize: 10
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        Row {
            anchors.right: fecharBt.left; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
            // Badge AO VIVO / RECONECTANDO
            Rectangle {
                width: seloTx.implicitWidth + 24; height: 18; radius: 3
                anchors.verticalCenter: parent.verticalCenter
                color: holo.semSinal ? "#40ef4444" : "#2010b981"
                border.width: 1; border.color: holo.semSinal ? "#ef4444" : holo.verde

                Rectangle {
                    x: 6; anchors.verticalCenter: parent.verticalCenter; width: 6; height: 6; radius: 3
                    color: holo.semSinal ? "#ef4444" : holo.verde
                    SequentialAnimation on opacity {
                        running: holo.visible; loops: Animation.Infinite
                        NumberAnimation { to: 0.25; duration: 550; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 550; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    id: seloTx; x: 17; anchors.verticalCenter: parent.verticalCenter
                    text: holo.semSinal ? "SEM SINAL" : "AO VIVO"
                    color: holo.semSinal ? "#fca5a5" : "#6ee7b7"
                    font.family: "monospace"; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.5
                }
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: holo.fps + " FPS"
                font.family: "monospace"; font.pixelSize: 11; font.bold: true
                color: holo.fps >= 50 ? holo.cianoForte : holo.fps >= 25 ? "#facc15" : "#f87171"
            }
        }

        // Botão Fechar ✕
        Rectangle {
            id: fecharBt
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: 22; height: 22; radius: 11
            color: fma.containsMouse ? "#66ef4444" : "#200f172a"
            border.width: 1; border.color: fma.containsMouse ? "#f87171" : holo.ciano

            Text {
                anchors.centerIn: parent; text: "✕"
                color: fma.containsMouse ? "#ffffff" : holo.ciano; font.pixelSize: 11; font.bold: true
            }
            MouseArea {
                id: fma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                onClicked: holo.fechar()
            }
        }
    }

    // ================== CORPO DO APARELHO ==================
    Item {
        id: aparelho
        x: holo.ladoM; y: holo.topoH; width: holo.corpoW; height: holo.corpoH

        // Aura Stark sutil (sem MultiEffect pesado para garantir 60 FPS estáveis)
        Rectangle {
            anchors.fill: parent; anchors.margins: -2; radius: holo.raio + 2
            color: "transparent"; border.width: 1.5; border.color: holo.cianoForte; opacity: 0.55
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: -5; radius: holo.raio + 5
            color: "transparent"; border.width: 1; border.color: holo.ciano; opacity: 0.2
        }

        // Botões físicos laterais (Volume à esquerda, Power à direita)
        component BotaoLado: Rectangle {
            width: 3.5; radius: 1.75
            color: "#334155"; border.width: 1; border.color: "#64748b"
        }
        BotaoLado { x: -3; y: parent.height * 0.18; height: parent.height * 0.08 }
        BotaoLado { x: -3; y: parent.height * 0.28; height: parent.height * 0.08 }
        BotaoLado { x: parent.width - 0.5; y: parent.height * 0.23; height: parent.height * 0.12 }

        // Chassi Titanium Escuro
        Rectangle {
            id: corpo
            anchors.fill: parent; radius: holo.raio
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#1e293b" }
                GradientStop { position: 0.1; color: "#0f172a" }
                GradientStop { position: 0.9; color: "#0f172a" }
                GradientStop { position: 1.0; color: "#1e293b" }
            }
            border.width: 1.5; border.color: "#475569"
        }

        // Chanfro metálico reflexivo
        Rectangle {
            anchors.fill: parent; anchors.margins: holo.borda * 0.4
            radius: Math.max(2, holo.raio - holo.borda * 0.4)
            color: "transparent"; border.width: 1; border.color: "#38bdf8"; opacity: 0.35
        }

        // Arrastar pela moldura move o aparelho
        MouseArea { anchors.fill: parent; drag.target: holo; cursorShape: Qt.SizeAllCursor }

        // ================== ÁREA DA TELA ==================
        Item {
            id: tela
            x: holo.borda; y: holo.borda; width: holo.telaW; height: holo.telaH
            readonly property real raioTela: Math.max(4, holo.raio - holo.borda)
            clip: true

            // Fundo escuro OLED
            Rectangle {
                anchors.fill: parent; radius: tela.raioTela; color: "#020617"
            }

            // Renderização direta do vídeo (Hardware-accelerated DMA-BUF/OpenGL)
            VideoOutput {
                id: vo
                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectFit
            }

            // Brilho de vidro Stark sutil
            Rectangle {
                anchors.fill: parent; opacity: 0.08
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#ffffff" }
                    GradientStop { position: 0.35; color: "transparent" }
                }
            }

            // Borda interna de contenção de luz
            Rectangle {
                anchors.fill: parent; radius: tela.raioTela
                color: "transparent"; border.width: 1; border.color: holo.ciano; opacity: 0.4
            }

            // Furo da câmera frontal (Punch-hole moderno)
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter; y: 7
                width: 12; height: 12; radius: 6
                color: "#000000"; border.width: 1.5; border.color: "#1e293b"
                Rectangle {
                    anchors.centerIn: parent; width: 5; height: 5; radius: 2.5
                    color: "#0c4a6e"
                }
            }

            // Painel SEM SINAL / CONECTANDO
            Rectangle {
                anchors.fill: parent; radius: tela.raioTela
                color: "#f0020617"; visible: opacity > 0.01; opacity: holo.semSinal ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 250 } }

                Column {
                    anchors.centerIn: parent; spacing: 14
                    Item {
                        width: 56; height: 56; anchors.horizontalCenter: parent.horizontalCenter
                        Rectangle {
                            anchors.fill: parent; radius: 28; color: "transparent"
                            border.width: 1.5; border.color: holo.ciano; opacity: 0.35
                        }
                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                const c = getContext("2d"); c.reset(); c.lineWidth = 3; c.lineCap = "round"
                                c.strokeStyle = "#ff8a1f"; c.beginPath(); c.arc(28, 28, 24, 0, Math.PI * 0.7); c.stroke()
                                c.strokeStyle = "#38bdf8"; c.beginPath(); c.arc(28, 28, 24, Math.PI, Math.PI * 1.6); c.stroke()
                            }
                            RotationAnimation on rotation {
                                running: holo.semSinal && holo.visible; loops: Animation.Infinite
                                from: 0; to: 360; duration: 1200
                            }
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "SEM SINAL"; color: "#f87171"
                        font.family: "monospace"; font.pixelSize: 14; font.bold: true; font.letterSpacing: 3
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: holo.jaRecebeu ? "RECONECTANDO AO APARELHO…" : "AGUARDANDO TRANSMISSÃO…"
                        color: holo.ciano; opacity: 0.75; font.family: "monospace"; font.pixelSize: 10; font.letterSpacing: 1.5
                    }
                }
            }

            // Interação: Toque, Arrasto, Rolagem
            Rectangle {
                id: rastro; visible: false; height: 3; radius: 1.5
                color: holo.laranja; opacity: 0.85; transformOrigin: Item.Left
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                property real x0: 0; property real y0: 0; property double t0: 0; property bool arrastando: false

                function nx(px) {
                    const r = vo.contentRect.width > 0 ? vo.contentRect : Qt.rect(0, 0, width, height)
                    return Math.max(0, Math.min(1, (px - r.x) / r.width))
                }
                function ny(py) {
                    const r = vo.contentRect.height > 0 ? vo.contentRect : Qt.rect(0, 0, width, height)
                    return Math.max(0, Math.min(1, (py - r.y) / r.height))
                }

                onPressed: m => { x0 = m.x; y0 = m.y; t0 = Date.now(); arrastando = false }
                onPositionChanged: m => {
                    if (!pressed) return
                    const dx = m.x - x0, dy = m.y - y0
                    if (!arrastando && Math.hypot(dx, dy) > 10) arrastando = true
                    if (arrastando) {
                        rastro.visible = true; rastro.x = x0; rastro.y = y0 - 1.5
                        rastro.width = Math.hypot(dx, dy); rastro.rotation = Math.atan2(dy, dx) * 180 / Math.PI
                    }
                }
                onReleased: m => {
                    rastro.visible = false
                    if (arrastando) holo.arrastar(nx(x0), ny(y0), nx(m.x), ny(m.y))
                    else {
                        holo.toque(nx(m.x), ny(m.y))
                        holo.tocar(nx(m.x), ny(m.y), Date.now() - t0)
                    }
                    arrastando = false
                }
                onCanceled: { rastro.visible = false; arrastando = false }

                // Roda de scroll para navegar suavemente
                property real acum: 0; property double ultimaRoda: 0
                onWheel: w => {
                    acum += w.angleDelta.y
                    if (Math.abs(acum) < 100 || Date.now() - ultimaRoda < 220) return
                    const px = nx(w.x), sobe = acum < 0
                    acum = 0; ultimaRoda = Date.now()
                    holo.arrastar(px, sobe ? 0.65 : 0.35, px, sobe ? 0.35 : 0.65)
                }
            }
        }

        // Cantoneiras Stark HUD nos quatro cantos do chassi
        component Canto: Item {
            property bool dir: false; property bool baixo: false
            width: 18; height: 18
            Rectangle {
                x: parent.dir ? parent.width - 18 : 0; y: parent.baixo ? 16 : 0
                width: 18; height: 2; color: holo.laranja
            }
            Rectangle {
                x: parent.dir ? 16 : 0; y: 0
                width: 2; height: 18; color: holo.laranja
            }
        }
        Canto { x: -8; y: -8 }
        Canto { x: parent.width - 10; y: -8; dir: true }
        Canto { x: -8; y: parent.height - 10; baixo: true }
        Canto { x: parent.width - 10; y: parent.height - 10; dir: true; baixo: true }
    }

    // ================== BARRA DE NAVEGAÇÃO HOLOGRÁFICA FLUTUANTE ==================
    component BotaoNav: Item {
        id: bn
        property string simbolo: ""
        property string nome: ""
        width: 60; height: 38
        Rectangle {
            anchors.centerIn: parent; width: 38; height: 38; radius: 19
            color: bnm.pressed ? "#50ff8a1f" : bnm.containsMouse ? "#2038bdf8" : "#100f172a"
            border.width: 1; border.color: bnm.containsMouse ? holo.laranja : "#4038bdf8"
            Behavior on color { ColorAnimation { duration: 100 } }
        }
        Text {
            anchors.centerIn: parent; text: bn.simbolo
            color: bnm.containsMouse ? "#ffd2a8" : holo.ciano; font.pixelSize: 17
        }
        MouseArea {
            id: bnm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
            onClicked: holo.tecla(bn.nome)
        }
    }

    Item {
        x: holo.ladoM; y: holo.topoH + holo.corpoH + 8
        width: holo.corpoW; height: holo.baseH - 12

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter; anchors.verticalCenter: parent.verticalCenter
            width: Math.min(parent.width, 240); height: 42; radius: 21
            color: "#e609121a"; border.width: 1; border.color: "#5038bdf8"
            MouseArea { anchors.fill: parent; drag.target: holo }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom
                width: 50; height: 2; color: holo.laranja; opacity: 0.9
            }
            Row {
                anchors.centerIn: parent; spacing: 8
                BotaoNav { simbolo: "◁"; nome: "voltar" }
                BotaoNav { simbolo: "○"; nome: "inicio" }
                BotaoNav { simbolo: "▢"; nome: "recentes" }
            }
        }
    }

    // Anel de Toque Animado
    Component {
        id: anelComp
        Item {
            id: anel
            property real cx: 0; property real cy: 0
            property real t: 0
            x: cx; y: cy
            Rectangle {
                anchors.centerIn: parent; width: 12 + 60 * anel.t; height: width; radius: width / 2
                color: "transparent"; border.width: 2.5; border.color: holo.laranja; opacity: 1 - anel.t
            }
            Rectangle {
                anchors.centerIn: parent; width: 12 + 30 * anel.t; height: width; radius: width / 2
                color: "#40ff8a1f"; border.width: 1; border.color: "#ffd2a8"; opacity: (1 - anel.t) * 0.85
            }
            NumberAnimation on t {
                from: 0; to: 1; duration: 480; easing.type: Easing.OutCubic; running: true
                onFinished: anel.destroy()
            }
        }
    }
}
