import QtQuick
import QtQuick.Controls
import Quickshell.Io

// Painel lateral da conversa: chat de texto com a F.R.I.D.A.Y. (para quando o dono não pode falar).
// Mensagens vêm do daemon (model: ListModel role/text/files); enviar() emite send(texto, arquivos).
Item {
    id: cp
    property var model
    property string mode: "idle"
    property real level: 0
    property string heard: ""
    property bool heardFresh: false
    property bool online: false
    property bool pinned: false
    property real cpu: 0; property real ram: 0; property real gpu: 0; property real vram: 0
    property int camTick: 0
    property bool camOn: false
    property var anexos: []
    readonly property bool typing: input.activeFocus || input.text.length > 0 || anexos.length > 0
    signal send(string texto, var arquivos)
    signal closeRequested()
    signal pinToggled()

    property color cHot: "#ff7700"
    property color cHolo: "#ffa033"

    function focusInput() { input.forceActiveFocus() }
    function enviar() {
        const t = input.text.trim()
        if (!t && !anexos.length) return
        cp.send(t || "(veja os anexos)", anexos.slice())
        input.text = ""; anexos = []
    }
    function _isImg(f) { return /\.(png|jpe?g|webp|gif|bmp)$/i.test(f) }
    function _nome(f) { return String(f).split("/").pop() }

    // seletor de arquivos (zenity: funciona fora do Qt, sem depender de portal)
    Process {
        id: picker
        property bool soImagens: false
        command: ["zenity", "--file-selection", "--multiple", "--separator=\n", "--title=" + (soImagens ? "Imagens para a F.R.I.D.A.Y." : "Arquivos para a F.R.I.D.A.Y.")]
                 .concat(soImagens ? ["--file-filter=Imagens | *.png *.jpg *.jpeg *.webp *.gif *.bmp"] : [])
        stdout: StdioCollector {
            onStreamFinished: {
                const fs = text.split("\n").map(s => s.trim()).filter(s => s.length)
                if (fs.length) cp.anexos = cp.anexos.concat(fs).slice(0, 8)
                cp.focusInput()
            }
        }
    }

    // ---------- fundo ----------
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#f7080503" }
            GradientStop { position: 1.0; color: "#f7120a05" }
        }
    }
    Repeater {          // linhas de varredura
        model: 48
        Rectangle { x: 0; y: index * (cp.height / 48); width: cp.width; height: 1; color: "#0aff7700" }
    }
    Rectangle { anchors.right: parent.right; width: 2; height: parent.height; color: "#ccff7700" }
    Rectangle {         // luz correndo pela borda
        anchors.right: parent.right; width: 2; height: 140
        gradient: Gradient { GradientStop { position: 0; color: "#00ff7700" } GradientStop { position: 0.5; color: "#ffffaa55" } GradientStop { position: 1; color: "#00ff7700" } }
        NumberAnimation on y { from: -140; to: cp.height; duration: 3200; loops: Animation.Infinite; easing.type: Easing.InOutSine }
    }

    // ---------- cabeçalho ----------
    Item {
        id: head
        x: 18; y: 14; width: parent.width - 36; height: 112
        Rectangle {     // emblema: núcleo pulsando
            id: emb; width: 30; height: 30; radius: 15; y: 4; color: "transparent"; border.color: cp.cHot; border.width: 2
            Rectangle { anchors.centerIn: parent; width: 10 + cp.level * 12; height: width; radius: width / 2; color: cp.mode === "speaking" ? cp.cHot : cp.cHolo
                Behavior on width { NumberAnimation { duration: 90 } } }
            RotationAnimation on rotation { from: 0; to: 360; duration: 6000; loops: Animation.Infinite }
            Rectangle { width: 5; height: 5; radius: 2.5; color: "#ffffff"; x: 12; y: -2 }
        }
        Text { x: 42; y: 2; text: "F.R.I.D.A.Y."; color: "#ffffff"; font.pixelSize: 17; font.bold: true; font.letterSpacing: 5 }
        Text {
            x: 42; y: 24; font.pixelSize: 10; font.letterSpacing: 2
            color: cp.online ? cp.cHot : "#ff5f6f"
            text: !cp.online ? "● SEM CONEXÃO COM O NÚCLEO" : cp.mode === "speaking" ? "● TRANSMITINDO VOZ" : cp.mode === "listening" ? "● OUVINDO"
                  : cp.mode === "thinking" ? "● PROCESSANDO" : "● CANAL ABERTO"
            SequentialAnimation on opacity { running: cp.mode !== "idle"; loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 500 } NumberAnimation { to: 1; duration: 500 } }
        }
        Row {
            anchors.right: parent.right; y: 2; spacing: 6
            Repeater {
                model: [{ t: cp.pinned ? "◉ FIXO" : "○ FIXAR", a: "pin" }, { t: "✕", a: "close" }]
                Rectangle {
                    width: bt.implicitWidth + 16; height: 24; radius: 4; color: ma.containsMouse ? "#33ff7700" : "#14ffffff"
                    border.color: modelData.a === "pin" && cp.pinned ? cp.cHot : "#44ff7700"
                    Behavior on color { ColorAnimation { duration: 150 } }
                    Text { id: bt; anchors.centerIn: parent; text: modelData.t; color: "#fff3e0"; font.pixelSize: 10; font.letterSpacing: 1 }
                    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: modelData.a === "pin" ? cp.pinToggled() : cp.closeRequested() }
                }
            }
        }
        // medidores compactos (barras animadas)
        Row {
            y: 48; spacing: 10
            Repeater {
                model: [{ l: "CPU", v: cp.cpu, c: "#ffaa33" }, { l: "RAM", v: cp.ram, c: "#ffa033" }, { l: "GPU", v: cp.gpu, c: "#ff7700" }, { l: "VRAM", v: cp.vram, c: "#e65100" }]
                Item {
                    width: (head.width - 30) / 4; height: 26
                    Text { text: modelData.l; color: "#ffaa66"; font.pixelSize: 9; font.letterSpacing: 2 }
                    Text { anchors.right: parent.right; text: Math.round(modelData.v) + "%"; color: "#fff3e0"; font.pixelSize: 9; font.family: "monospace" }
                    Rectangle { y: 16; width: parent.width; height: 4; radius: 2; color: "#18ffffff"
                        Rectangle { height: parent.height; radius: 2; width: parent.width * Math.min(1, modelData.v / 100)
                            color: modelData.v > 85 ? "#ff7f9f" : modelData.v > 65 ? "#ffd27f" : modelData.c
                            Behavior on width { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } } } }
                }
            }
        }
        // 3 câmeras reais (miniaturas com identificação clara)
        Row {
            y: 76; spacing: 8; visible: cp.camOn
            Repeater {
                model: [
                    { f: "/tmp/friday-cam.jpg", l: "CAM 01", sub: "NATIVA" },
                    { f: "/tmp/friday-cam-amb.jpg", l: "CAM 02", sub: "AMBIENTE" },
                    { f: "/tmp/friday-cam-ptz.jpg", l: "CAM 03", sub: "PTZ 360°" }
                ]
                Rectangle {
                    width: (head.width - 16) / 3; height: 32; color: "#000"
                    border.color: "#66ff8a1f"; border.width: 1; radius: 3; clip: true
                    Image {
                        id: camImg
                        property bool falhou: false
                        anchors.fill: parent; cache: false; retainWhileLoading: true; fillMode: Image.PreserveAspectCrop
                        source: cp.camOn && cp.visible && !falhou ? "file://" + modelData.f + "?" + cp.camTick : ""
                        onStatusChanged: if (status === Image.Error) { falhou = true; novaTentativa.restart() }
                        Timer { id: novaTentativa; interval: 5000; onTriggered: camImg.falhou = false }
                    }
                    Rectangle {
                        anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
                        height: 12; color: "#d9050505"
                        Text {
                            anchors.centerIn: parent
                            text: modelData.l + " · " + modelData.sub
                            color: "#ffc27d"; font.pixelSize: 7; font.bold: true; font.letterSpacing: 1
                        }
                    }
                }
            }
        }
        Rectangle { y: 112; width: parent.width; height: 1; color: "#33ff8a1f"
            Rectangle { width: 60; height: 1; color: cp.cHot; NumberAnimation on x { from: 0; to: head.width - 60; duration: 2600; loops: Animation.Infinite; easing.type: Easing.InOutQuad } } }
    }

    // ---------- mensagens ----------
    ListView {
        id: lv
        anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: live.top; leftMargin: 14; rightMargin: 14; topMargin: 8 }
        clip: true; spacing: 10; model: cp.model
        onCountChanged: Qt.callLater(() => lv.positionViewAtEnd())
        onHeightChanged: Qt.callLater(() => lv.positionViewAtEnd())
        add: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 350 }
            NumberAnimation { property: "x"; from: 30; duration: 420; easing.type: Easing.OutCubic } } }
        delegate: Item {
            id: dl
            required property string role
            required property string text
            required property string files
            required property int index
            readonly property bool eu: role === "user"
            readonly property bool tool: role === "tool"
            readonly property var fl: files ? files.split("|").filter(s => s.length) : []
            width: lv.width; height: tool ? tl.implicitHeight + 4 : bub.height + 18
            // revelação "decodificando" das falas dela (só nas mensagens novas)
            property int shown: (role === "assistant" && index === lv.count - 1 && Date.now() - (cp.model.get(index).t || 0) < 4000) ? 0 : text.length
            NumberAnimation on shown { running: dl.shown < dl.text.length; to: dl.text.length; duration: Math.min(1600, dl.text.length * 18) }
            Text {
                id: tl; visible: dl.tool; width: parent.width; wrapMode: Text.Wrap
                text: "▸ " + dl.text; color: "#ccffaa55"; font.pixelSize: 10; font.family: "monospace"
            }
            Text { visible: !dl.tool; text: dl.eu ? "VOCÊ" : "F.R.I.D.A.Y."; color: dl.eu ? "#ffb070" : "#ffa033"; font.pixelSize: 8; font.letterSpacing: 2
                anchors.right: dl.eu ? parent.right : undefined; anchors.rightMargin: 4; x: 4 }
            Rectangle {
                id: bub; visible: !dl.tool; y: 12
                width: Math.min(lv.width * 0.86, Math.max(msg.implicitWidth, thumbs.width) + 24)
                height: msg.implicitHeight + (dl.fl.length ? thumbs.height + 10 : 0) + 18
                x: dl.eu ? parent.width - width : 0
                radius: 8
                color: dl.eu ? "#33ff7700" : "#22201004"
                border.color: dl.eu ? "#88ff7700" : "#66ff9922"; border.width: 1
                Rectangle { width: 3; height: parent.height - 12; y: 6; x: dl.eu ? parent.width - 5 : 2; radius: 1.5; color: dl.eu ? cp.cHot : cp.cHolo }
                Text {
                    id: msg; x: 12; y: 9; width: Math.min(implicitWidth, lv.width * 0.86 - 24)
                    text: dl.text.substring(0, dl.shown) + (dl.shown < dl.text.length ? "▌" : "")
                    color: "#fff5e6"; font.pixelSize: 13; wrapMode: Text.Wrap; textFormat: Text.PlainText; lineHeight: 1.15
                }
                Flow {
                    id: thumbs; x: 12; y: msg.y + msg.height + 8; spacing: 6; width: dl.fl.length ? lv.width * 0.8 - 24 : 0
                    Repeater {
                        model: dl.fl
                        Rectangle {
                            width: cp._isImg(modelData) ? 120 : ft.implicitWidth + 16; height: cp._isImg(modelData) ? 80 : 22; radius: 4
                            color: "#22000000"; border.color: "#66ff7700"; clip: true
                            Image { anchors.fill: parent; visible: cp._isImg(modelData); source: cp._isImg(modelData) ? "file://" + modelData : ""; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                            Text { id: ft; anchors.centerIn: parent; visible: !cp._isImg(modelData); text: "[DOC] " + cp._nome(modelData); color: "#ffe0b2"; font.pixelSize: 10 }
                        }
                    }
                }
            }
        }
    }

    // ---------- estado ao vivo: ouvindo / pensando / falando ----------
    Item {
        id: live
        anchors { left: parent.left; right: parent.right; bottom: inputBox.top; leftMargin: 18; rightMargin: 18; bottomMargin: 6 }
        height: cp.mode !== "idle" || cp.heardFresh ? 30 : 0
        Behavior on height { NumberAnimation { duration: 200 } }
        clip: true
        Row {       // equalizador ao falar
            visible: cp.mode === "speaking"; anchors.verticalCenter: parent.verticalCenter; spacing: 3
            Repeater { model: 28
                Rectangle { width: 3; radius: 1.5; anchors.verticalCenter: parent.verticalCenter; color: index % 5 === 0 ? cp.cHot : cp.cHolo
                    height: 3 + cp.level * 22 * (0.4 + 0.6 * Math.abs(Math.sin(index * 1.7 + cp.level * 9)))
                    Behavior on height { NumberAnimation { duration: 80 } } } }
        }
        Row {       // pontinhos ao pensar
            visible: cp.mode === "thinking"; anchors.verticalCenter: parent.verticalCenter; spacing: 6
            Repeater { model: 3
                Rectangle { width: 7; height: 7; radius: 3.5; color: cp.cHolo
                    SequentialAnimation on opacity { loops: Animation.Infinite
                        PauseAnimation { duration: index * 160 } NumberAnimation { to: 0.15; duration: 360 } NumberAnimation { to: 1; duration: 360 } } } }
            Text { text: "processando…"; color: "#ffa033"; font.pixelSize: 11; font.italic: true }
        }
        Text {      // o que ela está ouvindo
            visible: cp.mode === "listening" || (cp.mode === "idle" && cp.heardFresh)
            anchors.verticalCenter: parent.verticalCenter; width: parent.width; elide: Text.ElideLeft
            text: "[MIC] " + (cp.heard || "ouvindo…"); color: "#ffd9b0"; font.pixelSize: 12; font.italic: true
        }
    }

    // ---------- entrada: anexos + texto + enviar ----------
    Rectangle {
        id: inputBox
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 14 }
        height: Math.min(170, Math.max(52, input.contentHeight + 26)) + (cp.anexos.length ? 34 : 0)
        Behavior on height { NumberAnimation { duration: 140 } }
        radius: 10; color: "#14150b06"
        border.width: input.activeFocus ? 2 : 1; border.color: input.activeFocus ? cp.cHot : "#55ff7700"
        Behavior on border.color { ColorAnimation { duration: 200 } }
        // brilho girando na borda quando focado
        Rectangle { visible: input.activeFocus; width: 40; height: 2; color: "#ffa033"; opacity: 0.8
            NumberAnimation on x { from: 10; to: inputBox.width - 50; duration: 1800; loops: Animation.Infinite; easing.type: Easing.InOutSine } }
        Flow {
            id: chips; x: 10; y: 8; width: parent.width - 20; spacing: 6; visible: cp.anexos.length > 0
            Repeater {
                model: cp.anexos
                Rectangle {
                    height: 22; width: ct.implicitWidth + 30; radius: 11; color: "#33ff7700"; border.color: "#88ff7700"
                    Text { id: ct; x: 9; anchors.verticalCenter: parent.verticalCenter; text: (cp._isImg(modelData) ? "[IMG] " : "[DOC] ") + cp._nome(modelData).substring(0, 22); color: "#fff3e0"; font.pixelSize: 10 }
                    Text { anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: "×"; color: "#ff7700"; font.pixelSize: 13
                        MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor
                            onClicked: { const a = cp.anexos.slice(); a.splice(index, 1); cp.anexos = a } } }
                }
            }
        }
        ScrollView {
            id: sv
            anchors { left: parent.left; right: btns.left; top: parent.top; bottom: parent.bottom; leftMargin: 12; topMargin: cp.anexos.length ? 38 : 6; bottomMargin: 6 }
            TextArea {
                id: input
                placeholderText: "Escreva para a Sexta-Feira…   (Enter envia · Shift+Enter quebra linha)"
                placeholderTextColor: "#77ffaa66"
                color: "#ffffff"; font.pixelSize: 13; wrapMode: TextEdit.Wrap
                selectionColor: "#88ff7700"; background: null
                Keys.onPressed: e => {
                    if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) { cp.enviar(); e.accepted = true }
                    else if (e.key === Qt.Key_Escape) { input.focus = false; cp.closeRequested(); e.accepted = true }
                }
            }
        }
        Row {
            id: btns
            anchors { right: parent.right; bottom: parent.bottom; rightMargin: 8; bottomMargin: 8 }
            spacing: 6
            Repeater {
                model: [{ t: "ARC", tip: "anexar arquivo", a: "file" }, { t: "IMG", tip: "anexar imagem", a: "img" }, { t: "▶", tip: "enviar", a: "send" }]
                Rectangle {
                    width: 36; height: 36; radius: 18
                    color: modelData.a === "send" ? (ba.pressed ? "#ffb070" : cp.cHot) : (ba.containsMouse ? "#33ffffff" : "#14ffffff")
                    border.color: modelData.a === "send" ? "#ffd2a0" : "#44ffffff"
                    scale: ba.pressed ? 0.9 : (ba.containsMouse ? 1.08 : 1)
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    Behavior on color { ColorAnimation { duration: 150 } }
                    opacity: modelData.a === "send" && !input.text.trim() && !cp.anexos.length ? 0.45 : 1
                    Text { anchors.centerIn: parent; text: modelData.t; color: modelData.a === "send" ? "#1a0d00" : "#ffffff"; font.pixelSize: modelData.a === "send" ? 14 : 10; font.bold: true }
                    MouseArea { id: ba; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { if (modelData.a === "send") cp.enviar(); else if (!picker.running) { picker.soImagens = modelData.a === "img"; picker.running = true } } }
                    ToolTip.visible: ba.containsMouse; ToolTip.text: modelData.tip; ToolTip.delay: 500
                }
            }
        }
    }
}
