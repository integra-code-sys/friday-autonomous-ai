import QtQuick
import QtQuick.Controls

// MODO DEV: linha do tempo ao vivo do que a F.R.I.D.A.Y. ouve, pensa e faz (daemon/dev.py -> {"type":"dev",...}).
// Fontes: voz (STT/TTS), cerebro (pedido/passo/final), claude (ferramentas, pensamentos, edições com diff, custo),
// camera (PTZ), tempo (latências), sistema. Clique numa linha com diff/args para expandir.
Item {
    id: dp
    property var model                          // ListModel: hora, fonte, tipo, texto, extra (JSON com diff/args/...)
    property bool online: false
    property string filtro: "todas"
    property bool pausado: false
    signal fechar()
    signal pedirHistorico()
    signal limpar()

    readonly property var cores: ({ voz: "#7fe6ff", cerebro: "#ffd27f", claude: "#c99bff", camera: "#7fffb0",
                                    tempo: "#ff9f7f", sistema: "#9fb4c8" })
    readonly property var rotulos: ({ voz: "VOZ", cerebro: "CÉREBRO", claude: "CLAUDE", camera: "CÂMERA", tempo: "TEMPO", sistema: "SISTEMA" })

    Rectangle {
        anchors.fill: parent
        color: "#e6050b12"
        border.color: "#557fe6ff"; border.width: 1
        radius: 10
    }

    Column {
        id: topo
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
        spacing: 8
        Row {
            spacing: 10
            width: parent.width
            Text { text: "MODO DEV"; color: "#ff8a1f"; font.pixelSize: 18; font.bold: true; font.letterSpacing: 3 }
            Rectangle { width: 9; height: 9; radius: 5; anchors.verticalCenter: parent.verticalCenter
                        color: dp.online ? (dp.pausado ? "#ffd27f" : "#7fffb0") : "#ff7f9f" }
            Text { text: (dp.online ? (dp.pausado ? "pausado" : "ao vivo") : "sem daemon") + " · " + (dp.model ? dp.model.count : 0) + " eventos"
                   color: "#9fb4c8"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
        }
        Flow {
            width: parent.width
            spacing: 6
            Repeater {
                model: ["todas", "voz", "cerebro", "claude", "camera", "tempo", "sistema"]
                Rectangle {
                    required property string modelData
                    width: lb.implicitWidth + 16; height: 24; radius: 12
                    color: dp.filtro === modelData ? "#337fe6ff" : "transparent"
                    border.color: modelData === "todas" ? "#7fe6ff" : (dp.cores[modelData] || "#7fe6ff"); border.width: 1
                    Text { id: lb; anchors.centerIn: parent; text: modelData === "todas" ? "TODAS" : dp.rotulos[modelData]
                           color: modelData === "todas" ? "#cfefff" : dp.cores[modelData]; font.pixelSize: 11; font.bold: true }
                    MouseArea { anchors.fill: parent; onClicked: dp.filtro = parent.modelData }
                }
            }
        }
        Row {
            spacing: 6
            Repeater {
                model: [{ t: dp.pausado ? "▶ continuar" : "⏸ pausar", a: "pausa" }, { t: "⟳ histórico", a: "hist" },
                        { t: "⌫ limpar", a: "limpar" }, { t: "✕ fechar", a: "fechar" }]
                Rectangle {
                    required property var modelData
                    width: bt.implicitWidth + 16; height: 24; radius: 5
                    color: ma.containsMouse ? "#227fe6ff" : "transparent"; border.color: "#447fe6ff"
                    Text { id: bt; anchors.centerIn: parent; text: modelData.t; color: "#cfefff"; font.pixelSize: 11 }
                    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true
                        onClicked: { const a = parent.modelData.a
                            if (a === "pausa") dp.pausado = !dp.pausado
                            else if (a === "hist") dp.pedirHistorico()
                            else if (a === "limpar") dp.limpar()
                            else dp.fechar() } }
                }
            }
        }
    }

    ListView {
        id: lista
        anchors { left: parent.left; right: parent.right; top: topo.bottom; bottom: parent.bottom; margins: 12; topMargin: 10 }
        clip: true
        spacing: 3
        model: dp.model
        property bool noFim: true
        onContentYChanged: noFim = atYEnd
        onCountChanged: if (noFim && !dp.pausado) Qt.callLater(positionViewAtEnd)
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        delegate: Item {
            id: linha
            required property string hora
            required property string fonte
            required property string tipo
            required property string texto
            required property string extra
            property bool aberto: false
            readonly property bool mostra: dp.filtro === "todas" || dp.filtro === fonte
            readonly property var ex: { try { return JSON.parse(extra || "{}") } catch (e) { return {} } }
            readonly property string detalhe: ex.diff || ex.args || ""
            width: lista.width
            height: mostra ? col.implicitHeight + 6 : 0
            visible: mostra
            Rectangle {
                anchors.fill: parent
                radius: 4
                color: linha.tipo === "edicao" ? "#1a7fffb0" : (linha.ex.erro ? "#26ff7f9f" : (lm.containsMouse ? "#147fe6ff" : "transparent"))
            }
            Rectangle { width: 3; height: parent.height - 4; y: 2; radius: 2; color: dp.cores[linha.fonte] || "#7fe6ff" }
            Column {
                id: col
                x: 9; y: 3
                width: parent.width - 14
                spacing: 2
                Row {
                    spacing: 6
                    Text { text: linha.hora; color: "#6f8597"; font.pixelSize: 11; font.family: "monospace" }
                    Text { text: (dp.rotulos[linha.fonte] || linha.fonte) + " · " + linha.tipo
                           color: dp.cores[linha.fonte] || "#7fe6ff"; font.pixelSize: 11; font.bold: true }
                    Text { visible: linha.detalhe !== ""; text: linha.aberto ? "▾" : "▸"; color: "#9fb4c8"; font.pixelSize: 11 }
                    Text { visible: linha.ex.dur_s !== undefined && linha.ex.dur_s !== null
                           text: (linha.ex.dur_s || 0) + " s" + (linha.ex.custo ? " · US$ " + Number(linha.ex.custo).toFixed(3) : "")
                           color: "#ffd27f"; font.pixelSize: 11 }
                }
                Text {
                    width: parent.width
                    text: linha.texto
                    color: linha.tipo === "pensamento" ? "#b9a6d9" : "#dceefb"
                    font.italic: linha.tipo === "pensamento"
                    font.pixelSize: 13
                    wrapMode: Text.Wrap
                    maximumLineCount: linha.aberto ? 400 : 4
                    elide: Text.ElideRight
                }
                Text {
                    visible: linha.aberto && linha.detalhe !== ""
                    width: parent.width
                    text: linha.detalhe
                    textFormat: Text.PlainText
                    font.family: "monospace"; font.pixelSize: 11
                    color: "#cfe9d6"
                    wrapMode: Text.WrapAnywhere
                }
            }
            MouseArea { id: lm; anchors.fill: parent; hoverEnabled: true; onClicked: linha.aberto = !linha.aberto }
        }
    }
}
