import QtQuick
import QtQuick.Effects

// Telas holográficas da F.R.I.D.A.Y. (v2 do FridayPanels; mesma interface: show(op, dados) / hide() / closed()).
// Vidro escuro com brilho por GPU, entrada em 3D (inclinação + varredura que revela o conteúdo + glitch de cor),
// luz correndo na borda, cantoneiras animadas e saída "TV desligando". Conteúdo: agenda (linha do tempo), clima (ícone animado),
// sistema (medidores com brilho), mídia (equalizador) e plano (etapas com progresso).
Item {
    id: pn
    property string op: ""
    property var dados: ({})
    property bool open: false
    property int ttl: 30000
    signal closed()
    readonly property color cHot: "#ff8a1f"
    readonly property color cHolo: "#8fe9ff"
    property real entrada: 0
    property real varre: 0
    property real glitch: 0
    property real tilt: 0
    property int seq: 0                     // muda a cada show: reinicia as animações internas

    function show(o, d) {
        const longo = o === "plano" && !(d && d.fim)
        hideT.interval = longo ? 900000 : (o === "plano" ? 15000 : ttl)
        if (open && o === op && !leave.running) { dados = d || {}; hideT.restart(); return }
        leave.stop()
        op = o; dados = d || {}; seq++
        enter.restart(); hideT.restart()
    }
    function hide() { if (!open) return; open = false; hideT.stop(); enter.stop(); leave.restart() }

    Timer { id: hideT; onTriggered: pn.hide() }
    SequentialAnimation {
        id: enter
        ScriptAction { script: { pn.open = true; crt.xScale = 1; crt.yScale = 1; flash.opacity = 0 } }
        ParallelAnimation {
            NumberAnimation { target: pn; property: "entrada"; from: 0; to: 1; duration: 520; easing.type: Easing.OutCubic }
            NumberAnimation { target: pn; property: "tilt"; from: 22; to: 0; duration: 820; easing.type: Easing.OutBack }
            NumberAnimation { target: pn; property: "glitch"; from: 1; to: 0; duration: 700; easing.type: Easing.InQuad }
            SequentialAnimation {
                PauseAnimation { duration: 160 }
                NumberAnimation { target: pn; property: "varre"; from: 0; to: 1; duration: 780; easing.type: Easing.InOutQuad }
            }
        }
    }
    SequentialAnimation {                        // "TV desligando"
        id: leave
        ParallelAnimation {
            NumberAnimation { target: crt; property: "yScale"; to: 0.012; duration: 200; easing.type: Easing.InQuad }
            NumberAnimation { target: flash; property: "opacity"; to: 0.9; duration: 200 }
        }
        NumberAnimation { target: crt; property: "xScale"; to: 0; duration: 170; easing.type: Easing.InQuad }
        ScriptAction { script: { pn.entrada = 0; pn.varre = 0; pn.closed() } }
    }

    // ================== cartão ==================
    Item {
        id: card
        anchors.centerIn: parent
        width: Math.min(pn.width * 0.5, 760); height: Math.min(pn.height * 0.55, 480)
        opacity: pn.entrada
        visible: opacity > 0.01
        transform: [
            Scale { id: crt; origin.x: card.width / 2; origin.y: card.height / 2 },
            Rotation { origin.x: card.width / 2; origin.y: card.height / 2; axis { x: 0.25; y: 1; z: 0 } angle: pn.tilt }
        ]

        // vidro
        Rectangle {
            anchors.fill: parent; radius: 6
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#ee07141b" }
                GradientStop { position: 0.55; color: "#f0030a0e" }
                GradientStop { position: 1.0; color: "#f2060d12" }
            }
        }
        // trama hexagonal sutil (estática) + varredura lenta
        Canvas {
            anchors.fill: parent; opacity: 0.55
            onWidthChanged: requestPaint()
            onPaint: {
                const c = getContext("2d"); c.reset(); c.strokeStyle = "rgba(143,233,255,0.05)"; c.lineWidth = 1
                const s = 18, h = s * Math.sqrt(3) / 2
                for (let y = 0, row = 0; y < height + s; y += h, row++) {
                    for (let x = (row % 2) * s * 1.5; x < width + s * 3; x += s * 3) {
                        c.beginPath()
                        for (let k = 0; k <= 6; k++) { const a = k * Math.PI / 3; const px = x + s * Math.cos(a), py = y + s * Math.sin(a); if (k === 0) c.moveTo(px, py); else c.lineTo(px, py) }
                        c.stroke()
                    }
                }
            }
        }
        Item {
            anchors.fill: parent; clip: true
            Rectangle {
                width: parent.width; height: 90; opacity: 0.28
                gradient: Gradient { GradientStop { position: 0; color: "#008fe9ff" } GradientStop { position: 1; color: "#188fe9ff" } }
                NumberAnimation on y { from: -90; to: card.height; duration: 5200; loops: Animation.Infinite; running: card.visible }
            }
        }

        // moldura com brilho (GPU)
        Item {
            id: moldura
            anchors.fill: parent
            layer.enabled: true
            layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "#8fe9ff"; shadowBlur: 0.7; shadowOpacity: 0.9; shadowHorizontalOffset: 0; shadowVerticalOffset: 0; blurMax: 24 }
            Rectangle { anchors.fill: parent; radius: 6; color: "transparent"; border.color: "#aa8fe9ff"; border.width: 1 }
            // cantoneiras (crescem na entrada)
            Repeater {
                model: 4
                Item {
                    readonly property real len: 30 * pn.entrada
                    x: index % 2 ? card.width - len : 0; y: index > 1 ? card.height - len : 0; width: len; height: len
                    Rectangle { width: parent.len; height: 3; color: index < 2 ? "#ffffff" : pn.cHot; y: index > 1 ? parent.len - 3 : 0 }
                    Rectangle { width: 3; height: parent.len; color: index < 2 ? "#ffffff" : pn.cHot; x: index % 2 ? parent.len - 3 : 0 }
                }
            }
            // luz correndo pela borda
            Rectangle {
                id: corredor
                property real u: 0
                readonly property real per: 2 * (card.width + card.height)
                readonly property real d: u * per
                width: 26; height: 3; radius: 1.5; color: "#ffffff"
                x: d < card.width ? d - 13 : (d < card.width + card.height ? card.width - 2 : (d < 2 * card.width + card.height ? card.width - (d - card.width - card.height) - 13 : -1))
                y: d < card.width ? -1 : (d < card.width + card.height ? d - card.width - 13 : (d < 2 * card.width + card.height ? card.height - 2 : card.height - (d - 2 * card.width - card.height) - 13))
                rotation: (d >= card.width && d < card.width + card.height) || d >= 2 * card.width + card.height ? 90 : 0
                NumberAnimation on u { from: 0; to: 1; duration: 6000; loops: Animation.Infinite; running: card.visible }
            }
            // cabeçalho
            Rectangle {
                x: 1; y: 1; width: parent.width - 2; height: 46; radius: 5
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "#40ff8a1f" } GradientStop { position: 0.6; color: "#10ff8a1f" } GradientStop { position: 1.0; color: "#00ff8a1f" } }
            }
            Rectangle { x: 18; y: 46; height: 1; width: (card.width - 36) * pn.varre; color: "#888fe9ff" }
        }

        // título (com glitch de cor na entrada)
        Item {
            x: 20; y: 11; width: card.width - 40; height: 26
            readonly property string txt: ({ plano: "◆ TAREFA · " + String(pn.dados.titulo || "").toUpperCase(), clima: "METEO · CLIMA", agenda: "AGENDA · CRONO",
                                            sistema: "◉ SISTEMA", midia: "MÍDIA · AUDIO", transicao: String(pn.dados.titulo || "") })[pn.op] || pn.op.toUpperCase()
            Text { x: 3 * pn.glitch; text: parent.txt; color: "#ff3d6e"; opacity: pn.glitch * 0.8; font.pixelSize: 16; font.bold: true; font.letterSpacing: 5 }
            Text { x: -3 * pn.glitch; text: parent.txt; color: "#3df0ff"; opacity: pn.glitch * 0.8; font.pixelSize: 16; font.bold: true; font.letterSpacing: 5 }
            Text { text: parent.txt; color: "#ffffff"; font.pixelSize: 16; font.bold: true; font.letterSpacing: 5; elide: Text.ElideRight; width: parent.width - 170 }
        }
        Row {                                    // relógio + barras de sinal
            anchors { right: parent.right; rightMargin: 20; top: parent.top; topMargin: 16 } spacing: 10
            Text { id: rel; color: pn.cHot; font.pixelSize: 11; font.letterSpacing: 3; font.family: "monospace"; text: "F.R.I.D.A.Y. // " + Qt.formatTime(new Date(), "hh:mm:ss")
                Timer { interval: 1000; running: card.visible; repeat: true; onTriggered: rel.text = "F.R.I.D.A.Y. // " + Qt.formatTime(new Date(), "hh:mm:ss") } }
            Row { spacing: 2; anchors.bottom: rel.bottom
                Repeater { model: 4
                    Rectangle { width: 3; height: 4 + index * 3; anchors.bottom: parent.bottom; color: pn.cHolo
                        SequentialAnimation on opacity { loops: Animation.Infinite; running: card.visible
                            PauseAnimation { duration: index * 120 } NumberAnimation { to: 0.25; duration: 400 } NumberAnimation { to: 1; duration: 400 } } } } }
        }

        // conteúdo: revelado de cima p/ baixo pela varredura
        Item {
            id: corpo
            x: 24; y: 62; width: card.width - 48; height: card.height - 84
            clip: true
            Item {
                id: mascara
                width: parent.width; height: parent.height * pn.varre; clip: true
                Loader {
                    width: corpo.width; height: corpo.height
                    sourceComponent: pn.op === "plano" ? plano : pn.op === "clima" ? clima : pn.op === "agenda" ? agenda : pn.op === "sistema" ? sistema : pn.op === "midia" ? midia : null
                }
            }
            Rectangle { y: mascara.height - 2; width: parent.width; height: 2; color: "#ffffff"; visible: pn.varre > 0 && pn.varre < 1
                Rectangle { anchors.centerIn: parent; width: parent.width; height: 14; opacity: 0.35
                    gradient: Gradient { GradientStop { position: 0; color: "#008fe9ff" } GradientStop { position: 0.5; color: "#ff8fe9ff" } GradientStop { position: 1; color: "#008fe9ff" } } } }
        }
        Rectangle { id: flash; anchors.fill: parent; color: "#ffffff"; opacity: 0; radius: 6 }
    }

    // ================== conteúdos ==================
    Component {
        id: agenda
        Item {
            anchors.fill: parent
            readonly property var lista: pn.dados.itens || []

            // Estado vazio
            Column {
                visible: !parent.lista.length
                anchors.centerIn: parent
                spacing: 12
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "◈ AGENDA LIVRE ◈"
                    color: pn.cHolo; font.pixelSize: 22; font.bold: true; font.letterSpacing: 4
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Nenhum compromisso agendado no momento."
                    color: "#94a3b8"; font.pixelSize: 13; font.letterSpacing: 1.5
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 140; height: 1.5; color: pn.cHot; opacity: 0.7
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Diga 'agendar reunião amanhã às 15h' para marcar um evento."
                    color: pn.cHot; font.pixelSize: 11; opacity: 0.85
                }
            }

            // Lista rica com scroll
            Item {
                visible: parent.lista.length > 0
                anchors.fill: parent

                // Cabeçalho: nível do dia + foco do dia
                Item {
                    id: barraAg
                    anchors { top: parent.top; left: parent.left; right: parent.right }
                    readonly property var nv: pn.dados.nivel || ({})
                    readonly property color corNv: nv.nivel === "crítico" ? "#f87171" : nv.nivel === "intenso" ? "#ff8a1f" : nv.nivel === "moderado" ? "#ffd27f" : "#4ade80"
                    readonly property int idxNv: nv.nivel === "crítico" ? 4 : nv.nivel === "intenso" ? 3 : nv.nivel === "moderado" ? 2 : 1
                    height: nv.nivel ? 30 + (nv.foco && nv.foco.length ? 22 : 0) : 22
                    Row {
                        id: linhaNv
                        spacing: 10; height: 24
                        Text {
                            text: barraAg.nv.nivel ? "DIA " + String(barraAg.nv.nivel).toUpperCase() : lvAgenda.count + " COMPROMISSOS"
                            color: barraAg.nv.nivel ? barraAg.corNv : pn.cHot; font.pixelSize: 12; font.bold: true; font.letterSpacing: 2
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Row {                                   // medidor de 4 segmentos
                            visible: !!barraAg.nv.nivel; spacing: 3
                            anchors.verticalCenter: parent.verticalCenter
                            Repeater {
                                model: 4
                                Rectangle {
                                    width: 22; height: 6; radius: 2
                                    color: index < barraAg.idxNv ? barraAg.corNv : "#1f8fe9ff"
                                    SequentialAnimation on opacity {
                                        running: index === barraAg.idxNv - 1; loops: Animation.Infinite
                                        NumberAnimation { to: 0.45; duration: 700 } NumberAnimation { to: 1; duration: 700 }
                                    }
                                }
                            }
                        }
                        Text {
                            visible: !!barraAg.nv.nivel
                            text: (barraAg.nv.feitos || 0) + "/" + (barraAg.nv.total || 0) + " FEITOS"
                                  + (barraAg.nv.conflitos ? "  ·  [!] " + barraAg.nv.conflitos + " CONFLITO" + (barraAg.nv.conflitos > 1 ? "S" : "") : "")
                                  + "  ·  " + Math.floor((barraAg.nv.livre_min || 0) / 60) + "H" + ("0" + (barraAg.nv.livre_min || 0) % 60).slice(-2) + " LIVRES"
                            color: barraAg.nv.conflitos ? "#f87171" : "#94a3b8"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.2
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Row {                                       // foco do dia (top 3)
                        anchors { top: linhaNv.bottom; topMargin: 2 }
                        visible: !!(barraAg.nv.foco && barraAg.nv.foco.length)
                        spacing: 8; height: 20
                        Text { text: "FOCO"; color: pn.cHot; font.pixelSize: 10; font.bold: true; font.letterSpacing: 2; anchors.verticalCenter: parent.verticalCenter }
                        Repeater {
                            model: barraAg.nv.foco || []
                            Rectangle {
                                height: 18; radius: 9; width: txF.implicitWidth + 16
                                color: modelData.prioridade === 1 ? "#33f87171" : "#1a8fe9ff"
                                border.width: 1; border.color: modelData.prioridade === 1 ? "#f87171" : "#408fe9ff"
                                Text {
                                    id: txF; anchors.centerIn: parent
                                    text: (modelData.prioridade === 1 ? "[!] " : "") + (modelData.hora ? modelData.hora + " " : "") + modelData.titulo
                                    color: "#ffffff"; font.pixelSize: 10; font.bold: modelData.prioridade === 1
                                }
                            }
                        }
                    }
                }

                ListView {
                    id: lvAgenda
                    anchors { top: barraAg.bottom; topMargin: 6; left: parent.left; right: parent.right; bottom: parent.bottom }
                    clip: true
                    spacing: 8
                    model: parent.parent.lista

                    delegate: Item {
                        width: lvAgenda.width
                        height: 52

                        opacity: modelData.feito ? 0.45 : 1
                        readonly property color corPrio: modelData.prioridade === 1 ? "#f87171" : modelData.prioridade === 3 ? "#64748b" : "#ffd27f"
                        Rectangle {
                            anchors.fill: parent
                            radius: 4
                            color: modelData.proximo ? "#22ff8a1f" : modelData.prioridade === 1 ? "#18f87171" : "#120a1622"
                            border.width: 1
                            border.color: modelData.proximo ? pn.cHot : modelData.prioridade === 1 ? "#80f87171" : "#208fe9ff"
                        }

                        // Indicador vertical de cor por tipo
                        Rectangle {
                            x: 0; y: 0; width: 3; height: parent.height
                            color: modelData.cor || pn.cHolo
                            radius: 1.5
                        }

                        // Dia e Hora (Pill lateral)
                        Column {
                            id: colHora
                            x: 12; anchors.verticalCenter: parent.verticalCenter
                            width: 75; spacing: 2

                            Text {
                                text: String(modelData.dia || "HOJE")
                                color: modelData.proximo ? pn.cHot : "#94a3b8"
                                font.pixelSize: 10; font.bold: true; font.letterSpacing: 1
                            }
                            Text {
                                text: String(modelData.hora || "--:--")
                                color: "#ffffff"; font.pixelSize: 15; font.bold: true; font.family: "monospace"
                            }
                        }

                        // Linha divisória vertical
                        Rectangle {
                            x: 94; anchors.verticalCenter: parent.verticalCenter
                            width: 1; height: 32; color: "#258fe9ff"
                        }

                        // Título e Detalhes
                        Column {
                            anchors { left: parent.left; leftMargin: 106; right: tagTipo.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            spacing: 3

                            Text {
                                width: parent.width
                                text: (modelData.feito ? "✓ " : "") + String(modelData.titulo || "Compromisso")
                                color: "#ffffff"; font.pixelSize: 14; font.bold: true; font.strikeout: !!modelData.feito
                                elide: Text.ElideRight
                            }

                            Row {
                                spacing: 8
                                Rectangle {                     // selo de prioridade
                                    width: txP.implicitWidth + 10; height: 15; radius: 7; anchors.verticalCenter: parent.verticalCenter
                                    color: "transparent"; border.width: 1; border.color: parent.parent.parent.corPrio
                                    Text {
                                        id: txP; anchors.centerIn: parent
                                        text: modelData.prioridade === 1 ? "ALTA" : modelData.prioridade === 3 ? "BAIXA" : "NORMAL"
                                        color: parent.parent.parent.parent.corPrio; font.pixelSize: 8; font.bold: true; font.letterSpacing: 1
                                    }
                                }
                                Text {
                                    text: modelData.local ? "◈ " + modelData.local : (modelData.quando || "")
                                    color: "#7dd3fc"; font.pixelSize: 11
                                    elide: Text.ElideRight; maximumLineCount: 1
                                }
                                Text {
                                    visible: modelData.fonte === "google"
                                    text: "· GOOGLE"; color: "#94a3b8"; font.pixelSize: 9; font.bold: true; font.letterSpacing: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }

                        // Tag do Tipo de Compromisso
                        Rectangle {
                            id: tagTipo
                            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                            width: txtTipo.implicitWidth + 14; height: 20; radius: 3
                            color: "#18000000"; border.width: 1; border.color: modelData.cor || pn.cHolo

                            Text {
                                id: txtTipo
                                anchors.centerIn: parent
                                text: String(modelData.tipo || "COMPROMISSO")
                                color: modelData.cor || pn.cHolo
                                font.pixelSize: 9; font.bold: true; font.letterSpacing: 1
                            }
                        }
                    }
                }
            }
        }
    }
    Component {
        id: clima
        Item {
            readonly property string tipo: { const d = String(pn.dados.desc || "").toLowerCase()
                return /tempest|trovo|thunder/.test(d) ? "tempestade" : /chuv|garoa|rain|drizzle|shower/.test(d) ? "chuva"
                     : /nubl|nuve|cloud|encob|overcast/.test(d) ? "nuvens" : /neblin|névoa|fog|mist/.test(d) ? "neblina" : "sol" }
            Canvas {
                id: icone; width: 150; height: 130; x: 0; y: 6
                property real t: 0
                Timer { interval: 40; running: icone.visible; repeat: true; onTriggered: { icone.t += 0.04; icone.requestPaint() } }
                onPaint: {
                    const c = getContext("2d"); c.reset(); const tp = parent.tipo, t = icone.t
                    const sol = (cx, cy, r) => {
                        const g = c.createRadialGradient(cx, cy, 0, cx, cy, r * 2.1); g.addColorStop(0, "rgba(255,200,120,0.9)"); g.addColorStop(0.45, "rgba(255,138,31,0.35)"); g.addColorStop(1, "rgba(255,138,31,0)")
                        c.fillStyle = g; c.fillRect(cx - r * 2.2, cy - r * 2.2, r * 4.4, r * 4.4)
                        c.strokeStyle = "rgba(255,190,110,0.9)"; c.lineWidth = 2.5
                        for (let k = 0; k < 10; k++) { const a = k / 10 * 6.283 + t * 0.6; c.beginPath(); c.moveTo(cx + Math.cos(a) * r * 1.25, cy + Math.sin(a) * r * 1.25); c.lineTo(cx + Math.cos(a) * r * (1.6 + 0.12 * Math.sin(t * 3 + k)), cy + Math.sin(a) * r * (1.6 + 0.12 * Math.sin(t * 3 + k))); c.stroke() }
                        c.fillStyle = "#ffd9a8"; c.beginPath(); c.arc(cx, cy, r, 0, 6.283); c.fill()
                    }
                    const nuvem = (cx, cy, s, al) => {
                        c.fillStyle = "rgba(143,233,255," + 0.18 * al + ")"; c.strokeStyle = "rgba(190,245,255," + 0.9 * al + ")"; c.lineWidth = 2
                        c.beginPath(); c.arc(cx - s * 0.55, cy, s * 0.42, Math.PI * 0.5, Math.PI * 1.5); c.arc(cx - s * 0.1, cy - s * 0.32, s * 0.5, Math.PI, Math.PI * 1.95)
                        c.arc(cx + s * 0.5, cy - s * 0.05, s * 0.4, Math.PI * 1.3, Math.PI * 0.5); c.closePath(); c.fill(); c.stroke()
                    }
                    if (tp === "sol") sol(75, 62, 26)
                    else if (tp === "nuvens") { sol(50, 48, 16); nuvem(78 + Math.sin(t) * 6, 72, 52, 1); nuvem(100 + Math.sin(t * 0.7 + 1) * 4, 92, 34, 0.7) }
                    else if (tp === "neblina") { for (let k = 0; k < 5; k++) { c.strokeStyle = "rgba(190,245,255," + (0.3 + 0.12 * k) + ")"; c.lineWidth = 3; c.beginPath(); c.moveTo(18 + Math.sin(t + k) * 10, 40 + k * 16); c.lineTo(132 + Math.sin(t + k) * 10, 40 + k * 16); c.stroke() } }
                    else {
                        nuvem(75, 54, 56, 1)
                        c.strokeStyle = "rgba(143,233,255,0.85)"; c.lineWidth = 2
                        for (let k = 0; k < 9; k++) { const x = 32 + k * 11, y = 78 + ((t * 90 + k * 23) % 44); c.beginPath(); c.moveTo(x, y); c.lineTo(x - 4, y + 10); c.stroke() }
                        if (tp === "tempestade" && (Math.floor(t * 2.5) % 5) === 0) { c.strokeStyle = "#ffd27f"; c.lineWidth = 3; c.beginPath(); c.moveTo(80, 70); c.lineTo(68, 96); c.lineTo(82, 96); c.lineTo(70, 124); c.stroke() }
                    }
                }
            }
            Column {
                x: 170; y: 0; spacing: 2
                Text { text: (pn.dados.temp ?? "--") + "°"; color: pn.cHolo; font.pixelSize: 84; font.weight: Font.Light
                    layer.enabled: true; layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "#8fe9ff"; shadowBlur: 0.6; shadowHorizontalOffset: 0; shadowVerticalOffset: 0 } }
                Text { text: String(pn.dados.desc || "").toUpperCase(); color: "#ffffff"; font.pixelSize: 14; font.letterSpacing: 3 }
                Text { text: "◈ " + String(pn.dados.cidade || ""); color: pn.cHot; font.pixelSize: 12; font.letterSpacing: 2 }
            }
            Column {
                anchors.right: parent.right; y: 10; spacing: 12; width: 200
                Repeater {
                    model: [["SENSAÇÃO", (pn.dados.sensacao ?? "--") + "°", Math.min(1, Math.max(0, ((pn.dados.sensacao ?? 0) + 5) / 45))],
                            ["UMIDADE", (pn.dados.umidade ?? "--") + "%", (pn.dados.umidade ?? 0) / 100],
                            ["VENTO", (pn.dados.vento ?? "--") + " km/h", Math.min(1, (pn.dados.vento ?? 0) / 60)]]
                    Column { spacing: 3; width: 200
                        Row { spacing: 8
                            Text { width: 96; text: modelData[0]; color: pn.cHot; font.pixelSize: 11; font.letterSpacing: 2 }
                            Text { text: modelData[1]; color: "#ffffff"; font.pixelSize: 15 } }
                        Rectangle { width: 200; height: 3; color: "#1a8fe9ff"
                            Rectangle { height: 3; color: pn.cHolo; width: 200 * modelData[2] * pn.varre; Behavior on width { NumberAnimation { duration: 700 } } } } }
                }
            }
            Row {
                anchors.bottom: parent.bottom; spacing: 12
                Repeater {
                    model: (pn.dados.dias || []).slice(0, 4)
                    Rectangle {
                        property real ap: 0
                        width: 158; height: 92; radius: 4; color: "#1a0a1a24"; border.color: "#558fe9ff"; border.width: 1
                        opacity: ap; y: (1 - ap) * 20
                        SequentialAnimation on ap { running: true; PauseAnimation { duration: 450 + index * 120 } NumberAnimation { to: 1; duration: 400; easing.type: Easing.OutCubic } }
                        Column { anchors.centerIn: parent; spacing: 4
                            Text { text: String(modelData.data); color: "#ffffff"; font.pixelSize: 12; anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: modelData.min + "° / " + modelData.max + "°"; color: pn.cHolo; font.pixelSize: 19; anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "chuva " + modelData.chuva + "%"; color: pn.cHot; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter } } }
                }
            }
        }
    }
    Component {
        id: sistema
        Item {
            Row {
                anchors.horizontalCenter: parent.horizontalCenter; y: 6; spacing: 26
                Repeater {
                    model: [["CPU", pn.dados.cpu || 0], ["RAM", pn.dados.ram || 0], ["DISCO", pn.dados.disco || 0]]
                    Item {
                        width: 170; height: 196
                        Canvas {
                            id: g; width: 170; height: 170
                            property real v: 0
                            property real alvo: modelData[1]
                            onAlvoChanged: v = alvo
                            Component.onCompleted: v = alvo
                            Behavior on v { NumberAnimation { duration: 1100; easing.type: Easing.OutCubic } }
                            onVChanged: requestPaint()
                            layer.enabled: true
                            layer.effect: MultiEffect { shadowEnabled: true; shadowColor: g.v > 85 ? "#ff8a1f" : "#8fe9ff"; shadowBlur: 0.7; shadowHorizontalOffset: 0; shadowVerticalOffset: 0 }
                            onPaint: {
                                const c = getContext("2d"); c.reset(); const cx = 85, cy = 85, r = 66
                                c.lineWidth = 1; c.strokeStyle = "rgba(143,233,255,0.35)"
                                for (let k = 0; k <= 40; k++) { const a = 0.75 * Math.PI + k / 40 * 1.5 * Math.PI, r1 = r + 10, r2 = r + (k % 5 === 0 ? 17 : 13)
                                    c.beginPath(); c.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); c.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2); c.stroke() }
                                c.lineCap = "round"; c.lineWidth = 9; c.strokeStyle = "rgba(143,233,255,0.12)"
                                c.beginPath(); c.arc(cx, cy, r, 0.75 * Math.PI, 2.25 * Math.PI); c.stroke()
                                const fim = 0.75 * Math.PI + 1.5 * Math.PI * Math.max(0.005, Math.min(1, v / 100))
                                const gr = c.createLinearGradient(cx - r, cy, cx + r, cy)
                                gr.addColorStop(0, "#8fe9ff"); gr.addColorStop(1, v > 85 ? "#ff5f3a" : (v > 65 ? "#ffd27f" : "#c8f6ff"))
                                c.strokeStyle = gr; c.beginPath(); c.arc(cx, cy, r, 0.75 * Math.PI, fim); c.stroke()
                                c.fillStyle = "#ffffff"; c.beginPath(); c.arc(cx + Math.cos(fim) * r, cy + Math.sin(fim) * r, 4, 0, 6.283); c.fill()
                            }
                            Text { anchors.centerIn: parent; text: Math.round(g.v) + "%"; color: "#ffffff"; font.pixelSize: 32; font.weight: Font.Light }
                        }
                        Text { anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter } text: modelData[0]; color: pn.cHot; font.pixelSize: 12; font.letterSpacing: 5 }
                    }
                }
            }
            Text {
                anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
                text: "◈ CARGA " + (pn.dados.load ?? "--") + (pn.dados.up !== undefined ? "   ·   LIGADO HÁ " + pn.dados.up + " H" : "")
                color: "#7fd0e8"; font.pixelSize: 11; font.letterSpacing: 3; font.family: "monospace"
            }
        }
    }
    Component {
        id: midia
        Item {
            id: midiaRaiz
            readonly property bool tocando: /play/i.test(String(pn.dados.status || ""))
            Row {
                id: eq
                anchors.horizontalCenter: parent.horizontalCenter; y: 20; height: 120; spacing: 5
                Repeater {
                    model: 36
                    Rectangle {
                        id: barraEq
                        width: 9; radius: 2; anchors.bottom: parent.bottom
                        property real alvo: 0.1
                        height: 8 + alvo * 110
                        Behavior on height { NumberAnimation { duration: 120 } }
                        gradient: Gradient { GradientStop { position: 0; color: index % 6 === 0 ? pn.cHot : "#e0fbff" } GradientStop { position: 1; color: "#308fe9ff" } }
                        Timer { interval: 110 + (index % 5) * 17; repeat: true; running: eq.visible
                            onTriggered: barraEq.alvo = midiaRaiz.tocando ? Math.random() * (0.35 + 0.65 * Math.abs(Math.sin(index * 0.45 + Date.now() / 900))) : 0.05 }
                    }
                }
            }
            Column {
                anchors { horizontalCenter: parent.horizontalCenter; top: eq.bottom; topMargin: 22 } spacing: 6
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: pn.dados.titulo || "NADA TOCANDO"; color: "#ffffff"; font.pixelSize: 24; elide: Text.ElideRight; width: Math.min(implicitWidth, 600) }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: pn.dados.artista || ""; color: pn.cHolo; font.pixelSize: 16 }
                Text { anchors.horizontalCenter: parent.horizontalCenter; color: pn.cHot; font.pixelSize: 11; font.letterSpacing: 4
                       text: midiaRaiz.tocando ? "▶ TOCANDO" : (/pause/i.test(String(pn.dados.status || "")) ? "|| PAUSADO" : "■ PARADO") }
            }
        }
    }
    Component {
        id: plano
        Column {
            spacing: 10
            Row { spacing: 14
                Text { text: (pn.dados.etapa || 0) + "/" + (pn.dados.total || 0); color: pn.cHot; font.pixelSize: 34; font.bold: true }
                Text { anchors.verticalCenter: parent.verticalCenter; text: String(pn.dados.objetivo || ""); color: "#ffffff"; font.pixelSize: 15; width: 540; elide: Text.ElideRight } }
            Rectangle {
                width: 660; height: 6; radius: 3; color: "#33ff8a1f"; clip: true
                Rectangle { id: barra; height: parent.height; radius: 3; color: pn.cHot
                    width: parent.width * Math.max(0, ((pn.dados.etapa || 1) - (pn.dados.fim ? 0 : 1))) / Math.max(1, pn.dados.total || 1)
                    Behavior on width { NumberAnimation { duration: 700; easing.type: Easing.OutCubic } } }
                Rectangle { width: 60; height: parent.height; opacity: 0.7
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "#00ffffff" } GradientStop { position: 0.5; color: "#ffffffff" } GradientStop { position: 1; color: "#00ffffff" } }
                    NumberAnimation on x { from: -60; to: 660; duration: 1600; loops: Animation.Infinite } }
            }
            Repeater {
                model: pn.dados.etapas || []
                Row {
                    id: et
                    property real ap: 0
                    spacing: 12; opacity: ap
                    SequentialAnimation on ap { running: true; PauseAnimation { duration: 200 + index * 90 } NumberAnimation { to: 1; duration: 350 } }
                    Item { width: 18; height: 18; anchors.verticalCenter: parent.verticalCenter
                        Rectangle { anchors.fill: parent; radius: 9; color: modelData[1] === "ok" ? pn.cHolo : modelData[1] === "falhou" ? "#ff5f6d" : "transparent"
                            border.color: modelData[1] === "pendente" ? "#88ffffff" : (modelData[1] === "executando" ? "transparent" : "transparent"); border.width: 1 }
                        Text { anchors.centerIn: parent; text: modelData[1] === "ok" ? "✓" : modelData[1] === "falhou" ? "✕" : ""; color: "#04121a"; font.pixelSize: 12; font.bold: true }
                        Canvas { anchors.fill: parent; visible: modelData[1] === "executando"
                            onPaint: { const c = getContext("2d"); c.reset(); c.strokeStyle = "#ff8a1f"; c.lineWidth = 2.5; c.beginPath(); c.arc(9, 9, 7, 0, 4.4); c.stroke() }
                            RotationAnimation on rotation { from: 0; to: 360; duration: 900; loops: Animation.Infinite; running: modelData[1] === "executando" } }
                    }
                    Text { text: modelData[0]; color: modelData[1] === "ok" ? "#bfefff" : "#ffffff"; font.pixelSize: 14; width: 620; elide: Text.ElideRight
                        opacity: modelData[1] === "pendente" ? 0.55 : 1 }
                }
            }
        }
    }
}
