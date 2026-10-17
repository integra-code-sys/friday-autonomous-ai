import QtQuick

// F.R.I.D.A.Y. — NANOFORJA (AGLOMERADO CANÔNICO DE ALTA DENSIDADE)
// Enxame de nanotecnologia pura estilo Stark / F.R.I.D.A.Y. (sem rosto humano):
// - Núcleo de fusão 3D com 240 nanopartículas ligadas por filamentos de energia quântica
// - 3 anéis orbitais contra-rotativos inclinados com 200 nanorobôs em nuvem toroidal
// - 100 micro-faíscas e centelhas energéticas flutuantes
// - 4 anéis de contenção de arco com telemetria angular, réguas e marcadores
// - Reação total à voz (level 0..1), audição, processamento e estado de repouso
// - Explosão de partículas e choque eletromagnético para formar telas e janelas holográficas
Item {
    id: sw

    // ---- API Pública ----
    property real level: 0                  // amplitude da voz (0..1)
    property string mode: "idle"            // idle | listening | thinking | speaking
    property string humor: "neutro"         // humor/estado
    property real lookX: 0                  // foco do olhar / cursor (-1..1)
    property real lookY: 0
    property real coreX: width / 2
    property real coreY: height / 2
    property real radius: Math.min(width, height) * 0.14
    property string phase: "core"           // core | forming | screen | hold | reveal | release
    property string kind: "holo"            // app | holo
    property rect target: Qt.rect(0, 0, 0, 0)
    property string label: ""
    readonly property real progress: _prog
    property real _prog: 0
    readonly property bool cobreTela: kind === "app" && (phase === "forming" || phase === "hold" || phase === "reveal")

    signal formed()
    signal released()
    signal revealed()

    // Configuração do Enxame
    readonly property int nCore: 240        // partículas do núcleo 3D (filamentos)
    readonly property int nOrbit: 200       // partículas nas órbitas toroidais
    readonly property int nSparks: 100      // centelhas flutuantes
    readonly property int nTotal: nCore + nOrbit + nSparks // 540 partículas
    readonly property int cols: 28
    readonly property int rows: 16

    property var pts: []
    property real pulse: 0
    property double t0: 0
    property double tRev: 0
    property double tRel: 0
    property bool _emitted: false
    property real shock: 0                  // onda de choque ao explodir/formar

    // Paleta Holográfica Stark F.R.I.D.A.Y. (Âmbar Solar / Ouro Quântico - Imagem 5)
    property color cHolo: "#ff9f1c"         // âmbar dourado radiante
    property color cHoloBright: "#ffe082"   // ouro luminoso de alta energia
    property color cHot: "#ff5400"          // laranja fogo Stark de destaque
    property color cWhite: "#fff9e6"        // branco incandescente do núcleo

    function _now() { return Date.now() / 1000 }

    function formApp(r, nome) {
        kind = "app"
        label = nome || ""
        _start(r)
    }

    function formHolo(r, nome) {
        kind = "holo"
        label = nome || ""
        _start(r)
    }

    function _start(r) {
        target = r
        phase = "forming"
        t0 = _now()
        _emitted = false
        shock = 0
        shockAnim.restart()
        const cx = r.x + r.width / 2, cy = r.y + r.height / 2
        const maxd = Math.hypot(r.width / 2, r.height / 2) || 1
        for (let i = 0; i < pts.length; i++) {
            const p = pts[i]
            const c = i % cols, rw = Math.floor(i / cols) % rows
            p.tx = r.x + (c + 0.5) * r.width / cols
            p.ty = r.y + (rw + 0.5) * r.height / rows
            const dn = Math.hypot(p.tx - cx, p.ty - cy) / maxd
            p.delay = dn * 0.75 + Math.random() * 0.20
            p.arc = (Math.random() * 2 - 1) * (kind === "app" ? 220 : 130)
        }
    }

    function revelar() {
        if (phase === "reveal") return
        phase = "reveal"
        tRev = _now()
        const r = target
        for (let i = 0; i < pts.length; i++) {
            const p = pts[i]
            p.vx = (Math.random() * 2 - 1) * 120
            p.vy = (Math.random() * 2 - 1) * 120
        }
        revealed()
    }

    function release() {
        if (phase === "core" || phase === "release") return
        phase = "release"
        tRel = _now()
        const r = target, cx = r.x + r.width / 2, cy = r.y + r.height / 2
        const maxd = Math.hypot(r.width / 2, r.height / 2) || 1
        for (let i = 0; i < pts.length; i++) {
            const p = pts[i]
            p.delay = (1 - Math.hypot(p.tx - cx, p.ty - cy) / maxd) * 0.45 + Math.random() * 0.15
        }
    }

    readonly property real flight: 0.55
    readonly property real formTime: 0.75 + flight

    NumberAnimation {
        id: shockAnim
        target: sw
        property: "shock"
        from: 0
        to: 1
        duration: 900
        easing.type: Easing.OutCubic
    }

    Component.onCompleted: {
        const a = []
        for (let i = 0; i < nTotal; i++) {
            const u = Math.random() * 2 - 1
            const th = Math.random() * Math.PI * 2
            const r = Math.cbrt(Math.random())
            const s = Math.sqrt(Math.max(0, 1 - u * u))
            a.push({
                x: s * Math.cos(th) * r,
                y: u * r,
                z: s * Math.sin(th) * r,
                sp: 0.3 + Math.random() * 0.8,
                ph: Math.random() * 6.283,
                ring: i % 3,
                orb: 1.45 + Math.random() * 0.8,
                tx: 0, ty: 0,
                delay: 0, arc: 0,
                glint: Math.random() * 40,
                sz: 1.2 + Math.random() * 1.8,
                vx: 0, vy: 0
            })
        }
        pts = a
    }

    // Posição 3D da partícula no núcleo / órbitas
    function corePos(p, i, t) {
        const R = radius * (1 + pulse * 0.28)
        // Parallax do olhar / cursor
        const lx = lookX * 35, ly = lookY * 25

        if (i < nCore) {
            // Núcleo esférico interno rotativo com filamentos
            const ang = t * 0.32 * p.sp
            const ca = Math.cos(ang), sa = Math.sin(ang)
            const x = p.x * ca - p.z * sa
            const z = p.x * sa + p.z * ca
            const wob = 1 + pulse * 0.35 * Math.sin(t * 8 + p.ph)
            return [coreX + lx + x * R * wob, coreY + ly + p.y * R * wob, (z + 1) / 2]
        } else if (i < nCore + nOrbit) {
            // Órbitas toroidais elípticas inclinadas em 3 eixos
            const a = p.ph + t * p.sp * (p.ring === 1 ? -0.75 : 0.65)
            const tilt = [-0.55, 0.42, 1.35][p.ring]
            const ex = Math.cos(a) * R * p.orb * (1 + pulse * 0.25)
            const ey = Math.sin(a) * R * p.orb * 0.38
            const rx = ex * Math.cos(tilt) - ey * Math.sin(tilt)
            const ry = ex * Math.sin(tilt) + ey * Math.cos(tilt)
            return [coreX + lx * 1.2 + rx, coreY + ly * 1.2 + ry, (Math.sin(a) + 1) / 2]
        } else {
            // Centelhas que sobem suavemente e desaparecem
            const life = (t * 0.4 + p.ph) % 1.0
            const sx = Math.sin(t * 2 + p.ph) * R * 1.6
            const sy = -life * R * 2.8 + R * 0.5
            return [coreX + lx + sx, coreY + ly + sy, 1.0 - life]
        }
    }

    function perim(u, r) {
        const P = 2 * (r.width + r.height); let d = ((u % 1) + 1) % 1 * P
        if (d < r.width) return [r.x + d, r.y]; d -= r.width
        if (d < r.height) return [r.x + r.width, r.y + d]; d -= r.height
        if (d < r.width) return [r.x + r.width - d, r.y + r.height]; d -= r.width
        return [r.x, r.y + r.height - d]
    }

    function ease(s) { return 1 - Math.pow(1 - s, 3) }

    // Atualização de pulso e animação (30 FPS suave)
    Timer {
        interval: 33; running: sw.visible; repeat: true
        onTriggered: {
            const tg = sw.mode === "speaking" ? 0.35 + sw.level * 1.2
                     : (sw.mode === "listening" ? 0.25 : (sw.mode === "thinking" ? 0.20 : 0.06))
            sw.pulse += (tg - sw.pulse) * 0.32
            const T = sw._now() - sw.t0

            if (sw.phase === "forming") {
                sw._prog = Math.min(1, T / sw.formTime)
                if (T >= sw.formTime && !sw._emitted) {
                    sw._emitted = true
                    if (sw.kind === "holo") { sw.phase = "screen"; sw.t0 = sw._now() }
                    else if (sw.kind === "app") { sw.phase = "hold" }
                    sw.formed()
                }
            } else if (sw.phase === "reveal") {
                const Tr = sw._now() - sw.tRev
                if (Tr > 0.8) {
                    sw.phase = "core"; sw._prog = 0
                }
            } else if (sw.phase === "release") {
                const Trl = sw._now() - sw.tRel
                if (Trl > 0.9) {
                    sw.phase = "core"; sw._prog = 0; sw.released()
                }
            }
            cv.requestPaint()
        }
    }

    // 4 Anéis de Telemetria / Contenção de Arco Stark em volta do núcleo
    Repeater {
        model: 4
        Item {
            x: sw.coreX - width / 2; y: sw.coreY - height / 2
            width: sw.radius * (2.5 + index * 0.44) * (1 + sw.pulse * 0.08)
            height: width
            opacity: sw.phase === "core" ? (index === 3 ? 0.4 : 0.9) : (1.0 - sw._prog * 0.8)
            Behavior on opacity { NumberAnimation { duration: 400 } }
            NumberAnimation on rotation {
                from: 0; to: index % 2 ? -360 : 360
                duration: 16000 + index * 6000
                loops: Animation.Infinite
            }

            Rectangle {
                anchors.fill: parent; radius: width / 2; color: "transparent"
                border.width: index === 1 ? 2 : 1
                border.color: index === 1 ? sw.cHot : (index === 0 ? "#80ffffff" : "#60ffaa18")
            }

            // Balizas luminosas
            Rectangle {
                width: 6; height: 6; radius: 3; color: index === 1 ? "#ffffff" : sw.cHot
                x: parent.width / 2 - 3; y: -3
            }
            Rectangle {
                width: 20; height: 2; color: sw.cHot
                x: parent.width - 10; y: parent.height / 2 - 1
                visible: index === 0 || index === 2
            }

            // Marcas de bússola / régua no anel externo
            Repeater {
                model: index === 3 ? 48 : 0
                Rectangle {
                    width: 1; height: modelData % 6 === 0 ? 8 : 4
                    color: "#ffe082"; antialiasing: true
                    x: parent.width / 2 + Math.sin(modelData / 48 * 6.283) * parent.width / 2
                    y: parent.height / 2 - Math.cos(modelData / 48 * 6.283) * parent.height / 2
                    rotation: modelData / 48 * 360
                }
            }
        }
    }

    // Canvas de Renderização das Nanopartículas e Filamentos de Energia
    Canvas {
        id: cv
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative
        onPaint: {
            const ctx = getContext("2d"); ctx.reset()
            const t = sw._now(), ph = sw.phase, r = sw.target, N = sw.pts.length
            const T = t - sw.t0

            // Brilho radial central (respira com a amplitude da voz)
            const gR = sw.radius * (2.1 + sw.pulse * 0.8)
            const gA = ph === "core" ? 0.28 + sw.pulse * 0.42 : 0.08
            const rg = ctx.createRadialGradient(sw.coreX, sw.coreY, 0, sw.coreX, sw.coreY, gR)
            rg.addColorStop(0, Qt.rgba(1.0, 0.72, 0.15, gA * 1.2))
            rg.addColorStop(0.35, Qt.rgba(1.0, 0.52, 0.08, gA * 0.65))
            rg.addColorStop(0.7, Qt.rgba(1.0, 0.35, 0.02, gA * 0.2))
            rg.addColorStop(1, Qt.rgba(1.0, 0.35, 0.0, 0))
            ctx.fillStyle = rg
            ctx.fillRect(sw.coreX - gR, sw.coreY - gR, gR * 2, gR * 2)

            // Onda de choque ao iniciar formação
            if (sw.shock > 0 && sw.shock < 1) {
                ctx.strokeStyle = Qt.rgba(1.0, 0.82, 0.25, (1 - sw.shock) * 0.85)
                ctx.lineWidth = 2.5
                ctx.beginPath(); ctx.arc(sw.coreX, sw.coreY, sw.radius * (1 + sw.shock * 6.5), 0, 6.283); ctx.stroke()
                ctx.strokeStyle = Qt.rgba(1.0, 0.45, 0.05, (1 - sw.shock) * 0.6)
                ctx.lineWidth = 1.5
                ctx.beginPath(); ctx.arc(sw.coreX, sw.coreY, sw.radius * (1 + sw.shock * 4.5), 0, 6.283); ctx.stroke()
            }

            // Calcula posições das partículas
            const P = new Array(N)
            for (let i = 0; i < N; i++) {
                const p = sw.pts[i], c = sw.corePos(p, i, t)
                if (ph === "core") {
                    P[i] = [c[0], c[1], c[2], 0, 0]
                } else if (ph === "forming") {
                    const s = Math.max(0, Math.min(1, (T - p.delay) / sw.flight))
                    const e = sw.ease(s)
                    const nx = -(p.ty - c[1]), ny = p.tx - c[0]
                    const nl = Math.hypot(nx, ny) || 1
                    const bend = Math.sin(Math.PI * s) * p.arc
                    P[i] = [c[0] + (p.tx - c[0]) * e + nx / nl * bend,
                            c[1] + (p.ty - c[1]) * e + ny / nl * bend,
                            1.0, s, s >= 1 ? T - p.delay - sw.flight : -1]
                } else if (ph === "screen" || ph === "hold") {
                    const q = sw.perim(i / N + t * 0.02, r)
                    P[i] = [q[0], q[1], 1.0, 1.0, T + 10]
                } else if (ph === "reveal") {
                    const Tr = t - sw.tRev
                    P[i] = [p.tx + p.vx * Tr, p.ty + p.vy * Tr, 1.0, 1.0, -1]
                } else { // release
                    const s = Math.max(0, Math.min(1, (t - sw.tRel - p.delay) / 0.6))
                    const e = sw.ease(s)
                    P[i] = [p.tx + (c[0] - p.tx) * e, p.ty + (c[1] - p.ty) * e, c[2], 1 - s, -1]
                }
            }

            // Filamentos de Plexo Energético conectando as partículas no núcleo
            if (ph === "core" || ph === "release") {
                const maxD = sw.radius * 0.58
                ctx.lineWidth = 1
                for (let i = 0; i < sw.nCore; i += 2) {
                    for (let j = i + 1; j < sw.nCore; j += 2) {
                        const dx = P[i][0] - P[j][0], dy = P[i][1] - P[j][1]
                        if (Math.abs(dx) > maxD || Math.abs(dy) > maxD) continue
                        const d = Math.sqrt(dx * dx + dy * dy)
                        if (d < maxD) {
                            const alpha = (1 - d / maxD) * (0.28 + sw.pulse * 0.55)
                            ctx.strokeStyle = Qt.rgba(1.0, 0.72, 0.18, alpha)
                            ctx.beginPath()
                            ctx.moveTo(P[i][0], P[i][1])
                            ctx.lineTo(P[j][0], P[j][1])
                            ctx.stroke()
                        }
                    }
                }
            }

            // Desenha as nanopartículas com rastros em movimento
            for (let i = 0; i < N; i++) {
                const q = P[i]
                const moving = ph === "forming" && q[3] > 0 && q[3] < 1

                if (moving) {
                    // Rastro laser na trajetória curva
                    const p = sw.pts[i], c = sw.corePos(p, i, t), back = Math.max(0, q[3] - 0.14)
                    const e = sw.ease(back)
                    ctx.strokeStyle = Qt.rgba(1.0, 0.75, 0.18, 0.5)
                    ctx.lineWidth = 1.2
                    ctx.beginPath()
                    ctx.moveTo(c[0] + (p.tx - c[0]) * e, c[1] + (p.ty - c[1]) * e)
                    ctx.lineTo(q[0], q[1])
                    ctx.stroke()
                }

                const p = sw.pts[i]
                const sz = ph === "core" ? p.sz * (1.0 + q[2] * 0.8 + sw.pulse * 0.6) : (moving ? 3.0 : 2.0)
                const isHot = i % 14 === 0

                ctx.fillStyle = isHot ? Qt.rgba(1.0, 0.95, 0.70, 0.98)
                                      : Qt.rgba(1.0, 0.65, 0.12, ph === "core" ? 0.55 + q[2] * 0.45 : 0.9)
                ctx.fillRect(q[0] - sz / 2, q[1] - sz / 2, sz, sz)
            }
        }
    }

    // Rótulo de status Stark F.R.I.D.A.Y.
    Text {
        x: sw.coreX - width / 2; y: sw.coreY + sw.radius * 1.85
        opacity: sw.phase === "core" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 300 } }
        text: sw.mode === "speaking" ? "F.R.I.D.A.Y.  ·  FALANDO"
            : sw.mode === "listening" ? "F.R.I.D.A.Y.  ·  OUVINDO"
            : sw.mode === "thinking" ? "F.R.I.D.A.Y.  ·  PROCESSANDO"
            : "F.R.I.D.A.Y.  ·  SISTEMA ATIVO"
        color: "#ffffff"; font.pixelSize: 13; font.letterSpacing: 6; font.bold: true

        Rectangle {
            anchors { top: parent.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
            width: parent.width * 0.6; height: 2; color: sw.cHot
        }
    }

    // Telemetria da montagem holográfica
    Text {
        x: sw.target.x; y: sw.target.y - 24
        visible: sw.phase === "forming" || sw.phase === "screen" || sw.phase === "hold"
        text: (sw.phase === "forming" ? (sw.kind === "app" ? "◈ MATERIALIZANDO CAMADA HOLOGRÁFICA " : "◈ COMPILANDO TELA ") + Math.round(sw.progress * 100) + "%"
                                      : "◈ HOLOGRAMA ATIVO") + (sw.label ? "  ·  " + sw.label.toUpperCase() : "")
        color: "#00d2ff"; font.pixelSize: 11; font.letterSpacing: 3; font.family: "monospace"
    }
}
