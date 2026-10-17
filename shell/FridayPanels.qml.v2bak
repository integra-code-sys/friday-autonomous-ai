import QtQuick

// Telas de apresentação da F.R.I.D.A.Y.: vidro preto, moldura laranja/branca, dados holográficos azul-claros.
// show(op, data) faz a transição de entrada (o aglomerado explode antes, em FridayCore); some sozinha após ttl.
Item {
    id: pn
    property string op: ""
    property var dados: ({})
    property bool open: false
    property int ttl: 30000
    signal closed()
    readonly property color cHot: "#ff8a1f"
    readonly property color cHolo: "#8fe9ff"
    readonly property color cGlass: "#d9080808"

    function show(o, d) {
        const longo = o === "plano" && !(d && d.fim)                    // progresso de tarefa: fica até terminar e atualiza sem replay
        hideT.interval = longo ? 900000 : (o === "plano" ? 15000 : ttl)
        if (open && o === op) { dados = d || {}; hideT.restart(); return }
        op = o; dados = d || {}; open = false; enter.restart(); hideT.restart()
    }
    function hide() { if (!open) return; open = false; hideT.stop(); leave.restart() }

    Timer { id: hideT; onTriggered: pn.hide() }
    SequentialAnimation {
        id: enter
        PauseAnimation { duration: 380 }                   // tempo da explosão
        ScriptAction { script: { pn.open = true; sweep.y = 0 } }
        ParallelAnimation {
            NumberAnimation { target: card; property: "opacity"; from: 0; to: 1; duration: 420 }
            NumberAnimation { target: card; property: "scale"; from: 0.55; to: 1; duration: 520; easing.type: Easing.OutBack }
            NumberAnimation { target: sweep; property: "y"; from: 0; to: card.height; duration: 700; easing.type: Easing.InOutQuad }
        }
    }
    SequentialAnimation {
        id: leave
        ParallelAnimation {
            NumberAnimation { target: card; property: "opacity"; to: 0; duration: 320 }
            NumberAnimation { target: card; property: "scale"; to: 0.7; duration: 320; easing.type: Easing.InCubic }
        }
        ScriptAction { script: pn.closed() }
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(pn.width * 0.5, 760); height: Math.min(pn.height * 0.55, 480)
        opacity: 0; scale: 0.55
        color: pn.cGlass; radius: 4; border.color: pn.cHot; border.width: 1; clip: true
        // cantos em L (estilo HUD)
        Repeater {
            model: 4
            Item {
                x: index % 2 ? card.width - 26 : 0; y: index > 1 ? card.height - 26 : 0; width: 26; height: 26
                Rectangle { width: 26; height: 3; color: "#ffffff"; y: index > 1 ? 23 : 0 }
                Rectangle { width: 3; height: 26; color: "#ffffff"; x: index % 2 ? 23 : 0 }
            }
        }
        // trama de varredura holográfica
        Repeater { model: 40; Rectangle { y: index * card.height / 40; width: card.width; height: 1; color: "#0c8fe9ff" } }
        Rectangle { id: sweep; width: card.width; height: 3; color: pn.cHolo; opacity: 0.7 }

        // cabeçalho
        Rectangle { x: 0; y: 0; width: parent.width; height: 44; color: "#22ff8a1f" }
        Text { x: 20; y: 12; color: "#ffffff"; font.pixelSize: 16; font.bold: true; font.letterSpacing: 5
               text: ({ plano: "TAREFA · " + String(pn.dados.titulo || "").toUpperCase(), clima: "CLIMA", agenda: "AGENDA", sistema: "SISTEMA", midia: "MÍDIA", transicao: (pn.dados.titulo || "") })[pn.op] || pn.op.toUpperCase() }
        Text { anchors { right: parent.right; rightMargin: 20; top: parent.top; topMargin: 15 } color: pn.cHot; font.pixelSize: 11; font.letterSpacing: 3
               text: "F.R.I.D.A.Y. // " + Qt.formatTime(new Date(), "hh:mm") }

        Loader {
            anchors { fill: parent; topMargin: 60; margins: 24 }
            sourceComponent: pn.op === "plano" ? plano : pn.op === "clima" ? clima : pn.op === "agenda" ? agenda : pn.op === "sistema" ? sistema : pn.op === "midia" ? midia : null
        }
    }

    Component {
        id: plano
        Column {
            spacing: 10
            Row { spacing: 12
                Text { text: (pn.dados.etapa || 0) + "/" + (pn.dados.total || 0); color: pn.cHot; font.pixelSize: 30; font.bold: true }
                Text { anchors.verticalCenter: parent.verticalCenter; text: String(pn.dados.objetivo || ""); color: "#ffffff"; font.pixelSize: 15; width: 520; elide: Text.ElideRight } }
            Rectangle { width: 640; height: 4; color: "#228fe9ff"
                Rectangle { height: parent.height; color: pn.cHolo; width: parent.width * Math.max(0, ((pn.dados.etapa || 1) - (pn.dados.fim ? 0 : 1))) / Math.max(1, pn.dados.total || 1)
                    Behavior on width { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } } } }
            Repeater {
                model: pn.dados.etapas || []
                Row { spacing: 12
                    Rectangle { width: 14; height: 14; radius: 7; anchors.verticalCenter: parent.verticalCenter
                        color: modelData[1] === "ok" ? pn.cHolo : modelData[1] === "falhou" ? "#ff5f6d" : modelData[1] === "executando" ? pn.cHot : "transparent"
                        border.color: modelData[1] === "pendente" ? "#88ffffff" : "transparent"; border.width: 1
                        SequentialAnimation on opacity { running: modelData[1] === "executando"; loops: Animation.Infinite
                            NumberAnimation { to: 0.3; duration: 500 } NumberAnimation { to: 1; duration: 500 } } }
                    Text { text: modelData[0]; color: modelData[1] === "ok" ? "#bfefff" : "#ffffff"; font.pixelSize: 14; width: 600; elide: Text.ElideRight
                        font.strikeout: false; opacity: modelData[1] === "pendente" ? 0.6 : 1 } }
            }
        }
    }
    Component {
        id: clima
        Item {
            Column {
                spacing: 4
                Text { text: (pn.dados.temp ?? "--") + "°"; color: pn.cHolo; font.pixelSize: 96; font.weight: Font.Light }
                Text { text: String(pn.dados.desc || "").toUpperCase(); color: "#ffffff"; font.pixelSize: 15; font.letterSpacing: 3 }
                Text { text: String(pn.dados.cidade || ""); color: pn.cHot; font.pixelSize: 13; font.letterSpacing: 2 }
            }
            Column {
                anchors.right: parent.right; spacing: 10
                Repeater {
                    model: [["SENSAÇÃO", (pn.dados.sensacao ?? "--") + "°"], ["UMIDADE", (pn.dados.umidade ?? "--") + "%"], ["VENTO", (pn.dados.vento ?? "--") + " km/h"]]
                    Row { spacing: 12
                        Text { width: 110; text: modelData[0]; color: pn.cHot; font.pixelSize: 11; font.letterSpacing: 2; horizontalAlignment: Text.AlignRight }
                        Text { text: modelData[1]; color: pn.cHolo; font.pixelSize: 18 } }
                }
            }
            Row {
                anchors.bottom: parent.bottom; spacing: 16
                Repeater {
                    model: pn.dados.dias || []
                    Rectangle { width: 150; height: 86; color: "#14000000"; border.color: "#558fe9ff"; border.width: 1
                        Column { anchors.centerIn: parent; spacing: 3
                            Text { text: modelData.data; color: "#ffffff"; font.pixelSize: 12; anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: modelData.min + "° / " + modelData.max + "°"; color: pn.cHolo; font.pixelSize: 18; anchors.horizontalCenter: parent.horizontalCenter }
                            Text { text: "chuva " + modelData.chuva + "%"; color: pn.cHot; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter } } }
                }
            }
        }
    }
    Component {
        id: agenda
        Column {
            spacing: 8
            Text { visible: !(pn.dados.itens || []).length; text: "NENHUM COMPROMISSO NA SEMANA"; color: pn.cHolo; font.pixelSize: 16; font.letterSpacing: 3 }
            Repeater {
                model: pn.dados.itens || []
                Row { spacing: 16
                    Rectangle { width: 4; height: 24; color: index === 0 ? pn.cHot : pn.cHolo }
                    Text { width: 130; text: modelData.quando; color: pn.cHot; font.pixelSize: 15; font.family: "monospace" }
                    Text { text: modelData.titulo; color: "#ffffff"; font.pixelSize: 16; elide: Text.ElideRight; width: 420 } }
            }
        }
    }
    Component {
        id: sistema
        Row {
            spacing: 36; anchors.centerIn: parent
            Repeater {
                model: [["CPU", pn.dados.cpu || 0], ["RAM", pn.dados.ram || 0], ["DISCO", pn.dados.disco || 0]]
                Item { width: 150; height: 170
                    Canvas { id: g; width: 150; height: 150; property real v: modelData[1]
                        onPaint: { const c = getContext("2d"); c.reset(); c.lineWidth = 8
                            c.strokeStyle = "#228fe9ff"; c.beginPath(); c.arc(75, 75, 62, 0, Math.PI * 2); c.stroke()
                            c.strokeStyle = v > 85 ? "#ff8a1f" : "#8fe9ff"; c.beginPath(); c.arc(75, 75, 62, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * v / 100); c.stroke() }
                        Text { anchors.centerIn: parent; text: Math.round(g.v) + "%"; color: "#ffffff"; font.pixelSize: 28 } }
                    Text { anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter } text: modelData[0]; color: pn.cHot; font.pixelSize: 12; font.letterSpacing: 4 } }
            }
        }
    }
    Component {
        id: midia
        Column {
            anchors.centerIn: parent; spacing: 10
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: pn.dados.titulo || "NADA TOCANDO"; color: "#ffffff"; font.pixelSize: 24 }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: pn.dados.artista || ""; color: pn.cHolo; font.pixelSize: 16 }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: String(pn.dados.status || "").toUpperCase(); color: pn.cHot; font.pixelSize: 11; font.letterSpacing: 4 }
        }
    }
}
