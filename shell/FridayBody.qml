import QtQuick
import "assets/friday_body.js" as BodyData

// Corpo inteiro holográfico (nuvem de ~9 mil pontos, partes rígidas articuladas) — leve: Canvas 2D, ~20 fps.
// Pose = ângulos (graus) por articulação; a transição entre poses é suave. Poses nomeadas em `library`.
Item {
    id: fb
    property string pose: "neutro"          // nome da pose-alvo
    property real clock: 0
    property bool speaking: false
    property bool listening: false
    property bool thinking: false
    property real lookX: 0                  // -1..1 (olhar do usuário)
    property real lookY: 0
    property real alpha: 1.0
    property color tint: "#7fe6ff"

    // ------------------------------------------------------------------ biblioteca de poses (deltas em graus)
    // chaves: waist_rx/ry, chest_rx/ry, neck_rx/ry/rz, head_rx/ry/rz,
    //         shL_fwd/abd/rot, shR_..., elL, elR (flexão), wrL_rx/rz, wrR_rx/rz, hipL_fwd/abd, hipR_.., knL, knR, root_ry, root_dy
    readonly property var library: ({
        neutro:    { },
        ouvindo:   { head_rz: 5, head_rx: 4, neck_ry: 0, chest_rx: 3, shL_fwd: 8, elL: 12, shR_fwd: 4 },
        pensando:  { head_rx: 5, head_ry: -8, shR_fwd: 58, shR_rot: -38, shR_abd: -20, elR: 118, wrR_rx: -10, chest_rx: 3, shL_fwd: 30, shL_rot: 20, shL_abd: -15, elL: 70 },
        falando:   { shR_fwd: 22, elR: 22, shL_fwd: 14, elL: 18, head_rx: -2 },
        apresentar:{ shR_fwd: 35, shR_abd: 18, elR: 55, wrR_rx: 25, shL_fwd: 10, elL: 12, head_ry: 8 },
        apontar:   { root_ry: 38, shR_fwd: 82, shR_abd: -10, elR: -42, head_ry: -12, chest_ry: -6, shL_fwd: 8, elL: 20 },
        apontarL:  { root_ry: -38, shL_fwd: 82, shL_abd: -10, elL: -42, head_ry: 12, chest_ry: 6, shR_fwd: 8, elR: 20 },
        cruz:      { shL_fwd: 58, shL_rot: 56, shL_abd: -26, elL: 92, shR_fwd: 66, shR_rot: -56, shR_abd: -26, elR: 92, head_rx: 3, chest_rx: 1 },
        acenar:    { shR_fwd: 18, shR_abd: 62, elR: 75, wrR_rz: 0, head_rz: -5, head_ry: 8 },
        maosQuadril:{ shL_fwd: -8, shL_abd: 18, elL: 78, wrL_rx: 10, shR_fwd: -8, shR_abd: 18, elR: 78, wrR_rx: 10 },
        surpreso:  { shL_fwd: 20, shL_abd: 38, elL: 55, shR_fwd: 20, shR_abd: 38, elR: 55, head_rx: -8, chest_rx: -4 },
        reverencia:{ waist_rx: 28, chest_rx: 14, head_rx: 10, shL_fwd: 16, elL: 30, shR_fwd: 16, elR: 30 },
        alerta:    { shL_fwd: 30, elL: 60, shR_fwd: 30, elR: 60, head_rx: -3, chest_rx: -2 },
        confirmar: { shR_fwd: 62, shR_rot: -22, shR_abd: 4, elR: 108, head_rx: 8, wrR_rx: -10 },
        negar:     { shR_fwd: 30, shR_abd: 36, elR: 20, shL_fwd: 30, shL_abd: 36, elL: 20, head_ry: 0 },
        agarrar:   { shR_fwd: 70, shR_abd: 10, elR: 60, wrR_rx: 15, head_ry: 12, chest_ry: 6 }
    })
    // --- vida: gestos espontâneos quando ociosa e gestos de apoio quando fala
    property string actPose: ""             // pose espontânea atual ("" = nenhuma)
    property real lookJx: 0                 // olhar errante (sacadas)
    property real lookJy: 0
    Timer {
        id: actT
        interval: 4200; repeat: true; running: fb.visible
        onTriggered: {
            if (fb.speaking) {
                const g = ["apresentar", "confirmar", "maosQuadril", "apontar", "apresentar", "alerta"]
                fb.actPose = g[Math.floor(Math.random() * g.length)]
                interval = 1500 + Math.random() * 1500
            } else if (fb.pose === "neutro" && !fb.thinking) {
                if (Math.random() < 0.62) {
                    const g = ["maosQuadril", "apresentar", "pensando", "cruz", "ouvindo", "alerta", "reverencia", "acenar"]
                    fb.actPose = g[Math.floor(Math.random() * g.length)]
                    interval = 2000 + Math.random() * 1600
                } else { fb.actPose = ""; interval = 2500 + Math.random() * 3500 }
            } else { fb.actPose = ""; interval = 3000 }
        }
    }
    Timer {                                  // sacadas do olhar
        interval: 1300; repeat: true; running: fb.visible
        onTriggered: { fb.lookJx = (Math.random() - 0.5) * 1.1; fb.lookJy = (Math.random() - 0.5) * 0.6; interval = 700 + Math.random() * 2200 }
    }
    property var cur: ({})                  // valores atuais (suavizados)
    property var tgt: ({})                  // alvo = pose + procedural
    readonly property var keys: ["waist_rx","waist_ry","chest_rx","chest_ry","neck_rx","neck_ry","neck_rz","head_rx","head_ry","head_rz",
        "shL_fwd","shL_abd","shL_rot","shR_fwd","shR_abd","shR_rot","elL","elR","wrL_rx","wrL_rz","wrR_rx","wrR_rz",
        "hipL_fwd","hipL_abd","hipR_fwd","hipR_abd","knL","knR","root_ry","root_dy"]

    // ------------------------------------------------------------------ matemática
    function rotM(rx, ry, rz) {            // R = Rz * Ry * Rx (graus)
        const a = rx * Math.PI / 180, b = ry * Math.PI / 180, c = rz * Math.PI / 180
        const ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b), cc = Math.cos(c), sc = Math.sin(c)
        return [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa,
                sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa,
                -sb,     cb * sa,                cb * ca]
    }
    function mul(A, B) {
        const R = new Array(9)
        for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++)
            R[i * 3 + j] = A[i * 3] * B[j] + A[i * 3 + 1] * B[3 + j] + A[i * 3 + 2] * B[6 + j]
        return R
    }
    function mv(R, v) { return [R[0] * v[0] + R[1] * v[1] + R[2] * v[2], R[3] * v[0] + R[4] * v[1] + R[5] * v[2], R[6] * v[0] + R[7] * v[1] + R[8] * v[2]] }

    // rotação local (rx, ry, rz) de cada parte a partir dos valores de pose
    function localRot(name, p) {
        switch (name) {
        case "pelvis": return [0, p.root_ry, 0]
        case "waist":  return [p.waist_rx, p.waist_ry, 0]
        case "chest":  return [p.chest_rx, p.chest_ry, 0]
        case "neck":   return [p.neck_rx, p.neck_ry, p.neck_rz]
        case "head":   return [p.head_rx, p.head_ry, p.head_rz]
        case "armR":   return [-p.shR_fwd, p.shR_rot, p.shR_abd]
        case "armL":   return [-p.shL_fwd, p.shL_rot, -p.shL_abd]
        case "foreR":  return [-p.elR, 0, 0]
        case "foreL":  return [-p.elL, 0, 0]
        case "handR":  return [-p.wrR_rx, 0, p.wrR_rz]
        case "handL":  return [-p.wrL_rx, 0, p.wrL_rz]
        case "thighR": return [-p.hipR_fwd, 0, p.hipR_abd]
        case "thighL": return [-p.hipL_fwd, 0, -p.hipL_abd]
        case "shinR":  return [p.knR, 0, 0]
        case "shinL":  return [p.knL, 0, 0]
        default: return [0, 0, 0]
        }
    }

    // ------------------------------------------------------------------ animação
    Component.onCompleted: { const c = {}; for (const k of keys) c[k] = 0; cur = c; tgt = c }
    Timer {
        interval: (fb.speaking || fb.pose !== "neutro" || fb.thinking || fb.actPose !== "") ? 40 : 60; repeat: true; running: fb.visible     // ocioso: ~12 fps (leve)
        onTriggered: {
            fb.clock += interval / 1000.0
            const nome = (fb.pose !== "neutro" ? fb.pose : (fb.actPose !== "" ? fb.actPose : "neutro"))
            const base = fb.library[nome] || fb.library.neutro
            const t = fb.clock, T = {}
            for (const k of fb.keys) T[k] = base[k] !== undefined ? base[k] : 0
            // vida procedural
            const br = Math.sin(t * 1.3)
            T.chest_rx += br * 1.6; T.shL_fwd += br * 1.2 + Math.sin(t * 0.8) * 2; T.shR_fwd += br * 1.2 + Math.sin(t * 0.9 + 1) * 2
            T.waist_ry += Math.sin(t * 0.5) * 3.5; T.hipL_abd += Math.sin(t * 0.4) * 2; T.hipR_abd -= Math.sin(t * 0.4) * 2
            T.root_dy = Math.sin(t * 1.3) * 0.05 + Math.sin(t * 0.37) * 0.025
            T.head_ry += (fb.lookX + fb.lookJx * (fb.lookX === 0 ? 1 : 0.3)) * 14; T.head_rx += (fb.lookY + fb.lookJy * (fb.lookY === 0 ? 1 : 0.3)) * 8 + Math.sin(t * 0.7) * 1.6
            T.head_rz += Math.sin(t * 0.55 + 0.7) * 2.2
            T.neck_ry += (fb.lookX + fb.lookJx * 0.5) * 6
            T.root_ry += Math.sin(t * 0.35) * 9 + Math.sin(t * 0.83) * 3                       // balanço lento do corpo
            if (fb.speaking) {                                          // gesticula ao falar
                T.shR_fwd += 12 + Math.sin(t * 2.6) * 12; T.elR += Math.sin(t * 2.1 + 0.8) * 18; T.wrR_rx += Math.sin(t * 3.1) * 12
                T.shL_fwd += 8 + Math.sin(t * 1.9 + 1.4) * 10; T.elL += Math.sin(t * 2.4) * 14; T.wrL_rx += Math.sin(t * 2.7 + 1) * 10
                T.head_rx += Math.sin(t * 3.2) * 3.2; T.head_ry += Math.sin(t * 1.4) * 6; T.chest_ry += Math.sin(t * 1.1) * 4
            }
            if (fb.thinking && fb.pose === "neutro") { T.head_ry += Math.sin(t * 0.9) * 6 }
            const c = fb.cur
            for (const k of fb.keys) c[k] += (T[k] - c[k]) * 0.20
            cv.requestPaint()
        }
    }

    // ------------------------------------------------------------------ desenho
    Canvas {
        id: cv
        anchors.fill: parent
        renderStrategy: Canvas.Threaded
        onPaint: {
            const c = getContext("2d"), W = width, H = height
            c.reset()
            if (!BodyData.BODY) return
            const P = fb.cur, parts = BodyData.BODY.parts, byName = {}
            const Hm = BodyData.BODY.height + 0.5
            const sc = Math.min(H * 0.90 / Hm, W * 0.40 / 6.0)          // unidades do modelo -> px
            const gx = W / 2, gy = H * 0.955
            // transformações por parte
            const Tm = {}
            for (const part of parts) {
                const rr = fb.localRot(part.name, P)
                const Rl = fb.rotM(rr[0], rr[1], rr[2])
                const cpv = part.pivot
                const rc = fb.mv(Rl, cpv)
                let Rw = Rl, tw = [cpv[0] - rc[0], cpv[1] - rc[1] + (part.name === "pelvis" ? P.root_dy : 0), cpv[2] - rc[2]]
                if (part.parent) {
                    const pp = Tm[part.parent]
                    Rw = fb.mul(pp.R, Rl)
                    const rt = fb.mv(pp.R, tw)
                    tw = [rt[0] + pp.t[0], rt[1] + pp.t[1], rt[2] + pp.t[2]]
                }
                Tm[part.name] = { R: Rw, t: tw }
            }
            // plataforma/projetor
            const flick = 0.92 + 0.08 * Math.sin(fb.clock * 17)
            c.globalCompositeOperation = "lighter"
            const ringR = W * 0.34
            for (let k = 0; k < 3; k++) {
                c.strokeStyle = "rgba(127,230,255," + (0.35 - k * 0.1) * fb.alpha + ")"; c.lineWidth = 1.6
                c.beginPath(); c.ellipse(gx - ringR * (1 + k * 0.18), gy - ringR * 0.16 * (1 + k * 0.18) + 4, ringR * 2 * (1 + k * 0.18), ringR * 0.32 * (1 + k * 0.18)); c.stroke()
            }
            // pontos (3 faixas de profundidade -> 3 estilos, poucas trocas de fillStyle)
            const bins = [[], [], [], []]
            const scanY = ((fb.clock * 0.45) % 1.35) * Hm - 0.1
            const yaw = 0.0
            const scan = ((fb.clock * 0.35) % 1.2) * Hm                // faixa de varredura subindo
            for (const part of parts) {
                const T = Tm[part.name], R = T.R, t = T.t, pts = part.pts
                for (let i = 0; i < pts.length; i += 3) {
                    const x = pts[i], y = pts[i + 1], z = pts[i + 2]
                    const X = R[0] * x + R[1] * y + R[2] * z + t[0]
                    const Y = R[3] * x + R[4] * y + R[5] * z + t[1]
                    const Z = R[6] * x + R[7] * y + R[8] * z + t[2]
                    const persp = 1.0 / (1.0 + (Z - 0.3) * 0.03)
                    const sx = gx + X * sc * persp, sy = gy - Y * sc * persp
                    let b = Z > 0.9 ? 2 : (Z > -0.1 ? 1 : 0)
                    if (Math.abs(Y - scanY) < 0.30) b = 3                        // pontos "varridos" ficam brancos
                    bins[b].push(sx, sy, Y)
                }
            }
            const col = fb.tint
            const styles = ["rgba(60,140,230,", "rgba(110,205,255,", "rgba(210,248,255,", "rgba(255,255,255,"]
            const alphas = [0.62, 0.85, 1.0, 1.0]
            for (let b = 0; b < 4; b++) {
                c.fillStyle = styles[b] + (alphas[b] * fb.alpha * flick) + ")"
                const arr = bins[b], s = b === 3 ? 3.4 : (b === 2 ? 2.6 : (b === 1 ? 2.2 : 1.9))
                for (let i = 0; i < arr.length; i += 3) c.fillRect(arr[i], arr[i + 1], s, s)
            }
            // scanner: anel elíptico com rastro e régua lateral
            const syS = gy - scanY * sc
            for (let k = 0; k < 6; k++) {
                const yy = syS + k * 7, a = (0.55 - k * 0.09) * fb.alpha
                c.strokeStyle = "rgba(190,250,255," + a + ")"; c.lineWidth = k === 0 ? 2.2 : 1.2
                c.beginPath(); c.ellipse(gx - W * 0.30, yy - W * 0.045, W * 0.60, W * 0.09); c.stroke()
            }
            c.fillStyle = "rgba(160,240,255," + 0.85 * fb.alpha + ")"
            for (let k = 0; k < 22; k++) c.fillRect(gx + W * 0.36, gy - k * (H * 0.045), k % 5 === 0 ? 14 : 7, 1)
            c.fillRect(gx + W * 0.36 + 16, syS - 1, 18, 3)
            c.globalCompositeOperation = "source-over"
        }
    }
}
