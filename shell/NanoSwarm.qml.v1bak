import QtQuick

// Nanotecnologia virtual da F.R.I.D.A.Y.: um enxame de nanopartículas.
//  core    : aglomerado (plexo 3D + órbitas) que pulsa com a voz
//  forming : cada nanopartícula voa até uma célula de uma grade e a "acende" -> a tela se monta peça por peça
//  screen  : (kind "holo") a tela fica formada: moldura viva, partículas correndo pela borda, varredura, brilhos de dados
//  release : as partículas voltam ao núcleo (a tela se desfaz célula por célula)
// formApp(rect)/formHolo(rect) iniciam a formação; formed() avisa quando a última célula acendeu.
Item {
    id: sw
    property real level: 0
    property string mode: "idle"            // idle | listening | thinking | speaking
    property real coreX: width / 2
    property real coreY: height / 2
    property real radius: Math.min(width, height) * 0.13
    property string phase: "core"           // core | forming | screen | release
    property string kind: "holo"            // app | holo
    property rect target: Qt.rect(0, 0, 0, 0)
    property string label: ""
    readonly property real progress: _prog
    property real _prog: 0
    signal formed()
    signal released()

    readonly property int cols: 24
    readonly property int rows: 15
    readonly property int nCore: 120        // as primeiras formam o plexo ligado por linhas; o resto orbita
    property var pts: []
    property real pulse: 0
    property double t0: 0
    property bool _emitted: false
    property real shock: 0                  // onda de choque ao começar a formar (0..1)

    property color cHolo: "#8fe9ff"
    property color cHot: "#ff8a1f"

    function _now() { return Date.now() / 1000 }
    function formApp(r, nome) { kind = "app"; label = nome || ""; _start(r) }
    function formHolo(r, nome) { kind = "holo"; label = nome || ""; _start(r) }
    function _start(r) {
        target = r; phase = "forming"; t0 = _now(); _emitted = false; shock = 0; shockAnim.restart()
        const cx = r.x + r.width / 2, cy = r.y + r.height / 2, maxd = Math.hypot(r.width / 2, r.height / 2)
        for (let i = 0; i < pts.length; i++) {
            const p = pts[i], c = i % cols, rw = Math.floor(i / cols)
            p.tx = r.x + (c + 0.5) * r.width / cols; p.ty = r.y + (rw + 0.5) * r.height / rows
            const dn = Math.hypot(p.tx - cx, p.ty - cy) / maxd
            p.delay = dn * 0.95 + Math.random() * 0.25          // de dentro para fora, com um pouco de acaso
            p.arc = (Math.random() * 2 - 1) * 120
        }
    }
    function release() {
        if (phase === "core" || phase === "release") return
        phase = "release"; t0 = _now()
        const r = target, cx = r.x + r.width / 2, cy = r.y + r.height / 2, maxd = Math.hypot(r.width / 2, r.height / 2)
        for (let i = 0; i < pts.length; i++) {
            const p = pts[i]
            p.delay = (1 - Math.hypot(p.tx - cx, p.ty - cy) / maxd) * 0.45 + Math.random() * 0.15   // de fora para dentro
        }
    }
    readonly property real flight: 0.55
    readonly property real formTime: 0.95 + 0.25 + flight

    NumberAnimation { id: shockAnim; target: sw; property: "shock"; from: 0; to: 1; duration: 900; easing.type: Easing.OutCubic }

    Component.onCompleted: {
        const a = []
        for (let i = 0; i < cols * rows; i++) {
            const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, r = Math.cbrt(Math.random()), s = Math.sqrt(1 - u * u)
            a.push({ x: s * Math.cos(th) * r, y: u * r, z: s * Math.sin(th) * r, sp: 0.2 + Math.random() * 0.6, ph: Math.random() * 6.283,
                     ring: i % 3, orb: 1.55 + Math.random() * 0.6, tx: 0, ty: 0, delay: 0, arc: 0, glint: Math.random() * 40 })
        }
        pts = a
    }

    function corePos(p, i, t) {
        const R = radius * (1 + pulse * 0.22)
        if (i < nCore) {
            const ang = t * 0.25 * p.sp, ca = Math.cos(ang), sa = Math.sin(ang)
            const x = p.x * ca - p.z * sa, z = p.x * sa + p.z * ca
            const wob = 1 + pulse * 0.35 * Math.sin(t * 9 + p.ph)
            return [coreX + x * R * wob, coreY + p.y * R * wob, (z + 1) / 2]
        }
        // órbitas inclinadas (3 anéis) — a "nuvem" de nanorobôs em volta do núcleo
        const a = p.ph + t * p.sp * (p.ring === 1 ? -0.7 : 0.55), tilt = [-0.45, 0.35, 1.25][p.ring]
        const ex = Math.cos(a) * R * p.orb * (1 + pulse * 0.25), ey = Math.sin(a) * R * p.orb * 0.32
        return [coreX + ex * Math.cos(tilt) - ey * Math.sin(tilt), coreY + ex * Math.sin(tilt) + ey * Math.cos(tilt), (Math.sin(a) + 1) / 2]
    }
    function perim(u, r) {          // ponto na borda do retângulo (u 0..1)
        const P = 2 * (r.width + r.height); let d = ((u % 1) + 1) % 1 * P
        if (d < r.width) return [r.x + d, r.y]; d -= r.width
        if (d < r.height) return [r.x + r.width, r.y + d]; d -= r.height
        if (d < r.width) return [r.x + r.width - d, r.y + r.height]; d -= r.width
        return [r.x, r.y + r.height - d]
    }
    function ease(s) { return 1 - Math.pow(1 - s, 3) }

    Timer {
        interval: 33; running: sw.visible; repeat: true
        onTriggered: {
            const tg = sw.mode === "speaking" ? 0.35 + sw.level * 1.1 : (sw.mode === "listening" ? 0.25 : (sw.mode === "thinking" ? 0.15 : 0.05))
            sw.pulse += (tg - sw.pulse) * 0.35
            const T = sw._now() - sw.t0
            if (sw.phase === "forming") {
                sw._prog = Math.min(1, T / sw.formTime)
                if (T >= sw.formTime && !sw._emitted) {
                    sw._emitted = true
                    if (sw.kind === "holo") { sw.phase = "screen"; sw.t0 = sw._now() }
                    sw.formed()
                }
            } else if (sw.phase === "release" && T > 0.6 + 0.6) {
                sw.phase = "core"; sw._prog = 0; sw.released()
            }
            cv.requestPaint()
        }
    }

    // anéis de interface ao redor do núcleo
    Repeater {
        model: 4
        Item {
            x: sw.coreX - width / 2; y: sw.coreY - height / 2
            width: sw.radius * (2.6 + index * 0.42) * (1 + sw.pulse * 0.08); height: width
            opacity: sw.phase === "core" ? (index === 3 ? 0.35 : 1) : 0
            Behavior on opacity { NumberAnimation { duration: 450 } }
            NumberAnimation on rotation { from: 0; to: index % 2 ? -360 : 360; duration: 18000 + index * 7000; loops: Animation.Infinite }
            Rectangle {
                anchors.fill: parent; radius: width / 2; color: "transparent"
                border.width: index === 1 ? 2 : 1
                border.color: index === 1 ? sw.cHot : (index === 0 ? "#88ffffff" : "#44ff8a1f")
            }
            Rectangle { width: 6; height: 6; radius: 3; color: index === 1 ? "#ffffff" : sw.cHot; x: parent.width / 2 - 3; y: -3 }
            Rectangle { width: 22; height: 2; color: sw.cHot; x: parent.width - 11; y: parent.height / 2 - 1; visible: index === 0 || index === 2 }
            Repeater {      // marcas de régua no anel externo
                model: index === 3 ? 48 : 0
                Rectangle {
                    width: 1; height: modelData % 6 === 0 ? 9 : 4; color: "#8fe9ff"; antialiasing: true
                    x: parent.width / 2 + Math.sin(modelData / 48 * 6.283) * parent.width / 2
                    y: parent.height / 2 - Math.cos(modelData / 48 * 6.283) * parent.height / 2
                    rotation: modelData / 48 * 360
                }
            }
        }
    }

    Canvas {
        id: cv
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative
        onPaint: {
            const ctx = getContext("2d"); ctx.reset()
            const t = sw._now(), T = t - sw.t0, ph = sw.phase, r = sw.target, N = sw.pts.length
            const cw = r.width / sw.cols, ch = r.height / sw.rows
            // brilho radial do núcleo (respira com a voz)
            const gR = sw.radius * (1.9 + sw.pulse * 0.7), gA = ph === "core" ? 0.22 + sw.pulse * 0.35 : 0.07
            const rg = ctx.createRadialGradient(sw.coreX, sw.coreY, 0, sw.coreX, sw.coreY, gR)
            rg.addColorStop(0, Qt.rgba(0.56, 0.91, 1, gA)); rg.addColorStop(0.45, Qt.rgba(0.56, 0.91, 1, gA * 0.35)); rg.addColorStop(1, Qt.rgba(0.56, 0.91, 1, 0))
            ctx.fillStyle = rg; ctx.fillRect(sw.coreX - gR, sw.coreY - gR, gR * 2, gR * 2)
            // onda de choque
            if (sw.shock > 0 && sw.shock < 1) {
                ctx.strokeStyle = Qt.rgba(0.56, 0.91, 1, (1 - sw.shock) * 0.8); ctx.lineWidth = 2
                ctx.beginPath(); ctx.arc(sw.coreX, sw.coreY, sw.radius * (1 + sw.shock * 6), 0, 6.283); ctx.stroke()
                ctx.strokeStyle = Qt.rgba(1, 0.54, 0.12, (1 - sw.shock) * 0.5); ctx.lineWidth = 1
                ctx.beginPath(); ctx.arc(sw.coreX, sw.coreY, sw.radius * (1 + sw.shock * 4.2), 0, 6.283); ctx.stroke()
            }
            const P = new Array(N)
            let lit = 0
            for (let i = 0; i < N; i++) {
                const p = sw.pts[i], c = sw.corePos(p, i, t)
                if (ph === "core") { P[i] = [c[0], c[1], c[2], 0, 0]; continue }
                if (ph === "forming") {
                    const s = Math.max(0, Math.min(1, (T - p.delay) / sw.flight)), e = sw.ease(s)
                    const nx = -(p.ty - c[1]), ny = p.tx - c[0], nl = Math.hypot(nx, ny) || 1, bend = Math.sin(Math.PI * s) * p.arc
                    P[i] = [c[0] + (p.tx - c[0]) * e + nx / nl * bend, c[1] + (p.ty - c[1]) * e + ny / nl * bend, 1, s, s >= 1 ? T - p.delay - sw.flight : -1]
                    if (s >= 1) lit++
                } else if (ph === "screen") {
                    const s = Math.min(1, T / 0.9), e = sw.ease(s), q = sw.perim(i / N + t * 0.018, r)
                    P[i] = [p.tx + (q[0] - p.tx) * e, p.ty + (q[1] - p.ty) * e, 1, 1, T + 10]
                } else {    // release
                    const s = Math.max(0, Math.min(1, (T - p.delay) / 0.6)), e = sw.ease(s)
                    const fx = sw.kind === "holo" ? sw.perim(i / N + t * 0.018, r) : [p.tx, p.ty]
                    P[i] = [fx[0] + (c[0] - fx[0]) * e, fx[1] + (c[1] - fx[1]) * e, c[2], 1 - s, s > 0 ? -1 : 99]
                }
            }
            // células acesas (a tela se montando peça por peça)
            if (ph !== "core") {
                for (let i = 0; i < N; i++) {
                    const p = sw.pts[i], age = P[i][4]
                    if (age < 0) continue
                    const flash = Math.exp(-age * 5)
                    let a
                    if (sw.kind === "app") a = ph === "release" ? 0 : 0.10 + 0.55 * flash
                    else a = (ph === "screen" ? 0.05 : 0.08) + 0.6 * flash
                    if (a < 0.01) continue
                    ctx.fillStyle = Qt.rgba(0.56 + flash * 0.4, 0.91 + flash * 0.09, 1, a)
                    ctx.fillRect(p.tx - cw / 2 + 1, p.ty - ch / 2 + 1, cw - 2, ch - 2)
                    if (flash > 0.2) {           // contorno quente no instante em que a célula acende
                        ctx.strokeStyle = Qt.rgba(1, 0.54, 0.12, flash * 0.9); ctx.lineWidth = 1
                        ctx.strokeRect(p.tx - cw / 2 + 0.5, p.ty - ch / 2 + 0.5, cw - 1, ch - 1)
                    }
                }
                // grade fina + moldura que vai se fechando com o progresso
                const prog = ph === "forming" ? lit / N : (ph === "release" ? Math.max(0, 1 - T / 0.9) : 1)
                ctx.strokeStyle = Qt.rgba(0.56, 0.91, 1, 0.10 * prog); ctx.lineWidth = 1
                ctx.beginPath()
                for (let c = 1; c < sw.cols; c++) { ctx.moveTo(r.x + c * cw, r.y); ctx.lineTo(r.x + c * cw, r.y + r.height) }
                for (let k = 1; k < sw.rows; k++) { ctx.moveTo(r.x, r.y + k * ch); ctx.lineTo(r.x + r.width, r.y + k * ch) }
                ctx.stroke()
                ctx.strokeStyle = Qt.rgba(0.56, 0.91, 1, 0.75 * prog); ctx.lineWidth = 1.5
                ctx.strokeRect(r.x, r.y, r.width, r.height)
                // cantoneiras laranja
                const L = 34 * prog
                ctx.strokeStyle = Qt.rgba(1, 0.54, 0.12, prog); ctx.lineWidth = 3
                ctx.beginPath()
                ctx.moveTo(r.x, r.y + L); ctx.lineTo(r.x, r.y); ctx.lineTo(r.x + L, r.y)
                ctx.moveTo(r.x + r.width - L, r.y); ctx.lineTo(r.x + r.width, r.y); ctx.lineTo(r.x + r.width, r.y + L)
                ctx.moveTo(r.x + r.width, r.y + r.height - L); ctx.lineTo(r.x + r.width, r.y + r.height); ctx.lineTo(r.x + r.width - L, r.y + r.height)
                ctx.moveTo(r.x + L, r.y + r.height); ctx.lineTo(r.x, r.y + r.height); ctx.lineTo(r.x, r.y + r.height - L)
                ctx.stroke()
                if (ph === "screen") {
                    // varredura vertical + brilhos de dados aleatórios
                    const sy = r.y + ((t * 0.22) % 1) * r.height
                    const g = ctx.createLinearGradient(0, sy - 60, 0, sy)
                    g.addColorStop(0, Qt.rgba(0.56, 0.91, 1, 0)); g.addColorStop(1, Qt.rgba(0.56, 0.91, 1, 0.16))
                    ctx.fillStyle = g; ctx.fillRect(r.x, sy - 60, r.width, 60)
                    ctx.fillStyle = Qt.rgba(0.8, 0.97, 1, 0.55); ctx.fillRect(r.x, sy, r.width, 1)
                    for (let i = 0; i < N; i += 7) {
                        const p = sw.pts[i], k = (t * 1.3 + p.glint) % 40
                        if (k < 0.5) { ctx.fillStyle = Qt.rgba(0.56, 0.91, 1, 0.22 * (1 - k * 2)); ctx.fillRect(p.tx - cw / 2 + 1, p.ty - ch / 2 + 1, cw - 2, ch - 2) }
                    }
                }
            }
            // linhas do plexo (só no núcleo)
            if (ph === "core" || ph === "release") {
                const maxD = sw.radius * 0.55
                ctx.lineWidth = 1
                for (let i = 0; i < sw.nCore; i++) {
                    for (let j = i + 1; j < sw.nCore; j++) {
                        const dx = P[i][0] - P[j][0], dy = P[i][1] - P[j][1]
                        if (Math.abs(dx) > maxD || Math.abs(dy) > maxD) continue
                        const d = Math.sqrt(dx * dx + dy * dy)
                        if (d < maxD) {
                            ctx.strokeStyle = Qt.rgba(0.56, 0.91, 1, (1 - d / maxD) * (0.25 + sw.pulse * 0.5))
                            ctx.beginPath(); ctx.moveTo(P[i][0], P[i][1]); ctx.lineTo(P[j][0], P[j][1]); ctx.stroke()
                        }
                    }
                }
            }
            // as nanopartículas
            for (let i = 0; i < N; i++) {
                const q = P[i], moving = ph === "forming" && q[3] > 0 && q[3] < 1
                if (moving) {     // rastro
                    const p = sw.pts[i], c = sw.corePos(p, i, t), back = Math.max(0, q[3] - 0.12)
                    const e = sw.ease(back)
                    ctx.strokeStyle = Qt.rgba(0.56, 0.91, 1, 0.45); ctx.lineWidth = 1
                    ctx.beginPath(); ctx.moveTo(c[0] + (p.tx - c[0]) * e, c[1] + (p.ty - c[1]) * e); ctx.lineTo(q[0], q[1]); ctx.stroke()
                }
                const sz = ph === "core" ? 1.2 + q[2] * 2.2 + sw.pulse * 1.5 : (moving ? 2.6 : 1.8)
                ctx.fillStyle = i % 11 === 0 ? Qt.rgba(1, 0.54, 0.12, 0.95) : Qt.rgba(0.75, 0.96, 1, ph === "core" ? 0.45 + q[2] * 0.55 : 0.9)
                ctx.fillRect(q[0] - sz / 2, q[1] - sz / 2, sz, sz)
            }
        }
    }

    // rótulo do núcleo
    Text {
        x: sw.coreX - width / 2; y: sw.coreY + sw.radius * 1.9
        opacity: sw.phase === "core" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 300 } }
        text: sw.mode === "speaking" ? "F.R.I.D.A.Y.  ·  FALANDO" : sw.mode === "listening" ? "F.R.I.D.A.Y.  ·  OUVINDO"
              : sw.mode === "thinking" ? "F.R.I.D.A.Y.  ·  PROCESSANDO" : "F.R.I.D.A.Y.  ·  ONLINE"
        color: "#ffffff"; font.pixelSize: 13; font.letterSpacing: 6; font.bold: true
        Rectangle { anchors { top: parent.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter } width: parent.width * 0.6; height: 2; color: sw.cHot }
    }
    // telemetria da montagem
    Text {
        x: sw.target.x; y: sw.target.y - 24
        visible: sw.phase === "forming" || sw.phase === "screen"
        text: (sw.phase === "forming" ? (sw.kind === "app" ? "◈ MATERIALIZANDO " : "◈ COMPILANDO TELA ") + Math.round(sw.progress * 100) + "%"
                                      : "◈ HOLO-TELA ATIVA") + (sw.label ? "  ·  " + sw.label.toUpperCase() : "")
        color: "#ffb070"; font.pixelSize: 11; font.letterSpacing: 3; font.family: "monospace"
    }
    Text {
        x: sw.target.x + sw.target.width - width; y: sw.target.y + sw.target.height + 8
        visible: sw.phase === "screen" || sw.phase === "forming"
        text: "NANO " + sw.cols * sw.rows + "  ·  GRID " + sw.cols + "×" + sw.rows + "  ·  " + Math.round(sw.target.width) + "×" + Math.round(sw.target.height)
        color: "#668fe9ff"; font.pixelSize: 9; font.letterSpacing: 2; font.family: "monospace"
    }
}
