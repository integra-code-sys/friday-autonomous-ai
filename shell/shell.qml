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
    // emoção do rosto: humor do daemon, sobreposto por 7 s pela reação à fala do dono
    property string humorFala: ""
    property double humorFalaAt: 0
    readonly property string humorRosto: (humorFala !== "" && Date.now() - humorFalaAt < 7000 && convTick >= 0) ? humorFala
        : (state === "thinking" && mood === "neutro" ? "pensativo" : mood)
    function reagirFala(t) {
        const s = String(t || "").toLowerCase(); let h = ""
        if (/(droga|merda|porra|raiva|[óo]dio|irritad|que saco|caralho)/.test(s)) h = "preocupado"
        else if (/(triste|chatead|cansad|p[ée]ssim|deu errado|n[ãa]o funciona|desanimad)/.test(s)) h = "triste"
        else if (/(uau|nossa|caramba|s[ée]rio\?|n[ãa]o acredito|incr[íi]vel)/.test(s)) h = "surpreso"
        else if (/(obrigad|valeu|[óo]timo|perfeito|legal|show|haha|kkk|adorei|parab[ée]ns|bom dia|boa noite)/.test(s)) h = "alegre"
        else if (/(\?|por que|porque|como |quem |qual |onde |quando )/.test(s)) h = "curioso"
        else if (/(urgente|cuidado|perigo|aten[çc][ãa]o|r[áa]pido)/.test(s)) h = "serio"
        if (h) { humorFala = h; humorFalaAt = Date.now() }
    }
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
    property bool holoWindowEnabled: true
    property int holoSnapTick: 0
    property real stCpu: 0
    property real stRam: 0
    property real stGpu: 0
    property real stVram: 0
    property int stTemp: 0
    property var stPessoas: []
    property var stObjetos: []
    property string stProx: ""
    property int stTurnos: 0
    property string stAlvo: ""
    property bool stPtzOn: false
    property bool stUsbOn: false
    property bool stNatOn: false
    property bool modeSeg: false
    property bool modePriv: false
    property bool modeSil: false
    property string toolText: ""
    property real toolAt: 0
    Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true
        onTriggered: { const d = new Date(); root.clockText = Qt.formatTime(d, "HH:mm:ss"); root.dateText = Qt.formatDate(d, "ddd, dd MMM").toUpperCase() } }
    Timer { interval: 70; running: root.fridayOn; repeat: true; onTriggered: root.eqTick++ }
    Timer { interval: 66; running: root.fridayOn; repeat: true; onTriggered: root.camTick++ }
    // palco holográfico (e-mail, figuras, janelas projetadas)
    property var stageSpec: null
    property int stageSeq: 0
    property string stageOp: "show"
    // cursor do assistente (overlay)
    property real curX: 960; property real curY: 540
    property bool curOn: false
    property string painelOp: ""
    property var painelData: ({})
    property int painelSeq: 0
    property int curClick: 0
    property string curAct: "move"
    Timer { id: curHide; interval: 6000; onTriggered: root.curOn = false }
    Timer { id: poseReset; onTriggered: root.poseOverride = "" }
    Timer { id: gestReset; interval: 1800; onTriggered: root.gestureLabel = "" }
    Timer { interval: 1000; running: true; repeat: true; onTriggered: root.captionTick++ }
    readonly property bool captionVisible: caption !== "" && (Date.now() - lastSpeech < 7000 || state === "speaking") && captionTick >= 0

    // ---- conversa (tela preta + chat) ----
    ListModel { id: chatModelObj }
    // ---- MODO DEV: eventos ao vivo e IDE Claude CLI (dev_ide.py) ----
    ListModel { id: devModelObj }
    ListModel { id: ideEventosObj }
    property bool devOn: false
    property bool devPausado: false
    property var ideEstado: null
    property var ideArvore: null
    property var ideArquivo: null
    property var ideDiff: null
    onDevOnChanged: {
        if (devOn) {
            celEnviar({ type: "ide", op: "estado" })
            celEnviar({ type: "ide", op: "arvore", rel: "" })
        }
    }
    function devPush(e) {
        if (devPausado || !e) return
        const ex = {}
        for (const k in e) if (["t", "hora", "fonte", "tipo", "texto", "type", "tipo_ev"].indexOf(k) < 0) ex[k] = e[k]
        devModelObj.append({ hora: String(e.hora || ""), fonte: String(e.fonte || ""), tipo: String(e.tipo || ""),
                             texto: String(e.texto || ""), extra: JSON.stringify(ex) })
        if (devModelObj.count > 600) devModelObj.remove(0, devModelObj.count - 600)
    }
    function devPedir(op) { celEnviar({ type: "dev", op: op || "hist", n: 300 }) }
    property alias chatModel: chatModelObj
    property double convAt: 0
    property bool convPinned: false
    property bool chatTyping: false
    property bool holoOpen: false
    property var pendingPanel: null
    property bool agenteOn: false
    property bool convSuppressed: false      // depois de revelar um app ou de dispensar: só volta com atividade nova
    property bool appForming: false
    property bool appFormed: false
    property bool appReady: false
    property int appSeq: 0
    property string appNome: ""
    property int convTick: 0
    Timer { interval: 500; running: root.fridayOn; repeat: true; onTriggered: root.convTick++ }
    readonly property bool heardFresh: heardText !== "" && Date.now() - heardAt < 4000 && convTick >= 0
    // chat só quando o dono abre (atalho / qs ipc call friday chat); na fala não aparece nada (vai para o plugin)
    readonly property bool convShown: fridayOn && !agenteOn && (convPinned || chatTyping) && convTick >= 0
    signal chatFocusRequested()
    function activity() { convAt = Date.now(); if (convSuppressed && !appForming) convSuppressed = false }
    function dismissConv() {
        convPinned = false; chatTyping = false; convAt = 0; convSuppressed = true
        if (holoOpen) { painelOp = "fechar"; painelSeq++ }
    }
    function sendChat(texto, arquivos) {
        if (!sockLoader.item || !online) return
        sockLoader.item.write(JSON.stringify({ type: "chat", text: texto, files: arquivos || [] }) + "
"); sockLoader.item.flush()
        activity()
    }
    // ---- espelho da tela do celular (holograma CelularHolo) ----
    property bool celOn: false
    property bool celSaindo: false            // mantém a janela durante a animação de saída
    property string celUrl: ""
    property int celW: 720
    property int celH: 1568
    signal celToque(real x, real y)
    Timer { id: celSaidaT; interval: 560; onTriggered: root.celSaindo = false }
    function celFechou() { if (celOn) { celOn = false; celSaindo = true; celSaidaT.restart() } }
    function celEnviar(obj) {
        if (!sockLoader.item || !online) return
        sockLoader.item.write(JSON.stringify(obj) + "\n"); sockLoader.item.flush()
    }
    function chatPush(role, text, files) {
        chatModelObj.append({ role: role, text: String(text || ""), files: (files || []).join("|"), t: Date.now() })
        while (chatModelObj.count > 200) chatModelObj.remove(0)
    }
    onAppFormedChanged: maybeReveal()
    onAppReadyChanged: maybeReveal()
    signal revelarApp()
    function maybeReveal() { if (appForming && appFormed && appReady) { revelarApp(); revealT.restart() } }
    function appRevelado() { revealT.stop(); if (!appForming) return; convSuppressed = true; convAt = 0; appEndT.restart() }
    Timer { id: revealT; interval: 3000; onTriggered: root.appRevelado() }      // garantia: se a revelação não avisar, sai mesmo assim
    Timer { id: appEndT; interval: 700; onTriggered: root.appForming = false }          // depois do fade: volta ao normal
    Timer { id: appFallback; interval: 12000; onTriggered: if (root.appForming) { root.appReady = true; root.appFormed = true } }
    IpcHandler {        // qs ipc call friday chat  -> abre a conversa com o campo de texto (atalho no niri)
        target: "friday"
        function chat(): void { root.convPinned = true; root.activity(); root.chatFocusRequested() }
        function fechar(): void { root.dismissConv() }
        function dev(): void { root.devPedir(root.devOn ? "desligar" : "ligar") }      // atalho do niri: qs ipc call friday dev
    }

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
                        if (m.type === "state") { if (m.state) root.state = m.state; if (m.mood) root.mood = m.mood
                            if (m.state === "listening") root.activity(); else if (m.state && m.state !== "idle") root.convAt = Date.now() }
                        if (m.type === "history") { chatModelObj.clear(); (m.items || []).forEach(it => chatModelObj.append({ role: it.role, text: String(it.text || ""), files: "", t: 0 })) }
                        if (m.type === "text" && (m.role === "user" || m.role === "assistant" || m.role === "tool")) {
                            root.chatPush(m.role, m.text, m.files); if (m.role === "user") { root.reagirFala(m.text); root.activity() } else if (m.role === "assistant") root.convAt = Date.now() }
                        if (m.type === "nano") {
                            if (m.op === "agente") root.agenteOn = !!m.on
                            else if (m.op === "app") root.appNome = String(m.nome || "")      // app abre direto (sem tela de nanopartículas)
                            else if (m.op === "app_pronto" || m.op === "app_falhou") root.appReady = true
                        }
                        if (m.type === "mouth") root.mouth = m.v > 0.05 ? Math.min(1, 0.10 + m.v * 1.30) : 0
                        if (m.type === "text" && m.role === "assistant") { root.caption = String(m.text || ""); root.lastSpeech = Date.now() }
                        if (m.type === "gaze") { root.present = m.present; root.lookX = m.present ? m.x : 0; root.lookY = m.present ? m.y : 0 }
                        if (m.type === "modes") { root.modeSeg = !!m.seguranca; root.modePriv = !!m.privacidade; root.modeSil = !!m.silencio }
                        if (m.type === "text" && m.role === "tool") { root.toolText = String(m.text || ""); root.toolAt = Date.now() }
                        if (m.type === "camera") root.camOn = !!m.on
                        if (m.type === "dev") root.devPush(m)
                        if (m.type === "dev_modo") root.devOn = !!m.on
                        if (m.type === "dev_hist") { devModelObj.clear(); (m.itens || []).forEach(e => root.devPush(e)) }
                        if (m.type === "ide_estado") root.ideEstado = m
                        if (m.type === "ide_arvore") root.ideArvore = m
                        if (m.type === "ide_arquivo") root.ideArquivo = m
                        if (m.type === "ide_diff") root.ideDiff = m
                        if (m.type === "ide_ev") {
                            ideEventosObj.append({
                                id: String(m.id || ""),
                                hora: String(m.hora || ""),
                                kind: String(m.kind || ""),
                                texto: String(m.texto || ""),
                                arquivo: String(m.arquivo || m.caminho || ""),
                                diff: String(m.diff || ""),
                                extra: JSON.stringify(m)
                            })
                            if (ideEventosObj.count > 600) ideEventosObj.remove(0, 1)
                        }
                        if (m.type === "friday_heard") { root.heardText = String(m.text || ""); root.heardAt = Date.now(); root.reagirFala(m.text); root.activity() }
                        if (m.type === "voice") root.micOn = !!m.on
                        if (m.type === "painel") { root.painelOp = String(m.op || ""); root.painelData = m.data || m.dados || {}; root.painelSeq++ }
                        if (m.type === "holo_frame") { root.wfOn = !!m.on; root.wfX = m.x || 0; root.wfY = m.y || 0; root.wfW = m.w || 0; root.wfH = m.h || 0; root.wfTitulo = String(m.titulo || "") }
                        if (m.type === "holo_window") { root.holoWindowEnabled = !!m.enabled }
                        if (m.type === "holo_snap") { root.holoSnapTick++ }
                        if (m.type === "stats") {
                            root.stCpu = m.cpu || 0; root.stRam = m.ram || 0; root.stGpu = m.gpu || 0; root.stVram = m.vram || 0; root.stTemp = m.temp || 0
                            root.stPessoas = m.pessoas || []; root.stObjetos = m.objetos || []; root.stProx = m.prox || ""; root.stTurnos = m.turnos || 0
                            root.stAlvo = String(m.alvo || "")
                            root.stPtzOn = !!m.ptz_on
                            root.stUsbOn = !!m.usb_on
                            root.stNatOn = !!m.nat_on
                        }
                        if (m.type === "friday_pose") root.setPose(m.pose || "", m.ttl || 2500)
                        if (m.type === "friday_gesture") {
                            root.gestureLabel = String(m.label || m.kind || "")
                            gestReset.restart()
                            if (m.pose) root.setPose(m.pose, m.ttl || 1800)
                        }
                        if (m.type === "holo") {
                            if (m.op !== "clear" && !m.spec && !root.stageSpec) return    // 19/10: show sem conteúdo abria o holograma vazio
                            root.stageOp = m.op || "show"
                            if (m.op === "clear") root.stageSpec = null
                            else if (m.spec) root.stageSpec = m.spec
                            root.stageSeq++
                        }
                        if (m.type === "conv") {
                            root.convPinned = !!m.open
                            if (m.open) { root.convSuppressed = false; root.activity() }
                            else root.convAt = Date.now()
                        }
                        if (m.type === "cel_tela") {
                            if (m.on) { root.celUrl = String(m.url || root.celUrl); root.celW = m.w || root.celW; root.celH = m.h || root.celH
                                root.celSaindo = false; root.celOn = true }
                            else root.celFechou()
                        }
                        if (m.type === "cel_toque") root.celToque(m.x || 0, m.y || 0)
                        if (m.type === "cursor") {
                            if (m.agent) {
                                root.curX = m.x; root.curY = m.y; root.curOn = true; curHide.restart()
                                if (m.act === "click") root.curClick++
                                root.curAct = m.act || "move"
                            }
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

    // ================== CONVERSA: tela preta + nanotecnologia + chat lateral (só enquanto conversamos) ==================
    // Só o chat lateral (com a transcrição do que ela entendeu): aparece quando ela ouve/pensa/fala, quando há mensagem
    // nova ou quando o dono digita; some ~12 s depois. Sem tela preta/nanopartículas. Some enquanto o agente usa mouse/teclado.
    Variants {
        model: root.fridayOn ? Quickshell.screens : []
        PanelWindow {
            id: convWin
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { left: true; top: true; bottom: true }
            implicitWidth: Math.round(modelData.width * 0.26)
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.namespace: "friday-conversa"
            // fixado (atalho do chat): teclado direto no campo; conversa por voz: só se clicar (não rouba o teclado dos apps)
            WlrLayershell.keyboardFocus: !root.convShown ? WlrKeyboardFocus.None : (root.convPinned ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.OnDemand)
            property Region rAll: Region { item: chat }
            property Region rNone: Region {}
            mask: root.convShown ? rAll : rNone

            readonly property real chatW: width
            Item {
                id: convRoot
                anchors.fill: parent
                opacity: root.convShown ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: root.convShown ? 380 : 650; easing.type: Easing.InOutQuad } }

                ChatPanel {
                    id: chat
                    width: convWin.chatW; height: parent.height
                    x: 0
                    Behavior on x { NumberAnimation { duration: 450; easing.type: Easing.InOutCubic } }
                    model: root.chatModel
                    mode: root.state; level: root.mouth
                    heard: root.heardText; heardFresh: root.heardFresh
                    online: root.online; pinned: root.convPinned
                    cpu: root.stCpu; ram: root.stRam; gpu: root.stGpu; vram: root.stVram
                    camTick: root.camTick; camOn: root.camOn
                    onSend: (texto, arquivos) => root.sendChat(texto, arquivos)
                    onCloseRequested: root.dismissConv()
                    onPinToggled: root.convPinned = !root.convPinned
                    onTypingChanged: { root.chatTyping = typing; root.convAt = Date.now() }
                }
                Shortcut { sequence: "Escape"; enabled: root.convShown; onActivated: root.dismissConv() }
                Timer { id: focusT; interval: 450; onTriggered: chat.focusInput() }        // espera o fade-in (item invisível não recebe foco)

                Connections { target: root; function onChatFocusRequested() { focusT.restart() } }
            }
        }
    }

    // ================== MODO DEV: IDE AUTÔNOMA CLAUDE CLI (DevIDE) ==================
    Variants {
        model: root.devOn ? Quickshell.screens : []
        PanelWindow {
            id: devWin
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { right: true; top: true; bottom: true }
            implicitWidth: Math.round(modelData.width * 0.62)
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.namespace: "friday-dev-ide"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
            DevIDE {
                anchors.fill: parent
                anchors.margins: 10
                online: root.online
                estado: root.ideEstado
                arvore: root.ideArvore
                arquivo: root.ideArquivo
                diffAtual: root.ideDiff
                eventos: ideEventosObj
                onEnviarCmd: obj => root.celEnviar(obj)
                onFechar: root.devPedir("desligar")
            }
        }
    }

    // ================== FUNDO ANIMADO (PainelStark, camada Bottom: sobre o wallpaper, atrás das janelas) ==================
    Variants {
        model: Quickshell.screens
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { left: true; right: true; top: true; bottom: true }
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Bottom
            WlrLayershell.namespace: "friday-core"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region { item: painel.hit }      // só a armadura recebe mouse (arrastar gira); o resto passa direto
            PainelStark {
                id: painel
                anchors.fill: parent
                mode: root.state
                level: root.mouth
                cpu: root.stCpu; ram: root.stRam; gpu: root.stGpu; vram: root.stVram; temp: root.stTemp
                online: root.online; clock: root.clockText; date: root.dateText
                pessoas: (root.stPessoas || []).length; objetos: (root.stObjetos || []).length
                listaPessoas: root.stPessoas || []; listaObjetos: root.stObjetos || []
                alvo: root.stAlvo
                ptzOnline: root.stPtzOn; usbOnline: root.stUsbOn; natOnline: root.stNatOn
                camTick: root.camTick; camOn: root.camOn
            }
        }
    }

    // ================== PAINÉIS DE APRESENTAÇÃO (clima/agenda/sistema/mídia; clique passa direto) ==================
    Variants {
        model: root.fridayOn ? Quickshell.screens : []
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { right: true; top: true; bottom: true }
            implicitWidth: Math.round(modelData.width * 0.80)
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.namespace: "friday-panels"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}
            TelasHolo {
                id: fpan
                anchors.fill: parent
                onClosed: { if (root.painelOp !== "fechar") { root.painelOp = "fechar"; root.painelSeq++ } }
                Connections {
                    target: root
                    function onPainelSeqChanged() {
                        if (root.painelOp === "fechar") fpan.hide()
                        else if (root.painelOp !== "transicao") fpan.show(root.painelOp, root.painelData)
                    }
                }
            }
        }
    }

    // ================== PALCO HOLOGRÁFICO (80% direitos; clique passa direto) ==================
    Variants {
        model: Quickshell.screens
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { left: true; right: true; top: true; bottom: true }
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "friday-stage"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}
            HoloStage {
                id: stage
                readonly property bool is3d: root.stageSpec !== null && root.stageSpec !== undefined && root.stageSpec.kind === "projecao_3d"
                readonly property bool cheio: root.stageSpec !== null && root.stageSpec !== undefined && root.stageSpec.kind === "imagem" && root.stageSpec.tamanho !== "mao"
                readonly property real esq: root.convShown ? Math.round(parent.width * 0.26) : 0       // não cobre o chat da conversa
                x: esq + (cheio ? (parent.width - esq) * 0.012 : (parent.width - esq) * 0.04)
                y: cheio ? parent.height * 0.02 : (is3d ? parent.height * 0.04 : parent.height * 0.06)
                width: cheio ? (parent.width - esq) * 0.976 : (parent.width - esq) * 0.92
                height: cheio ? parent.height * 0.96 : (is3d ? parent.height * 0.88 : parent.height * 0.62)
                Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Behavior on height { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                Component.onCompleted: {
                    if (root.stageSpec) {
                        if (root.stageOp === "update") stage.update(root.stageSpec);
                        else stage.show(root.stageSpec);
                    }
                }
                Connections {
                    target: root
                    function onStageSeqChanged() { if (!root.stageSpec) stage.clear(); else if (root.stageOp === "update") stage.update(root.stageSpec); else stage.show(root.stageSpec) }
                }
            }
            Rectangle {
                id: gestureBadge
                visible: opacity > 0.01
                opacity: root.gestureLabel !== "" ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 250; easing.type: Easing.InOutQuad } }
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 46
                width: Math.max(160, glTxt.implicitWidth + 36)
                height: 38
                radius: 19
                color: "#e6120804"
                border.color: "#ff7700"
                border.width: 1.5
                Row {
                    anchors.centerIn: parent
                    spacing: 8
                    Rectangle {
                        width: 14; height: 14; radius: 3
                        color: "transparent"
                        border.color: "#ffa033"
                        border.width: 1.5
                        anchors.verticalCenter: parent.verticalCenter
                        Rectangle {
                            width: 4; height: 4; radius: 2
                            color: "#ff7700"
                            anchors.centerIn: parent
                        }
                    }
                    Text {
                        id: glTxt
                        text: root.gestureLabel.toUpperCase()
                        color: "#ffeedb"
                        font.pixelSize: 12
                        font.bold: true
                        font.letterSpacing: 1.5
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }
    }




    // ================== JANELA HOLOGRÁFICA 100% PARTÍCULAS SOBRE A JANELA REAL ==================
    // Camada de conversão visual 100% holográfica monocromática azul/ciano (#00d2ff) composta de partículas.
    // Interativa: mask: Region {} garante 100% de passthrough para navegação com cursor, mouse e teclado.
    // Pode ser desligada a qualquer momento por comando de voz: "mudar janela para a real".
    Variants {
        model: root.fridayOn && root.wfOn ? Quickshell.screens : []
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { top: true; bottom: true; left: true; right: true }
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "friday-holowin"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}

            HoloAppWindow {
                id: holoApp
                winX: root.wfX
                winY: root.wfY
                winW: root.wfW
                winH: root.wfH
                titulo: root.wfTitulo
                active: root.holoWindowEnabled && root.wfOn
                snapTick: root.holoSnapTick
            }
        }
    }

    // ================== CELULAR AO VIVO (holograma em formato de aparelho, 60 FPS) ==================
    // Só o aparelho recebe mouse (mask); o resto da tela passa direto. Clique/arrasto/roda/teclas viram comandos no celular.
    Variants {
        model: (root.celOn || root.celSaindo) ? Quickshell.screens : []
        PanelWindow {
            required property var modelData
            screen: modelData
            color: "transparent"
            anchors { top: true; bottom: true; left: true; right: true }
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.namespace: "friday-celular"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region { item: celHolo }
            CelularHolo {
                id: celHolo
                height: Math.round(parent.height * 0.82)
                x: parent.width - width - Math.round(parent.width * 0.03)
                y: Math.round((parent.height - height) / 2)
                fonte: root.celUrl
                vidW: root.celW; vidH: root.celH
                ligado: root.celOn
                onTocar: (nx, ny, ms) => root.celEnviar({ type: "cel_toque_ui", x: nx, y: ny, ms: ms })
                onArrastar: (x0, y0, x1, y1) => root.celEnviar({ type: "cel_arrastar_ui", x0: x0, y0: y0, x1: x1, y1: y1 })
                onTecla: nome => root.celEnviar({ type: "cel_tecla_ui", tecla: nome })
                onFechar: { root.celEnviar({ type: "cel_tela_ui", on: false }); root.celFechou() }
                Connections { target: root; function onCelToque(x, y) { celHolo.toque(x, y) } }
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
                Behavior on x { NumberAnimation { duration: 60; easing.type: Easing.OutQuad } }
                Behavior on y { NumberAnimation { duration: 60; easing.type: Easing.OutQuad } }
                readonly property color corEstado: root.curAct === "perdida" ? "#ff5f6d" : root.curAct === "drag" ? "#3fdc8a"
                                                 : root.curAct === "punho" ? "#ffb547" : root.curAct === "rolar" ? "#c58bff" : "#7fe6ff"
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
                Rectangle { anchors.centerIn: parent; width: 52; height: 52; radius: 26; color: "#1f6fd0ff"; border.color: cur.corEstado; border.width: 3 }
                Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; color: "#ffffff"; border.color: "#001018"; border.width: 2 }
                Rectangle { x: -34; y: -1; width: 24; height: 3; color: "#7fe6ff" }
                Rectangle { x: 10; y: -1; width: 24; height: 3; color: "#7fe6ff" }
                Rectangle { x: -1; y: -34; width: 3; height: 24; color: "#7fe6ff" }
                Rectangle { x: -1; y: 10; width: 3; height: 24; color: "#7fe6ff" }
                Rectangle { x: 34; y: 24; width: lbl.implicitWidth + 14; height: lbl.implicitHeight + 6; radius: 5; color: "#d9061a2a"; border.color: cur.corEstado; border.width: 1
                    Text { id: lbl; anchors.centerIn: parent; color: "#d6f6ff"; font.pixelSize: 12; font.bold: true; font.letterSpacing: 2
                        text: ({"perdida": "SEM MÃO", "drag": "ARRASTANDO", "punho": "PARADO", "rolar": "ROLANDO", "click": "CLIQUE"})[root.curAct] || "F.R.I.D.A.Y." }
                }
            }
        }
    }
}
