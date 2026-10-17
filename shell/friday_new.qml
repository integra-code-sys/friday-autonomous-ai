import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// F.R.I.D.A.Y. — assistente holográfica. Dormindo: não desenha nada (o wallpaper normal do Noctalia aparece).
// "Sexta-Feira, ligar!" -> coluna esquerda (20% da tela) com o corpo inteiro holográfico articulado; as janelas reais
// ocupam os 80% restantes (a coluna reserva espaço no layout). "Sexta-Feira, desligar!" -> some.
// O avatar-wallpaper antigo continua em wallpaper_avatar.qml (PROMETHEUS_OLD=1 usa-o em vez deste).
ShellRoot {
    id: root

    component Gauge: Item {
        id: g
        property real value: 0
        property real shown: value
        Behavior on shown { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
        onShownChanged: cv.requestPaint()
        property string label: ""
        property color tint: "#7fe6ff"
        width: 76; height: 84
        onValueChanged: cv.requestPaint()
        Canvas {
            id: cv; width: 64; height: 64; x: 6; y: 0
            onPaint: {
                const c = getContext("2d"); c.reset()
                c.lineWidth = 6; c.lineCap = "round"
                c.strokeStyle = "rgba(127,230,255,0.16)"; c.beginPath(); c.arc(32, 32, 26, 0.75 * Math.PI, 2.25 * Math.PI); c.stroke()
                const v = Math.max(0.02, Math.min(1, g.shown / 100))
                c.strokeStyle = g.value > 85 ? "#ff7f9f" : (g.value > 65 ? "#ffd27f" : g.tint)
                c.beginPath(); c.arc(32, 32, 26, 0.75 * Math.PI, (0.75 + 1.5 * v) * Math.PI); c.stroke()
            }
        }
        Text { anchors.horizontalCenter: cv.horizontalCenter; y: 22; text: Math.round(g.value) + "%"; color: "#e9f9ff"; font.pixelSize: 14; font.bold: true; font.family: "monospace" }
        Text { anchors.horizontalCenter: cv.horizontalCenter; y: 66; text: g.label; color: "#7fd0e8"; font.pixelSize: 10; font.letterSpacing: 2 }
    }

    // ---- estado vindo do daemon ----
    property bool online: false
    property double lastRx: 0
    property bool fridayOn: false
    property string state: "idle"           // idle | listening | thinking | speaking
    property string mood: "neutro"
    property real mouth: 0
    property real lookX: 0
    property real lookY: 0
    property bool present: false
    property string caption: ""
    property double lastSpeech: 0
    property string poseOverride: ""
    property string gestureLabel: ""
    property bool micOn: true
    property bool camOn: false
    property int captionTick: 0
    property string heardText: ""
    property double heardAt: 0
    property int camTick: 0
    property string clockText: ""
    property string dateText: ""
    property int eqTick: 0
    property bool wfOn: false
    property real wfX: 0
    property real wfY: 0
    property real wfW: 0
    property real wfH: 0
    property string wfTitulo: ""
    property real stCpu: 0
    property real stRam: 0
    property real stGpu: 0
    property real stVram: 0
    property int stTemp: 0
    property var stPessoas: []
    property var stObjetos: []
    property string stProx: ""
    property int stTurnos: 0
    Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true
        onTriggered: { const d = new Date(); root.clockText = Qt.formatTime(d, "HH:mm:ss"); root.dateText = Qt.formatDate(d, "ddd, dd MMM").toUpperCase() } }
    Timer { interval: 70; running: root.fridayOn; repeat: true; onTriggered: root.eqTick++ }
    Timer { interval: 80; running: root.fridayOn && root.camOn; repeat: true; onTriggered: root.camTick++ }
    // palco holográfico (e-mail, figuras, janelas projetadas)
    property var stageSpec: null
    property int stageSeq: 0
    property string stageOp: "show"
    // cursor do assistente (overlay)
    property real curX: 960; property real curY: 540
    property bool curOn: false
    property int curClick: 0
    Timer { id: curHide; interval: 6000; onTriggered: root.curOn = false }
    Timer { id: poseReset; onTriggered: root.poseOverride = "" }
    Timer { id: gestReset; interval: 1800; onTriggered: root.gestureLabel = "" }
    Timer { interval: 1000; running: true; repeat: true; onTriggered: root.captionTick++ }
    readonly property bool captionVisible: caption !== "" && (Date.now() - lastSpeech < 7000 || state === "speaking") && captionTick >= 0

    function setPose(name, ttl) { poseOverride = name; if (ttl > 0) { poseReset.interval = ttl; poseReset.restart() } }

    // ---- conexão com o daemon (JSON por linha) ----
    Component {
        id: sockComp
        Socket {
            path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/prometheus.sock"
            connected: true
            onConnectedChanged: root.online = connected
            onError: root.online = false
            parser: SplitParser {
                onRead: line => {
                    try {
                        root.lastRx = Date.now()
                        const m = JSON.parse(line)
                        if (m.type === "friday") { root.fridayOn = !!m.on; if (!m.on) { root.caption = ""; root.stageSpec = null; root.stageSeq++; root.wfOn = false } }
                        if (m.type === "state") { if (m.state) root.state = m.state; if (m.mood) root.mood = m.mood }
                        if (m.type === "mouth") root.mouth = m.v > 0.05 ? Math.min(1, 0.10 + m.v * 1.30) : 0
                        if (m.type === "text" && m.role === "assistant") { root.caption = String(m.text || ""); root.lastSpeech = Date.now() }
                        if (m.type === "gaze") { root.present = m.present; root.lookX = m.present ? m.x : 0; root.lookY = m.present ? m.y : 0 }
                        if (m.type === "camera") root.camOn = !!m.on
                        if (m.type === "friday_heard") { root.heardText = String(m.text || ""); root.heardAt = Date.now() }
                        if (m.type === "voice") root.micOn = !!m.on
                        if (m.type === "holo_frame") { root.wfOn = !!m.on; root.wfX = m.x || 0; root.wfY = m.y || 0; root.wfW = m.w || 0; root.wfH = m.h || 0; root.wfTitulo = String(m.titulo || "") }
                        if (m.type === "stats") { root.stCpu = m.cpu || 0; root.stRam = m.ram || 0; root.stGpu = m.gpu || 0; root.stVram = m.vram || 0; root.stTemp = m.temp || 0
                            root.stPessoas = m.pessoas || []; root.stObjetos = m.objetos || []; root.stProx = m.prox || ""; root.stTurnos = m.turnos || 0 }
                        if (m.type === "friday_pose") root.setPose(m.pose || "", m.ttl || 2500)
                        if (m.type === "friday_gesture") {
                            root.gestureLabel = String(m.label || m.kind || "")
                            gestReset.restart()
                            if (m.pose) root.setPose(m.pose, m.ttl || 1800)
                        }
                        if (m.type === "holo") {
                            root.stageOp = m.op || "show"
                            if (m.op === "clear") root.stageSpec = null
                            else if (m.spec) root.stageSpec = m.spec
                            root.stageSeq++
                        }
                        if (m.type === "cursor") {
                            root.curX = m.x; root.curY = m.y; root.curOn = true; curHide.restart()
                            if (m.act === "click") root.curClick++
                        }
                    } catch (e) {}
                }
            }
        }
    }
    Loader { id: sockLoader; active: true; sourceComponent: sockComp }
    function reconnect() { online = false; sockLoader.active = false; retry.restart() }
    Timer { interval: 2500; running: !root.online; repeat: true; onTriggered: root.reconnect() }
    Timer { id: retry; interval: 300; onTriggered: sockLoader.active = true }
    Timer { interval: 3000; running: true; repeat: true; onTriggered: if (Date.now() - root.lastRx > 7000) root.reconnect() }

    // ================== COLUNA DO AVATAR (20% da tela, esquerda; reserva espaço no layout) ==================
    Variants {
        model: root.fridayOn ? Quickshell.screens : []
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { left: true; top: true; bottom: true }
            implicitWidth: Math.round(modelData.width * 0.20)
            exclusionMode: ExclusionMode.Normal
            exclusiveZone: Math.round(modelData.width * 0.20)      // reserva a coluna: as janelas reais ocupam só os 80% restantes
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.namespace: "friday-avatar"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#e0030a14" }
                    GradientStop { position: 1.0; color: "#e0061a2c" }
                }
                Rectangle { anchors.right: parent.right; width: 2; height: parent.height; color: "#667fe6ff" }
                // trama sutil de fundo (linhas de varredura) + brilho atrás do corpo
                Repeater {
                    model: 36
                    Rectangle { x: 0; y: index * (parent.height / 36); width: parent.width; height: 1; color: "#0f7fe6ff" }
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.30
                    width: parent.width * 0.9; height: width; radius: width / 2
                    gradient: Gradient { GradientStop { position: 0.0; color: "#1a3fb8ff" } GradientStop { position: 1.0; color: "#003fb8ff" } }
                    opacity: root.state === "speaking" ? 0.9 : 0.55
                    Behavior on opacity { NumberAnimation { duration: 400 } }
                }
                // anel giratório + dados caindo (efeitos de projeção)
                Item {
                    id: fx
                    anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.32
                    width: parent.width * 0.86; height: width
                    Repeater {
                        model: 3
                        Rectangle {
                            anchors.centerIn: parent
                            width: fx.width * (1.0 - index * 0.14); height: width; radius: width / 2; color: "transparent"
                            border.color: index === 0 ? "#337fe6ff" : (index === 1 ? "#2a9fffd0" : "#22c9a8ff"); border.width: 1
                            rotation: 0
                            NumberAnimation on rotation { from: 0; to: index % 2 === 0 ? 360 : -360; duration: 14000 + index * 5000; loops: Animation.Infinite }
                            Rectangle { width: 10; height: 10; radius: 5; x: parent.width / 2 - 5; y: -5; color: index === 0 ? "#bff3ff" : "#9fffd0" }
                        }
                    }
                }
                Repeater {
                    model: 5
                    Text {
                        x: 6 + index * (parent.width - 30) / 4; width: 14
                        text: "0 1 A 7 F 3 9 C E 2 5 B 8 D 4 6 0 1 A 7 F 3 9 C E 2 5 B"; wrapMode: Text.WrapAnywhere
                        color: "#7fe6ff"; opacity: 0.10 + (index % 2) * 0.05; font.pixelSize: 11; font.family: "monospace"
                        y: -200
                        NumberAnimation on y { from: -260; to: 1100; duration: 9000 + index * 2300; loops: Animation.Infinite }
                    }
                }
                // luz correndo pela borda direita
                Rectangle {
                    anchors.right: parent.right; width: 2; height: 160
                    gradient: Gradient { GradientStop { position: 0.0; color: "#007fe6ff" } GradientStop { position: 0.5; color: "#ffbff3ff" } GradientStop { position: 1.0; color: "#007fe6ff" } }
                    NumberAnimation on y { from: -160; to: 1100; duration: 4200; loops: Animation.Infinite }
                }
                // cabeçalho
                Rectangle { x: 10; y: 10; width: parent.width - 20; height: 54; radius: 8; color: "#70062038"; border.color: "#447fe6ff"; border.width: 1 }
                Rectangle {
                    id: dot; x: 22; y: 21; width: 12; height: 12; radius: 6
                    color: root.state === "speaking" ? "#7fffd0" : (root.state === "thinking" ? "#ffd27f" : (root.state === "listening" ? "#ff9fd0" : "#7fe6ff"))
                    Rectangle { anchors.centerIn: parent; width: 12; height: 12; radius: 6; color: "transparent"; border.color: parent.color; border.width: 1
                        SequentialAnimation on scale { loops: Animation.Infinite
                            NumberAnimation { from: 1.0; to: 2.4; duration: 1100; easing.type: Easing.OutQuad }
                            NumberAnimation { from: 2.4; to: 1.0; duration: 1 } }
                        SequentialAnimation on opacity { loops: Animation.Infinite
                            NumberAnimation { from: 0.9; to: 0.0; duration: 1100 }
                            NumberAnimation { from: 0.0; to: 0.9; duration: 1 } }
                    }
                }
                Text { x: 44; y: 15; text: "F.R.I.D.A.Y."; color: "#d6f6ff"; font.pixelSize: 16; font.bold: true; font.letterSpacing: 5 }
                Text { x: 44; y: 38; color: "#7fd0e8"; font.pixelSize: 10; font.letterSpacing: 2
                       text: (root.state === "listening" ? "OUVINDO" : root.state === "thinking" ? "PROCESSANDO" : root.state === "speaking" ? "FALANDO" : "ONLINE")
                             + "  ·  " + (root.micOn ? "MIC" : "MIC OFF") + "  ·  " + (root.camOn ? "CAM" : "CAM OFF") }
                Text { anchors { right: parent.right; rightMargin: 20; top: parent.top; topMargin: 15 } horizontalAlignment: Text.AlignRight
                       text: root.clockText; color: "#d6f6ff"; font.pixelSize: 15; font.family: "monospace"; font.bold: true }
                Text { anchors { right: parent.right; rightMargin: 20; top: parent.top; topMargin: 38 } horizontalAlignment: Text.AlignRight
                       text: root.dateText; color: "#7fd0e8"; font.pixelSize: 10; font.letterSpacing: 1 }
                FridayBody {
                    anchors { left: parent.left; right: parent.right; top: parent.top; bottom: capBox.top; topMargin: 322; bottomMargin: 90 }
                    pose: root.poseOverride !== "" ? root.poseOverride : (root.state === "listening" ? "ouvindo" : (root.state === "thinking" ? "pensando" : "neutro"))
                    speaking: root.state === "speaking"
                    thinking: root.state === "thinking"
                    lookX: root.lookX
                    lookY: root.lookY
                }
                // miniatura da câmera (com os pontos da mão): ajuda a posicionar a mão no quadro
                Rectangle {
                    id: camBox
                    visible: root.camOn
                    anchors { right: parent.right; top: parent.top; rightMargin: 12; topMargin: 70 }
                    SequentialAnimation on opacity { loops: Animation.Infinite
                        NumberAnimation { from: 1.0; to: 0.82; duration: 140 } NumberAnimation { from: 0.82; to: 1.0; duration: 260 }
                        PauseAnimation { duration: 1800 } }
                    width: 160; height: 120; radius: 3; color: "#101820"; border.color: "#557fe6ff"; border.width: 1; clip: true
                    Image { anchors.fill: parent; cache: false; fillMode: Image.PreserveAspectCrop; source: "file:///tmp/friday-cam.jpg?" + root.camTick }
                    Text { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 3; text: "◈ REFLEXO HOLOGRÁFICO"; color: "#9fe6ff"; font.pixelSize: 8; font.letterSpacing: 1 }
                    Rectangle { anchors.fill: parent; color: "transparent"; border.color: "#cc7fe6ff"; border.width: 1 }
                }
                // o que ela ouviu (feedback imediato)
                Text {
                    visible: root.heardText !== "" && Date.now() - root.heardAt < 6000 && root.captionTick >= 0
                    anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 14; rightMargin: 182; topMargin: 74 }
                    text: "🎤 " + root.heardText; color: "#9fe6ff"; font.pixelSize: 12; font.italic: true; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight
                }
                // gesto reconhecido (feedback)
                Rectangle {
                    visible: root.gestureLabel !== ""
                    anchors { left: parent.left; top: parent.top; leftMargin: 14; topMargin: 152 }
                    width: gl.implicitWidth + 24; height: 26; radius: 13; color: "#cc062a44"; border.color: "#7fe6ff"; border.width: 1
                    Text { id: gl; anchors.centerIn: parent; text: "✋ " + root.gestureLabel.toUpperCase(); color: "#d6f6ff"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2 }
                }
                // medidores do sistema
                Row {
                    x: 12; y: 192; spacing: 14
                    Gauge { value: root.stCpu; label: "CPU" }
                    Gauge { value: root.stRam; label: "RAM" }
                    Gauge { value: root.stGpu; label: "GPU"; tint: "#9fffd0" }
                    Gauge { value: root.stVram; label: "VRAM"; tint: "#c9a8ff" }
                }
                Rectangle {
                    x: 10; y: 284; width: parent.width - 20; height: 30; radius: 6; color: "#55062038"; border.color: "#337fe6ff"; border.width: 1
                    Text { anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                           color: "#9fe6ff"; font.pixelSize: 11; font.letterSpacing: 1
                           text: root.stProx !== "" ? ("⏰  " + root.stProx) : ("GPU " + root.stTemp + "°C  ·  " + root.stTurnos + " conversas") }
                }
                // percepção: quem e o que ela está vendo
                Flow {
                    id: perc
                    anchors { left: parent.left; right: parent.right; bottom: eq.top; leftMargin: 12; rightMargin: 12; bottomMargin: 8 }
                    spacing: 6
                    Repeater {
                        model: root.camOn ? root.stPessoas.concat(root.stObjetos).slice(0, 8) : []
                        Rectangle {
                            height: 22; radius: 11; width: pt.implicitWidth + 18
                            color: index < root.stPessoas.length ? "#55208060" : "#55205080"
                            border.color: index < root.stPessoas.length ? "#8800ffc0" : "#667fe6ff"; border.width: 1
                            Text { id: pt; anchors.centerIn: parent; text: (index < root.stPessoas.length ? "👤 " : "▫ ") + modelData; color: "#e9f9ff"; font.pixelSize: 11 }
                        }
                    }
                }
                // equalizador de voz
                Row {
                    id: eq
                    anchors { horizontalCenter: parent.horizontalCenter; bottom: capBox.top; bottomMargin: 8 }
                    spacing: 3; height: 22
                    Repeater {
                        model: 28
                        Rectangle {
                            width: 4; anchors.bottom: parent.bottom; radius: 2
                            color: root.state === "speaking" ? "#7fffd0" : (root.state === "listening" ? "#ff9fd0" : "#4d9fb8")
                            height: {
                                root.eqTick
                                const amp = root.state === "speaking" ? 0.25 + root.mouth * 0.9 : (root.state === "listening" ? 0.35 : (root.state === "thinking" ? 0.2 : 0.07))
                                const env = 0.55 + 0.45 * Math.sin(index * 0.5 + root.eqTick * 0.35)
                                return Math.max(2, 22 * Math.min(1, amp * env * (0.6 + Math.random() * 0.8)))
                            }
                            Behavior on height { NumberAnimation { duration: 60 } }
                        }
                    }
                }
                // legenda da fala
                Rectangle {
                    id: capBox
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 10 }
                    height: root.captionVisible ? Math.min(150, capText.implicitHeight + 20) : 0
                    radius: 10; color: "#c0062038"; border.color: root.state === "speaking" ? "#aa7fffd0" : "#557fe6ff"; border.width: 1
                    clip: true
                    Behavior on height { NumberAnimation { duration: 180 } }
                    Text {
                        id: capText
                        x: 10; y: 10; width: parent.width - 20
                        text: root.caption; color: "#e9f9ff"; font.pixelSize: 14; wrapMode: Text.WordWrap
                        maximumLineCount: 6; elide: Text.ElideRight
                    }
                }
            }
        }
    }

    // ================== PALCO HOLOGRÁFICO (80% direitos; clique passa direto) ==================
    Variants {
        model: root.fridayOn ? Quickshell.screens : []
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { right: true; top: true; bottom: true }
            implicitWidth: Math.round(modelData.width * 0.80)
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "friday-stage"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}
            HoloStage {
                id: stage
                readonly property bool cheio: root.stageSpec !== null && root.stageSpec !== undefined && root.stageSpec.kind === "imagem" && root.stageSpec.tamanho !== "mao"
                x: cheio ? parent.width * 0.012 : parent.width * 0.04
                y: cheio ? parent.height * 0.02 : parent.height * 0.06
                width: cheio ? parent.width * 0.976 : parent.width * 0.92
                height: cheio ? parent.height * 0.96 : parent.height * 0.62
                Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Behavior on height { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Connections {
                    target: root
                    function onStageSeqChanged() { if (!root.stageSpec) stage.clear(); else if (root.stageOp === "update") stage.update(root.stageSpec); else stage.show(root.stageSpec) }
                }
            }
        }
    }


    // ================== "TINTA" HOLOGRÁFICA sobre as janelas reais (80% direitos; clique passa direto) ==================
    Variants {
        model: root.fridayOn ? Quickshell.screens : []
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { right: true; top: true; bottom: true }
            implicitWidth: Math.round(modelData.width * 0.80)
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "friday-coat"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}
            Item {
                anchors.fill: parent
                opacity: 0.72
                // véu azulado muito leve
                Rectangle { anchors.fill: parent; color: "#0a2a55ff"; opacity: 0.10 }
                // scanner: feixe horizontal (sobe) + feixe vertical (varre) + réguas nas bordas + leitura de dados
                Rectangle {
                    id: sweep; width: parent.width; height: 120
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#00bff3ff" }
                        GradientStop { position: 0.85; color: "#26bff3ff" }
                        GradientStop { position: 1.0; color: "#99d6f6ff" }
                    }
                    NumberAnimation on y { from: 1080; to: -120; duration: 6500; loops: Animation.Infinite }
                }
                Rectangle {
                    id: vsweep; height: parent.height; width: 90
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "#007fe6ff" }
                        GradientStop { position: 0.9; color: "#1a7fe6ff" }
                        GradientStop { position: 1.0; color: "#667fe6ff" }
                    }
                    NumberAnimation on x { from: -90; to: 1560; duration: 11000; loops: Animation.Infinite }
                }
                Repeater {                                   // régua superior e lateral
                    model: 78
                    Rectangle { x: index * 20; y: 0; width: 1; height: index % 5 === 0 ? 12 : 6; color: "#aa7fe6ff" }
                }
                Repeater {
                    model: 54
                    Rectangle { x: 0; y: index * 20; width: index % 5 === 0 ? 12 : 6; height: 1; color: "#aa7fe6ff" }
                }
                Repeater {
                    model: 54
                    Rectangle { x: parent.width - (index % 5 === 0 ? 12 : 6); y: index * 20; width: index % 5 === 0 ? 12 : 6; height: 1; color: "#aa7fe6ff" }
                }
                Column {
                    x: 22; y: 22; spacing: 2
                    Text { text: "◈ SCAN ATIVO"; color: "#d6f6ff"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 3; font.family: "monospace" }
                    Text { text: root.clockText + "  ·  PESSOAS " + root.stPessoas.length + "  ·  OBJETOS " + root.stObjetos.length
                           color: "#9fe6ff"; font.pixelSize: 10; font.family: "monospace" }
                    Text { text: "CPU " + Math.round(root.stCpu) + "%  GPU " + Math.round(root.stGpu) + "%  VRAM " + Math.round(root.stVram) + "%"
                           color: "#7fd0e8"; font.pixelSize: 10; font.family: "monospace" }
                }
                // cantos de projeção
                Repeater {
                    model: [[0, 0, 1, 1], [1, 0, -1, 1], [0, 1, 1, -1], [1, 1, -1, -1]]
                    Item {
                        x: modelData[0] === 0 ? 6 : parent.width - 6; y: modelData[1] === 0 ? 6 : parent.height - 6
                        Rectangle { x: modelData[2] > 0 ? 0 : -34; y: modelData[3] > 0 ? 0 : -2; width: 34; height: 2; color: "#cc7fe6ff" }
                        Rectangle { x: modelData[2] > 0 ? 0 : -2; y: modelData[3] > 0 ? 0 : -34; width: 2; height: 34; color: "#cc7fe6ff" }
                    }
                }
            }
        }
    }

    // ================== MOLDURA HOLOGRÁFICA SOBRE A JANELA REAL (clique passa direto; a janela continua operável) ==================
    Variants {
        model: root.fridayOn && root.wfOn ? Quickshell.screens : []
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { top: true; bottom: true; left: true; right: true }
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "friday-wframe"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}
            Item {
                id: wf
                x: root.wfX; y: root.wfY; width: root.wfW; height: root.wfH
                Behavior on x { NumberAnimation { duration: 140 } }
                Behavior on y { NumberAnimation { duration: 140 } }
                Behavior on width { NumberAnimation { duration: 140 } }
                Behavior on height { NumberAnimation { duration: 140 } }
                // brilho externo + borda
                Rectangle { anchors.fill: parent; anchors.margins: -12; color: "transparent"; border.color: "#227fe6ff"; border.width: 8; radius: 8 }
                Rectangle { anchors.fill: parent; anchors.margins: -6; color: "transparent"; border.color: "#557fe6ff"; border.width: 4; radius: 5 }
                Rectangle { anchors.fill: parent; color: "#0c3fa8ff"; border.color: "#ee9ff3ff"; border.width: 3; radius: 2
                    SequentialAnimation on opacity { loops: Animation.Infinite
                        NumberAnimation { from: 1.0; to: 0.62; duration: 900; easing.type: Easing.InOutSine }
                        NumberAnimation { from: 0.62; to: 1.0; duration: 900; easing.type: Easing.InOutSine } }
                }
                // véu holográfico + faixa horizontal tipo "tremor" de projeção
                Rectangle { anchors.fill: parent; color: "#122a7fff"; opacity: 0.55 }
                Repeater {
                    model: Math.ceil(wf.height / 4)
                    Rectangle { y: index * 4; width: wf.width; height: 1; color: "#1c9ff3ff" }
                }
                Item {
                    anchors.fill: parent; clip: true
                    Rectangle {
                        width: parent.width; height: 70
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#007fe6ff" }
                            GradientStop { position: 0.5; color: "#227fe6ff" }
                            GradientStop { position: 1.0; color: "#007fe6ff" }
                        }
                        NumberAnimation on y { from: -70; to: wf.height; duration: 3600; loops: Animation.Infinite }
                    }
                }
                // cantos reforçados
                Repeater {
                    model: [[0, 0, 1, 1], [1, 0, -1, 1], [0, 1, 1, -1], [1, 1, -1, -1]]
                    Item {
                        x: modelData[0] === 0 ? -3 : wf.width + 3; y: modelData[1] === 0 ? -3 : wf.height + 3
                        Rectangle { x: modelData[2] > 0 ? 0 : -40; y: modelData[3] > 0 ? 0 : -3; width: 40; height: 3; color: "#ffbff3ff" }
                        Rectangle { x: modelData[2] > 0 ? 0 : -3; y: modelData[3] > 0 ? 0 : -40; width: 3; height: 40; color: "#ffbff3ff" }
                    }
                }
                // etiqueta
                Rectangle {
                    x: 10; y: -26; height: 22; width: wtag.implicitWidth + 20; radius: 4; color: "#e0062a44"; border.color: "#aa7fe6ff"; border.width: 1
                    Text { id: wtag; anchors.centerIn: parent; text: "◈ HOLOGRAMA · " + root.wfTitulo; color: "#d6f6ff"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2 }
                }
            }
        }
    }

    // ================== CURSOR DO ASSISTENTE (sempre disponível) ==================
    Variants {
        model: Quickshell.screens
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { top: true; bottom: true; left: true; right: true }
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "prometheus-cursor"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}
            visible: root.curOn
            Item {
                id: cur
                x: root.curX; y: root.curY
                Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
                Behavior on y { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
                Rectangle { id: ripple; anchors.centerIn: parent; width: 40; height: 40; radius: width / 2
                    color: "transparent"; border.color: "#aaf0ff"; border.width: 3; opacity: 0
                    SequentialAnimation { id: rip
                        ParallelAnimation {
                            NumberAnimation { target: ripple; property: "width"; from: 40; to: 130; duration: 420; easing.type: Easing.OutCubic }
                            NumberAnimation { target: ripple; property: "height"; from: 40; to: 130; duration: 420; easing.type: Easing.OutCubic }
                            NumberAnimation { target: ripple; property: "opacity"; from: 0.95; to: 0; duration: 420 }
                        }
                    }
                }
                Connections { target: root; function onCurClickChanged() { rip.restart() } }
                Rectangle { anchors.centerIn: parent; width: 52; height: 52; radius: 26; color: "transparent"; border.color: "#000000"; border.width: 7; opacity: 0.55 }
                Rectangle { anchors.centerIn: parent; width: 52; height: 52; radius: 26; color: "#1f6fd0ff"; border.color: "#7fe6ff"; border.width: 3 }
                Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; color: "#ffffff"; border.color: "#001018"; border.width: 2 }
                Rectangle { x: -34; y: -1; width: 24; height: 3; color: "#7fe6ff" }
                Rectangle { x: 10; y: -1; width: 24; height: 3; color: "#7fe6ff" }
                Rectangle { x: -1; y: -34; width: 3; height: 24; color: "#7fe6ff" }
                Rectangle { x: -1; y: 10; width: 3; height: 24; color: "#7fe6ff" }
                Rectangle { x: 34; y: 24; width: lbl.implicitWidth + 14; height: lbl.implicitHeight + 6; radius: 5; color: "#d9061a2a"; border.color: "#7fe6ff"; border.width: 1
                    Text { id: lbl; anchors.centerIn: parent; text: "F.R.I.D.A.Y."; color: "#d6f6ff"; font.pixelSize: 12; font.bold: true; font.letterSpacing: 2 }
                }
            }
        }
    }
}
