import QtQuick

// ==============================================================================
// F.R.I.D.A.Y. // MATRIZ HOLOGRÁFICA STARK HUD (IMAGEM 5)
// ------------------------------------------------------------------------------
// 1. Núcleo Holográfico 3D (Imagem colada (5).png):
//    - Núcleo central incandescente âmbar/dourado com íris de fusão quântica
//    - Filamentos e raios sinápticos radiantes conectando o centro aos anéis orbitais
//    - 3 anéis giroscópios contra-rotativos inclinados com réguas e arcos segmentados
//    - Enxame toroidal 3D com 220 nanopartículas e faíscas flutuantes em perspectiva
// 2. Três Câmeras Holográficas Reais Perfeitamente Enquadradas:
//    - CAM 01 // NATIVA [NOTEBOOK INTEGRADA · ROSTO & BIOMETRIA] -> /tmp/friday-cam.jpg
//    - CAM 02 // AMBIENTE [EXTERNA FIXA · VISÃO DE SALA & MESA] -> /tmp/friday-cam-amb.jpg
//    - CAM 03 // PTZ 360° [WIRELESS MOTORIZADA · SENTINELA & RASTREAMENTO] -> /tmp/friday-cam-ptz.jpg
// 3. Painel de Telemetria de Hardware (CPU, RAM, GPU, VRAM, Temperatura)
// 4. Vão inferior central de 500px 100% livre para o dock Noctalia
// ==============================================================================
Item {
    id: core

    // ---- propriedades recebidas do shell ----
    property real level: 0              // amplitude da fala (0..1)
    property string mode: "idle"        // idle | listening | thinking | speaking
    property bool exploded: false
    property color cGold: "#ffaa18"     // Dourado Stark
    property color cAmber: "#ff7000"    // Âmbar Radiante
    property color cBright: "#ffe680"   // Ouro Incandescente
    property color cHolo: "#00e5ff"     // Ciano Stark de suporte
    property color cGreen: "#10b981"    // Verde nominal
    property color cBgGlass: "#cc04080e"// Fundo vidro escuro translúcido

    property real cpu: 0
    property real ram: 0
    property real gpu: 0
    property real vram: 0
    property int temp: 0
    property bool online: true
    property int pessoas: 0
    property int objetos: 0
    property string clock: ""
    property string date: ""
    property string alvo: ""
    property bool ptzOnline: false
    property bool usbOnline: true
    property bool natOnline: true
    property int camTick: 0
    property bool camOn: true
    property alias hit: hitArea

    // ---- estado interno de animação ----
    property var pts: []
    property var sparks: []
    property real burst: 0
    property real pulse: 0
    property real boot: 0
    property real ang: 0
    property real tiltX: 0
    property real tiltY: 0
    property real hover: 0
    property int shockTick: 0

    readonly property color cState: mode === "speaking" ? cBright : mode === "listening" ? "#60d5ff" : mode === "thinking" ? cAmber : cGold
    readonly property real fade: (1 - burst) * boot

    Behavior on burst { NumberAnimation { duration: core.exploded ? 600 : 1200; easing.type: Easing.InOutCubic } }
    Behavior on hover { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }

    function explode() { exploded = true; burst = 1 }
    function regroup() { exploded = false; burst = 0 }
    function shock() { shockTick++; wave.restart() }

    NumberAnimation on boot { from: 0; to: 1; duration: 1600; easing.type: Easing.OutCubic; running: true }

    // Inicialização da nuvem esférica 3D de nanopartículas (Imagem 5)
    Component.onCompleted: {
        const arr = []
        const count = 380
        for (let i = 0; i < count; i++) {
            // Distribuição esférica de Fibonacci com variações de raio e densidade
            const phi = Math.acos(1 - 2 * (i + 0.5) / count)
            const theta = Math.PI * (1 + Math.sqrt(5)) * i
            arr.push({
                lat: phi - Math.PI / 2,
                lon: theta,
                r: 0.35 + (i % 6) * 0.15 + Math.random() * 0.18,
                sp: 0.6 + (i % 7) * 0.16,
                sz: 1.5 + Math.random() * 2.8,
                bright: i % 4 === 0,
                ph: Math.random() * 6.28
            })
        }
        pts = arr

        // Centelhas que sobem suavemente
        const spk = []
        for (let j = 0; j < 60; j++) {
            spk.push({
                x: (Math.random() - 0.5) * 360,
                y: Math.random() * 300,
                sp: 0.8 + Math.random() * 1.5,
                sz: 1.2 + Math.random() * 2.2,
                ph: Math.random() * 6.28
            })
        }
        sparks = spk
    }

    // Loop de animação principal a 30 FPS econômico
    Timer {
        interval: 33
        running: core.visible
        repeat: true
        onTriggered: {
            const target = core.mode === "speaking" ? 0.40 + core.level * 1.3
                         : (core.mode === "listening" ? 0.26 : (core.mode === "thinking" ? 0.20 : 0.06))
            core.pulse += (target - core.pulse) * 0.26
            core.ang += 0.022
            if (!hitArea.containsMouse) {
                core.tiltX *= 0.92
                core.tiltY *= 0.92
            }
            coreCanvas.requestPaint()
        }
    }

    // =========================================================================
    // 1. BARRA SUPERIOR HOLOGRÁFICA (ALINHADA ABAIXO DA BARRA DO SISTEMA)
    // =========================================================================
    Rectangle {
        id: topBar
        x: 0; y: 40; width: parent.width; height: 36
        color: "#e802070d"
        border.color: "#66ffaa18"
        border.width: 1
        opacity: core.fade

        Row {
            anchors.left: parent.left; anchors.leftMargin: 24
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12

            Text { text: "◈"; color: core.cGold; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }

            Text {
                text: "STARK ARCHITECTURE // F.R.I.D.A.Y. NANO-CORE"
                color: "#ffffff"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 3
                anchors.verticalCenter: parent.verticalCenter
            }

            Rectangle {
                width: 64; height: 18; radius: 3
                color: "#28ffaa18"
                border.color: core.cGold; border.width: 1
                anchors.verticalCenter: parent.verticalCenter
                Text {
                    anchors.centerIn: parent
                    text: "+ ATIVO"
                    color: core.cGold; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1
                }
            }
        }

        // Título central
        Text {
            anchors.centerIn: parent
            text: "MATRIZ HOLOGRÁFICA TRÍPLICE [CAM 01 · CAM 02 · CAM 03] // NÚCLEO QUÂNTICO"
            color: "#ffe082"; font.pixelSize: 10; font.letterSpacing: 3; font.bold: true; opacity: 0.95
        }

        // Status à direita
        Row {
            anchors.right: parent.right; anchors.rightMargin: 48
            anchors.verticalCenter: parent.verticalCenter
            spacing: 14

            Text {
                text: "STARK SECURE // LEVEL 5"
                color: "#e2f1f8"; font.pixelSize: 10; font.letterSpacing: 2
                anchors.verticalCenter: parent.verticalCenter
            }

            Row {
                spacing: 4; anchors.verticalCenter: parent.verticalCenter
                Repeater {
                    model: 3
                    Rectangle { width: 6; height: 6; radius: 3; color: core.cGreen; opacity: 0.9 }
                }
            }

            Text {
                text: core.clock !== "" ? core.clock : Qt.formatTime(new Date(), "hh:mm:ss")
                color: core.cGold; font.pixelSize: 12; font.bold: true; font.family: "monospace"
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    // =========================================================================
    // 2. NÚCLEO HOLOGRÁFICO 3D CENTRAL (CANVAS BASEADO NA IMAGEM 5)
    // =========================================================================
    Canvas {
        id: coreCanvas
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative
        opacity: core.fade

        readonly property real cx: width / 2
        readonly property real cy: height * 0.48
        readonly property real baseR: Math.min(width, height) * 0.175

        onPaint: {
            const ctx = getContext("2d"); ctx.reset()
            const w = width, h = height
            if (w <= 10 || h <= 10) return

            const pulseAmp = core.pulse
            const R = baseR * (1.0 + pulseAmp * 0.22)
            const angRot = core.ang

            // 2.1 Scanlines sutis em tela cheia
            ctx.lineWidth = 1
            ctx.strokeStyle = "rgba(255, 170, 24, 0.024)"
            for (let y = 0; y < h; y += 14) {
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke()
            }

            // 2.2 Resplendor radial do Núcleo Dourado Âmbar (Imagem 5)
            const gR = R * (2.4 + pulseAmp * 0.6)
            const gA = 0.38 + pulseAmp * 0.45
            const rg = ctx.createRadialGradient(cx, cy, 0, cx, cy, gR)
            rg.addColorStop(0.0, "rgba(255, 255, 255, " + (gA * 0.95).toFixed(3) + ")")
            rg.addColorStop(0.12, "rgba(255, 230, 120, " + (gA * 0.85).toFixed(3) + ")")
            rg.addColorStop(0.35, "rgba(255, 160, 20, " + (gA * 0.50).toFixed(3) + ")")
            rg.addColorStop(0.65, "rgba(255, 90, 0, " + (gA * 0.18).toFixed(3) + ")")
            rg.addColorStop(1.0, "rgba(255, 70, 0, 0)")
            ctx.fillStyle = rg
            ctx.fillRect(cx - gR, cy - gR, gR * 2, gR * 2)

            // 2.3 Ondas de Choque eletromagnéticas na ativação
            if (wave.running) {
                const prog = wave.progress
                ctx.strokeStyle = Qt.rgba(1.0, 0.82, 0.25, (1 - prog) * 0.8)
                ctx.lineWidth = 2.5
                ctx.beginPath(); ctx.arc(cx, cy, R * (1 + prog * 4.5), 0, Math.PI * 2); ctx.stroke()
            }

            // 2.4 Anéis Giroscópios 3D Inclinados com Arcos Segmentados e Marcas
            const rings = [
                { tilt: 0.42, ecc: 0.38, sp: 0.85, rMul: 0.72, dash: [14, 8], color: "rgba(255, 230, 140, 0.85)" },
                { tilt: -0.55, ecc: 0.45, sp: -0.65, rMul: 1.05, dash: [24, 10, 8, 10], color: "rgba(255, 170, 24, 0.90)" },
                { tilt: 1.25, ecc: 0.55, sp: 0.40, rMul: 1.35, dash: [40, 16], color: "rgba(255, 110, 10, 0.65)" }
            ]

            for (let rIdx = 0; rIdx < rings.length; rIdx++) {
                const ring = rings[rIdx]
                const curA = ring.sp * angRot
                const ringR = R * ring.rMul
                ctx.save()
                ctx.translate(cx, cy)
                ctx.rotate(ring.tilt)
                ctx.scale(1.0, ring.ecc)

                ctx.lineWidth = rIdx === 1 ? 2.2 : 1.2
                ctx.strokeStyle = ring.color
                ctx.setLineDash(ring.dash)
                ctx.beginPath()
                ctx.arc(0, 0, ringR, 0, Math.PI * 2)
                ctx.stroke()
                ctx.setLineDash([])

                // Nós luminosos e marcadores angulares no anel
                for (let k = 0; k < 6; k++) {
                    const nodeAng = curA + (k * Math.PI / 3)
                    const nx = Math.cos(nodeAng) * ringR
                    const ny = Math.sin(nodeAng) * ringR
                    ctx.fillStyle = k === 0 ? "#ffffff" : "#ffaa18"
                    ctx.beginPath()
                    ctx.arc(nx, ny, k === 0 ? 3.5 : 2.0, 0, Math.PI * 2)
                    ctx.fill()
                }
                ctx.restore()
            }

            // 2.5 Raios / Filamentos Sinápticos Radiantes (Destaque da Imagem 5)
            // Feixes de energia pura ligando a íris central aos limites da esfera
            const numSpokes = 12
            for (let s = 0; s < numSpokes; s++) {
                const sAng = angRot * 0.25 + (s * Math.PI * 2 / numSpokes)
                const innerDist = R * 0.18
                const outerDist = R * (0.95 + 0.35 * Math.sin(sAng * 2 + angRot))
                const sx1 = cx + Math.cos(sAng) * innerDist
                const sy1 = cy + Math.sin(sAng) * innerDist
                const sx2 = cx + Math.cos(sAng) * outerDist
                const sy2 = cy + Math.sin(sAng) * outerDist

                // Linha principal de filamento
                const spokeGrad = ctx.createLinearGradient(sx1, sy1, sx2, sy2)
                spokeGrad.addColorStop(0.0, "rgba(255, 255, 255, 0.95)")
                spokeGrad.addColorStop(0.3, "rgba(255, 210, 80, 0.75)")
                spokeGrad.addColorStop(0.7, "rgba(255, 140, 20, 0.45)")
                spokeGrad.addColorStop(1.0, "rgba(255, 80, 0, 0.05)")

                ctx.lineWidth = (s % 3 === 0) ? 2.0 : 1.0
                ctx.strokeStyle = spokeGrad
                ctx.beginPath()
                ctx.moveTo(sx1, sy1)
                ctx.lineTo(sx2, sy2)
                ctx.stroke()

                // Conexões secundárias em bifurcação (estilo rede neural/sináptica)
                if (s % 2 === 0) {
                    const midX = (sx1 + sx2) * 0.5 + Math.cos(sAng + 0.5) * (R * 0.15)
                    const midY = (sy1 + sy2) * 0.5 + Math.sin(sAng + 0.5) * (R * 0.15)
                    ctx.lineWidth = 0.8
                    ctx.strokeStyle = "rgba(255, 190, 60, 0.35)"
                    ctx.beginPath()
                    ctx.moveTo(sx1, sy1)
                    ctx.lineTo(midX, midY)
                    ctx.lineTo(sx2, sy2)
                    ctx.stroke()
                }
            }

            // 2.6 Projeção 3D do Enxame Toroidal de Nanopartículas Douradas
            const ptsArr = core.pts
            const n = ptsArr.length
            const aX = 0.24 + core.tiltY * 0.20
            const aY = angRot * 0.32 + core.tiltX * 0.20
            const cosX = Math.cos(aX), sinX = Math.sin(aX)
            const cosY = Math.cos(aY), sinY = Math.sin(aY)
            const fov = 380

            // Vetor de partículas transformadas
            const projected = new Array(n)
            for (let i = 0; i < n; i++) {
                const p = ptsArr[i]
                const lon = p.lon + angRot * 0.18 * p.sp
                const pR = R * p.r * (1 + 0.15 * Math.sin(core.ang * 3 + p.ph))

                const x0 = Math.cos(p.lat) * Math.sin(lon) * pR
                const y0 = Math.sin(p.lat) * pR
                const z0 = Math.cos(p.lat) * Math.cos(lon) * pR

                // Rotação Y
                const x1 = x0 * cosY + z0 * sinY
                const z1 = -x0 * sinY + z0 * cosY

                // Rotação X
                const y2 = y0 * cosX - z1 * sinX
                const z2 = y0 * sinX + z1 * cosX

                // Perspectiva
                const scale = fov / (fov + z2 + R * 1.2)
                const px = cx + x1 * scale
                const py = cy + y2 * scale
                const alpha = Math.max(0.12, Math.min(1.0, (z2 + R) / (2 * R)))

                projected[i] = { x: px, y: py, z: z2, scale: scale, alpha: alpha, bright: p.bright, sz: p.sz }
            }

            // Ordena as partículas por profundidade (Z-sort)
            projected.sort((a, b) => a.z - b.z)

            // Conexões de plexo entre partículas vizinhas no espaço 3D
            const maxConnectDist = R * 0.32
            ctx.lineWidth = 0.8
            for (let i = 0; i < n; i += 3) {
                for (let j = i + 1; j < Math.min(i + 8, n); j++) {
                    const pi = projected[i]
                    const pj = projected[j]
                    const dx = pi.x - pj.x, dy = pi.y - pj.y
                    const d = Math.sqrt(dx * dx + dy * dy)
                    if (d < maxConnectDist) {
                        const cAlpha = (1 - d / maxConnectDist) * Math.min(pi.alpha, pj.alpha) * 0.45
                        ctx.strokeStyle = Qt.rgba(1.0, 0.72, 0.18, cAlpha)
                        ctx.beginPath()
                        ctx.moveTo(pi.x, pi.y)
                        ctx.lineTo(pj.x, pj.y)
                        ctx.stroke()
                    }
                }
            }

            // Desenha as nanopartículas
            for (let i = 0; i < n; i++) {
                const pt = projected[i]
                const finalSz = pt.sz * pt.scale * (1.0 + pulseAmp * 0.4)
                if (pt.bright) {
                    ctx.fillStyle = Qt.rgba(1.0, 0.98, 0.85, pt.alpha * 0.98)
                    ctx.fillRect(pt.x - finalSz * 0.6, pt.y - finalSz * 0.6, finalSz * 1.2, finalSz * 1.2)
                } else {
                    ctx.fillStyle = Qt.rgba(1.0, 0.65, 0.12, pt.alpha * 0.85)
                    ctx.fillRect(pt.x - finalSz / 2, pt.y - finalSz / 2, finalSz, finalSz)
                }
            }

            // 2.7 Íris Central e Anéis de Fusão Incandescentes (Imagem 5)
            // Núcleo branco puro de energia
            ctx.fillStyle = "#ffffff"
            ctx.beginPath()
            ctx.arc(cx, cy, 12 + pulseAmp * 6, 0, Math.PI * 2)
            ctx.fill()

            // Primeiro toroide incandescente dourado
            ctx.strokeStyle = "#ffe480"
            ctx.lineWidth = 3.5
            ctx.beginPath()
            ctx.arc(cx, cy, 22 + pulseAmp * 10, 0, Math.PI * 2)
            ctx.stroke()

            // Segundo toroide com microranhuras
            ctx.strokeStyle = "#ff9500"
            ctx.lineWidth = 2.0
            ctx.setLineDash([10, 6])
            ctx.beginPath()
            ctx.arc(cx, cy, 38 + pulseAmp * 14, angRot * 1.5, angRot * 1.5 + Math.PI * 2)
            ctx.stroke()
            ctx.setLineDash([])

            // Anel interno de contenção com marcadores
            ctx.strokeStyle = "rgba(255, 230, 140, 0.75)"
            ctx.lineWidth = 1.2
            ctx.beginPath()
            ctx.arc(cx, cy, 54 + pulseAmp * 18, 0, Math.PI * 2)
            ctx.stroke()
            for (let t_ = 0; t_ < 12; t_++) {
                const ta = (t_ * Math.PI / 6) + angRot * 0.5
                ctx.beginPath()
                ctx.moveTo(cx + Math.cos(ta) * (50 + pulseAmp * 18), cy + Math.sin(ta) * (50 + pulseAmp * 18))
                ctx.lineTo(cx + Math.cos(ta) * (58 + pulseAmp * 18), cy + Math.sin(ta) * (58 + pulseAmp * 18))
                ctx.stroke()
            }
        }
    }

    // Efeito de onda de choque disparado no clique
    Item {
        id: wave
        property real progress: 0
        property bool running: false
        function restart() { running = true; anim.restart() }
        NumberAnimation on progress {
            id: anim; from: 0; to: 1; duration: 600; easing.type: Easing.OutCubic
            onFinished: wave.running = false
        }
    }

    // =========================================================================
    // 3. TÍTULO E STATUS CENTRAL DO NÚCLEO HOLOGRÁFICO
    // =========================================================================
    Item {
        x: (parent.width - width) / 2
        y: parent.height * 0.48 + core.baseR * 1.36
        width: 380; height: 50
        opacity: core.fade

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: core.mode === "speaking" ? "F.R.I.D.A.Y.  ·  TRANSMITINDO VOZ"
                : core.mode === "listening" ? "F.R.I.D.A.Y.  ·  OUVINDO COMANDO"
                : core.mode === "thinking" ? "F.R.I.D.A.Y.  ·  PROCESSANDO DADOS"
                : "F.R.I.D.A.Y.  ·  NÚCLEO HOLOGRÁFICO ATIVO"
            color: "#ffffff"; font.pixelSize: 12; font.bold: true; font.letterSpacing: 4
        }

        // Régua decorativa inferior
        Rectangle {
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 24 }
            width: 220; height: 2; color: core.cGold
            Rectangle {
                width: 28; height: 4; radius: 2; color: "#ffffff"
                anchors.centerIn: parent
                SequentialAnimation on x {
                    loops: Animation.Infinite
                    NumberAnimation { from: -90; to: 90; duration: 2400; easing.type: Easing.InOutQuad }
                    NumberAnimation { from: 90; to: -90; duration: 2400; easing.type: Easing.InOutQuad }
                }
            }
        }
    }

    // =========================================================================
    // 4. TRÍPLICE VISÃO DE CÂMERAS HOLOGRÁFICAS (ENQUADRAMENTO FLANQUEADO)
    // -------------------------------------------------------------------------
    // Painel 1 (Esq. Topo):   CAM 01 // NATIVA [Webcam Frontal]
    // Painel 2 (Esq. Baixo):  CAM 02 // AMBIENTE [Câmera Fixa Sala]
    // Painel 3 (Dir. Topo):   CAM 03 // PTZ 360° [Motorizada IP]
    // Painel 4 (Dir. Baixo):  SISTEMA // TELEMETRIA [Hardware HUD]
    // =========================================================================

    // (Componente StarkCamCard carregado automaticamente de StarkCamCard.qml)


    // -------------------------------------------------------------------------
    // COLUNA ESQUERDA (CAM 01 & CAM 02)
    // -------------------------------------------------------------------------
    Item {
        id: leftCol
        x: 28; y: 92; width: 430; height: parent.height - 180
        opacity: core.fade

        // CAM 01 // NATIVA
        StarkCamCard {
            id: cam1Card
            x: 0; y: 0; width: parent.width; height: (parent.height - 20) / 2
            title: "CAM 01"
            sub: "NATIVA // ROSTO & BIOMETRIA"
            liveBadge: core.natOnline ? "LIVE // REC" : "OFFLINE"
            accentColor: core.cGold
            src: "file:///tmp/friday-cam.jpg?t=" + core.camTick
            footerL: "DISPOSITIVO: /dev/video0 · RES: 1280x720"
            footerR: "SENSOR: ROSTO IDENTIFICADO"
        }

        // CAM 02 // AMBIENTE
        StarkCamCard {
            id: cam2Card
            x: 0; y: (parent.height - 20) / 2 + 20; width: parent.width; height: (parent.height - 20) / 2
            title: "CAM 02"
            sub: "AMBIENTE // MESA & SALA"
            liveBadge: core.usbOnline ? "LIVE // WIDE" : "OFFLINE"
            accentColor: "#ffa228"
            src: "file:///tmp/friday-cam-amb.jpg?t=" + core.camTick
            footerL: "DISPOSITIVO: USB C270 · CAMPO AMPLO"
            footerR: "ILUMINAÇÃO: NOMINAL"
        }
    }

    // -------------------------------------------------------------------------
    // COLUNA DIREITA (CAM 03 & TELEMETRIA DO SISTEMA)
    // -------------------------------------------------------------------------
    Item {
        id: rightCol
        anchors.right: parent.right; anchors.rightMargin: 48
        y: 92; width: 430; height: parent.height - 180
        opacity: core.fade

        // CAM 03 // PTZ 360°
        StarkCamCard {
            id: cam3Card
            x: 0; y: 0; width: parent.width; height: (parent.height - 20) / 2
            title: "CAM 03"
            sub: "PTZ 360° // RASTREAMENTO IP"
            liveBadge: core.ptzOnline ? "MOTOR ATIVO // 360°" : "STANDBY"
            accentColor: core.cGold
            src: "file:///tmp/friday-cam-ptz.jpg?t=" + core.camTick
            footerL: "MOTOR: PAN/TILT AITEK ML-310"
            footerR: core.alvo !== "" ? "ALVO: " + core.alvo.toUpperCase() : "RASTREAMENTO ATIVO"
        }

        // PAINEL DE TELEMETRIA DO SISTEMA (HARDWARE HUD)
        Rectangle {
            id: sysCard
            x: 0; y: (parent.height - 20) / 2 + 20; width: parent.width; height: (parent.height - 20) / 2
            color: core.cBgGlass
            radius: 4
            border.color: Qt.rgba(core.cGold.r, core.cGold.g, core.cGold.b, 0.45)
            border.width: 1
            clip: true

            // Cabeçalho
            Rectangle {
                id: sysHead; x: 0; y: 0; width: parent.width; height: 26; color: "#e003080e"
                border.color: Qt.rgba(core.cGold.r, core.cGold.g, core.cGold.b, 0.3); border.width: 1

                Row {
                    anchors.left: parent.left; anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Rectangle { width: 6; height: 6; radius: 3; color: core.cGold; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "SISTEMA"; color: "#ffffff"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 2 }
                    Text { text: "TELEMETRIA DE RECURSOS & NÚCLEO"; color: core.cGold; font.pixelSize: 9; font.letterSpacing: 1 }
                }
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                    text: core.temp > 0 ? core.temp + "°C NOMINAL" : "48°C NOMINAL"
                    color: core.cBright; font.pixelSize: 9; font.family: "monospace"
                }
            }

            // Medidores de CPU, RAM, GPU, VRAM
            Column {
                anchors { top: sysHead.bottom; topMargin: 14; left: parent.left; leftMargin: 16; right: parent.right; rightMargin: 16 }
                spacing: 12

                Repeater {
                    model: [
                        { l: "CPU INTEL / THREADS", v: core.cpu, c: core.cGold },
                        { l: "MEMÓRIA RAM SISTEMA", v: core.ram, c: "#ffa228" },
                        { l: "GPU NANO-COMPUTE", v: core.gpu, c: "#ffd060" },
                        { l: "VRAM TEXTURAS / VLM", v: core.vram, c: core.cGold }
                    ]
                    Item {
                        width: parent.width; height: 24
                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 8
                            Text { text: "◈ " + modelData.l; color: "#b0d0e0"; font.pixelSize: 9; font.letterSpacing: 1 }
                        }
                        Text {
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            text: Math.round(modelData.v) + "%"
                            color: "#ffffff"; font.pixelSize: 10; font.bold: true; font.family: "monospace"
                        }
                        Rectangle {
                            y: 18; width: parent.width; height: 4; radius: 2; color: "#22ffffff"
                            Rectangle {
                                height: parent.height; radius: 2
                                width: parent.width * Math.min(1.0, Math.max(0.04, modelData.v / 100))
                                color: modelData.v > 85 ? "#ff5440" : modelData.c
                                Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
                            }
                        }
                    }
                }
            }

            // Rodapé do Sistema
            Rectangle {
                x: 0; anchors.bottom: parent.bottom; width: parent.width; height: 22; color: "#e003080e"
                border.color: Qt.rgba(core.cGold.r, core.cGold.g, core.cGold.b, 0.3); border.width: 1
                Text {
                    anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter
                    text: "VOZ: ALSA USB PnP · STT: WHISPER"; color: "#b0d0e0"; font.pixelSize: 8; font.family: "monospace"
                }
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                    text: "STATUS: 100% OPERACIONAL"; color: core.cGreen; font.pixelSize: 8; font.bold: true; font.family: "monospace"
                }
            }
        }
    }

    // =========================================================================
    // 5. INTERAÇÃO DO MOUSE COM O NÚCLEO HOLOGRÁFICO
    // =========================================================================
    MouseArea {
        id: hitArea
        anchors.fill: parent
        hoverEnabled: true
        onEntered: core.hover = 1
        onExited: core.hover = 0
        onPositionChanged: m => {
            core.tiltX = (m.x / width - 0.5) * 2
            core.tiltY = (m.y / height - 0.5) * 2
        }
        onClicked: core.shock()
    }
}
