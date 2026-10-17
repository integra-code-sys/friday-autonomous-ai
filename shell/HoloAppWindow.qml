import QtQuick

// F.R.I.D.A.Y. — Janela de Aplicativo 100% Holográfica em Partículas
// Camada de conversão visual com CONSTRUÇÃO GRADUAL autêntica de nanopartículas Stark.
//
// 1. ESTRUTURA FIEL DE APLICATIVO REAL:
//    - Barra de título holográfica completa: ícone Stark, título do app nativo, abas de navegação,
//      badges de segurança e controles de janela [ ─ ] [ □ ] [ ✕ ].
//    - Barra de status holográfica inferior com telemetria ao vivo.
//    - Cantoneiras e trilhos de laser reforçados Stark nos 4 cantos e bordas.
//
// 2. 100% FORMADA POR PARTÍCULAS:
//    - Enxame de mais de 400 nanopartículas ativas:
//      * Nanorobôs de perímetro correndo pelas bordas e trilhos com rastros de luz.
//      * Malha interna de partículas com filamentos quânticos dinâmicos que conectam nós da janela.
//      * Micro-faíscas quânticas flutuando verticalmente pelo interior do holograma.
//      * Partículas de construção que viajam do núcleo em arcos laser até formar o app.
//    - Paleta 100% monocromática azul/ciano elétrico (#00d2ff, #020e1c, #d6f6ff).
//
// 3. NAVEGAÇÃO LIVRE COM MOUSE E TECLADO:
//    - mask: Region {} na janela pai permite que 100% dos cliques, cursor e teclas
//      operem o aplicativo nativo por baixo sem nenhum bloqueio!
//    - Fundo translúcido preserva 100% da nitidez e legibilidade de textos e botões.
//
// 4. ALTERNÂNCIA POR VOZ:
//    - "mudar janela para a real" desativa o holograma instantaneamente.
//    - "modo holográfico" reconstrói a janela holográfica gradualmente.
Item {
    id: holoWin

    property real winX: 0
    property real winY: 0
    property real winW: 800
    property real winH: 600
    property string titulo: "APLICATIVO"
    property bool active: true
    property int snapTick: 0
    property real buildProgress: 0.0
    property string buildPhase: "idle" // idle | forming | stable | dissolving

    x: winX
    y: winY
    width: Math.max(100, winW)
    height: Math.max(100, winH)

    opacity: active ? 1.0 : 0.0
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: 400; easing.type: Easing.InOutQuad } }

    Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

    // Dimensões da estrutura de janela
    readonly property real barH: 34       // Barra de título do app
    readonly property real footH: 24      // Barra de status do app

    // Enxame de Nanopartículas Stark (Mais de 400 partículas em 4 grupos)
    readonly property int nPerim: 90      // Nanorobôs que percorrem a borda externa e trilhos
    readonly property int nGrid: 150      // Malha interna de filamentos quânticos
    readonly property int nSparks: 60     // Micro-faíscas flutuantes
    readonly property int nFly: 120       // Partículas de montagem em vôo laser
    readonly property int nTotal: nPerim + nGrid + nSparks + nFly
    property var pts: []

    function _now() { return Date.now() / 1000 }

    // Inicia a construção gradual da janela
    function startBuild() {
        buildPhase = "forming"
        buildProgress = 0.0
        buildAnim.restart()
        initParticles()
    }

    function initParticles() {
        const a = []
        const w = holoWin.width, h = holoWin.height

        // 1. Nanorobôs de perímetro e trilhos
        for (let i = 0; i < nPerim; i++) {
            a.push({
                kind: "perim",
                u: Math.random(),
                speed: 0.03 + Math.random() * 0.10,
                dir: Math.random() < 0.5 ? 1 : -1,
                rail: i % 4, // 0 = borda externa, 1 = barra de título, 2 = barra inferior, 3 = borda interna
                trail: []
            })
        }

        // 2. Malha interna de partículas com filamentos quânticos
        for (let i = 0; i < nGrid; i++) {
            a.push({
                kind: "grid",
                gx: 0.04 + Math.random() * 0.92,
                gy: (barH + 10 + Math.random() * (h - barH - footH - 20)) / Math.max(1, h),
                vx: (Math.random() - 0.5) * 0.015,
                vy: (Math.random() - 0.5) * 0.015,
                phase: Math.random() * 6.28,
                sz: 1.4 + Math.random() * 2.2,
                isAmber: i % 11 === 0
            })
        }

        // 3. Micro-faíscas flutuantes
        for (let i = 0; i < nSparks; i++) {
            a.push({
                kind: "spark",
                sx: Math.random(),
                sy: Math.random(),
                speed: 0.04 + Math.random() * 0.12,
                sz: 1.2 + Math.random() * 2.0,
                glint: Math.random() * 20
            })
        }

        // 4. Partículas em vôo de construção
        for (let i = 0; i < nFly; i++) {
            a.push({
                kind: "fly",
                originX: -holoWin.winX + 400 + (Math.random() * 120 - 60),
                originY: holoWin.height * 0.8 + (Math.random() * 160 - 80),
                targetX: Math.random() * w,
                targetY: Math.random() * h,
                arc: (Math.random() * 2 - 1) * 160,
                delay: Math.random() * 0.45,
                duration: 0.55 + Math.random() * 0.25
            })
        }

        pts = a
    }

    Component.onCompleted: {
        initParticles()
        if (active) startBuild()
    }

    onActiveChanged: {
        if (active) {
            startBuild()
        } else {
            buildPhase = "dissolving"
        }
    }

    onTituloChanged: {
        if (active && titulo !== "") startBuild()
    }

    onWidthChanged: {
        if (active && buildPhase === "stable") initParticles()
    }

    onHeightChanged: {
        if (active && buildPhase === "stable") initParticles()
    }

    NumberAnimation {
        id: buildAnim
        target: holoWin
        property: "buildProgress"
        from: 0.0
        to: 1.0
        duration: 2200
        easing.type: Easing.OutCubic
        onFinished: {
            if (holoWin.active) holoWin.buildPhase = "stable"
        }
    }

    // Calcula coordenadas de um ponto u (0..1) no perímetro da janela
    function perimPos(u, w, h) {
        const P = 2 * (w + h)
        let d = (((u % 1) + 1) % 1) * P
        if (d < w) return [d, 0]
        d -= w
        if (d < h) return [w, d]
        d -= h
        if (d < w) return [w - d, h]
        d -= h
        return [0, h - d]
    }

    function ease(s) { return 1 - Math.pow(1 - s, 3) }

    // =========================================================================
    // CAMADA 1: VÉU TRANSLÚCIDO E SCANLINES HOLOGRÁFICAS (App 100% legível por baixo)
    // =========================================================================
    Item {
        anchors.fill: parent

        // Tint azul holográfico translúcido sutil (não obstrui leitura nem botões do app nativo)
        Rectangle {
            anchors.fill: parent
            color: "#031224"
            opacity: 0.26 * holoWin.buildProgress
            radius: 6
        }

        // Linhas de varredura horizontais sutis (holographic scanlines)
        Repeater {
            model: Math.ceil(holoWin.height / 4)
            Rectangle {
                y: index * 4
                width: holoWin.width
                height: 1
                color: "#00d2ff"
                opacity: 0.05 * holoWin.buildProgress
            }
        }

        // Feixe vertical de varredura holográfica (sweep contínuo)
        Item {
            anchors.fill: parent
            clip: true
            opacity: holoWin.buildProgress > 0.4 ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 400 } }

            Rectangle {
                width: parent.width
                height: 90
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#0000d2ff" }
                    GradientStop { position: 0.5; color: "#2200d2ff" }
                    GradientStop { position: 1.0; color: "#0000d2ff" }
                }
                NumberAnimation on y {
                    from: -90
                    to: holoWin.height + 30
                    duration: 4200
                    loops: Animation.Infinite
                }
            }
        }
    }

    // =========================================================================
    // CAMADA 2: CANVAS DE NANOPARTÍCULAS STARK (Montagem, Malha e Filamentos)
    // =========================================================================
    Canvas {
        id: cv
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative

        Timer {
            interval: 33
            running: holoWin.visible
            repeat: true
            onTriggered: cv.requestPaint()
        }

        onPaint: {
            const ctx = getContext("2d"); ctx.reset()
            const w = holoWin.width, h = holoWin.height
            const prog = holoWin.buildProgress
            const t = holoWin._now()
            const forming = holoWin.buildPhase === "forming"
            const pts = holoWin.pts
            const N = pts ? pts.length : 0

            if (prog < 0.01 || N === 0) return

            // 1. Moldura e Feixe Laser de Tecelagem durante a montagem gradual
            if (forming) {
                const sweepY = prog * h
                const sg = ctx.createLinearGradient(0, sweepY - 32, 0, sweepY + 4)
                sg.addColorStop(0, Qt.rgba(0.0, 0.82, 1.0, 0))
                sg.addColorStop(0.8, Qt.rgba(0.0, 0.82, 1.0, 0.35))
                sg.addColorStop(1, Qt.rgba(0.9, 0.98, 1.0, 0.95))
                ctx.fillStyle = sg
                ctx.fillRect(0, sweepY - 32, w, 36)

                // Linha laser horizontal de ponta a ponta
                ctx.strokeStyle = Qt.rgba(0.9, 0.98, 1.0, 0.95)
                ctx.lineWidth = 2.2
                ctx.beginPath()
                ctx.moveTo(0, sweepY)
                ctx.lineTo(w, sweepY)
                ctx.stroke()
            }

            // 2. Borda externa luminosa e trilhos internos da janela
            const frameAlpha = Math.min(1.0, prog * 1.3)
            ctx.strokeStyle = Qt.rgba(0.0, 0.82, 1.0, 0.80 * frameAlpha)
            ctx.lineWidth = 1.5
            ctx.strokeRect(1, 1, w - 2, h - 2)

            // Divisor inferior da barra de título
            ctx.strokeStyle = Qt.rgba(0.0, 0.82, 1.0, 0.65 * frameAlpha)
            ctx.lineWidth = 1.2
            ctx.beginPath()
            ctx.moveTo(4, holoWin.barH)
            ctx.lineTo(w - 4, holoWin.barH)
            ctx.stroke()

            // Divisor superior do rodapé
            ctx.strokeStyle = Qt.rgba(0.0, 0.82, 1.0, 0.45 * frameAlpha)
            ctx.lineWidth = 1.0
            ctx.beginPath()
            ctx.moveTo(4, h - holoWin.footH)
            ctx.lineTo(w - 4, h - holoWin.footH)
            ctx.stroke()

            // 3. Renderização das Nanopartículas por Categoria
            const gridPts = []

            for (let i = 0; i < N; i++) {
                const p = pts[i]
                if (!p) continue

                if (p.kind === "perim") {
                    // Nanorobô que percorre a borda externa ou trilhos
                    const curU = (p.u + t * p.speed * p.dir) % 1.0
                    let px = 0, py = 0

                    if (p.rail === 0) {
                        // Perímetro externo
                        const pos = holoWin.perimPos(curU, w, h)
                        px = pos[0]; py = pos[1]
                    } else if (p.rail === 1) {
                        // Trilho da barra de título
                        px = (curU * w) % w
                        py = holoWin.barH
                    } else if (p.rail === 2) {
                        // Trilho do rodapé
                        px = ((1 - curU) * w) % w
                        py = h - holoWin.footH
                    } else {
                        // Perímetro interno
                        const pos = holoWin.perimPos(curU, w - 8, h - 8)
                        px = pos[0] + 4; py = pos[1] + 4
                    }

                    // Desenha o nanorobô com rastro luminoso
                    const alpha = 0.85 * frameAlpha
                    const isHot = i % 8 === 0

                    ctx.fillStyle = isHot ? Qt.rgba(1.0, 0.68, 0.15, alpha) : Qt.rgba(0.2, 0.9, 1.0, alpha)
                    ctx.beginPath()
                    ctx.arc(px, py, isHot ? 2.6 : 2.0, 0, Math.PI * 2)
                    ctx.fill()

                } else if (p.kind === "grid") {
                    // Malha de partículas do corpo do aplicativo
                    if (prog < 0.25) continue
                    const gridAlpha = Math.min(1.0, (prog - 0.25) / 0.75)

                    // Posição suave oscilante
                    const oscX = Math.sin(t * 1.4 + p.phase) * 6
                    const oscY = Math.cos(t * 1.2 + p.phase) * 6
                    const gx = (p.gx * w + oscX) % (w - 20) + 10
                    const gy = Math.max(holoWin.barH + 8, Math.min(h - holoWin.footH - 8, p.gy * h + oscY))

                    gridPts.push({ x: gx, y: gy, sz: p.sz, isAmber: p.isAmber })

                    // Desenha o nó quântico
                    const dotAlpha = (0.35 + 0.30 * Math.sin(t * 2 + p.phase)) * gridAlpha
                    ctx.fillStyle = p.isAmber ? Qt.rgba(1.0, 0.65, 0.15, dotAlpha * 0.9) : Qt.rgba(0.0, 0.85, 1.0, dotAlpha)
                    ctx.beginPath()
                    ctx.arc(gx, gy, p.sz / 2, 0, Math.PI * 2)
                    ctx.fill()

                } else if (p.kind === "spark") {
                    // Micro-faíscas flutuando verticalmente
                    if (prog < 0.35) continue
                    const sparkAlpha = Math.min(1.0, (prog - 0.35) / 0.65)
                    const life = (t * p.speed + p.sy) % 1.0
                    const sx = (p.sx * w + Math.sin(t * 1.5 + p.glint) * 14) % w
                    const sy = (h - holoWin.footH) - life * (h - holoWin.barH - holoWin.footH)

                    const a = Math.sin(life * Math.PI) * 0.40 * sparkAlpha
                    ctx.fillStyle = Qt.rgba(0.1, 0.88, 1.0, a)
                    ctx.beginPath()
                    ctx.arc(sx, sy, p.sz / 2, 0, Math.PI * 2)
                    ctx.fill()

                } else if (p.kind === "fly" && forming) {
                    // Partículas de montagem em vôo do núcleo até a janela
                    const s = Math.max(0, Math.min(1, (prog * 1.6 - p.delay) / p.duration))
                    if (s <= 0.01 || s >= 0.99) continue

                    const e = holoWin.ease(s)
                    const nx = -(p.targetY - p.originY)
                    const ny = p.targetX - p.originX
                    const nl = Math.hypot(nx, ny) || 1
                    const bend = Math.sin(Math.PI * s) * p.arc

                    const px = p.originX + (p.targetX - p.originX) * e + (nx / nl) * bend
                    const py = p.originY + (p.targetY - p.originY) * e + (ny / nl) * bend

                    // Rastro luminoso do feixe
                    const backE = holoWin.ease(Math.max(0, s - 0.14))
                    const bx = p.originX + (p.targetX - p.originX) * backE + (nx / nl) * (bend * 0.85)
                    const by = p.originY + (p.targetY - p.originY) * backE + (ny / nl) * (bend * 0.85)

                    ctx.strokeStyle = Qt.rgba(0.0, 0.88, 1.0, 0.40 * Math.sin(s * Math.PI))
                    ctx.lineWidth = 1.3
                    ctx.beginPath()
                    ctx.moveTo(bx, by)
                    ctx.lineTo(px, py)
                    ctx.stroke()

                    // Ponto da partícula
                    ctx.fillStyle = Qt.rgba(0.9, 0.98, 1.0, 0.95)
                    ctx.beginPath()
                    ctx.arc(px, py, 2.5, 0, Math.PI * 2)
                    ctx.fill()
                }
            }

            // 4. Filamentos quânticos interligando nós da malha interna
            const maxConnDist = 68
            const nG = gridPts.length
            ctx.lineWidth = 0.9

            for (let i = 0; i < nG; i += 2) {
                const p1 = gridPts[i]
                for (let j = i + 1; j < nG; j += 2) {
                    const p2 = gridPts[j]
                    const dx = p1.x - p2.x, dy = p1.y - p2.y
                    if (Math.abs(dx) > maxConnDist || Math.abs(dy) > maxConnDist) continue
                    const d = Math.hypot(dx, dy)
                    if (d < maxConnDist) {
                        const filamentAlpha = (1.0 - d / maxConnDist) * 0.20 * frameAlpha
                        ctx.strokeStyle = Qt.rgba(0.0, 0.85, 1.0, filamentAlpha)
                        ctx.beginPath()
                        ctx.moveTo(p1.x, p1.y)
                        ctx.lineTo(p2.x, p2.y)
                        ctx.stroke()
                    }
                }
            }
        }
    }

    // =========================================================================
    // CAMADA 3: ESTRUTURA REAL DE APLICATIVO STARK (Título, Abas, Controles e Rodapé)
    // =========================================================================
    Item {
        anchors.fill: parent

        // Brilho externo sutil azul nas bordas
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            color: "transparent"
            border.color: "#3300d2ff"
            border.width: 2.5
            radius: 7
            opacity: holoWin.buildProgress
        }

        // Cantoneiras reforçadas Stark nos 4 cantos da janela
        Repeater {
            model: [[0, 0, 1, 1], [1, 0, -1, 1], [0, 1, 1, -1], [1, 1, -1, -1]]
            Item {
                x: modelData[0] === 0 ? 0 : holoWin.width
                y: modelData[1] === 0 ? 0 : holoWin.height
                readonly property real armLen: 42 * Math.min(1.0, holoWin.buildProgress * 1.25)
                Rectangle {
                    x: modelData[2] > 0 ? 0 : -armLen
                    y: modelData[3] > 0 ? 0 : -2.5
                    width: armLen; height: 2.5; color: "#00d2ff"
                }
                Rectangle {
                    x: modelData[2] > 0 ? 0 : -2.5
                    y: modelData[3] > 0 ? 0 : -armLen
                    width: 2.5; height: armLen; color: "#00d2ff"
                }
                // Parafuso / nó quântico no vértice
                Rectangle {
                    x: modelData[2] > 0 ? 3 : -7
                    y: modelData[3] > 0 ? 3 : -7
                    width: 4; height: 4
                    color: "#ffffff"
                    radius: 1
                }
            }
        }

        // =====================================================================
        // BARRA DE TÍTULO DA JANELA DE APLICATIVO (Holographic Stark Titlebar)
        // =====================================================================
        Rectangle {
            x: 0; y: 0
            width: holoWin.width; height: holoWin.barH
            color: "#ee020e1c"
            opacity: holoWin.buildProgress > 0.25 ? 1.0 : holoWin.buildProgress / 0.25

            // Ícone e Título do Aplicativo Real
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                // Ícone Stark Reator Arc
                Rectangle {
                    width: 14; height: 14; radius: 7
                    color: "transparent"
                    border.color: "#00d2ff"; border.width: 1.5
                    anchors.verticalCenter: parent.verticalCenter
                    Rectangle {
                        anchors.centerIn: parent
                        width: 6; height: 6; radius: 3
                        color: "#00d2ff"
                    }
                }

                // Nome do Aplicativo
                Text {
                    text: holoWin.titulo.toUpperCase() + "  //  MATRIZ HOLOGRÁFICA"
                    color: "#e0f7ff"
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 1.5
                    font.family: "monospace"
                    anchors.verticalCenter: parent.verticalCenter
                }

                // Abas holográficas simuladas
                Rectangle {
                    height: 20
                    width: tabTxt.implicitWidth + 16
                    radius: 3
                    color: "#1a00d2ff"
                    border.color: "#4000d2ff"; border.width: 1
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        id: tabTxt
                        anchors.centerIn: parent
                        text: "◈ ATIVO"
                        color: "#7fe6ff"
                        font.pixelSize: 9
                        font.bold: true
                        font.family: "monospace"
                    }
                }
            }

            // Controles de Janela Holográficos [ ─ ] [ □ ] [ ✕ ] e Status à Direita
            Row {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 12

                // Badge de Conexão e Segurança Stark
                Text {
                    text: "STARK SECURE // LEVEL 5"
                    color: "#5fd8ff"
                    font.pixelSize: 9
                    font.letterSpacing: 1
                    font.family: "monospace"
                    anchors.verticalCenter: parent.verticalCenter
                }

                // Botão Minimizar [ ─ ]
                Rectangle {
                    width: 22; height: 18; radius: 2
                    color: "#1500d2ff"
                    border.color: "#4000d2ff"; border.width: 1
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent; text: "─"; color: "#7fe6ff"; font.pixelSize: 10 }
                }

                // Botão Maximizar [ □ ]
                Rectangle {
                    width: 22; height: 18; radius: 2
                    color: "#1500d2ff"
                    border.color: "#4000d2ff"; border.width: 1
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent; text: "□"; color: "#7fe6ff"; font.pixelSize: 10 }
                }

                // Botão Fechar [ ✕ ]
                Rectangle {
                    width: 22; height: 18; radius: 2
                    color: "#2500d2ff"
                    border.color: "#6000d2ff"; border.width: 1
                    anchors.verticalCenter: parent.verticalCenter
                    Text { anchors.centerIn: parent; text: "✕"; color: "#00d2ff"; font.pixelSize: 10; font.bold: true }
                }
            }
        }

        // =====================================================================
        // BARRA DE STATUS DO RODAPÉ (Holographic Stark Statusbar)
        // =====================================================================
        Rectangle {
            x: 0; y: holoWin.height - holoWin.footH
            width: holoWin.width; height: holoWin.footH
            color: "#ee020c18"
            opacity: holoWin.buildProgress > 0.35 ? 1.0 : holoWin.buildProgress / 0.35

            Row {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                Rectangle {
                    width: 6; height: 6; radius: 3; color: "#00d2ff"
                    anchors.verticalCenter: parent.verticalCenter
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        NumberAnimation { from: 1.0; to: 0.3; duration: 600 }
                        NumberAnimation { from: 0.3; to: 1.0; duration: 600 }
                    }
                }

                Text {
                    text: "◈ F.R.I.D.A.Y. MATRIZ HOLOGRÁFICA · DIGA \"MUDAR JANELA PARA A REAL\" PARA ALTERNAR"
                    color: "#7fe6ff"
                    font.pixelSize: 9
                    font.letterSpacing: 1
                    font.family: "monospace"
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Row {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 12

                Text {
                    text: "CURSOR & MOUSE 100% OPERACIONAIS · " + Math.round(holoWin.width) + "×" + Math.round(holoWin.height) + "px · NANOPARTÍCULAS " + holoWin.nTotal
                    color: "#5fd8ff"
                    font.pixelSize: 9
                    font.letterSpacing: 1
                    font.family: "monospace"
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        // =====================================================================
        // PAINEL CENTRAL DE TELEMETRIA DURANTE A CONSTRUÇÃO GRADUAL
        // =====================================================================
        Rectangle {
            anchors.centerIn: parent
            width: 480; height: 96
            radius: 8
            color: "#fa020e1c"
            border.color: "#00d2ff"
            border.width: 1.5
            visible: holoWin.buildPhase === "forming" && holoWin.buildProgress < 0.98
            opacity: holoWin.buildProgress < 0.85 ? 1.0 : (1.0 - holoWin.buildProgress) / 0.15

            Column {
                anchors.centerIn: parent
                spacing: 8

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8
                    Rectangle {
                        width: 8; height: 8; radius: 4; color: "#00d2ff"
                        anchors.verticalCenter: parent.verticalCenter
                        SequentialAnimation on opacity {
                            loops: Animation.Infinite
                            NumberAnimation { from: 1.0; to: 0.2; duration: 350 }
                            NumberAnimation { from: 0.2; to: 1.0; duration: 350 }
                        }
                    }
                    Text {
                        text: "◈ CONSTRUÇÃO HOLOGRÁFICA: " + Math.round(holoWin.buildProgress * 100) + "%"
                        color: "#e0f7ff"
                        font.pixelSize: 13
                        font.bold: true
                        font.letterSpacing: 2
                        font.family: "monospace"
                    }
                }

                // Barra de progresso da matriz
                Rectangle {
                    width: 420; height: 6; radius: 3; color: "#1a00d2ff"
                    anchors.horizontalCenter: parent.horizontalCenter
                    Rectangle {
                        width: parent.width * holoWin.buildProgress
                        height: parent.height
                        radius: 3
                        color: "#00d2ff"
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: holoWin.buildProgress < 0.35 ? "MATERIALIZANDO ENXAME DE NANOPARTÍCULAS..." :
                          holoWin.buildProgress < 0.70 ? "COMPILANDO MATRIZ ESTRUTURAL DA JANELA..." :
                                                         "SINCRONIZANDO PASSTHROUGH DE CURSOR E TECLADO..."
                    color: "#7fe6ff"
                    font.pixelSize: 9
                    font.letterSpacing: 1
                    font.family: "monospace"
                }
            }
        }
    }
}
